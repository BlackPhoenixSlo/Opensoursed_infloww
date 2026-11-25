#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402 — module under test

a11._STEP_GAP_S = 0
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRun,
    Fan,
    FanLease,
    FunnelAccountMedia,
    FunnelResponder,
    FunnelState,
    MassMessageFunnel,
    MassRun,
    Message,
    SkipList,
)

OWN_ID = "999"
# Relative to now: a pinned date ages out of DISCOVERY_WINDOW_DAYS and the file turns red untouched.
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)
T_REPLY1 = T0 + timedelta(minutes=5)
SEND_AT = (T0 + timedelta(hours=2)).isoformat() + "+00:00"



class FakeOF:

    def __init__(self, user_id: str = OWN_ID):
        self.user_id = user_id
        self.sent: list[dict] = []
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {"id": self._next_id, "text": f"<p>{text}</p>", "createdAt": SEND_AT}


def _strip(s: str) -> str:
    return (s or "").replace("<p>", "").replace("</p>", "").strip()


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "generated nudge 💕") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]



async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_funnel(name: str, steps: list[dict]) -> int:
    async with get_session() as s:
        f = MassMessageFunnel(
            name=name, opening_message="How many strokes? 😈",
            media_indices="[]", steps_json=json.dumps(steps),
        )
        s.add(f)
        await s.flush()
        return int(f.id)


async def _seed_account_media(aid: str, funnel_id: int, *,
                              opening: list[int] | None = None,
                              steps_media: dict | None = None) -> None:
    async with get_session() as s:
        s.add(FunnelAccountMedia(
            funnel_id=funnel_id, account_id=aid,
            opening_media_ids=json.dumps(opening or []),
            steps_media_json=json.dumps(steps_media or {}),
        ))


async def _seed_mass_run(aid: str, funnel_id: int, status: str = "ok",
                         started_at: datetime | None = None) -> int:
    async with get_session() as s:
        mr = MassRun(account_id=aid, funnel_id=funnel_id, status=status,
                     recipient_count=1, started_at=started_at or T0)
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _seed_msg(aid: str, fan_id: int, mid: int, direction: str,
                    created_at: datetime, *, mass_run_id: int | None = None,
                    body: str = "hi") -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=mid, direction=direction,
            body=body, created_at=created_at, mass_run_id=mass_run_id,
        ))


async def _broadcast(aid: str, mass_run_id: int, fan_id: int) -> None:
    await _seed_msg(aid, fan_id, 5_000_000_000_000_000 + mass_run_id, "out", T0,
                    mass_run_id=mass_run_id, body="How many strokes? 😈")


async def _seed_paid_ppv(aid: str, fan_id: int, mid: int, *,
                         purchased_at: datetime) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=mid, direction="out",
            body="unlock me", price_cents=2000, is_paid=True,
            purchased_at=purchased_at, created_at=purchased_at,
        ))


async def _state(mass_run_id: int, fan_id: int) -> FunnelState | None:
    async with get_session() as s:
        return await s.get(FunnelState, (mass_run_id, fan_id))


async def _seed_state(mass_run_id: int, fan_id: int, *, current_step: int,
                      check_count: int = 0, hops: int = 0, status: str = "pending",
                      next_check_at: datetime | None = None) -> None:
    async with get_session() as s:
        s.add(FunnelState(
            mass_run_id=mass_run_id, fan_id=fan_id, current_step=current_step,
            check_count=check_count, hops=hops, status=status,
            next_check_at=next_check_at or (datetime.utcnow() - timedelta(minutes=1)),
        ))


async def _force_due(aid: str, mass_run_id: int, fan_id: int) -> None:
    async with get_session() as s:
        await s.execute(
            update(FunnelState)
            .where(FunnelState.mass_run_id == mass_run_id, FunnelState.fan_id == fan_id)
            .values(next_check_at=datetime.utcnow() - timedelta(minutes=1))
        )
        await s.execute(
            update(Fan)
            .where(Fan.account_id == aid, Fan.fan_id == fan_id)
            .values(automation_paused_until=None)
        )
    await ax.release_fan_lease(aid, fan_id)


async def _funnel_out_msgs(aid: str, fan_id: int) -> list[Message]:
    async with get_session() as s:
        return (await s.execute(
            select(Message).where(
                Message.account_id == aid, Message.fan_id == fan_id,
                Message.direction == "out", Message.funnel_step.is_not(None),
            ).order_by(Message.message_id)
        )).scalars().all()


_TWO_STEP = [
    {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["m1a", "m1b"]},
    {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["m2a"]},
    {"step": 3, "type": "paid_ppv", "price": 24, "messages": ["open this 😈"]},
]



async def case_discover_and_advance():
    aid = "acc_f1"
    await _seed_account(aid)
    fid = await _seed_funnel("f1", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 1001)
    await _seed_msg(aid, 1001, 7001, "in", T_REPLY1, body="haha a lot")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert res["discovered"] == 1, res
    assert res["advanced"] == 1, res

    st = await _state(mr, 1001)
    assert st is not None and st.current_step == 1, st
    assert st.status == "pending", st

    out = await _funnel_out_msgs(aid, 1001)
    assert len(out) == 2, [m.body for m in out]
    assert all(m.mass_run_id == mr and m.funnel_step == 1 for m in out), out
    assert {_strip(m.body) for m in out} == {"m1a", "m1b"}, [m.body for m in out]

    runs = await _runs(aid)
    assert len(runs) == 1 and runs[0].status == "ok", runs

    async with get_session() as s:
        assert await s.get(FanLease, (aid, 1001)) is None, "lease released after step"
        until = (await s.get(Fan, (aid, 1001))).automation_paused_until
    assert until is not None and until < datetime.utcnow() + timedelta(minutes=2), until


async def _runs(aid: str) -> list[AutomationRun]:
    async with get_session() as s:
        return (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()



async def case_cooldown_skips_funnel():
    aid = "acc_f1b"
    await _seed_account(aid)
    fid = await _seed_funnel("f1b", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 1101)
    await _seed_msg(aid, 1101, 7011, "in", T_REPLY1, body="haha a lot")
    fake = _use_fake()

    await ax.start_fan_cooldown(aid, 1101)

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["skipped_cooldown"] == 1, res
    assert res["advanced"] == 0, res
    assert fake.sent == [], fake.sent



async def case_resume_after_restart():
    aid = "acc_f2"
    await _seed_account(aid)
    fid = await _seed_funnel("f2", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 2001)
    await _seed_msg(aid, 2001, 7101, "in", T_REPLY1, body="reply 1")
    _use_fake()

    r1 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r1["advanced"] == 1, r1
    assert (await _state(mr, 2001)).current_step == 1, "step 0→1"

    await _seed_msg(aid, 2001, 7102, "in", T0 + timedelta(hours=3), body="reply 2")
    await _force_due(aid, mr, 2001)

    r2 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r2["advanced"] == 1, r2
    st = await _state(mr, 2001)
    assert st.current_step == 2, f"resumed 1→2 from DB, got {st.current_step}"



async def case_no_new_reply_reschedules():
    aid = "acc_f3"
    await _seed_account(aid)
    fid = await _seed_funnel("f3", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 3001)
    await _seed_msg(aid, 3001, 7201, "in", T_REPLY1, body="reply 1")
    _use_fake()

    await run_once(aid, "reply_mass_funnel", payload={})
    assert (await _state(mr, 3001)).current_step == 1

    await _force_due(aid, mr, 3001)
    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["waiting"] == 1, res
    assert res["advanced"] == 0, res

    st = await _state(mr, 3001)
    assert st.current_step == 1, "no advance without a fresh reply"
    assert st.check_count >= 1, st
    assert st.next_check_at is not None and st.next_check_at > datetime.utcnow(), st



async def case_ppv_step_is_terminal():
    aid = "acc_f4"
    await _seed_account(aid)
    fid = await _seed_funnel("f4", [
        {"step": 1, "type": "paid_ppv", "price": 30, "messages": ["unlock me"]},
    ])
    await _seed_account_media(aid, fid, steps_media={"1": {"media_files": [888]}})
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 4001)
    await _seed_msg(aid, 4001, 7301, "in", T_REPLY1, body="yes")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1 and res["completed"] == 1, res

    st = await _state(mr, 4001)
    assert st.current_step == 1 and st.status == "done", st

    assert fake.sent and fake.sent[0]["price"] == 30, fake.sent
    assert fake.sent[0]["media_files"] == [888], fake.sent
    out = await _funnel_out_msgs(aid, 4001)
    assert len(out) == 1 and out[0].price_cents == 3000, out



async def case_ppv_media_is_per_account():
    fid = await _seed_funnel("f_per_acct", [
        {"step": 1, "type": "paid_ppv", "price": 20, "messages": ["unlock me"]},
    ])
    for aid, mid, fan, msg in (
        ("acc_fa", 1111, 41001, 7411),
        ("acc_fb", 2222, 42001, 7421),
    ):
        await _seed_account(aid)
        await _seed_account_media(
            aid, fid, steps_media={"1": {"media_files": [mid, 3333], "previews": [mid]}})
        mr = await _seed_mass_run(aid, fid)
        await _broadcast(aid, mr, fan)
        await _seed_msg(aid, fan, msg, "in", T_REPLY1, body="yes")
        fake = _use_fake()

        res = await run_once(aid, "reply_mass_funnel", payload={})
        assert res["advanced"] == 1, (aid, res)
        assert fake.sent[0]["media_files"] == [mid, 3333], (aid, fake.sent)
        assert fake.sent[0]["previews"] == [mid], (aid, fake.sent)



async def case_ppv_media_legacy_fallback():
    aid = "acc_f_legacy"
    await _seed_account(aid)
    fid = await _seed_funnel("f_legacy", [
        {"step": 1, "type": "paid_ppv", "price": 15, "media_files": [555],
         "messages": ["unlock me"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 43001)
    await _seed_msg(aid, 43001, 7431, "in", T_REPLY1, body="yes")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1, res
    assert fake.sent[0]["media_files"] == [555], fake.sent



async def case_generated_step_uses_llm():
    aid = "acc_f5"
    await _seed_account(aid)
    fid = await _seed_funnel("f5", [
        {"step": 1, "prompt": "tease him about losing count"},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 5001)
    await _seed_msg(aid, 5001, 7401, "in", T_REPLY1, body="lots")
    fake = _use_fake()
    _patch_llm("bet you lose count fast 😏")

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1, res
    assert fake.sent and fake.sent[0]["text"] == "bet you lose count fast 😏", fake.sent

    out = await _funnel_out_msgs(aid, 5001)
    assert len(out) == 1 and _strip(out[0].body) == "bet you lose count fast 😏", out



async def case_dry_run_sends_nothing():
    aid = "acc_f6"
    await _seed_account(aid)
    fid = await _seed_funnel("f6", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 6001)
    await _seed_msg(aid, 6001, 7501, "in", T_REPLY1, body="hey")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={"dry_run": True})
    assert res["discovered"] == 1, res
    assert res["advanced"] == 1, res
    assert fake.sent == [], "dry run must not send"

    assert await _state(mr, 6001) is None, "dry run must not enroll the fan"
    async with get_session() as s:
        ledger = (await s.execute(select(FunnelResponder).where(
            FunnelResponder.account_id == aid))).scalars().all()
    assert ledger == [], "dry run must not write the responder ledger"
    assert (await _funnel_out_msgs(aid, 6001)) == [], "dry run writes no message row"

    await _seed_state(mr, 6002, current_step=1, check_count=0)
    await _seed_msg(aid, 6002, 7502, "out", T_REPLY1, mass_run_id=mr, body="m1a")
    before = await _state(mr, 6002)
    res = await run_once(aid, "reply_mass_funnel", payload={"dry_run": True})
    assert res["waiting"] == 1, res
    after = await _state(mr, 6002)
    assert (after.check_count, after.next_check_at) == (
        before.check_count, before.next_check_at), "dry run moved a state"



async def case_non_replier_not_discovered():
    aid = "acc_f7"
    await _seed_account(aid)
    fid = await _seed_funnel("f7", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 7001)
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["discovered"] == 0, res
    assert res["advanced"] == 0, res
    assert await _state(mr, 7001) is None, "non-replier must not be tracked"


async def case_unreachable_fan_ends_state():
    aid = "acc_f_unreach"
    await _seed_account(aid)
    fid = await _seed_funnel("f_unreach", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 8101)
    await _seed_msg(aid, 8101, 7081, "in", T_REPLY1, body="haha a lot")
    fake = _use_fake()
    def _raise(chat_id, text, **kw):
        raise Exception(
            f"404 for https://onlyfans.com/api2/v2/chats/{chat_id}/messages\n"
            '{"error":{"code":0,"message":"User not found"}}'
        )
    fake.send_message = _raise
    calls: list[int] = []
    async def _fake_chat(**kw):
        calls.append(kw.get("fan_id"))
        return SimpleNamespace(content="generated nudge 💕")
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]

    r1 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r1["errors"] == 1 and r1["advanced"] == 0, r1
    st = await _state(mr, 8101)
    assert st is not None and st.status == "done", st
    async with get_session() as s:
        row = await s.get(SkipList, (aid, 8101))
        assert row is not None and row.reason == "unreachable", row

    r2 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r2["errors"] == 0 and r2["advanced"] == 0 and r2["discovered"] == 0, r2
    assert calls == [], ("verbatim steps never hit the LLM; none after quarantine", calls)


async def case_list_audience_adoption():
    aid = "acc_f_adopt"
    await _seed_account(aid)
    fid = await _seed_funnel("f_adopt", _TWO_STEP)
    async with get_session() as s:
        mr_row = MassRun(
            account_id=aid, funnel_id=fid, status="ok", recipient_count=0,
            started_at=T0,
            audience_filter=json.dumps({"user_lists": ["fans"],
                                        "excluded_users": [9203]}),
        )
        s.add(mr_row)
        await s.flush()
        mr = int(mr_row.id)
    t_out = T0 + timedelta(minutes=1)
    await _seed_msg(aid, 9201, 9_001, "out", t_out, body="<p>How many strokes? 😈</p>")
    await _seed_msg(aid, 9201, 9_002, "in", T_REPLY1, body="haha a lot")
    await _seed_msg(aid, 9202, 9_003, "out", t_out, body="hey you 💕")
    await _seed_msg(aid, 9202, 9_004, "in", T_REPLY1, body="hi")
    await _seed_msg(aid, 9203, 9_005, "out", t_out, body="How many strokes? 😈")
    await _seed_msg(aid, 9203, 9_006, "in", T_REPLY1, body="yo")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert res["discovered"] == 1, res
    assert res["advanced"] == 1, res

    st = await _state(mr, 9201)
    assert st is not None and st.current_step == 1, st
    assert await _state(mr, 9202) is None, "non-opener outbound must not be adopted"
    assert await _state(mr, 9203) is None, "excluded fan must not be adopted"

    async with get_session() as s:
        m = await s.get(Message, (aid, 9201, 9_001))
        assert m is not None and m.mass_run_id == mr, m
    res2 = await run_once(aid, "reply_mass_funnel", payload={})
    assert res2["discovered"] == 0, res2



async def case_blank_ppv_blocked():
    aid = "acc_f_blank"
    await _seed_account(aid)
    fid = await _seed_funnel("f_blank", [
        {"step": 1, "type": "paid_ppv", "price": 20, "messages": ["unlock me"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 44001)
    await _seed_msg(aid, 44001, 7441, "in", T_REPLY1, body="yes")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["blocked"] == 1, res
    assert res["advanced"] == 0, res
    assert fake.sent == [], "blank PPV must not send a blank paywall"

    st = await _state(mr, 44001)
    assert st is not None and st.current_step == 0 and st.status == "pending", st
    assert st.last_error and "ppv_without_media" in st.last_error, st
    assert st.next_check_at is not None and st.next_check_at > datetime.utcnow(), st



async def case_offer_taken_halts():
    aid = "acc_f_taken"
    await _seed_account(aid)
    fid = await _seed_funnel("f_taken", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 45001)
    await _seed_msg(aid, 45001, 7451, "in", T_REPLY1, body="omg yes")
    await _seed_paid_ppv(aid, 45001, 7452, purchased_at=T0 + timedelta(minutes=10))
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["converted"] == 1, res
    assert res["advanced"] == 0, res
    assert fake.sent == [], "a converted fan gets no funnel step"

    st = await _state(mr, 45001)
    assert st is not None and st.status == "done", st
    assert st.current_step == 0, "halted before advancing"
    assert st.last_error == "offer_taken", st


async def case_offer_not_taken_still_walks():
    aid = "acc_f_oldbuy"
    await _seed_account(aid)
    fid = await _seed_funnel("f_oldbuy", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 46001)
    await _seed_msg(aid, 46001, 7461, "in", T_REPLY1, body="hey")
    await _seed_paid_ppv(aid, 46001, 7462, purchased_at=T0 - timedelta(hours=25))
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["converted"] == 0, res
    assert res["advanced"] == 1, res
    st = await _state(mr, 46001)
    assert st is not None and st.current_step == 1 and st.status == "pending", st



_BOUGHT_BRANCH = [
    {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"],
     "next": {"bought": 5}},
    {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"]},
    {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    {"step": 4, "check_intervals_min": [2, 4, 10], "messages": ["s4"]},
    {"step": 5, "check_intervals_min": [2, 4, 10], "messages": ["s5"]},
]


async def case_next_bought_jumps_else_falls_through():
    aid = "acc_br_bought"
    await _seed_account(aid)
    fid = await _seed_funnel("br_bought", _BOUGHT_BRANCH)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 51001)
    await _seed_msg(aid, 51001, 7601, "in", T_REPLY1, body="omg yes")
    await _seed_paid_ppv(aid, 51001, 7602, purchased_at=T0 + timedelta(minutes=10))
    await _broadcast(aid, mr, 51002)
    await _seed_msg(aid, 51002, 7603, "in", T_REPLY1, body="haha maybe")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["branched"] == 1, res
    assert res["advanced"] == 1, res
    assert res["converted"] == 0, res

    a = await _state(mr, 51001)
    assert a is not None and a.current_step == 4 and a.status == "pending", a
    assert await _funnel_out_msgs(aid, 51001) == [], "bought-branch sends no step"
    b = await _state(mr, 51002)
    assert b is not None and b.current_step == 1, b
    out_b = await _funnel_out_msgs(aid, 51002)
    assert len(out_b) == 1 and _strip(out_b[0].body) == "s1", out_b
    assert {m["fan_id"] for m in fake.sent} == {51002}, fake.sent


async def case_next_ignored_branch_on_no_reply():
    aid = "acc_br_ignored"
    await _seed_account(aid)
    fid = await _seed_funnel("br_ignored", [
        {"step": 1, "check_intervals_min": [2], "messages": ["s1"]},
        {"step": 2, "check_intervals_min": [2], "messages": ["s2"],
         "next": {"ignored": 3}},
        {"step": 3, "check_intervals_min": [2], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 52001)
    await _seed_state(mr, 52001, current_step=1, check_count=1)
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["branched"] == 1, res
    assert res["waiting"] == 0, res
    assert fake.sent == [], "ignored branch sends nothing"

    st = await _state(mr, 52001)
    assert st is not None and st.current_step == 2, st
    assert st.status == "pending", st


async def case_next_ignored_waits_inside_window():
    aid = "acc_br_ignored_wait"
    await _seed_account(aid)
    fid = await _seed_funnel("br_ignored_wait", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"]},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"],
         "next": {"ignored": 3}},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 52101)
    await _seed_state(mr, 52101, current_step=1, check_count=0)
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["waiting"] == 1 and res["branched"] == 0, res
    st = await _state(mr, 52101)
    assert st is not None and st.current_step == 1, st
    assert st.check_count == 1, st


async def case_next_keyword_branch_on_reply():
    aid = "acc_br_kw"
    await _seed_account(aid)
    fid = await _seed_funnel("br_kw", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"],
         "next": {"keyword": {"more": 3}, "default": 2}},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"]},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 53001)
    await _seed_msg(aid, 53001, 7701, "in", T_REPLY1, body="give me MORE please")
    await _broadcast(aid, mr, 53002)
    await _seed_msg(aid, 53002, 7702, "in", T_REPLY1, body="meh idk")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 2, res

    k = await _state(mr, 53001)
    assert k is not None and k.current_step == 2, ("keyword→step3(index2)", k)
    d = await _state(mr, 53002)
    assert d is not None and d.current_step == 1, ("default→step2(index1)", d)
    assert (k.last_sent_step, d.last_sent_step) == (0, 0), (k.last_sent_step, d.last_sent_step)
    assert _strip((await _funnel_out_msgs(aid, 53001))[0].body) == "s1"
    assert _strip((await _funnel_out_msgs(aid, 53002))[0].body) == "s1"


async def case_next_keyword_ignores_bare_reaction():
    aid = "acc_br_kw_react"
    await _seed_account(aid)
    fid = await _seed_funnel("br_kw_react", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"],
         "next": {"keyword": {"more": 3}, "default": 2}},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"]},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 53101)
    await _seed_msg(aid, 53101, 7711, "in", T_REPLY1, body="🔥")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1, res
    st = await _state(mr, 53101)
    assert st is not None and st.current_step == 1, ("bare reaction → default", st)


async def case_loop_guard_halts_self_reference():
    aid = "acc_br_loop"
    await _seed_account(aid)
    fid = await _seed_funnel("br_loop", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["loop"],
         "next": {"default": 1}},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 54001)
    await _seed_msg(aid, 54001, 7801, "in", T_REPLY1, body="reply 1")
    _use_fake()

    prev = a11._MAX_HOPS
    a11._MAX_HOPS = 3
    try:
        r1 = await run_once(aid, "reply_mass_funnel", payload={})
        assert r1["advanced"] == 1, r1
        st = await _state(mr, 54001)
        assert st.current_step == 0 and st.hops == 1, ("self-loop, 1 hop", st)
        await _seed_msg(aid, 54001, 7802, "in", T0 + timedelta(hours=3),
                        body="again")
        for _ in range(10):
            st = await _state(mr, 54001)
            if st.status == "done":
                break
            await _force_due(aid, mr, 54001)
            await run_once(aid, "reply_mass_funnel", payload={})
        st = await _state(mr, 54001)
        assert st.status == "done", ("loop guard must halt the fan", st)
        assert st.last_error == "loop_guard", st
        assert st.hops >= 3, st
    finally:
        a11._MAX_HOPS = prev


async def case_no_next_walks_linearly():
    aid = "acc_br_linear"
    await _seed_account(aid)
    fid = await _seed_funnel("br_linear", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["m1"]},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["m2"]},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["m3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 55001)
    await _seed_msg(aid, 55001, 7901, "in", T_REPLY1, body="reply 1")
    _use_fake()

    await run_once(aid, "reply_mass_funnel", payload={})
    assert (await _state(mr, 55001)).current_step == 1

    await _seed_msg(aid, 55001, 7902, "in", T0 + timedelta(hours=3), body="r2")
    await _force_due(aid, mr, 55001)
    await run_once(aid, "reply_mass_funnel", payload={})
    assert (await _state(mr, 55001)).current_step == 2

    await _seed_msg(aid, 55001, 7903, "in", T0 + timedelta(hours=4), body="r3")
    await _force_due(aid, mr, 55001)
    await run_once(aid, "reply_mass_funnel", payload={})
    st = await _state(mr, 55001)
    assert st.current_step == 3 and st.status == "done", st
    assert not st.hops, ("linear funnel must not bump hops", st.hops)

    out = await _funnel_out_msgs(aid, 55001)
    assert [_strip(m.body) for m in out] == ["m1", "m2", "m3"], out


async def case_aged_broadcast_stops_discovering():
    aid = "acc_f_aged"
    await _seed_account(aid)
    fid = await _seed_funnel("f_aged", _TWO_STEP)
    old = T0 - timedelta(days=a11.DISCOVERY_WINDOW_DAYS + 1)
    mr = await _seed_mass_run(aid, fid, started_at=old)
    await _seed_msg(aid, 8201, 5_900_000 + mr, "out", old, mass_run_id=mr,
                    body="How many strokes? 😈")
    await _seed_msg(aid, 8201, 7_201, "in", old + timedelta(minutes=5), body="a lot")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res.get("reason") == "no_active_funnel_runs", res
    assert await _state(mr, 8201) is None, "aged-out run must not enrol anyone"


async def case_aged_broadcast_still_walks_pending_fan():
    aid = "acc_f_aged_live"
    await _seed_account(aid)
    fid = await _seed_funnel("f_aged_live", _TWO_STEP)
    old = T0 - timedelta(days=a11.DISCOVERY_WINDOW_DAYS + 1)
    mr = await _seed_mass_run(aid, fid, started_at=old)
    await _seed_msg(aid, 8301, 5_910_000 + mr, "out", old, mass_run_id=mr,
                    body="How many strokes? 😈")
    await _seed_state(mr, 8301, current_step=1)
    await _seed_msg(aid, 8301, 7_301, "in", datetime.utcnow(), body="yes please")
    await _seed_msg(aid, 8302, 5_920_000 + mr, "out", old, mass_run_id=mr,
                    body="How many strokes? 😈")
    await _seed_msg(aid, 8302, 7_302, "in", old + timedelta(minutes=5), body="a lot")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["runs"] == 1, res
    assert res["discovery_skipped"] == 1, res
    assert res["discovered"] == 0, res
    assert res["advanced"] == 1, res
    assert fake.sent, "the pending fan must still receive his step"
    assert await _state(mr, 8302) is None, "discovery stays closed past the window"


async def case_slot_lost_mid_step_records_the_step_and_never_resends_it():
    aid = "acc_slot_lost"
    await _seed_account(aid)
    fid = await _seed_funnel("slot_lost", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 66001)
    await _seed_msg(aid, 66001, 7951, "in", T_REPLY1, body="haha a lot")
    fake = _use_fake()
    with _harness.slot_lost_at_hold(a11, 2):
        res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "error", res
    assert [_strip(m["text"]) for m in fake.sent] == ["m1a"], fake.sent
    st = await _state(mr, 66001)
    assert st.current_step == 1 and st.status == "pending", st
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 66001)) is None
        assert (await s.get(Fan, (aid, 66001))).automation_paused_until is not None
        await s.execute(update(Fan).where(Fan.account_id == aid).values(automation_paused_until=None))
        await s.commit()
    await _force_due(aid, mr, 66001)
    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert [_strip(m["text"]) for m in fake.sent] == ["m1a"], fake.sent


_GEN_STEP = [{"step": 1, "prompt": "tease him about losing count"}]


async def case_model_wait_frees_the_slot():
    aid = "acc_freed"
    await _seed_account(aid)
    mr = await _seed_mass_run(aid, await _seed_funnel("freed", _GEN_STEP))
    await _broadcast(aid, mr, 66101)
    await _seed_msg(aid, 66101, 7961, "in", T_REPLY1, body="lots")
    fake = _use_fake()
    _patch_llm()
    chat = llm_client.chat = _harness.parking_chat(llm_client.chat, 1)
    res = await _harness.slot_parked(lambda: run_once(aid, "reply_mass_funnel", payload={}), chat)
    assert res["advanced"] == 1 and [m["fan_id"] for m in fake.sent] == [66101], (res, fake.sent)


async def case_slot_lost_in_model_wait_sends_no_more():
    aid = "acc_freed_lost"
    await _seed_account(aid)
    mr = await _seed_mass_run(aid, await _seed_funnel("freed_lost", _GEN_STEP))
    for fan, mid in ((66111, 7971), (66112, 7972)):
        await _broadcast(aid, mr, fan)
        await _seed_msg(aid, fan, mid, "in", T_REPLY1, body="lots")
    fake = _use_fake()
    _patch_llm()
    chat = llm_client.chat = _harness.parking_chat(llm_client.chat, 2)
    real, a11.INLINE_MAX_S = a11.INLINE_MAX_S, 0.2
    try:
        res = await _harness.slot_parked(lambda: run_once(aid, "reply_mass_funnel", payload={}),
                                         chat, keep_s=0.5)
    finally:
        a11.INLINE_MAX_S = real
    assert res["status"] == "error", res
    assert len(fake.sent) == 1, fake.sent
    first = fake.sent[0]["fan_id"]
    (other,) = {66111, 66112} - {first}
    assert (await _state(mr, first)).current_step == 1
    st = await _state(mr, other)
    assert st.current_step == 0 and st.status == "pending" and st.sending_at is None, st.__dict__
    async with get_session() as s:
        assert await s.get(FanLease, (aid, other)) is None
    await _force_due(aid, mr, other)
    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1 and [m["fan_id"] for m in fake.sent] == [first, other], (res, fake.sent)


_harness.run(
    case_model_wait_frees_the_slot,
    case_slot_lost_in_model_wait_sends_no_more,
    case_discover_and_advance,
    case_slot_lost_mid_step_records_the_step_and_never_resends_it,
    case_cooldown_skips_funnel,
    case_resume_after_restart,
    case_no_new_reply_reschedules,
    case_ppv_step_is_terminal,
    case_ppv_media_is_per_account,
    case_ppv_media_legacy_fallback,
    case_generated_step_uses_llm,
    case_dry_run_sends_nothing,
    case_non_replier_not_discovered,
    case_unreachable_fan_ends_state,
    case_list_audience_adoption,
    case_blank_ppv_blocked,
    case_offer_taken_halts,
    case_offer_not_taken_still_walks,
    case_next_bought_jumps_else_falls_through,
    case_next_ignored_branch_on_no_reply,
    case_next_ignored_waits_inside_window,
    case_next_keyword_branch_on_reply,
    case_next_keyword_ignores_bare_reaction,
    case_loop_guard_halts_self_reference,
    case_no_next_walks_linearly,
    case_aged_broadcast_stops_discovering,
    case_aged_broadcast_still_walks_pending_fan,
)
