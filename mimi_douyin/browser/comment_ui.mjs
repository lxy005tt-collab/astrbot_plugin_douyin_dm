const editorSelector=[
  '.comment-input-inner-container [contenteditable="true"]','.comment-input-inner-container [contenteditable="plaintext-only"]',
  '.comment-input-inner-container textarea','.comment-input-inner-container input',
  '[data-e2e="comment-input"][contenteditable="true"]','[data-e2e="comment-input"] [contenteditable="true"]',
  '[data-e2e="comment-input"] textarea','textarea[placeholder*="评论"]',
  '[contenteditable="true"][data-placeholder*="评论"]'
].join(',');

export async function getCommentEditor(tab) {
  let editor=tab.locator(editorSelector).filter({visible:true});
  if(await editor.count()===0) {
    const placeholder=tab.locator('.comment-input-inner-container').filter({visible:true});
    if(await placeholder.count()===1) {
      await placeholder.evaluate(node=>node.click());
      await tab.waitForTimeout(500);
      editor=tab.locator(editorSelector).filter({visible:true});
    }
  }
  if(await editor.count()!==1)throw new Error('评论输入框未就绪，请检查账号验证或该作品的评论权限。');
  return editor;
}

export async function getCommentSubmit(tab) {
  const count=await tab.evaluate(()=>{
    document.querySelectorAll('[data-mimi-comment-submit]').forEach(node=>node.removeAttribute('data-mimi-comment-submit'));
    const inner=document.querySelector('.comment-input-inner-container');
    let root=inner;
    for(let depth=0;root&&root.parentElement&&depth<3;depth++) {
      if(root.parentElement.querySelector('[data-e2e="comment-list"]'))break;
      root=root.parentElement;
    }
    const nodes=root?[root,...root.querySelectorAll('button,[role="button"],div,span,[data-e2e]')]
      :[...document.querySelectorAll('[data-e2e="comment-post"],[data-e2e="comment-submit"]')];
    const candidates=nodes.filter(node=>/^(发送|发布)$/.test((node.innerText||'').replace(/\s+/g,''))
      &&node.getBoundingClientRect().width>0&&node.getBoundingClientRect().height>0);
    const leaves=candidates.filter(node=>!candidates.some(child=>child!==node&&node.contains(child)));
    let controls=[...new Set(leaves.map(node=>node.closest('button,[role="button"]')||node))];
    if(!controls.length) {
      // The observed Draft.js composer uses an unlabelled SVG send control.
      // Select it only when exactly one composer control changes state from
      // the empty draft to the filled draft; never guess by screen position.
      controls=[...document.querySelectorAll('.commentInput-right-ct [data-mimi-empty-comment-class]')]
        .filter(node=>(node.getAttribute('class')||'')!==node.getAttribute('data-mimi-empty-comment-class'));
    }
    if(controls.length===1)controls[0].setAttribute('data-mimi-comment-submit','true');
    return controls.length;
  });
  if(count!==1)throw new Error('没有定位到唯一的评论提交按钮，未提交。');
  return tab.locator('[data-mimi-comment-submit="true"]');
}

export async function captureEmptyCommentControls(tab) {
  await tab.waitForTimeout(100);
  await tab.evaluate(()=>{
    for(const node of document.querySelectorAll('.commentInput-right-ct span')) {
      const props=Object.keys(node).filter(key=>key.startsWith('__reactProps')).map(key=>node[key]);
      if(!node.querySelector('span')&&props.some(prop=>typeof prop?.onClick==='function'))
        node.setAttribute('data-mimi-empty-comment-class',node.getAttribute('class')||'');
    }
  });
}
