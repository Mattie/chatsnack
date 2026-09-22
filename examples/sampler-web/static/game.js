const el=id=>document.getElementById(id);
const config=JSON.parse(el('config').textContent);
const stateUrl=new URL('./game-state.mjs',import.meta.url);stateUrl.searchParams.set('v',config.assetVersion);
const {Experiment,analysisActivity,automaticAnalysisDelay,categoryTargetText,readingMeets}=await import(stateUrl);
const pocketQuery=window.matchMedia('(max-width:760px)');
const pocketUrl=new URL('./game-pocket.mjs',import.meta.url);pocketUrl.searchParams.set('v',config.assetVersion);
const {installPocketLayout,createPocketSignals}=await import(pocketUrl);
const pocketSignals=createPocketSignals(pocketQuery);
const debug=new URLSearchParams(window.location.search).get('debug')==='1';
const progressKey='chatsnack.mad-hacker.progress.v1';
let autoTimer=null,pendingManual=false,scopeSettlingTimer=null,scopeDiscoveryTimer=null,discoveryStatusTimer=null,lastScopeAttempt=0;

function readProgress(){try{return JSON.parse(localStorage.getItem(progressKey));}catch{return null;}}
function clearStoredProgress(){try{localStorage.removeItem(progressKey);}catch{}}

const game=new Experiment(config.levels,config.configured,async(level,text)=>{
 const response=await fetch('/api/game',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({level,text,accepted:game.acceptedToken,reset:game.serverResetPending})});
 let data;
 try{data=await response.json();}catch{throw new Error("The analyzer couldn't complete the readings. Press Enter to retry.");}
 if(!response.ok)throw new Error(data.error||"The analyzer couldn't complete the readings. Press Enter to retry.");
 return data;
},()=>{},()=>Date.now(),async token=>{
 const response=await fetch('/api/game/accept',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
 if(!response.ok)throw new Error('The accepted solution could not be recorded.');
});
const savedProgress=readProgress();
const restoredProgress=savedProgress&&game.restoreProgress(savedProgress);
if(savedProgress&&!restoredProgress)clearStoredProgress();
if(restoredProgress&&Number.isInteger(config.unlocked))game.unlocked=Math.max(game.unlocked,config.unlocked);
if(!restoredProgress&&Number.isInteger(config.unlocked)&&config.unlocked>0)game.resumeAt(config.unlocked);
let lastStoredProgress='';
function persistProgress(){
 const progress=game.exportProgress();
 if(!Object.keys(progress.completed).length&&!progress.pending){clearStoredProgress();lastStoredProgress='';return;}
 const serialized=JSON.stringify(progress);
 if(serialized===lastStoredProgress)return;
 try{localStorage.setItem(progressKey,serialized);lastStoredProgress=serialized;}catch{}
}
game.changed=()=>{persistProgress();queueAnalysis();render();};
let wasWon=false;

function resizeInput(){
 const input=el('phrase'),minimum=pocketQuery.matches?54:84,maximum=pocketQuery.matches?100:210;
 input.style.height='auto';const height=input.value?Math.min(maximum,Math.max(minimum,input.scrollHeight)):minimum;
 input.style.height=height+'px';input.style.overflowY=input.scrollHeight>maximum?'auto':'hidden';
}
function syncInput(){el('phrase').value=game.text;resizeInput();}

/** Include a retained latest edit so stale responses never flash an idle state. */
function currentAnalysisActivity(){
 return analysisActivity(game,{scheduled:autoTimer!==null,manual:pendingManual});
}

/** Keep the scope energized while a request is running or waiting to run. */
function syncAnalysisScope(activity=currentAnalysisActivity()){
 const scope=el('analysis-scope');
 const starting=game.loading&&game.attempts!==lastScopeAttempt;
 if(activity.active){
  clearTimeout(scopeSettlingTimer);scopeSettlingTimer=null;scope.classList.remove('settling');
  if(starting){scope.classList.remove('active');void scope.offsetWidth;lastScopeAttempt=game.attempts;}
  scope.classList.add('active');scope.classList.toggle('queued',activity.queued);
 }else if(scope.classList.contains('active')){
  scope.classList.remove('active','queued');scope.classList.add('settling');
  clearTimeout(scopeSettlingTimer);scopeSettlingTimer=setTimeout(()=>{
   scope.classList.remove('settling');scope.setAttribute('aria-label','Analyzer idle, run '+game.attempts);
  },760);
 }else scope.classList.remove('queued');
 el('analysis-scope-run').textContent='RUN '+String(game.attempts).padStart(3,'0');
 const state=activity.queued?(game.loading?'Analyzing; another analysis is queued':'Analysis queued'):
  game.loading?'Analysis in progress':scope.classList.contains('settling')?'Analysis complete, returning to idle':'Analyzer idle';
 scope.setAttribute('aria-label',state+', run '+game.attempts);
}

/** Give newly decoded sensor knowledge one strong, short piece of apparatus feedback. */
function playDiscoveryFeedback(discoveries){
 if(!discoveries.length)return;
 const scope=el('analysis-scope'),status=el('discovery-status');
 clearTimeout(scopeDiscoveryTimer);scope.classList.remove('discovery');void scope.offsetWidth;scope.classList.add('discovery');
 scopeDiscoveryTimer=setTimeout(()=>scope.classList.remove('discovery'),950);
 const extra=discoveries.length-1;
 status.textContent='SIGNAL ACQUIRED: '+discoveries[0].label.toUpperCase()+(extra?' +'+extra:'');
 status.hidden=false;status.classList.remove('visible');void status.offsetWidth;status.classList.add('visible');
 clearTimeout(discoveryStatusTimer);discoveryStatusTimer=setTimeout(()=>{
  status.classList.remove('visible');status.hidden=true;
 },2400);
}

/** Overlay a brief decoder trace without changing the label exposed to assistive technology. */
function markDecoded(node){
 node.classList.add('decode-reveal');
 const noise=document.createElement('span');noise.className='decode-noise';noise.setAttribute('aria-hidden','true');node.append(noise);
}

/** Repaint the apparatus from the current authored level and its retained discoveries. */
function render(){
 const level=game.level,rules=game.rules;
 pocketSignals.begin(level.id);
 const activity=currentAnalysisActivity();
 const discoveries=game.takeDiscoveries(),discoveryByIndex=new Map(discoveries.map(discovery=>[discovery.index,discovery]));
 const newlyWon=game.accessGranted&&!wasWon;
 document.body.classList.toggle('busy',activity.active);
 el('statusline').classList.toggle('granted',game.accessGranted);
 if(debug){
  el('debug-reveal').disabled=game.loading||game.debugReveal;
  el('debug-reveal').textContent=game.debugReveal?'Goals revealed':'Reveal goals';
  el('debug-unlock').disabled=game.loading||game.debugUnlocked;
  el('debug-unlock').textContent=game.debugUnlocked?'Levels unlocked':'Unlock levels';
 }
 el('start-over').disabled=activity.active;
 const portrait=el('guardian-portrait'),guardian=level.guardian||config.levels[0].guardian;
 portrait.src=portrait.dataset.staticRoot+guardian.file;portrait.alt=guardian.alt;
 el('guardian-level').textContent=level.id;el('level-title').textContent='LEVEL '+level.id+' / '+level.title.toUpperCase();
 el('phrase-label').textContent=level.label;
 el('instruments').style.setProperty('--instrument-count',rules.length);
 el('instruments').setAttribute('aria-label',rules.length+' criteria');
 el('instruments').setAttribute('aria-busy',String(activity.active));
 el('instruments').classList.toggle('stale',!!game.readings&&!game.current);
 el('phrase').disabled=game.inputLocked;
 const canSubmit=game.canAnalyze()||game.canRetry;
 el('analyze').disabled=game.accessGranted?false:activity.active||!config.configured||!canSubmit;
 el('analyze').classList.toggle('continue',game.accessGranted);
 el('analyze').textContent=game.accessGranted?'CONTINUE':activity.active?'ANALYZING…':game.canRetry?'RETRY ▶':'ANALYZE\nTEXT';
 el('attempt').textContent='RUN '+String(game.attempts).padStart(3,'0');
 syncAnalysisScope(activity);
 el('status').textContent=!config.configured?'Set TYPESAFE_API_KEY on the server, then reload.':
  activity.active?'Sampling the unknown…':game.error||
  (game.accessGranted?'ACCESS GRANTED. The next circuit is live.':game.readings&&!game.current?'Input changed. Analyze to take a new reading.':game.current?'Reading complete. Adjust the phrase and try again.':level.briefing);
 el('status').setAttribute('role',game.error&&!activity.active?'alert':'status');
 const passed=game.current?rules.filter((rule,i)=>readingMeets(rule,game.readings[i])).length:0;
 el('progress').textContent=passed+' / '+rules.length+' TARGETS';el('model').textContent=game.model||'AWAITING INPUT';
 el('victory').hidden=!game.accessGranted;el('victory-copy').textContent='All '+rules.length+' readings align. Level '+level.id+' complete.';
 el('restart').textContent=game.levelIndex===game.levels.length-1?'NEW GAME':'CONTINUE TO LEVEL '+game.levels[game.levelIndex+1].id;

 el('levels').replaceChildren();
 game.levels.forEach((item,index)=>{
  const button=document.createElement('button');button.type='button';button.className=(index===game.levelIndex?'current ':'')+(index<game.unlocked?'complete':'');
  button.textContent=item.id;button.title=index>game.unlocked?'Level '+item.id+' locked':'Open Level '+item.id+' — '+item.title;
  button.setAttribute('aria-label',button.title);button.disabled=game.loading||index>game.unlocked;
  button.addEventListener('click',()=>{if(game.selectLevel(index)){syncInput();el('phrase').focus();}});el('levels').append(button);
 });

 el('instruments').replaceChildren();
 rules.forEach((rule,i)=>{
  const discovery=discoveryByIndex.get(i);
  const category=rule.categories?game.categoryView(i):null;
  const value=game.readings?.[i].value,revealed=category?category.title:game.revealed[i],met=game.current&&readingMeets(rule,game.readings[i]);
  const card=document.createElement('article');card.className='housing instrument'+(met?' met':'')+(rule.display==='dial'?' dial-instrument':'')+(discovery?' signal-acquired':'');
  const heading=document.createElement('h3'),serial=document.createElement('span'),name=document.createElement('span');
  serial.className='serial';serial.textContent=String(i+1).padStart(2,'0');name.textContent=revealed?rule.label:'UNKNOWN SIGNAL';
  if(discovery?.title)markDecoded(name);heading.append(serial,name);card.append(heading);
  if(rule.display==='dial'){
   const dial=document.createElement('div');dial.className='analog-dial'+(Number.isInteger(rule.target)?' target-known':'')+(value===undefined?' awaiting':'');
   dial.style.setProperty('--needle-angle',[-58,0,58][value??1]+'deg');
   dial.setAttribute('role','meter');dial.setAttribute('aria-label',revealed?rule.label:'Hidden categorical signal');dial.setAttribute('aria-valuemin','0');dial.setAttribute('aria-valuemax','2');
   if(value===undefined)dial.setAttribute('aria-valuetext','Awaiting first reading');
   else{dial.setAttribute('aria-valuenow',String(value));dial.setAttribute('aria-valuetext',rule.categories[value]);}
   category.labels.forEach((label,j)=>{const marker=document.createElement('span'),known=label!==null;marker.className='dial-label slot-'+j+(known?(j===rule.target?' target':' danger'):' locked')+(j===value?' current':'');marker.textContent=label??'???';marker.setAttribute('aria-label',label??'Undiscovered category');if(discovery?.categories.includes(j))markDecoded(marker);dial.append(marker);});
   const needle=document.createElement('i');needle.className='dial-needle';needle.setAttribute('aria-hidden','true');
   const hub=document.createElement('i');hub.className='dial-hub';hub.setAttribute('aria-hidden','true');dial.append(needle,hub);card.append(dial);
  }else if(rule.categories){
   const segments=document.createElement('div');segments.className='segments';segments.style.setProperty('--segments',rule.categories.length);segments.setAttribute('aria-label',revealed?rule.label:'Hidden categorical signal');
   game.categoryRows(i).forEach(({label,category:j,reached,active})=>{
    const discovered=label!==null,segment=document.createElement('div');
    segment.className='segment'+(reached?' reached':'')+(active?' active':'')+(j===rule.target?' target':'')+(!discovered?' locked':'');segment.textContent=discovered?label:'???';if(discovery?.categories.includes(j))markDecoded(segment);
    segment.setAttribute('aria-label',(discovered?label:'Hidden category '+(j+1))+(j===rule.target?', target':'')+(active?', current reading':''));segments.append(segment);
   });card.append(segments);
  }else{
   const display=document.createElement('div');display.className='display';const reading=document.createElement('div');reading.className='reading';
   const number=document.createElement('strong');number.textContent=value===undefined?'—':Math.round(value*100)+'%';
   const target=document.createElement('span');target.textContent=revealed?'TARGET '+Math.round(rule.target*100)+'%':'UNIDENTIFIED';reading.append(number,target);
   const meter=document.createElement('div');meter.className='gauge';meter.setAttribute('role','meter');meter.setAttribute('aria-label',revealed?rule.label:'Hidden signal '+(i+1));meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');meter.setAttribute('aria-valuenow',String(Math.round((value??0)*100)));if(value===undefined)meter.setAttribute('aria-valuetext','Awaiting first reading');
   const fill=document.createElement('div');fill.className='fill';fill.style.setProperty('--value',((value??0)*100)+'%');const threshold=document.createElement('div');threshold.className='threshold';threshold.style.setProperty('--target',((revealed?rule.target:(rule.revealAt??.3))*100)+'%');meter.append(fill,threshold);
   const ticks=document.createElement('div');ticks.className='ticks';ticks.innerHTML='<span>0</span><span>100</span>';display.append(reading,meter,ticks);card.append(display);
  }
  if(rule.categories){
   // Keep full instruments available behind a compact, already-revealed reading.
   const key=level.id+':'+i,detail=document.createElement('details');
   detail.className='pocket-detail';
   const summary=document.createElement('summary');summary.className='pocket-summary';
   summary.textContent=value===undefined?'Awaiting signal':(category.labels[value]??'???');
   summary.setAttribute('aria-label','Expand '+(revealed?rule.label:'unknown signal')+' readings');
   const instrument=card.lastElementChild;detail.append(summary,instrument);card.append(detail);
   pocketSignals.attach(detail,key);
  }
  const note=document.createElement('p');note.className='criterion-note';
  note.textContent=met?'✓ TARGET MET':rule.categories?(value===undefined?'AWAITING SIGNAL':categoryTargetText(rule,category.labels)):!revealed?'LOCKED / REVEAL AT 30%':'TARGET / AT LEAST '+Math.round(rule.target*100)+'%';
  card.append(note);if(discovery){const scan=document.createElement('i');scan.className='discovery-scan';scan.setAttribute('aria-hidden','true');card.append(scan);}el('instruments').append(card);
 });
 pocketSignals.schedule();
 playDiscoveryFeedback(discoveries);
 wasWon=game.accessGranted;
 if(newlyWon)requestAnimationFrame(()=>el('analyze').focus());

 el('log-count').textContent=game.history.length+' '+(game.history.length===1?'RECORD':'RECORDS');el('history').replaceChildren();
 if(!game.history.length){const empty=document.createElement('li');empty.className='log-empty';empty.textContent='No commands granted access.';el('history').append(empty);}
 for(const entry of game.history.slice().reverse()){
  const row=document.createElement('li');row.className='log-row';const run=document.createElement('span');run.className='run-tag';run.textContent='LEVEL '+entry.level+' / RUN '+String(entry.run).padStart(3,'0');
  const phrase=document.createElement('p');phrase.className='log-phrase';phrase.textContent=entry.text;const boxes=document.createElement('div');boxes.className='target-boxes';
  boxes.setAttribute('aria-label',entry.met.map((met,i)=>entry.labels[i]+': '+(met?'met':'not met')).join('; '));entry.met.forEach((met,i)=>{const box=document.createElement('span');box.className=met?'met':'';box.textContent=met?'■':'□';box.title=entry.labels[i]+': '+(met?'met':'not met');box.setAttribute('aria-hidden','true');boxes.append(box);});
  row.append(run,phrase,boxes);el('history').append(row);
 }
}

/** Submit the latest pending text as soon as the request gate permits it. */
function queueAnalysis(manual=false){
 if(manual)pendingManual=true;
 clearTimeout(autoTimer);autoTimer=null;
 const retry=pendingManual&&game.canRetry;
 if(!config.configured||(!retry&&!game.canAnalyze())){
  pendingManual=false;
  return;
 }
 if(game.loading)return;
 const delay=retry?game.waitMilliseconds:automaticAnalysisDelay(game);
 if(delay===null)return;
 autoTimer=setTimeout(async()=>{
  autoTimer=null;
  const retry=pendingManual&&game.canRetry;
  if(game.loading||(!retry&&!game.canAnalyze()))return;
  pendingManual=false;
  await game.analyze({retry});
 },delay);
}

el('phrase').addEventListener('input',event=>{game.edit(event.target.value);resizeInput();});
if(debug){
 el('debug-panel').hidden=false;
 let debugLevels=null;
 async function enableDebug(){
  if(debugLevels)return debugLevels;
  const response=await fetch('/api/game/debug?debug=1'),data=await response.json();
  if(!response.ok)throw new Error();
  debugLevels=data.levels;return debugLevels;
 }
 el('debug-reveal').addEventListener('click',async()=>{
  el('debug-reveal').disabled=true;
  try{game.revealAllGoals(await enableDebug());}
  catch{game.error='The debug bus could not reveal the goals.';game.changed();}
 });
 el('debug-unlock').addEventListener('click',async()=>{
  el('debug-unlock').disabled=true;
  try{await enableDebug();game.unlockAllLevels();}
  catch{game.error='The debug bus could not unlock the levels.';game.changed();}
 });
}
function submitAnalysis(withBeep=false){if(!game.canAnalyze()&&!game.canRetry)return;if(withBeep)submissionBeep();queueAnalysis(true);}
function continueLevel(){if(game.advance()){syncInput();el('phrase').focus();return true;}return false;}
el('experiment').addEventListener('submit',event=>{event.preventDefault();if(game.awaitingAcceptance)submitAnalysis();else if(game.inputLocked)continueLevel();else submitAnalysis();});
let audioContext;
function submissionBeep(){
 try{const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext)return;audioContext ||= new AudioContext();const now=audioContext.currentTime,gain=audioContext.createGain();gain.gain.setValueAtTime(.0001,now);gain.gain.exponentialRampToValueAtTime(.055,now+.012);gain.gain.exponentialRampToValueAtTime(.0001,now+.34);gain.connect(audioContext.destination);[[116,'square',0],[233,'sawtooth',.055],[466,'square',.115]].forEach(([frequency,type,delay])=>{const oscillator=audioContext.createOscillator();oscillator.type=type;oscillator.frequency.setValueAtTime(frequency,now+delay);oscillator.frequency.exponentialRampToValueAtTime(frequency*.72,now+delay+.18);oscillator.connect(gain);oscillator.start(now+delay);oscillator.stop(now+delay+.22);});}catch{}
}
el('phrase').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(config.configured&&(game.canAnalyze()||game.canRetry))submitAnalysis(true);}});
el('start-over').addEventListener('click',async()=>{
 if(game.loading||!window.confirm('Clear all Mad Hacker progress and start over?'))return;
 el('start-over').disabled=true;
 try{
  const response=await fetch('/api/game/reset',{method:'POST'});
  if(!response.ok)throw new Error();
  game.newGame(true);game.serverResetPending=false;clearStoredProgress();lastStoredProgress='';syncInput();render();el('phrase').focus();
 }catch{game.error='The apparatus could not clear your progress. Try again.';render();}
});
el('restart').addEventListener('click',continueLevel);
installPocketLayout(pocketQuery,()=>{resizeInput();render();});
syncInput();render();el('phrase').focus({preventScroll:true});
