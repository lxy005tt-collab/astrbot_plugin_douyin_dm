"""Grounded browsing and comment receipts shared by both entry points."""
import asyncio
import hashlib
import json
import time
from urllib.parse import urlsplit
from .errors import BrowserError
from .media import prepare_video
from .perception import transcribe_video

class ActivityEngine:
    def __init__(self,owner,perceive=transcribe_video):
        self.owner=owner;self.perceive=perceive;self.lock=asyncio.Lock()

    async def watch(self,url='',prefer_images=False,info_only=False):
        async with self.lock:
            owner=self.owner
            seen=[key.split(':',1)[1] for (key,) in owner.ledger.db.execute("SELECT key FROM state WHERE key LIKE 'activity:%'").fetchall()]
            source=await owner.browser.call('browse',{'url':url,'seen_ids':seen[-100:],
                'prefer_images':prefer_images,'info_only':info_only},timeout=180)
            if info_only:return {'source':source}
            if source.get('path'):
                source['path']=await prepare_video(source['path'],owner.media_dir,owner.ffmpeg_binary,
                    float(owner.config.get('max_model_video_mb',18)),expected_duration=source.get('duration'),ffprobe_binary=owner.ffprobe_binary)
            source['url']=source.pop('source','')
            source['origin']='self_browse'
            transcript=await self.perceive(owner,[source])
            record={'verified':True,'post_id':source.get('post_id'),'url':source['url'],'kind':source.get('kind','video'),
                    'transcript':transcript,'watched_at':time.time(),'persona_scope':getattr(owner,'persona',None),
                    'owner_scope':owner.binding['peer']['key'] if getattr(owner,'binding',None) else None}
            if not record['post_id']:raise BrowserError('没有确认作品标识，未登记观看记录。')
            owner.ledger.put('activity:'+record['post_id'],record)
            return {'record':record,'source':source}

    async def comment(self,url,text):
        owner=self.owner
        if not owner.config.get('allow_public_comments',False):raise BrowserError('评论开关未开启。')
        import re
        post_id=re.search(r'/(?:video|note)/(\d{12,24})',urlsplit(url).path)
        parsed=urlsplit(url);record=owner.ledger.get('activity:'+post_id[1]) if post_id else None
        if (parsed.scheme!='https' or not (parsed.hostname=='douyin.com' or str(parsed.hostname).endswith('.douyin.com'))
                or parsed.username or parsed.password or not record or record.get('verified') is not True):
            raise BrowserError('先实际读取这条作品，再根据内容评论。')
        text=str(text).strip()
        if not text or len(text)>200:raise BrowserError('评论正文应为 1～200 字。')
        key='comment:'+post_id[1]+':'+hashlib.sha256(text.encode()).hexdigest()
        previous=owner.ledger.get(key)
        if previous:return {**previous,'already_submitted':True}
        owner.ledger.put(key,{'state':'unknown','post_id':post_id[1],'text':text,'submitted_at':time.time()})
        try:receipt=await owner.browser.call('comment',{'url':url,'text':text},timeout=90)
        except Exception:
            # A timeout can occur after the site accepted a comment. Keep the
            # unknown marker so the same text is never submitted automatically.
            raise
        owner.ledger.put(key,{**receipt,'text':text,'submitted_at':time.time()})
        return receipt
