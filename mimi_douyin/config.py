import json
import os
from pathlib import Path
from .cache import CACHE_DEFAULTS

DEFAULTS={
    **CACHE_DEFAULTS,
    'enabled':True,'auto_reply_enabled':False,'whitelist_enabled':True,'private_whitelist':[],
    'media_dir':'','browser_profile':'','browser_type':'自动选择','browser_headless':False,
    'node_binary':'','playwright_package':'','browser_executable':'','ffmpeg_binary':'','ffprobe_binary':'',
    'poll_seconds':4,'merge_seconds':3,'max_download_mb':64,'max_model_video_mb':18,'max_post_images':30,
    'video_provider_id':'video','video_input_mode':'转述为文本','video_separate_audio':True,
    'video_transcription_timeout_seconds':90,'video_transcription_prompt':'',
    'api_base':'','api_key':'','model':'','video_api_base':'','video_api_key':'','video_model':'',
    'system_prompt':'你是 Mimi，和用户自然聊天。只依据实际读到的内容，不编造浏览、观看或评论经历。',
    'autonomy_enabled':False,'allow_public_comments':False,'autonomy_interval_minutes':30,
}

class Settings(dict):
    def __init__(self,data_dir):
        self.data_dir=Path(data_dir).resolve();self.data_dir.mkdir(parents=True,exist_ok=True)
        self.path=self.data_dir/'config.json'
        saved=json.loads(self.path.read_text('utf-8-sig')) if self.path.exists() else {}
        super().__init__({**DEFAULTS,**saved})
        if not self.path.exists():self.save_config()

    def save_config(self):
        temporary=self.path.with_name('config.json.new')
        temporary.write_text(json.dumps(self,ensure_ascii=False,indent=2),encoding='utf8')
        if os.name!='nt':temporary.chmod(0o600)
        temporary.replace(self.path)

    def public(self):
        return {**{key:value for key,value in self.items() if key not in ('api_key','video_api_key')},
                'api_key_configured':bool(self.get('api_key')),'video_api_key_configured':bool(self.get('video_api_key'))}
