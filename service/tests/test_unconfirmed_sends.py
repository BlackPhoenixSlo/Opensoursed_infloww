#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import send_marker_decide as smd  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, FollowupState, FunnelState, MassMessageFunnel, MassRun, Message,
)
import auth  # noqa: E402
import unconfirmed_sends_api as usa  # noqa: E402
from test_send_once import _get, _owner, _retry, _status  # noqa: E402 — the shared owner/GET/Retry

a11._STEP_GAP_S = 0
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)
OLD = datetime.utcnow().replace(microsecond=0) - timedelta(seconds=2000)
CTX = json.dumps({"replied": True, "bought": False, "substantive": True, "reply_text": "yo"})
STEPS = [{"step": 1, "messages": ["m1"]}, {"step": 2, "messages": ["m2"]}]


class FakeOF:
    def __init__(self):
        self.sent: list[str] = []
        self._id = 9_500_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._id += 1
        self.sent.append(text)
        return {"id": self._id, "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}


def _fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _funnel_run(aid: str, steps=STEPS, *, funnel: bool = True) -> int:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        fid = None
        if funnel:
            f = MassMessageFunnel(name=f"us_{aid}", opening_message="hey",
                                  media_indices="[]", steps_json=json.dumps(steps))
            s.add(f)
            await s.flush()
            fid = int(f.id)
        mr = MassRun(account_id=aid, funnel_id=fid, status="ok", recipient_count=1,
                     started_at=T0)
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _marked(mr: int, fan: int, *, step: int = 0, sending_at=OLD, unconfirmed_at=None,
                  replied: bool = True, aid: str | None = None) -> None:
    async with get_session() as s:
        s.add(FunnelState(mass_run_id=mr, fan_id=fan, current_step=step, check_count=0,
                          status="pending", next_check_at=T0, sending_at=sending_at,
                          sending_ctx=CTX, unconfirmed_at=unconfirmed_at,
                          last_error="may not have sent: x" if unconfirmed_at else None))
        if replied and aid:
            s.add(Message(account_id=aid, fan_id=fan, message_id=4_000_000 + fan,
                          direction="out", body="hey", created_at=T0, mass_run_id=mr))
            s.add(Message(account_id=aid, fan_id=fan, message_id=4_100_000 + fan,
                          direction="in", body="yo", created_at=T0 + timedelta(minutes=5)))


async def _row(mr: int, fan: int) -> FunnelState:
    async with get_session() as s:
        return await s.get(FunnelState, (mr, fan))


async def _seed_followup(aid: str, fan: int, *, sending_at=OLD, step: int = 2) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(FollowupState(account_id=aid, fan_id=fan, phase="tracking", cycle=1,
                            messages_sent='{"1": "2026-10-01T00:00:00"}',
                            sending_at=sending_at, sending_ctx=json.dumps({"step": step})))



async def case_get_lists_only_this_creators_rows_and_writes_nothing():
    a, b = "acc_us_a", "acc_us_b"
    mra, mrb = await _funnel_run(a), await _funnel_run(b)
    await _marked(mra, 1, step=1, unconfirmed_at=OLD + timedelta(seconds=5))
    await _marked(mra, 2, sending_at=datetime.utcnow())
    await _marked(mrb, 3)
    await _seed_followup(a, 4)
    await _seed_followup(b, 5)
    async with get_session() as s:
        before = [tuple(r) for r in (await s.execute(
            FunnelState.__table__.select())).all()]
    rows = await _get(a)
    async with get_session() as s:
        after = [tuple(r) for r in (await s.execute(
            FunnelState.__table__.select())).all()]
    assert before == after, "GET writes nothing"
    got = sorted((r["kind"], r["fan_id"], r["mass_run_id"], r["step_label"], r["state"])
                 for r in rows)
    assert got == [("followup", "4", None, "STEP 2", "UNCONFIRMED"),
                   ("funnel", "1", mra, "STEP 2", "UNCONFIRMED"),
                   ("funnel", "2", mra, "STEP 1", "IN_FLIGHT")], got
    one = next(r for r in rows if r["fan_id"] == "1")
    assert one["since"] == OLD.isoformat() + "Z" and one["last_error"] == "may not have sent: x", one
    assert one["step"] == 2, one


async def case_funnel_less_row_never_listed():
    aid = "acc_us_nofunnel"
    mr = await _funnel_run(aid, funnel=False)
    await _marked(mr, 11)
    assert await _get(aid) == []
    assert await _status(_retry(aid, kind="funnel", fan_id=11, mass_run_id=mr)) == 404
    assert (await _row(mr, 11)).sending_at == OLD, "funnel-less row untouched"



async def case_retry_settle_hit_is_already_sent_no_send():
    aid = "acc_us_hit"
    mr = await _funnel_run(aid)
    await _marked(mr, 21, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=21, message_id=4_200_021, direction="out",
                      body="m1", automation_kind="reply_mass_funnel", mass_run_id=mr,
                      funnel_step=1, created_at=OLD + timedelta(seconds=1)))
    fake = _fake()
    assert await _retry(aid, kind="funnel", fan_id=21, mass_run_id=mr) == {"status": "already_sent"}
    r = await _row(mr, 21)
    assert (r.sending_at, r.unconfirmed_at, r.current_step, r.last_sent_step) == (None, None, 1, 0), r
    assert r.last_error is None, ("the settle's Sent save drops may-not-have-sent", r.last_error)
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == [], ("landed: never re-sent", fake.sent)


async def case_retry_unmarked_row_is_already_sent():
    aid = "acc_us_unmarked"
    mr = await _funnel_run(aid)
    await _marked(mr, 31, sending_at=None)
    assert await _retry(aid, kind="funnel", fan_id=31, mass_run_id=mr) == {"status": "already_sent"}
    await _seed_followup(aid, 32, sending_at=None)
    assert await _retry(aid, kind="followup", fan_id=32) == {"status": "already_sent"}


async def case_retry_unknown_row_404():
    aid = "acc_us_404"
    mr = await _funnel_run(aid)
    assert await _status(_retry(aid, kind="funnel", fan_id=41, mass_run_id=mr)) == 404
    assert await _status(_retry(aid, kind="followup", fan_id=41)) == 404
    other = await _funnel_run("acc_us_404b")
    await _marked(other, 42)
    assert await _status(_retry(aid, kind="funnel", fan_id=42, mass_run_id=other)) == 404, \
        "another Creator's run is not this Creator's row"
    assert await _status(_retry(aid, kind="funnel", fan_id=41)) == 422, "funnel needs mass_run_id"


async def case_foreign_creator_403():
    aid = "acc_us_foreign"
    mr = await _funnel_run(aid)
    await _marked(mr, 51)
    assert await _status(_get(aid, as_=("acc_us_mine",))) == 403
    assert await _status(_retry(aid, as_=("acc_us_mine",), kind="funnel", fan_id=51,
                                mass_run_id=mr)) == 403
    assert (await _row(mr, 51)).sending_at == OLD


async def case_retry_stale_in_flight_is_retried_then_sent_once():
    aid = "acc_us_stale"
    mr = await _funnel_run(aid)
    await _marked(mr, 61, aid=aid)
    fake = _fake()
    assert await _retry(aid, kind="funnel", fan_id=61, mass_run_id=mr) == {"status": "retried"}
    r = await _row(mr, 61)
    assert (r.sending_at, r.sending_ctx, r.unconfirmed_at, r.status) == (None, None, None, "pending"), r
    assert r.next_check_at <= datetime.utcnow(), r.next_check_at
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == ["m1"], fake.sent
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == ["m1"], ("exactly once", fake.sent)
    assert await _get(aid) == []


async def case_retry_fresh_in_flight_409():
    aid = "acc_us_fresh"
    mr = await _funnel_run(aid)
    now = datetime.utcnow()
    await _marked(mr, 71, sending_at=now)
    assert smd.marker_state(now, None, smd.BOOT_TS, datetime.utcnow()) == smd.IN_FLIGHT
    assert await _status(_retry(aid, kind="funnel", fan_id=71, mass_run_id=mr)) == 409
    assert (await _row(mr, 71)).sending_at == now


async def case_retry_shortened_funnel_row_is_retried():
    aid = "acc_us_short"
    mr = await _funnel_run(aid, [{"step": 1, "messages": ["m1"]}])
    await _marked(mr, 81, step=3, aid=aid, unconfirmed_at=OLD)
    assert [r["step_label"] for r in await _get(aid)] == ["STEP 4"]
    assert await _retry(aid, kind="funnel", fan_id=81, mass_run_id=mr) == {"status": "retried"}
    assert (await _row(mr, 81)).last_error is None, "the Retry drops may-not-have-sent"
    fake = _fake()
    await run_once(aid, "reply_mass_funnel", payload={})
    r = await _row(mr, 81)
    assert r.status == "done" and fake.sent == [], (r.status, fake.sent)


async def case_retry_row_changed_under_the_clear_is_read_again():
    aid = "acc_us_race"
    mr = await _funnel_run(aid)
    real = a11.retry_clear
    for fan, then, want in ((101, None, {"status": "already_sent"}),
                            (102, datetime.utcnow(), 409)):
        await _marked(mr, fan, unconfirmed_at=OLD)

        async def _raced(account_id, fan_id, mass_run_id, sending_at, now, then=then):
            async with get_session() as s:
                st = await s.get(FunnelState, (mass_run_id, fan_id))
                st.sending_at, st.unconfirmed_at = then, None
            return await real(account_id, fan_id, mass_run_id, sending_at, now)
        a11.retry_clear = _raced
        try:
            got = _retry(aid, kind="funnel", fan_id=fan, mass_run_id=mr)
            got = await (got if isinstance(want, dict) else _status(got))
        finally:
            a11.retry_clear = real
        assert got == want, (fan, got)


async def case_retry_followup_row_is_retried():
    aid = "acc_us_fu"
    await _seed_followup(aid, 91)
    assert await _retry(aid, kind="followup", fan_id=91) == {"status": "retried"}
    async with get_session() as s:
        r = await s.get(FollowupState, (aid, 91))
    assert (r.sending_at, r.sending_ctx, r.unconfirmed_at) == (None, None, None), r
    assert json.loads(r.messages_sent) == {"1": "2026-10-01T00:00:00"}, r.messages_sent


async def case_retry_from_a_stale_tab_after_a_retry_is_refused():
    aid = "acc_us_retry_stale"
    mr = await _funnel_run(aid)
    await _marked(mr, 161, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    await _seed_followup(aid, 162)
    listed = {r["fan_id"]: r["since"] for r in await _get(aid)}
    assert await _retry(aid, kind="funnel", fan_id=161, mass_run_id=mr, since=listed["161"]) == \
        {"status": "retried"}
    assert await _retry(aid, kind="followup", fan_id=162, since=listed["162"]) == {"status": "retried"}
    newer = OLD + timedelta(seconds=60)
    async with get_session() as s:
        st = await s.get(FunnelState, (mr, 161))
        st.sending_at, st.sending_ctx, st.unconfirmed_at = newer, CTX, newer + timedelta(seconds=5)
        fu = await s.get(FollowupState, (aid, 162))
        fu.sending_at, fu.sending_ctx = newer, json.dumps({"step": 2})
    for body in ({"kind": "funnel", "fan_id": 161, "mass_run_id": mr, "since": listed["161"]},
                 {"kind": "followup", "fan_id": 162, "since": listed["162"]}):
        try:
            await _retry(aid, **body)
            raise AssertionError(("a stale Retry cleared a newer attempt", body))
        except HTTPException as e:
            assert (e.status_code, e.detail) == (409, "this row changed since it was listed: refresh"), e
    assert (await _row(mr, 161)).sending_at == newer, "attempt B's mark untouched"
    async with get_session() as s:
        assert (await s.get(FollowupState, (aid, 162))).sending_at == newer
    assert await _status(_retry(aid, kind="followup", fan_id=162, since="not a time")) == 422
    b = (newer + timedelta(hours=2)).isoformat() + "+02:00"
    assert await _retry(aid, kind="followup", fan_id=162, since=b) == {"status": "retried"}


async def _dismiss(aid: str, *, as_=None, **body) -> dict:
    tok = _owner(*(as_ or (aid,)))
    try:
        return await usa.dismiss_unconfirmed_send(account_id=aid, body=usa.DismissBody(**body))
    finally:
        auth._request_user.reset(tok)


_SAVED = ("current_step", "last_sent_step", "status", "check_count", "sending_at",
          "sending_ctx", "unconfirmed_at", "last_error")


async def case_dismiss_saves_the_step_sent_like_the_settle_and_never_resends():
    aid = "acc_us_dismiss"
    mr = await _funnel_run(aid)
    await _marked(mr, 111, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    await _marked(mr, 112, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=112, message_id=4_200_112, direction="out",
                      body="m1", automation_kind="reply_mass_funnel", mass_run_id=mr,
                      funnel_step=1, created_at=OLD + timedelta(seconds=1)))
        s.add(Message(account_id=aid, fan_id=111, message_id=4_200_111, direction="out",
                      body="m1", created_at=OLD + timedelta(seconds=1)))
    hint = next(r["hint"] for r in await _get(aid) if r["fan_id"] == "111")
    assert hint and hint["message_id"] == "4200111", hint
    fake = _fake()
    assert await _dismiss(aid, kind="funnel", fan_id=111, mass_run_id=mr, since=OLD.isoformat() + "Z",
                          hint_message_id=hint["message_id"]) == {"status": "dismissed"}
    assert await _retry(aid, kind="funnel", fan_id=112, mass_run_id=mr) == {"status": "already_sent"}
    async with get_session() as s:
        m = await s.get(Message, (aid, 111, 4_200_111))
    assert (m.automation_kind, m.mass_run_id, m.funnel_step) == ("reply_mass_funnel", mr, 1), \
        ("the confirmed copy carries the step's tags, as a confirmed send's row", m.__dict__)
    got, settled = await _row(mr, 111), await _row(mr, 112)
    assert [getattr(got, c) for c in _SAVED] == [getattr(settled, c) for c in _SAVED], \
        ("saved as the settle saves a landed step", got.__dict__, settled.__dict__)
    assert (got.sending_at, got.unconfirmed_at, got.current_step, got.last_sent_step) == \
        (None, None, 1, 0), got.__dict__
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == [], ("dismissed: never re-sent, the next step waits for a reply", fake.sent)
    assert await _dismiss(aid, kind="funnel", fan_id=111, mass_run_id=mr, since=OLD.isoformat() + "Z") == \
        {"status": "already_sent"}, "idempotent"
    assert await _get(aid) == []


async def case_dismiss_race_with_the_settle_keeps_the_winners_tag():
    aid = "acc_us_dismiss_race"
    mr = await _funnel_run(aid)
    await _marked(mr, 151, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=151, message_id=4_200_151, direction="out",
                      body="m1", created_at=OLD + timedelta(seconds=1)))
    since = next(r["since"] for r in await _get(aid) if r["fan_id"] == "151")
    real = a11.smst.tag_out

    async def _tag_then_settle(*a, **kw):
        ok = await real(*a, **kw)
        await a11.settle_landed(aid, smd.BOOT_TS, datetime.utcnow())
        return ok
    a11.smst.tag_out = _tag_then_settle
    try:
        got = await _dismiss(aid, kind="funnel", fan_id=151, mass_run_id=mr, since=since,
                             hint_message_id="4200151")
    finally:
        a11.smst.tag_out = real
    assert got == {"status": "already_sent"}, got
    async with get_session() as s:
        m = await s.get(Message, (aid, 151, 4_200_151))
    assert (m.automation_kind, m.mass_run_id, m.funnel_step) == ("reply_mass_funnel", mr, 1), \
        ("the settle saved the step by this tag: it stays", m.__dict__)
    r = await _row(mr, 151)
    assert (r.sending_at, r.current_step, r.last_sent_step) == (None, 1, 0), r.__dict__
    fake = _fake()
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == [], ("no reply after the confirmed step: nothing sent", fake.sent)


async def case_dismiss_without_hint_waits_for_a_new_reply():
    aid = "acc_us_dismiss_nohint"
    mr = await _funnel_run(aid)
    await _marked(mr, 152, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    since = next(r["since"] for r in await _get(aid) if r["fan_id"] == "152")
    assert await _dismiss(aid, kind="funnel", fan_id=152, mass_run_id=mr, since=since) == \
        {"status": "dismissed"}
    r = await _row(mr, 152)
    assert (r.sending_at, r.current_step, r.last_sent_step) == (None, 1, 0), r.__dict__
    fake = _fake()
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == [], ("the old reply is not one to the confirmed step", fake.sent)


async def case_settled_send_stamped_before_the_mark_counts_a_reply_after_it():
    aid = "acc_us_skewed_out"
    mr = await _funnel_run(aid)
    await _marked(mr, 155, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=155, message_id=4_200_155, direction="out",
                      body="m1", automation_kind="reply_mass_funnel", mass_run_id=mr,
                      funnel_step=1, created_at=OLD - timedelta(seconds=10)))
        s.add(Message(account_id=aid, fan_id=155, message_id=4_300_155, direction="in",
                      body="sure, tell me more", created_at=OLD - timedelta(seconds=5)))
    fake = _fake()
    assert await _retry(aid, kind="funnel", fan_id=155, mass_run_id=mr) == {"status": "already_sent"}
    r = await _row(mr, 155)
    assert (r.sending_at, r.current_step, r.confirmed_sent_at) == (None, 1, OLD), r.__dict__
    await run_once(aid, "reply_mass_funnel", payload={})
    assert fake.sent == ["m2"], ("the reply after the step's own row is one to it", fake.sent)


async def case_dismiss_after_a_retry_is_refused_not_already_sent():
    aid = "acc_us_dismiss_retried"
    mr = await _funnel_run(aid)
    await _marked(mr, 153, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    await _seed_followup(aid, 154)
    listed = {r["fan_id"]: r["since"] for r in await _get(aid)}
    assert await _retry(aid, kind="funnel", fan_id=153, mass_run_id=mr) == {"status": "retried"}
    assert await _retry(aid, kind="followup", fan_id=154) == {"status": "retried"}
    assert await _status(_dismiss(aid, kind="funnel", fan_id=153, mass_run_id=mr,
                                  since=listed["153"])) == 409
    try:
        await _dismiss(aid, kind="followup", fan_id=154, since=listed["154"])
        raise AssertionError("a retried row dismissed")
    except HTTPException as e:
        assert (e.status_code, e.detail) == (409, "this row changed since it was listed: refresh"), e
    r = await _row(mr, 153)
    assert (r.current_step, r.status, r.confirmed_sent_at) == (0, "pending", None), r.__dict__
    async with get_session() as s:
        fu = await s.get(FollowupState, (aid, 154))
    assert json.loads(fu.messages_sent) == {"1": "2026-10-01T00:00:00"}, fu.messages_sent


async def case_dismiss_compares_since_as_a_time_not_a_string():
    aid = "acc_us_dismiss_since_fmt"
    mr = await _funnel_run(aid)
    await _marked(mr, 155, aid=aid, unconfirmed_at=OLD + timedelta(seconds=5))
    await _seed_followup(aid, 156)
    since = (OLD + timedelta(hours=2)).isoformat() + "+02:00"
    assert await _dismiss(aid, kind="funnel", fan_id=155, mass_run_id=mr, since=since) == \
        {"status": "dismissed"}
    assert await _dismiss(aid, kind="funnel", fan_id=155, mass_run_id=mr, since=since) == \
        {"status": "already_sent"}
    assert await _dismiss(aid, kind="followup", fan_id=156, since=since) == {"status": "dismissed"}
    assert await _dismiss(aid, kind="followup", fan_id=156, since=since) == {"status": "already_sent"}
    assert await _status(_dismiss(aid, kind="followup", fan_id=156, since="not a time")) == 422


async def case_dismiss_followup_saves_the_nudge_sent():
    aid = "acc_us_dismiss_fu"
    await _seed_followup(aid, 121)
    try:
        await _dismiss(aid, kind="followup", fan_id=121, since="2020-01-01T00:00:00Z")
        raise AssertionError("a stale since dismissed the row")
    except HTTPException as e:
        assert e.status_code == 409, e
    listed = next(r["since"] for r in await _get(aid) if r["fan_id"] == "121")
    assert await _dismiss(aid, kind="followup", fan_id=121, since=listed) == {"status": "dismissed"}
    async with get_session() as s:
        r = await s.get(FollowupState, (aid, 121))
    assert (r.sending_at, r.sending_ctx, r.unconfirmed_at) == (None, None, None), r.__dict__
    sent = json.loads(r.messages_sent)
    assert sent["1"] == "2026-10-01T00:00:00" and sent["2"].startswith(OLD.isoformat()), sent
    assert await _dismiss(aid, kind="followup", fan_id=121, since=listed) == {"status": "already_sent"}


async def case_dismiss_refusals():
    aid = "acc_us_dismiss_no"
    mr = await _funnel_run(aid)
    now = datetime.utcnow()
    await _marked(mr, 131, sending_at=now)
    assert await _status(_dismiss(aid, kind="funnel", fan_id=131, mass_run_id=mr,
                                  since=now.isoformat() + "Z")) == 409
    assert (await _row(mr, 131)).sending_at == now
    short_aid = "acc_us_dismiss_short"
    short = await _funnel_run(short_aid, [{"step": 1, "messages": ["m1"]}])
    await _marked(short, 132, step=3, unconfirmed_at=OLD)
    assert await _status(_dismiss(short_aid, kind="funnel", fan_id=132, mass_run_id=short,
                                  since=OLD.isoformat() + "Z")) == 409
    assert (await _row(short, 132)).sending_at == OLD, "a step it can't save stays listed"
    assert await _status(_dismiss(aid, kind="funnel", fan_id=133, mass_run_id=mr, since=OLD.isoformat() + "Z")) == 404
    assert await _status(_dismiss(aid, kind="funnel", fan_id=133, since=OLD.isoformat() + "Z")) == 422
    other = await _funnel_run("acc_us_dismiss_other")
    await _marked(other, 134, unconfirmed_at=OLD)
    assert await _status(_dismiss("acc_us_dismiss_other", as_=(aid,), kind="funnel",
                                  fan_id=134, mass_run_id=other, since=OLD.isoformat() + "Z")) == 403
    assert await _status(_dismiss(aid, kind="funnel", fan_id=134, mass_run_id=other,
                                  since=OLD.isoformat() + "Z")) == 404, \
        "another Creator's run is not this Creator's row"
    assert (await _row(other, 134)).sending_at == OLD


async def case_get_hint_is_the_first_untagged_send_since_the_mark():
    aid = "acc_us_hint"
    mr = await _funnel_run(aid)
    await _marked(mr, 141, aid=aid, unconfirmed_at=OLD)
    await _marked(mr, 142, aid=aid, unconfirmed_at=OLD)
    long = "x" * 80
    from db.models import Employee
    async with get_session() as s:
        s.add(Employee(id=7707, display_name="Chatter"))
    async with get_session() as s:
        s.add_all([
            Message(account_id=aid, fan_id=141, message_id=4_300_001, direction="out",
                    body=long, created_at=OLD + timedelta(seconds=30)),
            Message(account_id=aid, fan_id=141, message_id=4_300_002, direction="out",
                    body="later", created_at=OLD + timedelta(seconds=90)),
            Message(account_id=aid, fan_id=142, message_id=4_300_003, direction="out", body="tagged",
                    automation_kind="reply_mass_funnel", created_at=OLD + timedelta(seconds=30)),
            Message(account_id=aid, fan_id=142, message_id=4_300_004, direction="in",
                    body="fan", created_at=OLD + timedelta(seconds=30)),
            Message(account_id=aid, fan_id=142, message_id=4_300_005, direction="out",
                    body="before", created_at=OLD - timedelta(hours=1)),
            Message(account_id=aid, fan_id=142, message_id=4_300_006, direction="out", body="chatter",
                    sent_by_employee_id=7707, created_at=OLD + timedelta(seconds=40)),
            Message(account_id=aid, fan_id=142, message_id=4_300_007, direction="out",
                    body="much later", created_at=OLD + timedelta(hours=1)),
        ])
    hints = {r["fan_id"]: r["hint"] for r in await _get(aid)}
    assert hints == {"141": {"message_id": "4300001", "at": (OLD + timedelta(seconds=30)).isoformat()
                             + "Z", "text": "x" * 60},
                     "142": None}, hints
    for bad in (4_300_006, 4_300_007, 4_300_001, 4_300_003, 4_300_004, 4_300_005):
        got = await _dismiss(aid, kind="funnel", fan_id=142, mass_run_id=mr, hint_message_id=bad,
                             since=OLD.isoformat() + "Z")
        assert got["status"] in ("dismissed", "already_sent"), got
    async with get_session() as s:
        tags = {m.message_id: (m.automation_kind, m.mass_run_id) for m in (await s.execute(
            Message.__table__.select().where(Message.account_id == aid,
                                             Message.message_id >= 4_300_001))).all()}
    assert tags == {4_300_001: (None, None), 4_300_002: (None, None),
                    4_300_003: ("reply_mass_funnel", None), 4_300_004: (None, None),
                    4_300_005: (None, None), 4_300_006: (None, None), 4_300_007: (None, None)}, tags


def case_http_wiring():
    import os
    os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
    try:
        c = _harness.make_client()
        aid = "acc_us_http"
        import asyncio
        mr = asyncio.run(_funnel_run(aid))
        asyncio.run(_marked(mr, 99))
        r = c.get("/admin/unconfirmed-sends", params={"account_id": aid})
        assert r.status_code == 200, r.text
        row = r.json()["rows"][0]
        assert set(row) == {"kind", "fan_id", "mass_run_id", "step", "step_label", "since",
                            "last_error", "state", "hint"}, row
        r = c.post("/admin/unconfirmed-sends/retry", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "99", "mass_run_id": mr})
        assert r.status_code == 422, ("`since` is required", r.text)
        r = c.post("/admin/unconfirmed-sends/retry", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "99", "mass_run_id": mr, "since": row["since"]})
        assert (r.status_code, r.json()) == (200, {"status": "retried"}), r.text
        r = c.post("/admin/unconfirmed-sends/retry", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "98", "mass_run_id": mr,
                         "since": OLD.isoformat() + "Z"})
        assert r.status_code == 404, r.text
        asyncio.run(_marked(mr, 97, unconfirmed_at=OLD))
        r = c.post("/admin/unconfirmed-sends/dismiss", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "97", "mass_run_id": mr})
        assert r.status_code == 422, ("`since` is required", r.text)
        r = c.post("/admin/unconfirmed-sends/dismiss", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "97", "mass_run_id": mr,
                         "since": OLD.isoformat() + "Z"})
        assert (r.status_code, r.json()) == (200, {"status": "dismissed"}), r.text
        r = c.post("/admin/unconfirmed-sends/dismiss", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "98", "mass_run_id": mr,
                         "since": OLD.isoformat() + "Z"})
        assert r.status_code == 404, r.text
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)


def _cells_on(*aids: str):
    import contextlib
    import os
    import send_ops

    @contextlib.contextmanager
    def on():
        os.environ.update(OI_CELL_MAP="/nonexistent/placement.json",
                          OI_ACCOUNTS=",".join(f"onlyfans:{a}" for a in aids))
        send_ops.install(f"sqlite:///{_harness.DB_PATH}")
        try:
            yield send_ops
        finally:
            os.environ.pop("OI_CELL_MAP", None)
            os.environ.pop("OI_ACCOUNTS", None)
    return on()


def _op(send_ops, aid: str, op: str, kind: str, target: str, state: str = "uncertain") -> None:
    import sqlite3
    with sqlite3.connect(str(_harness.DB_PATH)) as c:
        c.execute("INSERT INTO send_ops (account, op_id, kind, target, digest, state, attempts, created_at,"
                  " updated_at) VALUES (?,?,?,?,'d',?,1,'2026-11-26 10:00:00.000','2026-11-26 10:00:00.000')",
                  (aid, op, kind, target, state))


async def _resolve(aid: str, op: str, outcome: str, *, as_=None) -> int:
    tok = _owner(*(as_ or (aid,)))
    try:
        return await _status(usa.resolve_unconfirmed_send(account_id=aid,
                                                          body=usa.ResolveBody(op_id=op, outcome=outcome,
                                                                               updated_at="2026-11-26 10:00:00.000")))
    finally:
        auth._request_user.reset(tok)


def _audit(aid: str, op: str):
    import sqlite3
    with sqlite3.connect(str(_harness.DB_PATH)) as c:
        return c.execute("SELECT state, resolved_by, resolved_at FROM send_ops WHERE account=? AND op_id=?",
                         (aid, op)).fetchone()


async def case_cell_mode_lists_every_uncertain_op_kind_with_its_link_and_no_retry():
    aid, other = "acc_us_cell", "acc_us_cell_other"
    mr = await _funnel_run(aid)
    await _marked(mr, 61, unconfirmed_at=OLD + timedelta(seconds=5))
    with _cells_on(aid) as so:
        _op(so, aid, "op-composer", "composer", "62")
        _op(so, aid, "op-mass", "mass_job", "mass:7")
        _op(so, aid, "op-sched", "scheduled_send", "63")
        _op(so, aid, "op-sent", "composer", "64", state="sent")
        _op(so, other, "op-foreign", "composer", "65")
        rows = await _get(aid)
    ops = sorted((r["kind"], r["fan_id"], r["link"], r["since"]) for r in rows if "op_id" in r)
    assert ops == [("composer", "62", "chat", "2026-11-26T10:00:00Z"),
                   ("mass_job", "mass:7", "queue", "2026-11-26T10:00:00Z"),
                   ("scheduled_send", "63", "chat", "2026-11-26T10:00:00Z")], ops
    assert all(r["retry_allowed"] is False and r["state"] == "UNCONFIRMED" for r in rows), rows
    assert [r["fan_id"] for r in rows if "op_id" not in r] == ["61"], "the funnel marker stays listed"


async def case_cell_mode_resolve_both_ways_is_audited_and_owner_scoped():
    aid = "acc_us_cell_resolve"
    with _cells_on(aid) as so:
        _op(so, aid, "op-a", "composer", "71")
        _op(so, aid, "op-b", "composer", "72")
        assert await _resolve(aid, "op-a", "was_sent", as_=("someone_else",)) == 403
        assert _audit(aid, "op-a") == ("uncertain", None, None)
        assert await _resolve(aid, "op-a", "was_sent") == 200
        assert await _resolve(aid, "op-b", "not_sent") == 200
        assert await _resolve(aid, "op-a", "not_sent") == 404, "a marked op is not marked again"
        assert await _resolve(aid, "op-missing", "was_sent") == 404
        rows = await _get(aid)
    a, b = _audit(aid, "op-a"), _audit(aid, "op-b")
    assert a[:2] == ("resolved_sent", "user:once_owner") and a[2], a
    assert b[:2] == ("resolved_not_sent", "user:once_owner") and b[2], b
    assert not [r for r in rows if "op_id" in r], rows


async def case_cell_mode_composer_access_is_independent_of_funnel_opt_in():
    from unittest.mock import patch

    aid = "acc_us_composer"
    denied = HTTPException(403, "composer denied")
    with _cells_on(aid) as so:
        _op(so, aid, "op-composer", "composer", "42")
        with patch.object(usa, "opt_in_refusal", return_value="funnel disabled"):
            answer = await _get(aid)
            assert [row["op_id"] for row in answer] == ["op-composer"], answer
            with patch.object(usa, "route_refusal", return_value=(denied, [])):
                token = _owner(aid)
                try:
                    assert await _status(usa.list_unconfirmed_sends(aid)) == 403
                finally:
                    auth._request_user.reset(token)
            assert await _resolve(aid, "op-composer", "was_sent") == 200


async def case_cell_role_middleware_enforces_resolve_for_the_requested_creator():
    from starlette.requests import Request
    from starlette.responses import Response
    from unittest.mock import AsyncMock, patch

    import permissions
    import server

    aid = "acc_us_resolve_role"
    call_next = AsyncMock(return_value=Response())
    resolve_path = "/admin/unconfirmed-sends/resolve"
    list_path = "/admin/unconfirmed-sends"
    request = Request({"type": "http", "method": "POST", "path": resolve_path,
                       "query_string": f"account_id={aid}".encode(), "headers": []})
    with _cells_on(aid):
        refusal = HTTPException(403, "send permission denied")
        policy = AsyncMock(return_value=(refusal, []))
        with patch.object(permissions, "route_refusal", policy):
            response = await permissions.role_enforcement_middleware(request, call_next)
        assert response.status_code == 403
        assert policy.await_args.args[:4] == (("/messages-pro",), "POST", resolve_path, [aid])
        call_next.assert_not_called()
        assert permissions.role_enforcement_middleware in server._http_hooks.hooks
        assert permissions.route_pages(list_path, "GET") == ("/messages-pro", "/growth/auto-funnel")
    assert permissions.route_pages(list_path, "GET") == ("/growth/auto-funnel",)


async def case_unconfirmed_route_permissions_by_role_and_mode():
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import patch

    from starlette.requests import Request
    from starlette.responses import Response

    import permissions as policy

    aid = "acc_us_role_table"
    composer, funnel = policy.COMPOSER_PAGE, "/growth/auto-funnel"
    base = policy.UNCONFIRMED_SENDS
    routes = (("GET", base), ("POST", policy.RESOLVE_SEND),
              ("POST", f"{base}/retry"), ("POST", f"{base}/dismiss"))
    for cell_mode in (False, True):
        with _cells_on(aid) if cell_mode else nullcontext():
            for role, grants, legacy, cell in (
                ("owner", (), (200, 200, 200, 200), (200, 200, 200, 200)),
                ("both", (composer, funnel), (200, 200, 200, 200), (200, 200, 200, 200)),
                ("composer", (composer,), (403, 403, 403, 403), (200, 200, 403, 403)),
                ("funnel", (funnel,), (200, 200, 200, 200), (200, 403, 200, 200)),
                ("ungranted", (), (403, 403, 403, 403), (403, 403, 403, 403)),
                ("disabled", (composer, funnel), (403, 403, 403, 403), (403, 403, 403, 403)),
                ("enforcement_off", (), (403, 403, 403, 403), (200, 200, 403, 403)),
            ):
                blob = {"enforce": role != "enforcement_off", "assignments": {"1": role},
                        "roles": [{"id": role, "permissions": dict.fromkeys(grants, True),
                                   "disabled": role == "disabled"}]}
                ctx = policy.AgencyContext("agency", 1, role == "owner", False)

                async def opt_in_refusal(pages, account_id):
                    assert account_id == aid
                    if not policy.opt_in_granted(ctx, blob).intersection(pages):
                        return policy.denied_detail(pages)

                async def next_route(_):
                    return Response()

                with (patch.object(policy, "agency_chatter", return_value=SimpleNamespace(owner_user_ids=())),
                      patch.object(policy, "_enforcing_roles", return_value={"agency": blob}
                                   if policy.enforced(blob) else None),
                      patch.object(policy, "agency_contexts", return_value=[ctx]),
                      patch.object(policy, "opt_in_refusal", side_effect=opt_in_refusal)):
                    for (method, path), status in zip(routes, cell if cell_mode else legacy, strict=True):
                        req = Request({"type": "http", "method": method, "path": path,
                                       "query_string": f"account_id={aid}".encode(), "headers": []})
                        response = await policy.role_enforcement_middleware(req, next_route)
                        assert response.status_code == status, (cell_mode, role, path, response.status_code)
            if cell_mode:
                with patch.object(policy, "_writers", wraps=policy._writers) as writers:
                    assert policy.route_pages(policy.RESOLVE_SEND, "POST") == (composer,)
                    writers.assert_called_once_with(policy.RESOLVE_SEND, (composer,))


async def case_cell_mode_retry_is_off_before_any_settle_or_clear():
    aid = "acc_us_cell_retry"
    mr = await _funnel_run(aid)
    await _marked(mr, 81, unconfirmed_at=OLD + timedelta(seconds=5))
    calls = []
    real = (a11.settle_landed, a11.retry_clear)

    async def settle(*a, **k):
        calls.append("settle")
        return await real[0](*a, **k)

    async def clear(*a, **k):
        calls.append("clear")
        return await real[1](*a, **k)
    a11.settle_landed, a11.retry_clear = settle, clear
    try:
        with _cells_on(aid):
            tok = _owner(aid)
            try:
                await usa.retry_unconfirmed_send(account_id=aid, body=usa.RetryBody(
                    kind="funnel", fan_id=81, mass_run_id=mr, since=OLD.isoformat() + "Z"))
                raise AssertionError("retry must refuse in Cell mode")
            except HTTPException as e:
                assert (e.status_code, e.detail) == (409, {"error": "retry_off_cell_mode"}), e.detail
            finally:
                auth._request_user.reset(tok)
            assert await _status(_retry(aid, kind="funnel", fan_id=81, mass_run_id=mr, as_=("x",))) == 403
    finally:
        a11.settle_landed, a11.retry_clear = real
    assert calls == [], calls
    st = await _row(mr, 81)
    assert st.sending_at == OLD and st.unconfirmed_at is not None, "marker untouched"


async def case_env_unset_rows_have_no_retry_flag():
    aid = "acc_us_env_unset"
    mr = await _funnel_run(aid)
    await _marked(mr, 91, unconfirmed_at=OLD + timedelta(seconds=5))
    rows = await _get(aid)
    assert rows and all("retry_allowed" not in r and "op_id" not in r for r in rows), rows


_harness.run()
