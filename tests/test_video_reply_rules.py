import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_reply_rules import guide, violates, BANNED, RULES

assert len(RULES) == 5
assert all(isinstance(x, str) and x for x in RULES)
assert '\u76f4\u63a5' in guide()
assert violates('\u6211\u8bb0\u4e0b\u4e86') == ['\u6211\u8bb0\u4e0b\u4e86']
assert violates('\u4eca\u5929\u771f\u597d') == []
