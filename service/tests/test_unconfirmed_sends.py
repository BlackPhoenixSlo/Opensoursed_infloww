#!/usr/bin/env python3
"""
unconfirmed_sends_api — the Creator's maybe-sent funnel / follow-up steps and Retry.

  case_get_lists_only_this_creators_rows_and_writes_nothing:
      both kinds listed (step label, since, state), another Creator's rows are not,
      and the GET leaves every row byte-identical.
  case_funnel_less_row_never_listed:
      a funnel_state row (mass_runs.funnel_id NULL) is not the house
      funnel's: never listed, its Retry 404s.
  case_retry_settle_hit_is_already_sent_no_send:
      the step landed (outbound messages row): Retry's settle saves it as sent
      (last_error dropped) → `already_sent`, and the next tick sends nothing.
  case_retry_unmarked_row_is_already_sent:
      an existing row with no marker → `already_sent`.
  case_retry_unknown_row_404:
      no such row for this Creator → 404.
  case_foreign_creator_403:
      GET and Retry for a Creator the session does not own → 403.
  case_retry_stale_in_flight_is_retried_then_sent_once:
      a mark older than the lease (UNCONFIRMED) → `retried`, cleared + pending + due;
      the next tick sends the step exactly once, the one after nothing.
  case_retry_fresh_in_flight_409:
      a mark of this process seconds old → 409, the row untouched.
  case_retry_shortened_funnel_row_is_retried:
      a marked row on a step the funnel no longer has (the settle can't replay it)
      → `retried`; the next tick ends it done.
  case_retry_row_changed_under_the_clear_is_read_again:
      the clear lost a race: re-read → `already_sent` when unmarked, else 409.
  case_retry_followup_row_is_retried:
      a follow-up row past the lease → `retried`, the three columns cleared.
  case_http_wiring:
      GET + POST through the app: JSON shape and status codes.

Run: ./venv/bin/python service/tests/test_unconfirmed_sends.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import send_marker_decide as smd  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, FollowupState, FunnelState, MassMessageFunnel, MassRun, Message,
)
from test_send_once import _get, _retry, _status  # noqa: E402 — the shared owner/GET/Retry

a11._STEP_GAP_S = 0
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)
OLD = datetime.utcnow().replace(microsecond=0) - timedelta(seconds=2000)   # past the lease
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
    """A marked funnel_state row; `replied`: the broadcast + his reply, so a cleared
    row is due and its step sends on the next tick."""
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


# ── GET ───────────────────────────────────────────────────────────────

async def case_get_lists_only_this_creators_rows_and_writes_nothing():
    a, b = "acc_us_a", "acc_us_b"
    mra, mrb = await _funnel_run(a), await _funnel_run(b)
    await _marked(mra, 1, step=1, unconfirmed_at=OLD + timedelta(seconds=5))
    await _marked(mra, 2, sending_at=datetime.utcnow())        # this process, fresh
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


# ── Retry ─────────────────────────────────────────────────────────────

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
    await _marked(mr, 61, aid=aid)              # sending_at 2000 s ago, never confirmed
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
    """The clear finds the mark gone (a concurrent Retry / settle took it): re-read,
    unmarked → `already_sent`; marked again (a fresh attempt) → 409."""
    aid = "acc_us_race"
    mr = await _funnel_run(aid)
    real = a11.retry_clear
    for fan, then, want in ((101, None, {"status": "already_sent"}),
                            (102, datetime.utcnow(), 409)):
        await _marked(mr, fan, unconfirmed_at=OLD)

        async def _raced(account_id, fan_id, mass_run_id, sending_at, now, then=then):
            async with get_session() as s:   # someone else got there first
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
                            "last_error", "state"}, row
        r = c.post("/admin/unconfirmed-sends/retry", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "99", "mass_run_id": mr})
        assert (r.status_code, r.json()) == (200, {"status": "retried"}), r.text
        r = c.post("/admin/unconfirmed-sends/retry", params={"account_id": aid},
                   json={"kind": "funnel", "fan_id": "98", "mass_run_id": mr})
        assert r.status_code == 404, r.text
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_ADMIN", None)


_harness.run()
