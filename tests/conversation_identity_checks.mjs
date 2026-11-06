// Identity behavior only; no account, browser, network or checksum validation.
import assert from 'node:assert/strict';
import {ConversationIdentities} from '../mimi_douyin/browser/conversation_identity.mjs';

const keyOf = value => 'key(' + value + ')';
const publicURL = value => {try {const u=new URL(value);return u.origin+u.pathname;} catch {return '';}};
const row = {conversation_type:1,conversation_id:'conversation-1'};
const peer = {...row,conversation_type:'private',name:'Example',link:'https://www.douyin.com/user/example?tracking=1'};
const legacy = keyOf(publicURL(peer.link));

let ids = new ConversationIdentities(keyOf,publicURL);
assert.equal(ids.key(row),ids.key(peer));
assert.equal(ids.key(peer),keyOf(row.conversation_id));
console.log('PASS new private list and chat use the same stable conversation ID');

ids = new ConversationIdentities(keyOf,publicURL,{},[legacy]);
assert.equal(ids.key(peer),legacy);
assert.equal(ids.key(row),legacy);
assert.equal(ids.key({...peer,link:''}),legacy);
console.log('PASS legacy profile key survives missing links without changing the allowlist');

ids = new ConversationIdentities(keyOf,publicURL,JSON.parse(JSON.stringify(Object.fromEntries(ids.known))),[legacy]);
assert.equal(ids.key(row),legacy);
console.log('PASS persisted identity survives reopening');

ids = new ConversationIdentities(keyOf,publicURL);
ids.remember(peer,legacy); // Existing binding passed to BrowserWorker.open.
assert.equal(ids.key(row),legacy);
assert.equal(ids.key({...peer,link:'https://www.douyin.com/user/changed-display'}),legacy);
console.log('PASS restored binding retains its original session key');

ids = new ConversationIdentities(keyOf,publicURL,{},[legacy]);
assert.equal(ids.key({...row,link:peer.link}),legacy);
assert.equal(ids.key({...row,conversation_id:'unrelated'}),keyOf('unrelated'));
assert.equal(ids.key({...row,conversation_type:2}),keyOf('group:conversation-1'));
assert.equal(ids.key({...row,conversation_type:'group'}),keyOf('group:conversation-1'));
console.log('PASS legacy list links resolve without granting unrelated conversations or groups access');

ids = new ConversationIdentities(keyOf,publicURL,{},[keyOf('conversation-1'),legacy]);
ids.remember(peer,keyOf('conversation-1'));
assert.equal(ids.key(peer),keyOf('conversation-1'));
console.log('PASS a known conversation key wins over a later visible profile link');
