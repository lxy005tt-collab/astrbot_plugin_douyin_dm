"""Native plugin setup page: server-side directory chooser and dependency setup."""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from astrbot.api.web import request

from .bridge import BrowserError
from .runtime import RuntimeEnvironment, browse_directories
from .mimi_douyin.cache import media_settings,validate_media_settings


class SetupAPI:
    def __init__(self,owner):
        self.owner=owner
        self.install_task=None
        self.install_state={'running':False,'message':'尚未安装','component':''}

    def routes(self):
        return [('setup/status',self.status,['GET']),('setup/browse',self.browse,['POST']),
                ('setup/save',self.save,['POST']),('setup/install',self.install,['POST']),
                ('setup/install/status',self.install_status,['GET'])]

    async def status(self):
        data=await self.owner.runtime.diagnose()
        memory=self.owner.context.get_registered_star('astrbot_plugin_livingmemory')
        data.update({'bot':self.owner.status(),'install':self.install_state,
            'models':{'chat':self.owner.config.get('provider_id') or '跟随 AstrBot 当前配置',
                      'video':self.owner.config.get('video_provider_id') or '尚未选择视频模型'},
            'optional_memory_available':bool(memory and memory.activated),
            'autonomy_enabled':bool(self.owner.config.get('autonomy_enabled',False)),
            'allow_public_comments':bool(self.owner.config.get('allow_public_comments',False)),
            **media_settings(self.owner.config),'cache_cleanup':self.owner.cache.status()})
        return {'status':'ok','data':data}

    async def browse(self):
        payload=await request.json(default={})
        try:
            value=payload.get('path','') if isinstance(payload,dict) else ''
            if not isinstance(value,str):raise BrowserError('目录路径应为文本。')
            return {'status':'ok','data':await asyncio.to_thread(browse_directories,value)}
        except (BrowserError,OSError) as exc:return {'status':'error','message':str(exc)}

    async def save(self):
        payload=await request.json(default={})
        if not isinstance(payload,dict) or not isinstance(payload.get('media_dir'),str):
            return {'status':'error','message':'请填写视频保存目录，留空使用默认目录。'}
        try:
            async with self.owner.action_lock:
                if self.owner.job_lock.locked():raise BrowserError('正在处理消息或视频，请等本轮结束后保存目录。')
                async with self.owner.job_lock:
                    raw=payload['media_dir'].strip()
                    kind=payload.get('browser_type',self.owner.config.get('browser_type','自动选择'))
                    if kind not in ('自动选择','Edge','Chrome','Chromium'):raise BrowserError('浏览器类型不受支持。')
                    flags={key:payload[key] for key in ('autonomy_enabled','allow_public_comments') if key in payload}
                    preferences=validate_media_settings(payload)
                    if any(not isinstance(value,bool) for value in flags.values()):raise BrowserError('活动开关应为布尔值。')
                    proposed=RuntimeEnvironment({**self.owner.config,'media_dir':raw,**preferences},self.owner.data_dir)
                    directory=proposed.media_dir
                    directory.mkdir(parents=True,exist_ok=True)
                    probe=directory/('.mimi-write-check-'+uuid4().hex)
                    try:
                        with probe.open('x',encoding='utf-8') as file:file.write('')
                    finally:
                        if probe.exists():probe.unlink()
                    old_dir=self.owner.media_dir
                    running=bool(self.owner.browser.process and self.owner.browser.process.returncode is None)
                    old_limit=self.owner.config.get('max_download_mb',64)
                    next_limit=preferences.get('max_download_mb',old_limit)
                    if running:await self.owner.browser.call('configure',{'media_dir':str(directory),'max_download_mb':next_limit})
                    previous=dict(self.owner.config)
                    self.owner.config['media_dir']=raw
                    self.owner.config['browser_type']=kind
                    self.owner.config.update(flags)
                    self.owner.config.update(preferences)
                    try:self.owner._save_config()
                    except Exception:
                        self.owner.config.clear();self.owner.config.update(previous)
                        if running:await self.owner.browser.call('configure',{'media_dir':old_dir,'max_download_mb':old_limit})
                        raise
                    self.owner.browser.config=self.owner.runtime.settings()
                    self.owner.cache.settings_changed()
                    return {'status':'ok','data':{'media_dir':str(directory),'setting':raw,
                        'browser_reopen_needed':running and previous['browser_type']!=kind,
                        **media_settings(self.owner.config),'cache_cleanup':self.owner.cache.status(),
                        'message':'设置已保存，下载上限已生效。已有缓存和登录资料保持原位。'}}
        except (BrowserError,OSError,ValueError) as exc:return {'status':'error','message':str(exc)}

    async def install(self):
        payload=await request.json(default={})
        component=payload.get('component') if isinstance(payload,dict) else None
        if component not in ('playwright','chromium'):return {'status':'error','message':'请选择 Playwright 或 Chromium。'}
        if self.install_task and not self.install_task.done():return {'status':'ok','data':self.install_state}
        self.install_state={'running':True,'component':component,'message':'正在安装，请保持网络可用。','started_at':time.time()}
        async def run():
            try:
                result=await self.owner.runtime.install(component)
                self.install_state={**self.install_state,'running':False,'success':True,'message':'安装完成。','result':result}
            except asyncio.CancelledError:
                self.install_state={**self.install_state,'running':False,'success':False,'message':'安装已中止。'}
                raise
            except Exception as exc:
                self.install_state={**self.install_state,'running':False,'success':False,'message':str(exc)[:500]}
        self.install_task=asyncio.create_task(run())
        return {'status':'ok','data':self.install_state}

    async def install_status(self):return {'status':'ok','data':self.install_state}

    async def terminate(self):
        if self.install_task and not self.install_task.done():
            self.install_task.cancel()
            await asyncio.gather(self.install_task,return_exceptions=True)
