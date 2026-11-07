// Keep routine chat actions inside the page instead of issuing mouse clicks.
export async function enterReply(page,text) {
  const editor=page.locator('[data-mimi-dm-editor="true"]').first();
  await editor.focus();
  await editor.press('Control+A');
  await editor.press('Backspace');
  await page.keyboard.insertText(text);
  const visible=value=>value.replace(/[\u200b\ufeff]/g,'').trim();
  if(visible(await editor.innerText())!==visible(text))
    throw new Error('输入框未能正确写入，未发送。');
}

export async function submitReply(page) {
  const button=page.locator('.e2e-send-msg-btn:visible');
  if(await button.count()!==1)throw new Error('没有定位到唯一的私信发送按钮。');
  // A single DOM click reaches the page's handler without mouse activation.
  // Never retry this operation if its result or the later send echo is unknown.
  await button.evaluate(node=>{
    if(node.disabled || node.closest('button:disabled,[aria-disabled="true"]'))
      throw new Error('私信发送按钮尚未就绪。');
    if(typeof node.click==='function')node.click();
    else node.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));
  });
}

export async function sendReply(page,snapshot,args) {
  const before=await snapshot();
  const rejected=(receipt,error)=>({state:'not_sent',receipt,error});
  // These checks finish before touching the editor or attempting a click.
  // Exceptions once dispatch starts must retain the caller's unknown outcome.
  if(!before.ready || before.peer.key!==args.peer_key)
    return rejected('recipient_mismatch','当前私信对象与已绑定对象不一致，未发送。');
  if(args.conversation_type&&before.peer.conversation_type!==args.conversation_type)
    return rejected('conversation_type_changed','会话类型已变化，没有发送。');
  if(!before.direction_proven)return rejected('direction_unconfirmed','尚未确认消息的收发方向，未发送。');
  const text=String(args.text||'').trim();
  if(!text || text.length>2000)return rejected('invalid_text','回复为空或超过当前单条文字限制。');
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

export async function openBackgroundPage(context,anchor) {
  // This integration uses Chromium's persistent default context. A normal
  // context.newPage() creates an active tab and can activate the browser app.
  const session=await context.newCDPSession(anchor);
  let targetId;
  try {
    const created=context.waitForEvent('page',{timeout:15000});
    created.catch(()=>{});
    ({targetId}=await session.send('Target.createTarget',{url:'about:blank',background:true}));
    const tab=await created;
    const probe=await context.newCDPSession(tab);
    try {
      const {targetInfo}=await probe.send('Target.getTargetInfo');
      if(targetInfo.targetId!==targetId)throw new Error('视频后台标签页未能正确绑定。');
    } finally {await probe.detach();}
    return tab;
  } catch(error) {
    if(targetId)await session.send('Target.closeTarget',{targetId}).catch(()=>{});
    throw error;
  } finally {await session.detach();}
}
