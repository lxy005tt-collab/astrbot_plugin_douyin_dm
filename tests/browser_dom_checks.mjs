// Offline DOM fixtures: no account access and no network requests.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readChatDOM} from '../mimi_douyin/browser/dom.mjs';
import {activateConversation} from '../mimi_douyin/browser/conversation_ui.mjs';
const require=createRequire(process.argv[2]);
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:process.argv[3],headless:true});
try{
 const page=await browser.newPage();
 await page.setContent('<div data-e2e="conversation-item" class="active"><span class="name">Test group</span></div>'+
   '<section><header class="chatHeader"><span class="name">Test group</span></header>'+
   '<div><div data-message-id="one" data-index="2"><span class="pureText">Hello from A</span></div>'+
   '<div data-message-id="two" data-index="1"><span class="pureText">Hello from B</span></div>'+
   '<div data-message-id="mine" data-index="0"><span class="pureText">Bot answer</span></div></div>'+
   '<div contenteditable="true" role="textbox"> </div></section>');
 await page.evaluate(()=>{
   document.querySelector('[data-e2e="conversation-item"]').__reactProps$fixture={conversation:{conversation_id:'group-123',conversation_type:2}};
   for(const [id,uid,name,me] of [['one','111','Alice',false],['two','222','Bob',false],['mine','999','Bot',true]])
     document.querySelector('[data-message-id="'+id+'"]').__reactProps$fixture={message:{isMyMessage:me,sender:uid,senderInfo:{uid,nickname:name},conversation_type:2,conversation_id:'group-123'}};
 });
 const result=await page.evaluate(readChatDOM);
 assert.equal(result.peer.conversation_type,'group');assert.equal(result.peer.conversation_id,'group-123');
 assert.equal(result.direction_proven,true);assert.equal(result.items.find(x=>x.native_id==='one').sender_id,'111');
 assert.equal(result.items.find(x=>x.native_id==='two').sender_name,'Bob');assert.equal(result.items.find(x=>x.native_id==='mine').sender,'me');
 const list=await page.evaluate(readChatDOM,{conversations_only:true});assert.equal(list.conversations[0].name,'Test group');
 await page.evaluate(()=>{
   document.querySelector('[data-e2e="conversation-item"]').__reactProps$fixture.conversation.conversation_type=1;
   for(const item of document.querySelectorAll('[data-message-id]'))item.__reactProps$fixture.message.conversation_type=1;
 });
 assert.equal((await page.evaluate(readChatDOM)).peer.conversation_type,'private');
 await page.evaluate(()=>{
   class Conversation {get id(){return 'prototype-group';}get type(){return 2;}get name(){return 'Prototype group';}get unreadCount(){return 3;}get lastMessage(){return {clientId:'last-native'};}}
   document.querySelector('[data-e2e="conversation-item"]').__reactProps$fixture={conversation:new Conversation(),onMouseDown(){}};
   for(const item of document.querySelectorAll('[data-message-id]')){
     const msg=item.__reactProps$fixture.message;msg.conversation_type=2;msg.conversation_id='prototype-group';
     const stableID=item.dataset.messageId;
     Object.setPrototypeOf(msg,{get clientId(){return 'native-'+stableID;}});
     item.removeAttribute('data-message-id');
     item.__reactProps$fixture.isMyMessage=true;
     if(msg.isMyMessage)item.classList.add('isFromMe');
     if(stableID==='one'){
       delete msg.senderInfo.nickname;
       const name=document.createElement('span');name.className='MessageBoxMessageTitleavatarName';name.textContent='Visible member';item.append(name);
     }
   }
 });
 const updated=await page.evaluate(readChatDOM);
 assert.equal(updated.items.find(x=>x.native_id==='native-one').sender,'peer');
 assert.equal(updated.items.find(x=>x.native_id==='native-one').sender_name,'Visible member');
 await page.evaluate(()=>{
   const read=document.createElement('div');read.className='ContentBottomHasReadheadPhotoWrapper';
   const img=document.createElement('img');img.src='data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
   read.append(img);document.querySelector('.isFromMe').append(read);
 });
 const readState=await page.evaluate(readChatDOM);
 assert.equal(readState.items.find(x=>x.native_id==='native-mine').images.length,0);
 assert.deepEqual(readState.items.map(x=>x.native_id),updated.items.map(x=>x.native_id));
 const prototypes=await page.evaluate(readChatDOM,{conversations_only:true});
 assert.equal(prototypes.conversations[0].conversation_id,'prototype-group');
 assert.equal(prototypes.conversations[0].name,'Prototype group');
 assert.equal(prototypes.conversations[0].unread_count,3);
 assert.equal(prototypes.conversations[0].latest_message_id,'last-native');
 assert.equal(prototypes.conversations[0].activation_event,'mousedown');
 await page.evaluate(()=>document.querySelector('[data-mimi-chat-index="0"]').addEventListener('mousedown',()=>{window.selectedConversation='prototype-group';}));
 const chosen=await activateConversation(page,prototypes.conversations[0],()=>page.evaluate(()=>({ready:true,peer:{conversation_id:window.selectedConversation}})));
 assert.equal(chosen.peer.conversation_id,'prototype-group');
 await page.evaluate(()=>{
   const row=document.querySelector('[data-e2e="conversation-item"]');
   row.__reactProps$fixture.conversation={id:'prototype-group',type:2,name:'Example',
     lastMessage:{clientId:'hidden-system'},lastVisibleMessage:{clientId:'different-model-instance',serverId:'visible-server'}};
   for(const box of document.querySelectorAll('[data-index]')){
     const msg=box.__reactProps$fixture?.message;
     if(msg?.isMyMessage)Object.defineProperty(msg,'serverId',{value:'visible-server'});
   }
 });
 const authoritative=await page.evaluate(readChatDOM);
 assert.equal(authoritative.items.find(x=>x.sender==='me').native_id,'visible-server');
 const visibleLatest=await page.evaluate(readChatDOM,{conversations_only:true});
 assert.equal(visibleLatest.conversations[0].latest_message_id,'visible-server');
 console.log('PASS group identity, member attribution, conflicting direction flags, prototype IDs, read-receipt exclusion, private type');
}finally{await browser.close();}
