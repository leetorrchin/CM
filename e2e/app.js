const { chromium, devices } = require('playwright');
const BASE = process.env.BASE || 'http://localhost:8000';
const SHOTS = process.env.SHOTS || require('os').tmpdir();
(async () => {
  const b = await chromium.launch();
  const errs = [];
  const ctx = await b.newContext({ ...devices['iPhone 13'] });
  const pg = await ctx.newPage();
  pg.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  pg.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await pg.goto(BASE + '/app.html');
  await pg.waitForSelector('#where option', { state: 'attached' });
  await pg.screenshot({ path: SHOTS + '/app_join.png' });
  console.log('people buttons:', await pg.$$eval('#people button', e => e.map(x => x.textContent)));
  await pg.selectOption('#where', 'main_field');
  await pg.click('#joinBtn');
  await pg.waitForSelector('#main:not([hidden])');
  await pg.waitForTimeout(3000);
  console.log('instr:', await pg.textContent('#iTitle'), '|', await pg.textContent('#iDetail'));
  await pg.screenshot({ path: SHOTS + '/app_main.png' });
  // organiser evacuates
  await fetch(BASE + '/api/control/mode', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ mode: 'evacuation' }) });
  await pg.waitForTimeout(3500);
  console.log('banner:', await pg.isVisible('#banner'), await pg.textContent('#banner'));
  console.log('instr after:', await pg.textContent('#iTitle'), '|', await pg.textContent('#iDetail'));
  await pg.screenshot({ path: SHOTS + '/app_evac.png' });
  // change destination
  await pg.selectOption('#dest', 'food');
  await pg.waitForTimeout(2000);
  console.log('facts:', (await pg.textContent('#facts')).slice(0, 120));
  // reload resumes
  await pg.reload();
  await pg.waitForSelector('#main:not([hidden])', { timeout: 5000 });
  console.log('resumed after reload');
  // follow a simulated person
  await pg.click('#leave');
  await pg.waitForSelector('#people button');
  await pg.click('#people button');
  await pg.waitForSelector('#main:not([hidden])');
  await pg.waitForTimeout(2500);
  console.log('sim person:', await pg.textContent('#iTitle'));
  console.log('errors:', errs);
  await b.close();
})();
