"""The ledger backfill's between-ticks statuses on Ingest health (components/stats/IngestHealthBanner.tsx,
in Creator reports' Inflowwww extras), from real supervisor passes against OF's ledger (lib/sweep_pacing_wire.py).

World: `agency_inbox`, a captured session per Creator. STALL holds STALL_ROWS ledger rows and OF answers its
first page blank once; LONG holds LONG_ROWS rows, past one tick's page cap; every other Creator's ledger is empty.
Flow: one supervisor pass (real `supervisor_cycle`, `POST /__slop/sweep-pacing/run`), the owner opens the page
and Ingest health (screenshot `trigger-stalled-and-working`), SETTLE_PASSES more passes, reload (screenshot `settled`).

Checks (names in lib/ingest_banner_faults.py, and below):
  banner_words_a_stopped_and_a_working_walk  after pass 1 the page says "backfill stalled" with its reason as the
                         row's title and "backfilling · still working", neither raw status.
  health_api_after_pass_1  the health API: STALL backfill_stalled + yellow + its reason, LONG backfill_partial + green.
  banner_settled         after the last pass neither wording remains and both rows read "last scan".
  rows_landed            each Creator's held provider ids == OF's, fully_backfilled 1, health API ok + green.
"""
from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from slop.actors import ui
from slop.lib.ingest_banner_faults import WORDS
from slop.lib.sweep_pacing_wire import SweepWire
from slop.seed import of_sessions

PROFILE = "agency_inbox"
UI = True
OF_WIRE = True
FAULT = "ingest-banner-raw-status"
STALL_ROWS, LONG_ROWS = 300, 4_200   # LONG: 42 pages, the tick cap's 40 + the rest
SETTLE_PASSES = 2                    # LONG: its full walk, then the rest of its walk
PASS_TIMEOUT_S = 300
HEALTH = "banner_settled"
API, LANDED = "health_api_after_pass_1", "rows_landed"
PAGE = "/analytics/creator-reports"
STALLED, WORKING = "backfill stalled", "backfilling · still working"


def _rows(base: int, fan_ids: list[int], n: int, top) -> list[dict]:
    step = timedelta(days=30) / n
    return [{"id": base + k, "user": {"id": fan_ids[k % len(fan_ids)]}, "amount": 12.0, "currency": "USD",
             "createdAt": (top - step * k).strftime("%Y-%m-%dT%H:%M:%S+00:00"), "status": "done",
             "net": 9.6, "fee": 2.4, "vatAmount": 0, "description": "Tip"} for k in range(n)]


async def _one_pass(ctx) -> None:
    n0 = sum(1 for x in (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()["runs"] if x["t1"])
    (await ctx.owner.post("/__slop/sweep-pacing/run", json={"job": "tx_cycles", "cycles": 1})).raise_for_status()
    until = time.monotonic() + PASS_TIMEOUT_S
    while time.monotonic() < until:
        if sum(1 for x in (await ctx.owner.get("/__slop/sweep-pacing/runs")).json()["runs"] if x["t1"]) > n0:
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("a supervisor pass outlasted PASS_TIMEOUT_S")


async def _health(ctx, aid: str) -> dict:
    r = await ctx.owner.get("/admin/ingest/transactions/health")
    r.raise_for_status()
    body = r.json()
    rows = body if isinstance(body, list) else body.get("accounts") or body.get("rows") or []
    return next((x for x in rows if str(x["account_id"]) == str(aid)), {})


async def _open_health(page, app: str) -> None:
    await page.goto(f"{app}{PAGE}", wait_until="domcontentloaded")
    await page.get_by_role("button", name="Inflowwww extras").click(timeout=90_000)
    await page.get_by_role("region", name="Inflowwww extras").get_by_role("button", name="Ingest health").click(timeout=60_000)
    await page.get_by_text("last scan").first.wait_for(timeout=60_000)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    stall, long_ = creators[0]["id"], creators[1]["id"]
    of_sessions.seed(w, creators)
    sw = SweepWire(ctx.of_wire)
    fan_ids = {a: [f["id"] for f in w.data["fans"][a]] for a in (stall, long_)}
    sw.txs[stall] = _rows(40_000_000_000, fan_ids[stall], STALL_ROWS, w.now - timedelta(hours=2))
    sw.txs[long_] = _rows(41_000_000_000, fan_ids[long_], LONG_ROWS, w.now - timedelta(hours=2))
    sw.inject[(stall, "transactions")] = {"offset": 0, "empty": True}
    sw.install()

    await _one_pass(ctx)
    h_stall, h_long = await _health(ctx, stall), await _health(ctx, long_)
    ctx.check(API, h_stall.get("current_status") == "backfill_stalled" and h_stall.get("tier") == "yellow"
              and h_stall.get("last_error") == "backfill_stopped: blank_first_page"
              and h_long.get("current_status") == "backfill_partial" and h_long.get("tier") == "green",
              stall=h_stall, long=h_long)

    async def settle() -> None:
        for _ in range(SETTLE_PASSES):
            await _one_pass(ctx)

    if not ctx.app:
        await settle()
        for n in (WORDS, HEALTH):
            ctx.skip(n, "--no-ui")
    else:
        async with ui.owner_browser(ctx) as page:
            await _open_health(page, ctx.app)
            stopped, working = page.get_by_text(STALLED, exact=True), page.get_by_text(WORKING, exact=True)
            seen = True
            try:
                await stopped.first.wait_for(timeout=30_000)
                await working.first.wait_for(timeout=30_000)
            except Exception:
                seen = False
            title = await stopped.first.get_attribute("title", timeout=5_000) if seen else None
            raw = await page.get_by_text("backfill_stalled", exact=True).count() + await page.get_by_text(
                "backfill_partial", exact=True).count()
            trigger = await ui.shot(ctx, page, "trigger-stalled-and-working")
            ctx.check(WORDS, seen and raw == 0 and title == "backfill_stopped: blank_first_page",
                      seen=seen, raw_statuses=raw, title=title, screenshot=trigger)
            await settle()
            await _open_health(page, ctx.app)
            await page.wait_for_timeout(1_000)
            left = await page.get_by_text(STALLED, exact=True).count() + await page.get_by_text(WORKING, exact=True).count()
            scans = await page.get_by_text("last scan").count()
            settled = await ui.shot(ctx, page, "settled")
            ctx.check(HEALTH, left == 0 and scans >= 2, labels_left=left, rows=scans, screenshot=settled)

    con = w.sql()
    wrong = {}
    for a in (stall, long_):
        ids = {str(r[0]) for r in con.execute("SELECT provider_transaction_id FROM transactions WHERE account_id = ? "
                                              "AND provider_transaction_id IS NOT NULL", (a,))}
        done = con.execute("SELECT fully_backfilled FROM transaction_scan_history WHERE account_id = ?", (a,)).fetchone()[0]
        h = await _health(ctx, a)
        want = {str(r["id"]) for r in sw.txs[a]}
        if ids != want or not done or h.get("current_status") != "ok" or h.get("tier") != "green":
            wrong[a] = {"held": len(ids), "of": len(want), "done": done, "status": h.get("current_status"), "tier": h.get("tier")}
    con.close()
    ctx.check(LANDED, not wrong, wrong=wrong, creators=[stall, long_])
