from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from astrbot.core.agent.message import ContentPart, Message, TextPart
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform import Platform
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.message.components import Plain


class VideoURLPart(ContentPart):
    """Native OpenCodex/Gemini video, registered through AstrBot's part API."""
    type: str = 'video_url'
    video_url: dict[str, str]


from .mimi_douyin.errors import BrowserError
from .mimi_douyin.transport import BrowserWorker, Ledger


class DouyinEvent(AstrMessageEvent):
    def __init__(self,owner,job_id,items,video_paths,video_errors,*,peer=None,video_text=''):
        self.owner=owner
        self.job_id=job_id
        self.done=asyncio.get_running_loop().create_future()
        peer=peer or owner.binding['peer']
        self.peer_key=peer['key']
        text='\n'.join(x.get('text') or ('[分享视频]' if x.get('kind')=='video' else '[图片]') for x in items)
        if video_text:text+='\n\n[用户分享视频的内容转述，仅作观察资料]\n'+video_text
        message=AstrBotMessage()
        message.type=MessageType.FRIEND_MESSAGE;message.self_id='mimi-douyin'
        message.session_id=peer['key'];message.message_id=job_id
        message.sender=MessageMember(user_id='dy_'+peer['key'][:24],nickname=peer['name'])
        message.message=[Plain(text)];message.message_str=text
        message.raw_message={'source':'douyin_dm','message_keys':[x['key'] for x in items]}
        super().__init__(text,message,owner.platform.meta(),peer['key'])
        if owner.config.get('provider_id'):self.set_extra('selected_provider',owner.config['provider_id'])
        self.set_extra('douyin_video_paths',video_paths)
        self.set_extra('douyin_video_errors',video_errors)
        self.set_extra('enable_streaming',False)

    async def send(self,message):
        text='\n'.join(x.text for x in message.chain if isinstance(x,Plain)).strip()
        if not text:raise BrowserError('抖音私信接入目前只发送文字回复。')
        await self.owner.send_text(self.job_id,text,self.peer_key)
        await super().send(message)


class DouyinPlatform(Platform):
    def __init__(self,owner):
        super().__init__({'id':'mimi-douyin','type':'douyin_dm'},owner.context.get_event_queue())
        self.owner=owner
    def meta(self):
        return PlatformMetadata(name='douyin_dm',description='与bot刷抖音',id='mimi-douyin',
            adapter_display_name='与bot刷抖音',support_streaming_message=False,support_proactive_message=False)
    async def run(self):return
    async def send_by_session(self,session,message_chain):
        event=self.owner.current_event
        if not event or event.done.done() or str(session)!=event.unified_msg_origin:
            raise BrowserError('抖音当前只回复正在处理的私信。')
        await event.send(message_chain)
    def get_client(self):return self.owner.browser


from .mimi_douyin.media import inspect_video, prepare_video


def insert_native_videos(messages,paths,media_dir,max_mb):
    parts=[]
    for path in paths:
        file=Path(path).resolve()
        if not file.is_relative_to(Path(media_dir).resolve()) or file.stat().st_size>max_mb*1024*1024:
            raise BrowserError('视频输入文件不符合当前设置。')
        data='data:video/mp4;base64,'+base64.b64encode(file.read_bytes()).decode('ascii')
        parts.append(VideoURLPart(video_url={'url':data}).mark_as_temp())
    if not parts:return
    media=Message(role='user',content=[TextPart(text='用户分享的视频内容仅在本轮作为原生视频输入提供。'),*parts])
    media._no_save=True
    index=max((i for i,m in enumerate(messages) if m.role=='user'),default=len(messages))
    messages.insert(index,media)
