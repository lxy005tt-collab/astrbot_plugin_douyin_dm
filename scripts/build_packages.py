"""Build both editions from one explicit shared-core file list."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
CORE_PY=['__init__.py','__main__.py','activities.py','app.py','cache.py','client.py','config.py','errors.py',
    'media.py','perception.py','runtime.py','service.py','transport.py','wire.py']
BROWSER=['worker.mjs','browser_actions.mjs','comment_ui.mjs','dom.mjs','media.mjs','post_media.mjs','explore.mjs','runtime_probe.mjs']
SHARED=['mimi_douyin/'+name for name in CORE_PY]+['mimi_douyin/browser/'+name for name in BROWSER]+[
    'mimi_douyin/web/index.html','mimi_douyin/web/app.js','mimi_douyin/web/style.css']
COMMON=['ATTRIBUTIONS.md','LICENSE','CHANGELOG.md','pyproject.toml','standalone-requirements.txt',
    'setup.bat','start.bat','config.example.json','.gitignore','scripts/build_packages.py']
NATIVE=['__init__.py','metadata.yaml','_conf_schema.json','main.py','bridge.py','browser_worker.mjs','dom.mjs','media.mjs',
    'watch_memory.py','video_transcription.py','runtime.py','runtime_probe.mjs','setup_api.py','browser_actions.mjs','native_activities.py',
    'package.json','requirements.txt','README.md','pages/接入设置/index.html','pages/接入设置/app.js','pages/接入设置/style.css','integrations/README.md']

def main():
    parser=argparse.ArgumentParser(description='Build standalone and optional AstrBot packages from this shared core.')
    parser.add_argument('--astrbot-source',type=Path,help='AstrBot adapter source directory; runtime data is never included.')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    version=re.search(r'^version\s*=\s*"([^"]+)"',(ROOT/'pyproject.toml').read_text('utf8'),re.M)[1]
    manifest={'version':version,'shared_files':SHARED,'archives':{}}
    def build(name,prefix,mapping):
        hashes={}
        with zipfile.ZipFile(args.output/name,'w',zipfile.ZIP_DEFLATED) as archive:
            for relative,file in sorted(mapping.items()):
                data=file.read_bytes();hashes[relative]=hashlib.sha256(data).hexdigest();archive.writestr(prefix+'/'+relative,data)
        manifest['archives'][name]={'files':hashes,'sha256':hashlib.sha256((args.output/name).read_bytes()).hexdigest()}
    standalone={name:ROOT/name for name in [*COMMON,'README.md',*SHARED]}
    build(f'MimiDouyin-Standalone-v{version}.zip','MimiDouyin',standalone)
    if args.astrbot_source:
        metadata=(args.astrbot_source/'metadata.yaml').read_text('utf-8-sig')
        native_version=re.search(r'^version:\s*["\']?([^\s"\']+)',metadata,re.M)[1]
        if native_version!=version:raise SystemExit('AstrBot metadata and shared-core version differ; neither edition should be published as a matched pair.')
        native={name:args.astrbot_source/name for name in NATIVE}
        native.update({name:ROOT/name for name in [*COMMON,*SHARED]})
        build(f'astrbot_plugin_douyin_dm-v{version}.zip','astrbot_plugin_douyin_dm',native)
        archives=list(manifest['archives'].values())
        assert all(archives[0]['files'][name]==archives[1]['files'][name] for name in SHARED)
    (args.output/'package-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'version':version,'packages':list(manifest['archives']),'shared_files':len(SHARED),'shared_core_matches':True},ensure_ascii=False))

if __name__=='__main__':main()
