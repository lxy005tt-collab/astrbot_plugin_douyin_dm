from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from .errors import BrowserError
from .cache import CacheFiles

class _ConnectionClosed(BrowserError):
    """The response stream cannot be used again, even if the process is alive."""
    pass

class BrowserWorker:
    def __init__(self, config):
        self.config=config
        self.process=None
        self.reader=None
        self.pending={}
        self.sequence=0
        self.start_lock=asyncio.Lock()
        self.open_lock=asyncio.Lock()
        self.cache_registration_error=''
        self._broken=False
        self._open_args=None

    async def start(self):
        async with self.start_lock:
            if (self.process and self.process.returncode is None and not self._broken
                    and self.reader and not self.reader.done()):return
            if not self.config.get('node_binary'):raise BrowserError('未找到 Node.js，请先在接入设置中检查依赖。')
            await self._stop_process(self.process,self.reader)
            env=os.environ.copy()
            if self.config.get('playwright_browsers_path'):env['PLAYWRIGHT_BROWSERS_PATH']=self.config['playwright_browsers_path']
            self.process=await asyncio.create_subprocess_exec(self.config['node_binary'],
                str(Path(__file__).parent/'browser/worker.mjs'),stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env,
                creationflags=0x08000000 if os.name=='nt' else 0,limit=16*1024*1024)
            self.pending={}
            self._broken=False
            self.reader=asyncio.create_task(self._read(self.process,self.pending))
            self.reader.add_done_callback(self._reader_finished)
            if self._open_args is not None:
                try:await self._call(self.process,'open',dict(self._open_args),timeout=90)
                except BaseException:
                    await self._stop_process(self.process,self.reader)
                    raise

    @staticmethod
    def _reader_finished(task):
        if not task.cancelled():task.exception()

    def _invalidate(self,process):
        if process is self.process:self._broken=True
        if process.stdin:process.stdin.close()

    @staticmethod
    async def _discard_output(stream):
        while await stream.read(65536):pass

    async def _stop_process(self,process,reader):
        if not process:return
        if process.stdin:process.stdin.close()
        if process.returncode is None and reader and not reader.done():
            reader.cancel()
            await asyncio.gather(reader,return_exceptions=True)
        # Drain a failed reader's buffered output so a large blocked writer can
        # exit. A previous, already-dead generation may still have its own reader.
        drain=asyncio.create_task(self._discard_output(process.stdout)) if not reader or reader.done() else None
        try:
            try:await asyncio.wait_for(process.wait(),5)
            except asyncio.TimeoutError:
                if process.returncode is None:
                    try:process.kill()
                    except ProcessLookupError:pass
                await asyncio.wait_for(process.wait(),5)
        finally:
            if drain:
                drain.cancel()
                await asyncio.gather(drain,return_exceptions=True)

    async def _read(self,process,pending):
        message='抖音浏览器连接已关闭，请重试读取或重新绑定；未自动重发消息。'
        try:
            while line:=await process.stdout.readline():
                reply=json.loads(line)
                if (not isinstance(reply,dict) or type(reply.get('id')) is not int
                        or type(reply.get('ok')) is not bool or (reply['ok'] and 'result' not in reply)):
                    raise ValueError('invalid response envelope')
                future=pending.pop(reply.get('id'),None)
                if future and not future.done():
                    if reply.get('ok'):future.set_result(reply['result'])
                    else:future.set_exception(BrowserError(reply.get('error','浏览器操作失败。')))
        except (ValueError,TypeError):
            message='抖音浏览器响应超过 16 MiB 或格式无效，连接已停用；请重试读取或重新绑定。'
        except (OSError,RuntimeError):
            message='抖音浏览器响应读取失败，连接已停用；请重试读取或重新绑定。'
        finally:
            self._invalidate(process)
            for future in pending.values():
                if not future.done():future.set_exception(_ConnectionClosed(message))
            pending.clear()

    async def call(self, action, args=None, timeout=30):
        await self.start()
        return await self._call(self.process,action,args,timeout)

    async def _call(self,process,action,args=None,timeout=30):
        pending=self.pending
        self.sequence+=1
        request_id=self.sequence
        future=asyncio.get_running_loop().create_future()
        pending[request_id]=future
        try:
            async def exchange():
                process.stdin.write((json.dumps({'id':request_id,'action':action,'args':args or {}},ensure_ascii=False)+'\n').encode())
                await process.stdin.drain()
                return await future
            result=await asyncio.wait_for(exchange(),timeout)
            if process is self.process and action=='open':self._open_args=dict(args or {})
            elif process is self.process and action=='configure' and self._open_args is not None:
                self._open_args.update({key:value for key,value in (args or {}).items()
                    if key in ('media_dir','max_download_mb','max_video_duration_seconds')})
            elif process is self.process and self._open_args is not None and isinstance(result,dict) and result.get('ready') and isinstance(result.get('peer'),dict):
                self._open_args={**self._open_args,'restore_peer':dict(result['peer'])}
            if action in ('download','browse') and self.config.get('media_cache_registry'):
                try:
                    CacheFiles(self.config['media_cache_registry']).register(self.config['media_dir'],result)
                    self.cache_registration_error=''
                except (OSError,sqlite3.Error):self.cache_registration_error='缓存登记暂不可写，未登记的文件会保留。'
            return result
        except asyncio.TimeoutError as exc:
            if action=='send':return {'state':'unknown','receipt':'browser_command_timeout'}
            raise BrowserError('抖音浏览器操作超时。') from exc
        except _ConnectionClosed:
            if action=='send':return {'state':'unknown','receipt':'browser_connection_closed'}
            raise
        except OSError:
            self._invalidate(process)
            if action=='send':return {'state':'unknown','receipt':'browser_connection_closed'}
            raise
        finally:
            pending.pop(request_id,None)
            if not future.done():future.cancel()
            elif not future.cancelled():future.exception()

    async def open(self,peer=None):
        async with self.open_lock:
            return await self.call('open',{'profile':self.config['browser_profile'],
                'media_dir':self.config['media_dir'],'playwright_package':self.config['playwright_package'],
                'max_download_mb':self.config.get('max_download_mb',64),
                'max_video_duration_seconds':self.config.get('max_video_duration_seconds',180),
                'max_post_images':self.config.get('max_post_images',30),'restore_peer':peer,
                'private_whitelist':self.config.get('private_whitelist',[]),
                'browser_channel':self.config.get('browser_channel',''),
                'browser_executable':self.config.get('browser_executable',''),
                'headless':bool(self.config.get('browser_headless',False))},timeout=90)

    async def close(self):
        async with self.start_lock:
            self._open_args=None
            process=self.process
            if not process:return
            try:
                if process.returncode is None and not self._broken and self.reader and not self.reader.done():
                    await self._call(process,'close',timeout=10)
            except (BrowserError,OSError):pass
            finally:
                await self._stop_process(process,self.reader)
                if self.reader:await asyncio.gather(self.reader,return_exceptions=True)
                self._open_args=None



class Ledger:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, details TEXT NOT NULL, updated REAL NOT NULL)')
        self.db.execute("UPDATE jobs SET state='interrupted' WHERE state IN ('queued','generating')")
        self.db.execute("UPDATE jobs SET state='unknown' WHERE state='sending'")
        self.db.commit()

    def get(self,key,default=None):
        row=self.db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
        self.db.commit()

    def observe(self,peer_key,items,*,prime=False,on_fresh=None):
        key='snapshot:'+peer_key
        current=[{k:item.get(k) for k in ('fingerprint','native_id','sender')} for item in items]
        previous=self.get(key)
        epoch=(previous[0].get('_delivery_epoch',0) if previous else 0)+1
        # Retain the receive sequence even across an empty/virtualized list.
        if not current:current=[{'fingerprint':None,'native_id':None,'sender':None}]
        current[0]['_delivery_epoch']=epoch
        if prime or previous is None:
            self.put(key,current);return []
        def identity(item):return (item.get('native_id') or item['fingerprint'],item['sender'])
        old=[identity(x) for x in previous];new=[identity(x) for x in current]
        overlap=0
        for length in range(min(len(old),len(new)),0,-1):
            if old[-length:]==new[:length]:overlap=length;break
        # Without an overlap we cannot distinguish old history, a virtual-list
        # reset, and new messages; re-baseline instead of replaying history.
        fresh=[x for x in items[overlap:] if x['sender']=='peer'] if overlap else []
        if on_fresh:
            fresh=[item if item.get('native_id') else {**item,'_delivery_key':f'observation:{epoch}:{index}'}
                for index,item in enumerate(fresh)]
        # Persist the inbox before advancing the receive cursor. If the cursor
        # write fails, the inbox deduplicates the next observation by message ID.
        if fresh and on_fresh:on_fresh(fresh)
        self.put(key,current)
        return fresh

    def job(self,job_id,state,details=None):
        if details is None:
            row=self.db.execute('SELECT details FROM jobs WHERE id=?',(job_id,)).fetchone()
            details=json.loads(row[0]) if row else {}
        self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',
            (job_id,state,json.dumps(details,ensure_ascii=False),time.time()))
        self.db.commit()

    def outbox(self,job_id,text):
        digest=hashlib.sha256(text.encode()).hexdigest()
        key='outbox:'+job_id+':'+digest
        if self.get(key) is not None:return None
        self.put(key,{'state':'sending','at':time.time()})
        self.job(job_id,'sending')
        return key

    def close(self):self.db.close()


