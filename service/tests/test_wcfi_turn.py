#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import contextlib  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
import run_slot  # noqa: E402
import automations.welcome_chatter_for_info as a05  # noqa: E402
from automations import wcfi_decide  # noqa: E402
from automation_executor import acquire_fan_lease, run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, FanLease, Message  # noqa: E402

_T0 = datetime(2026, 6, 4, 12, 0, 0)


class FakeOF:
    def __init__(self, *, no_id: bool = False, lapsed: bool = False):
        self.sent: list[tuple[int, str]] = []
        self._id, self._no_id, self._lapsed = 9_000_000_000_000, no_id, lapsed

    def send_message(self, chat_id, text, **kw) -> dict:
        self.sent.append((int(chat_id), text))
        if self._no_id:
            return {"success": True}
        self._id += 1
        return {"id": self._id, "text": text, "createdAt": "2026-06-04T12:30:00+00:00"}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": not self._lapsed}


@contextlib.contextmanager
def _patched_llm(reply: str):
    calls: list = []

    async def _chat(**kw):
        calls.append(kw)
        return SimpleNamespace(content=reply, call_id=1)
    real = llm_client.chat
    llm_client.chat = _chat  # type: ignore[attr-defined]
    try:
        yield calls
    finally:
        llm_client.chat = real  # type: ignore[attr-defined]


async def _seed(aid: str, fan_id: int, msgs: list[tuple[str, str]]) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(Fan(account_id=aid, fan_id=fan_id))
        for i, (d, body) in enumerate(msgs):
            s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id * 1000 + i,
                          direction=d, body=body, created_at=_T0 + timedelta(minutes=i)))


async def _turn(aid: str, fan_id: int, client) -> a05.TurnOutcome:
    model = await a05.resolve_model(aid, a05._PURPOSE, None)
    cfg = await a05._load_run_config(aid, {}, a05._PayloadKnobs.of({}), model=model,
                                     llm_capped=False)
    c = (await a05._gather(aid, {fan_id}))[fan_id]
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan_id))
    return await a05._turn(cfg, c, f, None, client, datetime.utcnow())


async def _fan(aid: str, fan_id: int) -> Fan:
    async with get_session() as s:
        return await s.get(Fan, (aid, fan_id))


async def _lease(aid: str, fan_id: int):
    async with get_session() as s:
        return await s.get(FanLease, (aid, fan_id))


async def case_sent():
    aid, fid = "turn_sent", 7101
    await _seed(aid, fid, [("out", "hey babe"), ("in", "hi! how are you")])
    of = FakeOF()
    with _patched_llm("heyy what are you up to tonight?"):
        out = await _turn(aid, fid, of)
    assert (out.kind, out.replies_sent, out.errors) == ("sent", 1, 0), out
    assert of.sent == [(fid, "heyy what are you up to tonight?")], of.sent
    assert await _lease(aid, fid) is None, "lease not released after a sent reply"
    f = await _fan(aid, fid)
    assert f.turn_counter == 1 and f.last_message_sent_at is not None, f
    assert await ax.fan_on_cooldown(aid, fid), "no short rest after a sent reply"


async def case_skipped_cooldown():
    aid, fid = "turn_cool", 7102
    await _seed(aid, fid, [("in", "hi there")])
    await ax.start_fan_cooldown(aid, fid, cooldown_s=600)
    of = FakeOF()
    with _patched_llm("never") as calls:
        out = await _turn(aid, fid, of)
    assert (out.kind, out.skipped_cooldown, out.replies_sent) == ("cooldown", 1, 0), out
    assert not calls and not of.sent, (calls, of.sent)


async def case_skipped_locked():
    aid, fid = "turn_lock", 7103
    await _seed(aid, fid, [("in", "hi there")])
    assert await acquire_fan_lease(aid, fid, "send_followup")
    of = FakeOF()
    with _patched_llm("never") as calls:
        out = await _turn(aid, fid, of)
    assert (out.kind, out.skipped_locked, out.replies_sent) == ("locked", 1, 0), out
    assert not calls and not of.sent, (calls, of.sent)
    lease = await _lease(aid, fid)
    assert lease is not None and lease.automation_kind == "send_followup", "the other engine's lease was touched"


async def case_echo_only_dropped():
    aid, fid = "turn_echo", 7104
    dm = "what are you doing this weekend babe"
    await _seed(aid, fid, [("out", "hey you"), ("in", dm)])
    of = FakeOF()
    with _patched_llm(dm):
        out = await _turn(aid, fid, of)
    assert (out.kind, out.errors, out.replies_sent) == ("echo", 1, 0), out
    assert not of.sent, of.sent
    f = await _fan(aid, fid)
    assert f.turn_counter == 1, "the generated try is counted even when dropped"
    assert await _lease(aid, fid) is None


async def case_lost_slot():
    aid, fid = "turn_lost", 7105
    await _seed(aid, fid, [("in", "hey")])
    of = FakeOF()
    with _patched_llm("heyy what are you up to tonight?\ni just got home 😏"), \
            _harness.slot_lost_at_hold(a05, 2) as calls:
        try:
            await _turn(aid, fid, of)
            raise AssertionError("SlotLost not raised")
        except run_slot.SlotLost:
            pass
    assert calls[0] == 2 and len(of.sent) == 1, (calls, of.sent)
    f = await _fan(aid, fid)
    assert f.last_message_sent_at is not None, "the landed bubble was not recorded"
    assert await _lease(aid, fid) is None


async def case_lost_slot_at_sticker():
    from automations import cat_stickers as cs
    aid, fid = "turn_lost_st", 7110
    await _seed(aid, fid, [("in", "lol that was so funny")])

    class _OF(FakeOF):
        read = 0

        def mark_chat_read(self, chat_id) -> dict:
            self.read += 1
            return super().mark_chat_read(chat_id)
    of, real_roll = _OF(), cs.roll_mode
    cs._last_sent.clear()
    cs.roll_mode = lambda *a, **k: "allow"
    try:
        with _patched_llm("omg ur funny\nSTICKER: laugh"), \
                _harness.slot_lost_at_hold(a05, 2) as calls:
            try:
                await _turn(aid, fid, of)
                raise AssertionError("SlotLost not raised")
            except run_slot.SlotLost:
                pass
    finally:
        cs.roll_mode = real_roll
        cs._last_sent.clear()
    assert calls[0] == 2 and of.sent == [(fid, "omg ur funny")], (calls, of.sent)
    f = await _fan(aid, fid)
    assert f.last_message_sent_at is not None, "the landed bubble was not recorded"
    assert of.read == 0, "mark-read ran after the slot was lost"
    assert await _lease(aid, fid) is None


async def case_no_id_quarantined():
    aid, fid = "turn_noid", 7106
    await _seed(aid, fid, [("in", "how badly?")])
    of = FakeOF(no_id=True, lapsed=True)
    with _patched_llm("heyy what are you up to tonight?"):
        out = await _turn(aid, fid, of)
    assert (out.kind, out.errors, out.replies_sent) == ("no_id", 1, 0), out
    f = await _fan(aid, fid)
    assert f.automation_paused_until > datetime.utcnow() + timedelta(days=6), f.automation_paused_until
    assert f.subscription_status == "expired", f.subscription_status
    assert await _lease(aid, fid) is None


async def case_cap_raises():
    aid, fid = "turn_cap", 7108
    await _seed(aid, fid, [("in", "hi there")])
    for exc in (llm_client.LLMCapExceeded("acc", 100, 200),
                llm_client.LLMKeyError("invalid", "deepseek", "welcome_chatter_for_info",
                                       status=401, detail="HTTP 401: bad key")):
        async def _raise(**kw):
            raise exc
        real, llm_client.chat = llm_client.chat, _raise  # type: ignore[attr-defined]
        of = FakeOF()
        try:
            await _turn(aid, fid, of)
            raise AssertionError(f"{type(exc).__name__} not raised")
        except type(exc):
            pass
        finally:
            llm_client.chat = real  # type: ignore[attr-defined]
        assert not of.sent, of.sent
        assert await _lease(aid, fid) is None, f"lease kept after {type(exc).__name__}"


async def case_persist_seam():
    aid, fid = "turn_seam", 7109
    await _seed(aid, fid, [("in", "hi there")])
    real, seen = a05.write_outbound_attribution, []

    async def _spy(**kw):
        seen.append(kw["body"])
        return await real(**kw)
    a05.write_outbound_attribution = _spy  # type: ignore[attr-defined]
    try:
        with _patched_llm("heyy what are you up to tonight?"):
            out = await _turn(aid, fid, FakeOF())
    finally:
        a05.write_outbound_attribution = real  # type: ignore[attr-defined]
    assert out.kind == "sent" and seen == ["heyy what are you up to tonight?"], (out, seen)


def case_fold_table():
    tally, skips = Counter(), Counter(dict.fromkeys(wcfi_decide.COUNTERS, 0))
    for o in (a05.TurnOutcome(kind="sent", replies_sent=1),
              a05.TurnOutcome(kind="sent", replies_sent=1, stickers_sent=1),
              a05.TurnOutcome(kind="cooldown", skipped_cooldown=1),
              a05.TurnOutcome(kind="locked", skipped_locked=1),
              a05.TurnOutcome(kind="banned", skipped_banned=1),
              a05.TurnOutcome(kind="no_id", errors=1),
              a05.TurnOutcome(kind="graduated", newly_skiplisted=1),
              a05.TurnOutcome(kind="closing_cut", replies_sent=1, closing_ppvs_sent=1)):
        a05._fold(tally, skips, o)
    assert dict(tally) == {"replies_sent": 3, "stickers_sent": 1, "closing_ppvs_sent": 1,
                           "skipped_locked": 1, "skipped_cooldown": 1, "skipped_banned": 1,
                           "errors": 1}, tally
    assert skips["newly_skiplisted"] == 1 and set(skips) == set(wcfi_decide.COUNTERS), skips


async def case_run_stats_keys():
    aid = "turn_stats"
    await _seed(aid, 7107, [("in", "hi there")])
    real_client = ax._make_client
    ax._make_client = lambda account_id: FakeOF()  # type: ignore[attr-defined]
    try:
        with _patched_llm("heyy what are you up to tonight?"):
            res = await run_once(aid, "welcome_chatter_for_info", payload={})
    finally:
        ax._make_client = real_client  # type: ignore[attr-defined]
    keys = [k for k in res if k in {"candidates", "replies_sent", "stickers_sent",
                                    "closing_ppvs_sent", *wcfi_decide.COUNTERS,
                                    "skipped_locked", "skipped_cooldown", "skipped_banned",
                                    "errors", "cap_hit", "dry_run", "model"}]
    assert keys == ["candidates", "replies_sent", "stickers_sent", "closing_ppvs_sent",
                    *wcfi_decide.COUNTERS, "skipped_locked", "skipped_cooldown",
                    "skipped_banned", "errors", "cap_hit", "dry_run", "model"], keys
    assert (res["replies_sent"], res["errors"], res["cap_hit"]) == (1, 0, False), res


def _extract_call(kw) -> bool:
    return "profile analyzer" in kw["messages"][0]["content"]


async def _profile_chat(**kw):
    if _extract_call(kw):
        return SimpleNamespace(content='{"his_age":"31"}', parsed={"his_age": "31"}, call_id=1)
    return SimpleNamespace(content="mmm tell me more 😏", call_id=2)


@contextlib.contextmanager
def _run_seams(chat):
    of, real_client, real_chat = FakeOF(), ax._make_client, llm_client.chat
    ax._make_client = lambda account_id: of  # type: ignore[attr-defined]
    llm_client.chat = chat  # type: ignore[attr-defined]
    try:
        yield of
    finally:
        ax._make_client, llm_client.chat = real_client, real_chat  # type: ignore[attr-defined]


async def case_model_waits_free_the_slot():
    for aid, fid, park in (("turn_freed_x", 7121, _extract_call),
                           ("turn_freed_r", 7122, lambda kw: not _extract_call(kw))):
        await _seed(aid, fid, [("in", "haha im 31 btw")])
        chat = _harness.parking_chat(_profile_chat, park)
        with _run_seams(chat) as of:
            res = await _harness.slot_parked(
                lambda: run_once(aid, "welcome_chatter_for_info", payload={}), chat)
        assert res["replies_sent"] == 1 and [c for c, _ in of.sent] == [fid], (aid, res, of.sent)
        assert (await _fan(aid, fid)).his_age == "31", aid


async def case_slot_lost_in_model_wait_sends_no_more():
    aid = "turn_freed_lost"
    for fid in (7123, 7124):
        await _seed(aid, fid, [("in", "hey")])
    replies = [0]

    def _second_reply(kw) -> bool:
        replies[0] += not _extract_call(kw)
        return replies[0] == 2
    chat = _harness.parking_chat(_profile_chat, _second_reply)
    real, a05.INLINE_MAX_S = a05.INLINE_MAX_S, 0.2
    try:
        with _run_seams(chat) as of:
            res = await _harness.slot_parked(
                lambda: run_once(aid, "welcome_chatter_for_info", payload={}), chat, keep_s=0.5)
    finally:
        a05.INLINE_MAX_S = real
    assert res["status"] == "error", res
    assert len(of.sent) == 1, of.sent
    first = of.sent[0][0]
    (other,) = {7123, 7124} - {first}
    f = await _fan(aid, other)
    assert not f.turn_counter and f.last_message_sent_at is None, (f.turn_counter, f.last_message_sent_at)
    assert await _lease(aid, other) is None
    assert (await _fan(aid, first)).turn_counter == 1
    with _run_seams(_profile_chat) as of2:
        res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1 and [c for c, _ in of2.sent] == [other], (res, of2.sent)


_harness.run()
