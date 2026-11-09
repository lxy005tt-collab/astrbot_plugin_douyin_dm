"""Pure policy for browser dialog recovery decisions."""
MIN_DIALOG_WIDTH = 100
RELOAD_COOLDOWN_MS = 90000


def needs_reload(dialog_width, now_ms, last_heal_ms):
    return dialog_width < MIN_DIALOG_WIDTH and now_ms - last_heal_ms > RELOAD_COOLDOWN_MS


def editor_ready(width):
    return width >= MIN_DIALOG_WIDTH
