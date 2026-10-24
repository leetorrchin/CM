# server/ (crowd_server)

Realtime service: runs a live simulated crowd, exposes REST and WebSocket APIs, and serves the web apps from `viz/dist`. See [docs/api.md](../docs/api.md).

```
uv run python -m crowd_server --port 8000
```

Modules: `app.py` (routes), `session.py` (the stepped simulation), `catalog.py` (venues and scenarios, including venues saved from the editor). Tests: `uv run pytest server/tests`.

Later: ingest real positions and sensor readings in place of the simulator, authentication, several sessions.
