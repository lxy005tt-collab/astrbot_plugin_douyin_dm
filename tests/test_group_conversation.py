"""Check group context, non-mention decisions and cross-member media references."""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_douyin_dm.bridge import Ledger,DouyinEvent,DouyinPlatform
from astrbot_plugin_douyin_dm.main import MimiDouyinDM
from astrbot_plugin_douyin_dm.group_conversation import GroupConversation,validate_settings


def item(key,sender,text,kind='text'):
    return dict(key=key,native_id=key,fingerprint=key,sender='peer',sender_id=sender,sender_name=sender,
        text=text,kind=kind,links=['https://www.douyin.com/video/1234567890123456'] if kind=='video' else [])


def setup(directory,mode='仅@机器人'):
    owner=object.__new__(MimiDouyinDM);owner.ledger=Ledger(Path(directory)/'messages.db')
    owner.config={'provider_id':'example-judge','group_reply_mode':mode,'group_conversation':{'reply_probability':1}}
    owner.context=NS(llm_generate=AsyncMock(return_value=NS(completion_text='TOPIC')),get_event_queue=lambda:asyncio.Queue())
    owner.platform=DouyinPlatform(owner);owner.job_lock=asyncio.Lock();owner._process_items=AsyncMock()
    owner.group_conversation=GroupConversation(owner)
    peer=dict(key='example-group',conversation_type='group',name='Example group',self_user_id='bot',self_user_name='ExampleBot')
    return owner,peer


def test_unmentioned_messages_are_available_to_later_mention_with_speaker_identity():
    async def check(directory):
        owner,peer=setup(directory)
        await owner._handle([item('1','Alice','The trip is on Saturday'),item('2','Bob','Bring an umbrella')],peer)
        owner._process_items.assert_not_called()
        await owner._handle([item('3','Charlie','@ExampleBot What are we planning?')],peer)
        payload=owner._process_items.call_args.kwargs['group_context']
        assert [row['sender_id'] for row in payload['messages']]==['Alice','Bob']
        assert 'Saturday' in payload['messages'][0]['text'];owner.context.llm_generate.assert_not_called()
        other={**peer,'key':'other-group'};assert not owner.group_conversation.recent(other,[])
        owner.ledger.close()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(check(directory))


def test_smart_verdict_cooldown_sampling_and_direct_mention_bypass():
    async def check(directory):
        owner,peer=setup(directory,'智能接话')
        await owner._handle([item('1','Alice','The garden is blooming beautifully')],peer)
        assert owner._process_items.call_args.kwargs['group_context']['reply_style']=='TOPIC'
        owner.group_conversation.sent(peer,'TOPIC')
        await owner._handle([item('2','Bob','It is a lovely day')],peer)
        assert owner._process_items.await_count==1
        await owner._handle([item('3','Bob','@ExampleBot hello')],peer)
        assert owner._process_items.await_count==2
        owner.config['group_conversation'].update(reply_probability=0,reply_cooldown_seconds=0)
        owner.context.llm_generate.reset_mock()
        await owner._handle([item('4','Bob','Another public discussion')],peer)
        assert owner._process_items.await_count==2;owner.context.llm_generate.assert_not_called()
        owner.ledger.close()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(check(directory))


def test_another_member_can_request_previous_share_without_becoming_its_author():
    async def check(directory):
        owner,peer=setup(directory)
        await owner._handle([item('intro-A','Alice','Earlier message with visible member name')],peer)
        share=item('video-A','Alice','A shared work','video')
        share['sender_name']=''
        await owner._handle([share],peer)
        owner.context.llm_generate.return_value=NS(completion_text=json.dumps({'media_ids':['video-A'],'needs_clarification':False}))
        trigger=item('mention-B','Bob','@ExampleBot take a look at that video')
        await owner._handle([trigger],peer)
        called=owner._process_items.call_args
        assert called.args[0]==[trigger]
        assert called.kwargs['referenced_media'][0]['sender_id']=='Alice'
        assert called.kwargs['referenced_media'][0]['sender_name']=='Alice'
        assert called.kwargs['referenced_media'][0]['key']=='video-A'
        assert called.kwargs['referenced_media'][0]['sender']=='peer'
        event=DouyinEvent(owner,'reference-test',[trigger],[],[],peer=peer)
        assert event.get_sender_id()=='Bob'
        owner.group_conversation.media_read(peer,[share],'Actual media observation')
        assert next(row for row in owner.group_conversation.recent(peer,[trigger]) if row['id']=='video-A')['media_observation']=='Actual media observation'
        owner.ledger.close()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(check(directory))


def test_unknown_share_reference_and_failed_proactive_judge_do_not_block_mentions():
    async def check(directory):
        owner,peer=setup(directory)
        await owner._handle([item('video-A','Alice','Shared work','video')],peer)
        owner.context.llm_generate.return_value=NS(completion_text='{"media_ids":["not-in-this-group"],"needs_clarification":false}')
        await owner._handle([item('2','Bob','@ExampleBot look at the share')],peer)
        assert owner._process_items.call_args.kwargs['referenced_media']==[]
        assert owner._process_items.call_args.kwargs['reference_notice']
        owner.config['group_reply_mode']='智能接话';owner.context.llm_generate.side_effect=TimeoutError()
        await owner._handle([item('3','Bob','A new public topic')],peer)
        assert owner._process_items.await_count==1
        owner.config['group_conversation']['reference_previous_media']=False
        await owner._handle([item('4','Bob','@ExampleBot hello')],peer)
        assert owner._process_items.await_count==2
        owner.ledger.close()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(check(directory))


def test_context_retention_and_custom_prompts_apply_without_persona_changes():
    async def check(directory):
        owner,peer=setup(directory,'智能接话')
        owner.config['group_conversation'].update(context_messages=2,context_minutes=1,judge_prompt='Custom eligibility rules',reply_prompt='Custom reply style')
        engine=owner.group_conversation
        engine.observe({'peer':peer,'items':[item('1','Alice','Older'),item('2','Bob','Recent'),item('3','Bob','Latest')]})
        assert [row['id'] for row in engine.recent(peer,[])]==['2','3']
        data=engine._load(peer);data['messages'][0]['observed_at']=time.time()-120;engine._save(peer,data)
        assert [row['id'] for row in engine.recent(peer,[])]==['3']
        await owner._handle([item('4','Alice','A public thought')],peer)
        assert 'Custom eligibility rules' in owner.context.llm_generate.call_args.kwargs['system_prompt']
        event=DouyinEvent(owner,'context-test',[item('4','Alice','A public thought')],[],[],peer=peer)
        event.set_extra('douyin_group_context',owner._process_items.call_args.kwargs['group_context']);event.set_extra('douyin_group_reply_style','TOPIC')
        request=NS(extra_user_content_parts=[NS(text='Other memory context')]);engine.inject(event,request)
        assert request.extra_user_content_parts[0].text=='Other memory context'
        assert 'Custom reply style' in request.extra_user_content_parts[-1].text
        owner.config['group_conversation']['context_enabled']=False;assert engine.recent(peer,[])==[]
        owner.ledger.close()
    with tempfile.TemporaryDirectory() as directory:asyncio.run(check(directory))


if __name__=='__main__':
    for name,check in list(globals().items()):
        if name.startswith('test_') and callable(check):check();print('PASS',name)
