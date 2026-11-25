#!/usr/bin/env bash
#
#
#

set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"
PIDFILE="/tmp/of-relay.pid"
LOGFILE="/tmp/of-relay.log"
VENV="venv/bin/uvicorn"
NEXT_PORT="${NEXT_PORT:-3001}"
NEXT_PIDFILE="/tmp/of-inbox.pid"
NEXT_LOGFILE="/tmp/of-inbox.log"
export BRAND_NAME="${BRAND_NAME:-OfmSaasDev}"
export NEXT_PUBLIC_BRAND_NAME="${NEXT_PUBLIC_BRAND_NAME:-$BRAND_NAME}"

if [[ ! -x "$VENV" ]]; then
  echo "[start] $VENV not found — create the venv first:"
  echo "         python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

want_tunnel=true
for arg in "$@"; do
  case "$arg" in
    --no-tunnel) want_tunnel=false ;;
    *) echo "[start] unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null \
   && curl -fsS -o /dev/null "http://${HOST}:${PORT}/health" 2>/dev/null; then
  echo "[start] relay already running (pid $(cat "$PIDFILE"))"
else
  if [[ -f "$PIDFILE" ]]; then
    OLD=$(cat "$PIDFILE")
    kill -0 "$OLD" 2>/dev/null && kill "$OLD" || true
    rm -f "$PIDFILE"
  fi
  # macOS holds the port briefly in TIME_WAIT after a kill: wait it out.
  for _ in 1 2 3 4 5; do
    if ! lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then break; fi
    sleep 1
  done

  echo "[start] launching uvicorn supervisor on ${HOST}:${PORT} (logs: $LOGFILE)"
  if [[ "${RELOAD:-0}" == "1" ]]; then
    echo "[start] --reload enabled (RELOAD=1). Expect periodic 10–15s freezes when chat traffic is high."
    echo "[start] WARNING: --reload bypasses the supervisor; a crash here will not self-heal."
    nohup "$VENV" service.server:app --host "$HOST" --port "$PORT" --reload \
      --reload-exclude '*.db' \
      --reload-exclude '*.db-*' \
      --reload-exclude '*.pyc' \
      --reload-exclude '__pycache__/*' \
      > "$LOGFILE" 2>&1 &
  else
    PORT="$PORT" HOST="$HOST" \
      nohup ./scripts/uvicorn-supervisor.sh > "$LOGFILE" 2>&1 &
  fi
  echo $! > "$PIDFILE"
  disown 2>/dev/null || true

  for i in $(seq 1 20); do
    if curl -fsS -o /dev/null "http://${HOST}:${PORT}/health" 2>/dev/null; then
      echo "[start] relay ready (supervisor pid $(cat "$PIDFILE"))"
      break
    fi
    sleep 1
    if [[ $i -eq 20 ]]; then
      echo "[start] timed out waiting for /health — tail of $LOGFILE:"
      tail -20 "$LOGFILE"
    fi
  done
fi

if [[ -f "$NEXT_PIDFILE" ]] && kill -0 "$(cat "$NEXT_PIDFILE")" 2>/dev/null \
   && curl -fsS -o /dev/null "http://${HOST}:${NEXT_PORT}/" 2>/dev/null; then
  echo "[start] next dev already running (pid $(cat "$NEXT_PIDFILE"))"
elif [[ -d app && -f app/package.json ]] && command -v pnpm >/dev/null 2>&1; then
  if [[ -f "$NEXT_PIDFILE" ]]; then
    OLD=$(cat "$NEXT_PIDFILE")
    kill -0 "$OLD" 2>/dev/null && kill "$OLD" || true
    rm -f "$NEXT_PIDFILE"
  fi
  echo "[start] launching next dev supervisor on ${HOST}:${NEXT_PORT} (logs: $NEXT_LOGFILE)"
  nohup ./scripts/next-supervisor.sh > "$NEXT_LOGFILE" 2>&1 &
  echo $! > "$NEXT_PIDFILE"
  disown 2>/dev/null || true
  for i in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://${HOST}:${NEXT_PORT}/" 2>/dev/null; then
      echo "[start] next ready (supervisor pid $(cat "$NEXT_PIDFILE"))"
      WARM_TOKEN="${SHARE_TOKEN:-}"
      (
        for _ in 1 2 3 4 5; do
          curl -fsS -o /dev/null --max-time 90 \
            "http://${HOST}:${NEXT_PORT}/inbox?t=${WARM_TOKEN}" 2>/dev/null && break
          sleep 1
        done
      ) >/dev/null 2>&1 &
      disown 2>/dev/null || true
      break
    fi
    sleep 1
    [[ $i -eq 30 ]] && echo "[start] timed out waiting for next dev — tail of $NEXT_LOGFILE:" && tail -10 "$NEXT_LOGFILE"
  done
else
  echo "[start] skipping next dev (app/ or pnpm missing) — funnel will expose the relay API only"
fi

ROTATOR_PIDFILE="/tmp/of-rotator.pid"
if [[ -f "$ROTATOR_PIDFILE" ]] && kill -0 "$(cat "$ROTATOR_PIDFILE")" 2>/dev/null; then
  echo "[start] log rotator already running (pid $(cat "$ROTATOR_PIDFILE"))"
else
  rm -f "$ROTATOR_PIDFILE"
  nohup bash -c 'while true; do ./scripts/rotate-logs.sh >/dev/null 2>&1; ./scripts/prune-storyboards.sh >>/tmp/of-storyboard-prune.log 2>&1; sleep 3600; done' \
    > /dev/null 2>&1 &
  echo $! > "$ROTATOR_PIDFILE"
  disown 2>/dev/null || true
  echo "[start] log rotator + storyboard prune launched (pid $(cat "$ROTATOR_PIDFILE"), hourly)"
fi

FUNNEL_TARGET="$PORT"
if [[ -f "$NEXT_PIDFILE" ]] && kill -0 "$(cat "$NEXT_PIDFILE")" 2>/dev/null; then
  FUNNEL_TARGET="$NEXT_PORT"
fi

if [[ "$want_tunnel" == "true" ]]; then
  if ! command -v tailscale >/dev/null 2>&1; then
    echo "[start] tailscale CLI not found — skipping funnel."
    echo "         Local /inbox: http://${HOST}:${NEXT_PORT}/inbox/"
    exit 0
  fi
  echo "[start] enabling tailscale funnel → 127.0.0.1:${FUNNEL_TARGET}"
  tailscale funnel --bg "$FUNNEL_TARGET" || {
    echo "[start] funnel failed (not signed in / not enabled in admin?). "
    echo "         Local /inbox: http://${HOST}:${NEXT_PORT}/inbox/"
    exit 0
  }
fi

if [[ -n "${SHARE_TOKEN:-}" ]]; then QS="?t=${SHARE_TOKEN}"; else QS=""; fi

echo
echo "  Local /inbox: http://${HOST}:${NEXT_PORT}/inbox${QS}"
if [[ "$want_tunnel" == "true" ]] && command -v tailscale >/dev/null 2>&1; then
  TS_HOST="$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("Self",{}).get("DNSName","").rstrip("."))' 2>/dev/null || true)"
  if [[ -n "$TS_HOST" ]]; then
    echo "  Tailscale:    https://${TS_HOST}/inbox${QS}"
  fi
fi
echo "  Stop:      ./scripts/stop.sh"
