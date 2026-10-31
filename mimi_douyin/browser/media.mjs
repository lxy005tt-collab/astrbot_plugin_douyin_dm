import {setTimeout as pause} from 'node:timers/promises';
import {readPost} from './post_media.mjs';
export {readPost};

function postLink(item,siteHost) {
  const links=Array.isArray(item?.links)?item.links:[];
  const textLinks=String(item?.text||'').match(/https:\/\/(?:[\w-]+\.)?(?:douyin|iesdouyin)\.com\/[^\s<>]+/g)||[];
  const supported=[];
  for(const value of [...links,...textLinks]) {
    let url;
    try {url=new URL(value);}catch {continue;}
    if(url.protocol!=='https:'||url.username||url.password||!siteHost(url.hostname))continue;
    if(/\/(?:share\/)?(?:video|note)\/\d{12,24}(?:\/|$)/.test(url.pathname)
      ||url.hostname==='v.douyin.com'&&url.pathname!=='/')supported.push(url.href);
  }
  return supported.find(value=>new URL(value).pathname.match(/\/(?:video|note)\/\d{12,24}(?:\/|$)/))||supported[0]||'';
}

function postIdentity(value) {
  const url=new URL(value);
  return url.pathname.match(/\/(?:video|note)\/(\d{12,24})(?:\/|$)/)?.[1]||'';
}

export async function resolveSharedPost(args,environment) {
  const {snapshot,siteHost}=environment;
  const hint=args.message_hint||{};
  // Only the original inbound share can supply this fallback. Never pick the
  // newest card or match a publisher nickname when an old key disappears.
  const captured=hint.sender==='peer'&&hint.kind==='video'?postLink(hint,siteHost):'';
  let lastError='未找到这条对方分享的作品。';
  for(let attempt=1;attempt<=3;attempt++) {
    const before=await snapshot();
    if(!before.ready||before.peer?.key!==args.peer_key)throw new Error('当前私信对象已变化。');
    const items=before.items||[];
    let item=items.find(item=>item.key===args.message_key);
    if(item&&item.sender!=='peer')throw new Error('指定消息不是对方分享的作品。');
    if(!item&&hint.native_id) {
      const matching=items.filter(item=>item.sender==='peer'&&item.native_id===hint.native_id);
      if(matching.length===1)item=matching[0];
    }
    const current=item?postLink(item,siteHost):'';
    if(current&&captured&&postIdentity(current)&&postIdentity(captured)&&postIdentity(current)!==postIdentity(captured))
      throw new Error('分享作品标识不一致，没有读取其他视频。');
    if(current)return {url:current,matched_by:item.key===args.message_key?'message_key':'native_message_id',attempts:attempt};
    if(captured)return {url:captured,matched_by:'captured_share_link',attempts:attempt};
    if(item)lastError='分享卡片尚未提供可访问作品链接。';
    if(attempt<3)await pause(400);
  }
  throw new Error(lastError+' 已重新检查 3 次，请重新分享该作品或发送作品链接。');
}

export async function downloadVideo(args,environment) {
  const resolved=await resolveSharedPost(args,environment);
  const source=await readPost({url:resolved.url},environment);
  return {...source,share_lookup:{matched_by:resolved.matched_by,attempts:resolved.attempts}};
}
