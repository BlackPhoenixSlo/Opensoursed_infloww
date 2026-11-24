#!/usr/bin/env bash
# run.sh — regenerate the marketing-site product shots in web/public/img/ from a
# throwaway localhost stack fed a synthetic demo agency (scripts/demo-shots/dataset.py).
#
#   scripts/demo-shots/run.sh                  capture every screen, compose, encode
#   scripts/demo-shots/run.sh --only dashboard,creators   capture a subset
#   scripts/demo-shots/run.sh serve            start the stack and wait (prints its URLs;
#                                              point capture.py at it with DEMO_SHOTS_APP/RELAY)
#
# Same safety model as scripts/ui-shots.sh: temp-DB relay with network guards and the
# secret store redirected, `next dev` with a fetch guard and dead proxies, and a browser
# that resolves no name but localhost. Nothing leaves the machine. See README.md here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$ROOT/scripts/demo-shots"
PY="$ROOT/venv/bin/python"

if ! test -x "$PY"; then
  echo "demo-shots: $PY not found (needs the repo's relay venv with uvicorn, FastAPI, Playwright)." >&2
  exit 3
fi
# Importing service/secrets_store.py would copy service/secrets.json into service/secrets/
# before the redirect can run (see docs/ui-shots.md). Refuse in that state.
if [ -f "$ROOT/service/secrets.json" ] && [ ! -e "$ROOT/service/secrets/secrets.json" ]; then
  echo "demo-shots: service/secrets.json exists and service/secrets/secrets.json does not; see docs/ui-shots.md." >&2
  exit 3
fi
for bin in cwebp magick; do
  command -v "$bin" >/dev/null || { echo "demo-shots: $bin not on PATH (brew install webp imagemagick)" >&2; exit 3; }
done

mkdir -p "$ROOT/.scratch"
exec 9>"$ROOT/.scratch/demo-shots.lock"
if ! "$PY" -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)' 2>/dev/null; then
  echo "demo-shots: another stack is running in this checkout" >&2
  exit 3
fi

TMP=""
NEXT_ENV_ABSENT=0
PIDS=()
PROBE=""
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  local pid alive=0
  if [ -n "$PROBE" ]; then kill -TERM "$PROBE" 2>/dev/null || true; fi
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  for _ in $(seq 1 50); do
    alive=0
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.2
  done
  if [ "$alive" != 0 ]; then
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
  fi
  local f
  for f in tsconfig.json next-env.d.ts; do
    if [ -n "$TMP" ] && [ -f "$TMP/$f.orig" ] && ! cmp -s "$TMP/$f.orig" "$ROOT/app/$f"; then
      cp "$TMP/$f.orig" "$ROOT/app/$f"
      echo "demo-shots: restored app/$f (next dev had rewritten it)" >&2
    fi
  done
  if [ "$NEXT_ENV_ABSENT" = 1 ] && [ -f "$ROOT/app/next-env.d.ts" ]; then
    rm -f "$ROOT/app/next-env.d.ts"   # it was absent: leave it absent (as slop/lib/stack.py)
  fi
  if [ "$alive" != 0 ]; then
    echo "demo-shots: child groups did not exit after TERM, retaining $TMP" >&2
    if [ "$code" = 0 ]; then code=1; fi
    exit "$code"
  fi
  [ -n "$TMP" ] && rm -rf "$TMP"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

TMP="$(mktemp -d "${TMPDIR:-/tmp}/demo-shots.XXXXXX")"
echo "demo-shots: temp $TMP"
cp "$ROOT/app/tsconfig.json" "$TMP/tsconfig.json.orig"
# next-env.d.ts is gitignored (absent in a fresh worktree): cleanup then removes the one `next dev` writes.
if [ -f "$ROOT/app/next-env.d.ts" ]; then cp "$ROOT/app/next-env.d.ts" "$TMP/next-env.d.ts.orig"; else NEXT_ENV_ABSENT=1; fi

read -r RELAY_PORT APP_PORT CLOSED_PORT < <("$PY" -c '
import socket
ss = [socket.socket() for _ in range(3)]
for s in ss: s.bind(("127.0.0.1", 0))
print(*[s.getsockname()[1] for s in ss])
for s in ss: s.close()')
RELAY="http://127.0.0.1:$RELAY_PORT"
APP="http://127.0.0.1:$APP_PORT"
DEAD_PROXY="http://127.0.0.1:$CLOSED_PORT"

set -m  # own process group per job, so the trap stops children too

env -u OPENINFLOWW_LEGACY_AUTOMATIONS \
  DATABASE_URL="sqlite+aiosqlite:///$TMP/relay.db" CHATTERLY_DB_URL="sqlite:///$TMP/relay.db" \
  CHATTERLY_TEST_MODE=1 SHARE_TOKEN= \
  SESSION_SECRET=demo-shots-session-not-for-prod CHATTER_SESSION_SECRET=demo-shots-chatter-not-for-prod \
  ADMIN_PASSWORD=demo-shots-admin-not-for-prod DEEPSEEK_API_KEY=demo-shots-fake \
  DEEPINFRA_API_KEY=demo-shots-fake GOOGLE_DRIVE_API_KEY=demo-shots-fake \
  DEMO_SHOTS_ROOT="$ROOT" DEMO_SHOTS_TMP="$TMP" DEMO_SHOTS_RELAY_PORT="$RELAY_PORT" DEMO_SHOTS_CURL_GUARD=1 \
  "$PY" "$HERE/relay_guarded.py" >"$TMP/relay.log" 2>&1 &
PIDS+=($!); disown $!

# NEXT_PUBLIC_* knobs keep dev chrome out of the shots where Next allows it; the
# capture script also hides the dev indicator with CSS.
(cd "$ROOT/app" && exec env RELAY_URL="$RELAY" NEXT_DIST_DIR=.next/demo-shots NEXT_TELEMETRY_DISABLED=1 \
  HTTP_PROXY="$DEAD_PROXY" HTTPS_PROXY="$DEAD_PROXY" http_proxy="$DEAD_PROXY" https_proxy="$DEAD_PROXY" \
  NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  NODE_OPTIONS="--require $HERE/fetch-guard.cjs" DEMO_SHOTS_TMP="$TMP" \
  node node_modules/next/dist/bin/next dev --webpack -H 127.0.0.1 -p "$APP_PORT") >"$TMP/next.log" 2>&1 &
PIDS+=($!); disown $!

set +m

wait_for() {  # name url timeout-seconds pid log
  local i
  for i in $(seq 1 "$3"); do
    curl --noproxy '*' -s -o /dev/null --max-time 60 "$2" &
    PROBE=$!
    if wait "$PROBE"; then PROBE=""; return 0; fi
    PROBE=""
    if ! kill -0 "$4" 2>/dev/null; then
      echo "demo-shots: $1 exited during startup; last log lines:" >&2; tail -n 30 "$5" >&2; exit 4
    fi
    sleep 1
  done
  echo "demo-shots: $1 not ready at $2 after $3s; last log lines:" >&2; tail -n 30 "$5" >&2; exit 4
}
echo "demo-shots: relay $RELAY, app $APP, temp $TMP"
wait_for relay "$RELAY/health" 60 "${PIDS[0]}" "$TMP/relay.log"
wait_for "next dev" "$APP/" 300 "${PIDS[1]}" "$TMP/next.log"

if [ "${1:-}" = serve ]; then
  echo "demo-shots: serving. DEMO_SHOTS_APP=$APP DEMO_SHOTS_RELAY=$RELAY DEMO_SHOTS_TMP=$TMP (Ctrl-C stops)"
  while kill -0 "${PIDS[1]}" 2>/dev/null; do sleep 2; done
  exit 0
fi

DEMO_SHOTS_ROOT="$ROOT" DEMO_SHOTS_TMP="$TMP" DEMO_SHOTS_APP="$APP" DEMO_SHOTS_RELAY="$RELAY" \
  "$PY" -u "$HERE/capture.py" "$@"
