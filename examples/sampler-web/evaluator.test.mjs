import test from 'node:test';
import assert from 'node:assert/strict';
import {Evaluator} from './static/evaluator.mjs';
function harness(configured=true) {
  let callback; const requests=[];
  const machine=new Evaluator([{id:'a',sample:'first'},{id:'b',sample:'second'}],configured,
    (id,text)=>new Promise((resolve,reject)=>requests.push({id,text,resolve,reject})),()=>{},
    {setTimeout(fn,ms){assert.equal(ms,800); callback=fn;return 1;},clearTimeout(){callback=null;}});
  return {machine,requests,tick(){const fn=callback;callback=null;fn?.();}};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('debounces edits and never submits without a key or text',()=>{
  const h=harness();h.machine.select('a');h.machine.edit('one');h.machine.edit('latest');
  assert.equal(h.requests.length,0);h.tick();assert.equal(h.requests[0].text,'latest');
  const no=harness(false);no.machine.select('a');no.tick();assert.equal(no.requests.length,0);
  const empty=harness();empty.machine.edit('  ');empty.tick();assert.equal(empty.requests.length,0);
});
test('one in flight; stale response discarded and latest input evaluated',async()=>{
  const h=harness();h.machine.select('a');h.tick();h.machine.edit('new');h.tick();
  assert.equal(h.requests.length,1);h.requests[0].resolve({results:['old'],model:'test'});await flush();
  assert.equal(h.requests.length,2);assert.deepEqual(h.machine.tabs.a.results,[]);
  h.requests[1].resolve({results:['new'],model:'test'});await flush();assert.deepEqual(h.machine.tabs.a.results,['new']);
});
test('tab changes keep answers with their originating tab',async()=>{
  const h=harness();h.machine.select('a');h.tick();h.machine.select('b');h.tick();
  h.requests[0].resolve({results:['a'],model:'test'});await flush();assert.equal(h.requests[1].id,'b');
  assert.deepEqual(h.machine.tabs.b.results,[]);h.requests[1].resolve({results:['b'],model:'test'});await flush();
  h.machine.select('a');h.tick();assert.equal(h.requests.length,2);
});
test('failure waits for explicit retry',async()=>{
  const h=harness();h.machine.select('a');h.tick();h.requests[0].reject(new Error('Failed'));await flush();
  h.machine.select('a');h.tick();assert.equal(h.requests.length,1);
  h.machine.retry();h.tick();assert.equal(h.requests.length,2);
});
test('finishing a request does not skip the next edit debounce',async()=>{
  const h=harness();h.machine.select('a');h.tick();h.machine.edit('new');
  h.requests[0].resolve({results:['old'],model:'test'});await flush();
  assert.equal(h.requests.length,1);
  h.tick();assert.equal(h.requests.length,2);assert.equal(h.requests[1].text,'new');
});
