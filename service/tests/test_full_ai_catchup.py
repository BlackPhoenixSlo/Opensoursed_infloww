#!/usr/bin/env python3
"""test_full_ai_catchup — Full AI Chat's waiting-chats catch-up (automations/full_ai_catchup.py).

OF's chat list faked (`ChatsOF`: `_of_fixtures.FakeOF` + `list_chats`, OF's 10-row pages) behind
`ax._make_client`, Jev and the Writers faked (`_full_ai_live_helpers.world`); the loop's sleep
swapped for a recorder. Temp DB only; no OF, no paid call.

  case_schedule_offsets            defaults: passes at 0, +5, +15, then every 15 min (offset_s / gap_s table); a
                                   custom `catchup_minutes` is followed; a missing / invalid one reads the defaults
  case_start_passes_now_then_sleeps   start: a pass at once, then 300, 600, 900, 900 s waits
  case_config_change_next_wait     a checkpoint saved while the loop waits sets the next wait (no restart); an
                                   after_live not starting at 0 delays the first pass
  case_unsaved_dm_saved_one_turn   his DM not in `messages`: saved, one-Fan scrape queued, one Turn job
                                   (no sooner than the scrape grace); the job replies once, row `sent`
  case_skips                       answered (row on the key) / she wrote last / a funnel walk owns him /
                                   8 days old: nothing queued, nothing saved for her chat
  case_unhealthy_creator_skipped   deactivated / Dead session: a skip, no OF read, no job; the loop goes on
  case_more_than_twenty_cap_40     45 waiting chats: 40 read, 40 queued in one pass (the sweep's 20 cap
                                   not applied)
  case_second_pass_no_double       two passes: one job; after his reply, a third pass queues none
  case_running_fan_skipped         a Fan whose job runs in this process (`full_ai_live._running`): not queued
  case_off_stops                   stop cancels the loop; a rule no longer live ends it after its pass
  case_boot_starts_live_only       relay start: only the Live Creator's loop starts; it waits BOOT_DELAY_S, then passes
  case_race_with_inbound_hook_one_send  catch-up and the inbound hook both queue one Fan (two jobs, both
                                   naming him for the per-Fan dispatch): run together, one Turn, one send

Run: ./venv/bin/python service/tests/test_full_ai_catchup.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

from _full_ai_fixtures import KIND, _msg, _rows, _seed, seed_live  # noqa: E402
from _full_ai_live_helpers import world  # noqa: E402
from _of_fixtures import FakeOF  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import full_ai_catchup as cu  # noqa: E402
from automations import full_ai_config  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AccountAiConfig, AiDecision, AutomationRule, FunnelState, MassRun, Message, ScheduledJob  # noqa: E402


class ChatsOF(FakeOF):
    """FakeOF with OF's chat list: `chats` in order, at most 10 rows a page (OF's cap)."""

    def __init__(self, chats: list[dict]):
        super().__init__()
        self.chats = chats
        self.pages: list[int] = []          # each list_chats offset

    def list_chats(self, *, limit=10, offset=0, **_kw) -> dict:
        self.pages.append(offset)
        rows = self.chats[offset:offset + min(limit, 10)]
        return {"list": rows, "hasMore": offset + len(rows) < len(self.chats)}


def _iso(at: datetime) -> str:
    return at.isoformat() + "+00:00"


def _chat(fan: int, mid: int, at: datetime, sender: int | str | None = None, text: str = "u there?") -> dict:
    return {"withUser": {"id": fan}, "unreadMessagesCount": 1,
            "lastMessage": {"id": mid, "fromUser": {"id": fan if sender is None else sender},
                            "text": text, "createdAt": _iso(at)}}


def _ago(minutes: float) -> datetime:
    return datetime.utcnow() - timedelta(minutes=minutes)


async def _jobs(aid: str, kind: str = KIND) -> list[ScheduledJob]:
    async with get_session() as s:
        return list((await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == kind, ScheduledJob.status == "pending")
            .order_by(ScheduledJob.id))).scalars())


async def _payloads(aid: str, kind: str = KIND) -> list[dict]:
    return [json.loads(j.payload_json) for j in await _jobs(aid, kind)]


async def _pass(aid: str, chats: list[dict]) -> tuple[dict, ChatsOF]:
    fake = ChatsOF(chats)
    with world(fake=fake):
        res = await cu.run_pass(aid)
    return res, fake


class Sleeps:
    """The loop's sleep: records each wait; the `n`-th call runs `then` (if set) and, unless it
    returns True, parks forever (the test stops the loop)."""

    def __init__(self, n: int, then=None):
        self.n, self.then, self.calls, self.hit = n, then, [], asyncio.Event()

    async def __call__(self, secs):
        self.calls.append(secs)
        if len(self.calls) >= self.n:
            go_on = await self.then() if self.then else False
            self.hit.set()
            if not go_on:
                await asyncio.Event().wait()


def case_schedule_offsets():
    assert cu.DEFAULT_SCHEDULE == cu.schedule(None) == cu.schedule(DEFAULTS) == ((0, 300, 900), 900)
    assert [cu.offset_s(i) for i in range(6)] == [0, 300, 900, 1800, 2700, 3600]
    assert [cu.gap_s(i) for i in range(5)] == [300, 600, 900, 900, 900]
    custom = cu.schedule({"catchup_minutes": {"after_live": [0, 2], "then_every": 60}})
    assert custom == ((0, 120), 3600), custom
    assert [cu.gap_s(i, custom) for i in range(3)] == [120, 3600, 3600]
    for bad in ({"after_live": [5, 0], "then_every": 25}, {"after_live": [0], "then_every": 1}, None, "x"):
        assert cu.schedule({"catchup_minutes": bad}) == cu.DEFAULT_SCHEDULE, bad   # a bad stored side never stalls


async def case_start_passes_now_then_sleeps():
    aid = "fa_cu_sched"
    await seed_live(aid)
    fake = ChatsOF([_chat(1101, 71101, _ago(30))])
    passes: list[int] = []
    real_pass, real_sleep = cu.run_pass, cu._sleep

    async def counting(a):
        passes.append(len(sleeps.calls))       # sleeps before this pass
        return await real_pass(a)
    sleeps = Sleeps(4)
    cu.run_pass, cu._sleep = counting, sleeps
    try:
        with world(fake=fake):
            task = cu.start(aid)
            await asyncio.wait_for(sleeps.hit.wait(), 30)
            cu.stop(aid)
            await asyncio.gather(task, return_exceptions=True)
    finally:
        cu.run_pass, cu._sleep = real_pass, real_sleep
    assert passes == [0, 1, 2, 3], passes            # the first pass before any wait
    assert sleeps.calls == [300, 600, 900, 900], sleeps.calls
    assert task.cancelled() and aid not in cu._tasks
    assert len(await _jobs(aid)) == 1                 # four passes, one Turn


async def _store_checkpoint(aid: str, catchup_minutes: dict) -> None:
    """The page's checkpoint write (`put_checkpoint`) with `catchup_minutes`, stored for `aid`."""
    async with get_session() as s:
        row = await s.get(AccountAiConfig, aid)
        if row is None:
            row = AccountAiConfig(account_id=aid)
            s.add(row)
        stored = json.loads(row.full_ai_config_json) if row.full_ai_config_json else None
        blob = full_ai_config.put_checkpoint(stored, {**DEFAULTS, "catchup_minutes": catchup_minutes},
                                             full_ai_config.merged(stored)["rev"])
        row.full_ai_config_json = json.dumps(blob)


async def case_config_change_next_wait():
    aid = "fa_cu_cfg"
    await seed_live(aid)
    real_sleep = cu._sleep
    calls: list[int] = []
    hit, change = asyncio.Event(), [{"after_live": [0, 5, 30], "then_every": 60}]

    async def sleep(secs):
        calls.append(secs)
        if change:                             # saved while the loop waits after its first pass
            await _store_checkpoint(aid, change.pop())
        if len(calls) >= 3:
            hit.set()
            await asyncio.Event().wait()
    cu._sleep = sleep
    try:
        with world(fake=ChatsOF([])):
            task = cu.start(aid)
            await asyncio.wait_for(hit.wait(), 30)
            cu.stop(aid)
            await asyncio.gather(task, return_exceptions=True)
        assert calls == [300, 1500, 3600], calls    # old first wait; then 30 - 5 min, then every 60 min
        # after_live not starting at 0: the first pass waits it (after the boot delay).
        await _store_checkpoint(aid, {"after_live": [2, 7], "then_every": 25})
        calls.clear()
        hit.clear()
        with world(fake=ChatsOF([])):
            task = cu.start(aid, 60)
            await asyncio.wait_for(hit.wait(), 30)
            cu.stop(aid)
            await asyncio.gather(task, return_exceptions=True)
        assert calls == [60, 120, 300], calls
    finally:
        cu._sleep = real_sleep
        await _store_checkpoint(aid, DEFAULTS["catchup_minutes"])    # boot's case runs every Live Creator


async def case_unsaved_dm_saved_one_turn():
    aid, fan, mid = "fa_cu_save", 1201, 71201
    rid = await seed_live(aid)
    t0 = datetime.utcnow()
    res, fake = await _pass(aid, [_chat(fan, mid, _ago(45), text="hello?? anyone")])
    assert res == {"chats": 1, "waiting": 1, "claimed": 1, "saved": 1, "swept": 1, "queued": 1}, res
    async with get_session() as s:
        m = await s.get(Message, (aid, fan, mid))
    assert m is not None and m.direction == "in" and m.body == "hello?? anyone", m
    (job,) = await _jobs(aid)
    assert json.loads(job.payload_json) == {"only_fan_ids": [fan], "anchor": mid, "_rule_id": rid, "tries": 0}
    assert job.run_at >= t0 + timedelta(seconds=cu.SCRAPE_GRACE_S), job.run_at   # the scrape first
    assert await _payloads(aid, "scrape_fan") == [{"fan_ids": [fan], "source": cu.SOURCE}]
    assert fake.sent == [] and fake.read == []        # sends nothing, marks nothing read
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.id == job.id)
                        .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
    with world() as (of, *_):
        assert (await run_once(aid, KIND))["status"] == "ok"
    (row,) = await _rows(aid)
    assert (row.status, row.trigger_key) == ("sent", str(mid)), row
    assert of.sent


async def case_skips():
    aid = "fa_cu_skip"
    await seed_live(aid)
    await _msg(aid, 1301, 71301, "in", "hey", _ago(20))                       # answered: a row on its key
    async with get_session() as s:
        s.add(AiDecision(account_id=aid, fan_id=1301, mode="live", trigger_kind="inbound", trigger_key="71301",
                         route="chat", heat=1, route_row="chat", question_version="x", status="sent",
                         created_at=datetime.utcnow()))
        run = MassRun(account_id=aid)                                         # a funnel walk owns 1303
        s.add(run)
        await s.flush()
        s.add(FunnelState(mass_run_id=run.id, fan_id=1303, status="pending"))
    chats = [_chat(1301, 71301, _ago(20)),
             _chat(1302, 71302, _ago(20), sender=aid),                        # she wrote last
             _chat(1303, 71303, _ago(20)),
             _chat(1304, 71304, datetime.utcnow() - timedelta(days=8))]       # too old
    res, _ = await _pass(aid, chats)
    assert (res["chats"], res["waiting"], res["queued"]) == (4, 2, 0), res
    assert await _jobs(aid) == []
    async with get_session() as s:
        saved = {m for (m,) in (await s.execute(select(Message.message_id).where(Message.account_id == aid))).all()}
    assert 71302 not in saved and 71304 not in saved, saved


async def case_unhealthy_creator_skipped():
    """A deactivated or Dead-session Creator left on Live: the pass skips before any OF read (the
    dispatcher would never run its jobs), and returns a skip, not None, so the loop keeps its schedule."""
    import account_health
    for aid, sick, want in (("fa_cu_deact", account_health.deactivate, "account_deactivated"),
                            ("fa_cu_dead", lambda a: account_health.mark_session_dead(a, "wrong_user"),
                             "session_dead")):
        await seed_live(aid)
        await sick(aid)
        res, fake = await _pass(aid, [_chat(1501, 71501, _ago(20))])
        assert res == {"skipped": want}, res
        assert fake.pages == [] and await _jobs(aid) == [], (fake.pages, await _jobs(aid))


async def case_more_than_twenty_cap_40():
    aid = "fa_cu_many"
    await seed_live(aid)
    chats = [_chat(2000 + i, 72000 + i, _ago(10 + i)) for i in range(45)]
    res, fake = await _pass(aid, chats)
    assert (res["chats"], res["waiting"], res["saved"], res["queued"]) == (40, 40, 40, 40), res
    assert sorted(p["only_fan_ids"][0] for p in await _payloads(aid)) == list(range(2000, 2040))
    assert fake.pages == list(range(0, 40, 10)), fake.pages         # 4 paged reads, none past 40


async def case_second_pass_no_double():
    aid, fan, mid = "fa_cu_twice", 1401, 71401
    await seed_live(aid)
    await _msg(aid, fan, mid, "in", "hey you", _ago(30))                     # saved, socket date unset
    chats = [_chat(fan, mid, _ago(30))]
    assert (await _pass(aid, chats))[0]["queued"] == 1
    assert (await _pass(aid, chats))[0]["queued"] == 0
    (job,) = await _jobs(aid)
    assert job.run_at <= datetime.utcnow(), job.run_at                         # already saved: no grace
    assert await _payloads(aid, "scrape_fan") == []
    with world():
        assert (await run_once(aid, KIND))["status"] == "ok"
    assert len(await _rows(aid)) == 1
    async with get_session() as s:                                             # his cooldown over
        from db.models import Fan
        await s.execute(update(Fan).where(Fan.account_id == aid).values(automation_paused_until=None))
    res, _ = await _pass(aid, chats)                                           # OF's list not caught up yet
    assert res["queued"] == 0 and await _jobs(aid) == [], res
    assert len(await _rows(aid)) == 1


async def case_running_fan_skipped():
    from automations import full_ai_live
    aid, fan, mid = "fa_cu_running", 1701, 71701
    await seed_live(aid)
    await _msg(aid, fan, mid, "in", "you there", _ago(30))
    full_ai_live._running.add((aid, fan))                                      # his Turn runs here now
    try:
        assert (await _pass(aid, [_chat(fan, mid, _ago(30))]))[0]["queued"] == 0
    finally:
        full_ai_live._running.discard((aid, fan))
    assert (await _pass(aid, [_chat(fan, mid, _ago(30))]))[0]["queued"] == 1


async def case_off_stops():
    aid = "fa_cu_off"
    rid = await seed_live(aid)
    real_sleep = cu._sleep
    try:
        cu._sleep = Sleeps(1)
        with world(fake=ChatsOF([])):
            task = cu.start(aid)
            await asyncio.wait_for(cu._sleep.hit.wait(), 30)
            cu.stop(aid)                                                       # Mode Off
            await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and aid not in cu._tasks

        async def rule_off():
            async with get_session() as s:
                await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(is_enabled=False))
            return True
        cu._sleep = Sleeps(1, then=rule_off)
        fake = ChatsOF([])
        with world(fake=fake):
            task = cu.start(aid)
            await asyncio.wait_for(task, 30)                                   # ends by itself
        assert not task.cancelled() and task.exception() is None and aid not in cu._tasks
        assert cu._sleep.calls == [300] and fake.pages == [0], (cu._sleep.calls, fake.pages)
    finally:
        cu._sleep = real_sleep


async def case_socket_reconnect_restarts():
    """A socket drop: a running schedule restarts (first pass after RECONNECT_DELAY_S); none running: nothing."""
    aid = "fa_cu_recon"
    await seed_live(aid)
    real_sleep = cu._sleep
    try:
        cu.reconnected(aid)                                                    # no schedule: not started
        assert aid not in cu._tasks
        cu._sleep = Sleeps(1)
        fake = ChatsOF([])
        with world(fake=fake):
            first = cu.start(aid)
            await asyncio.wait_for(cu._sleep.hit.wait(), 30)                   # pass 1 done, waiting 5 min
            cu._sleep = Sleeps(2)
            import full_ai_catchup_wiring  # noqa: F401 — registers the hook
            import relay_hooks
            relay_hooks.fire_socket_reconnected(aid)
            task = cu._tasks[aid]
            await asyncio.wait_for(cu._sleep.hit.wait(), 30)
            cu.stop(aid)
            await asyncio.gather(first, task, return_exceptions=True)
        assert first.cancelled() and task is not first
        assert cu._sleep.calls == [cu.RECONNECT_DELAY_S, 300], cu._sleep.calls
        assert fake.pages == [0, 0], fake.pages                                # one pass each
    finally:
        cu._sleep = real_sleep


async def case_boot_starts_live_only():
    live, shadow = "fa_cu_boot_live", "fa_cu_boot_shadow"
    await seed_live(live)
    await _seed(shadow, rule=True, gate=False)                                 # enabled, no Mode live
    for aid in list(cu._tasks):
        cu.stop(aid)
    real_sleep, real_pass = cu._sleep, cu.run_pass
    log: list = []                                                             # (sleep | pass, aid, secs)

    async def sleep(secs):
        log.append(("sleep", asyncio.current_task().get_name().split(":", 1)[1], secs))
        if secs != cu.BOOT_DELAY_S:                                            # each loop parks after its pass
            await asyncio.Event().wait()

    async def counting(a):
        log.append(("pass", a, None))
        return await real_pass(a)
    cu._sleep, cu.run_pass = sleep, counting
    fake = ChatsOF([_chat(1501, 71501, _ago(30))])
    try:
        with world(fake=fake):
            await cu.boot()                                                    # earlier cases' Creators stay Live
            assert live in cu._tasks and shadow not in cu._tasks, set(cu._tasks)
            tasks = list(cu._tasks.values())
            for _ in range(600):                                               # every loop's first pass done
                if sum(e[2] == 300 for e in log) >= len(tasks):
                    break
                await asyncio.sleep(0.05)
            for aid in list(cu._tasks):
                cu.stop(aid)
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        cu._sleep, cu.run_pass = real_sleep, real_pass
    for t in tasks:                                                            # each loop: wait, pass, park
        a = t.get_name().split(":", 1)[1]
        assert [e for e in log if e[1] == a] == [("sleep", a, cu.BOOT_DELAY_S), ("pass", a, None),
                                                 ("sleep", a, 300)], log
    assert [p["anchor"] for p in await _payloads(live)] == [71501]
    assert await _jobs(shadow) == []


async def case_race_with_inbound_hook_one_send():
    """The catch-up and the inbound hook queue the same Fan at once (both past the pending-job check
    before either job lands): two jobs, both naming him (`only_fan_ids`, the per-Fan dispatch's
    `JOB_FAN`); run together and then the rest: one Turn, one send."""
    import webhook_dispatch as wd
    from job_queue import JOB_FAN
    aid, fan, mid = "fa_cu_race", 1601, 71601
    await seed_live(aid)
    await _msg(aid, fan, mid, "in", "hey are you there", _ago(30))
    real = wd._imminent_pending_job

    async def blind(*_a, **_kw):                                               # the race window
        await asyncio.sleep(0)
        return None
    wd._imminent_pending_job = blind
    try:
        with world(fake=ChatsOF([_chat(fan, mid, _ago(30))])):
            res, _ = await asyncio.gather(cu.run_pass(aid), wd.on_inbound_message(aid, fan, mid))
    finally:
        wd._imminent_pending_job = real
    assert res["queued"] == 1, res
    jobs = await _jobs(aid)
    assert len(jobs) == 2 and all(json.loads(j.payload_json)["only_fan_ids"] == [fan] for j in jobs), jobs
    async with get_session() as s:
        assert {f for (f,) in (await s.execute(select(JOB_FAN).where(
            ScheduledJob.id.in_([j.id for j in jobs])))).all()} == {fan}

    async def due_now():
        async with get_session() as s:
            await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid, ScheduledJob.kind == KIND,
                                                       ScheduledJob.status == "pending")
                            .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
    with world() as (of, *_):
        await due_now()
        await asyncio.gather(run_once(aid, KIND, fan=fan), run_once(aid, KIND, fan=fan))
        sent = list(of.sent)
        for _ in range(5):                                                     # a busy job's retries
            if not await _jobs(aid):
                break
            await due_now()
            await run_once(aid, KIND, fan=fan)
        assert await _jobs(aid) == [], "jobs left"
        assert sent and of.sent == sent, (sent, of.sent)                      # nothing after the one Turn
    (row,) = await _rows(aid)
    assert (row.status, row.trigger_key) == ("sent", str(mid)), row


_harness.run()
