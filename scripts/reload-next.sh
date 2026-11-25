#!/usr/bin/env bash
#

set -u

PIDS="$(lsof -ti tcp:3001 2>/dev/null || true)"

if [[ -z "$PIDS" ]]; then
  echo "[reload-next] nothing listening on :3001 — is the supervisor running? (./scripts/start.sh)"
  exit 0
fi

echo "[reload-next] stopping Next on :3001 (pids: $PIDS) — supervisor will relaunch…"
echo "$PIDS" | xargs kill 2>/dev/null || true

for _ in 1 2 3 4 5; do
  sleep 1
  lsof -ti tcp:3001 >/dev/null 2>&1 || { echo "[reload-next] stopped — supervisor is relaunching."; exit 0; }
done

echo "[reload-next] still bound after 5s — force-killing."
lsof -ti tcp:3001 | xargs kill -9 2>/dev/null || true
echo "[reload-next] done — supervisor will relaunch shortly. Tail with ./scripts/tail.sh"
