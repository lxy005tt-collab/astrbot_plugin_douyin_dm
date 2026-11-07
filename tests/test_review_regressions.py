"""Offline regressions for account identity, context locks and send receipts."""
import asyncio
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import test_processing_regressions as regression
from test_processing_regressions import item
from astrbot_plugin_douyin_dm import setup_api
from astrbot_plugin_douyin_dm.bridge import BrowserError, addressed_to_bot


class ReviewRegressions(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = regression.ProcessingRegressions.asyncSetUp
    asyncTearDown = regression.ProcessingRegressions.asyncTearDown

    async def test_group_mention_survives_own_messages_leaving_view(self):
        owner = self.owner
        peer = {**self.peer, 'conversation_type': 'group',
                'self_user_id': '999', 'self_user_name': 'ExampleBot'}
        owner.with_account_identity(peer)
        later = {**peer, 'self_user_id': '', 'self_user_name': ''}
        mention = {**item('mention'), 'text': '请看一下',
                   'mentioned_ids': ['999'], 'mentioned_bot': False}
        owner._process_items = AsyncMock()
        owner.inbox.add(later, [mention])
        await owner._handle([mention], later, delivery=owner.inbox)
        owner._process_items.assert_awaited_once()
        resolved = owner._process_items.call_args.args[1]
        self.assertEqual(resolved['self_user_id'], '999')
        self.assertEqual(resolved['self_user_name'], 'ExampleBot')
        self.assertTrue(owner._process_items.call_args.kwargs['group_context']['mentioned_self'])
        self.assertIsNone(owner.inbox.next())
        self.assertEqual(owner.config.get('group_mention_names', []), [])

    async def test_observed_account_change_drops_old_name_and_mention_id(self):
        owner = self.owner
        owner.with_account_identity({**self.peer, 'self_user_id': '999', 'self_user_name': 'OldBot'})
        owner.with_account_identity({**self.peer, 'self_user_id': '888', 'self_user_name': ''})
        later = owner.with_account_identity(self.peer)
        self.assertEqual(later['self_user_id'], '888')
        self.assertEqual(later['self_aliases'], [])
        self.assertFalse(addressed_to_bot([{'text': '@OldBot hello', 'mentioned_ids': ['999']}], later))
        self.assertTrue(addressed_to_bot([{'text': 'hello', 'mentioned_ids': ['888']}], later))

    async def test_explicit_rebind_without_identity_does_not_reuse_previous_account(self):
        owner = self.owner
        owner.with_account_identity({**self.peer, 'self_user_id': '999', 'self_user_name': 'OldBot'})
        owner.config['auto_reply_enabled'] = False
        await owner.control('bind')
        resolved = owner.with_account_identity(self.peer)
        self.assertFalse(resolved.get('self_user_id'))
        self.assertFalse(resolved['self_aliases'])

    async def test_context_link_rejects_busy_reply_without_waiting_for_activity_lock(self):
        owner = self.owner
        owner.context_sharing = NS(save_link=AsyncMock(), remove_link=Mock())
        api = setup_api.SetupAPI(owner)
        async with owner.job_lock, owner.action_lock:
            for body in ({'target_session': 'qq:FriendMessage:example'}, {'action': 'remove'}):
                with patch.object(setup_api, 'request', NS(json=AsyncMock(return_value=body))):
                    result = await asyncio.wait_for(api.context_link(), 0.2)
                self.assertEqual(result['status'], 'error')
                self.assertIn('正在处理', result['message'])
        owner.context_sharing.save_link.assert_not_awaited()
        owner.context_sharing.remove_link.assert_not_called()

    async def test_context_link_rechecks_job_after_waiting_for_action_lock(self):
        owner = self.owner
        owner.context_sharing = NS(remove_link=Mock())
        api = setup_api.SetupAPI(owner)
        with patch.object(setup_api, 'request', NS(json=AsyncMock(return_value={'action': 'remove'}))):
            async with owner.action_lock:
                task = asyncio.create_task(api.context_link())
                await asyncio.sleep(0)
                await owner.job_lock.acquire()
            try:
                result = await asyncio.wait_for(task, 0.2)
                self.assertEqual(result['status'], 'error')
            finally:
                owner.job_lock.release()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        owner.context_sharing.remove_link.assert_not_called()

    async def test_context_link_save_and_remove_still_work_when_idle(self):
        owner = self.owner
        owner.context_sharing = NS(save_link=AsyncMock(return_value={'saved': True}), remove_link=Mock())
        api = setup_api.SetupAPI(owner)
        for body in ({'target_session': 'qq:FriendMessage:example'}, {'action': 'remove'}):
            with patch.object(setup_api, 'request', NS(json=AsyncMock(return_value=body))):
                self.assertEqual((await api.context_link())['status'], 'ok')
        owner.context_sharing.save_link.assert_awaited_once()
        owner.context_sharing.remove_link.assert_called_once_with(owner.session_id())
        self.assertFalse(owner.action_lock.locked())
        self.assertFalse(owner.job_lock.locked())

    def prepare_send(self):
        owner = self.owner
        owner.current_event = NS(job_id='job', peer_key=self.peer['key'],
            message_obj=NS(raw_message={'conversation_type': 'private'}),
            get_extra=lambda key, default=None: default)
        owner.context.get_registered_star = Mock(return_value=None)
        owner.ledger.job('job', 'generating')
        return owner

    async def test_preflight_receipt_is_not_unknown_and_allows_corrected_text(self):
        owner = self.prepare_send()
        owner.browser.call.side_effect = [self.snapshot,
            {'state': 'not_sent', 'receipt': 'invalid_text', 'error': '回复为空或超过当前单条文字限制。'},
            self.snapshot, {'state': 'sent', 'receipt': 'offline_echo'}]
        with self.assertRaisesRegex(BrowserError, '单条文字限制'):
            await owner.send_text('job', '答' * 2001, self.peer['key'])
        self.assertEqual(owner.ledger.db.execute('SELECT state FROM jobs').fetchone()[0], 'not_sent')
        outbox = json.loads(owner.ledger.db.execute("SELECT value FROM state WHERE key LIKE 'outbox:%'").fetchone()[0])
        self.assertEqual(outbox['state'], 'not_sent')
        self.assertEqual(owner.browser.call.await_count, 2)  # No automatic resend.
        await owner.send_text('job', '简短回复', self.peer['key'])
        self.assertEqual(owner.ledger.db.execute('SELECT state FROM jobs').fetchone()[0], 'sent')

    async def test_ambiguous_send_error_still_blocks_later_segments(self):
        owner = self.prepare_send()
        owner.browser.call.side_effect = [self.snapshot, BrowserError('connection lost after click')]
        with self.assertRaises(BrowserError):
            await owner.send_text('job', '回复', self.peer['key'])
        with self.assertRaisesRegex(BrowserError, '尚未确认'):
            await owner.send_text('job', '后续分段', self.peer['key'])
        self.assertEqual(owner.browser.call.await_count, 2)
        self.assertEqual(owner.ledger.db.execute('SELECT state FROM jobs').fetchone()[0], 'unknown')


if __name__ == '__main__':
    unittest.main(verbosity=2)
