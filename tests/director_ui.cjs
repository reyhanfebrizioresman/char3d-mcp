/* Real offline drafts through Studio; visual and accessibility checks. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/layar-browser/node_modules/playwright-core');
const base = process.env.CHAR3D_UI_URL || 'http://127.0.0.1:8789';
const out = path.resolve('output/director_screens');
(async () => {
  fs.mkdirSync(out, {recursive: true});
  let server;
  if (process.env.DIRECTOR_START_UI === '1') {
    server = spawn(path.resolve('.venv/bin/python'), ['-m','webui','--port','8789'], {
      env:{...process.env,CHAR3D_PORT:'9989',CHAR3D_WORKSPACE:path.resolve('output')},
      stdio:['ignore',fs.openSync('output/director_ui.log','a'),fs.openSync('output/director_ui.log','a')],
    });
    for (let i=0;i<150;i++) {
      try { if ((await fetch(base+'/api/tools')).ok) break; } catch {}
      if (server.exitCode !== null) throw new Error('Studio exited before startup');
      await new Promise(resolve => setTimeout(resolve,100));
    }
  }
  const browser = await chromium.launch({executablePath:'/usr/bin/chromium', headless:true, args:['--no-sandbox','--disable-dev-shm-usage']});
  const errors = [];
  try {
    for (const theme of ['dark', 'light']) for (const width of [1440, 390]) {
      const context = await browser.newContext({viewport:{width,height:1100},colorScheme:theme});
      await context.grantPermissions(['clipboard-read','clipboard-write'], {origin:base});
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(t => localStorage.setItem('char3d-theme',t), theme);
      let calls = 0;
      await page.route('**/api/run', async route => {
        if (route.request().postDataJSON()?.tool === 'direct_scene') {
          calls++;
          const response = await route.fetch();
          await new Promise(resolve => setTimeout(resolve, 1800));
          await route.fulfill({response});
        } else await route.continue();
      });
      await page.goto(base);
      await page.waitForSelector('#director-idea');
      // Each context starts with a genuinely empty panel even though the local
      // server retains completed jobs from the preceding visual case.
      await page.evaluate(async () => { (await import('/static/api.js')).state.latestDirector = null; location.hash='galeri'; });
      await page.waitForSelector('#gallery-content');
      await page.evaluate(() => location.hash='naskah');
      await page.waitForSelector('#director-idea');
      assert.equal(await page.locator('#director-result').isHidden(), true);
      await page.locator('#toasts button').evaluateAll(buttons => buttons.forEach(b => b.click()));
      await page.locator('#director').screenshot({path:`${out}/empty_${theme}_${width}.png`});
      await page.screenshot({path:`${out}/studio_${theme}_${width}.png`});
      const original = await page.locator('#script-text').inputValue();
      await page.locator('[data-idea="0"]').click();
      await page.locator('.director-options summary').click();
      await page.locator('#director-cast').selectOption('2');
      await page.locator('#director-look').selectOption('sunset');
      await page.locator('#director-duration').selectOption('15');
      await page.locator('#director-generate').click();
      await page.waitForSelector('#director-progress:not([hidden])');
      assert.equal(await page.locator('#director-generate').isDisabled(), true);
      await page.locator('#director').screenshot({path:`${out}/loading_${theme}_${width}.png`});
      await page.waitForSelector('#director-tab-brief', {timeout:20000});
      await page.waitForSelector('#director:not([aria-busy="true"])', {timeout:20000});
      assert.equal(await page.locator('#director-tab-brief').getAttribute('aria-selected'), 'true');
      assert((await page.locator('#director-content').textContent()).includes('Daftar shot'));
      await page.locator('#director-copy').click();
      assert((await page.evaluate(() => navigator.clipboard.readText())).includes('## Logline'));
      await page.locator('#toasts button').evaluateAll(buttons => buttons.forEach(b => b.click()));
      await page.locator('#director').screenshot({path:`${out}/brief_${theme}_${width}.png`});
      await page.locator('#director-tab-brief').focus();
      await page.keyboard.press('ArrowRight');
      assert.equal(await page.locator('#director-tab-script').getAttribute('aria-selected'), 'true');
      assert.equal(await page.locator('#director-tab-script').evaluate(el => el === document.activeElement), true);
      assert((await page.locator('#director-content').textContent()).includes('SUASANA: sunset'));
      await page.locator('#director-copy').click();
      assert((await page.evaluate(() => navigator.clipboard.readText())).includes('SUASANA: sunset'));
      await page.locator('#toasts button').evaluateAll(buttons => buttons.forEach(b => b.click()));
      await page.locator('#director').screenshot({path:`${out}/script_${theme}_${width}.png`});
      await page.locator('#director-use').click();
      assert.notEqual(await page.locator('#script-text').inputValue(), original);
      assert.equal(await page.locator('#script-lighting').inputValue(), 'sunset');
      assert.equal(await page.locator('#script-look').getAttribute('data-value'), '');
      assert.equal(await page.locator('#script-steps .active').getAttribute('data-step'), '1');
      await page.locator('#director-use').click();
      await page.locator('#director-undo').click();
      assert.equal(await page.locator('#script-text').inputValue(), original);
      for (const mode of ['claude_cli','claude']) {
        await page.locator('#director-generator').selectOption(mode);
        await page.locator('#director-generate').click();
        await page.waitForSelector('#modal[open]');
        const text = await page.locator('#modal').textContent();
        assert(text.includes('Anthropic'));
        assert(text.includes(mode === 'claude' ? '$0.05' : 'kuota langganan'));
        await page.locator('#confirm-no').click();
      }
      assert.equal(calls,1, 'cancelled consent must not send another request');
      await page.locator('#director-generator').selectOption('offline');
      await page.evaluate(()=>location.hash='galeri');
      await page.waitForSelector('#gallery-content');
      await page.evaluate(()=>location.hash='naskah');
      await page.waitForSelector('#director-tab-brief');
      assert(!(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth)), `${theme} ${width}: horizontal overflow`);
      await context.close();
    }
    assert.deepEqual(errors, []);
    console.log('DIRECTOR UI OK: real offline | empty/loading/brief/script | dark/light | desktop/390px | keyboard tabs | apply/undo | consent cancelled | navigation retained');
  } finally {
    await browser.close();
    if (server) {
      server.kill('SIGTERM');
      await new Promise(resolve => server.once('exit',resolve));
    }
  }
})().catch(e => {console.error(e);process.exit(1)});
