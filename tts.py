"""MOSS-TTSD 语音合成：把回复文本转成语音，用 AstrBot 标准 Record 组件发送。

模型 fnlp/MOSS-TTSD-v0.5 走 SiliconFlow 的 /v1/audio/speech，
voice 格式为 "fnlp/MOSS-TTSD-v0.5:<音色>"。
可用音色：anna / alex / bella / claire / david / diana。

参照社区 astrbot_plugin_tts_llm 的做法：分段合成 wav，再用
event.chain_result([Comp.Record(file=path)]) 交给平台适配器发送。
"""
from __future__ import annotations

import re
import uuid
import wave
from pathlib import Path

import httpx

try:
    from .bridge import BrowserError
except ImportError:  # 独立测试时没有包上下文
    class BrowserError(Exception):
        pass

API_URL = 'https://api.siliconflow.cn/v1/audio/speech'
# 实测对比：
#   fnlp/MOSS-TTSD-v0.5       对话式，克隆时会带出参考音频的气口和"嗯/哇"填充词，
#                             长文本必须切段（切段后拼接还会变速），开头杂音明显。
#   FunAudioLLM/CosyVoice2-0.5B 零样本克隆，单次合成整段（14s 长句实测一遍过），
#                             几乎不产生填充词，ASR 回读与原文一致，默认用它。
MODEL_ID = 'FunAudioLLM/CosyVoice2-0.5B'
LEGACY_MODEL_ID = 'fnlp/MOSS-TTSD-v0.5'
DEFAULT_VOICE = 'anna'
VOICES = ('anna', 'alex', 'bella', 'claire', 'david', 'diana')
# 单段合成上限；过长的回复按句切分再拼接，避免一次塞太多导致语气走样。
# 一次合成越长，前后语气越容易走样；但切太碎又会每段换一种语调。
# 实测 320~400 字一段、最多 3 段是音色最稳的区间。
MAX_CHARS = 380


def clean_for_speech(text):
    """去掉不该念出来的痕迹：表情标记、链接、代码块、修饰符。"""
    value = str(text or '')
    value = re.sub(r'&&[^&]{1,40}&&', ' ', value)
    value = re.sub(r'```.*?```', ' ', value, flags=re.S)
    value = re.sub(r'https?://\S+', ' ', value)
    value = re.sub(r'[*_~]{2,}', '', value)
    # 音符/装饰符不能进合成：CosyVoice2 会把 ♪ 当成音节念出来，
    # 听感就是"到某一句突然多出一个重复的声音"。
    value = re.sub(r'[♪♫♬♩♬🎵🎶]+', ' ', value)
    value = re.sub(r'[~～]{1,}', ' ', value)
    value = re.sub(r'\s+', ' ', value)
    return value.strip()


def split_for_speech(text, limit=MAX_CHARS):
    """按句子边界切分，避免在句中截断。"""
    text = clean_for_speech(text)
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts, buffer = [], ''
    for piece in re.split(r'(?<=[。！？；!?;\n])', text):
        if len(buffer) + len(piece) <= limit:
            buffer += piece
        else:
            if buffer.strip():
                parts.append(buffer.strip())
            buffer = piece
    if buffer.strip():
        parts.append(buffer.strip())
    return parts[:3]


def merge_wavs(paths, target):
    """把多段 wav 按顺序拼成一个。

    旧实现直接把各段 PCM 帧写进第一段的 WAV 头里；只要某一段的采样率或声道数
    与第一段不同，拼出来的文件就会变速、变调、后半段听不清。这里统一先重采样
    到同一格式再拼接，保证整条语音音色和语速一致。
    """
    if len(paths) == 1:
        Path(paths[0]).replace(target)
        return str(target)
    import subprocess
    # 统一规格：MOSS-TTSD 输出 24k 单声道；统一成 24k/16bit/mono 再拼。
    normalized = []
    for index, path in enumerate(paths):
        piece = Path(path).with_name(Path(path).stem + '-norm.wav')
        try:
            subprocess.run(
                ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                 '-i', str(path), '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(piece)],
                check=True, timeout=60,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            normalized.append(str(piece))
        except Exception:
            normalized.append(str(path))
    with wave.open(normalized[0], 'rb') as first:
        params = first.getparams()
    with wave.open(str(target), 'wb') as out:
        out.setparams(params)
        for path in normalized:
            try:
                with wave.open(path, 'rb') as src:
                    if (src.getnchannels(), src.getframerate(), src.getsampwidth()) == (
                            params.nchannels, params.framerate, params.sampwidth):
                        out.writeframes(src.readframes(src.getnframes()))
                    else:
                        # 兜底：格式仍不一致就补齐静音，宁可少一段也不要变速噪声
                        continue
            except (wave.Error, EOFError):
                continue
    for piece in normalized:
        if piece not in paths:
            try:
                Path(piece).unlink(missing_ok=True)
            except OSError:
                pass
    return str(target)


class TTSD:
    def __init__(self, owner):
        self.owner = owner

    @property
    def config(self):
        return self.owner.config

    def _api_key(self):
        key = str(self.config.get('tts_api_key') or '').strip()
        if key:
            return key
        try:
            provider = self.owner.context.get_provider_by_id('siliconflow/qwen3-omni')
            if provider:
                keys = provider.provider_config.get('key') or []
                if isinstance(keys, str):
                    keys = [keys]
                if keys and keys[0]:
                    return str(keys[0])
        except Exception:
            pass
        return ''

    def available(self):
        if not self.config.get('tts_enabled', False):
            return False, '语音合成未开启。'
        if not self._api_key():
            return False, '语音合成缺少 API Key，请先填写或配置 SiliconFlow 模型。'
        voice = str(self.config.get('tts_voice') or DEFAULT_VOICE)
        # 配了参考音频就走进零样本克隆，此时不需要（也不能）再传预置音色。
        if not str(self.config.get('tts_ref_audio') or '').strip() and voice not in VOICES:
            return False, '语音音色不支持：' + voice
        return True, ''

    async def synthesize(self, text):
        """返回本地 wav 路径；失败抛 BrowserError。"""
        ok, reason = self.available()
        if not ok:
            raise BrowserError(reason)
        # CosyVoice2 单次就能稳定合成整段，不需要切段（切段反而更容易跳调）。
        chunks = [str(text).strip()] if MODEL_ID != LEGACY_MODEL_ID else split_for_speech(text)
        if not chunks:
            raise BrowserError('这条回复没有可朗读的内容。')
        voice = str(self.config.get('tts_voice') or DEFAULT_VOICE)
        ref_audio = str(self.config.get('tts_ref_audio') or '').strip()
        ref_text = str(self.config.get('tts_ref_text') or '').strip()
        media = Path(self.owner.media_dir)
        media.mkdir(parents=True, exist_ok=True)
        timeout = float(self.config.get('tts_timeout_seconds', 60))
        pieces = []
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                for index, chunk in enumerate(chunks):
                    payload = {
                        'model': MODEL_ID,
                        'input': ('[S1]' + chunk) if MODEL_ID == LEGACY_MODEL_ID else chunk,
                        'response_format': 'wav',
                    }
                    if MODEL_ID != LEGACY_MODEL_ID:
                        # 44.1kHz 保留更多高频细节（齿音、气声），听感比 24k 清楚；
                        # 语速略降到 0.9，中文咬字更完整。
                        payload['sample_rate'] = int(self.config.get('tts_sample_rate') or 44100)
                        payload['speed'] = float(self.config.get('tts_speed') or 0.9)
                    if ref_audio:
                        # 接口规定 voice 与 references 互斥（同时传会报 20053）。
                        payload['references'] = [{'audio': ref_audio, 'text': ref_text or ''}]
                    elif MODEL_ID == LEGACY_MODEL_ID:
                        payload['voice'] = MODEL_ID + ':' + voice
                    response = await client.post(API_URL, json=payload,
                        headers={'Authorization': 'Bearer ' + self._api_key()})
                    if response.status_code != 200:
                        raise BrowserError('语音合成接口返回 ' + str(response.status_code)
                            + '：' + response.text[:160])
                    data = response.content
                    if not data or len(data) < 1000:
                        raise BrowserError('语音合成没有返回有效音频。')
                    piece = media / ('tts-' + uuid.uuid4().hex + '-' + str(index) + '.wav')
                    piece.write_bytes(data)
                    pieces.append(str(piece))
            target = media / ('tts-' + uuid.uuid4().hex + '.wav')
            merged = merge_wavs(pieces, target)
            return merged
        finally:
            for piece in pieces:
                try:
                    Path(piece).unlink(missing_ok=True)
                except OSError:
                    pass


ASR_URL = 'https://api.siliconflow.cn/v1/audio/transcriptions'
ASR_MODEL = 'XingChenAGI/XingChenASR-V3.2-Ultra'


async def verify_speech(api_key, wav_path, expected, timeout=40):
    """用 ASR 回读刚合成的音频，和原文对比，判断是否"听得懂"。

    克隆音色偶尔会跑调或吞字，用户听到的就是一串听不懂的声音。
    这里在发出去之前先自检一遍，相似度太低就换参数重试。
    """
    import httpx
    try:
        data = Path(wav_path).read_bytes()
    except OSError:
        return 0.0
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(ASR_URL,
                headers={'Authorization': 'Bearer ' + api_key},
                files={'file': ('check.wav', data, 'audio/wav')},
                data={'model': ASR_MODEL})
        if response.status_code != 200:
            return 0.0
        heard = str(response.json().get('text') or '')
    except Exception:
        return 0.0
    import re as _re
    def norm(value):
        return _re.sub(r'[^\w\u4e00-\u9fff]', '', str(value or ''))
    a, b = norm(expected), norm(heard)
    if not a or not b:
        return 0.0
    # 用最长公共子序列占比近似"听懂率"，比逐字相等更宽容同音字
    previous = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            current[j] = previous[j - 1] + 1 if a[i - 1] == b[j - 1] else max(previous[j], current[j - 1])
        previous = current
    return previous[len(b)] / float(len(a))


async def synthesize_reply(owner, text):
    return await TTSD(owner).synthesize(text)


# ── 旋律演唱 ──────────────────────────────────────────────
# MOSS-TTSD 只能"念"：没有音高控制。这里把已合成的语音按歌词音节切成若干段，
# 每段用 rubberband 变调到目标音高（时长不变），再拼回去，得到真实的旋律起伏。
# 半音表：以 C 为 0。
NOTE_BASE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

# 预置旋律：每项为 (音名, 八度) 序列，取值是相对整首曲子主音的半音数。
MELODIES = {
    'twinkle': [-9, -9, -5, -5, -2, -2, -5,   # 一闪一闪亮晶晶
                -4, -4, -2, -2, 0, 0, -2],    # 满天都是小星星（C 大调）
    'birthday': [-1, -1, 0, -1, 3, 2,
                 -1, -1, 0, -1, 4, 3,
                 -1, -1, 8, 5, 3, 2, 0],
    'lullaby': [0, 2, 4, 2, 0, -3, 0,
                2, 4, 5, 4, 2, 0, 2],
    'cheer': [0, 4, 7, 4, 0, 4, 7, 12, 7, 4, 0],
}
DEFAULT_MELODY = 'twinkle'


def pick_melody(text):
    """从歌词里挑旋律：命中关键字就用对应曲子，否则用默认轻快小调。"""
    value = str(text or '')
    if any(word in value for word in ('生日', '祝你')): return 'birthday'
    if any(word in value for word in ('睡', '晚安', '摇篮')): return 'lullaby'
    if any(word in value for word in ('加油', '高兴', '开心', '冲')): return 'cheer'
    return DEFAULT_MELODY


def _syllable_count(text):
    """中文按字、英文按音节粗分：用来决定每个音要唱多久。"""
    import re as _re
    cleaned = _re.sub(r'[\s♪♫♬♩♬,，。.！!？?、；;：:~～\-—]', '', str(text or ''))
    return max(1, min(64, len(cleaned)))


def _wav_duration(path):
    with wave.open(str(path), 'rb') as handle:
        rate = handle.getframerate() or 24000
        return handle.getnframes() / float(rate)


async def sing_with_melody(ffmpeg, wav_path, melody_name, syllables):
    """把一段语音改编成旋律演唱，返回新 wav 路径；失败返回原路径。"""
    import asyncio as _asyncio
    import math as _math
    from pathlib import Path as _Path

    notes = MELODIES.get(melody_name) or MELODIES[DEFAULT_MELODY]
    source = _Path(wav_path)
    total = _wav_duration(source)
    if total <= 0.2:
        return str(source)

    # 音符不够就循环铺满歌词，多出来的音截断
    plan = [notes[i % len(notes)] for i in range(max(1, syllables))]
    step = total / len(plan)
    if step < 0.08:                      # 音节太多时合并，避免每段过短听不出音高
        keep = max(1, int(total / 0.09))
        plan = plan[:keep]
        step = total / len(plan)

    pieces = []
    for index, semitone in enumerate(plan):
        start = index * step
        piece = source.with_name(source.stem + '-n' + str(index) + '.wav')
        ratio = _math.pow(2.0, semitone / 12.0)
        args = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
                '-ss', '%.3f' % start, '-t', '%.3f' % (step + 0.02),
                '-i', str(source)]
        # 半音偏移为 0 时不需要变调，省一次滤波
        if abs(semitone) >= 1:
            args += ['-af', 'rubberband=pitch=%.6f' % ratio]
        args += ['-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', str(piece)]
        try:
            proc = await _asyncio.create_subprocess_exec(
                *args, stdout=_asyncio.subprocess.DEVNULL, stderr=_asyncio.subprocess.DEVNULL)
            await _asyncio.wait_for(proc.wait(), 20)
            if piece.is_file() and piece.stat().st_size > 200:
                pieces.append(str(piece))
            else:
                pieces.append('')
        except Exception:
            pieces.append('')

    if not any(pieces):
        return str(source)

    merged = source.with_name(source.stem + '-melody.wav')
    with wave.open(str(merged), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(24000)
        for piece in pieces:
            if not piece:
                continue
            try:
                with wave.open(piece, 'rb') as src:
                    out.writeframes(src.readframes(src.getnframes()))
            except (wave.Error, EOFError):
                continue
    for piece in pieces:
        if piece:
            try:
                _Path(piece).unlink(missing_ok=True)
            except OSError:
                pass
    if merged.is_file() and merged.stat().st_size > 2000:
        return str(merged)
    return str(source)


# ── 唱歌：哼唱 → RVC 换音色 ───────────────────────────────
# RVC 不改旋律，只换音色。所以"她唱歌"的正确链路是：
#   源音频（你哼的，或数据集里的真实演唱干声）
#     → RVC 换成助手音色 → 带旋律的"她在唱"
# 注意：TTS 生成的念白走这条路依然是念白，必须先有旋律。

async def sing_with_rvc(owner, source_audio):
    """把一段带旋律的源音频换成目标音色。"""
    from .rvc import convert_voice
    return await convert_voice(owner, source_audio)


# 曲库文件名 → 用户会说出的曲名
SONG_ALIASES = {
    # 数据集自带（她本人真实演唱干声）
    'yu-ai': '雨爱',
    'pipa-qu': '琵琶曲',
    'yan-wu-xie': '燕无歇',
    'pengyou-de-jiu': '朋友的酒',
    'bianhao-89757-a': '编号89757',
    'bianhao-89757-b': '编号89757',
    # 甲自己录的干声（纯 ffmpeg 处理，无 AI）
    'yu-yi': '唯一',
    'ta-bu-dong': '他不懂',
    'mei-tian': '每天每天',
    'nothing': 'Nothing’s Gonna Change My Love For You',
    'shuo-hao': '说好不哭',
}


def _alias_for(owner, stem):
    """曲名优先级：ledger 里用户导入时填的名字 > 内置别名表。"""
    try:
        saved = owner.ledger.get('song-alias:' + stem, '')
        if saved:
            return str(saved)
    except Exception:
        pass
    return SONG_ALIASES.get(stem, '')


def list_song_titles(owner):
    """当前曲库里实际能唱的歌名，用来告诉模型别说错。"""
    from pathlib import Path
    folder = Path(str(owner.config.get('singing_library_dir') or '')).expanduser()
    if not str(folder) or not folder.is_dir():
        return []
    titles = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() == '.wav' and '-clip' not in path.stem:
            label = _alias_for(owner, path.stem)
            if label and label not in titles:
                titles.append(label)
    return titles


def pick_builtin_song(owner):
    """从内置演唱干声库里随机挑一首，作为"她真的在唱"的音源。"""
    import random
    from pathlib import Path
    folder = Path(str(owner.config.get('singing_library_dir') or '')).expanduser()
    if not str(folder) or not folder.is_dir():
        return ''
    # 只认原始干声：排除本插件生成的 clip/mp4/rvc 中间产物，
    # 否则会出现「拿裁剪结果再裁剪」的套娃，最后切到一片静音。
    songs = [p for p in sorted(folder.iterdir())
             if p.is_file() and p.suffix.lower() == '.wav'
             and '-clip' not in p.stem and '-rough' not in p.stem
             and not p.stem.startswith('rvc-')]
    if not songs:
        return ''
    # 点歌：用户消息里出现曲名就放那首，优先于"固定曲目"配置。
    asked = str(getattr(owner, '_singing_request', '') or '')
    for song in songs:
        label = _alias_for(owner, song.stem)
        if label and label in asked:
            return str(song)
    wanted = str(owner.config.get('singing_library_pick') or '').strip()
    for song in songs:
        if song.name == wanted:
            return str(song)
    return str(random.choice(songs))
