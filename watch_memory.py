"""Persist a compact, grounded video recollection in the linked private memory."""

from __future__ import annotations

from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import time

from .bridge import BrowserError
from .video_transcription import transcribe_video


def memory_components(owner):
    star = owner.context.get_registered_star('astrbot_plugin_livingmemory')
    if not star or not star.activated or not star.star_cls:
        raise BrowserError('长期记忆插件尚未就绪。')
    plugin = star.star_cls
    engine = plugin.initializer.memory_engine
    if not engine:
        raise BrowserError('长期记忆引擎尚未就绪。')
    package = plugin.__class__.__module__.rsplit('.', 1)[0]
    scope = importlib.import_module(package + '.core.memory_scope')
    return plugin, engine, scope


async def remember_video(owner, event, sources, watched_at=None):
    plugin, engine, scope = memory_components(owner)
    if not scope.is_event_memory_allowed(plugin.config_manager, event):
        raise BrowserError('这条私信没有长期记忆权限。')
    canonical = scope.resolve_memory_scope(plugin.config_manager, event) or event.unified_msg_origin
    utilities = importlib.import_module(plugin.__class__.__module__.rsplit('.', 1)[0] + '.core.utils')
    persona = await utilities.get_persona_id(owner.context, event)
    if not persona:
        raise BrowserError('当前视频会话没有确认的人格，未写入共享记忆。')
    source_keys = [source.get('url') or hashlib.sha256(Path(source['path']).read_bytes()).hexdigest() for source in sources]
    watch_key = hashlib.sha256(json.dumps([canonical, persona, sorted(source_keys)]).encode()).hexdigest()
    receipt_key = 'watch-memory:' + watch_key
    previous = owner.ledger.get(receipt_key)
    if previous:
        return {**previous, 'already_saved': True}
    if engine.db_connection:
        cursor = await engine.db_connection.execute(
            "SELECT doc_id FROM documents WHERE json_extract(metadata,'$.video_watch_key')=? LIMIT 1", (watch_key,))
        row = await cursor.fetchone()
        if row:
            receipt = {'memory_id': row[0], 'scope': canonical, 'persona_id': persona}
            owner.ledger.put(receipt_key, receipt)
            return {**receipt, 'already_saved': True}
    record_key = 'watch-record:' + watch_key
    record = owner.ledger.get(record_key)
    if not record:
        record = await _build_watch_record(owner,event,sources,canonical,persona,watch_key,source_keys,watched_at)
        owner.ledger.put(record_key,record)
    if owner.config.get('defer_video_memory_indexing',False):
        return {'memory_id':None,'scope':canonical,'persona_id':persona,'state':'saved_locally'}
    try:
        memory_id = await engine.add_memory(content=record['content'], session_id=canonical, persona_id=persona,
                                            importance=0.85, metadata=record['metadata'])
    except Exception as exc:
        raise BrowserError(f'视频回忆已保存在本地，向量入库暂未完成：{type(exc).__name__}。') from exc
    receipt = {'memory_id': memory_id, 'scope': canonical, 'persona_id': persona,'state':'indexed'}
    record.update(receipt)
    owner.ledger.put(record_key,record)
    owner.ledger.put(receipt_key, receipt)
    return receipt


async def _build_watch_record(owner,event,sources,canonical,persona,watch_key,source_keys,watched_at):
    get_extra=getattr(event,'get_extra',None)
    data=get_extra('douyin_video_transcript') if get_extra else None
    if not data:
        data=await transcribe_video(owner,sources)
    summary = str(data.get('summary') or '').strip()[:1000]
    if not summary:
        raise BrowserError('视频回忆没有取得有效内容。')
    facts = [str(x)[:250] for x in data.get('key_facts', [])[:4]]
    audio = str(data.get('audio') or '')[:500]
    uncertain = [str(x)[:200] for x in data.get('uncertain', [])[:4]]
    when = datetime.fromtimestamp(watched_at or time.time()).strftime('%Y-%m-%d %H:%M')
    media_kind='图文' if sources and all(source.get('kind')=='images' for source in sources) else '视频'
    action='主动读取了一条抖音作品' if any(source.get('origin')=='self_browse' for source in sources) else f'在抖音观看了用户分享的{media_kind}'
    content = f'{when}，机器人{action}。内容：{summary}'
    if facts:
        content += '\n具体画面或事件：' + '；'.join(facts)
    if audio:
        content += '\n声音或语音：' + audio
    if data.get('post_descriptions'):
        content += '\n作品文案：'+'；'.join(str(text) for text in data['post_descriptions'])[:1000]
    if uncertain:
        content += '\n未确认：' + '；'.join(uncertain)
    metadata = {'memory_origin': 'douyin_video_watch', 'source_session_id': event.unified_msg_origin,
                'video_watch_key': watch_key, 'video_urls': source_keys, 'watched_at': watched_at,
                'summary': summary, 'video_provider_id':data.get('provider_id'), 'video_model':data.get('model'), 'topics': ['抖音', '分享视频', '观看回忆'], 'key_facts': facts}
    return {'content':content,'metadata':metadata,'scope':canonical,'persona_id':persona,
            'state':'pending_index','memory_id':None,'watched_at':watched_at or time.time()}


async def index_pending_video_memories(owner,event):
    plugin,engine,scope=memory_components(owner)
    if not scope.is_event_memory_allowed(plugin.config_manager,event):
        raise BrowserError('当前私信没有长期记忆权限。')
    canonical=scope.resolve_memory_scope(plugin.config_manager,event) or event.unified_msg_origin
    results={'indexed':[],'already_indexed':[],'skipped':[],'failed':[]}
    rows=owner.ledger.db.execute("SELECT key,value FROM state WHERE key LIKE 'watch-record:%'").fetchall()
    for key,value in rows:
        record=json.loads(value)
        if record.get('state')!='pending_index':continue
        metadata=record.get('metadata',{})
        if record.get('scope')!=canonical or metadata.get('source_session_id')!=event.unified_msg_origin:
            results['skipped'].append({'key':key,'reason':'关联或权限范围已改变'});continue
        try:
            existing=None
            if engine.db_connection:
                cursor=await engine.db_connection.execute("SELECT doc_id FROM documents WHERE json_extract(metadata,'$.video_watch_key')=? LIMIT 1",(metadata.get('video_watch_key'),))
                row=await cursor.fetchone();existing=row[0] if row else None
            memory_id=existing if existing is not None else await engine.add_memory(
                content=record['content'],session_id=record['scope'],persona_id=record['persona_id'],
                importance=0.85,metadata=metadata)
            receipt={'memory_id':memory_id,'scope':record['scope'],'persona_id':record['persona_id'],'state':'indexed'}
            record.update(receipt);owner.ledger.put(key,record)
            owner.ledger.put('watch-memory:'+metadata['video_watch_key'],receipt)
            results['already_indexed' if existing is not None else 'indexed'].append(memory_id)
        except Exception as exc:
            results['failed'].append({'key':key,'reason':type(exc).__name__})
    return results
