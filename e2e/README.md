# Browser smoke tests

Drive the real pages with Playwright against a running server (`./run.sh`, default http://localhost:8000).

```
npm i -D playwright && npx playwright install chromium   # once
for f in live app editor; do node e2e/$f.js; done
```

Each script prints what it checked and any console errors, and saves screenshots to `$SHOTS` (default: the system temp folder). `BASE=http://host:port` points them at another server. They change the live session (evacuate, close a gate, save a venue called `e2e-venue`), so run them on a demo server, not during a real event.
