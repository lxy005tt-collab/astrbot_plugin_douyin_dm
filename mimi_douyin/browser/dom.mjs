export function readChatDOM({debug=false}={}) {
    const visible=el=>el && el.getBoundingClientRect().width>10 && el.getBoundingClientRect().height>8;
    const factsFor=node=>{
      const facts={video_ids:[],links:[],message_ids:[],conversation_ids:[],shapes:[]};
      const seen=new WeakSet();let budget=1500;
      const walk=(value,depth,label='')=>{
        if(!value||typeof value!=='object'||depth>9||--budget<0||seen.has(value))return;
        seen.add(value);
        const keys=Object.keys(value);
        if(debug&&/message|content|data|item/i.test(label)&&facts.shapes.length<16)
          facts.shapes.push({at:label,keys:keys.slice(0,35)});
        for(const key of keys.slice(0,80)){
          let child;try{child=value[key];}catch{continue;}
          if(typeof child==='string'||typeof child==='number'){
            const text=String(child);
            if(/^(aweme_?id|item_?id)$/i.test(key)&&/^\d{12,24}$/.test(text))facts.video_ids.push(text);
            if(/^(message_?id|server_?id|client_?id)$/i.test(key)&&text.length<100)facts.message_ids.push(text);
            if(/^conversation_?id$/i.test(key)&&text.length<150)facts.conversation_ids.push(text);
            if(/^(share_?url|url)$/i.test(key)&&/^https:\/\/(?:www\.|v\.)?douyin\.com\//.test(text))facts.links.push(text);
            if(/^(content|body|data)$/i.test(key)&&text.startsWith('{')&&text.length<50000){
              try{walk(JSON.parse(text),depth+1,key);}catch{}
            }
          }else if(child&&typeof child==='object'&&
            /^(children|props|message|msg|content|parsedContent|conversation|conversationInfo|conversationModel|data|item|body|record|info|messageInfo|messageModel|_content|_message)$/i.test(key)){
            if(Array.isArray(child))child.slice(0,12).forEach(x=>walk(x,depth+1,key));
            else walk(child,depth+1,key);
          }
        }
      };
      for(const el of [node,...node.querySelectorAll('*')].slice(0,100))
        for(const key of Object.keys(el).filter(k=>k.startsWith('__reactProps')))
          walk(el[key],0,'props');
      return facts;
    };
    const editor=[...document.querySelectorAll('.messageEditorinputArea,[contenteditable="true"][role="textbox"],[contenteditable="true"]')].find(visible);
    if(!editor)return {ready:false,reason:'请打开消息面板，并选中要绑定的私信会话。',...(debug?{diagnostics:{
      navigation:[...document.querySelectorAll('[data-e2e]')].filter(x=>/im-|conversation/.test(x.getAttribute('data-e2e'))).slice(0,15).map(x=>({tag:x.tagName,className:String(x.className),'data-e2e':x.getAttribute('data-e2e')})),
      conversations:[...document.querySelectorAll('[data-e2e="conversation-item"]')].slice(0,15).map(x=>({facts:factsFor(x),prop_keys:Object.keys(x).filter(k=>k.startsWith('__reactProps')).map(k=>Object.keys(x[k]||{}))}))}}:{})};
    let root=editor;
    while(root.parentElement && !root.querySelector('div[data-index],[data-message-id],[data-msg-id]'))root=root.parentElement;
    if(root===document.body || root===document.documentElement)return {ready:false,reason:'尚未定位到私信消息列表。'};
    let area=root;
    for(let i=0;i<3 && area.parentElement;i++) {
      if(area.querySelector('[class*="chatHeader"],[class*="ChatHeader"],[data-e2e="chat-header"],[class*="chatInfo"]'))break;
      area=area.parentElement;
    }
    const header=area.querySelector('[class*="chatHeader"],[class*="ChatHeader"],[data-e2e="chat-header"],[class*="chatInfo"]');
    const selected=[...document.querySelectorAll('[data-e2e="conversation-item"],[class*="conversationItem"],.conversationConversationItemwrapper')]
      .find(x=>x.getAttribute('aria-selected')==='true'||/selected|active/i.test(String(x.className)));
    const peerName=header?.querySelector('[class*="name"],[class*="Name"]')?.textContent?.trim()
      || header?.innerText?.trim().split('\n')[0] || selected?.querySelector('[class*="name"],[class*="Name"]')?.textContent?.trim() || '';
    const peerLink=header?.querySelector('a[href*="/user/"]')?.href || selected?.querySelector('a[href*="/user/"]')?.href || '';
    const avatar=header?.querySelector('img')?.src || selected?.querySelector('img')?.src || '';
    let conversationID=selected?.getAttribute('data-conversation-id') || header?.getAttribute('data-conversation-id') || '';
    editor.setAttribute('data-mimi-dm-editor','true');
    const raw=[...root.querySelectorAll('[data-message-id],[data-msg-id],div[data-index]')]
      .filter(x=>visible(x)&&!x.parentElement?.closest('[data-message-id],[data-msg-id],div[data-index]'));
    const ownClass=raw.some(x=>/isFromMe/i.test(String(x.className))||x.querySelector('[class*="isFromMe"],[class*="IsFromMe"]'));
    const items=raw.map((box,position)=>{
      if(box.querySelector('[class*="isFullRowCenterMessage"],[class*="SystemNormalSystem"]'))return null;
      const facts=factsFor(box);
      conversationID ||= facts.conversation_ids[0] || '';
      const own=/isFromMe/i.test(String(box.className))||!!box.querySelector('[class*="isFromMe"],[class*="IsFromMe"]');
      const textElement=box.querySelector('[class*="pureText"],[class*="textInnerContent"],[class*="bubbleContent"],[data-e2e="msg-item-content"]');
      const text=(textElement?.innerText || box.innerText || '').replace(/[\u200b\ufeff]/g,'').trim();
      const links=[...new Set([...box.querySelectorAll('a[href]')].map(x=>x.href).filter(x=>/douyin\.com|iesdouyin\.com/.test(x)).concat(facts.links,facts.video_ids.map(id=>'https://www.douyin.com/video/'+id)))];
      const images=[...box.querySelectorAll('img')].filter(x=>!x.closest('[class*="avatar"],[class*="Avatar"]')).map(x=>x.src).slice(0,4);
      const video=links.some(x=>/\/(?:video|note)\/|\/share\/(?:video|note)\/|v\.douyin\.com/.test(x))||!!box.querySelector('[class*="videoMessage"],[class*="VideoMessage"],[data-e2e*="video"]');
      const id=box.getAttribute('data-message-id')||box.getAttribute('data-msg-id')||facts.message_ids[0]||'';
      const index=Number(box.getAttribute('data-index'));
      box.setAttribute('data-mimi-dm-position',String(position));
      return {native_id:id,index:Number.isFinite(index)?index:position,position,sender:own?'me':'peer',
        text,links,images,kind:video?'video':images.length&&!text?'image':'text',
        className:String(box.className),failed:!!box.querySelector('[class*="sendFail"],[class*="SendFail"]'),
        pending:!!box.querySelector('[class*="sending"],[class*="Sending"]'),
        ...(debug?{prop_shapes:facts.shapes}: {})};
    }).filter(x=>x&&(x.text||x.links.length||x.images.length));
    if(raw.every(x=>x.hasAttribute('data-index')))items.sort((a,b)=>b.index-a.index);
    let diagnostics;
    if(debug) {
      const outline=(node,depth=0)=>({tag:node.tagName,className:String(node.className||''),
        attrs:Object.fromEntries([...node.attributes].filter(a=>a.name!=='src'&&a.name!=='style'&&a.name!=='href').map(a=>[a.name,a.value.slice(0,150)])),
        props:Object.keys(node).filter(k=>k.startsWith('__reactProps')).map(k=>Object.keys(node[k]||{})),
        children:depth<8?[...node.children].slice(0,6).map(x=>outline(x,depth+1)):[]});
      diagnostics={header:header?outline(header):null,latest:raw.slice(0,2).map(x=>outline(x)),
        editor_area:outline(editor.parentElement.parentElement),draft_length:editor.innerText.length,draft_codepoints:[...editor.innerText].map(c=>c.codePointAt(0)),
        send_controls:[...root.querySelectorAll('button,[role="button"],[class*="send"],[class*="Send"]')].filter(visible).slice(-15).map(x=>({tag:x.tagName,className:String(x.className),text:x.innerText?.slice(0,80),attrs:Object.fromEntries([...x.attributes].filter(a=>a.name!=='style').map(a=>[a.name,a.value]))})),
        navigation:[...document.querySelectorAll('[data-e2e]')].filter(x=>/im-|message/.test(x.getAttribute('data-e2e'))).slice(0,8).map(x=>({tag:x.tagName,className:String(x.className),parent_class:String(x.parentElement.className),'data-e2e':x.getAttribute('data-e2e')})),
        conversations:[...document.querySelectorAll('.conversationConversationItemwrapper')].filter(visible).slice(0,8).map(x=>({className:String(x.className),name:x.querySelector('[class*="name"],[class*="Name"]')?.textContent?.trim(),attrs:Object.fromEntries([...x.attributes].map(a=>[a.name,a.value]))})),
        root:root.tagName,root_class:root.className};
    }
    return {ready:true,peer:{name:peerName,link:peerLink,avatar,conversation_id:conversationID},
      direction_proven:ownClass,items,editor_class:editor.className,root_class:root.className,diagnostics};
}
