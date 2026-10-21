#!/usr/bin/env python3
"""SSE replay and account-state events (roadmap W2 2.5).

  • Every pushed frame carries an `id:`; a reconnect with `Last-Event-ID`
    gets what it missed, oldest first, then the live stream, no duplicates.
  • Each account's ring is bounded: a reconnect from before what a ring still
    holds gets `resync` (the browser refetches) plus what is left; another
    Creator's overflow does not resync a tab that cannot see it. An id from
    another relay process (or garbage) is a `resync` too, and so is a
    subscriber queue that overflowed.
  • A session only ever receives its own Creators' events, live and on
    replay, and its own Agencies' Agency-wide events; `GET /events` builds
    that from the session (403 for another Creator's scope, 401 signed out).
  • `assignment_changed` ends the stream so the reconnect reads fresh grants,
    and `sessions_revoked` ends a revoked sign-in's streams.
  • The state events leave from where the state changes: on commit (never on
    rollback), from another thread, account_health, proxies.save,
    automation_executor._finalize_run (after the run's job is written), every
    scheduled-send transition and its cancel route, and admin_delete_user.

Run:  ./venv/bin/python service/tests/test_sse_replay.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402

import account_health  # noqa: E402
import automation_executor  # noqa: E402
import automation_registry  # noqa: E402
import chatters  # noqa: E402
import events  # noqa: E402
import proxies  # noqa: E402
from db.engine import get_session  # noqa: E402

A, B = "9101", "9102"            # the session's Creator, and one it is not granted
OWNER, OTHER = "owner-1", "owner-2"
SEEN = frozenset({A})


class _Req:
    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}

    async def is_disconnected(self) -> bool:
        return False


def _parse(raw: bytes) -> dict:
    """One SSE frame → its fields; a comment-only frame is {}."""
    out: dict = {}
    for line in raw.decode().split("\n"):
        if line and not line.startswith(":"):
            k, _, v = line.partition(": ")
            out[k] = v
    return out


async def _frames(gen, n: int) -> list[dict]:
    return [_parse(await asyncio.wait_for(gen.__anext__(), 3)) for _ in range(n)]


def _stream(last: str | None = None, *, accounts=SEEN, scope="all"):
    return events.sse_stream(_Req(), scope, accounts=accounts,
                             agencies=frozenset({OWNER}), last_event_id=last)


def _msg(aid: str, mid: int) -> dict:
    return {"api2_chat_message": {"id": mid}, "__account_id": aid}


def _mid(frame: dict) -> int:
    return json.loads(frame["data"])["api2_chat_message"]["id"]


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _types(got: list) -> list:
    return [(events._first_real_key(e), e.get("__account_id")) for e in got]


def _reset() -> None:
    events._subs.clear()
    events._rings.clear()
    events._evicted.clear()


async def case_replay_after_reconnect():
    _reset()
    gen = _stream()
    hello, head = await _frames(gen, 2)
    assert hello == {} and set(head) == {"id"}, (hello, head)
    await events.broadcast(_msg(A, 1))
    (f1,) = await _frames(gen, 1)
    assert f1["event"] == "api2_chat_message" and f1["id"], f1
    await gen.aclose()
    assert events.subscriber_count() == 0

    # Missed while away: two of A's, one of a Creator the session isn't granted.
    for ev in (_msg(A, 2), _msg(B, 3), _msg(A, 4)):
        await events.broadcast(ev)

    gen = _stream(f1["id"])
    got = await _frames(gen, 4)
    assert got[0] == {}
    assert [_mid(f) for f in got[1:3]] == [2, 4], got
    assert got[3] == {"id": got[2]["id"]}, "the head marker names the last event replayed"
    # Live again, nothing replayed twice.
    await events.broadcast(_msg(A, 5))
    (f5,) = await _frames(gen, 1)
    assert _mid(f5) == 5
    await gen.aclose()

    # A fresh tab (no id) gets no replay.
    gen = _stream()
    assert [set(f) for f in await _frames(gen, 2)] == [set(), {"id"}]
    await gen.aclose()


async def case_ring_overflow_resyncs():
    _reset()
    old = events._RING_MAX
    events._RING_MAX = 3
    try:
        gen = _stream()
        _, head = await _frames(gen, 2)
        await gen.aclose()
        for mid in range(10, 15):
            await events.broadcast(_msg(A, mid))

        gen = _stream(head["id"])
        got = await _frames(gen, 6)
        assert got[1] == {"event": "resync", "data": "{}"}, got[1]
        assert [_mid(f) for f in got[2:5]] == [12, 13, 14], "what the ring still holds is replayed"
        await gen.aclose()

        # From inside what the ring still reaches: replay, no resync.
        gen = _stream(got[2]["id"])
        inside = await _frames(gen, 4)
        assert [_mid(f) for f in inside[1:3]] == [13, 14] and set(inside[3]) == {"id"}, inside
        await gen.aclose()

        # A's overflow is not the concern of a tab that only sees B.
        gen = _stream(head["id"], accounts=frozenset({B}))
        assert [set(f) for f in await _frames(gen, 2)] == [set(), {"id"}]
        await gen.aclose()

        # An id from another relay process, or garbage: resync, nothing replayed.
        for stale in ("0.1", "not-an-id"):
            gen = _stream(stale)
            got = await _frames(gen, 3)
            assert got[1]["event"] == "resync" and set(got[2]) == {"id"}, (stale, got)
            await gen.aclose()
    finally:
        events._RING_MAX = old


async def case_queue_overflow_resyncs():
    _reset()
    old = events._QUEUE_MAX
    events._QUEUE_MAX = 2
    try:
        gen = _stream()
        await _frames(gen, 2)
        for mid in (20, 21, 22):
            await events.broadcast(_msg(A, mid))
        got = await _frames(gen, 3)
        assert got[0]["event"] == "resync", got
        assert [_mid(f) for f in got[1:]] == [21, 22], "a slow tab loses the oldest"
        await gen.aclose()
    finally:
        events._QUEUE_MAX = old


async def case_state_events_reach_only_granted_creators():
    _reset()
    q = await events.subscribe("all", accounts=SEEN, agencies=frozenset({OWNER}))
    for aid in (A, B):
        events.publish_state("session_dead", account_id=aid, dead=True, reason="wrong_user")
        events.publish_state("proxy_switched", account_id=aid, proxied=True)
        events.publish_state("rule_run_finished", account_id=aid, run_id=1, kind="k",
                             status="ok", rule_id=None)
    for agency in (OWNER, OTHER):
        events.publish_state("permissions_changed", agency=agency)
    events.publish_state("assignment_changed", agency=OTHER)
    assert _types(_drain(q)) == [
        ("session_dead", A), ("proxy_switched", A), ("rule_run_finished", A),
        ("permissions_changed", None),
    ]
    await events.unsubscribe("all", q)

    # A one-Creator scope gets only that Creator, but its Agency's events still.
    q = await events.subscribe(f"model:{B}", accounts=frozenset({A, B}), agencies=frozenset({OWNER}))
    events.publish_state("session_dead", account_id=A, dead=False, reason=None)
    events.publish_state("session_dead", account_id=B, dead=False, reason=None)
    events.publish_state("permissions_changed", agency=OWNER)
    assert _types(_drain(q)) == [("session_dead", B), ("permissions_changed", None)]
    await events.unsubscribe(f"model:{B}", q)

    # Replay applies the same rule.
    gen = _stream()
    _, head = await _frames(gen, 2)
    await gen.aclose()
    events.publish_state("rule_run_finished", account_id=B, run_id=2, kind="k", status="ok", rule_id=None)
    events.publish_state("permissions_changed", agency=OTHER)
    events.publish_state("rule_run_finished", account_id=A, run_id=3, kind="k", status="ok", rule_id=None)
    gen = _stream(head["id"])
    got = await _frames(gen, 3)
    assert got[1]["event"] == "rule_run_finished" and json.loads(got[1]["data"])["__account_id"] == A, got
    assert set(got[2]) == {"id"}
    await gen.aclose()


async def case_events_route_scopes_to_the_session():
    import auth
    import server

    _reset()
    ident = chatters.ChatterIdentity(
        id_="c-1", username="chat1", display_name=None, color=None,
        owner_user_ids=frozenset({OWNER}), account_ids=SEEN,
    )
    tok = chatters._request_chatter.set(ident)
    try:
        try:
            await server.sse_events(_Req(), scope=f"model:{B}", last_event_id=None)
            raise AssertionError("another Creator's scope must be refused")
        except HTTPException as e:
            assert e.status_code == 403, e.status_code
        resp = await server.sse_events(_Req(), scope="all", last_event_id=None)
        gen = resp.body_iterator
        await gen.__anext__()
        await gen.__anext__()
        events.publish_state("session_dead", account_id=B, dead=True, reason="wrong_user")
        events.publish_state("session_dead", account_id=A, dead=True, reason="wrong_user")
        (f,) = await _frames(gen, 1)
        assert json.loads(f["data"])["__account_id"] == A, f
        events.publish_state("assignment_changed", agency=OWNER)
        (f,) = await _frames(gen, 1)
        assert f["event"] == "assignment_changed"
        try:
            await asyncio.wait_for(gen.__anext__(), 3)
            raise AssertionError("assignment_changed must end the stream")
        except StopAsyncIteration:
            pass
        assert events.subscriber_count() == 0
    finally:
        chatters._request_chatter.reset(tok)

    assert auth.get_request_user() is None
    try:
        await server.sse_events(_Req(), scope="all", last_event_id=None)
        raise AssertionError("signed out must be refused")
    except HTTPException as e:
        assert e.status_code == 401, e.status_code


async def case_on_commit_and_threads():
    _reset()
    q = await events.subscribe("all", agencies=frozenset({OWNER}))
    async with get_session() as s:
        await s.execute(text("SELECT 1"))   # a session that never began commits nothing
        events.on_commit(s, "permissions_changed", agency=OWNER)
        assert _drain(q) == [], "nothing before the commit"
    assert _types(_drain(q)) == [("permissions_changed", None)]
    try:
        async with get_session() as s:
            await s.execute(text("SELECT 1"))
            events.on_commit(s, "permissions_changed", agency=OWNER)
            raise RuntimeError("roll back")
    except RuntimeError:
        pass
    assert _drain(q) == [], "a rolled-back change is not announced"

    # From a threadpool route: handed to the loop, not run on the thread.
    t = threading.Thread(target=events.publish_state, args=("proxy_switched",),
                         kwargs={"account_id": A, "proxied": False})
    t.start()
    t.join()
    await asyncio.sleep(0.05)
    assert _types(_drain(q)) == [("proxy_switched", A)]
    await events.unsubscribe("all", q)


async def case_emitted_where_state_changes():
    _reset()
    q = await events.subscribe("all")

    assert await account_health.mark_session_dead(A, "wrong_user")
    assert not await account_health.mark_session_dead(A, "wrong_user")
    assert await account_health.clear_session_dead(A)
    got = _drain(q)
    assert [e["session_dead"]["dead"] for e in got] == [True, False], got

    old_path = proxies.REGISTRY_PATH
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp()) / "proxies.json"
    try:
        p = {"label": "p1", "scheme": "http", "host": "h", "port": 1, "assigned_account_ids": [A]}
        proxies.save({"proxies": [p]})
        proxies.save({"proxies": [{**p, "verified_ip": "1.2.3.4"}]})   # a probe stamp: same egress
        proxies.save({"proxies": [{**p, "port": 2}]})                  # endpoint edited in place
        proxies.save({"proxies": [{**p, "assigned_account_ids": []}]})
    finally:
        proxies.REGISTRY_PATH = old_path
    got = _drain(q)
    assert [(e["__account_id"], e["proxy_switched"]["proxied"]) for e in got] == \
        [(A, True), (A, True), (A, False)], got

    run_id = await automation_executor._open_run(A, "scheduled_send")
    await automation_executor._finalize_run(run_id, "error", None, "boom")
    (e,) = _drain(q)
    assert e["__account_id"] == A and e["rule_run_finished"] == {
        "run_id": run_id, "kind": "scheduled_send", "status": "error", "rule_id": None,
    }, e
    await events.unsubscribe("all", q)


async def _ensure_account() -> None:
    """scheduled_jobs.account_id references accounts."""
    from db.models import Account
    async with get_session() as s:
        if await s.get(Account, A) is None:
            s.add(Account(id=A))


def _job_status(job_id: int) -> str:
    with sqlite3.connect(_harness.DB_PATH) as c:
        return c.execute("SELECT status FROM scheduled_jobs WHERE id=?", (job_id,)).fetchone()[0]


async def case_run_finished_reads_the_written_job():
    """rule_run_finished leaves after the run's job is written, and every
    scheduled-send transition (queued, claimed, finished, parked) announces
    itself: a refetch on either event never reads the job as running."""
    _reset()
    automation_registry.load_automation_plugins()
    reg = automation_registry._REGISTRY
    real = reg["scheduled_send"]
    seen: list[tuple[str, str]] = []
    real_publish = events.publish_state

    def spy(event_type, **kw):
        job_id = kw.get("job_id") or jobs.get(kw.get("run_id"))
        if job_id is not None:
            seen.append((event_type, _job_status(job_id)))
        return real_publish(event_type, **kw)

    jobs: dict = {}
    outcome = {"raise": False}

    async def fake(account_id, payload, run_id=None):
        jobs[run_id] = job_id
        if outcome["raise"]:
            raise RuntimeError("boom")
        return {}

    await _ensure_account()
    reg["scheduled_send"] = fake
    events.publish_state = spy
    try:
        q = await events.subscribe("all", accounts=SEEN)
        job_id = await automation_executor.enqueue_job(A, "scheduled_send", payload={"fan_id": 1})
        await automation_executor.run_once(A, "scheduled_send")
        assert seen == [("scheduled_send_changed", "pending"), ("scheduled_send_changed", "running"),
                        ("scheduled_send_changed", "done"), ("rule_run_finished", "done")], seen
        assert {events._first_real_key(e) for e in _drain(q)} == \
            {"scheduled_send_changed", "rule_run_finished"}

        seen.clear()
        outcome["raise"] = True
        job_id = await automation_executor.enqueue_job(A, "scheduled_send", payload={"fan_id": 1})
        await automation_executor.run_once(A, "scheduled_send")
        assert seen[-2:] == [("scheduled_send_changed", "pending"), ("rule_run_finished", "pending")], seen

        # Another kind's job is not a scheduled send.
        seen.clear()
        await automation_executor.enqueue_job(A, "nudge_online_fire", payload={})
        assert seen == [], seen
        await events.unsubscribe("all", q)
    finally:
        reg["scheduled_send"] = real
        events.publish_state = real_publish


async def case_finalize_without_a_run_row_still_closes_the_job():
    await _ensure_account()
    job_id = await automation_executor.enqueue_job(A, "scheduled_send", payload={"fan_id": 1})
    await automation_executor._finalize_run(10**9, "ok", {}, None, job_id=job_id)
    assert _job_status(job_id) == "done"


async def case_cancel_route_announces():
    import server
    _reset()
    await _ensure_account()
    q = await events.subscribe("all", accounts=SEEN)
    job_id = await automation_executor.enqueue_job(A, "scheduled_send", payload={"fan_id": 1})
    _drain(q)
    real_resolve = server._resolve_account_id
    server._resolve_account_id = lambda _r: A
    try:
        assert (await server.cancel_scheduled_send(_Req(), job_id))["cancelled"]
        (e,) = _drain(q)
        assert e["__account_id"] == A and e["scheduled_send_changed"] == {"job_id": job_id}, e
        # Already cancelled: nothing changed, nothing sent.
        assert not (await server.cancel_scheduled_send(_Req(), job_id))["cancelled"]
        assert _drain(q) == []
    finally:
        server._resolve_account_id = real_resolve
    await events.unsubscribe("all", q)


async def case_deleting_a_user_ends_its_agency_streams():
    import auth
    from db.models import User
    _reset()
    async with get_session() as s:
        s.add(User(id="gone-1", username="gone-1", password="x"))
    owner = await events.subscribe("all", accounts=SEEN, agencies=frozenset({"gone-1"}))
    chatter = await events.subscribe(f"model:{A}", accounts=SEEN, agencies=frozenset({"gone-1"}))
    other = await events.subscribe("all", accounts=SEEN, agencies=frozenset({OTHER}))
    await auth.admin_delete_user(
        "gone-1", auth.DeleteUserBody(confirm="delete", admin_password="test-admin-password"))
    for q in (owner, chatter):
        (e,) = _drain(q)
        assert e == {"assignment_changed": {}, "__agency": "gone-1"}, e
    assert _drain(other) == []
    for scope, q in (("all", owner), (f"model:{A}", chatter), ("all", other)):
        await events.unsubscribe(scope, q)


async def case_revoking_a_sign_ins_sessions_ends_its_streams_only():
    # Log out other sessions, 2FA on/off/reset, a password reset, Deactivate: a revoked cookie must not
    # keep its open stream (account_security.revoke_sessions); the reconnect is refused.
    import server
    from account_security import revoke_sessions
    _reset()
    ident = chatters.ChatterIdentity(
        id_="c-rv", username="rv", display_name=None, color=None,
        owner_user_ids=frozenset({OWNER}), account_ids=SEEN,
    )
    tok = chatters._request_chatter.set(ident)
    try:
        gen = (await server.sse_events(_Req(), scope="all", last_event_id=None)).body_iterator
        await gen.__anext__()
        await gen.__anext__()
    finally:
        chatters._request_chatter.reset(tok)
    # The Agency's other sessions, and an owner whose id is the same string, keep theirs.
    other = await events.subscribe("all", accounts=SEEN, agencies=frozenset(
        {OWNER, events.sessions_audience("chatter", "c-other")}))
    owner = await events.subscribe("all", accounts=SEEN, agencies=frozenset(
        {OWNER, events.sessions_audience("user", "c-rv")}))
    async with get_session() as s:
        await revoke_sessions(s, "chatter", "c-rv")
    (f,) = await _frames(gen, 1)
    assert f["event"] == "sessions_revoked", f
    try:
        await asyncio.wait_for(gen.__anext__(), 3)
        raise AssertionError("sessions_revoked must end the stream")
    except StopAsyncIteration:
        pass
    assert _drain(other) == [] and _drain(owner) == []
    async with get_session() as s:
        await revoke_sessions(s, "user", "c-rv")
    assert _drain(owner) == [{"sessions_revoked": {}, "__agency": "sessions:user:c-rv"}]
    assert _drain(other) == []
    for q in (other, owner):
        await events.unsubscribe("all", q)


async def case_proxies_save_survives_a_malformed_old_file():
    _reset()
    old_path = proxies.REGISTRY_PATH
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp()) / "proxies.json"
    try:
        proxies.REGISTRY_PATH.write_text(json.dumps({"proxies": ["not-an-entry", {"assigned_account_ids": 5}]}))
        p = {"label": "p1", "scheme": "http", "host": "h", "port": 1, "assigned_account_ids": [A]}
        proxies.save({"proxies": [p]})
        assert proxies.load() == {"proxies": [p]}
    finally:
        proxies.REGISTRY_PATH = old_path


_harness.run()
