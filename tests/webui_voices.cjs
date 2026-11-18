/* Dedicated voice UI QA. Run with PLAYWRIGHT_MODULE and CHAR3D_UI_URL. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const out = require('node:path').resolve('output/voice_screens');
const base = process.env.CHAR3D_UI_URL || 'http://127.0.0.1:8785';
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const {spawn} = require('node:child_process');
 const profile = fs.mkdtempSync('/tmp/char3d-voice-browser-');
 const chrome = spawn('/usr/bin/chromium', ['--headless','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-first-run', '--remote-debugging-port=0', `--user-data-dir=${profile}`], {env:{...process.env,XDG_CONFIG_HOME:profile+'/config',XDG_CACHE_HOME:profile+'/cache'},stdio:'ignore'});
 let browser;
 try {
 for(let attempt=0;attempt<200;attempt++) {
  if(fs.existsSync(profile+'/DevToolsActivePort')) break;
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 const debugPort=fs.readFileSync(profile+'/DevToolsActivePort','utf8').split('\n')[0];
 browser=await chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`);
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);
 await page.waitForSelector('#tts-engine');
 await page.waitForFunction(()=>document.querySelector('#voice-status').textContent.includes('Siap digunakan'));
 await page.locator('#script-text').fill('JUDUL: Suara di Studio\nANA (perempuan, 28, rambut bob): Halo, Budi! Apa kabar?\nBUDI (laki-laki, 45, rambut pendek): Baik, Ana. Terima kasih!');
 await page.locator('#plan').click();
 await page.waitForSelector('[data-character="ANA"]',{timeout:180000});
 assert.equal(await page.locator('.voice-card').count(),2);
 await page.locator('#listen-0').click();
 await page.waitForSelector('#voice-preview audio',{timeout:60000});
 await page.waitForFunction(()=>document.querySelector('#voice-preview audio').readyState>=2);
 assert.ok(await page.locator('#voice-preview audio').evaluate(a=>a.duration>0));
 await page.evaluate(()=>document.querySelectorAll('.toast').forEach(el=>el.remove()));
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:width===390?844:1050});
  for(const theme of ['dark','light']){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
   await page.locator('#script-voices').scrollIntoViewIfNeeded();
   await page.waitForTimeout(150);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${width}`);
   await page.locator('#script-voices').screenshot({path:`${out}/suara_${theme}_${width===390?'mobile':'desktop'}.png`});
  }
 }
 // Online sample requires a consent modal; cancel sends no text synthesis request.
 let onlineRequests=0;
 page.on('request',r=>{if(r.url().endsWith('/api/run')&&r.postData()?.includes('text_to_speech')) onlineRequests++;});
 await page.locator('#tts-engine').selectOption('edge');
 await page.waitForFunction(()=>document.querySelector('#cast-voice-0')?.options[0]?.text.includes('edge'), null, {timeout:60000});
 await page.locator('#listen-0').click();
 await page.waitForSelector('#confirm-no');
 assert.equal(onlineRequests,0);
 await page.locator('#confirm-no').click();
 await page.locator('#tts-engine').selectOption('f5');
 await page.waitForFunction(()=>document.querySelector('#voice-status').textContent.includes('scripts/install_tts.sh f5 --yes'));
 await page.locator('#script-voices').screenshot({path:`${out}/suara_f5_install_mobile.png`});
 await page.locator('#tts-engine').selectOption('none');
 await page.waitForFunction(()=>document.querySelector('#listen-0')?.disabled===true);
 await page.evaluate(()=>location.hash='galeri');
 await page.locator('[data-filter=audio]').click();
 await page.locator('.asset-thumb').first().click();
 await page.waitForSelector('#modal audio');
 await page.waitForFunction(()=>document.querySelector('#modal audio').readyState>=2);
 assert.ok(await page.locator('#modal audio').evaluate(a=>a.duration>0));
 assert.deepEqual(errors,[]);
 console.log('VOICE BROWSER OK: dark/light desktop/mobile | WAV preview + gallery playback | online consent cancel | F5 install hint | mute');
 } finally { await browser?.close(); chrome.kill(); fs.rmSync(profile,{recursive:true,force:true}); }
})().catch(e=>{console.error(e);process.exit(1)});
