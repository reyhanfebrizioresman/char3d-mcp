/* Real Studio film states, with local headless Chromium and no mocked endpoints. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/layar-browser/node_modules/playwright-core');
const base = process.env.CHAR3D_UI_URL || 'http://127.0.0.1:8796';
const output = path.resolve('output/film_ui');
const script = fs.readFileSync(path.resolve('output/film_script.txt'), 'utf8');
(async () => {
 fs.mkdirSync(output,{recursive:true});
 const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
 const errors=[];
 try {
  for (const theme of ['dark','light']) for (const width of [1440,390]) {
   const context=await browser.newContext({viewport:{width,height:1000},colorScheme:theme});
   const page=await context.newPage();
   page.on('pageerror',e=>errors.push(e.message));
   await page.addInitScript(({theme,script})=>{localStorage.setItem('char3d-theme',theme);localStorage.setItem('char3d-script',script);},{theme,script});
   await page.goto(base);
   await page.waitForSelector('#script-text');
   assert.equal(await page.locator('#build').textContent(),'Bangun semua adegan');
   await page.locator('#plan').click();
   await page.waitForFunction(()=>document.querySelectorAll('.film-scene-card').length===3 && !document.querySelector('#plan').disabled,{},{timeout:180000});
   assert.equal(await page.locator('.film-scene-card').count(),3);
   await page.locator('#listen-0').click();
   await page.waitForSelector('#voice-preview audio',{timeout:30000});
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),`${theme} ${width} plan overflow`);
   await page.locator('#script-result').screenshot({path:`${output}/storyboard_plan_${theme}_${width}.png`});
   await page.screenshot({path:`${output}/naskah_${theme}_${width}.png`,fullPage:true});
   await page.evaluate(async()=>{
    const {run,state}=await import('/static/api.js');
    const {refreshResult}=await import('/static/script.js');
    const film=(await run('film_info',{name:'film_acceptance'})).data;
    state.film=film;
    state.latestScript={data:{kind:'film',built:true,plan:film,film},built:true};
    refreshResult(document.querySelector('#script-result'));
   });
   assert.equal(await page.locator('[id^=film-rebuild-]').count(),3);
   await page.locator('#script-result').screenshot({path:`${output}/storyboard_built_${theme}_${width}.png`});
   await page.locator('#film-open-3').click();
   await page.locator('#confirm-yes').click();
   await page.waitForSelector('#film-scene-select',{timeout:180000});
   assert.equal(await page.locator('#film-scene-select option').count(),3);
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),`${theme} ${width} scene overflow`);
   await page.screenshot({path:`${output}/adegan_${theme}_${width}.png`,fullPage:true});
   await page.evaluate(()=>location.hash='render');
   await page.waitForSelector('input[name=resolution]',{timeout:180000});
   assert(await page.locator('#start-render').isDisabled());
   assert.match(await page.locator('#film-render-scope').textContent(),/Seluruh film/);
   await page.locator('input[name=resolution][value="480p"]').check();
   assert(!(await page.locator('#start-render').isDisabled()));
   if (theme === 'dark' && width === 1440) {
    await page.locator('#video-name').fill('film_ui.mp4');
    await page.locator('#start-render').click();
    await page.waitForSelector('#render-progress .film-build-progress li',{timeout:180000});
    assert.equal(await page.locator('#render-progress .film-build-progress li').count(),3);
    await page.screenshot({path:`${output}/render_progress_${theme}_${width}.png`,fullPage:true});
    await page.waitForFunction(()=>document.querySelector('#video-state')?.textContent==='SELESAI',{},{timeout:360000});
   }
   await page.screenshot({path:`${output}/render_${theme}_${width}.png`,fullPage:true});
   await page.evaluate(()=>location.hash='galeri');
   await page.waitForSelector('[data-file="renders/film_acceptance.mp4"]',{timeout:30000});
   await page.locator('[data-file="renders/film_acceptance.mp4"]').click();
   await page.waitForFunction(()=>document.querySelector('.media-content video')?.readyState>=1,{},{timeout:30000});
   assert((await page.locator('.media-content video').evaluate(el=>el.duration))>5);
   await page.screenshot({path:`${output}/galeri_${theme}_${width}.png`});
   await context.close();
  }
  assert.deepEqual(errors,[]);
  console.log('FILM UI OK: real plan + saved storyboard | scene switcher | whole-film estimates + resolution gate | playable gallery | dark/light desktop/390px');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
