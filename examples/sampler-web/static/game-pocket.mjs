/** Spend spare height on unresolved instruments while retaining every summary row. */
export function createPocketSignals(query){
 const list=document.getElementById('instruments'),manual=new Map();
 let level=null,expanded=new Set(),frame=0;
 function schedule(){cancelAnimationFrame(frame);frame=requestAnimationFrame(fit);}
 function fit(){
  if(!query.matches)return;
  const details=[...list.querySelectorAll('.pocket-detail')];
  const met=[...list.querySelectorAll('.instrument.met:not(:has(details))')];
  met.forEach(card=>card.classList.remove('pocket-compact'));
  details.forEach(detail=>{detail.open=manual.get(detail.dataset.signal)??false;});
  const next=new Set();
  const usedHeight=()=>list.lastElementChild?list.lastElementChild.getBoundingClientRect().bottom-list.firstElementChild.getBoundingClientRect().top+4:0;
  // Manual expansion may intentionally require scrolling. Never close it for the player.
  const candidates=details.filter(detail=>!manual.has(detail.dataset.signal))
   .sort((a,b)=>Number(a.closest('.instrument').classList.contains('met'))-Number(b.closest('.instrument').classList.contains('met')));
  for(const detail of candidates){
   detail.open=true;
   const reserve=expanded.has(detail.dataset.signal)?0:16;
   if(usedHeight()>list.clientHeight-reserve)detail.open=false;
   else next.add(detail.dataset.signal);
  }
  if(usedHeight()>list.clientHeight)for(const card of met){
   card.classList.add('pocket-compact');if(usedHeight()<=list.clientHeight)break;
  }
  expanded=next;
 }
 new ResizeObserver(schedule).observe(list);
 return {
  begin(id){if(id!==level){manual.clear();expanded.clear();level=id;}},
  attach(detail,key){
   detail.dataset.signal=key;detail.open=!query.matches||(manual.get(key)??expanded.has(key));
   detail.querySelector('summary').addEventListener('click',event=>{
    if(!query.matches)return;
    event.preventDefault();manual.set(key,!detail.open);detail.open=!detail.open;schedule();
   });
  },
  schedule,
 };
}

/** Reorder the same live controls on phones, restoring their exact desktop slots. */
export function installPocketLayout(query, changed) {
 const find=selector=>document.querySelector(selector);
 const frame=document.createElement('section');frame.className='pocket-play';
 const help=document.createElement('details');help.className='pocket-help';
 const summary=document.createElement('summary');summary.textContent='HELP';
 const panel=document.createElement('div');panel.className='pocket-help-panel';help.append(summary,panel);
 const nodes=['.masthead','.plate-head','#instruments','#statusline','#experiment','.guardian-cabinet','.header-guide','#start-over','#debug-panel'].map(find);
 const slots=nodes.map(node=>{const slot=document.createComment('desktop position');node.before(slot);return slot;});
 let currentMode=query.matches,breakpointFocus=null;
 // A media rule can hide the old parent before its change event reaches us.
 document.addEventListener('focusout',event=>{if(query.matches!==currentMode)breakpointFocus=event.target;});
 /** Follow the visible area when a software keyboard reduces the phone viewport. */
 function fitViewport(){
  const viewport=window.visualViewport;
  if(query.matches&&viewport&&viewport.scale===1)frame.style.height=Math.max(180,viewport.height-16)+'px';
  else frame.style.removeProperty('height');
 }
 function layout(){
  const focused=document.activeElement===document.body?breakpointFocus:document.activeElement;
  const selection=focused instanceof HTMLTextAreaElement?[focused.selectionStart,focused.selectionEnd,focused.selectionDirection]:null;
  if(query.matches){
   find('.apparatus').prepend(frame);
   frame.append(...nodes.slice(0,5));
   nodes[0].append(nodes[5],help);panel.append(...nodes.slice(6));
  }else{
   nodes.forEach((node,i)=>slots[i].after(node));help.remove();frame.remove();
  }
  fitViewport();changed();
  if(focused?.isConnected&&focused!==document.body){focused.focus({preventScroll:true});if(selection)focused.setSelectionRange(...selection);}
  currentMode=query.matches;breakpointFocus=null;
 }
 window.visualViewport?.addEventListener('resize',fitViewport);
 query.addEventListener('change',layout);layout();
}
