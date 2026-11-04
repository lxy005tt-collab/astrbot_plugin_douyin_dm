// Offline transport fixtures: never opens a site or sends a comment.
import assert from 'node:assert/strict';
import {publishComment} from '../mimi_douyin/browser/explore.mjs';
const id='1234567890123456789',text='离线评论回执';
function fixture({body={status_code:0,comment:{cid:'confirmed'}},clickError=false,closeError=false,responseURL='https://www.douyin.com/aweme/v1/web/comment/publish/',method='POST',target=id,targetURL=null,sourceURL=null}={}) {
 let clicks=0,matched=false;
 const editor={count:async()=>1,focus:async()=>{},press:async()=>{},evaluate:async()=>text};
 const submit={evaluate:async()=>{clicks++;if(clickError)throw Error('execution context lost after dispatch');}};
 const tab={goto:async()=>{},title:async()=>'',url:()=>targetURL||'https://www.douyin.com/note/'+target,
  locator:selector=>selector.includes('data-mimi-comment-submit')?submit:{filter:()=>editor},
  evaluate:async()=>1,waitForTimeout:async()=>{},keyboard:{insertText:async()=>{}},
  waitForResponse:async predicate=>{const response={url:()=>responseURL,request:()=>({postData:()=>new URLSearchParams({aweme_id:id,text}).toString(),method:()=>method}),status:()=>200,json:async()=>body};matched=predicate(response);if(!matched)throw Error('no matching response');return response;},
  close:async()=>{if(closeError)throw Error('closed context');}};
 const session={send:async name=>name==='Target.createTarget'?{targetId:'offline'}:{targetInfo:{targetId:'offline'}},detach:async()=>{}};
 const environment={context:{newCDPSession:async()=>session,waitForEvent:async()=>tab},page:{},siteHost:host=>host==='www.douyin.com'};
 return {run:()=>publishComment({url:sourceURL||'https://www.douyin.com/note/'+id,text},environment),clicks:()=>clicks,matched:()=>matched};
}
const valid=fixture();assert.equal((await valid.run()).state,'sent');assert.equal(valid.clicks(),1);
const rejected=fixture({body:{status_code:4}});assert.equal((await rejected.run()).state,'failed');
const malformed=fixture({body:{message:'no status'}});assert.equal((await malformed.run()).state,'unknown','missing status remains unknown');
const missingID=fixture({body:{status_code:0,comment:{}}});assert.equal((await missingID.run()).state,'unknown','missing comment id is not sent');
const interrupted=fixture({clickError:true,body:null});assert.equal((await interrupted.run()).state,'unknown','dispatch exception retains unknown');assert.equal(interrupted.clicks(),1);
const confirmedAfterDispatch=fixture({clickError:true});assert.equal((await confirmedAfterDispatch.run()).state,'sent','confirmed receipt survives dispatch exception');
const cleanup=fixture({closeError:true});assert.equal((await cleanup.run()).state,'sent','cleanup error preserves confirmed receipt');
for(const options of [{responseURL:'https://other.example/aweme/v1/web/comment/publish/'},{responseURL:'https://www.douyin.com.evil.example/aweme/v1/web/comment/publish/'},{method:'GET'}]) {
 const wrong=fixture(options);assert.equal((await wrong.run()).state,'unknown');assert.equal(wrong.matched(),false);
}
for(const options of [{target:id+'0'},{targetURL:'https://other.example/note/'+id},{targetURL:'http://www.douyin.com/note/'+id},{targetURL:'https://www.douyin.com/note/9999999999999999999'}, {sourceURL:'https://user:password@www.douyin.com/note/'+id}]) {
 const changed=fixture(options);await assert.rejects(changed.run());assert.equal(changed.clicks(),0);
}
console.log('PASS comment receipt, exact target, unknown dispatch, cleanup, host/method and comment id checks');
