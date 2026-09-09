#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT_DIR/.env"

BACKEND_PORT="${BACKEND_PORT:-12100}"
FRONTEND_PORT="${FRONTEND_PORT:-12000}"

echo "==> Starting YTrader dev environment"
echo "    Backend   : http://localhost:${BACKEND_PORT}"
echo "    Frontend  : http://localhost:${FRONTEND_PORT}"
echo ""
echo "    ── Infra services (docker compose -f docker/docker-compose.yml up -d) ──"
echo "    RSSHub    : http://localhost:1200"
echo "    WeWe RSS  : http://localhost:4000   (we-mp-rss)"
echo "    Miniflux  : http://localhost:8380   (admin / admin123)"
echo "    NewsNow   : http://localhost:4444"
echo ""

# ── Kill existing processes on target ports ──
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    pid=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "[kill] Stopping process on port $port (pid: $pid)"
        kill $pid 2>/dev/null || true
    fi
done
sleep 1

# ── Start Backend ──
echo "[backend] Installing dependencies..."
cd "$ROOT_DIR/backend"
uv sync --quiet

echo "[backend] Starting FastAPI on :${BACKEND_PORT}"
export MINIMAX_API_KEY FEISHU_APP_ID FEISHU_APP_SECRET BACKEND_PORT
uv run python main.py &
BACKEND_PID=$!

# ── Start Frontend ──
echo "[frontend] Installing dependencies..."
cd "$ROOT_DIR/frontend"
pnpm install --frozen-lockfile 2>/dev/null || pnpm install

echo "[frontend] Starting dev server on :${FRONTEND_PORT}"
pnpm --filter web dev &
FRONTEND_PID=$!

# ── Cleanup on exit ──
cleanup() {
    echo ""
    echo "==> Shutting down..."
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    wait 2>/dev/null
    echo "==> Done"
}
trap cleanup EXIT INT TERM

echo ""
echo "==> Ready! Press Ctrl+C to stop."
wait
