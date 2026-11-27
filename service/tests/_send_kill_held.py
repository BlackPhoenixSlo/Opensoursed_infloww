from __future__ import annotations

import contextlib
import sqlite3
from unittest.mock import patch

from fastapi import HTTPException

import _harness
import _send_kill_cell as cell
from _send_kill import Killed

AID = cell.AID
_anchors = iter(range(1, 10_000))


@contextlib.contextmanager
def _owner():
    import auth
    tok = auth._request_user.set(auth.AuthedUser("u_held", "held_owner", frozenset({AID})))
    try:
        yield
    finally:
        auth._request_user.reset(tok)


async def _call(coro):
    try:
        return 200, await coro
    except HTTPException as e:
        return e.status_code, e.detail


async def listed() -> list[dict]:
    import unconfirmed_sends_api as usa
    with _owner():
        return (await usa.list_unconfirmed_sends(account_id=AID))["rows"]


async def resolve(op: str, outcome: str, updated_at: str | None = None):
    import unconfirmed_sends_api as usa
    if updated_at is None:
        shown = _row(await listed(), op)
        updated_at = shown["updated_at"] if shown else ""
    body = usa.ResolveBody(op_id=op, outcome=outcome, updated_at=updated_at)
    with _owner():
        return await _call(usa.resolve_unconfirmed_send(account_id=AID, body=body))


async def retry(fan: int):
    import unconfirmed_sends_api as usa
    with _owner():
        return await _call(usa.retry_unconfirmed_send(account_id=AID, body=usa.RetryBody(
            kind="followup", fan_id=fan, since="2026-11-26T10:00:00Z")))


def tick(http: cell.FakeHttp, fan: int, kind: str = "scheduled_send") -> str:
    import send_ops
    anchor = f"job-{next(_anchors)}"
    c = cell.client(http)
    try:
        with patch.dict(send_ops.CAPABILITY, {kind: "send_message"}):
                send_ops.dispatch("onlyfans", AID, send_ops.op_id("onlyfans", AID, kind, str(fan), anchor), kind, str(fan),
                              send_ops.digest({"anchor": anchor}), lambda: c.send_message(fan, "scheduled hi"))
    except HTTPException as e:
        return cell.err(e.detail) or str(e.status_code)
    return "sent"


def audit(op: str):
    with contextlib.closing(sqlite3.connect(str(_harness.DB_PATH))) as c:
        return c.execute("SELECT state, resolved_by, resolved_at FROM send_ops WHERE account=? AND op_id=?",
                         (AID, op)).fetchone()


def _row(rows: list[dict], op: str) -> dict | None:
    return next((r for r in rows if r.get("op_id") == op), None)


async def _uncertain_composer(fan: int, anchor: str) -> str:
    def die_after_accept(fake, url, body):
        cell.accept(fake, url, body)
        raise Killed()
    with contextlib.suppress(Killed):
        await cell.post(cell.FakeHttp(die_after_accept), fan, anchor)
    cell.restart()
    return cell.op_of(fan, anchor)


async def run() -> list[cell.Check]:
    from automations import send_followup as sf
    out: list[cell.Check] = []
    held, other, other2 = next(cell._fans), next(cell._fans), next(cell._fans)
    op = await _uncertain_composer(held, "held-kill")
    rows = await listed()
    r = _row(rows, op)
    out.append(("kill matrix uncertain op listed with its chat link, retry_allowed false",
                r is not None and r["kind"] == "composer" and r["fan_id"] == str(held) and r["link"] == "chat"
                and r["state"] == "UNCONFIRMED" and r["retry_allowed"] is False
                and all(x.get("retry_allowed") is False for x in rows), {"row": r, "rows": rows}))

    settled: list = []
    real_settle = sf.settle_landed

    async def spy(*a, **k):
        settled.append(a)
        return await real_settle(*a, **k)
    sf.settle_landed = spy
    try:
        st, body = await retry(held)
    finally:
        sf.settle_landed = real_settle
    out.append(("/retry in Cell mode → 409 retry_off_cell_mode before any settle",
                (st, cell.err(body)) == (409, "retry_off_cell_mode") and not settled, {"answer": [st, body],
                                                                                        "settled": len(settled)}))

    h1, h2 = cell.FakeHttp(), cell.FakeHttp()
    held_tick, other_tick = tick(h1, held), tick(h2, other)
    out.append(("held Fan's tick refused fan_held, 0 transport calls; another Fan's tick sends",
                held_tick == "fan_held" and not h1.calls and other_tick == "sent" and len(h2.accepts) == 1,
                {"held": [held_tick, h1.calls], "other": [other_tick, h2.calls]}))
    st, _ = await cell.post(h1, held, "held-manual", text="a new manual message")
    out.append(("held Fan: a new manual composer message still sends", st == 200 and len(h1.accepts) == 1,
                {"status": st, "calls": h1.calls}))

    st, body = await resolve(op, "was_sent")
    a = audit(op)
    again = await resolve(op, "not_sent")
    h3 = cell.FakeHttp()
    after = tick(h3, held)
    out.append(("mark was sent via the route: resolved_sent + resolved_by/resolved_at; held Fan's tick sends",
                (st, body) == (200, {"status": "was_sent"}) and a is not None and a[0] == "resolved_sent"
                and a[1] == "user:held_owner" and a[2] and again[0] == 404 and after == "sent"
                and len(h3.accepts) == 1 and _row(await listed(), op) is None,
                {"answer": [st, body], "audit": a, "again": again, "tick": [after, h3.calls]}))

    replay_http = cell.FakeHttp()
    replay = await cell.post(replay_http, held, "held-kill")
    out.append(("same composer send after was_sent: reconciled without a new delivery",
                replay == (200, {"status": "reconciled"}) and not replay_http.calls,
                {"answer": replay, "calls": replay_http.calls}))

    op2 = await _uncertain_composer(other2, "held-kill-2")
    blocked = tick(cell.FakeHttp(), other2)
    st, body = await resolve(op2, "not_sent")
    a2 = audit(op2)
    h4 = cell.FakeHttp()
    after2 = tick(h4, other2)
    out.append(("mark not sent via the route: resolved_not_sent + audit; that Fan's tick sends",
                blocked == "fan_held" and (st, body) == (200, {"status": "not_sent"}) and a2 is not None
                and a2[0] == "resolved_not_sent" and a2[1] == "user:held_owner" and a2[2] and after2 == "sent"
                and len(h4.accepts) == 1, {"blocked": blocked, "answer": [st, body], "audit": a2, "tick": after2}))
    retried = cell.FakeHttp()
    retry_answer = await cell.post(retried, other2, "held-kill-2")
    out.append(("same composer send after not_sent can be delivered",
                retry_answer[0] == 200 and len(retried.accepts) == 1,
                {"answer": retry_answer, "calls": retried.calls}))
    return out


async def case_stale_resolution_cannot_release_new_attempt():
    await cell._seed()
    cell.restart()
    fan, anchor = next(cell._fans), "stale-resolution"

    def accepted_timeout(fake, url, body):
        cell.accept(fake, url, body)
        raise cell.curl.exceptions.Timeout("response lost", cell.CurlECode.OPERATION_TIMEDOUT)

    http = cell.FakeHttp(accepted_timeout, accepted_timeout)
    with cell.cells():
        first = await cell.post(http, fan, anchor)
        assert first[1]["op_state"] == "uncertain", first
        op = cell.op_of(fan, anchor)
        shown = _row(await listed(), op)
        assert shown is not None
        token = shown["updated_at"]
        assert (await resolve(op, "not_sent", token))[0] == 200
        second = await cell.post(http, fan, anchor)
        assert second[1]["op_state"] == "uncertain", second
        stale = await resolve(op, "not_sent", token)
        third = await cell.post(http, fan, anchor)
    assert stale[0] == 409 and third[0] == 409 and len(http.accepts) == 2, (stale, third, http.calls)
