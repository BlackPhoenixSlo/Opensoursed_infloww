"""Sales attribution's part of the slop relay (lib/relay.py loads it: `OF` joins
`_OfflineOF`'s bases, `wire` runs at the end of its `_wire`).

OnlyFans' payouts ledger is faked only when a scenario writes
`$DEMO_SHOTS_TMP/of-ledger.jsonl` (one line per ledger row: `{"account_id": ...,
"row": <an OF /payouts/transactions row>}`, appended while the run goes on):
`transactions` (GET /api2/v2/payouts/transactions, what
`transaction_ingest.run_one_tick` pages) answers the Creator's rows whose
`createdAt` is inside [start, end], newest first, `limit` per page from `offset`,
with `hasMore`, read from the file when the call arrives (a line still being
written is skipped). No file: the read fails as before. Latency: none (the real
ledger walk sleeps 0.4 s between pages; one page holds a slop Creator's rows).

  GET /__slop/ledger  {calls, rows_served}: ledger pages OF answered.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

_ledger = {"calls": 0, "rows_served": 0}
_lock = threading.Lock()  # the ingest pages from a worker thread


def _naive(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


class OF:
    def transactions(self, *, limit=10, offset=0, start=None, end=None, **_kw) -> dict:
        path = Path(os.environ.get("DEMO_SHOTS_TMP", "")) / "of-ledger.jsonl"
        if not path.is_file():
            raise self._err
        lo, hi = _naive(start), _naive(end)
        rows = []
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # the scenario is mid-write on this line
            if str(rec.get("account_id")) != str(self.account_id):
                continue
            at = _naive(rec["row"].get("createdAt"))
            if at is None or (lo and at < lo) or (hi and at > hi):
                continue
            rows.append((at, rec["row"]))
        rows.sort(key=lambda x: x[0], reverse=True)
        page = [r for _, r in rows[offset:offset + limit]]
        with _lock:
            _ledger["calls"] += 1
            _ledger["rows_served"] += len(page)
        return {"list": page, "hasMore": offset + limit < len(rows)}


def wire(app, loopback, _relay) -> None:
    from fastapi import Request

    async def ledger(request: Request) -> dict:
        loopback(request)
        with _lock:
            return dict(_ledger)

    app.add_api_route("/__slop/ledger", ledger, methods=["GET"])
