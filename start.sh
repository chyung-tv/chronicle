#!/bin/sh
set -eu

export PLAYOUT_API_PORT="${PLAYOUT_API_PORT:-8765}"
export PLAYOUT_HOST="${PLAYOUT_HOST:-127.0.0.1}"
export PLAYOUT_WORKER="${PLAYOUT_WORKER:-external}"

python -m playout &
API_PID=$!
python -m playout.worker &
WORKER_PID=$!
WEB_PID=0

term() {
  if [ "$WEB_PID" -ne 0 ]; then
    kill -TERM "$WEB_PID" 2>/dev/null || true
  fi
  kill -TERM "$WORKER_PID" 2>/dev/null || true
  kill -TERM "$API_PID" 2>/dev/null || true
  if [ "$WEB_PID" -ne 0 ]; then
    wait "$WEB_PID" 2>/dev/null || true
  fi
  wait "$WORKER_PID" 2>/dev/null || true
  wait "$API_PID" 2>/dev/null || true
}

trap term INT TERM

# Wait until FastAPI is accepting connections so /api/health can pass.
i=0
while [ "$i" -lt 60 ]; do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PLAYOUT_API_PORT}/api/health', timeout=1)" 2>/dev/null; then
    break
  fi
  i=$((i + 1))
  sleep 0.5
done

# Next looks for .next in cwd; the image keeps the built app under /web.
cd /web
node node_modules/next/dist/bin/next start -H 0.0.0.0 -p "${PORT:-3000}" &
WEB_PID=$!
wait "$WEB_PID"
status=$?
term
exit "$status"
