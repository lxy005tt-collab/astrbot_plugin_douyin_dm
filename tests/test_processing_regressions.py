"""Offline regressions for pause, failed initialization and media attribution."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_douyin_dm import main
from astrbot_plugin_douyin_dm.bridge import BrowserError, Ledger
from astrbot_plugin_douyin_dm.conversation_switching import ConversationSwitching
from astrbot_plugin_douyin_dm.group_conversation import GroupConversation
from astrbot_plugin_douyin_dm.pending_messages import PendingMessages


def item(key,kind='text'):
    return dict(key=key,native_id=key,fingerprint=key,sender='peer',sender_id='member',
        sender_name='Member',text=key,kind=kind,links=[])


class Event:
    def __init__(self,owner,job_id,items,paths,errors,*,peer,**kwargs):
        self.job_id=job_id;self.peer_key=peer['key'];self.paths=paths
        self.done=asyncio.get_running_loop().create_future();self.extra={}
        self.unified_msg_origin='mimi-douyin:FriendMessage:'+peer['key']
    def set_extra(self,key,value):self.extra[key]=value
    def get_extra(self,key,default=None):return self.extra.get(key,default)
    def stop_event(self):self.extra['stopped']=True
    def is_stopped(self):return self.extra.get('stopped',False)


class ProcessingRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner=o=object.__new__(main.MimiDouyinDM)
        o.config={'auto_reply_enabled':True,'remember_videos':False};o.closed=False
        o.status=Mock(return_value={});o._save_config=Mock();o.current_event=None
        o.action_lock=asyncio.Lock();o.job_lock=asyncio.Lock();o.ledger=Ledger(':memory:')
        o.inbox=PendingMessages(o.ledger);o.last_activity=0
        self.peer=peer=dict(key='peer',name='Peer',conversation_type='private',conversation_id='cid')
        o.binding={'peer':peer}
        self.snapshot=dict(ready=True,direction_proven=True,peer=peer,items=[])
        o.browser=NS(call=AsyncMock(return_value=self.snapshot))
        o._check_peer=Mock();o._check_profile=Mock();o._check_whitelist=Mock()
        o.switching=ConversationSwitching(o);o.group_conversation=GroupConversation(o)
        o.platform=NS(status=None,commit_event=Mock(side_effect=lambda event:event.done.set_result('finished')))
        self.manager=NS(get_curr_conversation_id=AsyncMock(return_value='existing'),new_conversation=AsyncMock())
        o.context=NS(conversation_manager=self.manager)
        self.event_patch=patch.object(main,'DouyinEvent',Event);self.event_patch.start()

    async def asyncTearDown(self):
        self.event_patch.stop();self.owner.ledger.close()

    async def test_resume_ignores_paused_messages_but_accepts_later_messages(self):
        o=self.owner;old=item('old');paused=item('paused');new=item('new')
        o.ledger.observe('peer',[old],prime=True)
        await o.control('pause');self.snapshot['items']=[old,paused]
        await o.control('start')
        self.assertEqual(o.ledger.observe('peer',[old,paused]),[])
        self.assertEqual(o.ledger.observe('peer',[old,paused,new]),[new])

    async def test_automatic_resume_keeps_existing_baseline_path(self):
        o=self.owner;o.config['auto_switch_enabled']=True
        o.switching=NS(reset=Mock(),poll=AsyncMock())
        await o.control('start')
        o.switching.poll.assert_awaited_once()

    async def test_initialization_errors_clear_event_and_allow_next_message(self):
        o=self.owner
        for operation in (self.manager.get_curr_conversation_id,self.manager.new_conversation,o.platform.commit_event):
            with self.subTest(operation=operation):
                self.manager.get_curr_conversation_id.return_value=None
                previous=operation.side_effect;operation.side_effect=RuntimeError('synthetic initialization failure')
                try:
                    with self.assertRaises(RuntimeError):await o._process_items([item('first')],self.peer)
                    self.assertIsNone(o.current_event)
                    self.assertEqual(o.ledger.db.execute('SELECT state FROM jobs ORDER BY updated DESC LIMIT 1').fetchone()[0],'failed')
                finally:operation.side_effect=previous
                await o._process_items([item('next')],self.peer)
                self.assertIsNone(o.current_event)

    async def test_cancellation_clears_event(self):
        o=self.owner;entered=asyncio.Event()
        async def pending(*args):
            entered.set();await asyncio.Future()
        self.manager.get_curr_conversation_id.side_effect=pending
        task=asyncio.create_task(o._process_items([item('cancel')],self.peer))
        await entered.wait();event=o.current_event;task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertIsNone(o.current_event);self.assertTrue(event.done.cancelled())
        self.assertEqual(o.ledger.db.execute('SELECT state FROM jobs').fetchone()[0],'interrupted')

    async def test_failed_and_skipped_media_do_not_receive_successful_summary(self):
        o=self.owner;self.peer['conversation_type']='group'
        items=[item('good','video'),item('failed','video'),item('skipped','video')]
        o.group_conversation.observe({'peer':self.peer,'items':items})
        o._prepare_video_item=AsyncMock(side_effect=[{'path':'fake.mp4'},BrowserError('download failed'),
            {'state':'skipped','message':'duration limit'}])
        transcript={'summary':'Only the first work was read','provider_id':'fake'}
        with patch.object(main,'transcribe_video',AsyncMock(return_value=transcript)):
            await o._process_items(items,self.peer)
        rows=o.group_conversation._load(self.peer)['messages']
        self.assertEqual(rows[0]['media_state'],'已实际读取')
        for row in rows[1:]:
            self.assertEqual(row['media_state'],'尚未读取');self.assertNotIn('media_observation',row)

    async def test_failed_transcription_does_not_mark_downloaded_media_read(self):
        o=self.owner;self.peer['conversation_type']='group';items=[item('good','video')]
        o.group_conversation.observe({'peer':self.peer,'items':items})
        o._prepare_video_item=AsyncMock(return_value={'path':'fake.mp4'})
        with patch.object(main,'transcribe_video',AsyncMock(side_effect=BrowserError('perception failed'))):
            await o._process_items(items,self.peer)
        self.assertEqual(o.group_conversation._load(self.peer)['messages'][0]['media_state'],'尚未读取')

    async def test_backfill_handles_images_video_and_skipped_without_aborting(self):
        o=self.owner;items=[item(key,'video') for key in ('skipped','images','video')]
        self.snapshot['items']=items
        o.ledger.job('historical','sent',{'kinds':['video'],'message_keys':[x['key'] for x in items]})
        watched=o.ledger.db.execute('SELECT updated FROM jobs').fetchone()[0]
        sources=[{'state':'skipped','reason':'duration_limit'},
            {'kind':'images','images':[{'path':'fake.jpg'}],'url':'https://www.douyin.com/note/123'},
            {'kind':'video','path':'fake.mp4'}]
        o._prepare_video_item=AsyncMock(side_effect=sources)
        remember=AsyncMock(return_value={'memory_id':'fake'})
        with patch.object(main,'remember_video',remember):result=await o.control('remember_videos')
        self.assertEqual(len(result['skipped']),1);self.assertEqual(len(result['saved_videos']),2)
        calls=remember.await_args_list
        self.assertEqual(calls[0].args[1].paths,[])
        self.assertEqual(calls[0].args[2],[sources[1]])
        self.assertEqual(calls[1].args[1].paths,['fake.mp4'])
        self.assertTrue(all(call.args[3]==watched for call in calls))


if __name__=='__main__':unittest.main(verbosity=2)
