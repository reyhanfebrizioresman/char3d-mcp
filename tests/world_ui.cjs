/* Real offline world drafting, inline validation, consent and responsive evidence. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'/tmp/layar-browser/node_modules/playwright-core');
const base=process.env.CHAR3D_UI_URL||'http://127.0.0.1:8798';
(async()=>{
 fs.mkdirSync('output/world_sheets/ui',{recursive:true});
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const errors=[];
 try{
  for(const theme of ['dark','light'])for(const width of [1440,390]){
   const context=await browser.newContext({viewport:{width,height:1100},colorScheme:theme});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.addInitScript(t=>localStorage.setItem('char3d-theme',t),theme);
   await page.goto(base+'/#dunia');await page.waitForSelector('#world-idea');
   await page.locator('[data-world-example="2"]').click();
   await page.locator('#world-generate').click();
   await page.waitForSelector('.world-valid',{timeout:30000});
   const recipe=JSON.parse(await page.locator('#world-json').inputValue());assert.equal(recipe.name,'Sky Whale');
   assert.equal(await page.locator('#world-generator').inputValue(),'offline');
   await page.locator('#toasts button').evaluateAll(bs=>bs.forEach(b=>b.click()));
   await page.screenshot({path:`output/world_sheets/ui/world_${theme}_${width}.png`,fullPage:true});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow');
   recipe.python='dangerous';await page.locator('#world-json').fill(JSON.stringify(recipe));
   await page.locator('#world-validate').click();
   await page.waitForSelector('#world-json[aria-invalid="true"]',{timeout:10000});
   assert((await page.locator('#world-validation').textContent()).includes('unknown key'));
   delete recipe.python;await page.locator('#world-json').fill(JSON.stringify(recipe,null,2));
   await page.locator('#world-validate').click();await page.waitForSelector('#world-json:not([aria-invalid])');
   await page.locator('#world-generator').selectOption('claude_cli');await page.locator('#world-generate').click();
   await page.waitForSelector('dialog[open]');assert((await page.locator('dialog').textContent()).includes('Anthropic'));
   await page.keyboard.press('Escape');
   if(process.argv.includes('--preview') && theme==='dark' && width===1440){
    await page.evaluate(async()=>{const api=await import('/static/api.js');await api.run('scene_info');await api.run('new_scene');});
    await page.locator('#world-preview-button').click();
    await page.waitForSelector('#world-preview img',{timeout:180000});
    await page.locator('#world-preview img').evaluate(img=>img.decode());
    await page.locator('.world-workbench').screenshot({path:'output/world_sheets/ui/world_preview.png'});
    await page.locator('#world-name').fill('ui-world');
    await page.locator('#world-use').click();
    await page.waitForSelector('#script-text',{timeout:30000});
    assert((await page.locator('#script-text').inputValue()).startsWith('DUNIA: ui-world'));
    await page.locator('#plan').click();
    await page.waitForFunction(async()=>{const a=await import('/static/api.js');return a.state.plan?.plan?.world==='ui-world';},null,{timeout:30000});
   }
   const denied=await page.request.post(base+'/api/run',{data:{tool:'direct_world',arguments:{idea:'whale',generator:'claude',consent:true}}});
   assert.equal(denied.status(),403);
   await context.close();
  }
  assert.deepEqual(errors,[]);console.log('WORLD UI OK: dark/light, 390/1440, real offline generation, validation, consent');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
