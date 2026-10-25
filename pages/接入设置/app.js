(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const bridge=window.AstrBotPluginPage;
  let busy=false,folderParent='',selectedFolder='',installTimer;
  function unwrap(response){
    const body=response?.data?.status?response.data:response;
    if(body?.status==='error')throw new Error(body.message||'请求失败。');
    if(body?.status==='ok')return body.data;
    // Current AstrBot bridge already returns the payload inside the response.
    if(body&&typeof body==='object')return body;
    throw new Error('请求失败。');
  }
  function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
  async function run(action){if(busy)return;busy=true;document.querySelectorAll('main button').forEach(b=>b.disabled=true);try{await action();}catch(error){notice(error.message||String(error),true);}finally{busy=false;document.querySelectorAll('main button').forEach(b=>b.disabled=false);}}
  function line(text,className){const node=document.createElement('div');node.textContent=text;if(className)node.className=className;return node;}
  async function load(){
    const data=unwrap(await bridge.apiGet('setup/status',{}));
    $('media-dir').value=data.media_dir_setting||'';
    $('max-download').value=data.max_download_mb??64;
    $('cache-cleanup').checked=!!data.cache_cleanup_enabled;
    $('cleanup-hours').value=data.cache_cleanup_interval_hours??24;
    $('retention-hours').value=data.cache_retention_hours??24;
    const cache=data.cache_cleanup||{},last=cache.last_cleanup;
    $('cache-state').textContent=(cache.cache_cleanup_enabled?'下次清理：'+(cache.next_run_at?new Date(cache.next_run_at*1000).toLocaleString():'等待计时'):'定时清理未开启。')+
      (last?'；上次清理 '+last.deleted_files+' 个文件，释放 '+(last.deleted_bytes/1024/1024).toFixed(1)+' MB':'')+(cache.last_error?'；'+cache.last_error:'');
    $('effective-dir').textContent='当前保存位置：'+data.media_dir+'；默认位置：'+data.default_media_dir;
    $('browser-type').value=data.browser_type;
    $('autonomy').checked=!!data.autonomy_enabled;
    $('public-comments').checked=!!data.allow_public_comments;
    $('dependencies').replaceChildren();
    for(const dep of data.dependencies){const tr=document.createElement('tr');const name=document.createElement('td');name.textContent=dep.name;const state=document.createElement('td');state.textContent=dep.ready?'可用':'未就绪';state.className=dep.ready?'ready':'missing';const detail=document.createElement('td');detail.append(line(dep.path||'未找到','code'),line(dep.version||dep.hint,'detail'));if(!dep.ready&&dep.url){const a=document.createElement('a');a.href=dep.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='安装说明';detail.append(a);}tr.append(name,state,detail);$('dependencies').append(tr);}
    $('models').textContent='聊天模型：'+data.models.chat+'；视频转述模型：'+data.models.video;
    const bot=data.bot;
    $('bot-state').textContent='状态：'+(bot.auto_reply_enabled?'回复已开启':'回复已暂停')+'；绑定对象：'+(bot.binding?.peer?.name||'尚未绑定')+(bot.last_error?'；'+bot.last_error:'');
    $('session').textContent=bot.session_id?'私信会话标识：'+bot.session_id:'';
    $('optional-memory').textContent=data.optional_memory_available?'检测到可选的 LivingMemory。观看回忆由插件配置控制。':'未安装 LivingMemory：可正常聊天和转述视频；需要观看回忆或跨平台记忆时再安装配置。';
    $('install-state').textContent=data.install.message;
    if(data.install.running)pollInstall();
  }
  async function browse(path){
    try{const data=unwrap(await bridge.apiPost('setup/browse',{path:path||''}));selectedFolder=data.path;folderParent=data.parent;$('folder-path').value=data.path;$('folders').replaceChildren();for(const dir of data.directories){const button=document.createElement('button');button.type='button';button.textContent='📁 '+dir.name;button.addEventListener('click',()=>browse(dir.path));$('folders').append(button);}$('folder-notice').textContent=data.truncated?'只显示前 300 个目录，也可在上方输入完整路径。':data.directories.length?'':'此目录没有子文件夹。';$('folder-use').disabled=!data.path;$('folder-up').disabled=data.parent===null;}catch(error){$('folder-notice').textContent=error.message;}
  }
  async function install(component){await run(async()=>{const data=unwrap(await bridge.apiPost('setup/install',{component}));$('install-state').textContent=data.message;notice('安装已开始，依赖将放在本插件的数据目录。');pollInstall();});}
  function pollInstall(){clearTimeout(installTimer);installTimer=setTimeout(async()=>{try{const data=unwrap(await bridge.apiGet('setup/install/status',{}));$('install-state').textContent=data.message;if(data.running){pollInstall();return;}notice(data.message,!data.success);await run(load);}catch(error){notice(error.message,true);}},1800);}
  async function control(action){await run(async()=>{const result=unwrap(await bridge.apiPost('control',{action}));notice(action==='bind'?'已绑定当前私信，并记录旧消息基线。':action==='pause'?'回复已暂停。':action==='start'?'回复已开启。':'操作已完成。');if(action==='reopen')$('reopen').hidden=true;if(action==='watch_recommended')$('activity-observation').textContent=result.url+'\n'+result.transcript.summary+'\n'+(result.transcript.key_facts||[]).join('\n')+'\n作品文案：'+(result.transcript.post_descriptions||[]).join('\n');await load();});}
  $('refresh').addEventListener('click',()=>run(load));
  $('default-dir').addEventListener('click',()=>{$('media-dir').value='';notice('已选择默认目录，点击保存后生效。');});
  $('save').addEventListener('click',()=>run(async()=>{const result=unwrap(await bridge.apiPost('setup/save',{media_dir:$('media-dir').value,browser_type:$('browser-type').value,autonomy_enabled:$('autonomy').checked,allow_public_comments:$('public-comments').checked,
    max_download_mb:$('max-download').value.trim(),cache_cleanup_enabled:$('cache-cleanup').checked,
    cache_cleanup_interval_hours:$('cleanup-hours').value.trim(),cache_retention_hours:$('retention-hours').value.trim()}));notice(result.message);$('reopen').hidden=!result.browser_reopen_needed;await load();}));
    $('browse').addEventListener('click',()=>{$('folder-dialog').showModal();const value=$('media-dir').value.trim();browse(/^(?:[A-Za-z]:[\\/]|\/|\\\\)/.test(value)?value:'');});
  $('folder-go').addEventListener('click',()=>browse($('folder-path').value.trim()));
  $('folder-path').addEventListener('keydown',event=>{if(event.key==='Enter')browse($('folder-path').value.trim());});
  $('folder-roots').addEventListener('click',()=>browse(''));
  $('folder-up').addEventListener('click',()=>browse(folderParent||''));
  $('folder-cancel').addEventListener('click',()=>$('folder-dialog').close());
  $('folder-use').addEventListener('click',()=>{$('media-dir').value=selectedFolder;$('folder-dialog').close();notice('目录已选中，点击保存后生效。');});
  $('install-playwright').addEventListener('click',()=>install('playwright'));
  $('install-chromium').addEventListener('click',()=>install('chromium'));
  $('reopen').addEventListener('click',()=>control('reopen'));
  document.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>control(button.dataset.action)));
  run(async()=>{if(!bridge)throw new Error('请从 AstrBot 管理面板的插件页面打开接入设置。');await bridge.ready();await load();});
})();
