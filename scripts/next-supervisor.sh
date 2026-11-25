#!/usr/bin/env bash
#
#

set -u
cd "$(dirname "$0")/.."

CHILD_PID=""

cleanup() {
  echo "[next-sup] received signal — shutting down child $CHILD_PID"
  if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -TERM "$CHILD_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8; do
      kill -0 "$CHILD_PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$CHILD_PID" 2>/dev/null || true
  fi
  # If only pnpm dies its node child can keep :3001 and the next start loops on EADDRINUSE.
  if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS="$(lsof -ti :3001 2>/dev/null || true)"
    [[ -n "$PORT_PIDS" ]] && echo "$PORT_PIDS" | xargs -I{} kill -9 {} 2>/dev/null || true
  fi
  exit 0
}
trap cleanup TERM INT

ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS="$(lsof -ti :3001 2>/dev/null || true)"
    if [[ -n "$PORT_PIDS" ]]; then
      echo "[next-sup] reaping leftover :3001 listener(s): $PORT_PIDS"
      echo "$PORT_PIDS" | xargs -I{} kill -9 {} 2>/dev/null || true
      sleep 1
    fi
  fi
  echo "[next-sup] launching pnpm dev (attempt $ATTEMPT) at $(date '+%Y-%m-%d %H:%M:%S')"
  START=$(date +%s)
  ( cd app && exec pnpm dev ) &
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
  echo "[next-sup] pnpm dev exited code=$CODE after ${RUNTIME}s — restart in ${SLEEP}s"
  sleep "$SLEEP"
done
