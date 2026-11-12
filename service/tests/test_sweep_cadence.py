#!/usr/bin/env python3
"""
sweep_cadence — full chat sweeps (`scrape_chats` `{}`) on a cadence, not per restart.

  case_plan_table:
      the pure plan: keep the oldest pending automation sweep, cancel the rest;
      none kept beside a running / operator / rule sweep; enqueue only for a live
      account with nothing open and no recent sweep.
  case_restarts_leave_one_open_sweep_per_account:
      three simulated restarts (module reloaded, a pass each) over a seeded
      backlog of 5 identical sweeps: one stays per account, the rest cancelled
      DUP_REASON; a `fan_ids` job and an operator's `{}` job untouched.
  case_never_swept_gets_one_at_once_and_dead_or_off_get_none:
      a live account with no sweep ever gets one on the first pass; a deactivated,
      a session-dead and a session-less account get none.
  case_cadence_anchors_on_the_last_finished_sweep:
      a `{}` sweep finished ok 1 h ago holds the next one, at SWEEP_EVERY_S + 1 min
      one is enqueued; a `{}` job parked 'error' by a real error holds it too. A
      failed fan_ids run, a `{"limit": 50}` run, a `{}` job whose retries restarts
      cancelled, and an interrupted run never delay it.
  case_sweep_with_every_chat_failed_raises_not_full_sweep:
      a `{}` scrape_chats run whose every target chat failed raises (the job
      retries, then parks 'error'); one scraped chat finalises `full_sweep`; an
      explicit-id run with every chat failed still returns its stats. A sweep whose
      first SCRAPE_SWEEP_FAIL_FAST (5) chats all failed stops there (no more OF calls) and raises.
      OF's 404 (fan gone) is handled, not a failure: 5 gone then good chats, and an
      all-gone small sidebar, finalise `full_sweep` without raising.

Run: ./venv/bin/python service/tests/test_sweep_cadence.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import importlib  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402
import sweep_cadence  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AutomationRun, Employee, ScheduledJob  # noqa: E402
from sweep_cadence import OpenJob, plan  # noqa: E402

_SESSIONS: dict[str, bool] = {}
account_registry.list_accounts = lambda include_watchers=False: [
    {"id": a, "has_session": has} for a, has in _SESSIONS.items()]


async def _accounts(*ids: str, session: bool = True) -> None:
    async with get_session() as s:
        for aid in ids:
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
            _SESSIONS[aid] = session


async def _jobs(aid: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.kind == "scrape_chats")
            .order_by(ScheduledJob.id))).scalars().all())


def _open_sweeps(jobs: list[ScheduledJob]) -> list[ScheduledJob]:
    return [j for j in jobs if j.payload_json == "{}" and j.status in ("pending", "running")]


async def _run(aid: str, *, ago_s: float, stats: dict | None) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(AutomationRun(account_id=aid, kind="scrape_chats", status="ok" if stats else "error",
                            started_at=now - timedelta(seconds=ago_s + 60),
                            completed_at=now - timedelta(seconds=ago_s),
                            stats_json=json.dumps(stats) if stats is not None else None))


def case_plan_table():
    P, R, OP = (lambda i: OpenJob(i, False, True)), (lambda i: OpenJob(i, True, True)), (
        lambda i: OpenJob(i, False, False))
    rows = [
        # live, open jobs, swept recently -> enqueue, cancel
        (["a"], {}, set(), ["a"], []),
        (["a"], {}, {"a"}, [], []),
        (["a"], {"a": [P(1)]}, set(), [], []),
        (["a"], {"a": [P(1), P(2), P(3)]}, set(), [], [2, 3]),
        (["a"], {"a": [R(1), P(2), P(3)]}, set(), [], [2, 3]),
        (["a"], {"a": [OP(1), P(2)]}, set(), [], [2]),
        ([], {"z": [P(1), P(2)]}, set(), [], [2]),          # not live: still collapsed, never enqueued
        (["a", "b"], {"b": [P(5)]}, {"a"}, [], []),
    ]
    for live, open_jobs, recent, enq, cancel in rows:
        got = plan(live, open_jobs, recent)
        assert (got.enqueue, sorted(got.cancel)) == (enq, cancel), (live, open_jobs, recent, got)


async def case_restarts_leave_one_open_sweep_per_account():
    a, b = "sc_restart_a", "sc_restart_b"
    await _accounts(a, b)
    async with get_session() as s:
        op = Employee(display_name="sc_op")
        s.add(op)
        await s.flush()
        now = datetime.utcnow()
        for aid in (a, b):
            for k in range(5):   # five restarts' worth of the old boot seed
                s.add(ScheduledJob(account_id=aid, kind="scrape_chats", payload_json="{}", status="pending",
                                   run_at=now - timedelta(hours=10 - k)))
        s.add(ScheduledJob(account_id=a, kind="scrape_chats", payload_json='{"fan_ids": [7]}',
                           status="pending", run_at=now))
        s.add(ScheduledJob(account_id=b, kind="scrape_chats", payload_json="{}", status="pending",
                           run_at=now, created_by_employee_id=op.id))
    oldest_a = _open_sweeps(await _jobs(a))[0].id
    for _ in range(3):
        mod = importlib.reload(sweep_cadence)   # a restart: no process state survives
        await mod.tick()
    ja, jb = await _jobs(a), await _jobs(b)
    assert [j.id for j in _open_sweeps(ja)] == [oldest_a], [(j.id, j.status) for j in ja]
    assert sum(j.status == "cancelled" and j.last_error == sweep_cadence.DUP_REASON for j in ja) == 4, ja
    fan = [j for j in ja if j.payload_json != "{}"]
    assert len(fan) == 1 and fan[0].status == "pending", fan
    # b: the operator's sweep stays, every automation duplicate beside it goes.
    ob = _open_sweeps(jb)
    assert len(ob) == 1 and ob[0].created_by_employee_id is not None, [(j.id, j.status) for j in jb]
    assert len(jb) == 6, len(jb)   # nothing new enqueued while one is open


async def case_never_swept_gets_one_at_once_and_dead_or_off_get_none():
    live, off, dead, bare = "sc_new_live", "sc_new_off", "sc_new_dead", "sc_new_bare"
    await _accounts(live, off, dead)
    await _accounts(bare, session=False)
    await account_health.deactivate(off)
    await account_health.mark_session_dead(dead, "wrong_user")
    await sweep_cadence.tick()
    await sweep_cadence.tick()
    assert len(_open_sweeps(await _jobs(live))) == 1
    for aid in (off, dead, bare):
        assert await _jobs(aid) == [], aid


async def _parked(aid: str, *, last_error: str, ago_s: float = 60) -> None:
    """A `{}` sweep job parked 'error' with its retries spent."""
    async with get_session() as s:
        s.add(ScheduledJob(account_id=aid, kind="scrape_chats", payload_json="{}", status="error",
                           attempts=3, last_error=last_error,
                           run_at=datetime.utcnow() - timedelta(seconds=ago_s)))


async def case_cadence_anchors_on_the_last_finished_sweep():
    a, fan_failed, limit50, cancelled, interrupted, failed = (
        "sc_anchor_a", "sc_anchor_fan_failed", "sc_anchor_limit50", "sc_anchor_cancelled",
        "sc_anchor_interrupted", "sc_anchor_failed")
    await _accounts(a, fan_failed, limit50, cancelled, interrupted, failed)
    await _run(a, ago_s=3600, stats={"full_sweep": True, "chats_scanned": 3})
    await _run(fan_failed, ago_s=60, stats=None)                     # a failed fan_ids run
    await _run(limit50, ago_s=60, stats={"chats_scanned": 50})       # a rule's {"limit": 50}
    await _parked(cancelled, last_error=sweep_cadence.RESTART_CANCEL)  # restarts spent its retries
    async with get_session() as s:                                   # an orphan the heal closed
        s.add(AutomationRun(account_id=interrupted, kind="scrape_chats", status="error",
                            started_at=datetime.utcnow() - timedelta(minutes=5),
                            completed_at=datetime.utcnow(), error_text="interrupted (relay restart)"))
    await _parked(failed, last_error="OFAPIError('500')")            # a real error holds
    await sweep_cadence.tick()
    assert _open_sweeps(await _jobs(a)) == []
    for aid in (fan_failed, limit50, cancelled, interrupted):
        assert len(_open_sweeps(await _jobs(aid))) == 1, aid
    assert _open_sweeps(await _jobs(failed)) == []
    async with get_session() as s:
        run = (await s.execute(select(AutomationRun).where(AutomationRun.account_id == a))).scalar_one()
        run.completed_at = datetime.utcnow() - timedelta(seconds=sweep_cadence.SWEEP_EVERY_S + 60)
    await sweep_cadence.tick()
    assert len(_open_sweeps(await _jobs(a))) == 1


async def case_sweep_with_every_chat_failed_raises_not_full_sweep():
    import automation_executor as ax
    from automations import scrape_chats as sc

    chats = [11, 12]
    tried: list[int] = []

    class _Client:
        user_id = 1

        def list_chats(self, **_kw):
            return {"list": [{"withUser": {"id": c}} for c in chats], "hasMore": False}
    ok_ids: set[int] = set()

    gone_ids: set[int] = set()

    async def one_chat(_aid, _own, _client, chat_id, *_a, **_kw):
        tried.append(chat_id)
        if chat_id in gone_ids:
            raise sc.OFAPIError("404", response=type("R", (), {"status_code": 404})())
        if chat_id not in ok_ids:
            raise RuntimeError("boom")
        return 1, 1

    async def stamp(_aid, _fid, **_kw):
        return None
    real = (ax._make_client, sc._scrape_one_chat, sc._PAGE_SLEEP_S, sc._stamp_scrape_history)
    ax._make_client, sc._scrape_one_chat, sc._PAGE_SLEEP_S = (lambda _aid: _Client()), one_chat, 0
    sc._stamp_scrape_history = stamp
    try:
        try:
            await sc._automation_scrape_chats("sc_failed_sweep", {}, run_id=0)
            raise AssertionError("an all-failed {} sweep must raise")
        except RuntimeError as e:
            assert "0 of 2" in str(e), e
        out = await sc._automation_scrape_chats("sc_failed_sweep", {"fan_ids": [11, 12]}, run_id=0)
        assert out["chats_failed"] == 2 and "full_sweep" not in out, out
        ok_ids.add(12)
        out = await sc._automation_scrape_chats("sc_failed_sweep", {}, run_id=0)
        assert out["full_sweep"] is True and out["chats_scanned"] == 1, out
        chats[:], tried[:] = list(range(100, 140)), []   # 40 chats, every one failing
        try:
            await sc._automation_scrape_chats("sc_failed_sweep", {}, run_id=0)
            raise AssertionError("a failing {} sweep must raise")
        except RuntimeError as e:
            assert "5 failed of the first 5 of 40" in str(e), e
        assert len(tried) == sc._sweep_fail_fast() == 5, tried
        # 5 gone fans at the top, then good chats: a healthy sweep.
        chats[:], tried[:] = list(range(200, 210)), []
        gone_ids |= set(range(200, 205))
        ok_ids |= set(range(205, 210))
        out = await sc._automation_scrape_chats("sc_failed_sweep", {}, run_id=0)
        assert out["full_sweep"] is True and out["chats_scanned"] == 5 and out["chats_failed"] == 5, out
        # A small sidebar of only gone fans: nothing to scrape, still a sweep.
        chats[:] = [200, 201, 202]
        out = await sc._automation_scrape_chats("sc_failed_sweep", {}, run_id=0)
        assert out["full_sweep"] is True and out["chats_scanned"] == 0 and out["chats_failed"] == 3, out
    finally:
        ax._make_client, sc._scrape_one_chat, sc._PAGE_SLEEP_S, sc._stamp_scrape_history = real


_harness.run()
