"""Transport lifecycle checks without AstrBot, Playwright or an account."""
import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mimi_douyin.transport import BrowserWorker
from mimi_douyin.errors import BrowserError


CHILD = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps(dict(id=request['id'], ok=True,
                         result=dict(action=request['action'], args=request['args']))), flush=True)
"""


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = BrowserWorker(dict(node_binary='node', browser_profile='profile',
                                        media_dir='media', playwright_package='playwright'))
        create = asyncio.create_subprocess_exec
        self.create = create

        async def spawn(*args, **kwargs):
            return await create(sys.executable, '-u', '-c', CHILD, **kwargs)

        self.spawn = AsyncMock(side_effect=spawn)
        self.patch = patch('mimi_douyin.transport.asyncio.create_subprocess_exec', self.spawn)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def asyncTearDown(self):
        await self.worker.close()

    async def test_wire_roundtrip_and_concurrent_start_use_one_process(self):
        results = await asyncio.gather(*(self.worker.call('status', {'number': n}) for n in range(8)))
        self.assertEqual([r['args']['number'] for r in results], list(range(8)))
        self.spawn.assert_awaited_once()
        self.assertFalse(self.worker.pending)

    async def test_real_node_worker_status_and_close_wire(self):
        self.spawn.side_effect = self.create
        self.assertEqual(await self.worker.call('status'),
                         {'open': False, 'logged_in': False, 'state': 'browser_closed'})
        await self.worker.close()
        self.assertIsNotNone(self.worker.process.returncode)
        self.spawn.assert_awaited_once()

    async def test_open_waits_for_previous_open_to_finish(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def call(action, args, timeout):
            calls.append(args['restore_peer'])
            entered.set()
            await release.wait()
            return args['restore_peer']

        with patch.object(self.worker, 'call', AsyncMock(side_effect=call)):
            first = asyncio.create_task(self.worker.open('first'))
            await entered.wait()
            second = asyncio.create_task(self.worker.open('second'))
            await asyncio.sleep(0)
            try:
                self.assertEqual(calls, ['first'])
            finally:
                release.set()
                results = await asyncio.gather(first, second)
            self.assertEqual(results, ['first', 'second'])

    async def test_write_failure_removes_pending_request(self):
        await self.worker.start()
        writer = self.worker.process.stdin
        with patch.object(writer, 'write', Mock(side_effect=BrokenPipeError('closed pipe'))):
            with self.assertRaises(BrokenPipeError):
                await self.worker.call('status')
        self.assertFalse(self.worker.pending)

    async def test_drain_failure_removes_pending_request(self):
        await self.worker.start()
        writer = self.worker.process.stdin
        with patch.object(writer, 'write', Mock()), patch.object(
                writer, 'drain', AsyncMock(side_effect=ConnectionResetError('closed pipe'))):
            with self.assertRaises(ConnectionResetError):
                await self.worker.call('status')
        self.assertFalse(self.worker.pending)

    async def test_cancel_during_drain_removes_pending_request(self):
        await self.worker.start()
        entered = asyncio.Event()

        async def drain():
            entered.set()
            await asyncio.Future()

        writer = self.worker.process.stdin
        with patch.object(writer, 'write', Mock()), patch.object(writer, 'drain', AsyncMock(side_effect=drain)):
            task = asyncio.create_task(self.worker.call('status'))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.worker.pending)

    async def test_timeout_keeps_send_receipt_and_cleans_pending(self):
        await self.worker.start()
        with patch.object(self.worker.process.stdin, 'write', Mock()):
            self.assertEqual(await self.worker.call('send', timeout=0.01),
                             {'state': 'unknown', 'receipt': 'browser_command_timeout'})
            with self.assertRaises(BrowserError):
                await self.worker.call('status', timeout=0.01)
        self.assertFalse(self.worker.pending)

    async def test_close_live_process_does_not_enter_auto_start_path(self):
        await self.worker.start()
        process = self.worker.process
        with patch.object(self.worker, 'start', AsyncMock(wraps=self.worker.start)) as start:
            await self.worker.close()
        start.assert_not_awaited()
        self.assertIsNotNone(process.returncode)
        self.spawn.assert_awaited_once()
        await self.worker.close()
        self.spawn.assert_awaited_once()

    async def test_close_command_timeout_still_reaps_process(self):
        await self.worker.start()
        call = self.worker._call

        async def short_call(process, action, timeout):
            return await call(process, action, timeout=0.01)

        with patch.object(self.worker, '_call', short_call), patch.object(
                self.worker.process.stdin, 'write', Mock()):
            await self.worker.close()
        self.assertIsNotNone(self.worker.process.returncode)
        self.assertTrue(self.worker.reader.done())
        self.assertFalse(self.worker.pending)

    async def test_close_oserror_still_reaps_process(self):
        await self.worker.start()
        with patch.object(self.worker, '_call', AsyncMock(side_effect=OSError('write failed'))):
            await self.worker.close()
        self.assertIsNotNone(self.worker.process.returncode)
        self.assertTrue(self.worker.reader.done())

    async def test_cancel_close_still_reaps_process_and_propagates_cancel(self):
        await self.worker.start()
        entered = asyncio.Event()

        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Future()

        with patch.object(self.worker, '_call', AsyncMock(side_effect=blocked)):
            closing = asyncio.create_task(self.worker.close())
            await entered.wait()
            closing.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await closing
        self.assertIsNotNone(self.worker.process.returncode)
        self.assertTrue(self.worker.reader.done())

    async def test_old_reader_eof_does_not_clear_restarted_process_requests(self):
        release = asyncio.Event()
        original_read = self.worker._read
        generation = 0

        async def read(*args):
            nonlocal generation
            generation += 1
            if generation == 1:
                await release.wait()
            return await original_read(*args)

        with patch.object(self.worker, '_read', read):
            await self.worker.start()
            await asyncio.sleep(0)
            old_reader = self.worker.reader
            self.worker.process.kill()
            await self.worker.process.wait()
            await self.worker.start()
            with patch.object(self.worker.process.stdin, 'write', Mock()):
                request = asyncio.create_task(self.worker.call('status'))
                await asyncio.sleep(0)
                release.set()
                await old_reader
                try:
                    self.assertFalse(request.done())
                    self.assertEqual(len(self.worker.pending), 1)
                finally:
                    request.cancel()
                    await asyncio.gather(request, return_exceptions=True)

    async def test_close_dead_or_unstarted_worker_does_not_spawn(self):
        await self.worker.close()
        self.spawn.assert_not_awaited()
        await self.worker.start()
        self.worker.process.kill()
        await self.worker.process.wait()
        await self.worker.reader
        await self.worker.close()
        self.spawn.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
