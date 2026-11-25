#!/usr/bin/env bash
#
#
#
#

set -u
cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
RELAY_PORT="${PORT:-8787}"
NEXT_PORT="${NEXT_PORT:-3001}"

do_relay=true
do_next=true
do_wait=true
for arg in "$@"; do
  case "$arg" in
    --relay|--relay-only) do_next=false ;;
    --next|--next-only)   do_relay=false ;;
    --no-wait)            do_wait=false ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "[reload] unknown arg: $arg" >&2; exit 2 ;;
  esac
done

bounce() {
  local port="$1" label="$2"
  local pids
  # Kill the port listener, not the supervisor: it relaunches the child with the new code.
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "[reload] nothing on :$port ($label) — supervisor down? run ./scripts/start.sh"
    return 1
  fi
  echo "[reload] bouncing $label on :$port (pids: $pids) — supervisor will relaunch…"
  echo "$pids" | xargs kill 2>/dev/null || true
  for _ in 1 2 3 4 5 6; do
    sleep 1
    lsof -ti tcp:"$port" >/dev/null 2>&1 || return 0
  done
  echo "[reload] :$port still bound after 6s — force-killing."
  lsof -ti tcp:"$port" | xargs kill -9 2>/dev/null || true
  return 0
}

wait_up() {
  local url="$1" label="$2" tries="${3:-30}"
  for i in $(seq 1 "$tries"); do
    if curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null; then
      echo "[reload] $label is back ($url)"
      return 0
    fi
    sleep 1
  done
  echo "[reload] timed out waiting for $label ($url) — check ./scripts/tail.sh"
  return 1
}

[[ "$do_relay" == "true" ]] && bounce "$RELAY_PORT" "relay/uvicorn" || true
[[ "$do_next"  == "true" ]] && bounce "$NEXT_PORT"  "next dev"      || true

if [[ "$do_wait" == "true" ]]; then
  echo "[reload] waiting for services to come back…"
  [[ "$do_relay" == "true" ]] && wait_up "http://${HOST}:${RELAY_PORT}/health" "relay" 30 || true
  [[ "$do_next" == "true" ]] && wait_up "http://${HOST}:${NEXT_PORT}/" "next" 60 || true
fi

echo "[reload] done."
