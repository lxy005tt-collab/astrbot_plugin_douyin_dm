"""Sequential, explicit-allowlist routing using observed IM message frontiers."""
from __future__ import annotations

import time

from .bridge import BrowserError


class ConversationSwitching:
    def __init__(self,owner):
        self.owner=owner
        self.frontiers=None
        self.served={}

    def reset(self):
        self.frontiers=None;self.served.clear()

    def allowed(self,row):
        group=row.get('conversation_type')==2
        if row.get('conversation_type') not in (1,2) or not row.get('key'):return False
        if group and not self.owner.config.get('group_chat_enabled',True):return False
        return row['key'] in self.owner.config.get('group_whitelist' if group else 'private_whitelist',[])

    async def poll(self):
        owner=self.owner
        if getattr(owner,'current_event',None) or owner.job_lock.locked():return None
        listing=await owner.browser.call('conversations')
        rows=[row for row in listing.get('conversations',[]) if self.allowed(row) and row.get('conversation_id')]
        if not rows:raise BrowserError('自动切换未找到白名单内的会话，请在专用窗口打开消息列表，并先绑定允许接入的会话。')
        if self.frontiers is None:
            self.frontiers={row['conversation_id']:row.get('latest_message_id','') for row in rows}
            current=await owner.browser.call('snapshot')
            owner._check_peer(current)
            owner.ledger.observe(current['peer']['key'],current['items'],prime=True)
            return None
        candidates=[]
        for row in rows:
            cid=row['conversation_id'];latest=row.get('latest_message_id','')
            if cid not in self.frontiers:
                self.frontiers[cid]=latest;continue  # Newly authorized history is never replayed.
            if latest and latest!=self.frontiers[cid]:candidates.append(row)
        if not candidates:return None
        row=min(candidates,key=lambda item:self.served.get(item['conversation_id'],0))
        cid=row['conversation_id'];previous=self.frontiers[cid]
        self.served[cid]=time.monotonic()
        current=await owner.browser.call('snapshot')
        if not current.get('ready') or current['peer'].get('conversation_id')!=cid:
            current=await owner.browser.call('select_conversation',{'conversation_id':cid})
        if not current.get('ready') or current['peer'].get('conversation_id')!=cid:
            raise BrowserError('自动切换未能确认目标会话，未处理或发送消息。')
        peer=current['peer'];owner._check_whitelist(peer['key'],peer)
        if peer['key']!=row['key']:raise BrowserError('会话身份与白名单不一致，未处理或发送消息。')
        owner._check_profile(peer['key'],peer)
        items=current['items'];ids=[item.get('native_id') for item in items]
        if row['latest_message_id'] not in ids:
            raise BrowserError('目标会话尚未显示最新消息，未将历史消息当作新消息处理。')
        if previous in ids:
            fresh=items[ids.index(previous)+1:]
        else:
            # The virtual list no longer contains our old boundary. Only the
            # newly observed latest ID is established as new, never all history.
            fresh=[items[ids.index(row['latest_message_id'])]]
        owner.binding={'peer':peer,'bound_at':time.time(),'automatic':True}
        owner.ledger.put('binding',owner.binding)
        owner.ledger.observe(peer['key'],items,prime=True)
        self.frontiers[cid]=items[-1].get('native_id') or row['latest_message_id']
        return current,[item for item in fresh if item['sender']=='peer']

    def observed(self,snapshot):
        if self.frontiers is not None and snapshot.get('items') and snapshot['items'][-1].get('native_id'):
            self.frontiers[snapshot['peer']['conversation_id']]=snapshot['items'][-1]['native_id']
