#!/usr/bin/env bash
# run.sh — the OF-manager Live proof harness (docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md).
#
#   scripts/of-live-proof/run.sh --of fake [--proof tracer.create-list]
#   scripts/of-live-proof/run.sh --of fake|live [--session-dir <dir>] serve
#
# Fake mode: a loopback-only stack (FakeOF, the guarded Relay, next dev, Chromium) at nice >= 10, one evidence
# folder under slop/evidence/. `capture [--abort] --proof <id>` plays one proof in the capture browser (fake mode).
# Live mode needs --session-dir (no default) and is never run unattended; `serve` prints the stack's URLs and waits
# for Ctrl-C. See prove.py and live_entry.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/venv/bin/python"

if ! test -x "$PY"; then
  echo "ofm-live-proof: $PY not found (needs the repo's relay venv with uvicorn, FastAPI, Playwright)." >&2
  exit 3
fi
# Importing service/secrets_store.py would copy service/secrets.json into service/secrets/ before the redirect can
# run (docs/ui-shots.md, as scripts/demo-shots/run.sh). Refuse in that state.
if [ -f "$ROOT/service/secrets.json" ] && [ ! -e "$ROOT/service/secrets/secrets.json" ]; then
  echo "ofm-live-proof: service/secrets.json exists and service/secrets/secrets.json does not; see docs/ui-shots.md." >&2
  exit 3
fi
export PYTHONDONTWRITEBYTECODE=1
exec nice -n 10 "$PY" -u "$ROOT/scripts/of-live-proof/prove.py" "$@"
