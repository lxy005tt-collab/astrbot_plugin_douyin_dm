import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autostart_policy import wants_listening, state_after_open, should_guard, LISTEN_KEY

assert LISTEN_KEY == 'listen-wanted'
assert wants_listening(None, True) is True
assert wants_listening(False, True) is False
assert state_after_open('waiting_for_conversation', True, False, {'key': 'peer'}) == 'listening'
assert state_after_open('waiting_for_conversation', False, True, {'key': 'peer'}) == 'paused'
assert should_guard('needs_attention', {'key': 'peer'}) is True
assert should_guard('listening', {'key': 'peer'}) is False
