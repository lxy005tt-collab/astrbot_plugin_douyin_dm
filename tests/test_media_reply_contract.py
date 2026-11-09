# 离线测试：媒体回复契约的纯函数边界。
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from media_reply import _tokens, _similarity, _sentences, _repetition_audit, media_reply_contract

assert _tokens('') == set()
assert len(_tokens('你好，世界')) > 0
assert _similarity('完全相同的句子', '完全相同的句子') == 1.0
assert _similarity('甲', '乙') == 0.0
assert _sentences('一句。两句！') == ['一句', '两句']
audit = _repetition_audit('视频里有一只猫', '画面：视频里有一只猫')
assert isinstance(audit, dict) and 'fact_echo_ratio' in audit and 'matched_sentences' in audit
assert isinstance(media_reply_contract(object(), None), str)
