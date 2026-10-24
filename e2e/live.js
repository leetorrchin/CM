const { chromium } = require('playwright');
const BASE = process.env.BASE || 'http://localhost:8000';
const SHOTS = process.env.SHOTS || require('os').tmpdir();
(async () => {
  const b = await chromium.launch();
  const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 } });
  const pg = await ctx.newPage();
  pg.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  pg.on('pageerror', e => errs.push('pageerror: ' + e.message));
  await pg.goto(BASE + '/live.html');
  await pg.waitForSelector('#stats dt');
  await pg.waitForTimeout(2500);
  await pg.screenshot({ path: SHOTS + '/live1.png' });
  console.log('conn:', await pg.textContent('#conn'));
  console.log('stats:', (await pg.textContent('#stats')).slice(0, 160));
  // evacuate (two clicks)
  await pg.click('#modes button[data-mode=evacuation]');
  await pg.click('#modes button[data-mode=evacuation]');
  await pg.waitForTimeout(1500);
  console.log('mode on:', await pg.$eval('#modes button.on', e => e.dataset.mode));
  // close a gate by clicking the map where the south gate is
  const box = await (await pg.$('#cv')).boundingBox();
  const closed0 = await pg.textContent('#closed');
  // find the gate position using the page's own model: click each candidate point along a grid until a closure appears
  let done = false;
  for (let fx = 0.05; fx < 0.98 && !done; fx += 0.04) for (let fy = 0.05; fy < 0.98 && !done; fy += 0.04) {
    await pg.mouse.move(box.x + box.width * fx, box.y + box.height * fy);
    const cur = await pg.$eval('#cv', e => e.style.cursor);
    if (cur === 'pointer') { await pg.mouse.click(box.x + box.width * fx, box.y + box.height * fy); done = true; }
  }
  await pg.waitForTimeout(1500);
  console.log('closed list:', (await pg.textContent('#closed')).trim().slice(0, 80), '| before:', closed0.trim());
  await pg.screenshot({ path: SHOTS + '/live2.png' });
  console.log('errors:', errs);
  await b.close();
})();
