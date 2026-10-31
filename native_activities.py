"""AstrBot permissions and activity evidence; no independent timers."""
import json
from .bridge import BrowserError
from .watch_memory import remember_video
from .mimi_douyin.activities import ActivityEngine
from .video_transcription import transcribe_video,format_transcript

def allowed(owner,event):
    if not owner.config.get('enabled',True) or not owner.config.get('autonomy_enabled',False):return False
    if event.is_private_chat() and event.is_admin():return True
    return bool(owner.binding and event.unified_msg_origin==owner.session_id())

class _MemoryEvent:
    def __init__(self,event,transcript):self.event=event;self.transcript=transcript
    def __getattr__(self,name):return getattr(self.event,name)
    def get_extra(self,key,default=None):
        return self.transcript if key=='douyin_video_transcript' else self.event.get_extra(key,default)

async def watch(owner,event,url=''):
    if not allowed(owner,event):raise BrowserError('此会话未启用抖音自主浏览。')
    async with owner.action_lock:
        await owner._open_browser()
        result=await owner.activities.watch(url)
        if result.get('skipped'):
            source=result['source']
            skipped=event.get_extra('douyin_skipped_posts',[])
            skipped.append({'post_id':source.get('post_id'),'reason':source.get('reason')})
            event.set_extra('douyin_skipped_posts',skipped[-10:])
            return json.dumps({**source,'verified':False,
                'next_step':'换一个视频：可再次调用 douyin_watch_recommended，并将 url 留空以选择另一条推荐作品。不要继续下载本条，也不要把它当作已看过。'},ensure_ascii=False)
        record=result['record'];text=format_transcript(record['transcript'])
        event.set_extra('douyin_activity_receipt',{**record,'excerpt':text})
        facts=event.get_extra('activity_report_tools',[])
        facts.append({'tool':'douyin_watch_recommended','ok':True,'arguments':{'url':record['url']},
            'result_excerpt':text[:6000],'limit':'已读取实际完整视频及音轨，或图文全部原图；不证明真实停留时长。'})
        event.set_extra('activity_report_tools',facts[-8:])
        memory=None
        if owner.config.get('remember_videos',False):
            try:memory=await remember_video(owner,_MemoryEvent(event,record['transcript']),[result['source']],record['watched_at'])
            except BrowserError:memory={'state':'local_activity_saved'}
        return json.dumps({'verified':True,'post_id':record['post_id'],'url':record['url'],'kind':record['kind'],
            'observation':text,'memory':memory,'limit':'只按实际转述聊天；未执行评论。'},ensure_ascii=False)

async def comment(owner,event,url,text):
    if not allowed(owner,event):raise BrowserError('此会话未启用抖音自主浏览。')
    async with owner.action_lock:
        await owner._open_browser()
        receipt=await owner.activities.comment(url,text)
        facts=event.get_extra('activity_report_tools',[])
        facts.append({'tool':'douyin_comment_watched','ok':receipt.get('state')=='sent','arguments':{'url':url},
                      'result_excerpt':json.dumps(receipt,ensure_ascii=False),'limit':'只有 state=sent 且有 comment_id 才确认发表评论。'})
        event.set_extra('activity_report_tools',facts[-8:])
        return json.dumps(receipt,ensure_ascii=False)
