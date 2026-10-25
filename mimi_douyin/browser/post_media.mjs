import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {openBackgroundPage} from './browser_actions.mjs';
import {getCommentEditor,getCommentSubmit,captureEmptyCommentControls} from './comment_ui.mjs';

export function postImages(detail) {
  const images=Array.isArray(detail?.images)&&detail.images.length?detail.images:detail?.image_post_info?.images;
  if(!Array.isArray(images))return [];
  return images.map(image=>{
    const lists=[image.display_image?.url_list,image.owner_watermark_image?.url_list,image.url_list,image.download_url_list];
    return lists.flatMap(list=>Array.isArray(list)?list:[]).find(url=>typeof url==='string'&&url.startsWith('https:'));
  });
}

async function downloadAsset(url,{context,page,settings,mediaHost},expected,remaining) {
  let response;
  for(let redirects=0;redirects<5;redirects++) {
    const target=new URL(url);
    if(target.protocol!=='https:'||!mediaHost(target.hostname)||target.username||target.password)
      throw new Error('媒体下载地址不在支持范围。');
    const cookies=await context.cookies(url);
    response=await fetch(url,{redirect:'manual',headers:{Referer:'https://www.douyin.com/',
      'User-Agent':await page.evaluate(()=>navigator.userAgent),Cookie:cookies.map(cookie=>cookie.name+'='+cookie.value).join('; ')},
      signal:AbortSignal.timeout(60000)});
    if(response.status>=300&&response.status<400){url=new URL(response.headers.get('location'),url).href;continue;}
    break;
  }
  const mime=(response?.headers.get('content-type')||'').split(';')[0];
  if(!response?.ok||!mime.startsWith(expected+'/'))throw new Error('实际媒体文件下载失败。');
  if(Number(response.headers.get('content-length'))>remaining)throw new Error('作品媒体总大小超过下载设置。');
  const reader=response.body.getReader();const chunks=[];let bytes=0;
  try {
    while(true){const chunk=await reader.read();if(chunk.done)break;bytes+=chunk.value.length;
      if(bytes>remaining)throw new Error('作品媒体总大小超过下载设置。');chunks.push(chunk.value);}
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
  const extension=expected==='video'?'.mp4':({'image/png':'.png','image/webp':'.webp','image/avif':'.avif','image/gif':'.gif'}[mime]||'.jpg');
  await fs.mkdir(settings.media_dir,{recursive:true});
  const file=path.join(settings.media_dir,randomUUID()+extension);
  await fs.writeFile(file,Buffer.concat(chunks));
  return {path:file,bytes,mime};
}

export async function readPost(args,environment) {
  const {context,page,settings,siteHost,mediaHost,publicURL}=environment;
  const url=new URL(args.url);
  if(url.protocol!=='https:'||!siteHost(url.hostname)||url.username||url.password)throw new Error('作品来源不受支持。');
  const tab=await openBackgroundPage(context,page);
  const media=[];
  const detailPromise=tab.waitForResponse(response=>/\/aweme\/v1\/web\/aweme\/detail\//.test(response.url())
    && response.status()===200 && (response.headers()['content-type']||'').includes('json'),{timeout:18000})
    .then(response=>response.json()).catch(()=>null);
  tab.on('response',response=>{
    if((response.headers()['content-type']||'').startsWith('video/')&&mediaHost(new URL(response.url()).hostname))media.push(response.url());
  });
  try {
    await tab.goto(url.href,{waitUntil:'domcontentloaded',timeout:45000});
    if(/验证码|安全验证/.test(await tab.title()))throw new Error('抖音要求账号验证，请在登录窗口完成后重试。');
    const payload=await detailPromise;
    const detail=payload?.aweme_detail;
    const id=new URL(tab.url()).pathname.match(/\/(?:video|note)\/(\d+)/)?.[1]
      ||url.pathname.match(/\/(?:video|note)\/(\d+)/)?.[1];
    if(detail && id && String(detail.aweme_id)!==id)throw new Error('作品详情标识不匹配，未读取其他内容。');
    const images=postImages(detail);
    const postID=String(detail?.aweme_id||id||'');
    const info={kind:images.length?'images':'video',description:String(detail?.desc||''),
      source:postID?`https://www.douyin.com/${images.length?'note':'video'}/${postID}`:publicURL(tab.url()),post_id:postID,image_count:images.length,
      has_video:!!detail?.video,metadata_fields:detail?Object.keys(detail):[]};
    if(args.info_only) {
      await tab.waitForSelector('video,[data-e2e*="comment"]',{timeout:10000}).catch(()=>{});
      await tab.waitForTimeout(1000);
      if(args.probe_comment) {
        let editor;
        try {
          editor=await getCommentEditor(tab);
          if(args.probe_text){await editor.focus();await editor.press('Control+A');await editor.press('Backspace');await captureEmptyCommentControls(tab);await tab.keyboard.insertText('临时检查，未发送');await tab.waitForTimeout(300);}
          const submit=await getCommentSubmit(tab);
          info.comment_ui={editor_count:await editor.count(),submit_count:await submit.count(),submitted:false};
        } catch(error) {info.comment_ui={ready:false,reason:String(error.message),submitted:false};}
        finally {
          if(args.probe_text)info.comment_ui.scene=await tab.evaluate(()=>{
            const inner=document.querySelector('.comment-input-inner-container');
            const parent=inner?.parentElement?.parentElement;
            if(!parent)return [];
            return [...parent.querySelectorAll('button,div,span,svg,use')].slice(-45).map(node=>({tag:node.tagName,
              cls:node.getAttribute('class'),label:node.getAttribute('aria-label'),title:node.getAttribute('title'),
              role:node.getAttribute('role'),href:node.getAttribute('href')||node.getAttribute('xlink:href'),
              text:node.tagName.toLowerCase()==='svg'?'':(node.innerText||'').slice(0,35),
              handlers:Object.keys(node).filter(key=>key.startsWith('__reactProps')).flatMap(key=>Object.keys(node[key]||{}).filter(name=>name.startsWith('on')))}));
          });
          if(args.probe_text&&editor){await editor.focus();await editor.press('Control+A');await editor.press('Backspace');await tab.waitForTimeout(300);
            info.comment_ui.draft_cleared=(await editor.innerText()).replace(/[\u200b\ufeff]/g,'').trim()==='';}
        }
      }
      info.comment_permission={allow_comment:detail?.status?.allow_comment,video_allow_comment:detail?.video_control?.allow_comment};
      info.comment_controls=await tab.evaluate(()=>{
        const visible=node=>node.getBoundingClientRect().width>10&&node.getBoundingClientRect().height>8;
        const describe=node=>({tag:node.tagName,cls:String(node.className),e2e:node.getAttribute('data-e2e'),
          editable:node.getAttribute('contenteditable'),role:node.getAttribute('role'),visible:visible(node),
          placeholder:node.getAttribute('placeholder')||node.getAttribute('data-placeholder'),
          text:(node.tagName==='BUTTON'||node.getAttribute('role')==='button')?(node.innerText||'').slice(0,40):''});
        return {editors:[...document.querySelectorAll('textarea,input,[contenteditable]')].map(describe).slice(0,25),
          e2e:[...new Set([...document.querySelectorAll('[data-e2e]')].map(node=>node.getAttribute('data-e2e')))].slice(0,70),
          inputs:[...document.querySelectorAll('[class*="comment-input"],[class*="CommentInput"],[class*="commentInput"],[data-placeholder],[data-slate-editor]')].map(describe).slice(0,20),
          composer:[...document.querySelectorAll('.commentInput-right-ct')].map(node=>({parent_class:String(node.parentElement.className),parent_text:node.parentElement.innerText.slice(0,180),
            children:[...node.parentElement.querySelectorAll('div,span,button')].slice(-16).map(child=>({tag:child.tagName,cls:String(child.className),text:child.innerText.slice(0,30)}))})),
          iframes:[...document.querySelectorAll('iframe')].map(node=>({title:node.title,path:(()=>{try{return new URL(node.src).pathname;}catch{return '';}})()})).slice(0,8),
          buttons:[...document.querySelectorAll('button,[role="button"],[data-e2e*="comment"]')].filter(visible)
            .filter(node=>/comment|评论|发送|发布/.test(String(node.className)+' '+node.getAttribute('data-e2e')+' '+node.innerText)).map(describe).slice(0,25)};
      });
      return info;
    }
    let remaining=(settings.max_download_mb||64)*1024*1024;
    if(images.length) {
      if(images.length>Number(settings.max_post_images||30))throw new Error('图文图片数量超过设置，未仅下载封面。');
      if(images.some(url=>!url))throw new Error('图文中有原图地址缺失，未把部分图片当作完整作品。');
      const files=[];
      for(const url of images){const image=await downloadAsset(url,environment,'image',Math.min(remaining,20*1024*1024));
        files.push(image);remaining-=image.bytes;}
      return {...info,images:files,bytes:files.reduce((sum,image)=>sum+image.bytes,0)};
    }
    if(!detail?.video && /\/note\//.test(tab.url()))throw new Error('图文详情没有返回原图，未用封面代替。');
    await tab.waitForFunction(()=>[...document.querySelectorAll('video')].some(video=>video.currentSrc&&video.readyState>=1),undefined,{timeout:20000});
    const probe=await tab.evaluate(async()=>{
      const video=[...document.querySelectorAll('video')].filter(item=>item.currentSrc&&item.readyState>=1)
        .sort((a,b)=>b.getBoundingClientRect().width*b.getBoundingClientRect().height-a.getBoundingClientRect().width*a.getBoundingClientRect().height)[0];
      try{await video.play();}catch{}
      return {url:video.currentSrc,duration:video.duration,title:document.title};
    });
    await tab.waitForTimeout(1200);
    const playURL=detail?.video?.play_addr?.url_list?.find(value=>value.startsWith('https:'));
    const assetURL=playURL||(probe.url.startsWith('https:')?probe.url:media.at(-1));
    if(!assetURL)throw new Error('没有取得实际视频文件。');
    const file=await downloadAsset(assetURL,environment,'video',remaining);
    return {...info,...file,duration:Number.isFinite(probe.duration)?probe.duration:null,title:probe.title,
      download_strategy:playURL?'detail_play_addr':'player_source',media_response_count:media.length};
  } finally {await tab.close();}
}
