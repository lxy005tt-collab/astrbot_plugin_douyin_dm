# 离线测试：视频回应风格观察模块的去重与提示词边界。
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_style_learning import topic, observe, hint

class Ledger:
    def __init__(self): self.data = {}
    def get(self, key, default=None): return self.data.get(key, default)
    def put(self, key, value): self.data[key] = value

assert topic('今天开黑打游戏') == '游戏'
assert topic('随便聊聊') == ''
ledger = Ledger()
peer = {'conversation_type': 'group', 'key': 'group-1'}
prior = {'kind': 'video', 'role': 'user', 'text': '游戏集锦', 'sender_id': '甲', 'observed_at': 100, 'id': 'v1'}
reaction = {'kind': 'text', 'role': 'user', 'text': '这波操作笑死我了呀', 'sender_id': '乙', 'observed_at': 120, 'id': 'm1'}
rows = [prior, reaction]
observe(ledger, peer, rows, [reaction])
assert len(ledger.get('video-reaction-style:v1')['chat']) == 1
observe(ledger, peer, rows, [reaction])
assert len(ledger.get('video-reaction-style:v1')['seen']) == 1
assert isinstance(hint(ledger, '游戏视频'), str)
