"""Durable receive queue. Only work not yet submitted to AstrBot can be retried."""
from __future__ import annotations

import json
import time


class PendingMessages:
    def __init__(self,ledger):
        self.db=ledger.db
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS incoming_messages (
                peer_key TEXT NOT NULL, message_key TEXT NOT NULL,
                peer TEXT NOT NULL, item TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                created REAL NOT NULL, job_id TEXT, PRIMARY KEY(peer_key,message_key))''')
            # A crash after submission cannot prove that nothing was sent.
            self.db.execute("UPDATE incoming_messages SET state='interrupted' WHERE state='submitted'")
            self.db.execute('CREATE INDEX IF NOT EXISTS incoming_state_created ON incoming_messages(state,created)')

    @staticmethod
    def _key(item):
        return 'native:'+str(item['native_id']) if item.get('native_id') else item.get('_delivery_key') or 'legacy:'+item['key']

    def add(self,peer,items):
        with self.db:
            self.db.executemany('''INSERT OR IGNORE INTO incoming_messages
                (peer_key,message_key,peer,item,state,created) VALUES (?,?,?,?,'pending',?)''',
                [(peer['key'],self._key(item),json.dumps(peer,ensure_ascii=False),
                  json.dumps(item,ensure_ascii=False),time.time()) for item in items if item['sender']=='peer'])

    def next(self,peer_key=None):
        query="SELECT peer_key,peer,retry_at FROM incoming_messages WHERE state='pending'"
        args=[]
        if peer_key is not None:query+=' AND peer_key=?';args.append(peer_key)
        row=None;seen=set();now=time.time()
        for candidate in self.db.execute(query+' ORDER BY created,rowid',args):
            if candidate[0] in seen:continue
            seen.add(candidate[0])
            if candidate[2]<=now:row=candidate;break
        if not row:return None
        items=self.db.execute("SELECT item FROM incoming_messages WHERE peer_key=? AND state='pending' ORDER BY created,rowid",(row[0],)).fetchall()
        return json.loads(row[1]),[json.loads(item[0]) for item in items]

    def submitted(self,peer,items,job_id):
        with self.db:
            self.db.executemany("UPDATE incoming_messages SET state='submitted',job_id=? WHERE peer_key=? AND message_key=? AND state='pending'",
                [(job_id,peer['key'],self._key(item)) for item in items])

    def finish(self,peer,items):
        with self.db:
            # Keep a compact deduplication receipt, not another full chat archive.
            self.db.executemany("UPDATE incoming_messages SET state='done',item='{}' WHERE peer_key=? AND message_key=? AND state IN ('pending','submitted')",
                [(peer['key'],self._key(item)) for item in items])

    def retry(self,peer_key):
        with self.db:
            self.db.execute("""UPDATE incoming_messages SET attempts=attempts+1,
                state=CASE WHEN attempts+1>=3 THEN 'failed' ELSE 'pending' END,
                retry_at=?+min(30,5*(attempts+1)) WHERE peer_key=? AND state='pending'""",(time.time(),peer_key))
            self.db.execute("UPDATE incoming_messages SET state='interrupted' WHERE peer_key=? AND state='submitted'",(peer_key,))

    def discard(self):
        with self.db:
            self.db.execute("UPDATE incoming_messages SET state='paused',item='{}' WHERE state IN ('pending','submitted')")

    def status(self):
        return dict(self.db.execute("SELECT state,count(*) FROM incoming_messages WHERE state IN ('pending','failed','interrupted') GROUP BY state"))


def poll_interval(config,last_activity,now=None):
    normal=max(1,float(config.get('poll_seconds',4)))
    if config.get('adaptive_polling',True) and (time.monotonic() if now is None else now)-last_activity<30:
        return min(normal,1.0)
    return normal


def merge_window(config):
    maximum=max(0,min(15,float(config.get('merge_seconds',3))))
    return maximum,min(maximum,0.8) if config.get('adaptive_polling',True) else maximum
