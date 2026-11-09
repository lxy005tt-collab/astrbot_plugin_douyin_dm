# -*- coding: utf-8 -*-
"""录音入库批处理（纯信号处理，不调用任何 AI 服务）。

流程：
  1) 立体声 → 中置提取（压两侧伴奏）
  2) 高通 80Hz 去低频轰鸣
  3) adeclick / adeclip 修爆音与削波
  4) afftdn 频谱门限降底噪
  5) silenceremove 抽掉句间空白，让演唱连续
  6) EQ 去浑浊、提齿音
  7) loudnorm 响度对齐 -16 LUFS
  8) 输出 24kHz 单声道 16bit WAV

全部由 ffmpeg 完成，不联网、不用模型、结果可复现。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FFMPEG = os.environ.get('MIMI_FFMPEG', 'ffmpeg')
FFPROBE = os.environ.get('MIMI_FFPROBE', 'ffprobe')

# 每首歌的伴奏压制强度，按侧/中声道能量比预先测定
JOBS = [
    ('weiyi.wav',    'yu-yi',       '唯一',      'light'),
    ('tabudong.wav', 'ta-bu-dong',  '他不懂',    'light'),
    ('meitiand.wav', 'mei-tian',    '每天每天',  'medium'),
    ('nothing.wav',  'nothing',     'Nothing’s Gonna Change My Love For You', 'light'),
    ('shuohao.wav',  'shuo-hao',    '说好不哭',  'medium'),
]

INBOX = Path(os.environ.get('MIMI_SINGING_INBOX', 'media/inbox'))
OUT = Path(os.environ.get('MIMI_SINGING_DIR', 'media/singing'))

LEVELS = {
    'light':  dict(centre='0.60', gate='afftdn=nf=-34:nr=6',
                   eq='equalizer=f=4000:t=q:w=1.5:g=1'),
    'medium': dict(centre='0.75', gate='afftdn=nf=-28:nr=16',
                   eq='equalizer=f=250:t=q:w=1.2:g=-2,equalizer=f=4000:t=q:w=1.5:g=2'),
    'strong': dict(centre='0.88', gate='afftdn=nf=-22:nr=26',
                   eq='equalizer=f=250:t=q:w=1.0:g=-3,equalizer=f=3500:t=q:w=1.2:g=3'),
}


def probe(path):
    out = subprocess.run([FFPROBE, '-v', 'error', '-show_entries',
                          'stream=channels,sample_rate:format=duration',
                          '-of', 'json', str(path)],
                         capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
        stream = (data.get('streams') or [{}])[0]
        return {'channels': stream.get('channels', 0),
                'rate': stream.get('sample_rate', '0'),
                'duration': float(data.get('format', {}).get('duration') or 0)}
    except Exception:
        return {'channels': 0, 'rate': '0', 'duration': 0.0}


def build_filter(level, has_stereo):
    cfg = LEVELS[level]
    parts = []
    if has_stereo:
        parts.append('aformat=channel_layouts=stereo')
        parts.append('stereotools=balance_out=1:slev=' + cfg['centre'])
    parts += [
        'aformat=channel_layouts=mono',
        'highpass=f=80',
        'adeclick=window=55:overlap=75:threshold=2:burst=2',
        'adeclip=window=55:overlap=75:threshold=10',
        cfg['gate'],
        'silenceremove=stop_periods=-1:stop_duration=0.45:stop_threshold=-40dB:detection=peak',
        cfg['eq'],
        'loudnorm=I=-16:TP=-1.5:LRA=11',
    ]
    return ','.join(parts)


def process(src, dst, level):
    info = probe(src)
    if info['duration'] <= 0:
        return False, '无法读取音频信息'
    filt = build_filter(level, info['channels'] >= 2)
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error', '-y',
           '-i', str(src), '-af', filt,
           '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(dst)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, (result.stderr or '')[:200]
    if not dst.is_file() or dst.stat().st_size < 2000:
        return False, '输出为空'
    return True, 'ok'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = []
    for filename, stem, title, level in JOBS:
        src = INBOX / filename
        dst = OUT / (stem + '.wav')
        if not src.is_file():
            report.append({'file': filename, 'ok': False, 'msg': '缺少源文件'})
            print('MISS %s' % filename)
            continue
        info = probe(src)
        ok, msg = process(src, dst, level)
        entry = {'file': filename, 'title': title, 'stem': stem,
                 'level': level, 'src_duration': round(info['duration'], 1),
                 'channels': info['channels'], 'ok': ok, 'msg': msg}
        if ok:
            out_info = probe(dst)
            entry['out_duration'] = round(out_info['duration'], 1)
            entry['out_kb'] = round(dst.stat().st_size / 1024)
            print('OK   %-14s %-5s %6.1fs -> %6.1fs  %dKB' % (
                stem, level, info['duration'], out_info['duration'], entry['out_kb']))
        else:
            print('FAIL %-14s %s' % (stem, msg))
        report.append(entry)
    Path('/host-tmp/import-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('DONE')


if __name__ == '__main__':
    main()
