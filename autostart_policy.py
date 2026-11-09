"""Pure policy helpers for restoring and guarding a listening session."""
LISTEN_KEY = 'listen-wanted'


def wants_listening(stored, config_enabled=False):
    return bool(config_enabled) if stored is None else bool(stored)


def state_after_open(open_state, stored, config_enabled=False, binding=None):
    if open_state == 'waiting_for_conversation' and binding and wants_listening(stored, config_enabled):
        return 'listening'
    if binding and wants_listening(stored, config_enabled):
        return 'listening'
    return 'paused' if binding else (open_state or 'not_bound')


def should_guard(state, binding=None, closed=False, auto_start=True):
    return bool(auto_start and not closed and binding and state != 'listening')
