// Exercise the real page and bridge payloads with an offline admin-API fixture.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const require=createRequire(process.argv[2]);
const {chromium}=require('playwright');
const browser=await chromium.launch({executablePath:process.argv[3],headless:true});
try{
 const page=await browser.newPage({viewport:{width:375,height:900}});
 await page.addInitScript(()=>{
   window.savedRequests=[];
   const settings={enabled:true,max_messages:8,max_age_hours:48,max_chars_per_message:600,max_total_chars:12000};
   const setup={media_dir:'media',default_media_dir:'media',dependencies:[],models:{chat:'Current model',video:'Video model'},
     browser_type:'自动选择',install:{message:'Ready'},group_share_qq_memory:true,
     bot:{auto_reply_enabled:false,binding:{peer:{name:'Example group'}},session_id:'douyin:GroupMessage:example'}};
   window.AstrBotPluginPage={ready:async()=>{},apiGet:async route=>({status:'ok',data:route==='setup/status'?setup:{
     settings,links:[],source_session:'douyin:GroupMessage:example',memory_available:true,group_share_qq_memory:true}}),
     apiPost:async(route,body)=>{
       window.savedRequests.push({route,body});
       if(route==='context/conversations')return {status:'ok',data:{conversations:[{id:'selected',session:'qq:FriendMessage:example',kind:'FriendMessage',title:'Existing chat'}]}};
       if(route==='context/settings')Object.assign(settings,body);
       return {status:'ok',data:{message:'Saved'}};
     }};
 });
 const url=pathToFileURL(path.resolve('pages/接入设置/index.html')).href;
 await page.goto(url);await page.waitForFunction(()=>document.querySelector('#refresh').disabled===false);
 assert.equal(await page.locator('[role="tab"]').count(),3);
 for(const panel of ['context','media','connect']){
   await page.locator('[data-panel="'+panel+'"]').click();
   assert.equal(await page.locator('#panel-'+panel).isVisible(),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 }
 await page.locator('[data-panel="context"]').click();
 assert.equal(await page.locator('#context-bidirectional').isDisabled(),true);
 assert.equal(await page.locator('#context-bidirectional').isChecked(),false);
 await page.locator('#context-messages').fill('12');
 await page.locator('#save-context-settings').click();await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
 await page.locator('#context-memory').check();await page.locator('#save-context-link').click();
 await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
 const requests=await page.evaluate(()=>window.savedRequests);
 assert.equal(requests.find(x=>x.route==='context/settings').body.max_messages,'12');
 assert.deepEqual(requests.find(x=>x.route==='context/link').body,{target_session:'qq:FriendMessage:example',target_conversation_id:'selected',bidirectional:false,share_memory:true});
 console.log('PASS setup tabs, mobile width, persisted context payload, explicit one-way group memory');
}finally{await browser.close();}
