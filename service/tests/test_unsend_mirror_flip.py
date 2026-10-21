#!/usr/bin/env python3
"""An unsend the operator clicks must be mirrored onto our own `messages` row.

The bug (seen live 2026-08-27, Ava ↔ fan 119473): the ⋯ → unsend flow dropped
the bubble from the react-query cache and called OF — but the relay never
touched the local mirror, so the chat pane's DB seed (GET /admin/messages,
useChatMessagesLocal) served the row again on the next reload. Seed rows carry
`media: []` and a PPV's body is blank, so the bubble came back as an EMPTY
locked shell that no refresh could clear.

Cases:
  case_unsend_flips_the_mirror_row         — route flips is_unsent + reason,
                                              and the seed stops serving it
  case_unsend_without_withuserid_flips     — no body → flip by (account, msg id)
  case_failed_of_unsend_leaves_the_row     — OF refused (past the ~24h window)
                                              → mirror untouched, bubble honest
  case_mirror_failure_does_not_fail_unsend — the flip is best-effort: OF already
                                              took it down, never 500 the caller
  case_queue_cancel_flips_broadcast_rows   — "also unsend from everyone" flips
                                              recipients but spares purchasers
                                              and funnel follow-ups
  case_queue_cancel_without_a_run_is_a_noop — a queue we never recorded flips
                                              nothing and touches no neighbour

Run:  ./venv/bin/python service/tests/test_unsend_mirror_flip.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import messages as messages_api  # noqa: E402 — seed endpoint + flip helpers
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, Message  # noqa: E402

AID = "acct-unsend"
FAN = 5150
MID = 10977996348669  # the real id from the live report


class _FakeClient:
    """Records what reached OF. `fails=True` = past the edit window."""

    def __init__(self, *, fails: bool = False):
        self.unsends: list[tuple[int, int | None]] = []
        self.cancels: list[int] = []
        self._fails = fails

    def unsend_message(self, message_id, with_user_id=None):
        if self._fails:
            raise RuntimeError("message is older than 24h")
        self.unsends.append((int(message_id), with_user_id))
        return {"success": True}

    def cancel_scheduled(self, queue_id):
        self.cancels.append(int(queue_id))
        return {"success": True}


class _Req:
    """Only what the route reads off the request: the raw JSON body."""

    def __init__(self, payload: dict | None = None):
        self._raw = b"" if payload is None else json.dumps(payload).encode()

    async def body(self) -> bytes:
        return self._raw


class _Ctx:
    """Patch the route's account resolution + OF client for the call."""

    def __init__(self, *, fails: bool = False):
        self.client = _FakeClient(fails=fails)
        self._orig: dict = {}

    def __enter__(self):
        self._orig = {
            "_resolve_account_id": server._resolve_account_id,
            "_get_client": server._get_client,
        }
        server._resolve_account_id = lambda _req=None: AID
        server._get_client = lambda *a, **k: self.client
        return self

    def __exit__(self, *exc):
        for name, fn in self._orig.items():
            setattr(server, name, fn)
        return False


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID))


async def _seed_ppv(fan_id: int, message_id: int, **kw) -> None:
    """A sent PPV exactly as the mirror holds it: priced, blank body (the
    caption lives on OF's media), media_count 0 — the shape that renders as
    an empty locked bubble when it wrongly survives an unsend."""
    async with get_session() as s:
        s.add(Message(
            account_id=AID, fan_id=fan_id, message_id=message_id,
            direction="out", body="", media_count=0, price_cents=20000,
            is_unsent=False, created_at=datetime.utcnow() - timedelta(minutes=5),
            **kw,
        ))


async def _row(fan_id: int, message_id: int) -> Message | None:
    async with get_session() as s:
        return await s.get(Message, (AID, fan_id, message_id))


# ── case 1: the flip happens, and the seed stops serving the bubble ───
async def case_unsend_flips_the_mirror_row():
    await _seed_account()
    await _seed_ppv(FAN, MID)

    with _Ctx() as ctx:
        resp = await server.of_unsend_message(_Req({"withUserId": FAN}), MID)

    assert resp == {"success": True}, resp
    assert ctx.client.unsends == [(MID, FAN)], ctx.client.unsends
    row = await _row(FAN, MID)
    assert row is not None and row.is_unsent is True, \
        "mirror row not flipped — the DB seed will repaint the bubble on reload"
    assert row.unsent_reason == "manual:chat", row.unsent_reason
    assert row.unsent_at is not None, "unsent_at not stamped"

    seed = await messages_api.list_messages(AID, FAN, limit=50, before_id=None)
    got = {m["message_id"] for m in seed["messages"]}
    assert MID not in got, "unsent bubble still seeds the chat pane"


# ── case 2: no body → still flip, by (account, message_id) ───────────
async def case_unsend_without_withuserid_flips():
    await _seed_account()
    await _seed_ppv(6001, MID + 1)

    with _Ctx() as ctx:
        await server.of_unsend_message(_Req(None), MID + 1)

    assert ctx.client.unsends == [(MID + 1, None)], ctx.client.unsends
    row = await _row(6001, MID + 1)
    assert row is not None and row.is_unsent is True, \
        "a bodyless unsend must still flip — OF message ids are global"


# ── case 3: OF refused → the bubble is still live, keep the mirror ────
async def case_failed_of_unsend_leaves_the_row():
    await _seed_account()
    await _seed_ppv(FAN, MID + 2)

    raised = False
    with _Ctx(fails=True):
        try:
            await server.of_unsend_message(_Req({"withUserId": FAN}), MID + 2)
        except Exception:
            raised = True

    assert raised, "a failed OF unsend must surface to the caller"
    row = await _row(FAN, MID + 2)
    assert row is not None and row.is_unsent is False, \
        "flipped a row OF still shows — the fan sees a bubble we hid locally"


# ── case 4: the flip is best-effort, never a 500 ─────────────────────
async def case_mirror_failure_does_not_fail_unsend():
    await _seed_account()
    await _seed_ppv(FAN, MID + 3)

    orig = messages_api.mark_unsent

    async def _boom(*a, **k):
        raise RuntimeError("db locked")

    messages_api.mark_unsent = _boom
    try:
        with _Ctx():
            resp = await server.of_unsend_message(_Req({"withUserId": FAN}), MID + 3)
    finally:
        messages_api.mark_unsent = orig

    assert resp == {"success": True}, \
        "OF already unsent it — a mirror failure must not fail the request"


# ── case 5: "also unsend from everyone" — recipients only ────────────
async def case_queue_cancel_flips_broadcast_rows():
    """OF's queue cancel pulls the broadcast from fans who did NOT buy it. A
    purchaser keeps their paid copy, and reply_mass_funnel follow-ups share the
    mass_run_id but are separate live messages — both must stay unflipped."""
    await _seed_account()
    qid, base = 8123, datetime.utcnow() - timedelta(hours=2)
    async with get_session() as s:
        mr = MassRun(account_id=AID, queue_id=qid, automation_kind="ppv_send",
                     status="ok", completed_at=datetime.utcnow())
        s.add(mr)
        await s.flush()
        run_id = int(mr.id)
    await _seed_ppv(701, 90001, mass_run_id=run_id)
    await _seed_ppv(702, 90002, mass_run_id=run_id,
                    purchased_at=base + timedelta(minutes=30))
    await _seed_ppv(703, 90003, mass_run_id=run_id, funnel_step=2)

    with _Ctx() as ctx:
        await server.of_cancel_scheduled(_Req(None), qid)

    assert ctx.client.cancels == [qid], ctx.client.cancels
    plain = await _row(701, 90001)
    bought = await _row(702, 90002)
    follow = await _row(703, 90003)
    assert plain is not None and plain.is_unsent is True, \
        "recipient mirror row must flip — it re-seeds as an empty bubble"
    assert plain.unsent_reason == "manual:queue", plain.unsent_reason
    assert bought is not None and bought.is_unsent is False, \
        "PURCHASED row must stay live — the fan keeps their paid copy on OF"
    assert follow is not None and follow.is_unsent is False, \
        "funnel follow-up must stay live — a queue cancel doesn't touch it"


# ── case 6: a queue that was never ours flips nothing, quietly ────────
async def case_queue_cancel_without_a_run_is_a_noop():
    """A scheduled message canceled before it ever sent has no MassRun and no
    mirror rows. The subquery finds nothing, the route still returns OF's
    answer, and the unrelated row next door is untouched."""
    await _seed_account()
    await _seed_ppv(704, 90004)  # no mass_run_id at all

    with _Ctx() as ctx:
        resp = await server.of_cancel_scheduled(_Req(None), 9999)

    assert resp == {"success": True}, resp
    assert ctx.client.cancels == [9999], ctx.client.cancels
    row = await _row(704, 90004)
    assert row is not None and row.is_unsent is False, \
        "an unknown queue id flipped an unrelated row"


# ── case 7: "unsend from everyone" also retires the UNTAGGED copies ───
async def case_unsend_from_everyone_route_flips_copies():
    """A LIST-audience blast writes no per-fan row at all, so `mark_mass_runs_unsent`
    (which needs a `mass_run_id`) reached nothing for it: the copies our inbox poll
    wrote later stayed `is_unsent = 0` forever and the pane's DB seed repainted a
    retired blast on every open. The route now also runs the untagged matcher —
    body-and-window, or OF's own `queueId` off a scraped frame.

    The count the route returns is the TOTAL of both halves: the caller asked how
    many bubbles this retired, not where each row came from."""
    await _seed_account()
    qid = 8124
    sent_at = datetime.utcnow() - timedelta(hours=2)
    body = "come see what i just shot\nits filthy"
    async with get_session() as s:
        mr = MassRun(account_id=AID, queue_id=qid, automation_kind="mass_premade",
                     status="ok", completed_at=sent_at,
                     body=body, sent_at=sent_at)
        s.add(mr)
        await s.flush()
        run_id = int(mr.id)
    # One TAGGED recipient (an explicit id in the same send) and two untagged
    # copies — OF's <br /> echo from the poll, and a scraped row with the queue id.
    await _seed_ppv(710, 90010, mass_run_id=run_id)
    async with get_session() as s:
        s.add(Message(account_id=AID, fan_id=711, message_id=90011, direction="out",
                      body="come see what i just shot<br />\nits filthy",
                      media_count=0, is_unsent=False,
                      created_at=sent_at + timedelta(minutes=4)))
        s.add(Message(account_id=AID, fan_id=712, message_id=90012, direction="out",
                      body="come see what i just shot<br />\nits filthy",
                      media_count=0, is_unsent=False,
                      created_at=sent_at + timedelta(minutes=50),
                      raw_json=json.dumps({"id": 90012, "queueId": qid})))
        # …and a chatter typing the same words three hours later. Not the blast.
        s.add(Message(account_id=AID, fan_id=713, message_id=90013, direction="out",
                      body=body, media_count=0, is_unsent=False,
                      created_at=sent_at + timedelta(hours=3)))

    with _Ctx() as ctx:
        await server.of_cancel_scheduled(_Req(None), qid)

    assert ctx.client.cancels == [qid], ctx.client.cancels
    for fan_id, mid in ((710, 90010), (711, 90011), (712, 90012)):
        row = await _row(fan_id, mid)
        assert row is not None and row.is_unsent is True, (fan_id, mid)
    late = await _row(713, 90013)
    assert late is not None and late.is_unsent is False, \
        "a 1:1 send reusing the blast's words was retired with it"
    async with get_session() as s:
        run = await s.get(MassRun, run_id)
    assert run.unsent_at is not None, "the run was not stamped — still spliceable"

    seed = await messages_api.list_messages(AID, 711, limit=50, before_id=None)
    assert [m["message_id"] for m in seed["messages"]] == [], seed["messages"]


# Collected automatically — a case defined here and forgotten is a hard error,
# not a silent skip (see _harness.run's docstring).
_harness.run()
