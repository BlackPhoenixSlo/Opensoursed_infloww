from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import parse_qs

from slop.actors import fan_dm
from slop.lib.view_lease_faults import DM_NO_BUST
from slop.lib.view_lease_feed import until

PLAIN_N = 5
ID_BASE = 9_570_000_000_000
NOTIF_PAGE_SIZE = 20
WINDOW_MAX_S = 25.0
LANDED_S = 10.0
SETTLE_S = 0.3
READS = {"purchases": f"/api/of/v2/users/notifications?limit={NOTIF_PAGE_SIZE}&offset=0&type=purchases",
         "tip": f"/api/of/v2/users/notifications?limit={NOTIF_PAGE_SIZE}&offset=0&type=tip",
         "count": "/api/of/v2/users/notifications/count"}


def _calls(fake, aid: str, lo: float) -> dict[str, int]:
    out = {k: 0 for k in READS}
    with fake.lock:
        for c in fake.calls:
            if c["account"] != aid or c["t0"] is None or c["t0"] < lo:
                continue
            if c["route"] == "GET /api2/v2/users/notifications/count":
                out["count"] += 1
            elif c["route"] == "GET /api2/v2/users/notifications":
                q = parse_qs(c.get("query") or "")
                kind = (q.get("type") or [""])[0]
                if kind in ("purchases", "tip") and (q.get("limit") or [""])[0] == str(NOTIF_PAGE_SIZE):
                    out[kind] += 1
    return out


async def _read(owner, aid: str) -> list[int]:
    return [(await owner.get(p, headers={"X-Account-Id": aid})).status_code for p in READS.values()]


async def run(ctx, aid: str) -> None:
    w, fake, owner = ctx.world, ctx.of_wire, ctx.owner
    fans = w.data["fans"][aid]
    ids = iter(range(ID_BASE, ID_BASE + 10**6))
    statuses: list[int] = []

    def landed(mid: int) -> bool:
        con = w.sql()
        try:
            return con.execute("SELECT 1 FROM messages WHERE account_id=? AND message_id=?", (aid, mid)).fetchone() \
                is not None
        finally:
            con.close()

    async def dm(fan: dict, tip: float) -> dict:
        mid = next(ids)
        r = await fan_dm.inject(owner, aid, fan_dm.frame(mid, fan, f"slop dm-no-bust {mid % 1000}", tip_dollars=tip))
        ok = await until(lambda: landed(mid), LANDED_S, step=0.1)
        await asyncio.sleep(SETTLE_S)
        t = time.time()
        statuses.extend(await _read(owner, aid))
        return {"message_id": mid, "tip": tip, "status": r.status_code, "landed": ok, "t_read": t}

    t0 = time.time()
    statuses.extend(await _read(owner, aid))
    t_plain = time.time()
    primed = _calls(fake, aid, t0)
    plain = [await dm(fans[k % len(fans)], 0) for k in range(PLAIN_N)]
    t_tip = time.time()
    after_plain = _calls(fake, aid, t_plain)
    tip = await dm(fans[0], 10)
    t_end = time.time()
    after_tip = _calls(fake, aid, t_tip)
    window = round(t_end - t0, 2)
    frames_ok = all(d["status"] == 200 and d["landed"] for d in plain + [tip])
    ok = (frames_ok and all(s == 200 for s in statuses) and window <= WINDOW_MAX_S
          and primed == {k: 1 for k in READS}
          and after_plain == {k: 0 for k in READS} and after_tip == {k: 1 for k in READS})
    ctx.check(DM_NO_BUST, ok, creator=aid, plain_dms=PLAIN_N, primed=primed, after_plain=after_plain,
              after_tip=after_tip,
              window_s=window, window_max_s=WINDOW_MAX_S, frames_ok=frames_ok,
              read_statuses=sorted(set(statuses)))
    (ctx.out / "dm-no-bust.json").write_text(json.dumps({
        "creator": aid, "t": {"start": t0, "plain": t_plain, "tip": t_tip, "end": t_end},
        "plain": plain, "tip": tip, "primed": primed, "after_plain": after_plain, "after_tip": after_tip,
    }, indent=1))
