#!/usr/bin/env python3
"""test_full_ai_live_watch — the sweep's Full AI checks on rows the live sender really writes (ticket 73).

`full_ai_live.run` (OF, Jev, Writers faked; temp DB) writes the rows; the proxy-health SQL
(`scripts/proxy-health/watch.WATCH_SQL`) then runs read-only on that DB file and the pure judges
(`full_ai_watch`) read it, as the 4-hourly sweep does on AE.

  case_sent_turn_is_healthy        a sent Turn: no breach, no stray, no double, `full_ai_live` ok
  case_killed_run_stuck_reaped     killed on bubble 2: `sending` (fresh: ok; aged 31 min: alert);
                                   the rerun reaps it `unconfirmed` (watch); his next DM's reply is
                                   no double; the Creator turned Off: its history is no breach

Run: ./venv/bin/python service/tests/test_full_ai_live_watch.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import timedelta  # noqa: E402
import sqlite3  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import update  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "proxy-health"))
import full_ai_watch as fw  # noqa: E402
import watch as wt  # noqa: E402

from _full_ai_live_fixtures import (  # noqa: E402
    LiveOF, clear_pause, dm, live_rows, payload, seed_live, world,
)
from automations import full_ai_live  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, AutomationRule  # noqa: E402

KEYS = ("full_ai_breach", "full_ai_live_on", "full_ai_live_rows", "full_ai_double", "full_ai_strays",
        "full_ai_orphans")
PER_ACCT = ("full_ai_live_on", "full_ai_live_rows", "full_ai_double", "full_ai_orphans")


def sweep(aid: str) -> dict[str, list]:
    """Each key's rows on a read-only connection to the temp DB (collect.sh's sqlite pass); the per-row keys
    kept to account `aid` (the cases share one DB)."""
    ro = sqlite3.connect(f"file:{_harness.DB_PATH}?mode=ro", uri=True)
    try:
        d = {k: ro.execute(wt.WATCH_SQL[k][0], {**wt.WATCH_SQL[k][1], "since": "-240 minutes"}).fetchall()
             for k in KEYS}
    finally:
        ro.close()
    return {k: [r for r in v if r[0] == aid] if k in PER_ACCT else v for k, v in d.items()}


def live_verdict(d: dict) -> tuple[str, str]:
    return fw.judge_live(d["full_ai_live_rows"], d["full_ai_double"], {r[0] for r in d["full_ai_live_on"]}, set(), [],
                         d["full_ai_orphans"])


async def _run(aid, fan, mid, rid, **kw):
    with world(**kw) as w:
        try:
            res = await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
        except BaseException as e:  # noqa: BLE001 — the case reads it
            res = e
    return res, w


def _kill_at(n: int):
    def before(call: int, _text: str) -> None:
        if call == n:
            raise asyncio.CancelledError()
    return before


async def case_sent_turn_is_healthy():
    aid, fan, mid = "fa_w_ok", 701, 9101
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid)
    assert res["row_status"] == "sent" and w.of.calls == res["sent"] >= 2, res
    d = sweep(aid)
    assert d["full_ai_breach"] == [(0, 0, None, None)], d["full_ai_breach"]
    assert d["full_ai_live_on"] == [(aid,)] and d["full_ai_double"] == [], d
    assert d["full_ai_live_rows"] == [(aid, fan, "sent", 0, 1, 0)], d["full_ai_live_rows"]
    assert d["full_ai_strays"][0][1] == 0, d["full_ai_strays"]
    assert live_verdict(d) == ("ok", "1 live rows: 1 sent, 0 no_send (0 stood down), 0 unconfirmed, 0 failed,"
                                     " 0 sending; 1 live Creators"), live_verdict(d)
    assert fw.alert(d["full_ai_breach"], {"caller": {"auto:full_ai_chat": [res["sent"], 0]}}, "", {aid})[0] is None


async def case_killed_run_stuck_reaped():
    aid, fan, mid = "fa_w_kill", 702, 9201
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(_kill_at(2)))
    assert isinstance(res, asyncio.CancelledError) and len(w.of.sent) == 1, res
    d = sweep(aid)
    assert d["full_ai_live_rows"] == [(aid, fan, "sending", 0, 1, 0)], d["full_ai_live_rows"]
    assert d["full_ai_double"] == [] and live_verdict(d)[0] == "ok", d     # in flight, one unclaimed bubble
    (row,) = await live_rows(aid)
    async with get_session() as s:                                         # the run died 31 min ago
        await s.execute(update(AiDecision).where(AiDecision.id == row.id).values(
            created_at=row.created_at - timedelta(minutes=31)))
    st, det = live_verdict(sweep(aid))
    assert (st, det.split(";")[0]) == ("alert", f"1 sending > 30 min: {aid}/{fan}"), det
    await clear_pause(aid, fan)
    res, w = await _run(aid, fan, mid, rid)                               # the next run reaps it
    assert res == {"skipped": "no_turn"} and w.of.calls == 0, res
    st, det = live_verdict(sweep(aid))
    assert (st, det.split(";")[0]) == ("watch", f"1 unconfirmed: {aid}/{fan}"), det
    await clear_pause(aid, fan)
    await dm(aid, fan, mid + 1, "u there?", ago_s=0)
    res, w = await _run(aid, fan, mid + 1, rid)                           # his next DM: a new Turn
    assert res["row_status"] == "sent", res
    d = sweep(aid)
    assert d["full_ai_double"] == [] and d["full_ai_breach"] == [(0, 0, None, None)], d
    async with get_session() as s:                                         # the owner turns it Off
        await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(is_enabled=False))
    d = sweep(aid)
    assert d["full_ai_live_on"] == [] and d["full_ai_breach"] == [(0, 0, None, None)], d
    assert d["full_ai_strays"][0][1:3] == (2, aid), d["full_ai_strays"]   # the known one-run false watch


_harness.run()
