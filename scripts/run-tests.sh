#!/usr/bin/env bash
# Run the whole project test suite:
#   - backend: every service/tests/test_*.py plain-assert script, ncpu/2 at a
#     time (scripts/run_tests_parallel.py: in-order buffered output, 600 s
#     per-script timeout, 10 slowest printed)
#   - frontend: vitest (app/) one-shot
# Exit 0 only if everything passes.
#
#   scripts/run-tests.sh              everything
#   scripts/run-tests.sh full_ai      only service/tests/test_*full_ai*.py (glob ok), no vitest
#
# Env: RUN_TESTS_JOBS (default ncpu/2), RUN_TESTS_TIMEOUT (default 600 s).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/venv/bin/python"
PATTERN="${1:-}"
NCPU="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
JOBS="${RUN_TESTS_JOBS:-$(( NCPU / 2 > 0 ? NCPU / 2 : 1 ))}"
fail=0

echo "──────── Backend (service/tests/*.py) ────────"
if [ ! -x "$PY" ]; then
  echo "✗ venv python not found at $PY"; fail=1
else
  "$PY" "$ROOT/scripts/run_tests_parallel.py" "$ROOT/service/tests" ${PATTERN:+"$PATTERN"} \
    -j "$JOBS" --timeout "${RUN_TESTS_TIMEOUT:-600}" || fail=1
fi

if [ -z "$PATTERN" ]; then
  echo "──────── Frontend (vitest, app/) ────────"
  if [ -f "$ROOT/app/vitest.config.ts" ] && [ -d "$ROOT/app/node_modules/vitest" ]; then
    ( cd "$ROOT/app" && pnpm test:run ) || fail=1
  else
    echo "… vitest not installed yet (run T-TESTKIT); skipping frontend"
  fi
fi

echo "─────────────────────────────────────────────"
if [ "$fail" -eq 0 ]; then echo "✅ ALL TESTS PASSED"; else echo "❌ SOME TESTS FAILED"; fi
exit "$fail"
