# -*- coding: utf-8 -*-
"""把用户录的干声整理成语音库可用的素材。

手机/电脑录的音频通常是 44.1k/48k 立体声、带房间底噪、首尾有停顿，
甚至会带伴奏。这里统一处理成插件需要的规格：
  24k 单声道 / 去静音 / 响度归一 -16 LUFS / 去爆音
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

TARGET_RATE = 24000


async def _run(cmd, timeout=180):
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(process.communicate(), timeout)
    return process.returncode, (err or b'').decode('utf-8', 'ignore')


async def prepare_dry_vocal(ffmpeg, source, target, monologue=False):
    """把任意录音整理成干净的演唱干声。

    Args:
        ffmpeg: ffmpeg 可执行文件路径。
        source: 原始录音。
        target: 输出 wav 路径。
        monologue: True 时按"说话"处理（保留较长停顿）。

    Returns:
        (成功标志, 说明文字)
    """
    src = Path(source)
    if not src.is_file():
        return False, '录音文件不存在。'

    # 演唱去静音留 0.45 秒气口，说话留 0.8 秒，避免把人声切碎
    pause = '0.8' if monologue else '0.45'
    filters = (
        # 单声道下混 + 重采样
        'aformat=channel_layouts=mono,'
        # 去掉 70Hz 以下的桌面震动与喷麦
        'highpass=f=70,'
        # 脉冲爆音与削波修复
        'adeclick=window=55:overlap=75:threshold=2:burst=2,'
        'adeclip=window=55:overlap=75:threshold=10,'
        # 轻度降噪，保住齿音
        'afftdn=nf=-30:nr=6,'
        # 抽掉句间空白，让演唱连续
        f'silenceremove=stop_periods=-1:stop_duration={pause}:stop_threshold=-40dB:detection=peak,'
        # 响度对齐短视频常用水平
        'loudnorm=I=-16:TP=-1.5:LRA=11'
    )
    code, err = await _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', str(src), '-af', filters,
                            '-ac', '1', '-ar', str(TARGET_RATE),
                            '-c:a', 'pcm_s16le', str(target)])
    if code != 0 or not Path(target).is_file():
        return False, '处理失败：' + err[:200]
    size = Path(target).stat().st_size
    if size < 2000:
        return False, '处理结果为空，录音可能没有有效人声。'
    return True, f'完成，输出 {size / 1024:.0f} KB'


# ── 伴奏压制 ──────────────────────────────────────────────
# 录音里带一点点伴奏和原声时，纯降噪压不干净（伴奏和嗓音都在人声频段）。
# 设备只有 7 核 / 5.5G 内存，跑 Demucs 不现实，所以用 ffmpeg 做三件事：
#   1) 中置声道提取：立体声里人声多在中置，伴奏多在两侧
#   2) 非局部均值降噪：anlmdn 压宽带残留
#   3) 频谱门限：afftdn 收掉稳态底噪
# 对"一点点伴奏"效果不错，对"伴奏很响"的录音只能减轻、无法根除。

async def strip_accompaniment(ffmpeg, source, target, strength='medium'):
    """压制录音里的伴奏与背景原声。

    Args:
        ffmpeg: ffmpeg 可执行文件。
        source: 输入录音。
        target: 输出文件。
        strength: light / medium / strong，越大残留越少，但人声也越干。

    Returns:
        (成功标志, 说明)
    """
    src = Path(source)
    if not src.is_file():
        return False, '录音文件不存在。'

    # 注意：anlmdn 在 proot/bionic 上会 malloc 崩溃（实测 munmap_chunk() invalid pointer），
    # arnndn 需要外部 .rnnn 模型文件（设备上没有），两个都不能用。
    # 可靠组合：中置提取压两侧伴奏 + afftdn 频谱门限 + EQ 强化人声。
    if strength == 'strong':
        centre, gate, eq = '0.88', 'afftdn=nf=-22:nr=26', 'equalizer=f=250:t=q:w=1.0:g=-3,equalizer=f=3500:t=q:w=1.2:g=3'
    elif strength == 'light':
        centre, gate, eq = '0.60', 'afftdn=nf=-34:nr=6', 'equalizer=f=4000:t=q:w=1.5:g=1'
    else:
        centre, gate, eq = '0.75', 'afftdn=nf=-28:nr=16', 'equalizer=f=250:t=q:w=1.2:g=-2,equalizer=f=4000:t=q:w=1.5:g=2'

    filters = (
        'aformat=channel_layouts=stereo,'
        'stereotools=balance_out=1:slev=' + centre + ','
        'aformat=channel_layouts=mono,'
        'highpass=f=80,'
        'adeclick=window=55:overlap=75:threshold=2:burst=2,'
        'adeclip=window=55:overlap=75:threshold=10,'
        + gate + ','
        # 收一点浑浊的中低频、提一点齿音区，让人声更突出
        + eq + ','
        'loudnorm=I=-16:TP=-1.5:LRA=11'
    )
    code, err = await _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                            '-i', str(src), '-af', filters,
                            '-ac', '1', '-ar', str(TARGET_RATE),
                            '-c:a', 'pcm_s16le', str(target)])
    if code != 0 or not Path(target).is_file():
        return False, '伴奏压制失败：' + err[:200]
    if Path(target).stat().st_size < 2000:
        return False, '伴奏压制后没有有效人声。'
    return True, strength + ' 强度处理完成'
