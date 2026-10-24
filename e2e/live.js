const { chromium } = require('playwright');
const { BASE, SHOTS, authed, newSession } = require('./common');
(async () => {
  const b = await chromium.launch();
  const errs = [];
  const { ctx, headers } = await authed(b, { viewport: { width: 1280, height: 800 } });
  const pg = await ctx.newPage();
  pg.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  pg.on('pageerror', e => errs.push('pageerror: ' + e.message));
  const a = await newSession(headers, { name: 'e2e A' });
  const c = await newSession(headers, { name: 'e2e B', scenario: 'entry-rush' });
  await pg.goto(BASE + '/live.html?s=' + a);
  await pg.waitForSelector('#stats dt');
  await pg.waitForTimeout(2500);
  await pg.screenshot({ path: SHOTS + '/live1.png' });
  console.log('conn:', await pg.textContent('#conn'));
  console.log('code shown:', await pg.textContent('#code'), '(expected ' + a + ')');
  console.log('sessions listed:', await pg.$$eval('#sessions button', e => e.length));
  // switch to the second event
  await pg.click(`#sessions button[data-sid="${c}"]`);
  await pg.waitForTimeout(2000);
  console.log('switched, code:', await pg.textContent('#code'));
  await pg.click(`#sessions button[data-sid="${a}"]`);
  await pg.waitForTimeout(1500);
  // evacuate (two clicks)
  await pg.click('#modes button[data-mode=evacuation]');
  await pg.click('#modes button[data-mode=evacuation]');
  await pg.waitForTimeout(1500);
  console.log('mode on:', await pg.$eval('#modes button.on', e => e.dataset.mode));
  // close a gate by clicking it on the map
  const box = await (await pg.$('#cv')).boundingBox();
  const closed0 = await pg.textContent('#closed');
  let done = false;
  for (let fx = 0.05; fx < 0.98 && !done; fx += 0.04) for (let fy = 0.05; fy < 0.98 && !done; fy += 0.04) {
    await pg.mouse.move(box.x + box.width * fx, box.y + box.height * fy);
    const cur = await pg.$eval('#cv', e => e.style.cursor);
    if (cur === 'pointer') { await pg.mouse.click(box.x + box.width * fx, box.y + box.height * fy); done = true; }
  }
  await pg.waitForTimeout(1500);
  console.log('closed list:', (await pg.textContent('#closed')).trim().slice(0, 80), '| before:', closed0.trim());
  await pg.screenshot({ path: SHOTS + '/live2.png' });
  // stop an event
  pg.once('dialog', d => d.accept());
  await pg.click('#del');
  await pg.waitForTimeout(1500);
  console.log('sessions after stop:', await pg.$$eval('#sessions button', e => e.length));
  await fetch(BASE + '/api/sessions/' + c, { method: 'DELETE', headers }).catch(() => {});
  console.log('errors:', errs);
  await b.close();
})();
