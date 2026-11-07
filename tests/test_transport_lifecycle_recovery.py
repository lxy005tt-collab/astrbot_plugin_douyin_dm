"""Offline recovery of browser initialization and uncertain send receipts."""
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mimi_douyin.transport import BrowserWorker
from mimi_douyin.errors import BrowserError

CHILD=r'''
import json, os, sys
opened=None
peer=None
for line in sys.stdin:
    request=json.loads(line); action=request['action']; args=request['args']
    if action=='open':
        opened=dict(args);peer=args.get('restore_peer');value={'open':True}
    elif action=='configure':
        opened.update(args);value={}
    elif action=='select_conversation':
        peer={'key':'new-peer','conversation_id':args['conversation_id'],'conversation_type':'private'}
        value={'ready':True,'peer':peer,'items':[]}
    elif action=='snapshot':
        if opened is None:
            print(json.dumps({'id':request['id'],'ok':False,'error':'browser not initialized'}),flush=True)
            continue
        value={'ready':True,'peer':peer,'items':[],'opened':opened}
    elif action=='hold':continue
    elif action in ('corrupt','send'):
        if action=='send':
            with open(sys.argv[1],'a',encoding='utf8') as output:output.write('send\n')
        print('{invalid json}',flush=True)
        continue
    elif action=='eof':
        os.close(1)
        for unused in sys.stdin:pass
        break
    elif action=='missing_result':
        print(json.dumps({'id':request['id'],'ok':True}),flush=True)
        continue
    else:value={'opened':opened,'pid':os.getpid()}
    print(json.dumps({'id':request['id'],'ok':True,'result':value}),flush=True)
'''


class LifecycleRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=Path(self.temp.name)/'synthetic-receipts.txt'
        self.processes=[]
        self.worker=BrowserWorker({'node_binary':'node','browser_profile':'offline',
            'media_dir':'initial-media','playwright_package':'playwright','private_whitelist':['new-peer']})
        create=asyncio.create_subprocess_exec
        async def spawn(*args,**kwargs):
            process=await create(sys.executable,'-u','-c',CHILD,str(self.journal),**kwargs)
            self.processes.append(process)
            return process
        self.spawn=AsyncMock(side_effect=spawn)
        self.patch=patch('mimi_douyin.transport.asyncio.create_subprocess_exec',self.spawn)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def asyncTearDown(self):
        try:await asyncio.wait_for(self.worker.close(),12)
        finally:
            for process in self.processes:
                if process.returncode is None:process.kill()
                await asyncio.wait_for(process.wait(),2)
            self.temp.cleanup()

    async def test_concurrent_recovery_restores_latest_browser_state_once(self):
        await self.worker.open({'key':'initial-peer','conversation_id':'initial'})
        await self.worker.call('configure',{'media_dir':'updated-media','max_download_mb':32})
        await self.worker.call('select_conversation',{'conversation_id':'latest'})
        old=self.worker.process;reader=self.worker.reader
        with self.assertRaises(BrowserError):await self.worker.call('corrupt',timeout=1)
        await asyncio.wait_for(reader,1)
        results=await asyncio.wait_for(asyncio.gather(*(self.worker.call('snapshot') for _ in range(8))),5)
        self.assertEqual(self.spawn.await_count,2)
        self.assertIsNotNone(old.returncode)
        self.assertIsNone(reader.exception())
        self.assertFalse(self.worker.pending)
        self.assertFalse(self.worker.reader.done())
        for result in results:
            self.assertEqual(result['peer']['conversation_id'],'latest')
            self.assertEqual(result['opened']['restore_peer']['key'],'new-peer')
            self.assertEqual(result['opened']['media_dir'],'updated-media')
            self.assertEqual(result['opened']['max_download_mb'],32)
            self.assertEqual(result['opened']['private_whitelist'],['new-peer'])
        await self.worker.close()
        self.assertIsNone((await self.worker.call('status'))['opened'])

    async def test_send_disconnect_is_unknown_and_never_replayed(self):
        await self.worker.open()
        result=await self.worker.call('send',{'text':'offline synthetic request'},timeout=1)
        self.assertEqual(result['state'],'unknown')
        await self.worker.call('status')
        self.assertEqual(self.spawn.await_count,2)
        self.assertEqual(self.journal.read_text(encoding='utf8'),'send\n')
        self.assertFalse(self.worker.pending)

    async def test_reader_failure_finishes_all_inflight_requests(self):
        await self.worker.start()
        waiting=asyncio.create_task(self.worker.call('hold',timeout=1))
        await asyncio.sleep(0)
        results=await asyncio.wait_for(asyncio.gather(waiting,self.worker.call('corrupt',timeout=1),
            return_exceptions=True),2)
        for result in results:
            self.assertIsInstance(result,BrowserError)
            self.assertNotIn('操作超时',str(result))
        self.assertFalse(self.worker.pending)
        await self.worker.call('status')
        self.assertEqual(self.spawn.await_count,2)

    async def test_eof_and_malformed_envelope_fail_pending_and_recover(self):
        for action in ('eof','missing_result'):
            with self.subTest(action=action):
                await self.worker.call('status')
                old=self.worker.process;reader=self.worker.reader
                with self.assertRaises(BrowserError):await self.worker.call(action,timeout=1)
                await asyncio.wait_for(reader,1)
                value=await asyncio.wait_for(self.worker.call('status'),5)
                self.assertNotEqual(value['pid'],old.pid)
                self.assertIsNotNone(old.returncode)
                self.assertIsNone(reader.exception())
                self.assertFalse(self.worker.pending)

    async def test_blocked_drain_respects_send_timeout(self):
        await self.worker.start()
        async def blocked():await asyncio.Future()
        with patch.object(self.worker.process.stdin,'write',Mock()),patch.object(
                self.worker.process.stdin,'drain',AsyncMock(side_effect=blocked)):
            result=await asyncio.wait_for(self.worker.call('send',timeout=0.03),1)
        self.assertEqual(result,{'state':'unknown','receipt':'browser_command_timeout'})
        self.assertFalse(self.worker.pending)


if __name__=='__main__':unittest.main()
