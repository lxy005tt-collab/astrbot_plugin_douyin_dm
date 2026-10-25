// Private-chat DOM selectors were informed by popohuan/douyin-bot (MIT).
// See ATTRIBUTIONS.md. No third-party persona, account state, or sending code is used.
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import readline from 'node:readline';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {enterReply,submitReply} from './browser_actions.mjs';

let context, page, settings;
const hash=x=>createHash('sha256').update(x).digest('hex');
const siteHost=host=>host==='douyin.com'||host.endsWith('.douyin.com')||host==='iesdouyin.com'||host.endsWith('.iesdouyin.com');
const mediaHost=host=>siteHost(host)||['douyinvod.com','douyincdn.com','douyinpic.com','bytecdn.cn','byteimg.com','byteimgtos.com','pstatp.com'].some(x=>host===x||host.endsWith('.'+x));
const publicURL=value=>{try{const u=new URL(value);return u.origin+u.pathname;}catch{return '';}};

async function open(config) {
  settings=config;
  if(context && page && !page.isClosed())return status();
  const require=createRequire(config.playwright_package);
  const {chromium}=require('playwright');
  await fs.mkdir(config.profile,{recursive:true});
  await fs.mkdir(config.media_dir,{recursive:true});
  if(process.platform==='linux'&&!config.headless&&!process.env.DISPLAY&&!process.env.WAYLAND_DISPLAY)
    throw new Error('当前主机没有图形桌面，无法打开扫码登录窗口。请为容器配置桌面或 VNC/X11。');
  const options={headless:!!config.headless,viewport:{width:1280,height:900},acceptDownloads:true};
  if(config.browser_channel)options.channel=config.browser_channel;
  if(config.browser_executable)options.executablePath=config.browser_executable;
  context=await chromium.launchPersistentContext(config.profile,options);
  page=context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(8000);
  await page.goto('https://www.douyin.com/',{waitUntil:'domcontentloaded',timeout:45000});
  if(config.restore_peer){
    try{
      await page.locator('[data-e2e="im-entry"]').click({timeout:20000});
      await page.locator('[data-e2e="conversation-item"]').first().waitFor({timeout:15000});
      const match=await page.evaluate(peer=>{
        const clean=x=>{try{return new URL(x).pathname;}catch{return '';}};
        const candidates=[...document.querySelectorAll('[data-e2e="conversation-item"]')]
          .filter(x=>[...x.querySelectorAll('img')].some(i=>clean(i.src)===clean(peer.avatar))
            &&(peer.conversation_id||x.innerText.split('\n').map(t=>t.trim()).includes(peer.name)));
        if(candidates.length!==1)return false;
        candidates[0].setAttribute('data-mimi-restore-peer','true');return true;
      },config.restore_peer);
      if(match){
        await page.locator('[data-mimi-restore-peer="true"]').click();
        await page.locator('.messageEditorinputArea').waitFor({timeout:10000});
        let restored;
        for(let i=0;i<6;i++){
          restored=await snapshot();
          if(restored.peer?.key===config.restore_peer.key)break;
          await page.waitForTimeout(500);
        }
        if(restored.peer?.key!==config.restore_peer.key)return {...await status(),state:'restore_recipient_mismatch'};
      }
    }catch{/* Keep login available for manual selection when restoring is unavailable. */}
  }
  return status();
}

async function status() {
  if(!page || page.isClosed())return {open:false,logged_in:false,state:'browser_closed'};
  const cookies=await context.cookies('https://www.douyin.com');
  const session=cookies.some(x=>['sessionid','sessionid_ss'].includes(x.name)&&x.value);
  const ui=await page.evaluate(()=>({title:document.title,url:location.origin+location.pathname,
    editors:[...document.querySelectorAll('[contenteditable="true"],textarea')].filter(x=>x.getBoundingClientRect().width>20)
      .map(x=>({tag:x.tagName,className:x.className,role:x.getAttribute('role')})).slice(0,8),
    loginButton:[...document.querySelectorAll('button,[role="button"]')].some(x=>x.innerText?.trim()==='登录'&&x.getBoundingClientRect().width>10)}));
  return {open:true,logged_in:session&&!ui.loginButton,state:session?'waiting_for_conversation':'login_required',...ui};
}

async function snapshot(options={}) {
  if(!page || page.isClosed())throw new Error('请先打开并登录 Mimi 的抖音窗口。');
  const domFile=path.join(path.dirname(fileURLToPath(import.meta.url)),'dom.mjs');
  const version=(await fs.stat(domFile)).mtimeMs;
  const {readChatDOM}=await import(pathToFileURL(domFile).href+'?v='+version);
  const data=await page.evaluate(readChatDOM,{debug:!!options.debug});
  if(!data.ready)return data;
  const peer=data.peer;
  const identity=peer.link?publicURL(peer.link):peer.conversation_id || (peer.name&&peer.avatar?peer.name+'|'+publicURL(peer.avatar):'');
  peer.identity_kind=peer.link?'profile_link':peer.conversation_id?'conversation_id':'name_and_avatar';
  peer.key=identity?hash(identity):'';
  peer.link=publicURL(peer.link);peer.avatar=publicURL(peer.avatar);
  const duplicates=new Map();
  for(const item of data.items) {
    // Never use the virtual-list index as the message identity: it shifts as new
    // messages arrive. Python aligns repeated content with the previous snapshot.
    item.fingerprint=hash(JSON.stringify([item.sender,item.text,item.links.map(publicURL),item.images.map(publicURL),item.kind]));
    const occurrence=duplicates.get(item.fingerprint)||0;duplicates.set(item.fingerprint,occurrence+1);
    item.key=item.native_id || item.fingerprint+':'+occurrence;
    item.images=item.images.map(publicURL);
  }
  return data;
}

async function send(args) {
  const before=await snapshot();
  if(!before.ready || before.peer.key!==args.peer_key)throw new Error('当前私信对象与已绑定对象不一致，未发送。');
  if(!before.direction_proven)throw new Error('尚未确认消息的收发方向，未发送。');
  const text=String(args.text||'').trim();
  if(!text || text.length>2000)throw new Error('回复为空或超过当前单条文字限制。');
  const count=before.items.filter(x=>x.sender==='me'&&x.text===text).length;
  await enterReply(page,text);
  await submitReply(page);
  for(let i=0;i<10;i++) {
    await page.waitForTimeout(500);
    const after=await snapshot();
    if(!after.ready || after.peer.key!==args.peer_key)return {state:'unknown',receipt:'conversation_changed_after_send'};
    const matches=after.items.filter(x=>x.sender==='me'&&x.text===text);
    if(matches.length>count) {
      const last=matches.at(-1);
      if(last.failed)return {state:'failed',receipt:'ui_send_failed'};
      if(!last.pending && i>=2)return {state:'sent',receipt:'ui_own_message_echo',message_key:last.key};
    }
  }
  return {state:'unknown',receipt:'no_confirmed_ui_echo'};
}

async function download(args) {
  const mediaFile=path.join(path.dirname(fileURLToPath(import.meta.url)),'media.mjs');
  const version=(await fs.stat(mediaFile)).mtimeMs;
  const {downloadVideo}=await import(pathToFileURL(mediaFile).href+'?v='+version);
  return downloadVideo(args,{context,page,settings,snapshot,siteHost,mediaHost,publicURL});
}

async function postInfo(args) {
  const {readPost}=await import('./post_media.mjs');
  return await readPost({...args,info_only:true,probe_comment:true},{context,page,settings,snapshot,siteHost,mediaHost,publicURL});
}

async function explore(action,args) {
  const {browsePost,publishComment}=await import('./explore.mjs');
  const environment={context,page,settings,snapshot,siteHost,mediaHost,publicURL};
  return await (action==='browse'?browsePost:publishComment)(args,environment);
}

const input=readline.createInterface({input:process.stdin});
let queue=Promise.resolve();
input.on('line',line=>{queue=queue.then(async()=>{
  let request;
  try {
    request=JSON.parse(line);
    const actions={open:()=>open(request.args),status,snapshot:()=>snapshot(request.args),send:()=>send(request.args),download:()=>download(request.args),post_info:()=>postInfo(request.args),
      browse:()=>explore('browse',request.args),comment:()=>explore('comment',request.args),
      configure:async()=>{
        const limit=request.args.max_download_mb??settings.max_download_mb;
        if(!Number.isInteger(limit)||limit<1||limit>10000)throw new Error('作品下载大小上限应为 1～10000 MB。');
        await fs.mkdir(request.args.media_dir,{recursive:true});
        settings.media_dir=request.args.media_dir;settings.max_download_mb=limit;
        return {media_dir:settings.media_dir,max_download_mb:settings.max_download_mb};
      },
      close:async()=>{await context?.close();context=null;page=null;return {closed:true};}};
    if(!actions[request.action])throw new Error('未知浏览器操作。');
    const result=await actions[request.action]();
    process.stdout.write(JSON.stringify({id:request.id,ok:true,result})+'\n');
  } catch(error) {
    // Do not put signed media URLs, cookies, or page HTML in logs.
    const message=String(error.message||error).replace(/https?:\/\/\S+/g,'[URL]').slice(0,500);
    process.stdout.write(JSON.stringify({id:request?.id,ok:false,error:message})+'\n');
  }
});});
input.on('close',()=>{queue.finally(async()=>{await context?.close().catch(()=>{});process.exit(0);});});
