#!/usr/bin/env bash
# One-command start for crowD.
#   ./run.sh          build the web apps if needed, then start the server on http://localhost:8000
#   ./run.sh dev      server plus the Vite dev server (hot reload) on http://localhost:5173
#   PORT=9000 ./run.sh   use another port
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'. $2" >&2; exit 1; }; }
need uv "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
need node "Install Node 20 or newer from https://nodejs.org"

lan_ip() {
  (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true) | head -n1
}

echo "Installing Python packages..."
uv sync --all-packages --quiet

if [ ! -d viz/node_modules ]; then
  echo "Installing web packages..."
  (cd viz && npm install --no-audit --no-fund --silent)
fi

if [ "${1:-}" = "dev" ]; then
  trap 'kill 0' EXIT
  uv run python -m crowd_server --host 0.0.0.0 --port "$PORT" &
  (cd viz && npm run dev -- --host) &
  sleep 3
  echo
  echo "Dev mode. Open http://localhost:5173  (API on :$PORT)"
  wait
  exit 0
fi

if [ ! -f viz/dist/index.html ] || [ -n "$(find viz/src viz/*.html viz/public -newer viz/dist/index.html -type f 2>/dev/null | head -n1)" ]; then
  echo "Building web apps..."
  (cd viz && npm run build --silent)
fi

IP="$(lan_ip || true)"
echo
echo "crowD is starting."
echo "  Sign in:        http://localhost:$PORT/login.html  (admin password is printed below on first start)"
echo "  Control room:   http://localhost:$PORT/live.html"
echo "  Venue editor:   http://localhost:$PORT/editor.html"
[ -n "$IP" ] && echo "  On your phone (same Wi-Fi):  http://$IP:$PORT/app.html?s=DEMO   (GPS needs https or localhost)"
echo
exec uv run python -m crowd_server --host 0.0.0.0 --port "$PORT"
