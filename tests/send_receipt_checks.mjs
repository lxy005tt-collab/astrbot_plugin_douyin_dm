// Exercise the real send path with an offline page fixture, never a browser/account.
import assert from 'node:assert/strict';
import {sendReply} from '../mimi_douyin/browser/browser_actions.mjs';

function fixture({before={},clickError=false}={}) {
  let inserted='',entries=0,clicks=0;
  const editor={first(){return this;},focus:async()=>{},press:async()=>{},innerText:async()=>inserted};
  const button={count:async()=>1,evaluate:async callback=>{
    callback({disabled:false,closest:()=>null,click:()=>{clicks++;}});
    if(clickError)throw Error('connection lost after click');
  }};
  const page={locator:selector=>selector.includes('send-msg')?button:editor,
    keyboard:{insertText:async text=>{inserted=text;entries++;}},waitForTimeout:async()=>{}};
  const snapshot=async()=>({ready:true,peer:{key:'peer',conversation_type:'private'},direction_proven:true,
    items:clicks?[{sender:'me',text:inserted,key:'confirmed',pending:false,failed:false}]:[],...before});
  return {run:(text,extra={})=>sendReply(page,snapshot,{peer_key:'peer',conversation_type:'private',text,...extra}),
    counts:()=>({entries,clicks})};
}

for(const [text,options] of [
  ['答'.repeat(2001),{}], ['😀'.repeat(1001),{}], ['   ',{}],
  ['hello',{before:{ready:false}}],
  ['hello',{before:{peer:{key:'other',conversation_type:'private'}}}],
  ['hello',{before:{peer:{key:'peer',conversation_type:'group'}}}],
  ['hello',{before:{direction_proven:false}}],
]) {
  const check=fixture(options),receipt=await check.run(text);
  assert.equal(receipt.state,'not_sent');assert.ok(receipt.error);
  assert.deepEqual(check.counts(),{entries:0,clicks:0});
}
for(const text of ['答'.repeat(2000),'😀'.repeat(1000)]) {
  const check=fixture();assert.equal((await check.run(text)).state,'sent');
  assert.deepEqual(check.counts(),{entries:1,clicks:1});
}
const ambiguous=fixture({clickError:true});
await assert.rejects(ambiguous.run('reply'),/after click/);
assert.deepEqual(ambiguous.counts(),{entries:1,clicks:1});
console.log('PASS 10 offline send cases: preflight rejection, UTF-16 limits, confirmed send and ambiguous dispatch');
