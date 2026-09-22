/** Opt-in browser Goal test. Requires Playwright and a running local game; no AI calls. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const origin=process.env.MAD_HACKER_TEST_URL||'http://127.0.0.1:5050';

test('POCKET keeps gameplay reachable and restores the desktop without duplicating requests',async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  // Use authored fixtures through the local debug endpoint; all submissions stay fake.
  const response=await page.request.get(origin+'/api/game/debug?debug=1');
  assert.equal(response.status(),200,'Run against a local or debug-enabled test server');
  const {levels}=await response.json();
  await page.route(origin+'/',async route=>{
   const upstream=await route.fetch();
   const html=(await upstream.text()).replace(/(<script id="config" type="application\/json">)(.*?)(<\/script>)/,(_,a,b,c)=>{
    const config=JSON.parse(b);config.levels=levels;config.unlocked=5;config.configured=true;return a+JSON.stringify(config)+c;
   });
   await route.fulfill({response:upstream,body:html});
  });
  let pending,requests=0;
  await page.route(origin+'/api/game',async route=>{requests++;pending=route;});
  await page.goto(origin+'/');await page.waitForSelector('.instrument');await page.evaluate(()=>document.fonts.ready);
  const geometry=()=>page.evaluate(()=>['.masthead','.entry','.guardian-cabinet','.statusline','.instruments'].map(selector=>{
   const r=document.querySelector(selector).getBoundingClientRect();return [r.x,r.y,r.width,r.height];
  }));
  const desktop=await geometry();
  for(const width of [320,390,430]){
   await page.setViewportSize({width,height:520});
   for(let level=0;level<levels.length;level++){
    await page.locator('#levels button').nth(level).click();
    const bounds=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:innerWidth,bottom:document.querySelector('#experiment').getBoundingClientRect().bottom,signals:document.querySelector('#instruments').clientHeight}));
    assert(bounds.width<=bounds.viewport,'No horizontal page overflow');
    assert(bounds.bottom<=520,'Composer stays in the visible viewport');
    assert(bounds.signals>130,'Signals retain usable space above the composer');
    assert.equal(await page.locator('#phrase').count(),1);
   }
  }
  // Tall phones start with detail; keyboard-sized reductions prioritize unmet signals.
  await page.setViewportSize({width:390,height:1000});
  await page.locator('#levels button').nth(3).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.pocket-detail')].every(d=>d.open));
  const sizing=await page.evaluate(()=>{
   const list=document.querySelector('#instruments'),details=[...list.querySelectorAll('details')];
   details[0].closest('.instrument').classList.add('met');
   const used=list.lastElementChild.getBoundingClientRect().bottom-list.firstElementChild.getBoundingClientRect().top+4;
   const extra=details[0].lastElementChild.getBoundingClientRect().height;
   return {spare:list.clientHeight-used,extra};
  });
  await page.setViewportSize({width:390,height:Math.ceil(1000-sizing.spare-sizing.extra+20)});
  await page.waitForFunction(()=>{const d=document.querySelectorAll('.pocket-detail');return !d[0].open&&d[1].open;});
  await page.locator('.pocket-summary').first().click();
  await page.setViewportSize({width:390,height:400});
  await page.waitForTimeout(100);
  assert(await page.locator('.pocket-detail').first().evaluate(d=>d.open),'Manual expansion survives keyboard pressure');
  await page.locator('#levels button').nth(2).click();
  await page.setViewportSize({width:390,height:1000});
  await page.locator('#levels button').nth(3).click();
  await page.waitForFunction(()=>[...document.querySelectorAll('.pocket-detail')].every(d=>d.open));
  await page.locator('#levels button').first().click();
  await page.setViewportSize({width:1280,height:1000});await page.locator('.pocket-play').waitFor({state:'detached'});assert.deepEqual(await geometry(),desktop);
  await page.setViewportSize({width:390,height:520});
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const detail=page.locator('.pocket-detail').first();if(!(await detail.evaluate(node=>node.open)))await detail.locator('summary').click();assert(await detail.evaluate(node=>node.open));
  await page.locator('#phrase').fill('please open the hatch for this clumsy visitor');
  await page.locator('#phrase').evaluate(input=>input.setSelectionRange(7,11));
  await page.waitForFunction(()=>document.body.classList.contains('busy'));
  await page.setViewportSize({width:1280,height:1000});await page.setViewportSize({width:390,height:520});
  await page.locator('.pocket-play').waitFor();
  assert.equal(await page.locator('#phrase').inputValue(),'please open the hatch for this clumsy visitor');
  assert.deepEqual(await page.locator('#phrase').evaluate(input=>[document.activeElement===input,input.selectionStart,input.selectionEnd]),[true,7,11]);
  await page.waitForTimeout(100);assert.equal(requests,1);
  await pending.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Test analyzer unavailable. Retry.'})});
  await page.locator('#analyze').filter({hasText:'RETRY'}).waitFor();assert.match(await page.locator('#status').innerText(),/Test analyzer/);
  await page.locator('#analyze').click();
  await page.waitForTimeout(1100);assert.equal(requests,2);
  await pending.fulfill({contentType:'application/json',body:JSON.stringify({model:'fake',readings:levels[0].rules.map(rule=>({id:rule.id,value:rule.target}))})});
  await page.locator('#analyze.continue').waitFor();assert(await page.locator('#phrase').isDisabled());
  assert.equal(await page.locator('.instrument.met').count(),levels[0].rules.length);
  await page.locator('#analyze').click();assert(!(await page.locator('#phrase').isDisabled()));
  await page.locator('.pocket-help summary').click();assert(await page.locator('#start-over').isVisible());
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});
