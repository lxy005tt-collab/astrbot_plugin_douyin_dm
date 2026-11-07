"""Reader recovery checks using a real Python JSON-lines subprocess."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mimi_douyin.errors import BrowserError
from mimi_douyin.transport import BrowserWorker


LIMIT = 16 * 1024 * 1024


CHILD = r"""
import json, sys

limit = 16 * 1024 * 1024
pending = []

def line_for(request, size):
    reply = {'id': request['id'], 'ok': True, 'result': {'text': ''}}
    base = json.dumps(reply, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    remainder = (size - len(base)) % 3
    reply['result']['text'] = 'x' * remainder + '中' * ((size - len(base) - remainder) // 3)
    line = json.dumps(reply, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    assert len(line) == size
    assert '中'.encode('utf-8') in line
    return line

def send(line, chunked=False):
    if chunked:
        for offset in range(0, len(line), 65537):
            sys.stdout.buffer.write(line[offset:offset + 65537])
            sys.stdout.buffer.flush()
    else:
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
    sys.stdout.buffer.write(b'\n')
    sys.stdout.buffer.flush()

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    action = request['action']
    if action == 'limit_minus':
        send(line_for(request, limit - 1))
    elif action == 'limit_exact':
        send(line_for(request, limit))
    elif action.startswith('pending_'):
        pending.append(request)
        if len(pending) == 3:
            send(line_for(pending[0], limit + 1), chunked=True)
            pending.clear()
    else:
        reply = {'id': request['id'], 'ok': True, 'result': {'action': action}}
        send(json.dumps(reply, separators=(',', ':')).encode('utf-8'))
"""


class ReaderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = BrowserWorker({
            'node_binary': 'python-fixture',
            'browser_profile': 'profile',
            'media_dir': 'media',
            'playwright_package': 'playwright',
        })
        self.processes = []
        create = asyncio.create_subprocess_exec

        async def spawn(*args, **kwargs):
            process = await create(sys.executable, '-u', '-c', CHILD, **kwargs)
            self.processes.append(process)
            return process

        self.spawn_patch = patch(
            'mimi_douyin.transport.asyncio.create_subprocess_exec', spawn
        )
        self.spawn_patch.start()

    async def asyncTearDown(self):
        try:
            await asyncio.wait_for(self.worker.close(), timeout=2)
        except BaseException:
            pass
        finally:
            for process in self.processes:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        pass
            reader = self.worker.reader
            if reader and not reader.done():
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            self.spawn_patch.stop()

    async def test_utf8_line_boundaries_and_chunked_overflow_recovery(self):
        below = await self.worker.call('limit_minus', timeout=5)
        exact = await self.worker.call('limit_exact', timeout=5)

        def encoded_size(request_id, result):
            reply = {'id': request_id, 'ok': True, 'result': result}
            return len(json.dumps(reply, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))

        self.assertIn('中', below['text'])
        self.assertIn('中', exact['text'])
        self.assertEqual(encoded_size(1, below), LIMIT - 1)
        self.assertEqual(encoded_size(2, exact), LIMIT)

        old_process = self.worker.process
        old_reader = self.worker.reader
        pending_calls = [
            asyncio.create_task(self.worker.call(f'pending_{index}', timeout=5))
            for index in range(3)
        ]
        deadline = asyncio.get_running_loop().time() + 3
        while len(self.worker.pending) < 3 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
        self.assertEqual(len(self.worker.pending), 3)

        failures = await asyncio.wait_for(
            asyncio.gather(*pending_calls, return_exceptions=True), timeout=8
        )
        self.assertTrue(all(isinstance(error, BrowserError) for error in failures), failures)
        self.assertTrue(old_reader.done())

        recovered = await asyncio.wait_for(asyncio.gather(
            self.worker.call('after_overflow_a', timeout=5),
            self.worker.call('after_overflow_b', timeout=5),
        ), timeout=12)
        self.assertEqual(recovered, [
            {'action': 'after_overflow_a'}, {'action': 'after_overflow_b'}
        ])
        self.assertEqual(len(self.processes), 2)
        self.assertIsNotNone(old_process.returncode)
        self.assertFalse(self.worker.pending)


if __name__ == '__main__':
    unittest.main()
