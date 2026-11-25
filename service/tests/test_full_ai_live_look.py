#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402

from _full_ai_fixtures import _msg  # noqa: E402
from _full_ai_live_fixtures import (  # noqa: E402
    LiveOF, dm, leases, live_rows, out_rows, payload, seed_live, world,
)
import run_slot  # noqa: E402
from automations import full_ai_live, full_ai_look, full_ai_test  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")
OFFER_COLS = ("offer_price_cents", "offer_list_cents", "offer_media_json", "offer_item_ref")
PICK = Pick(ref=711, media=(711, 712), previews=(701,), price_cents=1500, list_cents=1500,
            subject="any", format="photo", lane="paid", facts={})


@contextlib.contextmanager
def _patched(obj, name, value):
    real = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield real
    finally:
        setattr(obj, name, real)


@contextlib.contextmanager
def _checks(*extra: tuple[int, tuple]):
    saved = list(full_ai_look.LAST_LOOK)
    for at, entry in extra:
        full_ai_look.LAST_LOOK.insert(at, entry)
    try:
        yield
    finally:
        full_ai_look.LAST_LOOK[:] = saved


@contextlib.contextmanager
def _with_pick(only: bool = False):
    real = full_ai_test.send

    def send(row, parts, pick=None, **kw):
        return real(row, parts[-1:] if only else parts, pick or PICK, **kw)
    with _patched(full_ai_live.full_ai_test, "send", send):
        yield


async def _run(aid, fan, mid, rid, **kw):
    with world(**kw) as w:
        res = await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
    return res, w


def _reply(row) -> dict:
    return json.loads(row.reply_json)


def _at(name: str) -> int:
    return [n for n, _l, _c in full_ai_look.LAST_LOOK].index(name)


async def case_last_look_order():
    names = ["off_switch", "fans_list", "who_owns", "human_yield", "overtaken", "offer_valid"]
    assert [n for n, _l, _c in full_ai_look.LAST_LOOK] == names
    aid, fan, mid = "fa_lk_order", 701, 9101
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    called = []

    def first(look):
        called.append(("first", look.index))
        return "first_wins" if look.index == 0 else None

    def never(look):
        called.append(("overtaken", look.index))
        return "overtaken"
    with _checks((0, ("first", None, first))):
        full_ai_look.LAST_LOOK[_at("overtaken")] = ("overtaken", None, never)
        res, w = await _run(aid, fan, mid, rid)
    assert [n for n, _l, _c in full_ai_look.LAST_LOOK] == names
    assert await live_rows(aid) == []
    assert res == {"skipped": "overtaken:overtaken"}, res
    assert called == [("first", -1), ("overtaken", -1)], called
    assert w.of.calls == 0
    called.clear()
    aid, fan, mid = "fa_lk_order2", 702, 9201
    rid = await seed_live(aid)
    await dm(aid, fan, mid)

    async def loud_load(look):
        called.append(("load", look.index))

    def loud(look):
        called.append(("loud", look.index))
        return "loud" if look.index >= 0 else None
    with _checks((0, ("first", None, first))):
        full_ai_look.LAST_LOOK[_at("overtaken")] = ("loud", loud_load, loud)
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    sd = _reply(row)["stood_down"]
    assert (row.status, sd, w.of.calls) == ("no_send", {"check": "first", "reason": "first_wins", "index": 0}, 0)
    assert called == [("first", -1), ("load", -1), ("loud", -1), ("first", 0)], called
    assert await out_rows(aid, fan) == [] and all(getattr(row, c) is None for c in OFFER_COLS)


async def case_overtaken_before_bubble_1():
    aid, fan, mid = "fa_lk_over", 703, 9301
    rid = await seed_live(aid)
    await dm(aid, fan, mid, "hey you, how was your day")

    async def he_writes_again(*_a, **_k):
        if not wrote:
            wrote.append(1)
            await _msg(aid, fan, mid + 1, "in", "also are u free later", datetime.utcnow())
    wrote = []
    with _patched(full_ai_live, "hold_with_typing", he_writes_again):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    assert (row.status, w.of.calls, res["row_status"]) == ("no_send", 0, "no_send"), res
    assert _reply(row)["stood_down"] == {"check": "overtaken", "reason": "overtaken", "index": 0}
    assert await out_rows(aid, fan) == [] and await leases(aid) == []
    res, w = await _run(aid, fan, mid + 1, rid)
    old, new = await live_rows(aid)
    assert (new.trigger_key, new.status, res["row_status"]) == (str(mid + 1), "sent", "sent"), res
    state = json.dumps(w.jev.calls[0]["state"], ensure_ascii=False)
    assert "how was your day" in state and "free later" in state, state
    assert w.of.calls == len(_reply(new)["parts"]) == len(await out_rows(aid, fan))


async def case_inbound_after_bubble_1():
    aid, fan, mid = "fa_lk_after", 704, 9401

    def after_first(call, _text):
        if call == 1:
            asyncio.run_coroutine_threadsafe(
                _msg(aid, fan, mid + 1, "in", "lol", datetime.utcnow()), loop).result()
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    loop = asyncio.get_running_loop()
    res, w = await _run(aid, fan, mid, rid, of=LiveOF(after=after_first))
    (row,) = await live_rows(aid)
    n = len(_reply(row)["parts"])
    assert n >= 2 and (row.status, w.of.calls, len(await out_rows(aid, fan))) == ("sent", n, n), (row.status, n)
    assert "cut" not in _reply(row)


async def case_check_at_index_1():
    aid, fan, mid = "fa_lk_idx1", 705, 9501
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    with _checks((0, ("fake", None, lambda look: "nope" if look.index == 1 else None))):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    assert (row.status, w.of.calls, len(await out_rows(aid, fan))) == ("sent", 1, 1), row.status
    assert _reply(row)["cut"] == {"check": "fake", "reason": "nope", "index": 1}
    assert (w.turns, w.released) == (2, 1), (w.turns, w.released)


async def case_pre_look_stands_down():
    aid, fan, mid = "fa_lk_pre", 706, 9601
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    with _checks((0, ("fake", None, lambda look: "off" if look.index == -1 else None))):
        res, w = await _run(aid, fan, mid, rid)
    assert res == {"skipped": "fake:off"}, res
    assert (w.jev.calls, w.writer.requests, w.of.calls) == ([], [], 0)
    assert await live_rows(aid) == [] and await leases(aid) == [] and await out_rows(aid, fan) == []


async def case_loader_feeds_check():
    aid, fan, mid = "fa_lk_load", 707, 9701
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    loads, seen = [], []

    async def loader(look):
        loads.append(look.index)
        return {"index": look.index, "sent": look.sent}

    def check(look):
        seen.append(look.facts["fake"])
        return None
    with _checks((0, ("fake", loader, check))):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    n = len(_reply(row)["parts"])
    assert row.status == "sent" and n == w.of.calls and len(loads) == 2 * n + 1, (loads, n)
    assert seen == [{"index": -1, "sent": 0}] + [{"index": i, "sent": i} for i in range(n) for _ in "lg"], seen


async def case_ppv_unbuilt():
    aid, fan, mid = "fa_lk_ppv", 708, 9801
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    no_ppv = {k: v for k, v in full_ai_live.BUBBLE_SENDERS.items() if k != "ppv"}
    with _with_pick(), _patched(full_ai_live, "BUBBLE_SENDERS", no_ppv):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    reply = _reply(row)
    n = len(reply["parts"])
    assert "ppv" in reply["parts"][-1] and "message_id" not in reply["parts"][-1], reply["parts"]
    assert (row.status, w.of.calls, len(await out_rows(aid, fan))) == ("sent", n - 1, n - 1), row.status
    assert [s["text"] for s in w.of.sent] == [p["text"] for p in reply["parts"][:-1]]
    assert reply["cut"] == {"check": "sender", "reason": "ppv_unbuilt", "index": n - 1}, reply["cut"]
    assert reply["offer_dropped"] == "stood_down"
    assert all(getattr(row, c) is None for c in OFFER_COLS), [getattr(row, c) for c in OFFER_COLS]
    aid, fan, mid = "fa_lk_ppv1", 709, 9811
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    with _with_pick(only=True), _patched(full_ai_live, "BUBBLE_SENDERS", no_ppv):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    assert (row.status, w.of.calls) == ("no_send", 0), row.status
    assert _reply(row)["stood_down"] == {"check": "sender", "reason": "ppv_unbuilt", "index": 0}
    assert all(getattr(row, c) is None for c in OFFER_COLS)


def _ppv_sender(result: dict, calls: list):
    async def send(client, look):
        calls.append(look.bubble)
        return {"id": None, "attributed": False, "offer_dropped": None, "unknown": False, **result}
    return send


async def case_ppv_sender_results():
    aid, fan, mid = "fa_lk_attr", 710, 9901
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    calls = []
    with _with_pick(), _patched(full_ai_live, "BUBBLE_SENDERS",
                                {**full_ai_live.BUBBLE_SENDERS,
                                 "ppv": _ppv_sender({"id": 9_700_000_000_001, "attributed": True}, calls)}):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    reply = _reply(row)
    n = len(reply["parts"])
    assert len(calls) == 1 and "ppv" in calls[0] and reply["parts"][-1]["message_id"] == 9_700_000_000_001
    assert (row.status, w.of.calls, len(await out_rows(aid, fan))) == ("sent", n - 1, n - 1)
    assert row.offer_price_cents == 1500 and "offer_dropped" not in reply
    aid, fan, mid = "fa_lk_noattr", 711, 9911
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    with _with_pick(), _patched(full_ai_live, "BUBBLE_SENDERS",
                                {**full_ai_live.BUBBLE_SENDERS,
                                 "ppv": _ppv_sender({"id": 9_700_000_000_002}, [])}):
        await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    outs = await out_rows(aid, fan)
    assert len(outs) == len(_reply(row)["parts"]) and outs[-1].message_id == 9_700_000_000_002
    aid, fan, mid = "fa_lk_unk", 712, 9921
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    calls = []
    with _with_pick(only=True), _patched(full_ai_live, "BUBBLE_SENDERS",
                                         {**full_ai_live.BUBBLE_SENDERS,
                                          "ppv": _ppv_sender({"unknown": True}, calls)}):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    assert (len(calls), row.status, w.of.calls, await out_rows(aid, fan)) == (1, "unconfirmed", 0, []), row.status
    assert _reply(row)["cut"] == {"check": "send_error", "reason": "ppv_unconfirmed", "index": 0}
    assert row.offer_price_cents == 1500 and row.offer_item_ref and "offer_dropped" not in _reply(row)
    aid, fan, mid = "fa_lk_unk2", 713, 9931
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    with _with_pick(), _patched(full_ai_live, "BUBBLE_SENDERS",
                                {**full_ai_live.BUBBLE_SENDERS, "ppv": _ppv_sender({"unknown": True}, [])}):
        await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    assert row.status == "sent" and _reply(row)["cut"]["reason"] == "ppv_unconfirmed" and row.offer_price_cents == 1500
    aid, fan, mid = "fa_lk_media", 714, 9941
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    with _with_pick(), _patched(full_ai_live, "BUBBLE_SENDERS",
                                {**full_ai_live.BUBBLE_SENDERS, "ppv": _ppv_sender(
                                    {"id": 9_700_000_000_003, "attributed": True, "offer_dropped": "media"}, [])}):
        res, w = await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    assert row.status == "sent" and _reply(row)["offer_dropped"] == "media", _reply(row).get("offer_dropped")
    assert res["sent"] == len(_reply(row)["parts"])



async def case_look_raises():
    async def boom(look):
        if look.index == at:
            raise RuntimeError("read failed")
    for at, aid, fan, mid in ((-1, "fa_lk_err_pre", 715, 9951), (0, "fa_lk_err0", 716, 9961),
                              (1, "fa_lk_err1", 717, 9971)):
        rid = await seed_live(aid)
        await dm(aid, fan, mid)
        with _checks((0, ("boom", boom, lambda look: None))):
            res, w = await _run(aid, fan, mid, rid)
        rows = await live_rows(aid)
        if at == -1:
            assert res == {"skipped": "boom:error"} and rows == [] and w.of.calls == 0, res
            continue
        (row,) = rows
        stop = {"check": "boom", "reason": "error", "index": at}
        if at == 0:
            assert (row.status, w.of.calls, _reply(row)["stood_down"]) == ("no_send", 0, stop), row.status
        else:
            assert (row.status, w.of.calls, _reply(row)["cut"]) == ("sent", 1, stop), row.status
    aid, fan, mid = "fa_lk_err_slot", 718, 9981
    rid = await seed_live(aid)
    await dm(aid, fan, mid)

    async def lost(look):
        if look.index == 0:
            raise run_slot.SlotLost("test")
    with _checks((0, ("lost", lost, lambda look: None))):
        try:
            await _run(aid, fan, mid, rid)
            raise AssertionError("SlotLost swallowed")
        except run_slot.SlotLost:
            pass
    assert await live_rows(aid) == []


async def case_tease_stood_down():
    aid, fan, mid = "fa_lk_tease", 719, 9991
    rid = await seed_live(aid)
    await dm(aid, fan, mid)
    real = full_ai_test.send

    def tease(row, parts, pick=None, **kw):
        row["route"] = "tease"
        return real(row, parts, PICK, **kw)
    with _patched(full_ai_live.full_ai_test, "send", tease), \
            _checks((0, ("fake", None, lambda look: "no" if look.index == 0 else None))):
        await _run(aid, fan, mid, rid)
    (row,) = await live_rows(aid)
    reply = _reply(row)
    assert not any("ppv" in p for p in reply["parts"]) and row.status == "no_send", reply
    assert all(getattr(row, c) is None for c in OFFER_COLS), [getattr(row, c) for c in OFFER_COLS]
    assert reply["offer_dropped"] == "stood_down"


_harness.run()
