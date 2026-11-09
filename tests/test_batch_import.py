import importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'batch_import.py'
s=importlib.util.spec_from_file_location('batch_import',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
assert m.FFMPEG=='ffmpeg' or m.FFMPEG.endswith('ffmpeg')
assert isinstance(m.build_filter('light',False),str)
assert isinstance(m.LEVELS,dict) and m.LEVELS
