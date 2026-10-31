"""Behavior checks for explicit-allowlist routing, without a real account."""
import asyncio
import copy
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_douyin_dm.conversation_switching import ConversationSwitching
from astrbot_plugin_douyin_dm.bridge import BrowserError


def item(native,text,sender='peer'):
    return dict(native_id=native,key=native,fingerprint=text,text=text,sender=sender)


def fixture():
    rows=[dict(key='private',conversation_id='p',conversation_type=1,latest_message_id='p-old',unread_count=99),
          dict(key='group',conversation_id='g',conversation_type=2,latest_message_id='g-old',unread_count=500),
          dict(key='unapproved',conversation_id='x',conversation_type=2,latest_message_id='x-old',unread_count=999)]
    snapshots={cid:dict(ready=True,peer=dict(key=key,conversation_id=cid,conversation_type=kind),items=[item(cid+'-old','Old history')])
        for cid,key,kind in [('p','private','private'),('g','group','group'),('x','unapproved','group')]}
    calls=[];state={'active':'p'}
    async def call(action,args=None):
        calls.append((action,args))
        if action=='conversations':return {'conversations':copy.deepcopy(rows)}
        if action=='select_conversation':state['active']=args['conversation_id']
        return copy.deepcopy(snapshots[state['active']])
    owner=NS(config={'private_whitelist':['private'],'group_whitelist':['group'],'group_chat_enabled':True},
        browser=NS(call=call),ledger=NS(observe=Mock(),put=Mock()),job_lock=asyncio.Lock(),current_event=None,
        binding={'peer':snapshots['p']['peer']},_check_peer=Mock(),_check_whitelist=Mock(),_check_profile=Mock())
    return owner,rows,snapshots,calls,state


def test_only_new_ids_route_between_allowed_private_and_group():
    async def check():
        owner,rows,snapshots,calls,state=fixture();routing=ConversationSwitching(owner)
        assert await routing.poll() is None
        assert not any(action=='select_conversation' for action,args in calls)
        rows[1]['latest_message_id']='g-new';snapshots['g']['items'].append(item('g-new','New group message'))
        rows[2]['latest_message_id']='x-new'
        snapshot,fresh=await routing.poll()
        assert [value['native_id'] for value in fresh]==['g-new'] and owner.binding['peer']['key']=='group'
        assert await routing.poll() is None
        rows[0]['latest_message_id']='p-new';snapshots['p']['items'].append(item('p-new','New private message'))
        snapshot,fresh=await routing.poll()
        assert [value['native_id'] for value in fresh]==['p-new'] and owner.binding['peer']['key']=='private'
        assert all(not args or args.get('conversation_id')!='x' for action,args in calls)
    asyncio.run(check())


def test_busy_reply_keeps_target_and_own_messages_do_not_trigger_reply():
    async def check():
        owner,rows,snapshots,calls,state=fixture();routing=ConversationSwitching(owner)
        await routing.poll();rows[1]['latest_message_id']='g-new';snapshots['g']['items'].append(item('g-new','Group message'))
        owner.current_event=object();before=len(calls);assert await routing.poll() is None;assert len(calls)==before
        owner.current_event=None;await owner.job_lock.acquire()
        assert await routing.poll() is None;owner.job_lock.release()
        snapshot,fresh=await routing.poll();assert len(fresh)==1
        rows[1]['latest_message_id']='bot-answer';snapshots['g']['items'].append(item('bot-answer','Bot answer','me'))
        snapshot,fresh=await routing.poll();assert not fresh
    asyncio.run(check())


def test_removed_whitelist_and_missing_history_boundary_do_not_replay_history():
    async def check():
        owner,rows,snapshots,calls,state=fixture();routing=ConversationSwitching(owner)
        await routing.poll();rows[1]['latest_message_id']='g-new'
        snapshots['g']['items']=[item('g-middle','Unproven old or new'),item('g-new','Established latest')]
        snapshot,fresh=await routing.poll();assert [value['native_id'] for value in fresh]==['g-new']
        owner.config['private_whitelist']=[];rows[0]['latest_message_id']='p-new'
        assert await routing.poll() is None
        owner.config['group_chat_enabled']=False
        try:await routing.poll();assert False
        except BrowserError:pass
    asyncio.run(check())


if __name__=='__main__':
    for name,check in list(globals().items()):
        if name.startswith('test_') and callable(check):check();print('PASS',name)
