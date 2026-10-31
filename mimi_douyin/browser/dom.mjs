export function readChatDOM({debug=false,conversations_only=false}={}) {
    const visible=el=>el && el.getBoundingClientRect().width>10 && el.getBoundingClientRect().height>8;
    const factsFor=node=>{
      const facts={video_ids:[],links:[],message_ids:[],conversation_ids:[],conversation_types:[],conversation_names:[],unread_counts:[],latest_message_ids:[],sender_ids:[],sender_names:[],from_me_flags:[],mentioned_ids:[],shapes:[]};
      const seen=new WeakSet();let budget=1500;
      const walk=(value,depth,label='')=>{
        if(!value||typeof value!=='object'||depth>9||--budget<0||seen.has(value))return;
        seen.add(value);
        const keys=Object.keys(value);
        if(/^(message|msg|messageModel|record)$/i.test(label)){
          for(const key of ['serverId','server_id','messageId','message_id','clientId','client_id']){
            const id=value[key];
            if((typeof id==='string'||typeof id==='number')&&String(id)&&String(id)!=='0'&&String(id).length<100)
              facts.message_ids.push(String(id));
          }
        }
        // IM model identifiers are prototype getters, not enumerable own keys.
        const conversationID=value.conversationId??value.conversation_id;
        if(conversationID!=null&&String(conversationID).length<150)facts.conversation_ids.push(String(conversationID));
        const conversationType=value.conversationType??value.conversation_type;
        if([1,2].includes(Number(conversationType)))facts.conversation_types.push(Number(conversationType));
        if(/^conversation/i.test(label)){
          if(value.id!=null&&String(value.id).length<150)facts.conversation_ids.push(String(value.id));
          if([1,2].includes(Number(value.type)))facts.conversation_types.push(Number(value.type));
          const name=value.name??value.conversationName??value.displayName??value.coreInfo?.name;
          if(typeof name==='string'&&name)facts.conversation_names.push(name);
          for(const key of ['unreadCount','unreadMessageCount','unread_count','badgeCount']){
            const count=value[key];
            if(typeof count==='number'&&Number.isFinite(count)&&count>=0)facts.unread_counts.push(count);
          }
          const last=value.lastVisibleMessage??value.lastMessage??value.lastMsg;
          if(last){const id=last.serverId&&String(last.serverId)!=='0'?last.serverId:(last.messageId??last.clientId);if(id!=null)facts.latest_message_ids.push(String(id));}
        }
        if(typeof value.isMyMessage==='boolean')facts.from_me_flags.push(value.isMyMessage);
        if(typeof value.isFromMe==='boolean')facts.from_me_flags.push(value.isFromMe);
        for(const key of ['mentioned_users','mentioned_user_ids','mentionedUsers','mentionedUserIds','at_users'])
          if(Array.isArray(value[key]))for(const entry of value[key]){
            const id=typeof entry==='object'?(entry.uid??entry.user_id??entry.userId):entry;
            if(id!=null)facts.mentioned_ids.push(String(id));
          }
        const sender=value.senderInfo||value.sender_info||value.senderUser||value.sender_user;
        const senderID=value.senderUid??value.sender_uid??value.senderUserId??value.sender_user_id??
          (typeof value.sender==='string'||typeof value.sender==='number'?value.sender:null)??sender?.uid??sender?.user_id??sender?.userId;
        if(senderID!=null&&String(senderID))facts.sender_ids.push(String(senderID));
        const senderName=sender?.nickname??sender?.nick_name??sender?.name;
        if(typeof senderName==='string'&&senderName)facts.sender_names.push(senderName);
        if(debug&&facts.shapes.length<24)
          {let proto=Object.getPrototypeOf(value),inherited=[];
            for(let i=0;i<4&&proto;i++,proto=Object.getPrototypeOf(proto))inherited.push(...Object.getOwnPropertyNames(proto));
            facts.shapes.push({at:label,keys:keys.slice(0,35),prototype_keys:[...new Set(inherited)].slice(0,140)});}
        for(const key of keys.slice(0,80)){
          let child;try{child=value[key];}catch{continue;}
          if(typeof child==='string'||typeof child==='number'){
            const text=String(child);
            if(/^(aweme_?id|item_?id)$/i.test(key)&&/^\d{12,24}$/.test(text))facts.video_ids.push(text);
            if(/^(message_?id|server_?id|client_?id)$/i.test(key)&&text.length<100)facts.message_ids.push(text);
            if(/^conversation_?id$/i.test(key)&&text.length<150)facts.conversation_ids.push(text);
            if(/^(conversation_?type|conversationType)$/i.test(key)&&['1','2'].includes(text))facts.conversation_types.push(Number(text));
            if(/^(share_?url|url)$/i.test(key)&&/^https:\/\/(?:www\.|v\.)?douyin\.com\//.test(text))facts.links.push(text);
            if(/^(content|body|data)$/i.test(key)&&text.startsWith('{')&&text.length<50000){
              try{walk(JSON.parse(text),depth+1,key);}catch{}
            }
          }else if(child&&typeof child==='object'&&
            /^(children|props|message|msg|content|parsedContent|conversation|conversationInfo|conversationModel|data|item|body|record|info|messageInfo|messageModel|_content|_message|senderInfo|sender_info|senderUser|sender_user)$/i.test(key)){
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
    const conversationNodes=[...document.querySelectorAll('[data-e2e="conversation-item"]')].filter(visible);
    const brief=(node,depth=0)=>({tag:node.tagName,className:String(node.className||''),
      text:depth>=2?node.textContent?.slice(0,100):undefined,
      props:Object.keys(node).filter(k=>k.startsWith('__reactProps')).map(k=>Object.keys(node[k]||{})),
      children:depth<2?[...node.children].slice(0,8).map(child=>brief(child,depth+1)):[]});
    const conversations=conversationNodes.map((node,index)=>{
      node.setAttribute('data-mimi-chat-index',String(index));
      const facts=factsFor(node);
      const name=facts.conversation_names[0]||node.querySelector('[class$="title"],[class*="nickname"],[class*="NickName"],[class*="Name"],[class*="name"]')?.textContent?.trim()
        ||node.innerText?.trim().split('\n').find(Boolean)||'';
      return {index,name,conversation_id:facts.conversation_ids[0]||'',conversation_type:facts.conversation_types[0]||null,
        unread_count:facts.unread_counts.length?facts.unread_counts[0]:null,latest_message_id:facts.latest_message_ids[0]||'',
        activation_event:Object.keys(node).filter(key=>key.startsWith('__reactProps')).some(key=>typeof node[key]?.onMouseDown==='function')?'mousedown':'click',
        ...(debug?{facts,node:brief(node)}: {})};
    });
    if(conversations_only)return {ready:false,conversations};
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
    const peerName=header?.querySelector('[class$="ChatHeadertitle"],[class*="name"],[class*="Name"]')?.textContent?.trim()
      || header?.innerText?.trim().split('\n')[0] || selected?.querySelector('[class*="name"],[class*="Name"]')?.textContent?.trim() || '';
    const peerLink=header?.querySelector('a[href*="/user/"]')?.href || selected?.querySelector('a[href*="/user/"]')?.href || '';
    const avatar=header?.querySelector('img')?.src || selected?.querySelector('img')?.src || '';
    let conversationID=selected?.getAttribute('data-conversation-id') || header?.getAttribute('data-conversation-id') || '';
    const headerFacts=factsFor(header||area),selectedFacts=selected?factsFor(selected):null;
    conversationID ||= headerFacts.conversation_ids[0]||selectedFacts?.conversation_ids[0]||'';
    let conversationType=headerFacts.conversation_types[0]||selectedFacts?.conversation_types[0]||null;
    editor.setAttribute('data-mimi-dm-editor','true');
    const raw=[...root.querySelectorAll('[data-message-id],[data-msg-id],div[data-index]')]
      .filter(x=>visible(x)&&!x.parentElement?.closest('[data-message-id],[data-msg-id],div[data-index]'));
    const ownClass=raw.some(x=>/isFromMe/i.test(String(x.className))||x.querySelector('[class*="isFromMe"],[class*="IsFromMe"]'));
    const items=raw.map((box,position)=>{
      if(box.querySelector('[class*="isFullRowCenterMessage"],[class*="SystemNormalSystem"]'))return null;
      const facts=factsFor(box);
      conversationType ||= facts.conversation_types[0]||null;
      conversationID ||= facts.conversation_ids[0] || '';
      const ownCSS=/isFromMe/i.test(String(box.className))||!!box.querySelector('[class*="isFromMe"],[class*="IsFromMe"]');
      const own=ownCSS||(!ownClass&&facts.from_me_flags.length>0&&facts.from_me_flags.every(Boolean));
      const textElement=box.querySelector('[class*="pureText"],[class*="textInnerContent"],[class*="bubbleContent"],[data-e2e="msg-item-content"]');
      const text=(textElement?.innerText || box.innerText || '').replace(/[\u200b\ufeff]/g,'').trim();
      const links=[...new Set([...box.querySelectorAll('a[href]')].map(x=>x.href).filter(x=>/douyin\.com|iesdouyin\.com/.test(x)).concat(facts.links,facts.video_ids.map(id=>'https://www.douyin.com/video/'+id)))];
      const images=[...box.querySelectorAll('img')].filter(x=>!x.closest('[class*="avatar"],[class*="Avatar"],[class*="ContentBottomHasRead"]')).map(x=>x.src).slice(0,4);
      const video=links.some(x=>/\/(?:video|note)\/|\/share\/(?:video|note)\/|v\.douyin\.com/.test(x))||!!box.querySelector('[class*="videoMessage"],[class*="VideoMessage"],[data-e2e*="video"]');
      const id=box.getAttribute('data-message-id')||box.getAttribute('data-msg-id')||facts.message_ids[0]||'';
      const memberLink=box.querySelector('[class*="avatar"] a[href*="/user/"],[class*="Avatar"] a[href*="/user/"],a[href*="/user/"]')?.href||'';
      const memberName=facts.sender_names[0]||box.querySelector('[class*="avatarName"],[class*="nickname"],[class*="NickName"],[class*="senderName"],[class*="SenderName"],[class*="userName"],[class*="UserName"]')?.textContent?.trim()||'';
      const memberAvatar=box.querySelector('[class*="avatar"] img,[class*="Avatar"] img')?.src||'';
      const memberID=facts.sender_ids[0]||memberLink||(memberName&&memberAvatar?'visible:'+memberName+'|'+memberAvatar.split('?')[0]:'');
      const index=Number(box.getAttribute('data-index'));
      box.setAttribute('data-mimi-dm-position',String(position));
      return {native_id:id,index:Number.isFinite(index)?index:position,position,sender:own?'me':'peer',
        text,links,images,kind:video?'video':images.length&&!text?'image':'text',
        sender_id:memberID,sender_name:memberName,member_avatar:memberAvatar,mentioned_ids:facts.mentioned_ids,direction_known:facts.from_me_flags.length>0,
        className:String(box.className),failed:!!box.querySelector('[class*="sendFail"],[class*="SendFail"]'),
        pending:!!box.querySelector('[class*="sending"],[class*="Sending"]'),
        ...(debug?{prop_shapes:facts.shapes,direction_flags:facts.from_me_flags,
          observed_message_ids:facts.message_ids,
          css_from_me:/isFromMe/i.test(String(box.className))||!!box.querySelector('[class*="isFromMe"],[class*="IsFromMe"]')}: {})};
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
    // The web client exposes IM conversation type (1=private, 2=group).
    // Multiple visible sender names also establish a group; a title alone does not.
    const namedPeers=new Set(items.filter(x=>x.sender==='peer'&&x.sender_name).map(x=>x.sender_id||x.sender_name));
    const group=conversationType===2||(conversationType!==1&&(namedPeers.size>1||!!header?.querySelector('[class*="groupMember"],[class*="GroupMember"]')));
    const selfUserID=items.find(x=>x.sender==='me'&&x.sender_id)?.sender_id||'';
    const selfUserName=items.find(x=>x.sender==='me'&&x.sender_name)?.sender_name||'';
    if(group)for(const item of items){
      item.mentioned_bot=!!selfUserID&&(item.mentioned_ids.includes(selfUserID)||(item.text.includes('@')&&item.text.includes(selfUserID)));
    }
    return {ready:true,peer:{name:peerName,link:group?'':peerLink,avatar,conversation_id:conversationID,
        conversation_type:group?'group':'private',self_user_id:selfUserID,self_user_name:selfUserName},conversations,
      direction_proven:ownClass||items.some(item=>item.direction_known),items,editor_class:editor.className,root_class:root.className,diagnostics};
}
