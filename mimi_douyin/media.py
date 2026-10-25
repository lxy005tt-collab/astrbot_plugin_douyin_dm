from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from .errors import BrowserError

async def inspect_video(file,ffmpeg,ffprobe_binary=None):
    candidate=Path(ffmpeg).with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')
    ffprobe=ffprobe_binary or (str(candidate) if candidate.is_file() else 'ffprobe')
    process=await asyncio.create_subprocess_exec(ffprobe,'-v','error','-show_entries',
        'stream=codec_type:format=duration','-of','json',str(file),
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
        creationflags=0x08000000 if os.name=='nt' else 0)
    try:output,_=await asyncio.wait_for(process.communicate(),20)
    except BaseException:
        if process.returncode is None:process.kill();await process.wait()
        raise
    if process.returncode:raise BrowserError('下载的文件无法作为视频读取。')
    info=json.loads(output)
    if not any(s.get('codec_type')=='video' for s in info.get('streams',[])):
        raise BrowserError('下载的文件没有视频画面，未把单独音轨当作完整视频。')
    return float(info.get('format',{}).get('duration',0))


async def prepare_video(path,media_dir,ffmpeg,max_mb,expected_duration=None,ffprobe_binary=None):
    file=Path(path).resolve()
    if not file.is_relative_to(Path(media_dir).resolve()) or not file.is_file():
        raise BrowserError('视频文件不在本插件的媒体目录中。')
    duration=await inspect_video(file,ffmpeg,ffprobe_binary)
    if expected_duration and abs(duration-expected_duration)>max(2,expected_duration*0.02):
        raise BrowserError('取得的视频时长与原视频不符，没有把片段当作完整视频。')
    if file.stat().st_size<=max_mb*1024*1024:return str(file)
    output=file.with_name(file.stem+'-model.mp4')
    process=await asyncio.create_subprocess_exec(ffmpeg,'-hide_banner','-loglevel','error','-i',str(file),
        '-vf','scale=640:640:force_original_aspect_ratio=decrease','-c:v','libx264','-crf','32',
        '-preset','veryfast','-c:a','aac','-b:a','48k','-movflags','+faststart','-y',str(output),
        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,
        creationflags=0x08000000 if os.name=='nt' else 0)
    try:code=await asyncio.wait_for(process.wait(),120)
    except BaseException:
        if process.returncode is None:process.kill();await process.wait()
        raise
    if code or not output.is_file() or output.stat().st_size>max_mb*1024*1024:
        raise BrowserError('完整视频仍超过模型输入大小设置，未截断视频冒充已看完。')
    compressed_duration=await inspect_video(output,ffmpeg,ffprobe_binary)
    if abs(compressed_duration-duration)>max(2,duration*0.02):
        raise BrowserError('压缩后的视频时长不完整。')
    return str(output)


