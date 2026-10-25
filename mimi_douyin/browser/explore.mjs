import {openBackgroundPage} from './browser_actions.mjs';
import {readPost} from './post_media.mjs';
import {getCommentEditor,getCommentSubmit,captureEmptyCommentControls} from './comment_ui.mjs';

export async function browsePost(args,environment) {
  if(args.url)return await readPost({url:args.url,info_only:!!args.info_only},environment);
  const {context,page}=environment;
  const tab=await openBackgroundPage(context,page);
  const posts=new Map();
  const seen=new Set(args.seen_ids||[]);
  const pending=[];
  const responses=[];
  tab.on('response',response=>{
    try{const requestURL=new URL(response.url());if(requestURL.hostname.endsWith('douyin.com')&&requestURL.pathname.includes('/aweme/v1/web/')&&responses.length<40)
      responses.push({path:requestURL.pathname,status:response.status(),mime:response.headers()['content-type']||''});}catch{}
    if(!/\/aweme\/v1\/web\/(?:tab\/feed|recommend\/feed|aweme\/detail)/.test(response.url())
       ||!(response.headers()['content-type']||'').includes('json'))return;
    pending.push(response.json().then(body=>{
      for(const post of [...(body.aweme_list||[]),...(body.aweme_detail?[body.aweme_detail]:[])])
        if(/^\d{12,24}$/.test(String(post.aweme_id)))posts.set(String(post.aweme_id),post);
    }).catch(()=>{}));
  });
  let chosen;
  try {
    await tab.goto('https://www.douyin.com/',{waitUntil:'domcontentloaded',timeout:45000});
    if(/验证码|安全验证/.test(await tab.title()))throw new Error('推荐页要求账号验证，请在登录窗口完成。');
    const recommended=tab.locator('[data-e2e="douyin-navigation"] a').filter({hasText:/^推荐$/});
    if(await recommended.count()===1)await recommended.evaluate(node=>node.click());
    for(let attempt=0;attempt<12;attempt++) {
      await tab.waitForTimeout(500);await Promise.all(pending);
      const links=await tab.locator('a[href*="/video/"],a[href*="/note/"]').evaluateAll(nodes=>nodes.map(node=>node.href));
      for(const link of links){const id=link.match(/\/(?:video|note)\/(\d{12,24})/)?.[1];if(id&&!posts.has(id))posts.set(id,{aweme_id:id});}
      const hydrated=await tab.evaluate(()=>{
        const found=new Map(),seen=new WeakSet();let budget=3000;
        const walk=(value,depth)=>{
          if(!value||typeof value!=='object'||depth>11||--budget<0||seen.has(value))return;seen.add(value);
          const id=value.aweme_id||value.awemeId;
          if(/^\d{12,24}$/.test(String(id)))found.set(String(id),{aweme_id:String(id),
            images:Array.isArray(value.images)?value.images.map(()=>({})):undefined,
            image_post_info:value.image_post_info?{images:(value.image_post_info.images||[]).map(()=>({}))}:undefined});
          if(Array.isArray(value)){value.slice(0,30).forEach(child=>walk(child,depth+1));return;}
          for(const key of Object.keys(value).slice(0,70))if(/children|props|aweme|video|data|item|entry|list|info/i.test(key)){
            try{walk(value[key],depth+1);}catch{}}
        };
        for(const node of document.querySelectorAll('[data-e2e="feed-item"],[data-e2e="feed-active-video"]'))
          for(const key of Object.keys(node).filter(key=>key.startsWith('__reactProps')))walk(node[key],0);
        return [...found.values()];
      });
      for(const post of hydrated)posts.set(String(post.aweme_id),post);
      chosen=[...posts.values()].find(post=>!seen.has(String(post.aweme_id))&&(!args.prefer_images||post.images?.length||post.image_post_info?.images?.length));
      if(chosen)break;
      if(attempt===3||attempt===7)await tab.keyboard.press('ArrowDown');
    }
    if(args.debug)return {kind:'diagnostic',posts:posts.size,image_posts:[...posts.values()].filter(post=>post.images?.length||post.image_post_info?.images?.length).length,
      responses,dom:await tab.evaluate(()=>({title:document.title,url:location.origin+location.pathname,visibility:document.visibilityState,focused:document.hasFocus(),
        e2e:[...new Set([...document.querySelectorAll('[data-e2e]')].map(node=>node.getAttribute('data-e2e')))].slice(0,80),
        video_count:document.querySelectorAll('video').length,
        feed_props:[...document.querySelectorAll('[data-e2e="feed-item"],[data-e2e="feed-active-video"]')].slice(0,3).map(node=>
          Object.keys(node).filter(key=>key.startsWith('__reactProps')).map(key=>Object.keys(node[key]||{}))),
        links:[...document.querySelectorAll('a[href]')].slice(0,20).map(node=>({path:new URL(node.href).pathname,text:(node.innerText||'').slice(0,25)}))}))};
    if(!chosen)throw new Error('推荐页没有取得可读取的新作品，没有把首页标题当作刷过视频。');
  } finally {await tab.close();}
  const id=String(chosen.aweme_id);
  const kind=chosen.images?.length||chosen.image_post_info?.images?.length?'note':'video';
  return await readPost({url:`https://www.douyin.com/${kind}/${id}`,info_only:!!args.info_only},environment);
}

export async function publishComment(args,environment) {
  const {context,page,siteHost}=environment;
  const source=new URL(args.url);const postID=source.pathname.match(/\/(?:video|note)\/(\d{12,24})/)?.[1];
  const text=String(args.text||'').trim();
  if(source.protocol!=='https:'||!siteHost(source.hostname)||!postID||!text||text.length>200)
    throw new Error('评论需要有效作品链接和 1～200 字正文。');
  const tab=await openBackgroundPage(context,page);
  try {
    await tab.goto(source.href,{waitUntil:'domcontentloaded',timeout:45000});
    if(/验证码|安全验证/.test(await tab.title()))throw new Error('评论页要求账号验证，请先手动完成。');
    if(!new URL(tab.url()).pathname.includes(postID))throw new Error('评论目标已改变，未提交。');
    const editor=await getCommentEditor(tab);
    await editor.focus();await editor.press('Control+A');await editor.press('Backspace');await captureEmptyCommentControls(tab);await tab.keyboard.insertText(text);
    await tab.waitForTimeout(100);
    const entered=await editor.evaluate(node=>node.value??node.innerText);
    if(entered.replace(/[\u200b\ufeff]/g,'').trim()!==text)throw new Error('评论输入不一致，未提交。');
    const submit=await getCommentSubmit(tab);
    const receipt=tab.waitForResponse(response=>{
      if(!/\/aweme\/v1\/web\/comment\/publish\//.test(response.url()))return false;
      const params=new URLSearchParams(response.request().postData()||'');
      return params.get('aweme_id')===postID&&params.get('text')===text;
    },{timeout:15000}).then(response=>response.json()).catch(()=>null);
    await submit.evaluate(button=>{if(button.disabled||button.getAttribute('aria-disabled')==='true')throw new Error('评论发送按钮不可用。');button.click();});
    const result=await receipt;
    if(result?.status_code===0&&result.comment?.cid)return {state:'sent',post_id:postID,comment_id:String(result.comment.cid),receipt:'server_comment_id'};
    return {state:result&&result.status_code!==0?'failed':'unknown',post_id:postID,receipt:'no_confirmed_comment_id'};
  } finally {await tab.close();}
}
