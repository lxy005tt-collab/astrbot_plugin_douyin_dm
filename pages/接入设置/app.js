(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const bridge=window.AstrBotPluginPage;
  let busy=false,folderParent='',selectedFolder='',installTimer,contextChoices=[],douyinChoices=[],contextSource='',groupShare=false;
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
    $('max-video-duration').value=data.max_video_duration_seconds??180;
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
    $('group-enabled').checked=data.group_chat_enabled!==false;
    $('auto-switch').checked=!!data.auto_switch_enabled;
    $('account-display-name').value=data.account_display_name||'';
    $('group-reply-mode').value=data.group_reply_mode||'仅@机器人';
    $('group-mention-names').value=(data.group_mention_names||[]).join(', ');
    $('group-share-qq-memory').checked=!!data.group_share_qq_memory;
    $('dependencies').replaceChildren();
    for(const dep of data.dependencies){const tr=document.createElement('tr');const name=document.createElement('td');name.textContent=dep.name;const state=document.createElement('td');state.textContent=dep.ready?'可用':'未就绪';state.className=dep.ready?'ready':'missing';const detail=document.createElement('td');detail.append(line(dep.path||'未找到','code'),line(dep.version||dep.hint,'detail'));if(!dep.ready&&dep.url){const a=document.createElement('a');a.href=dep.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='安装说明';detail.append(a);}tr.append(name,state,detail);$('dependencies').append(tr);}
    $('models').textContent='聊天模型：'+data.models.chat+'；视频转述模型：'+data.models.video;
    const bot=data.bot;
    const phase=!bot.auto_reply_enabled?'回复已暂停':bot.processing_message?'正在处理消息（分享内容会先下载和识别，请稍候）':bot.state==='listening'&&!bot.last_error?'正在监听新消息':'回复开关已开启，等待聊天页面就绪';
    $('bot-state').textContent='状态：'+phase+(bot.auto_switch_enabled?' · 白名单自动切换':' · 固定会话')+'；当前对象：'+(bot.binding?.peer?.name||'尚未绑定')+(bot.last_error?'；'+bot.last_error:'');
    $('session').textContent=bot.session_id?'会话标识：'+bot.session_id:'';
    $('optional-memory').textContent=data.optional_memory_available?'LivingMemory（长期记忆插件）已启用。近期上下文无需依赖它；共享长期记忆时使用。':'近期上下文可直接关联；共享长期记忆需要另行安装并启用 LivingMemory 插件。';
    $('install-state').textContent=data.install.message;
    if(data.install.running)pollInstall();
    await loadContext();
  }
  async function loadContext(){
    const data=unwrap(await bridge.apiGet('context/status',{})),settings=data.settings;
    contextSource=data.source_session||'';
    groupShare=!!data.group_share_qq_memory;
    $('context-source').textContent=contextSource?'当前关联来源：'+contextSource:'先在上方绑定抖音会话，再关联已有对话。';
    $('context-enabled').checked=settings.enabled;
    for(const [id,key] of [['context-messages','max_messages'],['context-age','max_age_hours'],['context-chars','max_chars_per_message'],['context-total','max_total_chars']])$(id).value=settings[key];
    $('context-memory').disabled=!data.memory_available;
    $('context-links').replaceChildren();
    for(const link of data.links){const box=document.createElement('div');box.append(line(link.source_session+' → '+link.target_session,'code'),line((link.bidirectional?'双向上下文':'单向上下文')+(link.share_memory?' · 长期记忆已关联':''),'detail'));
      const remove=document.createElement('button');remove.type='button';remove.textContent='解除这项关联';remove.addEventListener('click',()=>run(async()=>{unwrap(await bridge.apiPost('context/link',{action:'remove',source_session:link.source_session}));notice('关联已解除，原聊天记录和已有记忆仍保留。');await loadContext();}));box.append(remove);$('context-links').append(box);}
    await loadContextChoices();
  }
  async function loadContextChoices(){
    const data=unwrap(await bridge.apiPost('context/conversations',{search:$('context-search').value.trim()}));contextChoices=data.conversations||[];
    $('context-conversation').replaceChildren();
    for(const [index,choice] of contextChoices.entries()){
      if(contextSource&&choice.kind!==contextSource.split(':')[1]&&!(contextSource.includes(':GroupMessage:')&&groupShare))continue;
      if(choice.session===contextSource)continue;
      const option=document.createElement('option');option.value=String(index);option.textContent=choice.title+' · '+choice.session; $('context-conversation').append(option);
    }
    if(!$('context-conversation').options.length){const option=document.createElement('option');option.value='';option.textContent='暂无同类型已有对话，请先在目标平台聊天';$('context-conversation').append(option);}
    updateDirection();
  }
  function updateDirection(){
    const choice=contextChoices[Number($('context-conversation').value)];
    const oneWay=contextSource.includes(':GroupMessage:')&&choice?.kind==='FriendMessage';
    $('context-bidirectional').disabled=oneWay;
    if(oneWay)$('context-bidirectional').checked=false;
    $('context-direction').textContent=oneWay?'所选私聊仅向当前群聊提供参考，不能反向读取群聊内容。':'';
  }
  $('context-conversation').addEventListener('change',updateDirection);
  $('context-search').addEventListener('keydown',event=>{if(event.key==='Enter')run(loadContextChoices);});
  $('refresh-context-conversations').addEventListener('click',()=>run(loadContextChoices));
  $('save-context-settings').addEventListener('click',()=>run(async()=>{unwrap(await bridge.apiPost('context/settings',{enabled:$('context-enabled').checked,
    max_messages:$('context-messages').value,max_age_hours:$('context-age').value,max_chars_per_message:$('context-chars').value,max_total_chars:$('context-total').value}));notice('上下文范围已保存，下一次回复生效。');await loadContext();}));
  $('save-context-link').addEventListener('click',()=>run(async()=>{const choice=contextChoices[Number($('context-conversation').value)];if(!$('context-conversation').value||!choice)throw new Error('请选择已有对话。');
    unwrap(await bridge.apiPost('context/link',{source_session:contextSource,target_session:choice.session,target_conversation_id:choice.id,bidirectional:$('context-bidirectional').checked,share_memory:$('context-memory').checked}));notice('已有对话已关联，下一次回复可接续上下文。');await loadContext();}));
  $('list-douyin-conversations').addEventListener('click',()=>run(async()=>{const data=unwrap(await bridge.apiPost('control',{action:'conversations'}));douyinChoices=data.conversations||[];$('douyin-conversations').replaceChildren();
    for(const [index,choice] of douyinChoices.entries()){const option=document.createElement('option');option.value=String(index);option.textContent=choice.name;$('douyin-conversations').append(option);}notice('会话列表已刷新；暂停回复后可打开所选会话。');}));
  $('select-douyin-conversation').addEventListener('click',()=>run(async()=>{const choice=douyinChoices[Number($('douyin-conversations').value)];if(!choice)throw new Error('请先刷新并选择抖音会话。');unwrap(await bridge.apiPost('setup/conversation/select',choice.conversation_id?{conversation_id:choice.conversation_id}:{name:choice.name}));notice('会话已打开，核对对象后点击“绑定当前会话”。');}));
  async function browse(path){
    try{const data=unwrap(await bridge.apiPost('setup/browse',{path:path||''}));selectedFolder=data.path;folderParent=data.parent;$('folder-path').value=data.path;$('folders').replaceChildren();for(const dir of data.directories){const button=document.createElement('button');button.type='button';button.textContent=dir.name;button.addEventListener('click',()=>browse(dir.path));$('folders').append(button);}$('folder-notice').textContent=data.truncated?'只显示前 300 个目录，也可在上方输入完整路径。':data.directories.length?'':'此目录没有子文件夹。';$('folder-use').disabled=!data.path;$('folder-up').disabled=data.parent===null;}catch(error){$('folder-notice').textContent=error.message;}
  }
  async function install(component){await run(async()=>{const data=unwrap(await bridge.apiPost('setup/install',{component}));$('install-state').textContent=data.message;notice('安装已开始，依赖将放在本插件的数据目录。');pollInstall();});}
  function pollInstall(){clearTimeout(installTimer);installTimer=setTimeout(async()=>{try{const data=unwrap(await bridge.apiGet('setup/install/status',{}));$('install-state').textContent=data.message;if(data.running){pollInstall();return;}notice(data.message,!data.success);await run(load);}catch(error){notice(error.message,true);}},1800);}
  async function control(action){await run(async()=>{const result=unwrap(await bridge.apiPost('control',{action}));const hints={open:'登录窗口已打开。请在该窗口登录机器人账号，点击“消息”并进入目标会话。',reopen:'登录窗口已重新打开。请确认已进入目标会话，再查看下方状态；同一对象不必重新绑定。',bind:'已绑定当前会话；已有消息只作为历史记录。核对对象后开启回复，再发送一条新消息。',pause:'回复已暂停。',start:'回复开关已开启。请查看下方状态，并用自己的账号给机器人发送一条新消息。'};notice(hints[action]||'操作已完成。');if(action==='watch_recommended'&&result.state==='skipped'){notice(result.message);$('activity-observation').textContent=result.message;await load();return;}if(action==='watch_recommended')$('activity-observation').textContent=result.url+'\n'+result.transcript.summary+'\n'+(result.transcript.key_facts||[]).join('\n')+'\n作品文案：'+(result.transcript.post_descriptions||[]).join('\n');await load();});}
  $('refresh').addEventListener('click',()=>run(load));
  $('default-dir').addEventListener('click',()=>{$('media-dir').value='';notice('已选择默认目录，点击保存后生效。');});
  $('save').addEventListener('click',()=>run(async()=>{const result=unwrap(await bridge.apiPost('setup/save',{media_dir:$('media-dir').value,browser_type:$('browser-type').value,autonomy_enabled:$('autonomy').checked,allow_public_comments:$('public-comments').checked,
    account_display_name:$('account-display-name').value,auto_switch_enabled:$('auto-switch').checked,group_chat_enabled:$('group-enabled').checked,group_reply_mode:$('group-reply-mode').value,group_mention_names:$('group-mention-names').value,group_share_qq_memory:$('group-share-qq-memory').checked,
    max_download_mb:$('max-download').value.trim(),max_video_duration_seconds:$('max-video-duration').value.trim(),cache_cleanup_enabled:$('cache-cleanup').checked,
    cache_cleanup_interval_hours:$('cleanup-hours').value.trim(),cache_retention_hours:$('retention-hours').value.trim()}));notice(result.message+(result.browser_reopen_needed?' 请点击下方“重开登录窗口”应用新的浏览器选择。':''));await load();}));
    $('save-connection').addEventListener('click',()=>$('save').click());
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
  document.querySelectorAll('[data-panel]').forEach(button=>button.addEventListener('click',()=>{for(const tab of document.querySelectorAll('[data-panel]')){const selected=tab===button;tab.setAttribute('aria-selected',String(selected));document.getElementById('panel-'+tab.dataset.panel).hidden=!selected;}}));
  run(async()=>{if(!bridge)throw new Error('请从 AstrBot 管理面板的插件页面打开接入设置。');await bridge.ready();await load();});
})();
