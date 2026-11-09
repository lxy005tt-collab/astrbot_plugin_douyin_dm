import json
from pathlib import Path
schema=json.loads(Path(__file__).resolve().parents[1].joinpath('_conf_schema.json').read_text(encoding='utf-8'))
for key in ('tts_enabled','tts_send_enabled','rvc_channel','auto_start_on_boot','open_timeout_seconds','guard_interval_seconds'):
    assert key in schema
assert schema['tts_enabled']['type']=='bool'
assert schema['rvc_channel']['type']=='string'
