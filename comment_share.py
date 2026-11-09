"""读取私信里「分享的评论」卡片，并识别评论图片/表情包或聊天图片。

抖音的分享评论消息在 DOM 里混在视频卡片中，结构和普通作品分享不同：
外层带 MessageItemCommentShare 类名，React parsedContent (aweType: 10500)
携带 comment_id、comment_user_name、comment、comment_content_type (1=文字, 2=图片, 3=表情包/GIF)、
comment_url、audio_duration、aweme_title、itemId。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from io import BytesIO
import re

import httpx
from .mimi_douyin.wire import ImageURLPart, Message, TextPart
from .bridge import BrowserError
from .video_transcription import _Owner

logger = logging.getLogger(__name__)

COMMENT_HINT = re.compile(r'分享\s*@?|的评论|来自视频')


def is_comment_share(item):
    """判断一条消息是否为分享评论卡片。"""
    if not isinstance(item, dict):
        return False
    if item.get('comment_share'):
        return True
    text = str(item.get('text') or '')
    cls = str(item.get('className') or '')
    if 'CommentShare' in cls:
        return True
    return bool(re.search(r'分享\s*@[^\n]+\s*\n?的评论', text)) or ('的评论' in text and '来自视频' in text)


def split_comment_card(item):
    """把卡片拆成结构化字段：作者、来源视频、正文、媒体。优先使用 dom.mjs 提取的 comment_share。"""
    cs = item.get('comment_share') if isinstance(item, dict) else None
    text = str(item.get('text') or '').replace('\u200b', '').strip()
    if isinstance(cs, dict) and (cs.get('author') or cs.get('text') or cs.get('media_url') or cs.get('aweme_id')):
        content_type = cs.get('content_type') or 1
        media_url = str(cs.get('media_url') or '')
        if not media_url and content_type in (2, 3):
            media_url = str(cs.get('dom_cover_img') or '')
        return {
            'kind': 'comment_share',
            'comment_id': str(cs.get('comment_id') or ''),
            'author': str(cs.get('author') or ''),
            'source': '视频',
            'text': str(cs.get('text') or '').strip(),
            'content_type': content_type,
            'media_url': media_url,
            'is_emoji': bool(cs.get('is_emoji') or content_type == 3),
            'audio_duration': int(cs.get('audio_duration') or 0),
            'source_title': str(cs.get('aweme_title') or '').strip(),
            'aweme_id': str(cs.get('aweme_id') or ''),
            'images': [{'url': media_url, 'alt': '表情包/动图' if content_type == 3 else '评论配图'}] if media_url else [],
            'has_media': bool(media_url) or bool(cs.get('audio_duration')),
            'raw_text': text,
        }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    author = ''
    source = ''
    source_title = ''
    body_lines = []
    header_done = False
    for index, line in enumerate(lines):
        if not header_done:
            if line.startswith('分享'):
                merged = line
                if merged.endswith('@') and index + 1 < len(lines):
                    merged += lines[index + 1]
                match = re.search(r'分享\s*@?\s*([^\s]+)', merged)
                if match:
                    author = match.group(1)
                continue
            if '的评论' in line:
                continue
            if line.startswith('来自'):
                source = line.replace('来自', '').strip()
                header_done = True
                continue
            if re.fullmatch(r'(刚刚|\d+\s*分钟前|\d+\s*小时前|昨天.*|前天.*|\d{1,2}:\d{2}|\d+天前)', line):
                continue
            if author and line == author:
                continue
        else:
            if not source_title:
                source_title = line
            continue
        if line != '当前评论不可见':
            body_lines.append(line)
    images = []
    for image in item.get('image_sources') or item.get('images') or []:
        if isinstance(image, dict) and image.get('src'):
            images.append({'url': image['src'], 'alt': image.get('alt', '')})
        elif isinstance(image, str):
            images.append({'url': image, 'alt': ''})
    return {
        'kind': 'comment_share',
        'author': author,
        'source': source,
        'text': '\n'.join(body_lines).strip(),
        'content_type': 1,
        'media_url': images[0]['url'] if images else '',
        'is_emoji': False,
        'audio_duration': 0,
        'source_title': source_title,
        'images': images,
        'has_media': bool(images) or bool(item.get('videos')),
        'raw_text': text,
    }


def _image_bytes_to_jpeg_data_url(raw_bytes):
    from PIL import Image, ImageOps
    with Image.open(BytesIO(raw_bytes)) as opened:
        # 如果是动图 GIF/WebP，取中间帧或第一帧转为 RGB JPEG 供视觉模型识别
        if getattr(opened, 'is_animated', False) and getattr(opened, 'n_frames', 1) > 1:
            try:
                opened.seek(min(opened.n_frames - 1, max(0, opened.n_frames // 2)))
            except Exception:
                opened.seek(0)
        frame = ImageOps.exif_transpose(opened).convert('RGB')
        frame.thumbnail((1280, 1280))
        buf = BytesIO()
        frame.save(buf, format='JPEG', quality=90)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


async def describe_image_source(owner, source_url, hint='聊天图片'):
    """下载或解码图片（支持 data:image/...;base64,... 与 https 签名链接），调用视觉模型返回简短客观描述。"""
    if not source_url or not isinstance(source_url, str):
        return ''
    provider_id = str(owner.config.get('video_provider_id') or '').strip()
    if not provider_id:
        return ''
    raw_bytes = b''
    stage = 'download'
    diagnostic = {'state': 'failed', 'stage': stage}
    digest = None
    try:
        if source_url.startswith('data:'):
            if ',' not in source_url:
                return ''
            raw_bytes = base64.b64decode(source_url.split(',', 1)[1])
        elif source_url.startswith(('http://', 'https://')):
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                resp = await client.get(source_url, headers={'Referer': 'https://www.douyin.com/'})
                diagnostic['http_status'] = resp.status_code
                resp.raise_for_status()
                raw_bytes = resp.content
        if not raw_bytes or len(raw_bytes) < 64:
            raise ValueError('empty_image_bytes')
        digest = hashlib.sha256(raw_bytes).hexdigest()
        cache_key = 'image-desc:v2:' + provider_id + ':' + digest
        cached = owner.ledger.get(cache_key)
        if cached and isinstance(cached, str):
            diagnostic.update(state='read', stage='cache', description_chars=len(cached))
            return cached
        stage = 'decode'
        data_url = _image_bytes_to_jpeg_data_url(raw_bytes)
        wrapped = _Owner(owner)
        msg = Message(role='user', content=[
            ImageURLPart(image_url={'url': data_url, 'detail': 'high'}),
            TextPart(text=f'客观、简明地描述这张{hint}里的画面内容、人物表情动作和全部可见文字（100字以内，不要寒暄）。只返回JSON对象，格式：{{"description":"画面描述"}}，description必须是非空字符串。'),
        ])
        stage = 'generate'
        response = await asyncio.wait_for(wrapped.context.llm_generate(
            chat_provider_id=provider_id,
            contexts=[msg],
            max_tokens=600,
            perception_task='image',
        ), timeout=90)
        stage = 'parse'
        content = str(getattr(response, 'completion_text', '') or '').strip()
        payload = json.loads(content)
        desc = payload.get('description') if isinstance(payload, dict) else None
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError('missing_image_description')
        desc = desc.strip()
        owner.ledger.put(cache_key, desc)
        diagnostic.update(state='read', stage='complete', description_chars=len(desc))
        return desc
    except Exception as exc:
        diagnostic.update(stage=stage, error_type=type(exc).__name__)
        logger.warning('Image description failed: stage=%s error_type=%s', stage, type(exc).__name__)
        return ''
    finally:
        try:
            owner.ledger.put('image-debug:' + (digest or hashlib.sha256(source_url.encode()).hexdigest()), diagnostic)
        except Exception:
            logger.warning('Image diagnostic persistence failed')


async def enrich_comment_card(owner, card):
    """如果分享的评论包含图片或表情包/GIF（content_type 为 2 或 3 且有 media_url），调用视觉模型补充画面描述。"""
    media_url = card.get('media_url') or ''
    content_type = card.get('content_type') or 1
    if media_url and (content_type in (2, 3) or card.get('is_emoji') or not card.get('text')):
        hint = '评论表情包/动图' if (content_type == 3 or card.get('is_emoji')) else '评论配图'
        desc = await describe_image_source(owner, media_url, hint=hint)
        if desc:
            card['media_description'] = desc
    return card


def format_comment_card(card):
    """把结构化评论整理成给模型看的观察资料。"""
    parts = ['[分享的评论]']
    if card.get('author'):
        parts.append('评论作者：' + card['author'])
    if card.get('source'):
        parts.append('来自：' + card['source'])
    ctype = card.get('content_type') or 1
    type_label = {1: '文字评论', 2: '图片评论', 3: '表情包/动图评论'}.get(ctype, '评论')
    if card.get('audio_duration'):
        type_label = f"语音评论（时长 {card['audio_duration']} 秒）"
    parts.append('评论类型：' + type_label)
    if card.get('text'):
        parts.append('评论正文：' + card['text'])
    elif card.get('media_description'):
        parts.append('评论正文：（无文字，为图片/表情包评论）')
    else:
        parts.append('评论正文：这条评论没有文字，只有图片或表情。')
    if card.get('media_description'):
        parts.append('评论图片/表情画面内容：' + card['media_description'])
    elif card.get('media_url'):
        parts.append('附带媒体：含评论配图或表情包。')
    if card.get('source_title'):
        parts.append('来源视频标题：' + card['source_title'])
    return '\n'.join(parts)
