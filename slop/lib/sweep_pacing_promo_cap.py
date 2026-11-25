from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from slop.lib.sweep_pacing_faults import PROMO_CAP
from slop.seed import ts

PAGE, CAP_PAGES = 100, 12
CAP_PROMOS = 1_300
LIVE_AT = 250
DEEP_MIRROR_AT = 1_250
READS = 3
_BASE = 50_000_000_000


def _seed(w, sw, cap: str) -> None:
    sw.promos[cap] = [{"id": _BASE + k, "message": f"slop capped promo {k}", "price": 4.99, "type": "all",
                       "claimsCount": 0, "subscribeCounts": 10, "subscribeDays": 0,
                       "createdAt": (w.now - timedelta(hours=k + 1)).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                       "finishedAt": None, "isFinished": k != LIVE_AT, "canClaim": k == LIVE_AT}
                      for k in range(CAP_PROMOS)]
    con = w.sql()
    with con:
        con.execute("INSERT INTO promo_campaigns (account_id, of_promo_id, name, discount_percent, price_cents,"
                    " subscribe_counts, subscribe_days, message, promo_type, status, subscriber_count,"
                    " auto_reactivate, reactivate_count, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cap, _BASE + DEEP_MIRROR_AT, "slop old campaign", 50, 0, 10, 30, "", "all", "active", 0,
                     0, 0, ts(w.now - timedelta(hours=DEEP_MIRROR_AT + 1))))
    con.close()


async def run(ctx, w, sw, cap: str) -> None:
    _seed(w, sw, cap)
    sw.depth[sw.share.get(cap, cap)] = CAP_PAGES + 1
    gap = CAP_PAGES / sw.refill_per_s + 0.5
    reads = []
    for i in range(READS):
        if i:
            await asyncio.sleep(gap)
        t0 = time.time()
        r = await ctx.owner.get(f"/admin/promotions?account_id={cap}")
        body = r.json() if r.status_code == 200 else {}
        reads.append({"t0": t0, "t1": time.time(), "status": r.status_code,
                      "of_available": body.get("of_available"), "campaigns": body.get("campaigns") or []})
    log = sw.snapshot()
    of_gets = [[e for e in log if e["account"] == cap and e["route"] == "promotions" and x["t0"] <= e["t"] <= x["t1"]]
               for x in reads]
    pages = [sum(1 for e in g if e["status"] == 200) for g in of_gets]
    want = CAP_PAGES * PAGE + 1
    live_id = _BASE + LIVE_AT
    shape = []
    for x, g in zip(reads, of_gets):
        ids = [c.get("of_promo_id") for c in x["campaigns"]]
        live = [c.get("status") for c in x["campaigns"] if c.get("of_promo_id") == live_id]
        shape.append({"status": x["status"], "of_available": x["of_available"], "rows": len(ids),
                      "distinct": len(set(ids)), "live": live, "deep_mirror": _BASE + DEEP_MIRROR_AT in ids,
                      "of_not_200": sum(1 for e in g if e["status"] != 200), "s": round(x["t1"] - x["t0"], 2)})
    rows_ok = all(s["status"] == 200 and s["of_available"] is True and s["rows"] == s["distinct"] == want
                  and s["live"] == ["active"] and s["deep_mirror"] and not s["of_not_200"] for s in shape)
    ctx.check(PROMO_CAP, rows_ok and pages[0] == CAP_PAGES and all(0 < p < CAP_PAGES for p in pages[1:]),
              creator=cap, promos=CAP_PROMOS, cap_pages=CAP_PAGES, pages_per_read=pages,
              live_promo_page=LIVE_AT // PAGE + 1, deep_mirror_page=DEEP_MIRROR_AT // PAGE + 1,
              want_rows=want, reads=shape)
