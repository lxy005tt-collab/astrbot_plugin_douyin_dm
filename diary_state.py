"""Manual diary state machine, independent from the chat runtime."""
from __future__ import annotations

from datetime import date, timedelta, timezone
import json

DIARY_COMMANDS = ('\u5199\u65e5\u8bb0',)
SHANGHAI = timezone(timedelta(hours=8))


def day_key(now=None):
    return 'manual-diary:' + (now or date.today()).isoformat()


def recent_confirmed(rows, today, limit=14):
    out = []
    for raw in rows:
        try:
            entry = json.loads(raw) if isinstance(raw, str) else dict(raw)
            saved = date.fromisoformat(entry.get('day', ''))
            if entry.get('state') == 'written' and 0 < (today - saved).days <= 14 and entry.get('text'):
                out.append({'day': entry['day'], 'text': str(entry['text'])[:1200]})
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    out.sort(key=lambda item: item['day'], reverse=True)
    return out[:limit]


def classify(record, active_job=None):
    state = (record or {}).get('state')
    if state == 'written':
        return 'blocked'
    if state == 'pending':
        return 'processing' if active_job in ('queued', 'generating', 'sending') else 'retry'
    if state == 'sending':
        return 'processing' if active_job in ('queued', 'generating', 'sending') else 'retry'
    if state in ('unknown', 'failed', 'partial'):
        return 'retry'
    return 'ready'


def prompt(day, recent=(), partial=()):
    head = '[' + '\u624b\u52a8\u65e5\u8bb0\u8bf7\u6c42' + '] ' + day
    dedup = '[\u6700\u8fd114\u5929\u5df2\u786e\u8ba4\u53d1\u9001\u7684\u65e5\u8bb0\uff0c\u4ec5\u7528\u4e8e\u53bb\u91cd]\n' + json.dumps(list(recent), ensure_ascii=False) if recent else '[\u6700\u8fd114\u5929\u6ca1\u6709\u5df2\u786e\u8ba4\u53d1\u9001\u7684\u65e5\u8bb0\u3002]\n'
    prior = ''
    if partial:
        prior = '[\u4e0a\u6b21\u5df2\u53d1\u51fa\u7684\u90e8\u5206\u65e5\u8bb0]\n' + json.dumps(list(partial), ensure_ascii=False) + '\n'
    return dedup + prior + head + '\n\u4ee5\u7b2c\u4e00\u4eba\u79f0\u5199\u4eca\u5929\u7684\u65e5\u8bb0\u6b63\u6587\uff0c\u4e0d\u590d\u8ff0\u65e7\u4e8b\u3001\u4e0d\u7f16\u9020\u7ecf\u5386\u3002'
