const { chromium, devices } = require('playwright');
const { BASE, SHOTS, authed, newSession } = require('./common');
// local (x, y) metres -> lat/lon for the example venue anchor (north-up, no rotation)
const ANCHOR = { lat: -33.8975, lon: 151.2300 };
const toLL = (x, y) => ({ latitude: ANCHOR.lat + y / 111320, longitude: ANCHOR.lon + x / (111320 * Math.cos(ANCHOR.lat * Math.PI / 180)), accuracy: 6 });
(async () => {
  const b = await chromium.launch();
  const errs = [];
  const op = await authed(b);
  const code = await newSession(op.headers, { name: 'e2e phone', demo_people: true });
  const ctx = await b.newContext({ ...devices['iPhone 13'], geolocation: toLL(130, 60), permissions: ['geolocation'] });
  const pg = await ctx.newPage();
  pg.on('console', m => { if (m.type() === 'error' && !/404/.test(m.text())) errs.push('console: ' + m.text()); });
  pg.on('pageerror', e => errs.push('pageerror: ' + e.message));
  // wrong code first
  await pg.goto(BASE + '/app.html');
  await pg.fill('#codeIn', 'NOPE1');
  await pg.click('#find');
  await pg.waitForSelector('#joinErr:not([hidden])');
  console.log('bad code message:', await pg.textContent('#joinErr'));
  await pg.fill('#codeIn', code.toLowerCase());
  await pg.click('#find');
  await pg.waitForSelector('#where option', { state: 'attached' });
  await pg.screenshot({ path: SHOTS + '/app_join.png' });
  console.log('people buttons:', await pg.$$eval('#people button', e => e.length));
  await pg.selectOption('#where', 'main_field');
  await pg.click('#joinBtn');
  await pg.waitForSelector('#main:not([hidden])');
  await pg.waitForTimeout(3000);
  console.log('instr:', await pg.textContent('#iTitle'), '|', await pg.textContent('#iDetail'));
  await pg.screenshot({ path: SHOTS + '/app_main.png' });
  // organiser evacuates
  await fetch(BASE + `/api/sessions/${code}/mode`, { method: 'POST', headers: op.headers, body: JSON.stringify({ mode: 'evacuation' }) });
  await pg.waitForTimeout(3500);
  console.log('banner:', await pg.isVisible('#banner'), await pg.textContent('#banner'));
  await pg.screenshot({ path: SHOTS + '/app_evac.png' });
  // real location: phone says it is at the stage (x=130..)
  await pg.check('#useLoc');
  await pg.waitForTimeout(4000);
  console.log('location status:', await pg.textContent('#locStatus'));
  console.log('facts after GPS:', (await pg.textContent('#facts')).slice(0, 100));
  await ctx.setGeolocation(toLL(10, 20));
  await pg.waitForTimeout(6500);
  console.log('location after moving:', await pg.textContent('#locStatus'));
  await pg.uncheck('#useLoc');
  // tap on map
  await pg.click('#tapBtn');
  const box = await (await pg.$('#cv')).boundingBox();
  await pg.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await pg.waitForTimeout(1200);
  console.log('after tap:', await pg.textContent('#locStatus'));
  // change destination, reload resumes
  await pg.selectOption('#dest', 'food');
  await pg.reload();
  await pg.waitForSelector('#main:not([hidden])', { timeout: 6000 });
  console.log('resumed after reload');
  // leave and follow a simulated person
  await pg.click('#leave');
  await pg.waitForSelector('#find');
  await pg.fill('#codeIn', code);
  await pg.click('#find');
  await pg.waitForSelector('#people button');
  await pg.click('#people button');
  await pg.waitForSelector('#main:not([hidden])');
  await pg.waitForTimeout(2500);
  console.log('sim person:', await pg.textContent('#iTitle'));
  await fetch(BASE + '/api/sessions/' + code, { method: 'DELETE', headers: op.headers }).catch(() => {});
  console.log('errors:', errs);
  await b.close();
})();
