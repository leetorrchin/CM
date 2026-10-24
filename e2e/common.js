// Shared helpers for the browser smoke tests.
// With sign in on, set E2E_USER and E2E_PASS (default admin / $CROWD_ADMIN_PASSWORD). With CROWD_AUTH=off nothing is needed.
const BASE = process.env.BASE || 'http://localhost:8000';
const SHOTS = process.env.SHOTS || require('os').tmpdir();

async function token() {
  const h = await (await fetch(BASE + '/api/health')).json();
  if (!h.auth) return '';
  const r = await fetch(BASE + '/api/login', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username: process.env.E2E_USER || 'admin', password: process.env.E2E_PASS || process.env.CROWD_ADMIN_PASSWORD || '' }),
  });
  if (!r.ok) throw new Error('login failed: set E2E_USER and E2E_PASS');
  return (await r.json()).token;
}

async function authed(browser, opts = {}) {
  const tok = await token();
  const ctx = await browser.newContext(opts);
  if (tok) await ctx.addInitScript((t) => { try { localStorage.setItem('crowd.token', t); } catch (e) {} }, tok);
  return { ctx, tok, headers: tok ? { authorization: 'Bearer ' + tok, 'content-type': 'application/json' } : { 'content-type': 'application/json' } };
}

async function newSession(headers, body = {}) {
  const r = await fetch(BASE + '/api/sessions', {
    method: 'POST', headers,
    body: JSON.stringify({ venue: 'example-minimal-festival', scenario: 'egress-end-of-night', total: 1500, speed: 5, ...body }),
  });
  if (!r.ok) throw new Error('could not start session: ' + (await r.text()));
  return (await r.json()).id;
}

module.exports = { BASE, SHOTS, token, authed, newSession };
