import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diary_state import classify, day_key, prompt, recent_confirmed, DIARY_COMMANDS

assert DIARY_COMMANDS == ('\u5199\u65e5\u8bb0',)
assert day_key(date(2026, 11, 9)) == 'manual-diary:2026-11-09'
assert classify({'state': 'written'}) == 'blocked'
assert classify({'state': 'pending'}, 'generating') == 'processing'
assert classify({'state': 'sending'}, None) == 'retry'
assert classify({'state': 'failed'}) == 'retry'
assert classify({}) == 'ready'
rows = [{'day': '2026-11-08', 'state': 'written', 'text': '旧日记'},
        {'day': '2026-11-07', 'state': 'failed', 'text': '不算'},
        {'day': '2026-10-01', 'state': 'written', 'text': '太旧'}]
recent = recent_confirmed(rows, date(2026, 11, 9))
assert len(recent) == 1 and recent[0]['day'] == '2026-11-08'
assert '\u624b\u52a8\u65e5\u8bb0\u8bf7\u6c42' in prompt('2026-11-09', recent, ['片段'])
