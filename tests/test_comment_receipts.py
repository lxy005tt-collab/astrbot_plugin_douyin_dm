import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from mimi_douyin.activities import ActivityEngine

URL='https://www.douyin.com/video/1234567890123456789'
class Ledger:
    def __init__(self): self.rows={'activity:1234567890123456789': {'verified':True}}
    def get(self,key): return self.rows.get(key)
    def put(self,key,value): self.rows[key]=value

def engine(result):
    owner=NS(config={'allow_public_comments':True},ledger=Ledger(),browser=NS(call=AsyncMock(return_value=result)))
    return ActivityEngine(owner),owner

def test_missing_id_is_unknown_and_deduplicated():
    activity,owner=engine({'state':'sent'})
    async def run():
        first=await activity.comment(URL,'这一段好有意思')
        second=await activity.comment(URL,'这一段好有意思')
        assert first['state']=='unknown' and first['reason']=='missing_comment_id'
        assert second['state']=='unknown' and second['already_submitted']
    asyncio.run(run())
    assert owner.browser.call.await_count==1

def test_confirmed_receipt_keeps_comment_id():
    activity,owner=engine({'state':'sent','comment_id':'receipt-1'})
    result=asyncio.run(activity.comment(URL,'有意思'))
    assert result['state']=='sent' and result['comment_id']=='receipt-1'

def test_concurrent_calls_are_serialized_and_observe_receipt():
    activity,owner=engine({'state':'sent','comment_id':'receipt-1'})
    async def run():
        a,b=await asyncio.gather(activity.comment(URL,'有意思'),activity.comment(URL,'有意思'))
        assert a['comment_id']==b['comment_id']=='receipt-1'
        assert b.get('already_submitted')
    asyncio.run(run())
    assert owner.browser.call.await_count==1

def test_unknown_dispatch_result_is_not_retried():
    activity,owner=engine({'state':'unknown'})
    async def run():
        first=await activity.comment(URL,'有意思')
        second=await activity.comment(URL,'有意思')
        assert first['state']=='unknown'
        assert second['state']=='unknown' and second['already_submitted']
    asyncio.run(run())
    assert owner.browser.call.await_count==1

def test_timeout_preserves_unknown_and_does_not_retry():
    activity,owner=engine(None)
    owner.browser.call.side_effect=TimeoutError()
    async def run():
        with pytest.raises(TimeoutError): await activity.comment(URL,'有意思')
        second=await activity.comment(URL,'有意思')
        assert second['state']=='unknown' and second['already_submitted']
    asyncio.run(run())
    assert owner.browser.call.await_count==1

def test_unread_post_never_sends():
    activity,owner=engine({'state':'sent','comment_id':'x'})
    owner.ledger.rows.clear()
    async def run():
        with pytest.raises(Exception): await activity.comment(URL,'有意思')
    asyncio.run(run())
    owner.browser.call.assert_not_called()
