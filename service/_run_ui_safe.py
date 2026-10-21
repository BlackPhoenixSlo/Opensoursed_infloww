#!/usr/bin/env python3
"""Spin the relay LOCALLY in SAFE / view-only mode.

Serves the full API (so the Next dev UI can read it) with the whole spawn/network
section of the startup hook skipped, so nothing reaches OF and nothing reaches a
fan. DB init still runs, which is what the UI needs.

⚠️ THIS USED TO PATCH FOUR NAMES BY HAND AND IT MISSED ONE. `start_supervisor`
was neutered but `start_fast_poll` — the 30s freshness poll layered on top of it,
spawned separately at server.py's `_tx_fast_task` — was not, so a run on a
prod-copy DB opened a real OFClient, fetched the live x-of-rev, and wrote
transactions and an ownership stamp into the DB. No sends (the executor patch did
hold), but "Nothing goes out to OF" was false.

The fix is not a fifth patch: `CHATTERLY_TEST_MODE` is the codebase's own switch
for exactly this and it returns before the ENTIRE spawn/network block, so it
cannot be outrun by a new task appearing there. The hand-patches stay below as
belt-and-suspenders, in the same spirit as the note at that guard.

For looking at the UI on a prod-copy DB without firing any enabled automation.

Run:  ./venv/bin/python service/_run_ui_safe.py
      → API at http://127.0.0.1:8787  (Next dev UI proxies /admin here on :3001)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
if str(_S) not in sys.path:
    sys.path.insert(0, str(_S))

# Set BEFORE `import server` — the guard is read inside its startup hook, but
# setting it first means no import-time path can race it either.
os.environ["CHATTERLY_TEST_MODE"] = "1"

import automation_executor          # noqa: E402
import transaction_ingest           # noqa: E402
import server                       # noqa: E402


async def _noop_forever() -> None:
    while True:
        await asyncio.sleep(3600)


# Disable every outbound/background loop BEFORE the startup hook reads them.
automation_executor.automation_supervisor = _noop_forever   # no rule firing / sends
transaction_ingest.start_supervisor = _noop_forever         # no payouts ingest
transaction_ingest.start_fast_poll = _noop_forever          # ← the one that got out
server._start_account_pump = lambda *a, **k: None           # no OF WS connect
server._pump_supervisor = _noop_forever                     # no pump management


if __name__ == "__main__":
    import uvicorn
    print("=" * 64)
    print("SAFE relay — CHATTERLY_TEST_MODE=1: no pumps, no ingest, no OF, no sends")
    print("API:  http://127.0.0.1:8787")
    print("UI :  start the Next dev server (cd app && npm run dev) → :3001")
    print("=" * 64)
    uvicorn.run(server.app, host="127.0.0.1", port=8787, log_level="warning")
