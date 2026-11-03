#!/usr/bin/env python3
"""
Send once (send_marker_decide / send_marker_store) through both drip senders:
the marker is committed right before the first OF call; a marked row is never
auto-sent; each tick's settle saves a dead attempt's landed step as sent; only
the user's Retry (unconfirmed_sends_api) sends a maybe-sent step again.

House funnel (reply_mass_funnel):
  case_once_*:   marked before bubble 0's call (after an emptied bubble, after the
                 hold; never on a dry run or a stale tick `now`); bubble 0 landed →
                 Sent (one PPV); an id-less return or a may-have-sent raise →
                 unconfirmed, never auto-resent; a 4xx or a raise before the call →
                 no marker; a marked row is not due; a fresh mark is IN_FLIGHT
                 (Retry 409); a Retry that cleared a live attempt's row wins over
                 the attempt's own failure write.
  case_settle_*: a dead attempt's landed step is saved Sent at `sending_at` (a
                 purchase since then converts), not listed; an id-less landing, an
                 IN_FLIGHT row, a funnel-less row and a shortened funnel's row are left
                 alone (the tick goes on).
Follow-up (send_followup):
  case_fu_once_*: a fresh fan with no row is marked after the DM-rate turn, before
                 the send; a 4xx clears it; a read timeout → unconfirmed, never
                 re-sent; a raise in the turn writes nothing and probes nothing; a
                 stale tick `now` still marks IN_FLIGHT (Retry 409).
  case_fu_settle_landed_is_sent_at_sending_at: a marked row whose nudge landed →
                 Sent(step, sending_at), marker cleared, nothing sent.

Also the shared fixtures of test_unconfirmed_sends.py (owner session, GET, Retry).

Run: ./venv/bin/python service/tests/test_send_once.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
import sqlite3  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from curl_cffi.requests import exceptions as curl_exc  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

import auth  # noqa: E402
import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import send_followup  # noqa: E402
from automations import send_marker_decide as smd  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Fan, FollowupState, FunnelAccountMedia, FunnelState, MassMessageFunnel,
    MassRun, Message,
)
from of_client import OFAPIError  # noqa: E402
import unconfirmed_sends_api as usa  # noqa: E402

a11._STEP_GAP_S = 0
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)   # broadcast time
T_REPLY1 = T0 + timedelta(minutes=5)


# ── Shared fixtures ───────────────────────────────────────────────────

class _Killed(BaseException):
    """The relay dies mid-call (SIGKILL stand-in): no handler runs, the marker stays."""


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def json(self) -> dict:
        return {"error": {"message": "bad request"}}


def _http_400() -> OFAPIError:
    return OFAPIError("400 for https://onlyfans.com/api2/v2/chats/1/messages\nbad request",
                      response=_Resp(400))


def _late_clock(real_dt, late: list):
    """`datetime` whose utcnow() runs 1000 s behind while late[0]: a tick's `now`
    taken before a long serial wait."""
    class _Clock(datetime):
        @classmethod
        def utcnow(cls):
            return real_dt.utcnow() - (timedelta(seconds=1000) if late[0] else timedelta())
    return _Clock


def _restart() -> None:
    """A new relay process: every marker of the old one is pre-boot (no live call)."""
    smd.BOOT_TS = datetime.utcnow()


def _owner(*aids: str):
    return auth._request_user.set(auth.AuthedUser("u_once", "once_owner", frozenset(aids)))


async def _get(aid: str, *, as_=None) -> list[dict]:
    tok = _owner(*(as_ or (aid,)))
    try:
        return (await usa.list_unconfirmed_sends(account_id=aid))["rows"]
    finally:
        auth._request_user.reset(tok)


async def _retry(aid: str, *, as_=None, **body) -> dict:
    tok = _owner(*(as_ or (aid,)))
    try:
        return await usa.retry_unconfirmed_send(account_id=aid, body=usa.RetryBody(**body))
    finally:
        auth._request_user.reset(tok)


async def _status(coro) -> int:
    try:
        await coro
    except HTTPException as e:
        return e.status_code
    return 200


def _db(sql: str, args: tuple):
    """Straight off the DB file (send_message runs in a worker thread)."""
    with sqlite3.connect(str(_harness.DB_PATH)) as c:
        return c.execute(sql, args).fetchone()


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


# ── House funnel ──────────────────────────────────────────────────────

_PPV2 = [{"step": 1, "type": "paid_ppv", "price": 24, "messages": ["ppv a", "ppv b"]}]
_PPV2_NEXT = [
    {"step": 1, "type": "paid_ppv", "price": 24, "messages": ["ppv a", "ppv b"],
     "next": {"default": 2}},
    {"step": 2, "messages": ["m2"]},
]


class ScriptedOF:
    """Bubble i does `script[i]`: "id" (landed, createdAt now), "noid" (returned
    without an id), "kill" (_Killed), a callable (run, then the next item is its
    answer: see case_once_retry_during_a_live_attempt_wins) or an exception
    instance (raised). Records every call's text and the row's marker then."""

    def __init__(self, script: list, mass_run_id: int):
        self.script, self.mr = list(script), mass_run_id
        self.calls: list[str] = []
        self.sent: list[dict] = []
        self.marker_at_call: list = []
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        i = len(self.calls)
        self.calls.append(text)
        self.marker_at_call.append(_db(
            "SELECT sending_at, unconfirmed_at FROM funnel_state WHERE mass_run_id=? AND fan_id=?",
            (self.mr, int(chat_id))))
        what = self.script[i] if i < len(self.script) else "id"
        if callable(what) and not isinstance(what, BaseException):
            what = what(int(chat_id))
        if what == "kill":
            raise _Killed()
        if isinstance(what, BaseException):
            raise what
        if what == "noid":
            return {"text": text}
        self._next_id += 1
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {"id": self._next_id, "text": text,
                "createdAt": datetime.utcnow().isoformat() + "+00:00"}


async def _seed_msg(aid: str, fan_id: int, mid: int, direction: str, created_at: datetime,
                    *, mass_run_id: int | None = None, body: str = "hi") -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=mid, direction=direction,
                      body=body, created_at=created_at, mass_run_id=mass_run_id))


async def _funnel_run(aid: str, steps: list[dict]) -> int:
    await _seed_account(aid)
    async with get_session() as s:
        f = MassMessageFunnel(name=f"once_{aid}", opening_message="hey", media_indices="[]",
                              steps_json=json.dumps(steps))
        s.add(f)
        await s.flush()
        s.add(FunnelAccountMedia(funnel_id=int(f.id), account_id=aid, opening_media_ids="[]",
                                 steps_media_json=json.dumps({"1": {"media_files": [111]}})))
        mr = MassRun(account_id=aid, funnel_id=int(f.id), status="ok", recipient_count=1,
                     started_at=T0)
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _replier(aid: str, mr: int, fan: int) -> None:
    """The broadcast to him + his reply: discovery enrolls him, step 1 is due."""
    await _seed_msg(aid, fan, 5_000_000_000_000_000 + mr * 100_000 + fan, "out", T0,
                    mass_run_id=mr, body="hey")
    await _seed_msg(aid, fan, 7_000_000 + fan, "in", T_REPLY1, body="haha a lot")


async def _ppv_fan(aid: str, fan: int, steps=None, *, script) -> tuple[int, ScriptedOF]:
    """A replier on a 2-bubble PPV step, the fake OF scripted per bubble."""
    mr = await _funnel_run(aid, steps or _PPV2)
    await _replier(aid, mr, fan)
    fake = ScriptedOF(script, mr)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return mr, fake


async def _tick(aid: str, **payload) -> dict | None:
    """One tick; None when the relay 'died' in it."""
    try:
        return await run_once(aid, "reply_mass_funnel", payload=payload)
    except _Killed:
        return None


async def _state(mass_run_id: int, fan_id: int) -> FunnelState | None:
    async with get_session() as s:
        return await s.get(FunnelState, (mass_run_id, fan_id))


async def _force_due(aid: str, mass_run_id: int, fan_id: int) -> None:
    """Time passes: the row is due, the send's rest and the fan lease are over."""
    async with get_session() as s:
        await s.execute(update(FunnelState).where(
            FunnelState.mass_run_id == mass_run_id, FunnelState.fan_id == fan_id
        ).values(next_check_at=datetime.utcnow() - timedelta(minutes=1)))
        await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == fan_id)
                        .values(automation_paused_until=None))
    await ax.release_fan_lease(aid, fan_id)


async def _seed_state(mass_run_id: int, fan_id: int, **values) -> None:
    async with get_session() as s:
        s.add(FunnelState(mass_run_id=mass_run_id, fan_id=fan_id, check_count=0,
                          status="pending", next_check_at=datetime.utcnow() - timedelta(minutes=1),
                          **values))


async def case_once_bubble0_landed_bubble1_4xx_is_sent():
    aid = "acc_once_partial"
    mr, fake = await _ppv_fan(aid, 90001, script=["id", _http_400()])
    res = await _tick(aid)
    assert res["advanced"] == 1 and res["errors"] == 1, res
    assert fake.calls == ["ppv a", "ppv b"], fake.calls
    assert fake.marker_at_call[0][0] is not None, "marked before bubble 0's call"
    st = await _state(mr, 90001)
    assert (st.status, st.current_step) == ("done", 1), st
    assert (st.sending_at, st.sending_ctx, st.unconfirmed_at) == (None, None, None), st
    await _force_due(aid, mr, 90001)
    await _tick(aid)
    assert fake.calls.count("ppv a") == 1, ("one PPV", fake.calls)


async def case_once_bubble0_noid_bubble1_4xx_is_unconfirmed():
    aid = "acc_once_noid"
    mr, fake = await _ppv_fan(aid, 90002, script=["noid", _http_400()])
    await _tick(aid)
    st = await _state(mr, 90002)
    assert st.status == "pending" and st.current_step == 0, st
    assert st.sending_at is not None and st.unconfirmed_at is not None, st
    assert st.last_error.startswith("may not have sent"), st.last_error
    assert json.loads(st.sending_ctx)["replied"] is True, st.sending_ctx
    await _force_due(aid, mr, 90002)
    await _tick(aid)
    assert fake.calls.count("ppv a") == 1, ("never auto-resent", fake.calls)


async def case_once_all_noid_is_unconfirmed():
    aid = "acc_once_allnoid"
    mr, fake = await _ppv_fan(aid, 90003, script=["noid", "noid"])
    res = await _tick(aid)
    assert res["advanced"] == 0 and res["errors"] == 1, res
    st = await _state(mr, 90003)
    assert st.unconfirmed_at is not None and st.status == "pending", st
    assert st.last_error == "may not have sent: send returned no id", st.last_error
    assert [r["state"] for r in await _get(aid)] == ["UNCONFIRMED"]


async def case_once_bubble0_4xx_clears_the_marker():
    aid = "acc_once_4xx"
    mr, fake = await _ppv_fan(aid, 90004, script=[_http_400(), "id", "id"])
    await _tick(aid)
    st = await _state(mr, 90004)
    assert (st.sending_at, st.unconfirmed_at, st.status) == (None, None, "pending"), st
    await _force_due(aid, mr, 90004)
    res = await _tick(aid)
    assert res["advanced"] == 1, ("surely not sent → retried as before", res)


async def case_once_bubble0_read_timeout_is_unconfirmed():
    aid = "acc_once_timeout"
    mr, fake = await _ppv_fan(aid, 90005, script=[curl_exc.ReadTimeout("read timed out")])
    await _tick(aid)
    st = await _state(mr, 90005)
    assert st.unconfirmed_at is not None and st.sending_at is not None, st
    assert "read timed out" in st.last_error, st.last_error
    await _force_due(aid, mr, 90005)
    await _tick(aid)
    assert fake.calls == ["ppv a"], fake.calls


async def case_once_retry_during_a_live_attempt_wins():
    """A Retry clears a >900 s mark while its call is still out; the call then
    raises a may-have-sent timeout: its write must not re-mark the row (it is
    conditional on the mark it wrote), so the Retry's clear stands."""
    aid = "acc_once_live"

    def _retry_meanwhile(fan: int):
        with sqlite3.connect(str(_harness.DB_PATH)) as c:   # the Retry's clear
            c.execute("UPDATE funnel_state SET sending_at=NULL, sending_ctx=NULL WHERE fan_id=?",
                      (fan,))
        return curl_exc.ReadTimeout("read timed out")
    mr, fake = await _ppv_fan(aid, 90020, script=[_retry_meanwhile])
    await _tick(aid)
    st = await _state(mr, 90020)
    assert (st.sending_at, st.unconfirmed_at, st.status) == (None, None, "pending"), st
    await _force_due(aid, mr, 90020)
    await _tick(aid)
    assert fake.calls == ["ppv a", "ppv a", "ppv b"], ("the Retry's send", fake.calls)


async def case_once_slot_lost_in_bubble0_hold_leaves_no_marker():
    aid = "acc_once_slot"
    mr, fake = await _ppv_fan(aid, 90006, script=["id", "id"])
    with _harness.slot_lost_at_hold(a11, 1):
        res = await _tick(aid)
    assert res["status"] == "error" and fake.calls == [], (res, fake.calls)
    st = await _state(mr, 90006)
    assert (st.sending_at, st.unconfirmed_at, st.status) == (None, None, "pending"), st


async def case_once_emptied_bubble0_marks_before_bubble1():
    aid = "acc_once_empty0"
    mr, fake = await _ppv_fan(aid, 90007, [{"step": 1, "messages": ["gone", "kept"]}],
                              script=["id"])
    real, marks = a11.apply_word_restriction, []
    real_mark = a11.smst.mark

    async def _counting(*a):
        marks.append(a)
        return await real_mark(*a)
    a11.apply_word_restriction = lambda t: "" if t == "gone" else real(t)
    a11.smst.mark = _counting
    try:
        res = await _tick(aid)
    finally:
        a11.apply_word_restriction, a11.smst.mark = real, real_mark
    assert res["advanced"] == 1 and fake.calls == ["kept"], (res, fake.calls)
    assert fake.marker_at_call[0][0] is not None and len(marks) == 1, (fake.marker_at_call, marks)
    st = await _state(mr, 90007)
    assert st.sending_at is None and st.current_step == 1, st


async def case_once_marked_row_is_not_due():
    aid = "acc_once_notdue"
    mr, fake = await _ppv_fan(aid, 90008, script=["id", "id"])
    await _replier(aid, mr, 90009)
    await _seed_state(mr, 90008, current_step=0, sending_at=datetime.utcnow())
    await _seed_state(mr, 90009, current_step=0, sending_at=T0, unconfirmed_at=T0)
    res = await _tick(aid)
    assert res["advanced"] == 0 and fake.calls == [], (res, fake.calls)


async def case_once_dry_run_marks_and_settles_nothing():
    aid = "acc_once_dry"
    mr, fake = await _ppv_fan(aid, 90010, script=["id", "kill"])
    await _tick(aid)                                  # bubble 0 landed, then died
    _restart()
    res = await _tick(aid, dry_run=True)
    st = await _state(mr, 90010)
    assert st.sending_at is not None and st.current_step == 0, ("dry run settles nothing", st)
    assert res["advanced"] == 0, res
    # a dry run over a fresh replier marks nothing either
    await _replier(aid, mr, 90011)
    res = await _tick(aid, dry_run=True)
    assert res["advanced"] == 1 and await _state(mr, 90011) is None, res


async def case_once_stale_tick_now_marks_in_flight_and_retry_409s():
    """The mark is the wall clock at the mark, not the tick's `now`: a serial tick
    whose `now` is 1000 s old still marks a live send IN_FLIGHT (Retry 409)."""
    aid = "acc_once_stale"
    mr, fake = await _ppv_fan(aid, 90012, script=["kill"])
    real_dt, real_hold, late = a11.datetime, a11.hold_with_typing, [True]

    async def _hold(*a, **k):
        late[0] = False                    # the serial wait: the tick's `now` aged
        return await real_hold(*a, **k)
    a11.datetime, a11.hold_with_typing = _late_clock(real_dt, late), _hold
    try:
        assert await _tick(aid) is None
    finally:
        a11.datetime, a11.hold_with_typing = real_dt, real_hold
    st = await _state(mr, 90012)
    assert datetime.utcnow() - st.sending_at < timedelta(seconds=60), st.sending_at
    assert smd.marker_state(st.sending_at, st.unconfirmed_at, smd.BOOT_TS,
                            datetime.utcnow()) == smd.IN_FLIGHT
    assert await _status(_retry(aid, kind="funnel", fan_id=90012, mass_run_id=mr)) == 409


async def case_settle_killed_after_bubble0_advances_not_listed():
    aid = "acc_settle_landed"
    mr, fake = await _ppv_fan(aid, 90013, script=["id", "kill"])
    assert await _tick(aid) is None
    marked = (await _state(mr, 90013)).sending_at
    assert marked is not None
    assert [r["state"] for r in await _get(aid)] == ["IN_FLIGHT"]
    _restart()
    await ax.release_fan_lease(aid, 90013)
    res = await _tick(aid)
    st = await _state(mr, 90013)
    assert (st.status, st.current_step, st.sending_at) == ("done", 1, None), st
    assert st.last_ppv_sent_at == marked, ("Sent at sending_at, never now", st.last_ppv_sent_at)
    assert fake.calls.count("ppv a") == 1, ("one PPV", fake.calls, res)
    assert await _get(aid) == []


async def case_settle_uses_sending_at_so_a_purchase_converts():
    """PPV step with a `next` map, bought between the send and the settle: the
    settle stamps last_ppv_sent_at = sending_at, so the next tick sees the
    purchase (Checked bought → Convert). Stamping `now` would hide it."""
    aid = "acc_settle_bought"
    mr, fake = await _ppv_fan(aid, 90014, _PPV2_NEXT, script=["id", "kill"])
    assert await _tick(aid) is None
    back = timedelta(minutes=10)
    async with get_session() as s:
        st = await s.get(FunnelState, (mr, 90014))
        st.sending_at = st.sending_at - back
        marked = st.sending_at
        for m in (await s.execute(select(Message).where(
                Message.account_id == aid, Message.fan_id == 90014,
                Message.funnel_step == 1))).scalars():
            m.created_at = m.created_at - back
        bought = marked + timedelta(minutes=1)
        s.add(Message(account_id=aid, fan_id=90014, message_id=7_190_014, direction="out",
                      body="unlock me", price_cents=2000, is_paid=True, purchased_at=bought,
                      created_at=bought))
    _restart()
    await ax.release_fan_lease(aid, 90014)
    await _tick(aid)                                   # settle → step 2, not yet due
    st = await _state(mr, 90014)
    assert (st.current_step, st.sending_at, st.last_ppv_sent_at) == (1, None, marked), st
    await _force_due(aid, mr, 90014)
    res = await _tick(aid)
    st = await _state(mr, 90014)
    assert (st.status, st.last_error) == ("done", "offer_taken"), (st.status, st.last_error, res)
    assert fake.calls.count("ppv a") == 1 and "m2" not in fake.calls, fake.calls


async def case_settle_noid_landing_stays_listed():
    aid = "acc_settle_noid"
    mr, fake = await _ppv_fan(aid, 90015, script=["noid", "kill"])
    assert await _tick(aid) is None
    _restart()
    await _force_due(aid, mr, 90015)
    await _tick(aid)
    st = await _state(mr, 90015)
    assert st.sending_at is not None and st.current_step == 0, st
    assert [(r["kind"], r["state"], r["step_label"]) for r in await _get(aid)] == [
        ("funnel", "UNCONFIRMED", "STEP 1")]
    assert fake.calls == ["ppv a", "ppv b"], fake.calls


async def case_settle_skips_in_flight_and_funnel_less_rows():
    aid = "acc_settle_skip"
    mr, fake = await _ppv_fan(aid, 90016, script=["id", "kill"])
    assert await _tick(aid) is None                    # no restart: IN_FLIGHT
    # a funnel-less row (mass_runs.funnel_id NULL), marked long ago, its message landed
    async with get_session() as s:
        other = MassRun(account_id=aid, funnel_id=None, status="ok", recipient_count=1,
                      started_at=T0)
        s.add(other)
        await s.flush()
        other_id = int(other.id)
        s.add(FunnelState(mass_run_id=other_id, fan_id=90017, current_step=0, status="pending",
                          check_count=0, sending_at=T0, sending_ctx="{}"))
    await ax.release_fan_lease(aid, 90016)
    await a11.settle_landed(aid, smd.BOOT_TS, datetime.utcnow())
    assert (await _state(mr, 90016)).sending_at is not None, "IN_FLIGHT untouched"
    assert (await _state(other_id, 90017)).sending_at == T0, "funnel-less row untouched"
    assert [r["mass_run_id"] for r in await _get(aid)] == [mr], "funnel-less row never listed"


async def case_settle_shortened_funnel_row_stays_listed_tick_proceeds():
    aid = "acc_settle_short"
    mr, fake = await _ppv_fan(aid, 90018, [{"step": 1, "messages": ["m1"]}], script=["id"])
    await _seed_state(mr, 90019, current_step=3,       # marked on a step since removed
                      sending_at=datetime.utcnow() - timedelta(hours=1), sending_ctx="{}")
    res = await _tick(aid)
    assert res["advanced"] == 1 and fake.calls == ["m1"], (res, fake.calls)
    st = await _state(mr, 90019)
    assert st.sending_at is not None and st.status == "pending", st
    assert [r["fan_id"] for r in await _get(aid)] == ["90019"]


# ── Follow-up ─────────────────────────────────────────────────────────

def _fu_marker(aid: str, fid: int):
    """(sending_at, sending_ctx, unconfirmed_at), or None (no row)."""
    return _db("SELECT sending_at, sending_ctx, unconfirmed_at FROM followup_state"
               " WHERE account_id=? AND fan_id=?", (aid, fid))


class MarkerOF:
    """Records the row's marker at each send; then does `then`: None (returns),
    an exception instance (raised) or "kill" (_Killed)."""

    def __init__(self, aid: str, then=None):
        self.aid, self.then = aid, then
        self.sent: list[tuple[int, str]] = []
        self.marker_at_call: list = []
        self._next_id = 8_000_000_000_000

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.marker_at_call.append(_fu_marker(self.aid, int(chat_id)))
        if self.then == "kill":
            raise _Killed()
        if isinstance(self.then, BaseException):
            raise self.then
        self._next_id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": text, "createdAt": "2026-06-04T12:00:00+00:00"}

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}


async def _due_fan(aid: str, fid: int, then=None) -> MarkerOF:
    """A first-cycle fan with NO followup_state row, step 1 due (48 h silent)."""
    await _seed_account(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fid, of_display_name="Bob", lifetime_spend_cents=500))
        s.add(Message(account_id=aid, fan_id=fid, message_id=1, direction="out", body="hi",
                      created_at=datetime.utcnow() - timedelta(hours=48)))
    fake = MarkerOF(aid, then)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    async def _fake_chat(**kw):
        return SimpleNamespace(content="hey you, been thinking about you today 💕")
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]
    return fake


async def _fu_tick(aid: str) -> dict | None:
    try:
        return await run_once(aid, "send_followup", payload={"with_image": False})
    except _Killed:
        return None


async def _fu_row(aid: str, fid: int) -> FollowupState | None:
    async with get_session() as s:
        return await s.get(FollowupState, (aid, fid))


async def case_fu_once_fresh_fan_is_marked_after_the_turn_before_the_send():
    aid, fid = "acc_once_fu_fresh", 9101
    fake = await _due_fan(aid, fid)
    real_turn, at_turn = send_followup.dm_rate.turn, []

    async def _turn(account_id, **kw):
        at_turn.append(_fu_marker(aid, fid))
        return await real_turn(account_id, **kw)
    send_followup.dm_rate.turn = _turn
    try:
        res = await _fu_tick(aid)
    finally:
        send_followup.dm_rate.turn = real_turn
    assert res["followups_sent"] == 1, res
    assert at_turn[0] is None, ("no row, no marker during the DM-rate turn", at_turn)
    sa, ctx, ua = fake.marker_at_call[0]
    assert sa is not None and json.loads(ctx) == {"step": 1} and ua is None, fake.marker_at_call
    row = await _fu_row(aid, fid)
    assert (row.sending_at, row.sending_ctx, row.unconfirmed_at) == (None, None, None), row
    assert "1" in json.loads(row.messages_sent), row.messages_sent


async def case_fu_once_4xx_clears_the_marker():
    aid, fid = "acc_once_fu_4xx", 9102
    await _due_fan(aid, fid, then=_http_400())
    res = await _fu_tick(aid)
    assert res["followups_sent"] == 0 and res["errors"] == 1, res
    row = await _fu_row(aid, fid)
    assert (row.sending_at, row.sending_ctx, row.unconfirmed_at) == (None, None, None), row


async def case_fu_once_read_timeout_is_unconfirmed_never_resent():
    aid, fid = "acc_once_fu_timeout", 9103
    fake = await _due_fan(aid, fid, then=curl_exc.ReadTimeout("read timed out"))
    await _fu_tick(aid)
    row = await _fu_row(aid, fid)
    assert row.sending_at is not None and row.unconfirmed_at is not None, row
    assert json.loads(row.sending_ctx) == {"step": 1}, row.sending_ctx
    await ax.release_fan_lease(aid, fid)
    res = await _fu_tick(aid)
    assert res["followups_sent"] == 0 and len(fake.marker_at_call) == 1, (res, fake.marker_at_call)


async def case_fu_once_raise_in_the_dm_rate_turn_writes_and_probes_nothing():
    aid, fid = "acc_once_fu_turn", 9104
    fake = await _due_fan(aid, fid)
    real_turn, real_probe, probed = send_followup.dm_rate.turn, send_followup.quarantine_if_undeliverable, []

    async def _boom(account_id, **kw):
        raise RuntimeError("turn failed")

    async def _probe(*a, **kw):
        probed.append(a)
    send_followup.dm_rate.turn, send_followup.quarantine_if_undeliverable = _boom, _probe
    try:
        res = await _fu_tick(aid)
    finally:
        send_followup.dm_rate.turn, send_followup.quarantine_if_undeliverable = real_turn, real_probe
    assert res["errors"] == 1 and fake.marker_at_call == [], (res, fake.marker_at_call)
    assert _fu_marker(aid, fid) is None, "no row written"
    assert probed == [], ("nothing reached OF: no quarantine probe", probed)


async def case_fu_once_stale_tick_now_marks_in_flight_and_retry_409s():
    aid, fid = "acc_once_fu_stale", 9105
    await _due_fan(aid, fid, then="kill")
    real_dt, real_turn, late = send_followup.datetime, send_followup.dm_rate.turn, [True]

    async def _turn(account_id, **kw):
        late[0] = False                    # the serial wait: the tick's `now` aged
        return await real_turn(account_id, **kw)
    send_followup.datetime, send_followup.dm_rate.turn = _late_clock(real_dt, late), _turn
    try:
        assert await _fu_tick(aid) is None
    finally:
        send_followup.datetime, send_followup.dm_rate.turn = real_dt, real_turn
    row = await _fu_row(aid, fid)
    assert datetime.utcnow() - row.sending_at < timedelta(seconds=60), row.sending_at
    assert smd.marker_state(row.sending_at, row.unconfirmed_at, smd.BOOT_TS,
                            datetime.utcnow()) == smd.IN_FLIGHT
    assert await _status(_retry(aid, kind="followup", fan_id=fid)) == 409


async def case_fu_settle_landed_is_sent_at_sending_at():
    aid, fid = "acc_settle_fu", 9106
    fake = await _due_fan(aid, fid)
    marked = datetime.utcnow().replace(microsecond=0) - timedelta(seconds=1000)
    async with get_session() as s:
        s.add(FollowupState(account_id=aid, fan_id=fid, phase="tracking", cycle=1,
                            silence_started_at=marked - timedelta(hours=48),
                            messages_sent="{}", sending_at=marked,
                            sending_ctx='{"step": 1}'))
        s.add(Message(account_id=aid, fan_id=fid, message_id=8_100_000_000_001,
                      direction="out", body="landed", automation_kind="followup",
                      created_at=marked + timedelta(seconds=2)))
    res = await _fu_tick(aid)
    row = await _fu_row(aid, fid)
    assert (row.sending_at, row.sending_ctx, row.unconfirmed_at) == (None, None, None), row
    assert json.loads(row.messages_sent) == {"1": marked.isoformat()}, row.messages_sent
    assert fake.sent == [] and res["followups_sent"] == 0, (fake.sent, res)


if __name__ == "__main__":   # test_unconfirmed_sends.py imports the fixtures above
    _harness.run()
