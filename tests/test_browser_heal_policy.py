import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_heal_policy import needs_reload, editor_ready, MIN_DIALOG_WIDTH, RELOAD_COOLDOWN_MS

assert MIN_DIALOG_WIDTH == 100
assert RELOAD_COOLDOWN_MS == 90000
assert needs_reload(50, 100000, 0) is True
assert needs_reload(50, 10000, 0) is False
assert needs_reload(200, 100000, 0) is False
assert editor_ready(120) is True
assert editor_ready(50) is False
