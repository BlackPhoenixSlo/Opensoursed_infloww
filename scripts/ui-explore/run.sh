#!/usr/bin/env bash
# run.sh — Bombadil UI exploration against a throwaway seeded stack (see README.md).
#
#   scripts/ui-explore/run.sh [--time-limit=2m] [--viewport=desktop|phone] [--exit-on-violation]
#   scripts/ui-explore/run.sh --reproduce=.scratch/ui-explore/<run-id>/trace.bin   (same viewport)
#   scripts/ui-explore/run.sh --shrink=.scratch/ui-explore/<run-id>/trace.bin [--time-limit=10m]
#
# Stack: scripts/demo-shots/run.sh serve (temp-DB relay + next dev, loopback guards), seeded with
# the demo agency (seed_session.py), behind shim.py (OnlyFans fixtures). Output: .scratch/ui-explore/<run-id>/.
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
test -x "$PY" || { echo "ui-explore: $PY not found (the repo's relay venv)" >&2; exit 3; }
if ! test -x "$HERE/node_modules/.bin/bombadil"; then
  (cd "$HERE" && nice -n 10 npm ci --no-audit --no-fund >/dev/null)
fi
BOMBADIL="$HERE/node_modules/.bin/bombadil"

RUN_ID="$(date -u +%Y%m%d-%H%M%S)-$VIEWPORT-$$"
OUT="$ROOT/.scratch/ui-explore/$RUN_ID"
mkdir -p "$OUT"
# Same dataset anchor for seed and shim; a reproduction reuses the original run's.
if [ -n "$REPRO" ] && [ -f "$(dirname "$REPRO")/anchor" ]; then
  DEMO_SHOTS_NOW="$(cat "$(dirname "$REPRO")/anchor")"
else
  DEMO_SHOTS_NOW="$(cd "$ROOT/scripts/demo-shots" && "$PY" -c 'import dataset; print(dataset.iso(dataset.default_now()))')"
fi
export DEMO_SHOTS_NOW
echo "$DEMO_SHOTS_NOW" >"$OUT/anchor"

PIDS=()
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  local pid
  # Keep the relay/next logs for triage; demo-shots removes its temp dir on exit.
  # (gone if next/relay died: demo-shots then already cleaned up; must not abort the kills below)
  [ -n "${STACK_TMP:-}" ] && cp "$STACK_TMP/relay.log" "$STACK_TMP/next.log" "$OUT/" 2>/dev/null || true
  # Only the process groups started here; demo-shots' own trap then stops next/relay and removes its temp dir.
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  for _ in $(seq 1 100); do
    local alive=0
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -0 -- "-$pid" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break
    sleep 0.2
  done
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

set -m  # own process group per job
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

COOKIE="$(DEMO_SHOTS_TMP="$STACK_TMP" nice -n 10 "$PY" "$HERE/seed_session.py" "$APP")"

SHIM_PORT="$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
SHIM="http://127.0.0.1:$SHIM_PORT"
set -m
UI_EXPLORE_NEXT="$APP" UI_EXPLORE_PORT="$SHIM_PORT" UI_EXPLORE_OUT="$OUT" DEMO_SHOTS_TMP="$STACK_TMP" \
  nice -n 10 "$PY" "$HERE/shim.py" >"$OUT/shim.log" 2>&1 &
PIDS=($! "${PIDS[@]}"); disown $!  # stopped before the stack it forwards to
set +m
for _ in $(seq 1 30); do curl --noproxy '*' -s -o /dev/null "$SHIM/__assets/" && break; sleep 1; done
# Chrome resolves no name but loopback: nothing the page asks for can leave the machine.
RESOLVER="--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"
CHROME_BIN="$("$PY" -c 'from playwright.sync_api import sync_playwright
with sync_playwright() as p: print(p.chromium.executable_path)')"
cat >"$OUT/chrome.sh" <<EOF
#!/bin/sh
exec "$CHROME_BIN" "$RESOLVER" "\$@"
EOF
chmod +x "$OUT/chrome.sh"

# next dev compiles the page and its client chunks on first load. Load it once in a browser so
# Bombadil (stops after 60 s without an event) and replays (act at once) meet a hydrated app.
nice -n 10 "$PY" "$HERE/warm.py" "$SHIM" "$COOKIE" "$RESOLVER" "$W" "$H" ||
  echo "ui-explore: warm-up load failed (continuing)" >&2

ARGS=(browser "$MODE" --headless --width "$W" --height "$H" --instrument-javascript files
      --allow-url "$SHIM/*" --cookie "$COOKIE" --output-path "$OUT/trace.bin")
if [ "$MODE" = shrink ]; then ARGS+=(--trace "$REPRO" --time-limit "$LIMIT")
elif [ -n "$REPRO" ]; then ARGS+=(--reproduce "$REPRO")
else ARGS+=(--time-limit "$LIMIT"); fi
[ -n "$EXIT_ON" ] && [ -z "$REPRO" ] && ARGS+=(--exit-on-violation)
echo "ui-explore: $MODE $SHIM ($VIEWPORT ${W}x$H, ${REPRO:-$LIMIT}); trace $OUT/trace.bin"
set +e
CHROME="$OUT/chrome.sh" nice -n 10 "$BOMBADIL" "${ARGS[@]}" "$SHIM/" "$HERE/specification.ts" >"$OUT/bombadil.log" 2>&1
CODE=$?
set -e

"$BOMBADIL" trace "$OUT/trace.bin" >"$OUT/trace.txt" 2>&1 || true
"$PY" "$HERE/summary.py" "$BOMBADIL" "$OUT" || true
echo "ui-explore: unmatched OF reads (got {}): $(cat "$OUT/shim-unmatched.txt" 2>/dev/null | wc -l | tr -d " ")"
echo "ui-explore: inspect: $BOMBADIL browser inspect $OUT/trace.bin"
echo "ui-explore: replay:  scripts/ui-explore/run.sh --viewport=$VIEWPORT --reproduce=$OUT/trace.bin"
exit "$CODE"
