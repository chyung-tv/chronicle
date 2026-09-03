#!/bin/sh
set -eu

export PLAYOUT_API_PORT="${PLAYOUT_API_PORT:-8765}"
export PLAYOUT_HOST="${PLAYOUT_HOST:-127.0.0.1}"

python -m playout &
API_PID=$!
WEB_PID=0

term() {
  if [ "$WEB_PID" -ne 0 ]; then
    kill -TERM "$WEB_PID" 2>/dev/null || true
  fi
  kill -TERM "$API_PID" 2>/dev/null || true
  if [ "$WEB_PID" -ne 0 ]; then
    wait "$WEB_PID" 2>/dev/null || true
  fi
  wait "$API_PID" 2>/dev/null || true
}

trap term INT TERM

# Next listens on Railway's PORT; FastAPI stays on PLAYOUT_API_PORT inside the container.
node /web/node_modules/next/dist/bin/next start -H 0.0.0.0 -p "${PORT:-3000}" &
WEB_PID=$!
wait "$WEB_PID"
status=$?
term
exit "$status"
