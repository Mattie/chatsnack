/** Send the latest changed phrase when the one-second request gate opens. */
export function automaticAnalysisDelay(experiment){
 if(!experiment.canAnalyze())return null;
 return experiment.waitMilliseconds;
}

/** Describe whether the apparatus is evaluating now or retaining future work. */
export function analysisActivity(experiment,{scheduled=false,manual=false}={}){
 const queued=scheduled||manual||(experiment.loading&&experiment.canAnalyze());
 return {active:experiment.loading||queued,queued};
}

/** Apply the authored success rule; dial targets can require one exact category. */
export function meetsTarget(rule,value){
 return rule.match==='exact'?value===rule.target:value>=rule.target;
}

/** Prefer the server-owned verdict when hidden target values are not yet public. */
export function readingMeets(rule,reading){
 return typeof reading?.met==='boolean'?reading.met:meetsTarget(rule,reading?.value);
}

/** Describe a categorical target only after that category is visible to the player. */
export function categoryTargetText(rule,visibleCategories){
 const label=Number.isInteger(rule.target)?visibleCategories?.[rule.target]:null;
 if(!label)return 'TARGET / UNKNOWN';
 return 'TARGET / '+(rule.match==='exact'?'':'AT LEAST ')+label.toUpperCase();
}

const copy=value=>JSON.parse(JSON.stringify(value));

/** Page-session state for six sequential Mad Hacker experiments. */
export class Experiment {
 constructor(levels,configured,send,changed,now=()=>Date.now(),accept=async()=>{}){
  this.initialLevels=copy(levels);this.levels=copy(levels);
  this.configured=configured;this.send=send;this.changed=changed;this.now=now;this.accept=accept;
  this.loading=false;this.revision=0;this.nextAllowedAt=-Infinity;this.acceptedToken=null;this.pendingAcceptance=null;this.serverResetPending=false;this.failedText='';
  this.debugReveal=false;this.debugUnlocked=false;this.newGame();
 }
 get level(){return this.levels[this.levelIndex];}
 get rules(){return this.level.rules;}
 /** Remember category discoveries while keeping the authored scale hidden. */
 categoryView(index){
  const rule=this.rules[index],value=this.readings?.[index].value,discoveries=this.categoryDiscoveries[index];
  const full=this.debugReveal||(rule.match==='exact'?discoveries.size>=rule.categories.length:this.topCategory[index]>=rule.categories.length-1);
  const progressive=rule.revealMode==='progressive';
  const title=full||!!rule.visible||discoveries.size>=(rule.revealTitleAt??Infinity)||(progressive&&this.revealed[index]);
  const labels=rule.categories.map((label,category)=>
   full||(progressive&&category<=this.topCategory[index])||discoveries.has(category)?label:null
  );
  return {full,title,labels,value,progressive};
 }
 /** Present stronger classifications above weaker ones without changing their score indices. */
 categoryRows(index){
  const view=this.categoryView(index);
  return view.labels.map((label,category)=>({
   label,category,
   reached:Number.isInteger(view.value)&&category<=view.value,
   active:category===view.value,
  })).reverse();
 }
 /** Return newly exposed sensor knowledge once so its reveal effect cannot replay. */
 takeDiscoveries(){const discoveries=this.discoveries;this.discoveries=[];return discoveries;}
 newGame(pristine=false){
  if(this.loading)return false;
  if(pristine){
   this.levels=copy(this.debugReveal&&this.debugLevels?this.debugLevels:this.initialLevels);
   this.acceptedToken=null;this.pendingAcceptance=null;this.serverResetPending=true;
  }
  this.completed={};this.levelIndex=0;this.unlocked=this.debugUnlocked?this.levels.length-1:0;this.history=[];this.resetLevel();return true;
 }
 resetLevel(){
  if(this.loading)return false;
  this.text='';this.revision++;this.resultRevision=-1;this.readings=null;
  this.lastAttemptedText='';this.failedText='';this.pendingAcceptance=null;
  this.revealed=this.rules.map(rule=>this.debugReveal||!!rule.visible);this.topCategory=this.rules.map(rule=>rule.categories?-1:0);
  this.categoryDiscoveries=this.rules.map(rule=>rule.categories?new Set():null);
  this.discoveries=[];
  this.error='';this.attempts=0;this.model='';this.changed();return true;
 }
 selectLevel(index){
  if(this.loading||!Number.isInteger(index)||index<0||index>this.unlocked||index>=this.levels.length)return false;
  this.levelIndex=index;
  const completed=this.completed[this.level.id];
  if(completed&&this.restoreCompletedLevel(completed)){this.changed();return true;}
  return this.resetLevel();
 }
 /** Freeze the winning view so the player can inspect it again later. */
 captureCompletedLevel(){
  return copy({
   text:this.text,readings:this.readings,model:this.model,attempts:this.attempts,rules:this.rules,
   revealed:this.revealed,topCategory:this.topCategory,
   categoryDiscoveries:this.categoryDiscoveries.map(values=>values?[...values]:null),
  });
 }
 /** Restore one previously earned winning view without another provider request. */
 restoreCompletedLevel(saved){
  if(!saved||typeof saved.text!=='string'||!Array.isArray(saved.rules)||!Array.isArray(saved.readings)||
     saved.rules.length!==this.rules.length||saved.readings.length!==this.rules.length||
     saved.rules.some((rule,index)=>rule?.id!==this.rules[index].id)||
     saved.readings.some((reading,index)=>reading?.id!==this.rules[index].id||!Number.isFinite(reading.value)))return false;
  // A completed snapshot is the historical puzzle the server accepted. Keep
  // that earned view across wording changes; START OVER restores current rules.
  this.level.rules=copy(saved.rules);this.text=saved.text;this.revision++;this.resultRevision=this.revision;
  this.readings=copy(saved.readings);this.lastAttemptedText=this.text.trim();this.failedText='';
  this.revealed=Array.isArray(saved.revealed)?saved.revealed.map(Boolean):this.rules.map(()=>true);
  this.topCategory=Array.isArray(saved.topCategory)?[...saved.topCategory]:this.rules.map(rule=>rule.categories?rule.categories.length-1:0);
  this.categoryDiscoveries=this.rules.map((rule,index)=>rule.categories
   ?new Set(Array.isArray(saved.categoryDiscoveries?.[index])?saved.categoryDiscoveries[index]:[this.readings[index].value])
   :null);
  this.discoveries=[];this.error='';this.attempts=Number.isInteger(saved.attempts)?saved.attempts:1;
  this.model=typeof saved.model==='string'?saved.model:'';this.acceptedToken=null;return this.won;
 }
 /** Serialize only completed, player-earned puzzle state for browser storage. */
 exportProgress(){
  let unlocked=0;
  for(let index=0;index<this.levels.length;index++){
   if(!this.completed[this.levels[index].id])break;
   unlocked=Math.min(this.levels.length-1,index+1);
  }
  const levelId=this.levelIndex<=unlocked?this.level.id:this.levels[unlocked].id;
  const progress={version:1,levelId,unlocked,history:this.history,completed:this.completed};
  if(this.pendingAcceptance&&this.won)progress.pending={
   levelId:this.level.id,token:this.pendingAcceptance,snapshot:this.captureCompletedLevel(),
  };
  return copy(progress);
 }
 /** Restore valid player-earned progress while ignoring corrupt browser data. */
 restoreProgress(saved){
  if(!saved||saved.version!==1||!saved.completed||typeof saved.completed!=='object')return false;
  this.levels=copy(this.initialLevels);this.completed={};this.pendingAcceptance=null;
  for(const level of this.levels){
   const snapshot=saved.completed[level.id];
   if(!snapshot)break;
   const index=this.levels.indexOf(level);this.levelIndex=index;
   if(!this.restoreCompletedLevel(snapshot))break;
   this.completed[level.id]=copy(snapshot);
  }
  this.unlocked=0;
  for(let index=0;index<this.levels.length;index++){
   if(!this.completed[this.levels[index].id])break;
   this.unlocked=Math.min(this.levels.length-1,index+1);
  }
  this.history=Array.isArray(saved.history)?copy(saved.history.filter(entry=>
   entry&&typeof entry.text==='string'&&this.completed[entry.level])):[];
  const pending=saved.pending;
  const pendingIndex=pending&&typeof pending.token==='string'&&pending.token&&pending.snapshot
   ?this.levels.findIndex(level=>level.id===pending.levelId):-1;
  const requested=this.levels.findIndex(level=>level.id===saved.levelId);
  const index=pendingIndex===this.unlocked?pendingIndex:
   requested>=0&&requested<=this.unlocked?requested:this.unlocked;
  this.levelIndex=index;
  const completed=this.completed[this.level.id];
  if(completed)this.restoreCompletedLevel(completed);else if(pendingIndex===index&&this.restoreCompletedLevel(pending.snapshot)){
   this.pendingAcceptance=pending.token;this.error='Access confirmation was interrupted. Retry to continue.';this.failedText=this.text.trim();
  }else this.resetLevel();
  this.serverResetPending=false;this.acceptedToken=null;return true;
 }
 /** Resume at the server's last unlocked stage when this browser predates saved snapshots. */
 resumeAt(index){
  if(!Number.isInteger(index)||index<0||index>=this.levels.length)return false;
  this.unlocked=Math.max(this.unlocked,index);this.levelIndex=index;this.serverResetPending=false;
  return this.resetLevel();
 }
 /** Merge the separately requested debug answers, then expose every goal. */
 revealAllGoals(levels){
  if(Array.isArray(levels)){
   this.debugLevels=JSON.parse(JSON.stringify(levels));
   this.levels.forEach((level,index)=>level.rules.forEach((rule,ruleIndex)=>Object.assign(rule,levels[index].rules[ruleIndex])));
  }
  this.debugReveal=true;this.revealed.fill(true);this.changed();return true;
 }
 /** Allow direct selection of any authored level during local design work. */
 unlockAllLevels(){this.debugUnlocked=true;this.unlocked=this.levels.length-1;this.changed();return true;}
 advance(){
  if(!this.accessGranted)return false;
  if(this.levelIndex===this.levels.length-1)return this.newGame(true);
  return this.selectLevel(this.levelIndex+1);
 }
 /** Reset server progress before a final-level victory becomes a new local game. */
 async continueAfterWin(resetServer){
  if(!this.accessGranted)return false;
  const final=this.levelIndex===this.levels.length-1;
  if(final)await resetServer();
  const advanced=this.advance();
  if(advanced&&final)this.serverResetPending=false;
  return advanced;
 }
 edit(text){this.text=text;this.revision++;this.error='';this.failedText='';this.discoveries=[];this.changed();}
 get current(){return this.readings!==null&&this.resultRevision===this.revision;}
 get won(){return this.current&&this.rules.every((rule,i)=>readingMeets(rule,this.readings[i]));}
 get awaitingAcceptance(){return !!this.pendingAcceptance&&this.won;}
 get accessGranted(){return this.won&&!!this.completed[this.level.id];}
 get canRetry(){return !!this.error&&!!this.failedText&&this.failedText===this.text.trim();}
 /** Let the view freeze an accepted request until the player advances. */
 get inputLocked(){return this.won;}
 get waitMilliseconds(){return Math.max(0,this.nextAllowedAt-this.now());}
 canAnalyze(){
  const submitted=this.text.trim();
  return !!submitted&&submitted!==this.lastAttemptedText;
 }
 async analyze({retry=false}={}){
  const retrying=retry&&this.canRetry;
  if(this.loading||!this.configured||(!retrying&&!this.canAnalyze())||this.text.length>2000||this.waitMilliseconds>0)return;
  if(retrying&&this.awaitingAcceptance)return this.retryAcceptance();
  this.nextAllowedAt=this.now()+1000;
  const level=this.level,submitted=this.text.trim();
  this.lastAttemptedText=submitted;
  this.loading=true;this.resultRevision=-1;this.error='';this.failedText='';this.discoveries=[];this.attempts++;this.changed();
  try{
   const data=await this.send(level.id,submitted);
   if(!Array.isArray(data.readings)||data.readings.length!==level.rules.length)throw new Error('Incomplete reading. Try again.');
   const ordered=level.rules.map(rule=>data.readings.find(reading=>reading.id===rule.id));
   if(ordered.some((reading,i)=>{
    const rule=level.rules[i],maximum=rule.categories?rule.categories.length-1:1;
    return !reading||!Number.isFinite(reading.value)||reading.value<0||reading.value>maximum||(rule.categories&&!Number.isInteger(reading.value));
   }))throw new Error('Invalid reading. Try again.');
   if(level!==this.level||submitted!==this.text.trim())return;
   if(typeof data.progressToken==='string')this.acceptedToken=data.progressToken;
   this.serverResetPending=false;
   const priorRevealed=[...this.revealed];
   const priorCategoryViews=this.rules.map((rule,i)=>rule.categories?this.categoryView(i):null);
   ordered.forEach((reading,i)=>{
    const rule=this.rules[i],reveal=reading.reveal;
    if(!reveal||typeof reveal!=='object')return;
    if(typeof reveal.label==='string')rule.label=reveal.label;
    if(Number.isFinite(reveal.target))rule.target=reveal.target;
    if(rule.categories&&reveal.categories&&typeof reveal.categories==='object')Object.entries(reveal.categories).forEach(([category,label])=>{
     const index=Number(category);if(Number.isInteger(index)&&index>=0&&index<rule.categories.length&&typeof label==='string')rule.categories[index]=label;
    });
   });
   this.readings=ordered;this.resultRevision=this.revision;this.model=data.model;
   ordered.forEach((reading,i)=>{
    const rule=this.rules[i],categorical=!!rule.categories;
    this.revealed[i] ||= categorical?reading.value>=(rule.revealMode==='progressive'?(rule.revealAt??2):rule.categories.length-1):reading.value>=(rule.revealAt??.3);
    if(categorical){this.topCategory[i]=Math.max(this.topCategory[i],reading.value);this.categoryDiscoveries[i].add(reading.value);}
   });
   this.discoveries=this.rules.flatMap((rule,i)=>{
    if(!rule.categories)return !priorRevealed[i]&&this.revealed[i]
     ?[{index:i,label:rule.label,categories:[],title:true,full:false}]:[];
    const before=priorCategoryViews[i],after=this.categoryView(i);
    const categories=after.labels.flatMap((label,category)=>label!==null&&before.labels[category]===null?[category]:[]);
    const title=!before.title&&after.title,full=!before.full&&after.full;
    if(!categories.length&&!title&&!full)return [];
    return [{index:i,label:title?rule.label:categories.map(category=>rule.categories[category]).join(' / '),categories,title,full}];
   });
   const met=ordered.map((reading,i)=>readingMeets(this.rules[i],reading));
   if(met.every(Boolean)){
    if(typeof data.progressToken==='string'){
     this.pendingAcceptance=data.progressToken;
     this.changed();
     await this.accept(data.progressToken);
    }
    this.completeCurrentLevel(submitted,met);
   }
  }catch(error){if(level===this.level&&submitted===this.text.trim()){this.error=error.message;this.failedText=submitted;}}
  finally{this.loading=false;this.changed();}
 }
 /** Mark a winning reading durable only after its server acknowledgement succeeds. */
 completeCurrentLevel(submitted,met){
  const level=this.level;
  this.history.push({level:level.id,run:this.attempts,text:submitted,met,labels:this.rules.map((rule,i)=>rule.categories&&!this.categoryView(i).title?'Unknown signal '+(i+1):rule.label)});
  this.completed[level.id]=this.captureCompletedLevel();
  this.unlocked=Math.min(this.levels.length-1,Math.max(this.unlocked,this.levelIndex+1));
  this.pendingAcceptance=null;this.error='';this.failedText='';
 }
 /** Retry only the durable-progress handshake, without another provider evaluation. */
 async retryAcceptance(){
  const token=this.pendingAcceptance;
  if(!token||this.loading||!this.won)return false;
  this.loading=true;this.error='';this.failedText='';this.changed();
  try{
   await this.accept(token);
   if(token!==this.pendingAcceptance||!this.won)return false;
   const met=this.readings.map((reading,i)=>readingMeets(this.rules[i],reading));
   this.completeCurrentLevel(this.text.trim(),met);return true;
  }catch(error){this.error=error.message;this.failedText=this.text.trim();return false;}
  finally{this.loading=false;this.changed();}
 }
}
