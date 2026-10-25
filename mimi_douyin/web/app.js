(() => {
  'use strict';
  document.documentElement.dataset.theme=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  const $=id=>document.getElementById(id);let busy=false,parent='',folder='',timer;
  function notice(message,error=false){$('notice').textContent=message;$('notice').classList.toggle('error',error);}
  async function api(path,payload){
    const response=await fetch('/api/'+path,payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const raw=await response.text();
    let body;
    try{body=JSON.parse(raw);}catch{throw new Error('请求失败（HTTP '+response.status+'）：'+raw.slice(0,120));}
    if(!response.ok)throw new Error((body&&body.message)||('请求失败（HTTP '+response.status+'）。'));
    if(!body||body.status!=='ok')throw new Error((body&&body.message)||'请求失败。');
    return body.data;
  }
  async function run(action){if(busy)return;busy=true;document.querySelectorAll('main button').forEach(button=>button.disabled=true);try{await action();}catch(error){notice(error.message,true);}finally{busy=false;document.querySelectorAll('main button').forEach(button=>button.disabled=false);}}
  async function load(){
    const data=await api('status');
    for(const field of $('settings').elements){if(!field.name||['api_key','video_api_key'].includes(field.name))continue;const value=data.settings[field.name];if(field.type==='checkbox')field.checked=!!value;else field.value=Array.isArray(value)?value.join('\n'):value??'';}
    $('api-key').placeholder=data.settings.api_key_configured?'已保存；留空保留':'填写接口密钥';
    $('video-key').placeholder=data.settings.video_api_key_configured?'已保存独立密钥；留空保留':'留空沿用聊天接口密钥';
    $('use-chat-key').checked=false;
    $('effective-dir').textContent='当前保存位置：'+data.runtime.media_dir+'；登录资料：'+data.runtime.browser_profile;
    const cache=data.cache_cleanup||{},last=cache.last_cleanup;
    $('cache-state').textContent=(cache.cache_cleanup_enabled?'下次清理：'+(cache.next_run_at?new Date(cache.next_run_at*1000).toLocaleString():'等待计时'):'定时清理未开启。')+
      (last?'；上次清理 '+last.deleted_files+' 个文件，释放 '+(last.deleted_bytes/1024/1024).toFixed(1)+' MB':'')+(cache.last_error?'；'+cache.last_error:'');
    $('dependencies').replaceChildren();
    for(const dependency of data.runtime.dependencies){const row=document.createElement('tr');for(const value of [dependency.name,dependency.ready?'可用':'未就绪',(dependency.path||dependency.hint)+(dependency.version?' · '+dependency.version:'')]){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}if(!dependency.ready&&dependency.url){const link=document.createElement('a');link.href=dependency.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='安装说明';row.lastChild.append(document.createElement('br'),link);}$('dependencies').append(row);}
    $('state').textContent=(data.bot.auto_reply_enabled?'回复已开启':'回复已暂停')+(data.bot.last_error?'；'+data.bot.last_error:'');
    $('binding').textContent=data.bot.binding?'当前对象：'+data.bot.binding.peer.name+'；会话标识：'+data.bot.binding.peer.key:'还没有绑定私信。';
    $('install-state').textContent=data.install.message;if(data.install.running)poll();
  }
  $('settings').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    const values={};for(const field of $('settings').elements){if(!field.name)continue;values[field.name]=field.type==='checkbox'?field.checked:field.type==='number'?(field.value.trim()===''?'':Number(field.value)):field.name==='private_whitelist'?field.value.split('\n').map(value=>value.trim()).filter(Boolean):field.value;}
    if(String(values.video_api_key||'').trim())values.use_chat_video_key=false;
    const result=await api('settings',values);$('api-key').value='';$('video-key').value='';notice(result.message);await load();
  });});
  $('refresh').addEventListener('click',()=>run(load));
  $('test-model').addEventListener('click',()=>run(async()=>{const result=await api('model/test',{});notice(result.message);}));
  document.querySelectorAll('[data-control]').forEach(button=>button.addEventListener('click',()=>run(async()=>{await api('control',{action:button.dataset.control});notice('操作完成。');await load();})));
  document.querySelectorAll('[data-install]').forEach(button=>button.addEventListener('click',()=>run(async()=>{const state=await api('install',{component:button.dataset.install});$('install-state').textContent=state.message;poll();})));
  function poll(){clearTimeout(timer);timer=setTimeout(async()=>{try{const state=await api('install/status');$('install-state').textContent=state.message;if(state.running)poll();else await run(load);}catch(error){notice(error.message,true);}},1800);}
  $('watch').addEventListener('click',()=>run(async()=>{notice('正在实际读取推荐作品…');const record=await api('watch',{});$('observation').textContent=record.transcript.summary+'\n'+(record.transcript.key_facts||[]).join('\n')+'\n声音：'+record.transcript.audio+'\n作品文案：'+(record.transcript.post_descriptions||[]).join('\n');$('comment-url').value=record.url;notice('已收到实际内容转述。');}));
  $('comment').addEventListener('click',()=>run(async()=>{const result=await api('comment',{url:$('comment-url').value,text:$('comment-text').value});notice(result.state==='sent'?'评论已提交，评论 ID：'+result.comment_id:'提交状态：'+result.state+'，不会自动重发。',result.state!=='sent');}));
  async function browse(path){try{const result=await api('browse',{path:path||''});folder=result.path;parent=result.parent;$('folder-path').value=folder;$('folders').replaceChildren();for(const directory of result.directories){const button=document.createElement('button');button.textContent='📁 '+directory.name;button.addEventListener('click',()=>browse(directory.path));$('folders').append(button);}$('folder-use').disabled=!folder;$('folder-up').disabled=parent===null;$('folder-notice').textContent=result.truncated?'仅显示前300个目录，也可输入完整路径。':'';}catch(error){$('folder-notice').textContent=error.message;}}
  $('browse').addEventListener('click',()=>{$('folder-dialog').showModal();const value=$('media-dir').value.trim();browse(/^(?:[A-Za-z]:[\\/]|\/|\\\\)/.test(value)?value:'');});
  $('folder-go').addEventListener('click',()=>browse($('folder-path').value));$('folder-roots').addEventListener('click',()=>browse(''));$('folder-up').addEventListener('click',()=>browse(parent||''));
  $('folder-cancel').addEventListener('click',()=>$('folder-dialog').close());$('folder-use').addEventListener('click',()=>{$('media-dir').value=folder;$('folder-dialog').close();notice('目录已选中，点击保存后生效。');});
  $('video-key').addEventListener('input',()=>{if($('video-key').value.trim())$('use-chat-key').checked=false;});
  run(load);
})();
