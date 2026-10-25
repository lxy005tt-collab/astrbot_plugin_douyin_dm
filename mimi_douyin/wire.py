"""Model payloads independent of the host application's message classes."""
import base64
from pathlib import Path
from typing import Any
from pydantic import BaseModel, PrivateAttr
from .errors import BrowserError

class ContentPart(BaseModel):
    type:str
    def mark_as_temp(self):return self

class TextPart(ContentPart):
    type:str='text'
    text:str

class VideoURLPart(ContentPart):
    type:str='video_url'
    video_url:dict[str,str]

class ImageURLPart(ContentPart):
    type:str='image_url'
    image_url:dict[str,str]

class Message(BaseModel):
    role:str
    content:Any
    _no_save:bool=PrivateAttr(default=False)

def insert_native_videos(messages,paths,media_dir,max_mb):
    parts=[]
    for value in paths:
        file=Path(value).resolve()
        if not file.is_relative_to(Path(media_dir).resolve()) or not file.is_file() or file.stat().st_size>max_mb*1024*1024:
            raise BrowserError('视频输入文件不符合当前设置。')
        data='data:video/mp4;base64,'+base64.b64encode(file.read_bytes()).decode('ascii')
        parts.append(VideoURLPart(video_url={'url':data}))
    if parts:messages.insert(0,Message(role='user',content=[TextPart(text='以下是实际取得的视频文件。'),*parts]))
