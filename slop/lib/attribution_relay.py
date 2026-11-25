import json
import math
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

LEDGER_LATEST = 600
CB_PAGE_CAP = 100
_ledger = {"calls": 0, "rows_served": 0, "cb_items_served": 0}
_cb_calls: Counter = Counter()
_cb_queries: list = []
_latest: dict[str, int] = {}
_lock = threading.Lock()


def _naive(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _lines(name: str, account_id: str, err: Exception) -> list[dict]:
    path = Path(os.environ.get("DEMO_SHOTS_TMP", "")) / name
    if not path.is_file():
        raise err
    out = []
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if str(rec.get("account_id")) == str(account_id):
            out.append(rec)
    return out


class OF:
    def transactions(self, *, limit=10, offset=0, start_date=None, marker=None, **_kw) -> dict:
        by_id: dict = {}
        for rec in _lines("of-ledger.jsonl", self.account_id, self._err):
            by_id[rec["row"]["id"]] = rec["row"]
        if start_date and len(str(start_date)) != 10:
            rows = []  # OF answers nothing for an ISO startDate  # OF answers nothing for an ISO startDate
        else:
            rows = sorted(((at, r) for r in by_id.values() if (at := _naive(r.get("createdAt"))) is not None
                           and (not start_date or at.date().isoformat() >= start_date)),
                          key=lambda x: x[0], reverse=True)
        with _lock:
            latest = _latest.get(str(self.account_id))
        if latest is not None:
            rows = rows[:latest]
        if marker is not None:
            bound = datetime.utcfromtimestamp(float(marker))
            rows = [(at, r) for at, r in rows if at <= bound]
            offset = 0
        limit = min(int(limit), 100)
        page = ([r for _, r in rows[offset:offset + limit if marker is not None else min(offset + limit, LEDGER_LATEST)]]
                if marker is not None or offset < LEDGER_LATEST
                else [])
        more = offset + limit < len(rows) if page else False
        next_marker = math.ceil(rows[offset + limit][0].replace(tzinfo=timezone.utc).timestamp()) if more else None
        with _lock:
            _ledger["calls"] += 1
            _ledger["rows_served"] += len(page)
        return {"list": page, "hasMore": more, **({"nextMarker": next_marker} if more else {})}

    def chargebacks(self, *, start=None, end=None, limit=10, offset=0, **_kw) -> dict:
        lo, hi = (str(start)[:10] if start else None), (str(end)[:10] if end else None)
        items = []
        for rec in _lines("of-chargebacks.jsonl", self.account_id, self._err):
            at = _naive(rec["item"].get("createdAt"))
            if at is None or (lo and at.date().isoformat() < lo) or (hi and at.date().isoformat() >= hi):
                continue
            items.append((at, rec["item"]))
        items.sort(key=lambda x: x[0], reverse=True)
        lim = min(int(limit), CB_PAGE_CAP)
        page = [i for _, i in items[offset:offset + lim]]
        with _lock:
            _cb_calls[str(self.account_id)] += 1
            _ledger["cb_items_served"] += len(page)
            _cb_queries.append({"account": str(self.account_id), "start": start, "end": end, "limit": limit,
                                "offset": offset, "served": len(page)})
        return {"list": page, "marker": int(time.time())}


def wire(app, loopback, _relay) -> None:
    from fastapi import Request

    async def ledger(request: Request) -> dict:
        loopback(request)
        with _lock:
            return {**_ledger, "cb_calls": dict(_cb_calls), "cb_queries": list(_cb_queries[-50:])}

    async def ledger_set(request: Request) -> dict:
        loopback(request)
        body = await request.json()
        with _lock:
            _latest.update({str(k): int(v) for k, v in (body.get("latest") or {}).items()})
            return {"latest": dict(_latest)}

    app.add_api_route("/__slop/ledger", ledger, methods=["GET"])
    app.add_api_route("/__slop/ledger", ledger_set, methods=["POST"])
