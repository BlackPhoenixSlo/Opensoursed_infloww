#!/usr/bin/env python3
"""test_full_ai_live_state — never double-send (04a ticket 65, automations/full_ai_live.py).

OF faked (`LiveOF` behind `ax._make_client`), Jev + Writers faked, temp DB. Every case asserts the
FakeOF call count, the row's `status` and the outbound `messages` rows of kind full_ai_chat.

  case_killed_on_bubble_2            CancelledError inside send 2: 1 bubble on OF, row `sending`;
                                     rerun (lease left as a hard crash leaves it): nothing sent,
                                     `unconfirmed`, lease gone; a fresh job on the Anchor sends
                                     nothing; his next DM is a new Turn that sends
  case_killed_after_of_took_bubble_1 OF took bubble 1, the run dies before its messages row: row
                                     `sending`, no messages row; rerun: nothing sent (the row is the
                                     only guard), `unconfirmed`; his next DM is a new Turn
  case_dies_before_any_send          killed in bubble 1's typing hold: no row; rerun sends once
  case_two_runs_one_turn_key         row pre-inserted `sending` after load: nothing sent, rate turn
                                     given back, the other run's row untouched
  case_slot_lost_bubble_1            SlotLost on rate turn 1: no row, no OF call, raised; retry sends once
  case_slot_lost_bubble_2            SlotLost on rate turn 2: `sent`, cut slot_lost, raised; retry nothing
  case_send_error                    bubble 1 raises: `failed`, lease gone, no cooldown;
                                     bubble 2 raises: `sent`, cut send_error
  case_unreachable_fan               "Cannot send message to this user": skip_list + 7-day pause
  case_no_id_first_bubble            OF answers no id: `failed`, quarantine probed once
  case_offer_column_survives_record  `outcome` / `jev_ms` set between reserve and record survive;
                                     row["id"] is the reserved row's id

Run: ./venv/bin/python service/tests/test_full_ai_live_state.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

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
from db.models import AiDecision, SkipList  # noqa: E402

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")


def _kill_at(n: int, exc: BaseException):
    def before(call: int, _text: str) -> None:
        if call == n:
            raise exc
    return before


async def _run(aid, fan, mid, rid, **kw):
    """One job run in its own world: (result or the exception, World)."""
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
    """Bubbles the row's reply has (the reply chain decides: 2-4 for these lines)."""
    return len(json.loads(row.reply_json)["parts"])


async def case_killed_on_bubble_2():
    aid, fan, mid = "fa_st_kill2", 601, 8101
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(_kill_at(2, asyncio.CancelledError())))
    assert isinstance(res, asyncio.CancelledError), res
    row = await _one(aid)
    assert (w.of.calls, len(w.of.sent), row.status) == (2, 1, "sending"), (w.of.calls, row.status)
    assert _n(row) >= 3, _n(row)            # killed on bubble 2 of >= 3
    assert len(await out_rows(aid, fan)) == 1 and await paused(aid, fan) is not None   # a bubble landed: rest
    await clear_pause(aid, fan)                                      # a hard crash runs no finally:
    assert await ax.acquire_fan_lease(aid, fan, KIND, ttl_s=900)    # no rest, its lease left
    res, w = await _run(aid, fan, mid, rid)
    assert res == {"skipped": "no_turn"}, res
    row = await _one(aid)
    assert (w.of.calls, row.status, len(await out_rows(aid, fan))) == (0, "unconfirmed", 1)
    assert await leases(aid) == []
    # A fresh job on the same Anchor: still nothing.
    res, w = await _run(aid, fan, mid, rid)
    assert res == {"skipped": "no_turn"} and w.of.calls == 0, res
    # His next DM is a new Turn that sends.
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


async def case_two_runs_one_turn_key():
    aid, fan, mid = "fa_st_race", 603, 8301
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    real = full_ai_live.load_typing_wpm

    async def other_run_first(account_id):     # after load, before the reserve
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
    res, w = await _run(aid, fan, mid, rid)          # the executor's retry
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
        async with get_session() as s:      # e.g. settle_pull lands between reserve and record
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
    assert row.jev_ms == 4242 != rowdict["jev_ms"], (row.jev_ms, rowdict["jev_ms"])   # a row-dict column too
    assert rowdict["id"] == got == row.id == res["row_id"], (rowdict.get("id"), got, row.id)


_harness.run()
