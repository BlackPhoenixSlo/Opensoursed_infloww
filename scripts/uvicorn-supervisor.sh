#!/usr/bin/env bash
#
#

set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"
VENV="venv/bin/uvicorn"

export SHARE_TOKEN="${SHARE_TOKEN-}"

CHILD_PID=""

cleanup() {
  echo "[relay-sup] received signal — shutting down child $CHILD_PID"
  if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -TERM "$CHILD_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
      kill -0 "$CHILD_PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$CHILD_PID" 2>/dev/null || true
  fi
  if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    [[ -n "$PORT_PIDS" ]] && echo "$PORT_PIDS" | xargs -I{} kill -9 {} 2>/dev/null || true
  fi
  exit 0
}
trap cleanup TERM INT

ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    if [[ -n "$PORT_PIDS" ]]; then
      echo "[relay-sup] reaping leftover :${PORT} listener(s): $PORT_PIDS"
      echo "$PORT_PIDS" | xargs -I{} kill -9 {} 2>/dev/null || true
      sleep 1
    fi
  fi
  echo "[relay-sup] launching uvicorn (attempt $ATTEMPT) at $(date '+%Y-%m-%d %H:%M:%S')"
  START=$(date +%s)
  "$VENV" service.server:app --host "$HOST" --port "$PORT" &
  CHILD_PID=$!
  wait "$CHILD_PID"
  CODE=$?
  END=$(date +%s)
  RUNTIME=$((END - START))

  if [[ "$RUNTIME" -gt 60 ]]; then
    ATTEMPT=0
    SLEEP=2
  else
    SLEEP=$(( 2 ** ATTEMPT ))
    [[ "$SLEEP" -gt 30 ]] && SLEEP=30
  fi
  echo "[relay-sup] uvicorn exited code=$CODE after ${RUNTIME}s — restart in ${SLEEP}s"
  sleep "$SLEEP"
done
