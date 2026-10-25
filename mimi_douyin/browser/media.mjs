import {readPost} from './post_media.mjs';
export {readPost};
export async function downloadVideo(args,environment) {
  const {snapshot,siteHost}=environment;
  const before=await snapshot();
  if(!before.ready||before.peer.key!==args.peer_key)throw new Error('当前私信对象已变化。');
  const item=before.items.find(item=>item.key===args.message_key);
  if(!item||item.sender!=='peer')throw new Error('未找到这条对方分享的作品。');
  const link=item.links.find(url=>/\/(?:video|note)\/|\/share\/(?:video|note)\/|v\.douyin\.com/.test(url))
    ||item.text.match(/https:\/\/(?:v\.|www\.)?douyin\.com\/[^\s]+/)?.[0];
  if(!link)throw new Error('分享卡片尚未提供可访问作品链接。');
  const source=new URL(link);
  if(source.protocol!=='https:'||!siteHost(source.hostname))throw new Error('作品来源不受支持。');
  return await readPost({url:link},environment);
}
