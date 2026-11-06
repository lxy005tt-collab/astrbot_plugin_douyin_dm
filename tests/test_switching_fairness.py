"""Clock-controlled routing behavior; no browser account or AstrBot required."""
import asyncio
from unittest.mock import patch
from test_auto_switching import ConversationSwitching, fixture, item, switching


def deliver(rows, snapshots, cid, native, kind='text'):
    row=next(row for row in rows if row['conversation_id']==cid)
    row['latest_message_id']=native
    snapshots[cid]['items'].append({**item(native,native),'kind':kind})


def test_video_followed_by_mention_stays_for_one_fixed_window():
    async def check():
        owner,rows,snapshots,calls,state=fixture()
        owner.config.update(conversation_hold_seconds=10,poll_seconds=2,merge_seconds=1)
        state['active']='g'
        routing=ConversationSwitching(owner)
        with patch.object(switching.time,'monotonic',return_value=100) as clock:
            await routing.poll()
            deliver(rows,snapshots,'p','p-new')
            deliver(rows,snapshots,'g','g-video','video')
            snapshot,fresh=await routing.poll()
            assert snapshot['peer']['conversation_id']=='g'
            assert fresh[0]['kind']=='video'
            clock.return_value=104
            # Even an idle active conversation keeps its short merge window.
            assert await routing.poll() is None
            deliver(rows,snapshots,'g','g-mention')
            snapshots['g']['items'][-1]['mentioned_bot']=True
            clock.return_value=105
            snapshot,fresh=await routing.poll()
            assert snapshot['peer']['conversation_id']=='g'
            assert fresh[0]['mentioned_bot']
            # The mention must not renew the initial deadline at 110.
            clock.return_value=110
            deliver(rows,snapshots,'g','g-busy')
            snapshot,fresh=await routing.poll()
            assert snapshot['peer']['conversation_id']=='p'
            assert [value['native_id'] for value in fresh]==['p-new']
    asyncio.run(check())


def test_default_window_covers_monitor_merge_and_poll_cadence():
    async def check():
        owner,rows,snapshots,calls,state=fixture()
        owner.config.pop('conversation_hold_seconds')
        state['active']='g'
        routing=ConversationSwitching(owner)
        with patch.object(switching.time,'monotonic',return_value=100) as clock:
            await routing.poll()
            deliver(rows,snapshots,'g','g-video','video')
            await routing.poll()
            # Default monitor merges for 3s, then sleeps for 4s.
            clock.return_value=107
            deliver(rows,snapshots,'g','g-mention')
            deliver(rows,snapshots,'p','p-new')
            snapshot,_=await routing.poll()
            assert snapshot['peer']['conversation_id']=='g'
            clock.return_value=115
            deliver(rows,snapshots,'g','g-busy')
            snapshot,_=await routing.poll()
            assert snapshot['peer']['conversation_id']=='p'
    asyncio.run(check())


def test_zero_hold_immediately_serves_waiting_private_chat():
    async def check():
        owner,rows,snapshots,calls,state=fixture()
        owner.config['conversation_hold_seconds']=0
        state['active']='g'
        routing=ConversationSwitching(owner)
        with patch.object(switching.time,'monotonic',return_value=100):
            await routing.poll()
            deliver(rows,snapshots,'g','g-first')
            await routing.poll()
            deliver(rows,snapshots,'g','g-busy')
            deliver(rows,snapshots,'p','p-new')
            snapshot,_=await routing.poll()
            assert snapshot['peer']['conversation_id']=='p'
    asyncio.run(check())


def test_reset_clears_hold_and_primes_history_again():
    async def check():
        owner,rows,snapshots,calls,state=fixture()
        owner.config['conversation_hold_seconds']=10
        routing=ConversationSwitching(owner)
        await routing.poll()
        deliver(rows,snapshots,'g','g-new')
        await routing.poll()
        routing.reset()
        assert await routing.poll() is None
        deliver(rows,snapshots,'p','p-new')
        snapshot,fresh=await routing.poll()
        assert snapshot['peer']['conversation_id']=='p'
        assert [value['native_id'] for value in fresh]==['p-new']
    asyncio.run(check())


if __name__=='__main__':
    for name,check in list(globals().items()):
        if name.startswith('test_') and callable(check):
            check()
            print('PASS',name)
