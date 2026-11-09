# -*- coding: utf-8 -*-
"""RVC 歌声换音色：把「人哼的旋律」换成助手的音色。

思路：RVC 只做音色转换，不改旋律/节奏。所以要"她唱歌"，必须先有一段
带旋律的源音频（你哼的、或数据集中现成的演唱干声），再换成她的音色。

支持两条通道：
  replicate  zsxkib/realistic-voice-cloning   $0.038/次（打包价，1~5 分钟内同价）
  eachlabs   rvc-v2                           $0.0002475/处理秒（短片段更划算）
"""
from __future__ import annotations

import asyncio
import base64
import json
import uuid
from pathlib import Path

import httpx

try:
    from .bridge import BrowserError
except ImportError:
    class BrowserError(Exception):
        pass

REPLICATE_MODEL = 'zsxkib/realistic-voice-cloning'
REPLICATE_API = 'https://api.replicate.com/v1'
EACHLABS_API = 'https://api.eachlabs.ai/v1/prediction'
# RVC 内置音色里没有"助手"，所以默认走 CUSTOM + 自训练模型的下载地址。
DEFAULT_F0_METHOD = 'rmvpe'


async def _download(url, target, timeout=180):
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        async with client.stream('GET', url) as response:
            if response.status_code != 200:
                raise BrowserError('音频下载失败：HTTP ' + str(response.status_code))
            with open(target, 'wb') as handle:
                async for chunk in response.aiter_bytes(65536):
                    handle.write(chunk)
    if not Path(target).is_file() or Path(target).stat().st_size < 1000:
        raise BrowserError('下载到的音频为空。')
    return str(target)


def _pick_url(output):
    """Replicate 的输出可能是 str / list / dict，统一取出音频地址。"""
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        return _pick_url(output[0])
    if isinstance(output, dict):
        for key in ('output', 'audio', 'url', 'file'):
            if output.get(key):
                return _pick_url(output[key])
    return ''


class RVC:
    def __init__(self, owner):
        self.owner = owner

    @property
    def config(self):
        return self.owner.config

    def _channel(self):
        return str(self.config.get('rvc_channel') or 'replicate').strip().lower()

    def _token(self, channel):
        if channel == 'eachlabs':
            return str(self.config.get('eachlabs_api_key') or '').strip()
        return str(self.config.get('replicate_api_token') or '').strip()

    def available(self):
        channel = self._channel()
        if not self._token(channel):
            label = 'Eachlabs' if channel == 'eachlabs' else 'Replicate'
            return False, f'尚未填写 {label} 的 API Token。'
        if channel not in ('replicate', 'eachlabs'):
            return False, 'RVC 通道只能是 replicate 或 eachlabs。'
        return True, ''

    async def convert(self, source_audio):
        """把 source_audio 换成目标音色，返回本地 wav/mp3 路径。"""
        ok, reason = self.available()
        if not ok:
            raise BrowserError(reason)
        source = Path(str(source_audio))
        if not source.is_file() or source.stat().st_size < 1000:
            raise BrowserError('待转换的源音频不存在或为空。')

        channel = self._channel()
        pitch = int(self.config.get('rvc_pitch_change') or 0)
        index_rate = float(self.config.get('rvc_index_rate') or 0.5)
        protect = float(self.config.get('rvc_protect') or 0.33)
        media = Path(self.owner.media_dir)
        media.mkdir(parents=True, exist_ok=True)
        target = media / ('rvc-' + uuid.uuid4().hex + '.wav')
        timeout = float(self.config.get('rvc_timeout_seconds') or 300)

        if channel == 'eachlabs':
            url = await self._eachlabs(source, pitch, index_rate, protect, timeout)
        else:
            url = await self._replicate(source, pitch, index_rate, protect, timeout)
        if not url:
            raise BrowserError('RVC 没有返回音频地址。')
        return await _download(url, str(target), timeout=timeout)

    async def _upload_replicate(self, path, token, timeout):
        """Replicate 的文件接口：先拿 upload URL，PUT 上传，返回可访问地址。"""
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                REPLICATE_API + '/files',
                headers={'Authorization': 'Bearer ' + token},
                json={'content_type': 'audio/wav', 'file_name': Path(path).name},
            )
            if response.status_code not in (200, 201):
                raise BrowserError('Replicate 文件登记失败：' + response.text[:160])
            info = response.json()
            upload_url = info.get('upload_url') or (info.get('urls') or {}).get('put')
            serving = (info.get('urls') or {}).get('get') or info.get('url')
            if not upload_url:
                raise BrowserError('Replicate 未返回上传地址。')
            data = Path(path).read_bytes()
            put = await client.put(upload_url, content=data,
                                   headers={'Content-Type': 'audio/wav'})
            if put.status_code not in (200, 201):
                raise BrowserError('Replicate 文件上传失败：HTTP ' + str(put.status_code))
            return serving or ''

    async def _replicate(self, source, pitch, index_rate, protect, timeout):
        token = self._token('replicate')
        model_url = str(self.config.get('rvc_model_url') or '').strip()
        model_name = str(self.config.get('rvc_model_name') or 'CUSTOM').strip()
        media_url = await self._upload_replicate(str(source), token, timeout)
        if not media_url:
            raise BrowserError('Replicate 上传后没有拿到文件地址。')

        payload = {
            'version': str(self.config.get('replicate_model_version') or '').strip() or None,
            'input': {
                'song_input': media_url,
                'rvc_model': 'CUSTOM' if model_url else model_name,
                'pitch_change': pitch,
                'index_rate': index_rate,
                'protect': protect,
                'output_format': 'wav',
            },
        }
        if model_url:
            payload['input']['custom_rvc_model_download_url'] = model_url
        if not payload['version']:
            raise BrowserError('请在设置中填写 Replicate 模型的 version 哈希。')

        async with httpx.AsyncClient(timeout=timeout) as client:
            created = await client.post(REPLICATE_API + '/predictions',
                headers={'Authorization': 'Bearer ' + token}, json=payload)
            if created.status_code not in (200, 201):
                raise BrowserError('Replicate 任务创建失败：' + created.text[:200])
            job = created.json()
            poll = (job.get('urls') or {}).get('get') or (REPLICATE_API + '/predictions/' + job['id'])
            for _ in range(int(timeout / 2)):
                await asyncio.sleep(2)
                status = await client.get(poll, headers={'Authorization': 'Bearer ' + token})
                data = status.json()
                state = data.get('status')
                if state == 'succeeded':
                    return _pick_url(data.get('output'))
                if state in ('failed', 'canceled'):
                    raise BrowserError('RVC 任务失败：' + str(data.get('error'))[:200])
        raise BrowserError('RVC 任务超时。')

    async def _eachlabs(self, source, pitch, index_rate, protect, timeout):
        token = self._token('eachlabs')
        model_url = str(self.config.get('rvc_model_url') or '').strip()
        media = Path(self.owner.media_dir)
        upload = media / ('rvc-src-' + uuid.uuid4().hex + '.wav')
        upload.write_bytes(Path(source).read_bytes())
        audio_b64 = base64.b64encode(upload.read_bytes()).decode('ascii')
        try:
            upload.unlink(missing_ok=True)
        except OSError:
            pass
        payload = {
            'model': 'rvc-v2',
            'input': {
                'song_input': 'data:audio/wav;base64,' + audio_b64,
                'rvc_model': 'CUSTOM' if model_url else 'Squidward',
                'pitch_change': pitch,
                'index_rate': index_rate,
                'filter_radius': int(self.config.get('rvc_filter_radius') or 3),
                'rms_mix_rate': float(self.config.get('rvc_rms_mix_rate') or 0.25),
                'f0_method': DEFAULT_F0_METHOD,
                'protect': protect,
                'output_format': 'wav',
            },
        }
        if model_url:
            payload['input']['custom_rvc_model_download_url'] = model_url
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(EACHLABS_API,
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
                json=payload)
            if response.status_code not in (200, 201):
                raise BrowserError('Eachlabs 调用失败：' + response.text[:200])
            data = response.json()
            for key in ('output', 'audio', 'url', 'result'):
                value = data.get(key)
                if isinstance(value, str) and value.startswith('http'):
                    return value
                if isinstance(value, list) and value and isinstance(value[0], str):
                    return value[0]
        return ''


async def convert_voice(owner, source_audio):
    return await RVC(owner).convert(source_audio)
