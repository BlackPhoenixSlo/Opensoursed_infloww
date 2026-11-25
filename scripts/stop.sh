#!/usr/bin/env bash
#
#

set -euo pipefail

cd "$(dirname "$0")/.."
PIDFILE="/tmp/of-relay.pid"

keep_tunnel=false
for arg in "$@"; do
  case "$arg" in
    --keep-tunnel) keep_tunnel=true ;;
    *) echo "[stop] unknown arg: $arg" >&2; exit 2 ;;
  esac
done

killed=false
if [[ -f "$PIDFILE" ]]; then
  PID=$(cat "$PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "[stop] killing relay supervisor (pid $PID)"
    kill "$PID"
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
      kill -0 "$PID" 2>/dev/null || { killed=true; break; }
      sleep 1
    done
    if kill -0 "$PID" 2>/dev/null; then
      echo "[stop] supervisor ignored SIGTERM — sending SIGKILL"
      kill -9 "$PID" || true
      killed=true
    fi
  fi
  rm -f "$PIDFILE"
fi

ROTATOR_PIDFILE="/tmp/of-rotator.pid"
if [[ -f "$ROTATOR_PIDFILE" ]]; then
  RPID=$(cat "$ROTATOR_PIDFILE")
  if kill -0 "$RPID" 2>/dev/null; then
    echo "[stop] killing log rotator (pid $RPID)"
    kill "$RPID" 2>/dev/null || true
  fi
  rm -f "$ROTATOR_PIDFILE"
fi

if pgrep -f "uvicorn.*service.server:app" >/dev/null 2>&1; then
  echo "[stop] killing stray uvicorn(s) for service.server:app"
  pkill -f "uvicorn.*service.server:app" || true
  killed=true
fi
if command -v lsof >/dev/null 2>&1; then
  PORT_PIDS="$(lsof -ti :8787 2>/dev/null || true)"
  if [[ -n "$PORT_PIDS" ]]; then
    echo "[stop] killing leftover listener(s) on :8787 ($PORT_PIDS)"
    echo "$PORT_PIDS" | xargs -I{} kill {} 2>/dev/null || true
    sleep 1
    echo "$PORT_PIDS" | xargs -I{} kill -9 {} 2>/dev/null || true
    killed=true
  fi
fi

[[ "$killed" == "true" ]] || echo "[stop] no uvicorn was running"

NEXT_PIDFILE="/tmp/of-inbox.pid"
if [[ -f "$NEXT_PIDFILE" ]]; then
  NPID=$(cat "$NEXT_PIDFILE")
  if kill -0 "$NPID" 2>/dev/null; then
    echo "[stop] killing next dev supervisor (pid $NPID)"
    kill "$NPID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$NPID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$NPID" 2>/dev/null || true
  fi
  rm -f "$NEXT_PIDFILE"
fi
if pgrep -f "next dev.*-p 3001" >/dev/null 2>&1; then
  echo "[stop] killing stray next dev"
  pkill -f "next dev.*-p 3001" 2>/dev/null || true
fi
if command -v lsof >/dev/null 2>&1; then
  PORT_PIDS="$(lsof -ti :3001 2>/dev/null || true)"
  if [[ -n "$PORT_PIDS" ]]; then
    echo "[stop] killing leftover listener(s) on :3001 ($PORT_PIDS)"
    echo "$PORT_PIDS" | xargs -I{} kill -9 {} 2>/dev/null || true
  fi
fi

if [[ "$keep_tunnel" != "true" ]]; then
  if command -v tailscale >/dev/null 2>&1; then
    echo "[stop] disabling tailscale funnel"
    tailscale funnel --https=443 off >/dev/null 2>&1 || true
  fi
fi

echo "[stop] done"
