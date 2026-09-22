import test from 'node:test';
import assert from 'node:assert/strict';
import {Experiment} from './static/game-state.mjs';

const levels=[
 {id:'01',title:'Front Security Desk',rules:[
  {id:'polite',label:'Polite request',target:.7,visible:true},
  {id:'self_deprecation',label:'Self-deprecating',target:2,categories:['Other-deprecating','Neutral','Slightly self-deprecating','Very self-deprecating']},
  {id:'specific',label:'Mentions a specific object or operation',target:.7},
 ]},
 ...['02','03','04','05','06'].map(id=>({id,title:'Level '+id,rules:[{id:'signal',label:'Signal',target:.7,visible:true}]})),
];
const response=(level,values)=>({readings:level.rules.map((rule,i)=>({id:rule.id,value:values[i]})),model:'fake'});

function setup(){
 let now=0;const requests=[];
 const game=new Experiment(levels,true,(level,text)=>new Promise(resolve=>requests.push({level,text,resolve})),()=>{},()=>now);
 return {game,requests,advanceTime:()=>{now+=3000}};
}

test('starts on Level 01 and unlocks Level 02 only after all three targets pass',async()=>{
 const {game,requests}=setup();
 assert.equal(game.level.id,'01');assert.deepEqual(game.revealed,[true,false,false]);assert.equal(game.unlocked,0);
 game.edit('please');const run=game.analyze();requests[0].resolve(response(game.level,[.8,1,.8]));await run;
 assert.equal(game.won,false);assert.equal(game.unlocked,0);assert.deepEqual(game.history,[]);

 game.nextAllowedAt=-Infinity;game.edit('please open the hatch, because I forgot how doors work');
 const win=game.analyze();requests[1].resolve(response(game.level,[.9,2,.9]));await win;
 assert.equal(game.won,true);assert.equal(game.unlocked,1);assert.equal(game.history.length,1);assert.equal(game.history[0].level,'01');
 assert.equal(game.advance(),true);assert.equal(game.level.id,'02');assert.equal(game.history.length,1);assert.equal(game.attempts,0);
});

test('completed levels are revisitable but locked future levels are not',()=>{
 const {game}=setup();game.unlocked=2;
 assert.equal(game.selectLevel(2),true);assert.equal(game.level.id,'03');
 assert.equal(game.selectLevel(4),false);assert.equal(game.level.id,'03');
 assert.equal(game.selectLevel(0),true);assert.equal(game.level.id,'01');
});

test('completed answers survive a browser progress round trip',async()=>{
 const {game,requests}=setup();
 game.edit('please open the hatch, because I forgot how doors work');
 const win=game.analyze();requests[0].resolve(response(game.level,[.9,2,.9]));await win;
 assert.equal(game.advance(),true);assert.equal(game.level.id,'02');

 const saved=game.exportProgress(),restored=setup().game;
 assert.equal(restored.restoreProgress(saved),true);
 assert.equal(restored.level.id,'02');assert.equal(restored.unlocked,1);
 assert.equal(restored.selectLevel(0),true);assert.equal(restored.won,true);
 assert.equal(restored.text,'please open the hatch, because I forgot how doors work');
 assert.deepEqual(restored.readings.map(reading=>reading.value),[.9,2,.9]);
 assert.equal(restored.history.length,1);assert.equal(restored.canAnalyze(),false);
 assert.equal(restored.selectLevel(1),true);assert.equal(restored.level.id,'02');assert.equal(restored.won,false);
});

test('a completed snapshot survives authored wording changes until start over',async()=>{
 const {game,requests}=setup();
 game.edit('please open the hatch, because I forgot how doors work');
 const win=game.analyze();requests[0].resolve(response(game.level,[.9,2,.9]));await win;
 const saved=game.exportProgress();
 const revised=structuredClone(levels);
 revised[0].rules[0].label='Simple phrasing';revised[0].rules[0].target=.75;
 const restored=new Experiment(revised,true,()=>{},()=>{},()=>0);
 assert.equal(restored.restoreProgress(saved),true);
 assert.ok(restored.completed['01']);
 assert.equal(restored.rules[0].label,'Polite request');
 assert.equal(restored.rules[0].target,.7);
 assert.equal(restored.text,'please open the hatch, because I forgot how doors work');
 assert.equal(restored.won,true);
 assert.equal(restored.newGame(true),true);
 assert.equal(restored.rules[0].label,'Simple phrasing');
 assert.equal(restored.rules[0].target,.75);
 assert.equal(restored.text,'');assert.equal(restored.won,false);
});

test('server progress resumes an older browser at its highest unlocked level',()=>{
 const {game}=setup();
 assert.equal(game.resumeAt(4),true);
 assert.equal(game.level.id,'05');assert.equal(game.unlocked,4);assert.equal(game.won,false);
 assert.equal(game.serverResetPending,false);
 assert.equal(game.selectLevel(3),true);assert.equal(game.level.id,'04');
});

test('starting over clears every stored completion',async()=>{
 const {game,requests}=setup();game.edit('winning answer');const win=game.analyze();
 requests[0].resolve(response(game.level,[.9,2,.9]));await win;
 assert.ok(game.exportProgress().completed['01']);
 assert.equal(game.newGame(true),true);
 assert.deepEqual(game.exportProgress(),{version:1,levelId:'01',unlocked:0,history:[],completed:{}});
});

test('debug controls reveal every goal and allow direct level selection',()=>{
 const {game}=setup();
 game.revealAllGoals();
 assert.deepEqual(game.revealed,[true,true,true]);
 assert.equal(game.categoryView(1).title,true);
 assert.deepEqual(game.categoryView(1).labels,levels[0].rules[1].categories);
 assert.deepEqual(game.categoryRows(1).map(row=>row.label),[...levels[0].rules[1].categories].reverse());
 assert.deepEqual(game.categoryRows(1).map(row=>row.category),[3,2,1,0]);

 game.unlockAllLevels();
 assert.equal(game.unlocked,5);
 assert.equal(game.selectLevel(5),true);
 assert.equal(game.level.id,'06');
 assert.deepEqual(game.revealed,[true]);
});

test('final victory action starts a clean game',()=>{
 const {game}=setup();game.levelIndex=5;game.unlocked=5;game.history=[{level:'06'}];game.readings=[{value:1}];game.resultRevision=game.revision;
 game.completed={'01':{},'06':game.captureCompletedLevel()};
 game.levels[0].rules[1].label='Previously decoded';game.levels[0].rules[1].target=2;game.acceptedToken='old-token';
 assert.equal(game.won,true);assert.equal(game.advance(),true);
 assert.equal(game.level.id,'01');assert.equal(game.unlocked,0);assert.deepEqual(game.history,[]);
 assert.equal(game.levels[0].rules[1].label,'Self-deprecating');assert.equal(game.acceptedToken,null);assert.equal(game.serverResetPending,true);
});
