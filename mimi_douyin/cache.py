"""Owned-media cleanup shared by the standalone and AstrBot runtimes."""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from .errors import BrowserError

CACHE_DEFAULTS={'cache_cleanup_enabled':False,'cache_cleanup_interval_hours':24,'cache_retention_hours':24}
MEDIA_DEFAULTS={'max_download_mb':64,**CACHE_DEFAULTS}
NAME=re.compile(r'^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-(?:model|vision|transcription)){0,4}\.(?:mp4|mp3|png|jpe?g|webp|avif|gif)$',re.I)

def media_settings(config):return {name:config.get(name,default) for name,default in MEDIA_DEFAULTS.items()}

def validate_media_settings(payload):
    changes={name:payload[name] for name in MEDIA_DEFAULTS if name in payload}
    if 'cache_cleanup_enabled' in changes and not isinstance(changes['cache_cleanup_enabled'],bool):
        raise BrowserError('定时清理开关应为布尔值。')
    labels={'max_download_mb':'作品下载大小上限','cache_cleanup_interval_hours':'清理间隔','cache_retention_hours':'缓存保留时长'}
    for name,label in labels.items():
        if name not in changes:continue
        value=changes[name]
        if isinstance(value,bool) or not re.fullmatch(r'\d+',str(value)):
            raise BrowserError(label+'应为整数。')
        value=int(value);minimum=0 if name=='cache_retention_hours' else 1
        if not minimum<=value<=10000:raise BrowserError(f'{label}应在 {minimum}～10000 之间。')
        changes[name]=value
    return changes

def normalized(path):return os.path.normcase(str(Path(path).resolve()))

class CacheFiles:
    def __init__(self,database):
        self.path=Path(database);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS owned (root TEXT,family TEXT,PRIMARY KEY(root,family))')
            db.execute('CREATE TABLE IF NOT EXISTS reports (key TEXT PRIMARY KEY,value TEXT)')

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=5)
        try:
            with connection:yield connection
        finally:connection.close()

    def register(self,root,source):
        root=Path(root).resolve();files=[]
        if not isinstance(source,dict):return
        if source.get('path'):files.append(source['path'])
        files.extend(item['path'] for item in source.get('images',[]) if isinstance(item,dict) and item.get('path'))
        families=set()
        for value in files:
            file=Path(value);match=NAME.fullmatch(file.name)
            if match and file.is_file() and not file.is_symlink() and file.resolve().parent==root:families.add(match[1].lower())
        if families:
            with self.connect() as db:db.executemany('INSERT OR IGNORE INTO owned VALUES (?,?)',[(normalized(root),family) for family in families])

    def last_report(self):
        with self.connect() as db:row=db.execute("SELECT value FROM reports WHERE key='last_cleanup'").fetchone()
        return json.loads(row[0]) if row else None

    def purge(self,root,retention_hours,*,legacy_roots=(),now=None):
        root=Path(root).resolve();root_key=normalized(root);now=time.time() if now is None else now
        result={'finished_at':now,'deleted_files':0,'deleted_bytes':0,'failed_files':0}
        if not root.is_dir():return result
        # Only the application's own default/legacy folders can adopt old UUID files.
        # In a user-selected mixed folder, files must have a download ownership record.
        if root_key in {normalized(item) for item in legacy_roots}:
            self.register(root,{'images':[{'path':str(file)} for file in root.iterdir() if NAME.fullmatch(file.name)]})
        with self.connect() as db:families={row[0] for row in db.execute('SELECT family FROM owned WHERE root=?',(root_key,))}
        cutoff=now-float(retention_hours)*3600
        for file in root.iterdir():
            match=NAME.fullmatch(file.name)
            if not match or match[1].lower() not in families:continue
            try:
                info=file.lstat()
                if not stat.S_ISREG(info.st_mode) or file.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:continue
                if file.resolve().parent!=root or info.st_mtime>cutoff:continue
                file.unlink();result['deleted_files']+=1;result['deleted_bytes']+=info.st_size
            except FileNotFoundError:pass
            except OSError:result['failed_files']+=1
        # Keep family ownership while any young/locked derivative still exists.
        still={match[1].lower() for file in root.iterdir() if (match:=NAME.fullmatch(file.name)) and match[1].lower() in families}
        with self.connect() as db:
            db.executemany('DELETE FROM owned WHERE root=? AND family=?',[(root_key,family) for family in families-still])
            db.execute('INSERT OR REPLACE INTO reports VALUES (?,?)',('last_cleanup',json.dumps(result)))
        return result

class CacheMaintenance:
    def __init__(self,owner,*,legacy_roots=()):
        self.owner=owner;self.files=CacheFiles(owner.data_dir/'media-cache.sqlite3')
        self.legacy_roots=(owner.data_dir/'media',*legacy_roots)
        self.task=None;self.event=asyncio.Event();self.signature=None;self.next_run=None;self.last_error=''

    def settings_changed(self):
        settings=media_settings(self.owner.config)
        signature=(settings['cache_cleanup_enabled'],settings['cache_cleanup_interval_hours'],
            settings['cache_retention_hours'],str(self.owner.media_dir))
        if signature!=self.signature:
            self.signature=signature
            self.next_run=time.time()+settings['cache_cleanup_interval_hours']*3600 if settings['cache_cleanup_enabled'] else None
        self.event.set()

    def start(self):
        if self.task is None or self.task.done():
            self.signature=None;self.settings_changed()
            self.task=asyncio.create_task(self._run())

    def status(self):
        return {**media_settings(self.owner.config),'next_run_at':self.next_run,'last_cleanup':self.files.last_report(),
            'last_error':self.last_error or getattr(self.owner.browser,'cache_registration_error',''),
            'restart_resets_timer':True}

    async def run_due(self,now=None):
        settings=media_settings(self.owner.config);now=time.time() if now is None else now
        if not settings['cache_cleanup_enabled'] or self.next_run is None or now<self.next_run:return None
        if self.owner.action_lock.locked() or self.owner.job_lock.locked():return None
        async with self.owner.action_lock:
            async with self.owner.job_lock:
                work=asyncio.create_task(asyncio.to_thread(self.files.purge,self.owner.media_dir,settings['cache_retention_hours'],
                    legacy_roots=self.legacy_roots,now=now))
                try:result=await asyncio.shield(work)
                except asyncio.CancelledError:
                    await work
                    raise
                self.next_run=now+settings['cache_cleanup_interval_hours']*3600
                self.last_error=f"有 {result['failed_files']} 个缓存文件暂时无法删除。" if result['failed_files'] else ''
                return result

    async def _run(self):
        while True:
            self.event.clear();self.settings_changed();self.event.clear()
            try:await self.run_due()
            except asyncio.CancelledError:raise
            except Exception as exc:
                self.last_error='缓存清理未完成：'+type(exc).__name__
                self.next_run=time.time()+media_settings(self.owner.config)['cache_cleanup_interval_hours']*3600
            try:await asyncio.wait_for(self.event.wait(),30)
            except asyncio.TimeoutError:pass

    async def close(self):
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);self.task=None
