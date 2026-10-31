// Select only an observed, uniquely matched IM row. No message is sent here.
export async function activateConversation(page,choice,snapshot){
  const row=page.locator('[data-mimi-chat-index="'+choice.index+'"]');
  await row.dispatchEvent(choice.activation_event==='mousedown'?'mousedown':'click',{button:0});
  let selected;
  for(let attempt=0;attempt<12;attempt++){
    await page.waitForTimeout(250);
    selected=await snapshot();
    if(selected.ready&&selected.peer?.conversation_id===choice.conversation_id)return selected;
  }
  throw new Error('会话切换尚未确认，未处理或发送消息；请确认消息面板仍打开。');
}
