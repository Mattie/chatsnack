import test from 'node:test';
import assert from 'node:assert/strict';
import {Experiment,analysisActivity,automaticAnalysisDelay,categoryTargetText,meetsTarget} from './static/game-state.mjs';
const LEVELS=[{id:'04',title:'Glitched Terminal',rules:[
 {id:'sentence',label:'Write a complete sentence',target:.75,visible:true},
 {id:'nerdy',label:'Nerdy',target:.7},
 {id:'insane',label:'Somewhat insane',target:.7},
 {id:'mood',label:'Temperament',target:2,categories:['Very Calm','Neutral','Somewhat Agitated','Angry']},
 {id:'passphrase',label:'Computer passphrase',target:3,categories:['Nope','Barely','Slightly complex','Decently complex']},
]}];
const reading = (values=[.95,.75,.75,2,3]) => ({readings:values.map((value,i)=>({id:['sentence','nerdy','insane','mood','passphrase'][i],value})),model:'fake'});
function setup(){let now=0;const requests=[];const experiment=new Experiment(LEVELS,true,(level,text)=>new Promise((resolve,reject)=>requests.push({level,text,resolve,reject})),()=>{},()=>now);return {experiment,requests,advance:()=>{now+=1000}};}
test('any changed trimmed text is eligible while unchanged text is ignored',async()=>{
 const {experiment:g,requests:r}=setup();
 g.edit('abc');assert.equal(g.canAnalyze(),true);const first=g.analyze();r[0].resolve(reading());await first;
 g.edit('abx');assert.equal(g.canAnalyze(),true);
 g.edit(' abc ');assert.equal(g.canAnalyze(),false);
});
test('automatic analysis waits only for the one-second send interval',()=>{
 let now=1000;
 const g=new Experiment(LEVELS,true,()=>{},()=>{},()=>now);
 g.lastAttemptedText='abc';
 g.edit('abx');
 g.nextAllowedAt=2000;
 assert.equal(automaticAnalysisDelay(g),1000);
 g.edit('latest');
 assert.equal(automaticAnalysisDelay(g),1000);
 now=2000;
 assert.equal(automaticAnalysisDelay(g),0);
 g.lastAttemptedText='latest';
 assert.equal(automaticAnalysisDelay(g),null);
});
test('analysis activity distinguishes idle, running, and queued work',async()=>{
 const {experiment:g,requests:r}=setup();
 assert.deepEqual(analysisActivity(g),{active:false,queued:false});
 g.edit('first phrase');
 assert.deepEqual(analysisActivity(g,{scheduled:true}),{active:true,queued:true});
 const first=g.analyze();
 assert.deepEqual(analysisActivity(g),{active:true,queued:false});
 g.edit('first phrase revised');
 assert.deepEqual(analysisActivity(g),{active:true,queued:true});
 r[0].resolve(reading());await first;
 assert.deepEqual(analysisActivity(g,{scheduled:true}),{active:true,queued:true});
 assert.deepEqual(analysisActivity(g),{active:false,queued:false});
});
test('sensor discoveries fire once only when public knowledge grows',async()=>{
 const levels=[{id:'01',title:'Discovery rig',rules:[
  {id:'voltage',label:'Hidden voltage',target:.7,revealAt:.3},
  {id:'class',label:'Signal class',target:2,categories:['Cold','Warm','Hot']},
 ]}];
 let now=0;const requests=[];
 const g=new Experiment(levels,true,()=>new Promise(resolve=>requests.push({resolve})),()=>{},()=>now);
 const analyze=async(text,voltage,classification)=>{
  g.edit(text);const run=g.analyze();
  requests.at(-1).resolve({readings:[{id:'voltage',value:voltage},{id:'class',value:classification}],model:'fake'});
  await run;now+=3000;
 };

 await analyze('first',.2,0);
 assert.deepEqual(g.takeDiscoveries(),[
  {index:1,label:'Cold',categories:[0],title:false,full:false},
 ]);
 assert.deepEqual(g.takeDiscoveries(),[]);

 await analyze('second',.4,0);
 assert.deepEqual(g.takeDiscoveries(),[
  {index:0,label:'Hidden voltage',categories:[],title:true,full:false},
 ]);

 await analyze('third',.6,0);
 assert.deepEqual(g.takeDiscoveries(),[]);

 await analyze('fourth',.6,2);
 assert.deepEqual(g.takeDiscoveries(),[
  {index:1,label:'Signal class',categories:[1,2],title:true,full:true},
 ]);
});
test('categorical gauges begin with every classification hidden',()=>{
 const {experiment:g}=setup();
 assert.deepEqual(g.categoryView(3).labels,[null,null,null,null]);
});
test('categorical target guidance appears only after its target label is known',()=>{
 const rule={target:2,categories:['Very Calm','Neutral','Somewhat Agitated','Angry']};
 const visible=[null,'Neutral',null,null];
 assert.equal(categoryTargetText(rule,visible),'TARGET / UNKNOWN');
 visible[2]='Somewhat Agitated';
 assert.equal(categoryTargetText(rule,visible),'TARGET / AT LEAST SOMEWHAT AGITATED');
 rule.match='exact';
 assert.equal(categoryTargetText(rule,visible),'TARGET / SOMEWHAT AGITATED');
});
test('an exact-choice dial passes only its target and reveals landed wrong categories',async()=>{
 const DIAL=[{id:'02',title:'Punctuation Calibration',rules:[
  {id:'lowercase',label:'Write it in all lowercase',target:.9,visible:true},
  {id:'punctuation',label:'Punctuation calibration',target:1,match:'exact',display:'dial',revealTitleAt:2,
   categories:['Confusing punctuation','Uses the right amount of punctuation','Simplistic punctuation']},
 ]}];
 let now=0;const requests=[];
 const g=new Experiment(DIAL,true,()=>new Promise(resolve=>requests.push({resolve})),()=>{},()=>now);
 assert.deepEqual(g.categoryView(1).labels,[null,null,null]);
 assert.equal(g.categoryView(1).title,false);
 g.edit('wrong!!!');const wrong=g.analyze();requests[0].resolve({readings:[{id:'lowercase',value:1},{id:'punctuation',value:2}],model:'fake'});await wrong;
 assert.equal(meetsTarget(g.rules[1],2),false);assert.equal(g.won,false);
 assert.deepEqual(g.categoryView(1).labels,[null,null,'Simplistic punctuation']);
 assert.equal(g.categoryView(1).title,false);
 now+=3000;g.edit('right, at last.');const right=g.analyze();requests[1].resolve({readings:[{id:'lowercase',value:1},{id:'punctuation',value:1}],model:'fake'});await right;
 assert.equal(g.won,true);
 assert.deepEqual(g.categoryView(1).labels,[null,'Uses the right amount of punctuation','Simplistic punctuation']);
 assert.equal(g.categoryView(1).title,true);
 now+=3000;g.edit('wrong,, again');const otherWrong=g.analyze();requests[2].resolve({readings:[{id:'lowercase',value:1},{id:'punctuation',value:0}],model:'fake'});await otherWrong;
 assert.equal(g.won,false);
 assert.deepEqual(g.categoryView(1).labels,['Confusing punctuation','Uses the right amount of punctuation','Simplistic punctuation']);
});
test('silently allows only one analysis request every second',async()=>{
 let now=1000;const requests=[];const g=new Experiment(LEVELS,true,()=>new Promise(resolve=>requests.push({resolve})),()=>{},()=>now);
 g.edit('first');const first=g.analyze();assert.equal(requests.length,1);
 requests[0].resolve(reading());await first;
 g.edit('second');await g.analyze();assert.equal(requests.length,1);assert.equal(g.error,'');
 now=1999;await g.analyze();assert.equal(requests.length,1);assert.equal(g.error,'');
 now=2000;const second=g.analyze();assert.equal(requests.length,2);requests[1].resolve(reading());await second;
});
test('a stale response is ignored and only the latest queued text is sent next',async()=>{
 const {experiment:g,requests:r,advance}=setup();
 g.edit('first');const first=g.analyze();
 g.edit('second');g.edit('very latest');
 r[0].resolve(reading());await first;
 assert.equal(g.readings,null);assert.equal(g.error,'');
 advance();const latest=g.analyze();
 assert.equal(r.length,2);assert.equal(r[1].text,'very latest');
 r[1].resolve(reading());await latest;assert.equal(g.current,true);
});
test('an in-flight result remains current when typing returns to the submitted phrase',async()=>{
 const {experiment:g,requests:r}=setup();
 g.edit('original');const first=g.analyze();
 g.edit('temporary edit');g.edit(' original ');
 r[0].resolve(reading());await first;
 assert.equal(g.current,true);assert.equal(g.readings.length,5);assert.equal(g.canAnalyze(),false);
});
test('remember only attained classifications and require all targets together',async()=>{
 const {experiment:g,requests:r,advance}=setup();g.edit('A sentence.');const run=g.analyze();r[0].resolve(reading([.95,.3,.29,2,2]));await run;
 assert.deepEqual(g.revealed,[true,true,false,false,false]);assert.equal(g.won,false);assert.deepEqual(g.topCategory,[0,0,0,2,2]);
 assert.deepEqual(g.categoryView(3),{full:false,title:false,labels:[null,null,'Somewhat Agitated',null],value:2,progressive:false});
 assert.deepEqual(g.categoryRows(3).map(row=>[row.category,row.reached,row.active]),[
  [3,false,false],[2,true,true],[1,true,false],[0,true,false],
 ]);
 advance();
 g.edit('Another sentence.');const next=g.analyze();r[1].resolve(reading([.5,.1,.1,0,0]));await next;
 assert.deepEqual(g.revealed,[true,true,false,false,false]);assert.equal(g.topCategory[3],2);assert.equal(g.won,false);
 assert.deepEqual(g.categoryView(3).labels,['Very Calm',null,'Somewhat Agitated',null]);
 advance();
 g.edit('The winning sentence.');const win=g.analyze();r[2].resolve(reading());await win;assert.equal(g.won,true);
 assert.deepEqual(g.history.map(entry=>entry.met),[[true,true,true,true,true]]);
 assert.equal(g.history[0].labels[3],'Unknown signal 4');
 assert.equal(g.inputLocked,true);assert.equal(g.selectLevel(0),true);assert.equal(g.inputLocked,true);
 assert.equal(g.advance(),true);assert.equal(g.inputLocked,false);
});
test('highest classification reveals the whole scale and retains that discovery',async()=>{
 const {experiment:g,requests:r,advance}=setup();g.edit('first');const first=g.analyze();r[0].resolve(reading([1,1,1,3,3]));await first;
 assert.equal(g.categoryView(3).full,true);
 advance();g.edit('second');const next=g.analyze();r[1].resolve(reading([1,1,1,0,0]));await next;
 assert.equal(g.categoryView(3).full,true);assert.equal(g.categoryView(3).title,true);
 assert.deepEqual(g.categoryView(3).labels,['Very Calm','Neutral','Somewhat Agitated','Angry']);
});
test('editing during a request discards both current readings and stale access grants',async()=>{
 const {experiment:g,requests:r}=setup();g.edit('first');const run=g.analyze();await g.analyze();assert.equal(r.length,1);
 g.edit('second');r[0].resolve({...reading(),progressToken:'stale'});await run;assert.equal(g.readings,null);assert.equal(g.revealed[1],false);assert.equal(g.won,false);
 assert.equal(g.acceptedToken,null);
 assert.deepEqual(g.history,[]);
});
test('only a current response becomes the next accepted progress token',async()=>{
 const {experiment:g,requests:r}=setup();g.edit('current');const run=g.analyze();r[0].resolve({...reading(),progressToken:'current-token'});await run;
 assert.equal(g.acceptedToken,'current-token');
});
test('only a current winning response is acknowledged for disk logging',async()=>{
 let now=0;const requests=[],accepted=[];
 const g=new Experiment(LEVELS,true,()=>new Promise(resolve=>requests.push({resolve})),()=>{},()=>now,async token=>accepted.push(token));
 g.edit('winning phrase');const win=g.analyze();requests[0].resolve({...reading(),progressToken:'winning-token'});await win;
 assert.deepEqual(accepted,['winning-token']);

 now+=3000;g.advance();g.edit('stale winner');const stale=g.analyze();g.edit('newer text');requests[1].resolve({...reading(),progressToken:'stale-token'});await stale;
 assert.deepEqual(accepted,['winning-token']);
});
test('failed current text can be retried unchanged after the one-second gate',async()=>{
 const {experiment:g,requests:r,advance}=setup();await g.analyze();assert.equal(r.length,0);g.edit('hello');g.configured=false;await g.analyze();assert.equal(r.length,0);
 g.configured=true;const run=g.analyze();r[0].reject(new Error('Try again.'));await run;
 assert.equal(g.error,'Try again.');assert.equal(g.loading,false);assert.equal(g.canRetry,true);assert.equal(g.canAnalyze(),false);assert.equal(automaticAnalysisDelay(g),null);assert.equal(r.length,1);
 await g.analyze({retry:true});assert.equal(r.length,1);assert.equal(g.error,'Try again.');assert.equal(g.canRetry,true);
 advance();
 const retry=g.analyze({retry:true});r[1].resolve(reading());await retry;
 assert.equal(g.error,'');assert.equal(g.canRetry,false);assert.equal(g.current,true);
});
test('editing clears retry state and stale failures cannot claim the new phrase',async()=>{
 const {experiment:g,requests:r,advance}=setup();g.edit('old phrase');const stale=g.analyze();
 g.edit('new phrase');r[0].reject(new Error('Old request failed.'));await stale;
 assert.equal(g.error,'');assert.equal(g.canRetry,false);assert.equal(g.canAnalyze(),true);

 advance();
 const current=g.analyze();r[1].reject(new Error('Current request failed.'));await current;
 assert.equal(g.canRetry,true);g.edit('new phrase revised');
 assert.equal(g.error,'');assert.equal(g.canRetry,false);assert.equal(g.canAnalyze(),true);
});
test('unchanged text is not analyzed twice but a changed Enter submission is',async()=>{
 const {experiment:g,requests:r,advance}=setup();g.edit('repeat me');const first=g.analyze();r[0].resolve(reading());await first;
 advance();
 await g.analyze();assert.equal(r.length,1);
 g.edit('repeat me!');const second=g.analyze();r[1].resolve(reading());await second;
 assert.equal(g.history.length,2);assert.equal(g.history[0].text,'repeat me');assert.equal(g.history[1].text,'repeat me!');
 assert.deepEqual(g.history[1].met,[true,true,true,true,true]);
});
test('malformed readings never unlock criteria',async()=>{
 const {experiment:g,requests:r}=setup();g.edit('test');const run=g.analyze();r[0].resolve({readings:[]});await run;
 assert.equal(g.readings,null);assert.deepEqual(g.revealed,[true,false,false,false,false]);assert.match(g.error,/Incomplete/);assert.equal(g.canRetry,true);
});
