/* Headless Chromium checks of the real Studio, dark/light and desktop/390px. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/layar-browser/node_modules/playwright-core');
const base = process.env.CHAR3D_UI_URL || 'http://127.0.0.1:8788';
const output = path.resolve('output/cinematic_sheets/ui');
(async () => {
  fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const errors=[];
  try {
    for (const theme of ['dark','light']) for (const width of [1440,390]) {
      const context=await browser.newContext({viewport:{width,height:1000},colorScheme:theme});
      const page=await context.newPage();
      page.on('pageerror',e=>errors.push(e.message));
      await page.addInitScript(t=>localStorage.setItem('char3d-theme',t),theme);
      await page.goto(base);
      await page.waitForSelector('#script-look');
      assert.equal(await page.locator('#script-look input').count(),11);
      const pickerBox=await page.locator('#script-look').boundingBox();
      const settingsBox=await page.locator('.settings-body .form-grid').boundingBox();
      assert(pickerBox.width>settingsBox.width*.9,`${theme} ${width}: look picker must span settings width`);
      await page.locator('#script-look label').filter({hasText:'Jam emas'}).click();
      assert.equal(await page.locator('#script-look').getAttribute('data-value'),'golden_hour');
      assert.equal(await page.locator('#script-look input:checked').inputValue(),'golden_hour');
      await page.locator('#script-look label').filter({hasText:'Ikuti naskah'}).click();
      assert.equal(await page.locator('#script-look').getAttribute('data-value'),'');
      await page.locator('#script-look').scrollIntoViewIfNeeded();
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      assert(!overflow,`${theme} ${width}: horizontal overflow`);
      await page.screenshot({path:`${output}/naskah_${theme}_${width}.png`});
      await page.locator('.script-settings').screenshot({path:`${output}/naskah_settings_${theme}_${width}.png`});
      await page.evaluate(()=>location.hash='adegan');
      await page.waitForSelector('#scene-look');
      assert.equal(await page.locator('#scene-look input').count(),10);
      await page.locator('#scene-look label').filter({hasText:'Malam'}).click();
      assert.equal(await page.locator('#scene-look').getAttribute('data-value'),'night');
      await page.locator('#scene-look').scrollIntoViewIfNeeded();
      assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)),`scene ${width}: overflow`);
      await page.screenshot({path:`${output}/adegan_${theme}_${width}.png`});
      await page.locator('[aria-label="Suasana adegan"]').screenshot({path:`${output}/adegan_picker_${theme}_${width}.png`});
      await context.close();
    }
    // Exercise the actual apply button and the no-shot automatic-camera fallback.
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    const page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);
    await page.waitForSelector('#script-text');
    await page.evaluate(async()=>{
      const {run}=await import('/static/api.js');
      await run('scene_info');
      await run('new_scene',{frame_end:4});
      await run('create_human',{name:'CineUI',style:'stylized'});
      await run('auto_rig_humanoid',{mesh:'CineUI'});
      await run('set_lighting',{preset:'studio',subject:['CineUI_rig']});
    });
    await page.evaluate(()=>location.hash='adegan');
    await page.waitForSelector('#scene-look');
    const calls=[];
    page.on('request',request=>{
      if(request.url().endsWith('/api/run')) calls.push(request.postDataJSON());
    });
    await page.locator('#scene-look label').filter({hasText:'Jam emas'}).click();
    await page.locator('#apply-look').click();
    await page.waitForFunction(()=>document.querySelector('#scene-viewport img') &&
      document.querySelector('#preview-engine')?.value==='eevee',{},{timeout:180000});
    assert(calls.some(c=>c.tool==='cinematic_look' && c.arguments.preset==='golden_hour'));
    assert(calls.some(c=>c.tool==='render_frames' && c.arguments.engine_name==='eevee' && c.arguments.camera==='auto'));
    await page.screenshot({path:`${output}/adegan_apply_preview.png`,fullPage:true});
    await page.evaluate(async()=>{
      const {run}=await import('/static/api.js');
      await run('cinematic_look',{clear:true});
      await run('engine_shutdown');
    });
    await context.close();
    assert.deepEqual(errors,[]);
    console.log('CINEMATIC UI OK: dark/light | desktop/390px | swatch selection | no overflow | screenshots | apply + Eevee preview');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
