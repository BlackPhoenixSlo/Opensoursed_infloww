#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from _full_ai_fixtures import KIND  # noqa: E402
from _full_ai_live_fixtures import (  # noqa: E402
    LiveOF, clear_pause, dm, leases, live_rows, out_rows, paused, payload, seed_live, world,
)
import automation_executor as ax  # noqa: E402
import run_slot  # noqa: E402
from automations import full_ai_live  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, ScheduledJob, SkipList  # noqa: E402

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")


def _kill_at(n: int, exc: BaseException):
    def before(call: int, _text: str) -> None:
        if call == n:
            raise exc
    return before


async def _run(aid, fan, mid, rid, **kw):
    with world(**kw) as w:
        try:
            res = await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
        except BaseException as e:  # noqa: BLE001 — the case reads it
            res = e
    return res, w


async def _one(aid):
    (row,) = await live_rows(aid)
    return row


def _n(row) -> int:
    return len(json.loads(row.reply_json)["parts"])


async def case_killed_on_bubble_2():
    aid, fan, mid = "fa_st_kill2", 601, 8101
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(_kill_at(2, asyncio.CancelledError())))
    assert isinstance(res, asyncio.CancelledError), res
    row = await _one(aid)
    assert (w.of.calls, len(w.of.sent), row.status) == (2, 1, "sending"), (w.of.calls, row.status)
    assert _n(row) >= 3, _n(row)
    assert len(await out_rows(aid, fan)) == 1 and await paused(aid, fan) is not None
    await clear_pause(aid, fan)
    assert await ax.acquire_fan_lease(aid, fan, KIND, ttl_s=900)
    res, w = await _run(aid, fan, mid, rid)
    assert res == {"skipped": "no_turn"}, res
    row = await _one(aid)
    assert (w.of.calls, row.status, len(await out_rows(aid, fan))) == (0, "unconfirmed", 1)
    assert await leases(aid) == []
    res, w = await _run(aid, fan, mid, rid)
    assert res == {"skipped": "no_turn"} and w.of.calls == 0, res
    await clear_pause(aid, fan)
    await dm(aid, fan, mid + 1, "u there?", ago_s=0)
    res, w = await _run(aid, fan, mid + 1, rid)
    assert res["row_status"] == "sent", res
    old, new = await live_rows(aid)
    assert (old.status, new.status, new.trigger_key) == ("unconfirmed", "sent", str(mid + 1))
    assert w.of.calls == res["sent"] == _n(new) and len(await out_rows(aid, fan)) == 1 + _n(new)


async def case_killed_after_of_took_bubble_1():
    aid, fan, mid = "fa_st_kill1", 610, 8151
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(after=_kill_at(1, asyncio.CancelledError())))
    assert isinstance(res, asyncio.CancelledError), res
    row = await _one(aid)
    assert (w.of.calls, len(w.of.sent), row.status, await out_rows(aid, fan)) == (1, 1, "sending", []), row.status
    assert await ax.acquire_fan_lease(aid, fan, KIND, ttl_s=900)
    res, w = await _run(aid, fan, mid, rid)
    row = await _one(aid)
    assert (res, w.of.calls, row.status, await out_rows(aid, fan)) == ({"skipped": "no_turn"}, 0, "unconfirmed", [])
    await clear_pause(aid, fan)
    await dm(aid, fan, mid + 1, "hello??", ago_s=0)
    res, w = await _run(aid, fan, mid + 1, rid)
    old, new = await live_rows(aid)
    assert (old.status, new.status, new.trigger_key, res["row_status"]) == ("unconfirmed", "sent", str(mid + 1), "sent")
    assert w.of.calls == _n(new) == len(await out_rows(aid, fan))


async def case_dies_before_any_send():
    aid, fan, mid = "fa_st_kill0", 602, 8201
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    real = full_ai_live.hold_with_typing

    async def die(*_a, **_k):
        raise asyncio.CancelledError()
    full_ai_live.hold_with_typing = die
    try:
        res, w = await _run(aid, fan, mid, rid)
    finally:
        full_ai_live.hold_with_typing = real
    assert isinstance(res, asyncio.CancelledError), res
    assert (w.of.calls, await live_rows(aid), await out_rows(aid, fan)) == (0, [], [])
    assert await ax.acquire_fan_lease(aid, fan, KIND, ttl_s=900)
    res, w = await _run(aid, fan, mid, rid)
    row = await _one(aid)
    assert (res["row_status"], row.status, w.of.calls) == ("sent", "sent", _n(row)), res
    assert len(await out_rows(aid, fan)) == _n(row) >= 2 and await leases(aid) == []


async def case_first_bubble_hold_releases_turn():
    from send_ops import SendRefused

    aid, fan, mid = "fa_st_hold", 621, 9401
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    refusal = SendRefused(409, "cell_held", why="carve")
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(_kill_at(1, refusal)))
    assert res is refusal and not w.of.sent, res
    assert await live_rows(aid) == [] and await leases(aid) == []
    res, w = await _run(aid, fan, mid, rid)
    assert res["row_status"] == "sent" and w.of.sent, res


async def case_two_runs_one_turn_key():
    aid, fan, mid = "fa_st_race", 603, 8301
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    real = full_ai_live.load_typing_wpm

    async def other_run_first(account_id):
        async with get_session() as s:
            await s.execute(sqlite_insert(AiDecision).values(
                account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=str(mid),
                route="chat", heat=0, route_row="r", question_version="q",
                status="sending", reply_json="{}"))
        return await real(account_id)
    full_ai_live.load_typing_wpm = other_run_first
    try:
        res, w = await _run(aid, fan, mid, rid)
    finally:
        full_ai_live.load_typing_wpm = real
    assert res == {"skipped": "taken"}, res
    row = await _one(aid)
    assert (w.of.calls, row.status, row.reply_json, w.turns, w.released) == (0, "sending", "{}", 1, 1)
    assert await out_rows(aid, fan) == [] and await leases(aid) == []


async def case_slot_lost_bubble_1():
    aid, fan, mid = "fa_st_slot1", 604, 8401
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, slot_lost=lambda n: n == 1)
    assert isinstance(res, run_slot.SlotLost), res
    assert (w.of.calls, await live_rows(aid), await out_rows(aid, fan)) == (0, [], [])
    assert await leases(aid) == [] and await paused(aid, fan) is None
    res, w = await _run(aid, fan, mid, rid)
    row = await _one(aid)
    n = _n(row)
    assert (res["row_status"], row.status, w.of.calls, len(await out_rows(aid, fan))) == ("sent", "sent", n, n)


async def case_slot_lost_bubble_2():
    aid, fan, mid = "fa_st_slot2", 605, 8501
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, slot_lost=lambda n: n == 2)
    assert isinstance(res, run_slot.SlotLost), res
    row = await _one(aid)
    cut = json.loads(row.reply_json)["cut"]
    assert (w.of.calls, row.status, cut["check"], cut["index"]) == (1, "sent", "slot_lost", 1), (row.status, cut)
    assert len(await out_rows(aid, fan)) == 1 and await paused(aid, fan) is not None
    assert await leases(aid) == []
    await clear_pause(aid, fan)
    res, w = await _run(aid, fan, mid, rid)
    assert res == {"skipped": "no_turn"} and w.of.calls == 0, res
    assert (await _one(aid)).status == "sent" and len(await out_rows(aid, fan)) == 1


async def case_send_error():
    aid, fan, mid = "fa_st_err1", 606, 8601
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(_kill_at(1, RuntimeError("HTTP 500 boom"))))
    row = await _one(aid)
    cut = json.loads(row.reply_json)["cut"]
    assert (res["row_status"], row.status, w.of.calls, cut["check"]) == ("failed", "failed", 1, "send_error")
    assert await out_rows(aid, fan) == [] and await leases(aid) == [] and await paused(aid, fan) is None
    aid, fan, mid = "fa_st_err2", 607, 8701
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(_kill_at(2, RuntimeError("HTTP 500 boom"))))
    row = await _one(aid)
    cut = json.loads(row.reply_json)["cut"]
    assert (row.status, w.of.calls, cut["check"], cut["index"]) == ("sent", 2, "send_error", 1), (row.status, cut)
    assert len(await out_rows(aid, fan)) == 1 and await leases(aid) == []


async def case_unreachable_fan():
    aid, fan, mid = "fa_st_gone", 611, 8751
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid,
                        of=LiveOF(_kill_at(1, RuntimeError("400 Cannot send message to this user"))))
    row = await _one(aid)
    assert (row.status, w.of.calls, await out_rows(aid, fan)) == ("failed", 1, []), row.status
    async with get_session() as s:
        skip = (await s.execute(select(SkipList.reason).where(
            SkipList.account_id == aid, SkipList.fan_id == fan))).scalar_one_or_none()
    until = await paused(aid, fan)
    assert skip == "unreachable" and until is not None and until > datetime.utcnow() + timedelta(days=6), (skip, until)


class NoIdOF(LiveOF):
    def send_message(self, chat_id, text, **kw) -> dict:
        self.calls += 1
        return {}


async def case_no_id_first_bubble():
    aid, fan, mid = "fa_st_noid", 608, 8801
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    probed, real = [], full_ai_live.quarantine_if_undeliverable

    async def probe(client, account_id, fan_id, **kw):
        probed.append((account_id, fan_id))
    full_ai_live.quarantine_if_undeliverable = probe
    try:
        res, w = await _run(aid, fan, mid, rid, of=NoIdOF())
    finally:
        full_ai_live.quarantine_if_undeliverable = real
    row = await _one(aid)
    assert (row.status, w.of.calls, probed) == ("failed", 1, [(aid, fan)]), (row.status, probed)
    assert json.loads(row.reply_json)["cut"]["reason"] == "no_id" and await out_rows(aid, fan) == []


async def case_offer_column_survives_record():
    aid, fan, mid = "fa_st_offer", 609, 8901
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    seen, real = [], full_ai_live._reserve

    async def reserve_then_settle(row, anchor):
        got = await real(row, anchor)
        seen.append((row, got))
        async with get_session() as s:
            await s.execute(update(AiDecision).where(AiDecision.id == got).values(outcome="bought", jev_ms=4242))
        return got
    full_ai_live._reserve = reserve_then_settle
    try:
        res, w = await _run(aid, fan, mid, rid)
    finally:
        full_ai_live._reserve = real
    row = await _one(aid)
    ((rowdict, got),) = seen
    n = _n(row)
    assert (row.status, row.outcome, w.of.calls, len(await out_rows(aid, fan))) == ("sent", "bought", n, n), \
        (row.status, row.outcome, w.of.calls, n)
    assert row.jev_ms == 4242 != rowdict["jev_ms"], (row.jev_ms, rowdict["jev_ms"])
    assert rowdict["id"] == got == row.id == res["row_id"], (rowdict.get("id"), got, row.id)


async def case_drain_waits_for_a_reserved_turn():
    aid, fan, mid = "fa_st_drain", 612, 9001
    rid = await seed_live(aid, {"typing_sign": True})
    await dm(aid, fan, mid)
    holds, in_hold = [], asyncio.Event()
    real_hold, real_wpm = full_ai_live.hold_with_typing, full_ai_live.load_typing_wpm

    async def hold(_aid, _fan, seconds, **kw):
        holds.append(seconds)
        if len(holds) == 1:
            return
        if len(holds) == 2:
            in_hold.set()
        await real_hold(_aid, _fan, seconds, **kw)

    async def wpm(_aid):
        return 1
    full_ai_live.hold_with_typing, full_ai_live.load_typing_wpm = hold, wpm
    try:
        with world() as w:
            task = asyncio.create_task(full_ai_live.run(aid, payload(fan, mid, rid), run_id=0))
            await asyncio.wait_for(in_hold.wait(), 10)
            assert w.of.calls == 1 and task in ax._sends_open, w.of.calls
            out = await ax.drain(timeout_s=10)
            res = await task
    finally:
        full_ai_live.hold_with_typing, full_ai_live.load_typing_wpm = real_hold, real_wpm
        ax._draining = False
    assert (out["waited"], out["left"]) == (1, 0) and out["s"] < 5, out
    row = await _one(aid)
    n = _n(row)
    assert n >= 3 and all("message_id" in p for p in json.loads(row.reply_json)["parts"]), row.reply_json
    assert (res["row_status"], row.status, w.of.calls, len(await out_rows(aid, fan))) == ("sent", "sent", n, n)
    assert holds[0] > 0 and holds[1] > 5 and holds[2:] == [0] * (n - 2), holds
    assert task not in ax._sends_open and await leases(aid) == []


async def case_draining_before_the_reserve():
    aid, fan, mid = "fa_st_drain0", 613, 9101
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    pl = {**payload(fan, mid, rid), "tries": 1}
    job_id = await ax.enqueue_job(aid, KIND, payload=pl, run_at=datetime.utcnow() - timedelta(seconds=1))
    ax._draining = True
    try:
        with world() as w:
            res = await ax.run_once(aid, KIND)
    finally:
        ax._draining = False
    assert (res["status"], res["skipped"], res["job_id"]) == ("ok", "draining", job_id), res
    assert (w.of.calls, w.turns, w.released) == (0, 1, 1), (w.of.calls, w.turns, w.released)
    assert await live_rows(aid) == [] and await out_rows(aid, fan) == [] and await leases(aid) == []
    async with get_session() as s:
        old, new = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == KIND).order_by(ScheduledJob.id))).scalars()
    now = datetime.utcnow()
    assert (old.id, old.status, new.status, new.attempts or 0) == (job_id, "done", "pending", 0), (old.status, new.status)
    assert json.loads(new.payload_json) == pl, new.payload_json
    assert now + timedelta(seconds=15) < new.run_at <= now + timedelta(seconds=21), new.run_at
    async with get_session() as s:
        await s.execute(update(ScheduledJob).where(ScheduledJob.id == new.id)
                        .values(run_at=now - timedelta(seconds=1)))
    with world() as w:
        res = await ax.run_once(aid, KIND)
    row = await _one(aid)
    assert (res["status"], res["row_status"], row.status, w.of.calls) == ("ok", "sent", "sent", _n(row)), res


async def case_drain_slot_released_on_raise_and_cancel():
    me = asyncio.current_task()
    aid, fan, mid = "fa_st_drain_err", 614, 9201
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    held, real = [], full_ai_live._reserve

    async def reserve_then_fail(row, anchor):
        await real(row, anchor)
        held.append(me in ax._sends_open)
        raise RuntimeError("db gone")
    full_ai_live._reserve = reserve_then_fail
    try:
        res, w = await _run(aid, fan, mid, rid)
    finally:
        full_ai_live._reserve = real
    assert isinstance(res, RuntimeError) and (held, w.of.calls) == ([True], 0), (res, held)
    assert me not in ax._sends_open
    aid, fan, mid = "fa_st_drain_cxl", 615, 9301
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(after=_kill_at(1, asyncio.CancelledError())))
    assert isinstance(res, asyncio.CancelledError) and w.of.calls == 1, res
    assert me not in ax._sends_open
    try:
        out = await ax.drain(timeout_s=5)
    finally:
        ax._draining = False
    assert (out["waited"], out["left"]) == (0, 0) and out["s"] < 1, out


async def case_restore_parked_anchor_cannot_enqueue_or_load():
    from unittest.mock import patch
    import run_decide

    aid, fan, mid = "fa_st_restore", 634, 9111
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    await ax.enqueue_job(aid, KIND, payload=payload(fan, mid, rid))
    await ax.park_restore([aid], datetime.utcnow())
    async with get_session() as s:
        assert (await s.scalar(select(ScheduledJob.last_error).where(
            ScheduledJob.account_id == aid))) == run_decide.RESTORE_REASON
    with patch.dict(os.environ, {"OI_CELL_MAP": "/nonexistent/placement.json"}), world() as w:
        turn = await full_ai_live.load(aid, fan, w.of)
        caught_up = await full_ai_live.catchup_queue(
            aid, [fan], max_age_s=600, cap=1, late=set(), not_before=datetime.utcnow())
        assert (turn is None, caught_up) == (True, {"swept": 0, "queued": 0})
        assert not await full_ai_live.enqueue(aid, fan, mid, rid)
        await dm(aid, fan, mid + 1, "new inbound", ago_s=0)
        assert await full_ai_live.enqueue(aid, fan, mid + 1, rid)


_harness.run()
