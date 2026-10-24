"""A relay crash in the middle of a fan DM flood. The local DB is a best-effort
cache of OnlyFans for OF-sourced rows (db/of_writer.py: no durable outbox), so a
SIGKILL may lose what the relay held in memory: frames still in the persist queue
and the OF-cache writer's open batch. This bounds that loss and shows the normal
OF read path fills it back in.

Flow: --users fans DM their Creators in the pump's shape (fan_dm.serial, open loop
at --rate frames/s per Creator). Partway through, the relay is SIGKILLed (no
shutdown hook runs), stays down DOWN_S while fans keep writing (OnlyFans holds
those; the relay never sees them), then starts again on the same DB. Afterwards
OnlyFans' side of the record (every DM sent, seen or not) is written to the fake
OF read (lib/relay.py `_OfflineOF.get_messages`) and the chat's own refresh,
POST /admin/messages/{aid}/{fan}/rescrape-now (the chat scrape), runs per thread.

Invariants: loss is bounded (every DM the relay took more than LOSS_WINDOW_MS
before the kill is in its thread); after the refill every DM OnlyFans holds is in
its thread, none twice. Measured, not asserted: how many taken DMs were lost and
how close to the kill they were.

Bypass (declared): the fan pump uses its own Recorder, so the transport errors of
frames sent into the outage (the relay is down: they never arrive) are counted in
metric `pump` instead of failing the stock "no 5xx or transport error" check. Every
manager call (thread reads, rescrape-now) is recorded as usual.
Break-it-once: of-writer-holds-batches-3s (lib/faults.py).
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime, timezone

from slop.actors import fan_dm, manager
from slop.lib.client import Recorder

PROFILE = "agency_inbox"
UI = False
FAULT = "of-writer-holds-batches-3s"
RECENT_MAX = 100
LOSS_WINDOW_MS = 1000      # a DM the relay took longer ago than this before the kill must have been written
DOWN_S = 2.0               # relay down this long, fans still writing
KILL_AT_FRAC = 0.5         # of the flood's scheduled length
CHECK_BOUNDED = f"crash loses only DMs the relay took < {LOSS_WINDOW_MS}ms before the kill"
CHECK_REFILL = "after rescrape-now every DM OnlyFans holds is in its thread"
CHECK_NO_DUP = "rescrape-now added no DM twice"
P95_MS = {"POST /admin/messages/:id/:id/rescrape-now": 2000}


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    per_fan = ctx.param("per_fan", {"small": 10, "medium": 10, "huge": 20}[ctx.scale])
    rate = ctx.param("rate", 5.0)  # frames/s per Creator
    creators, fans = w.data["creators"], w.data["fans"]
    k = min(RECENT_MAX, math.ceil(ctx.users / len(creators)))
    rng = w.rng("scenario:relay-crash")
    targets = [f for c in creators for f in rng.sample(fans[c["id"]], min(k, len(fans[c["id"]])))][: ctx.users]
    per_acct = max(sum(1 for t in targets if t["account_id"] == c["id"]) for c in creators)
    flood_s = per_acct * per_fan / rate
    ctx.metric("flood", {"fans": len(targets), "per_fan": per_fan, "dms": len(targets) * per_fan,
                         "rate_per_account": rate, "scheduled_s": round(flood_s, 1),
                         "kill_at_s": round(flood_s * KILL_AT_FRAC, 1), "down_s": DOWN_S})

    pump_rec = Recorder()
    pool = ctx.owner.share(rec=pump_rec, limits=max(10, len(creators)))
    flood = asyncio.create_task(fan_dm.serial(pool, targets, per_fan, rate=rate, text="slop crash dm"))
    await asyncio.sleep(flood_s * KILL_AT_FRAC)
    kill_ms = ctx.stack.crash_relay() * 1000
    await asyncio.sleep(DOWN_S)
    t_up = time.time()
    await asyncio.to_thread(ctx.stack.start_relay)
    up_ms = time.time() * 1000
    recs = await flood
    await pool.aclose()
    owner = ctx.owner.share()  # fresh connections: the old pool's sockets died with the relay
    stats = await manager.quiesce(owner)

    taken = [r for r in recs if r["status"] < 300]
    before = [r for r in taken if r["t1"] < kill_ms]
    ctx.metric("pump", {"frames": len(recs), "taken": len(taken), "taken_before_kill": len(before),
                        "not_taken": len(recs) - len(taken),
                        "transport_errors": sum(1 for r in recs if r["status"] == 599),
                        "restart_s": round(up_ms / 1000 - t_up, 2)})
    ctx.check("relay was killed mid-flood and came back", len(before) > 0 and len(taken) > len(before)
              and not stats.get("timed_out"), taken_before_kill=len(before), taken_after=len(taken) - len(before))

    by_fan: dict[tuple, list[dict]] = {}
    for r in recs:
        by_fan.setdefault((r["account_id"], r["fan_id"]), []).append(r)
    sem = asyncio.Semaphore(20)

    async def thread_ids(key) -> list[int]:
        async with sem:
            return [m["message_id"] for m in await manager.thread_messages(owner, key[0], key[1])]

    keys = list(by_fan)
    have = set().union(*map(set, await asyncio.gather(*(thread_ids(k_) for k_ in keys))))
    lost = [r for r in before if r["message_id"] not in have]
    late = [r for r in lost if kill_ms - r["t1"] >= LOSS_WINDOW_MS]
    ctx.metric("crash_loss", {"lost_taken": len(lost), "of_taken_before_kill": len(before),
                              "taken_ms_before_kill": sorted(round(kill_ms - r["t1"], 1) for r in lost)[:20],
                              "never_seen": sum(1 for r in recs if r["message_id"] not in have)})
    ctx.check(CHECK_BOUNDED, not late, lost_older=len(late), lost_total=len(lost),
              oldest_ms=round(max((kill_ms - r["t1"] for r in lost), default=0), 1))

    # OnlyFans' side of the record: every DM a fan sent, whether the relay saw it or not.
    truth = ctx.stack.tmp / "of-truth.jsonl"
    with truth.open("w") as fh:
        for r in recs:
            at = datetime.fromtimestamp(r["t0"] / 1000, timezone.utc).isoformat(timespec="milliseconds")
            fh.write(json.dumps({"account_id": r["account_id"], "fan_id": r["fan_id"], "message": {
                "id": r["message_id"], "text": "<p>slop crash dm</p>", "price": 0, "isFree": True,
                "mediaCount": 0, "media": [], "fromUser": {"id": r["fan_id"]}, "createdAt": at}}) + "\n")

    async def rescrape(key) -> dict:
        async with sem:
            return (await owner.post(f"/admin/messages/{key[0]}/{key[1]}/rescrape-now")).json()

    res = await asyncio.gather(*(rescrape(k_) for k_ in keys))
    bad = [r for r in res if not r.get("ok")]
    ctx.metric("refill", {"threads": len(keys), "inserted": sum(r.get("inserted", 0) for r in res if r.get("ok")),
                          "failed": len(bad), "sample_failed": bad[:3]})
    ctx.check("rescrape-now ok for every thread", not bad, failed=len(bad))

    after = await asyncio.gather(*(thread_ids(k_) for k_ in keys))
    missing = dups = 0
    for k_, ids in zip(keys, after):
        missing += len({r["message_id"] for r in by_fan[k_]} - set(ids))
        dups += len(ids) - len(set(ids))
    ctx.check(CHECK_REFILL, missing == 0, missing=missing, refilled=len([r for r in recs if r["message_id"] not in have]))
    ctx.check(CHECK_NO_DUP, dups == 0, duplicated=dups)

    routes = ctx.rec.summary()
    for route, budget in P95_MS.items():
        if route in routes:
            ctx.check(f"p95 {route} < {budget}ms", routes[route]["p95_ms"] < budget, budget=True,
                      p95=routes[route]["p95_ms"], n=routes[route]["n"])
        else:
            ctx.skip(f"p95 {route} < {budget}ms", "no samples")
    await owner.aclose()
