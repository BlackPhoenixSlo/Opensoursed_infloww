#!/usr/bin/env bash
#
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/venv/bin/python"

if ! test -x "$PY"; then
  echo "ofm-live-proof: $PY not found (needs the repo's relay venv with uvicorn, FastAPI, Playwright)." >&2
  exit 3
fi
# Importing service/secrets_store.py would copy secrets.json into service/secrets/ before the redirect can run; refuse in that state.
if [ -f "$ROOT/service/secrets.json" ] && [ ! -e "$ROOT/service/secrets/secrets.json" ]; then
  echo "ofm-live-proof: service/secrets.json exists and service/secrets/secrets.json does not; see docs/ui-shots.md." >&2
  exit 3
fi
export PYTHONDONTWRITEBYTECODE=1
exec nice -n 10 "$PY" -u "$ROOT/scripts/of-live-proof/prove.py" "$@"
