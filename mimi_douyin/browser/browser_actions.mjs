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
