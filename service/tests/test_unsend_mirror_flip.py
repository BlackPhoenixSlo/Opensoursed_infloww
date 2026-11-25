#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import messages as messages_api  # noqa: E402 — seed endpoint + flip helpers
import server  # noqa: E402
import mass_queue_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, Message  # noqa: E402

AID = "acct-unsend"
FAN = 5150
MID = 10977996348669


class _FakeClient:

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

    def __init__(self, payload: dict | None = None):
        self._raw = b"" if payload is None else json.dumps(payload).encode()

    async def body(self) -> bytes:
        return self._raw


class _Ctx:

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


async def case_unsend_without_withuserid_flips():
    await _seed_account()
    await _seed_ppv(6001, MID + 1)

    with _Ctx() as ctx:
        await server.of_unsend_message(_Req(None), MID + 1)

    assert ctx.client.unsends == [(MID + 1, None)], ctx.client.unsends
    row = await _row(6001, MID + 1)
    assert row is not None and row.is_unsent is True, \
        "a bodyless unsend must still flip — OF message ids are global"


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


async def case_queue_cancel_flips_broadcast_rows():
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
        await mass_queue_api.of_cancel_scheduled(_Req(None), qid)

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


async def case_queue_cancel_without_a_run_is_a_noop():
    await _seed_account()
    await _seed_ppv(704, 90004)

    with _Ctx() as ctx:
        resp = await mass_queue_api.of_cancel_scheduled(_Req(None), 9999)

    assert resp == {"success": True}, resp
    assert ctx.client.cancels == [9999], ctx.client.cancels
    row = await _row(704, 90004)
    assert row is not None and row.is_unsent is False, \
        "an unknown queue id flipped an unrelated row"


async def case_unsend_from_everyone_route_flips_copies():
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
        s.add(Message(account_id=AID, fan_id=713, message_id=90013, direction="out",
                      body=body, media_count=0, is_unsent=False,
                      created_at=sent_at + timedelta(hours=3)))

    with _Ctx() as ctx:
        await mass_queue_api.of_cancel_scheduled(_Req(None), qid)

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


_harness.run()
