"""Failure recovery and latency behavior, with no browser/account/model access."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock,Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_processing_regressions as regression
from test_processing_regressions import item,Event,main
from astrbot_plugin_douyin_dm.bridge import BrowserError,Ledger
from astrbot_plugin_douyin_dm.pending_messages import PendingMessages,poll_interval,merge_window


class InboxPersistence(unittest.TestCase):
    def setUp(self):
        self.ledger=Ledger(':memory:');self.queue=PendingMessages(self.ledger)
        self.peer={'key':'peer','name':'Peer','conversation_type':'private'}
    def tearDown(self):self.ledger.close()

    def test_cursor_never_advances_past_failed_queue_write(self):
        old=item('old');new=item('new');ledger=self.ledger
        ledger.observe('peer',[old],prime=True)
        with self.assertRaises(OSError):
            ledger.observe('peer',[old,new],on_fresh=Mock(side_effect=OSError('disk full')))
        fresh=ledger.observe('peer',[old,new],on_fresh=lambda values:self.queue.add(self.peer,values))
        self.assertEqual(fresh,[new]);self.assertEqual(self.queue.next()[1],[new])

    def test_queue_deduplicates_if_cursor_write_fails_after_enqueue(self):
        old=item('old');new=item('new');ledger=self.ledger
        ledger.observe('peer',[old],prime=True)
        with patch.object(ledger,'put',side_effect=OSError('cursor failure')):
            with self.assertRaises(OSError):ledger.observe('peer',[old,new],on_fresh=lambda values:self.queue.add(self.peer,values))
        ledger.observe('peer',[old,new],on_fresh=lambda values:self.queue.add(self.peer,values))
        self.assertEqual(self.queue.next()[1],[new])
        self.queue.finish(self.peer,[new]);self.queue.add(self.peer,[new]);self.assertIsNone(self.queue.next())

    def test_restart_recovers_only_unsubmitted_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'messages.db';ledger=Ledger(path);queue=PendingMessages(ledger)
            queue.add(self.peer,[item('pending'),item('submitted')]);queue.submitted(self.peer,[item('submitted')],'job')
            ledger.close();ledger=Ledger(path)
            try:
                queue=PendingMessages(ledger)
                self.assertEqual([x['key'] for x in queue.next()[1]],['pending'])
                self.assertEqual(queue.status(),{'interrupted':1,'pending':1})
            finally:ledger.close()

    def test_retry_keeps_peer_order_and_is_bounded(self):
        self.queue.add(self.peer,[item('old')]);self.queue.retry('peer')
        self.queue.add(self.peer,[item('new')])
        self.assertIsNone(self.queue.next('peer'))
        other={'key':'other'};self.queue.add(other,[item('other-message')])
        self.assertEqual(self.queue.next()[0]['key'],'other')
        self.ledger.db.execute("UPDATE incoming_messages SET retry_at=0 WHERE peer_key='peer'");self.ledger.db.commit()
        self.assertEqual([x['key'] for x in self.queue.next('peer')[1]],['old','new'])
        self.queue.retry('peer');self.queue.retry('peer')
        self.assertEqual(self.queue.status()['failed'],1)
        self.assertNotEqual(self.queue.next()[0]['key'],'peer')

    def test_pause_does_not_replay_pending_or_submitted(self):
        self.queue.add(self.peer,[item('one'),item('two')]);self.queue.submitted(self.peer,[item('two')],'job')
        self.queue.discard();self.queue.add(self.peer,[item('one'),item('two')])
        self.assertIsNone(self.queue.next())

    def test_same_text_without_native_id_is_not_suppressed_forever(self):
        old=item('old');repeat={**item('repeat'),'native_id':''}
        capture=lambda values:self.queue.add(self.peer,values)
        self.ledger.observe('peer',[old],prime=True)
        self.ledger.observe('peer',[old,repeat],on_fresh=capture)
        first=self.queue.next()[1];self.queue.finish(self.peer,first)
        # A virtual list reuses the same fallback key for a new identical text.
        middle=item('middle');self.ledger.observe('peer',[repeat,middle],on_fresh=capture)
        self.queue.finish(self.peer,self.queue.next()[1])
        self.ledger.observe('peer',[middle,repeat],on_fresh=capture)
        second=self.queue.next()[1]
        self.assertEqual(second[0]['text'],'repeat')
        self.assertNotEqual(first[0]['_delivery_key'],second[0]['_delivery_key'])

    def test_no_native_id_cursor_failure_remains_idempotent(self):
        old=item('old');repeat={**item('repeat'),'native_id':''}
        capture=lambda values:self.queue.add(self.peer,values)
        self.ledger.observe('peer',[old],prime=True)
        with patch.object(self.ledger,'put',side_effect=OSError('cursor failed')):
            with self.assertRaises(OSError):self.ledger.observe('peer',[old,repeat],on_fresh=capture)
        self.ledger.observe('peer',[old,repeat],on_fresh=capture)
        self.assertEqual(len(self.queue.next()[1]),1)

    def test_empty_baseline_preserves_fallback_delivery_identity(self):
        old=item('old');repeat={**item('repeat'),'native_id':''}
        capture=lambda values:self.queue.add(self.peer,values)
        self.ledger.observe('peer',[old],prime=True)
        self.ledger.observe('peer',[old,repeat],on_fresh=capture)
        previous=self.queue.next()[1][0]['_delivery_key'];self.queue.discard()
        self.ledger.observe('peer',[],prime=True)
        self.ledger.observe('peer',[old],on_fresh=capture)
        self.ledger.observe('peer',[old,repeat],on_fresh=capture)
        self.assertNotEqual(self.queue.next()[1][0]['_delivery_key'],previous)

    def test_adaptive_timing_and_fixed_mode(self):
        config={'poll_seconds':4,'merge_seconds':3}
        self.assertEqual(poll_interval(config,100,now=101),1)
        self.assertEqual(poll_interval(config,100,now=131),4)
        self.assertEqual(merge_window(config),(3,0.8))
        self.assertEqual(merge_window({**config,'merge_seconds':0}),(0,0))
        self.assertEqual(merge_window({**config,'adaptive_polling':False}),(3,3))
        self.assertEqual(poll_interval({**config,'adaptive_polling':False},100,now=101),4)


class ReceiveIntegration(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=regression.ProcessingRegressions.asyncSetUp
    asyncTearDown=regression.ProcessingRegressions.asyncTearDown

    async def test_second_snapshot_failure_retains_message_then_recovers_once(self):
        o=self.owner;old=item('old');new=item('new')
        o.ledger.observe('peer',[old],prime=True);self.snapshot['items']=[old,new]
        o.config.update(merge_seconds=0.001,adaptive_polling=False)
        o.browser.call.side_effect=[self.snapshot,BrowserError('temporary disconnect')]
        with self.assertRaises(BrowserError):await o._receive_once()
        self.assertEqual(o.inbox.status(),{'pending':1});o.platform.commit_event.assert_not_called()
        o.ledger.db.execute('UPDATE incoming_messages SET retry_at=0');o.ledger.db.commit()
        o.browser.call.side_effect=None
        await o._receive_once();await o._receive_once()
        self.assertEqual(o.platform.commit_event.call_count,1);self.assertIsNone(o.inbox.next())

    async def test_unknown_send_outcome_never_reenters_queue(self):
        o=self.owner;o.config['merge_seconds']=0;o.inbox.add(self.peer,[item('new')])
        def unknown(event):
            o.ledger.job(event.job_id,'unknown');event.done.set_result('finished')
        o.platform.commit_event.side_effect=unknown
        await o._receive_once();await o._receive_once()
        self.assertEqual(o.platform.commit_event.call_count,1)
        self.assertEqual(o.ledger.db.execute('SELECT state FROM jobs').fetchone()[0],'unknown')

    async def test_failed_group_batch_does_not_replay_earlier_batch(self):
        o=self.owner;self.peer['conversation_type']='group';o.config['group_reply_mode']='所有新消息'
        first=item('first');second={**item('second'),'sender_id':'other'};o.inbox.add(self.peer,[first,second])
        o._process_items=AsyncMock(side_effect=[None,BrowserError('pre-submit failure')])
        with self.assertRaises(BrowserError):await o._handle([first,second],self.peer,delivery=o.inbox)
        o.inbox.retry('peer');o.ledger.db.execute('UPDATE incoming_messages SET retry_at=0');o.ledger.db.commit()
        self.assertEqual(o.inbox.next()[1],[second])

    async def test_pending_rechecks_permissions_before_browser_or_model(self):
        o=self.owner;o.inbox.add(self.peer,[item('new')]);o._check_whitelist.side_effect=BrowserError('removed')
        with self.assertRaises(BrowserError):await o._receive_once()
        o.browser.call.assert_not_awaited();o.platform.commit_event.assert_not_called()

    async def test_timeout_signals_native_agent_stop_and_preserves_timeout_state(self):
        o=self.owner;captured=[];o.platform.commit_event.side_effect=captured.append
        async def timeout(*args,**kwargs):raise asyncio.TimeoutError()
        with patch.object(main.asyncio,'wait_for',timeout):await o._process_items([item('timeout')],self.peer)
        event=captured[0];self.assertTrue(event.get_extra('agent_stop_requested'));self.assertTrue(event.is_stopped())
        await o.agent_finished(event,None,None)
        self.assertEqual(o.ledger.db.execute('SELECT state FROM jobs').fetchone()[0],'timeout')
        # Verify the installed AstrBot watcher consumes the plugin's exact signal.
        from astrbot.core.astr_agent_run_util import _watch_agent_stop_signal
        runner=Mock();runner.done.return_value=False
        await _watch_agent_stop_signal(runner,event);runner.request_stop.assert_called_once()

    async def test_pause_during_conversation_creation_never_submits(self):
        o=self.owner;self.manager.get_curr_conversation_id.return_value=None
        async def pause(*args,**kwargs):await o.control('pause')
        self.manager.new_conversation.side_effect=pause
        await o._process_items([item('new')],self.peer)
        o.platform.commit_event.assert_not_called();self.assertIsNone(o.current_event)

    async def test_pause_stops_current_agent_even_if_send_future_already_completed(self):
        o=self.owner;event=Event(o,'job',[],[],[],peer=self.peer)
        event.done.set_result('finished');o.current_event=event
        await o.control('pause')
        self.assertTrue(event.get_extra('agent_stop_requested'));self.assertTrue(event.is_stopped())

    async def test_monitor_keeps_pause_status_when_pause_happens_inside_receive(self):
        o=self.owner;o.browser.process=Mock(returncode=None)
        async def receive():await o.control('pause');o.closed=True
        o._receive_once=receive
        with patch.object(main.asyncio,'sleep',AsyncMock()):await o._monitor()
        self.assertEqual(o.state,'paused')

    async def test_smart_group_plan_uses_one_call_and_validates_reference(self):
        o=self.owner;self.peer['conversation_type']='group'
        o.config.update(group_reply_mode='智能接话',group_conversation={'reply_probability':1,'reply_cooldown_seconds':0})
        share=item('share','video');o.group_conversation.observe({'peer':self.peer,'items':[share]})
        o._process_items=AsyncMock()
        o.group_conversation._generate=AsyncMock(return_value=json.dumps({'style':'REPLY','media_ids':['share'],'needs_clarification':False}))
        await o._handle([item('request')],self.peer)
        o.group_conversation._generate.assert_awaited_once()
        self.assertEqual(o._process_items.call_args.kwargs['referenced_media'][0]['key'],'share')
        o.group_conversation._generate.return_value='{"style":"REPLY","media_ids":["foreign"],"needs_clarification":false}'
        await o._handle([item('another')],self.peer)
        self.assertEqual(o._process_items.call_args.kwargs['referenced_media'],[])
        self.assertTrue(o._process_items.call_args.kwargs['reference_notice'])

    async def test_clarification_and_topic_do_not_download_candidate_media(self):
        o=self.owner;self.peer['conversation_type']='group';o.config['group_conversation']={'reply_probability':1,'reply_cooldown_seconds':0}
        share=item('share','video');o.group_conversation.observe({'peer':self.peer,'items':[share]})
        recent=o.group_conversation.recent(self.peer,[])
        for style,clarify in [('TOPIC',False),('REPLY',True),('IGNORE',False)]:
            o.group_conversation._generate=AsyncMock(return_value=json.dumps({'style':style,'media_ids':['share'],'needs_clarification':clarify}))
            result=await o.group_conversation.plan(self.peer,[item('request')],recent)
            self.assertEqual(result[1],[])


if __name__=='__main__':unittest.main(verbosity=2)
