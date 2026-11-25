#!/usr/bin/env bash
#
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$ROOT/scripts/ui-explore"
PY="$ROOT/venv/bin/python"
LIMIT=2m VIEWPORT=desktop REPRO="" MODE=test EXIT_ON=""
for a in "$@"; do
  case "$a" in
    --time-limit=*) LIMIT="${a#*=}" ;;
    --viewport=*) VIEWPORT="${a#*=}" ;;
    --reproduce=*|--shrink=*) REPRO="$(cd "$(dirname "${a#*=}")" && pwd)/$(basename "${a#*=}")"
      [ "${a%%=*}" = --shrink ] && MODE=shrink ;;
    --exit-on-violation) EXIT_ON=1 ;;
    --seed=*) echo "ui-explore: Bombadil 0.8.0 has no RNG seed; replay a run with --reproduce=<trace.bin>" >&2; exit 2 ;;
    *) echo "ui-explore: unknown option $a" >&2; exit 2 ;;
  esac
done
case "$VIEWPORT" in
  desktop) W=1280 H=800 ;;
  phone) W=390 H=844 ;;
  *) echo "ui-explore: --viewport is desktop or phone" >&2; exit 2 ;;
esac
if [ -n "$REPRO" ] && [ "$MODE" != shrink ]; then
  DEADLINE=420
else
  if [[ ! "$LIMIT" =~ ^([0-9]{1,9})([smhd])$ ]]; then
    echo "ui-explore: --time-limit requires an integer with s, m, h or d suffix" >&2
    exit 2
  fi
  case "${BASH_REMATCH[2]}" in
    s) UNIT=1 ;;
    m) UNIT=60 ;;
    h) UNIT=3600 ;;
    d) UNIT=86400 ;;
  esac
  DEADLINE=$((10#${BASH_REMATCH[1]} * UNIT + 120))
fi
test -x "$PY" || { echo "ui-explore: $PY not found (the repo's relay venv)" >&2; exit 3; }
RUN_ID="$(date -u +%Y%m%d-%H%M%S)-$VIEWPORT-$$"
OUT="$ROOT/.scratch/ui-explore/$RUN_ID"
mkdir -p "$OUT"
PIDS=()
ACTIVE="" WATCHDOG=""
track_chrome() {
  local pid started pgid current
  [ -f "$OUT/chrome.pids" ] || return 0
  while read -r pid started; do
    if read -r pgid current < <(ps -p "$pid" -o pgid= -o lstart=) &&
       [ "$pid" = "$pgid" ] && [ "$started" = "$current" ]; then
      PIDS+=("$pid")
      kill -TERM -- "-$pid" 2>/dev/null || true
    fi
  done <"$OUT/chrome.pids"
  rm "$OUT/chrome.pids"
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  local pid alive=0
  rm -f "$OUT/session"
  if [ -n "$WATCHDOG" ]; then kill -TERM -- "-$WATCHDOG" 2>/dev/null || true; fi
  if [ -n "$ACTIVE" ]; then PIDS=("$ACTIVE" ${PIDS[@]+"${PIDS[@]}"}); fi
  [ -n "${STACK_TMP:-}" ] && cp "$STACK_TMP/relay.log" "$STACK_TMP/next.log" "$OUT/" 2>/dev/null || true
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  track_chrome
  for _ in $(seq 1 100); do
    alive=0
    for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.2
  done
  if [ "$alive" != 0 ]; then
    for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill -KILL -- "-$pid" 2>/dev/null || true; done
    echo "ui-explore: a process group needed SIGKILL; see $OUT" >&2
    if [ "$code" = 0 ]; then code=1; fi
  fi
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

bounded() {
  local seconds="$1" code=0 watchdog_code=0
  shift
  set -m
  nice -n 10 "$@" &
  ACTIVE=$!
  (
    set +m
    trap 'exit "$watchdog_code"' TERM
    watchdog_code=143
    sleep "$seconds" &
    wait "$!"
    watchdog_code=124
    echo "ui-explore: command exceeded ${seconds}s: $1" >&2
    kill -TERM -- "-$ACTIVE" 2>/dev/null || exit 124
    sleep 3 &
    wait "$!"
    kill -KILL -- "-$ACTIVE" 2>/dev/null || true
    exit 124
  ) &
  WATCHDOG=$!
  set +m
  wait "$ACTIVE" || code=$?
  kill -TERM -- "-$WATCHDOG" 2>/dev/null || true
  wait "$WATCHDOG" 2>/dev/null || watchdog_code=$?
  WATCHDOG=""
  if [ "$watchdog_code" = 124 ]; then code=124; fi
  if kill -0 -- "-$ACTIVE" 2>/dev/null; then
    kill -TERM -- "-$ACTIVE" 2>/dev/null || true
    sleep 1
    if kill -KILL -- "-$ACTIVE" 2>/dev/null && [ "$code" = 0 ]; then code=1; fi
  fi
  ACTIVE=""
  return "$code"
}

if ! test -x "$HERE/node_modules/.bin/bombadil"; then
  bounded 180 npm --prefix "$HERE" ci --no-audit --no-fund >"$OUT/setup.log" 2>&1 ||
    { echo "ui-explore: npm setup failed; see $OUT/setup.log" >&2; exit 3; }
fi
BOMBADIL="$HERE/node_modules/.bin/bombadil"

if [ -n "$REPRO" ] && [ -f "$(dirname "$REPRO")/anchor" ]; then
  DEMO_SHOTS_NOW="$(cat "$(dirname "$REPRO")/anchor")"
else
  DEMO_SHOTS_NOW="$(cd "$ROOT/scripts/demo-shots" && "$PY" -c 'import dataset; print(dataset.iso(dataset.default_now()))')"
fi
export DEMO_SHOTS_NOW
echo "$DEMO_SHOTS_NOW" >"$OUT/anchor"

set -m
nice -n 10 "$ROOT/scripts/demo-shots/run.sh" serve >"$OUT/stack.log" 2>&1 &
PIDS+=($!); disown $!
set +m
echo "ui-explore: starting stack (log $OUT/stack.log)"
for _ in $(seq 1 420); do
  grep -q "demo-shots: serving." "$OUT/stack.log" && break
  kill -0 "${PIDS[0]}" 2>/dev/null || { echo "ui-explore: stack exited:" >&2; tail -n 20 "$OUT/stack.log" >&2; exit 4; }
  sleep 1
done
LINE="$(grep "demo-shots: serving." "$OUT/stack.log")" || { echo "ui-explore: stack not ready after 420s" >&2; exit 4; }
APP="$(sed -E 's/.*DEMO_SHOTS_APP=([^ ]+).*/\1/' <<<"$LINE")"
STACK_TMP="$(sed -E 's/.*DEMO_SHOTS_TMP=([^ ]+).*/\1/' <<<"$LINE")"

DEMO_SHOTS_TMP="$STACK_TMP" bounded 180 "$PY" "$HERE/seed_session.py" "$APP" >"$OUT/session"
IFS= read -r COOKIE <"$OUT/session"
rm "$OUT/session"

SHIM_PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
SHIM="http://127.0.0.1:$SHIM_PORT"
set -m
UI_EXPLORE_NEXT="$APP" UI_EXPLORE_PORT="$SHIM_PORT" UI_EXPLORE_OUT="$OUT" DEMO_SHOTS_TMP="$STACK_TMP" \
  nice -n 10 "$PY" "$HERE/shim.py" >"$OUT/shim.log" 2>&1 &
PIDS=($! "${PIDS[@]}"); disown $!
set +m
SHIM_READY=0
for _ in $(seq 1 30); do
  if curl --noproxy '*' -s -o /dev/null --max-time 2 "$SHIM/__assets/"; then
    SHIM_READY=1
    break
  fi
  sleep 1
done
[ "$SHIM_READY" = 1 ] || { echo "ui-explore: shim not ready; see $OUT/shim.log" >&2; exit 4; }
RESOLVER="--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"
CHROME_BIN="$("$PY" -c 'from playwright.sync_api import sync_playwright
with sync_playwright() as p: print(p.chromium.executable_path)')"
cat >"$OUT/chrome.sh" <<EOF
#!/bin/sh
printf '%s %s\n' "\$\$" "\$(ps -p "\$\$" -o lstart=)" >>"\$UI_EXPLORE_CHROME_PIDS"
exec "$CHROME_BIN" "$RESOLVER" --disable-breakpad --disable-crash-reporter "\$@"
EOF
chmod +x "$OUT/chrome.sh"

bounded 200 "$PY" "$HERE/warm.py" "$SHIM" "$COOKIE" "$RESOLVER" "$W" "$H" ||
  echo "ui-explore: warm-up load failed (continuing)" >&2

ARGS=(browser "$MODE" --headless --width "$W" --height "$H" --instrument-javascript files
      --allow-url "$SHIM/*" --cookie "$COOKIE" --output-path "$OUT/trace.bin")
if [ "$MODE" = shrink ]; then ARGS+=(--trace "$REPRO" --time-limit "$LIMIT")
elif [ -n "$REPRO" ]; then ARGS+=(--reproduce "$REPRO")
else ARGS+=(--time-limit "$LIMIT"); fi
[ -n "$EXIT_ON" ] && [ -z "$REPRO" ] && ARGS+=(--exit-on-violation)
echo "ui-explore: $MODE $SHIM ($VIEWPORT ${W}x$H, ${REPRO:-$LIMIT}); trace $OUT/trace.bin"
CODE=0 TRACE_CODE=0 SUMMARY_CODE=0
CHROME="$OUT/chrome.sh" UI_EXPLORE_CHROME_PIDS="$OUT/chrome.pids" \
  bounded "$DEADLINE" "$BOMBADIL" "${ARGS[@]}" "$SHIM/" "$HERE/specification.ts" >"$OUT/bombadil.log" 2>&1 || CODE=$?
track_chrome
bounded 60 "$BOMBADIL" trace "$OUT/trace.bin" >"$OUT/trace.txt" 2>&1 || TRACE_CODE=$?
bounded 120 "$PY" "$HERE/summary.py" "$BOMBADIL" "$OUT" || SUMMARY_CODE=$?
echo "ui-explore: unmatched OF reads (got {}): $(cat "$OUT/shim-unmatched.txt" 2>/dev/null | wc -l | tr -d " ")"
echo "ui-explore: inspect: $BOMBADIL browser inspect $OUT/trace.bin"
echo "ui-explore: replay:  scripts/ui-explore/run.sh --viewport=$VIEWPORT --reproduce=$OUT/trace.bin"
(( CODE == 0 )) || exit "$CODE"
(( TRACE_CODE == 0 )) || exit "$TRACE_CODE"
exit "$SUMMARY_CODE"
