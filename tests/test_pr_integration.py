"""Integration boundaries between PR lifecycle/routing and the durable inbox."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from test_auto_switching import ConversationSwitching, fixture, item
from mimi_douyin.transport import BrowserWorker


class IntegrationChecks(unittest.IsolatedAsyncioTestCase):
    async def test_open_retains_private_whitelist_with_serialized_open(self):
        worker=BrowserWorker({'browser_profile':'offline','media_dir':'offline',
            'playwright_package':'playwright','private_whitelist':['permitted-peer']})
        peer={'key':'permitted-peer'}
        with patch.object(worker,'call',AsyncMock(return_value={})) as call:
            await worker.open(peer)
        self.assertEqual(call.await_args.args[1]['private_whitelist'],['permitted-peer'])
        self.assertEqual(call.await_args.args[1]['restore_peer'],peer)

    async def test_failed_capture_does_not_advance_cursor_or_service_window(self):
        owner,rows,snapshots,calls,state=fixture()
        owner.config['conversation_hold_seconds']=10
        switching=ConversationSwitching(owner)
        await switching.poll()
        rows[1]['latest_message_id']='g-new'
        snapshots['g']['items'].extend([{**item('no-id','same text'),'native_id':None}, item('g-new','new')])
        attempts=[]
        def fail(peer,fresh):
            attempts.append(fresh)
            raise OSError('synthetic inbox write failure')
        with self.assertRaises(OSError):
            await switching.poll(capture=fail)
        self.assertEqual(switching.frontiers['g'],'g-old')
        self.assertNotIn('g',switching.served)
        self.assertNotIn('g',switching.hold_until)
        received=[]
        await switching.poll(capture=lambda peer,fresh: received.extend(fresh))
        self.assertEqual([x['key'] for x in received],['no-id','g-new'])
        self.assertEqual(attempts[0][0]['_delivery_key'],received[0]['_delivery_key'])
        self.assertEqual(switching.frontiers['g'],'g-new')
        self.assertIn('g',switching.served)
        self.assertIn('g',switching.hold_until)
        self.assertIsNone(await switching.poll(capture=lambda *_: self.fail('replayed')))


if __name__=='__main__':unittest.main()
