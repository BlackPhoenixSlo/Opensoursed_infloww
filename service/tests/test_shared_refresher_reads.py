#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402

import server  # noqa: E402  (before accounts_admin_api: server loads it)
import accounts_admin_api  # noqa: E402
import account_health  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from of_client import OFAPIError  # noqa: E402
import relay_cache  # noqa: E402
import relay_coalesce  # noqa: E402
import events  # noqa: E402
import shared_refresher  # noqa: E402
import shared_refresher_decide  # noqa: E402
import threading  # noqa: E402


def _reset() -> None:
    relay_cache._cache.clear()
    relay_coalesce.reset_for_tests()


def _lane(aid: str) -> dict:
    total, bg = server._lanes_for(aid)
    lease = server._bg_lease.get()
    return {"bg_held": bg.held, "total_free": total._value,
            "lease": lease.aid if lease is not None and not lease.closed else None,
            "priority": server._current_priority()}


def case_priority_is_background_only_inside_the_context():
    assert server._current_priority() == "user"
    assert relay_coalesce.priority_class() == "user"
    with server._background_reads("acct-r1"):
        assert server._current_priority() == "background"
        assert relay_coalesce.priority_class() == "background"
    assert server._current_priority() == "user", "the context must not leak past its exit"


async def case_read_coalesces_in_the_background_class_and_passes_admission():
    _reset()
    aid = "acct-r2"
    seen: dict = {}
    release = asyncio.Event()

    async def bg_fetch():
        seen["bg"] = _lane(aid)
        await release.wait()
        return "bg"

    async def user_fetch():
        seen["user"] = _lane(aid)
        return "user"

    async def in_ctx():
        with server._background_reads(aid):
            return await relay_coalesce.coalesce(("users_me", aid), bg_fetch)

    bg_task = asyncio.create_task(in_ctx())
    await asyncio.sleep(0.05)
    assert ("users_me", aid, "background") in relay_coalesce._inflight, list(relay_coalesce._inflight)
    assert seen["bg"]["lease"] == aid and seen["bg"]["bg_held"] == 1, seen
    assert await relay_coalesce.coalesce(("users_me", aid), user_fetch) == "user"
    assert seen["user"]["lease"] is None and seen["user"]["priority"] == "user", seen
    release.set()
    assert await bg_task == "bg"
    assert server._lanes_for(aid)[1].held == 0, "the admitted slot is released after the read"


async def case_warm_fetch_inside_context_borrows_the_admitted_slot():
    _reset()
    aid = "acct-r3"
    seen: list = []

    def read(_client):
        seen.append(_lane(aid))
        return {"ok": 1}

    orig = server._load_client
    server._load_client = lambda *_a, **_k: object()
    try:
        with server._background_reads(aid):
            got = await relay_cache.get_or_fetch(
                "users_me", aid, ("t",), 60.0, server._warm_fetch(("users_me", aid, "t"), aid, read), bypass=True)
    finally:
        server._load_client = orig
    assert got == {"ok": 1}
    assert seen == [{"bg_held": 1, "total_free": server._ACCOUNT_LANE_TOTAL - 1, "lease": aid,
                     "priority": "background"}], seen
    assert server._lanes_for(aid)[1].held == 0


class _ChatsClient:
    user_id = 999

    def __init__(self, aid: str) -> None:
        self.aid, self.seen = aid, []

    def list_chats(self, **_k):
        self.seen.append(_lane(self.aid))
        return {"list": [{"withUser": {"id": 1}, "unreadMessagesCount": 1,
                          "lastMessage": {"fromUser": {"id": 1}}}], "hasMore": False}


async def _window(aid: str, in_ctx: bool) -> list:
    _reset()
    client = _ChatsClient(aid)
    orig = server._load_client
    server._load_client = lambda *_a, **_k: client
    try:
        if in_ctx:
            with server._background_reads(aid):
                await accounts_admin_api.rewarm_roster_count(aid)
        else:
            await accounts_admin_api.rewarm_roster_count(aid)
    finally:
        server._load_client = orig
    assert server._lanes_for(aid)[1].held == 0
    return client.seen


async def case_window_read_inside_context_holds_the_background_lane():
    seen = await _window("acct-r4", in_ctx=True)
    assert seen == [{"bg_held": 1, "total_free": server._ACCOUNT_LANE_TOTAL - 1, "lease": "acct-r4",
                     "priority": "background"}], seen


async def case_window_read_outside_context_takes_no_lane_as_today():
    seen = await _window("acct-r5", in_ctx=False)
    assert seen == [{"bg_held": 0, "total_free": server._ACCOUNT_LANE_TOTAL, "lease": None,
                     "priority": "user"}], seen



class _MeRaises:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def me(self):
        raise self.exc


async def _me_fails(aid: str, exc: BaseException) -> tuple[BaseException | None, list]:
    _reset()
    evicted: list = []
    orig_load, orig_inv = server._load_client, server._invalidate_client
    server._load_client = lambda *_a, **_k: _MeRaises(exc)
    server._invalidate_client = lambda a=None, **_k: evicted.append(a)
    raised = None
    try:
        assert server._request_ctx.get() is None, "no request in flight"
        await server.shared_refresher_reads(aid)
    except Exception as e:  # noqa: BLE001
        raised = e
    finally:
        server._load_client, server._invalidate_client = orig_load, orig_inv
    return raised, evicted


async def case_dead_session_error_from_me_marks_the_creator_dead():
    aid = "acct-r6"
    assert aid not in await account_health.dead_session_map()
    raised, evicted = await _me_fails(aid, OFAPIError('400 {"error":{"code":301,"message":"Wrong user."}}'))
    assert isinstance(raised, HTTPException), "the read still fails: the job holds the Creator"
    dead = await account_health.dead_session_map()
    assert aid in dead and dead[aid].reason == "wrong_user", dead
    assert evicted == [aid], evicted


async def case_no_session_from_me_marks_the_creator_dead():
    aid = "acct-r7"
    raised, evicted = await _me_fails(aid, FileNotFoundError(f"account {aid} has no captured session"))
    assert raised is not None
    dead = await account_health.dead_session_map()
    assert aid in dead and dead[aid].reason == "no_session", dead
    assert evicted == [aid], evicted


async def case_transient_error_marks_nothing():
    aid = "acct-r8"
    raised, evicted = await _me_fails(aid, OFAPIError("500 upstream hiccup"))
    assert isinstance(raised, HTTPException)
    assert aid not in await account_health.dead_session_map() and evicted == []


class _Pooled:

    def __init__(self, aid: str, swap_to=None) -> None:
        self.aid, self.swap_to, self.closed = aid, swap_to, False

    def me(self):
        import client_pool
        if self.swap_to is not None:
            client_pool._POOL[self.aid] = self.swap_to
        raise OFAPIError('400 {"error":{"code":301,"message":"Wrong user."}}')

    def close_signed_sessions(self):
        self.closed = True


async def _pooled_me_fails(aid: str, swap: bool):
    import client_pool
    _reset()
    fresh = _Pooled(aid) if swap else None
    stale = _Pooled(aid, swap_to=fresh)
    client_pool._POOL[aid] = stale
    try:
        try:
            await server.shared_refresher_reads(aid)
        except HTTPException:
            pass
        return stale, fresh, client_pool._POOL.get(aid), await account_health.dead_session_map()
    finally:
        client_pool._POOL.pop(aid, None)


async def case_dead_session_on_a_replaced_client_keeps_the_fresh_one_and_flags_nothing():
    aid = "acct-r30"
    stale, fresh, pooled, dead = await _pooled_me_fails(aid, swap=True)
    assert pooled is fresh and not fresh.closed, ("the fresh client kept", pooled)
    assert aid not in dead, dead


async def case_dead_session_on_the_current_client_evicts_it_and_flags():
    aid = "acct-r31"
    stale, _fresh, pooled, dead = await _pooled_me_fails(aid, swap=False)
    assert pooled is None and stale.closed, ("the dead client evicted", pooled)
    assert aid in dead and dead[aid].reason == "wrong_user", dead


async def case_dead_session_on_a_cold_pool_flags_only_the_client_the_read_built():
    import client_pool
    aid = "acct-r32"
    _reset()
    fresh = _Pooled(aid)
    stale = _Pooled(aid, swap_to=fresh)
    orig_get = client_pool.get

    def build(a):
        client_pool._POOL[a] = stale
        return stale
    client_pool.get = build
    try:
        try:
            await server.shared_refresher_reads(aid)
        except HTTPException:
            pass
        pooled, dead = client_pool._POOL.get(aid), await account_health.dead_session_map()
    finally:
        client_pool.get = orig_get
        client_pool._POOL.pop(aid, None)
    assert pooled is fresh and not fresh.closed, ("the fresh client kept", pooled)
    assert aid not in dead, dead


ME = {"id": 1, "notificationsCount": 2}


class _Resp:
    def __init__(self, status: int, text: str = "", headers: dict | None = None) -> None:
        self.status_code, self.text, self.headers = status, text, headers or {}


class _Me:

    def __init__(self, exc: BaseException | None = None, during=None) -> None:
        self.exc, self.during, self.calls = exc, during, 0

    def me(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        if self.during is not None:
            self.during()
        return dict(ME)


PRIOR_AT = 1_700_000_000_000
ASK = 500.0


async def _run_job(aid: str, client: _Me, prime=None) -> dict:
    import time
    import app_open_warm
    _reset()
    if prime is not None:
        relay_cache._cache[("users_me", aid, ("users_me",))] = (prime, time.monotonic() + 60.0)
    app_open_warm._exits.clear()
    saved = (server._load_client, shared_refresher._state, dict(shared_refresher._at_ms), shared_refresher._clock)
    server._load_client = lambda *_a, **_k: client
    shared_refresher._clock = lambda: ASK
    shared_refresher._state = shared_refresher_decide.State(last={aid: 1.0})
    shared_refresher._at_ms.clear()
    shared_refresher._at_ms[aid] = PRIOR_AT
    try:
        before = time.monotonic()
        ok = await shared_refresher._job(aid)
        after = time.monotonic()
        ex = app_open_warm._exits.get(app_open_warm._egress(aid)[0])
        return {"ok": ok, "at": shared_refresher._at_ms.get(aid), "state": shared_refresher._state,
                "free_at": None if ex is None else ex.free_at, "before": before, "after": after,
                "entry": relay_cache.peek_fresh("users_me", aid, ("users_me",))}
    finally:
        server._load_client, shared_refresher._state, _, shared_refresher._clock = saved
        shared_refresher._at_ms.clear()
        shared_refresher._at_ms.update(saved[2])
        app_open_warm._exits.clear()


def _held_one_floor(r: dict, aid: str) -> None:
    st = r["state"]
    assert r["ok"] is False and r["at"] == PRIOR_AT and st.last == {aid: 1.0}, ("a failure keeps `at`", r)
    assert st.held == {aid: ASK + shared_refresher_decide.FLOOR_S}, ("first rung: held FLOOR_S", st.held)


async def case_terminal_429_with_retry_after_holds_the_exit_for_it():
    aid = "acct-r11"
    r = await _run_job(aid, _Me(OFAPIError("429", _Resp(429, "Too Many Requests", {"Retry-After": "120"}))))
    _held_one_floor(r, aid)
    assert r["free_at"] is not None and r["before"] + 120 <= r["free_at"] <= r["after"] + 120, r


async def case_terminal_429_without_a_wait_holds_the_exit_floor():
    aid = "acct-r12"
    r = await _run_job(aid, _Me(OFAPIError("429", _Resp(429, "Too Many Requests"))))
    _held_one_floor(r, aid)
    assert r["free_at"] is not None and r["before"] + 60 <= r["free_at"] <= r["after"] + 60, r


async def case_other_failure_holds_the_creator_only():
    aid = "acct-r13"
    r = await _run_job(aid, _Me(OFAPIError("500", _Resp(500, "upstream hiccup", {"Retry-After": "120"}))))
    _held_one_floor(r, aid)
    assert r["free_at"] is None, ("no exit hold: not a 429", r)


async def case_discarded_write_back_leaves_at():
    aid = "acct-r14"
    r = await _run_job(aid, _Me(during=lambda: relay_cache.invalidate("users_me", aid)))
    assert r["entry"] is None, "latest-wins: the write-back was discarded"
    _held_one_floor(r, aid)
    assert r["free_at"] is None, r


async def case_kept_read_moves_at_and_never_a_cache_hit():
    aid = "acct-r15"
    client = _Me()
    r = await _run_job(aid, client, prime={"stale": True})
    assert client.calls == 1 and r["entry"] == ME, ("bypass: OF read, the route's entry rewritten", r)
    assert r["ok"] is True and r["at"] > PRIOR_AT and r["state"].last == {aid: ASK} and r["state"].held == {}, r
    assert r["free_at"] is None, r


class _Asker:

    def __init__(self, due: bool = False) -> None:
        self.due, self.lock = due, threading.Lock()

    def snapshot(self, _aid):
        return None

    def window_due(self, _aid):
        with self.lock:
            return self.due


class _MeAndChats(_Me):

    def __init__(self, aid: str, chats_exc: BaseException | None = None, **kw) -> None:
        super().__init__(**kw)
        self.aid, self.chats_exc, self.user_id, self.chats = aid, chats_exc, 999, []

    def list_chats(self, **_k):
        self.chats.append(_lane(self.aid))
        if self.chats_exc is not None:
            raise self.chats_exc
        return {"list": [{"withUser": {"id": 1}, "unreadMessagesCount": 1,
                          "lastMessage": {"fromUser": {"id": 1}}}], "hasMore": False}


async def _cycle_jobs(aid: str, client, *, asks: tuple = (), ws_since=50.0, window_at=100.0, reader=True,
                      at: tuple = (ASK,)) -> dict:
    import app_open_warm
    import of_call_counter
    import of_ws
    _reset()
    app_open_warm._exits.clear()
    seen: list = []

    async def recorder(a):
        seen.append({"aid": a, "priority": server._current_priority(), "caller": of_call_counter.caller_kind()})

    saved = (server._load_client, server._invalidate_client, shared_refresher._state, dict(shared_refresher._at_ms),
             shared_refresher._clock, dict(shared_refresher._contributors), shared_refresher._window_reader,
             dict(shared_refresher._window_asked), of_ws.connected_since)
    evicted: list = []
    server._load_client = lambda *_a, **_k: client
    server._invalidate_client = lambda a=None, **_k: evicted.append(a)
    of_ws.connected_since = lambda a: ws_since if a == aid else None
    server._chats_window_fetched_at.pop(aid, None)
    if window_at is not None:
        server._chats_window_fetched_at[aid] = window_at
    shared_refresher._contributors.clear()
    for i, c in enumerate(asks):
        shared_refresher.register(f"c{i}", c)
    shared_refresher._window_reader = None
    if reader:
        shared_refresher.set_window_reader(recorder)
    shared_refresher._window_asked.clear()
    shared_refresher._state = shared_refresher_decide.State(
        last={aid: 1.0}, shown={aid: {"cycle_s": 600.0, "live": "up", "values": {}}})
    oks = []
    try:
        for t in at:
            shared_refresher._clock = lambda t=t: t
            oks.append(await shared_refresher._job(aid))
        return {"oks": oks, "seen": seen, "evicted": evicted, "state": shared_refresher._state,
                "roster": relay_cache.peek_fresh("roster_count", aid, ())}
    finally:
        (server._load_client, server._invalidate_client, shared_refresher._state, _, shared_refresher._clock, _,
         shared_refresher._window_reader, _, of_ws.connected_since) = saved
        shared_refresher._at_ms.clear()
        shared_refresher._at_ms.update(saved[3])
        shared_refresher._contributors.clear()
        shared_refresher._contributors.update(saved[5])
        shared_refresher._window_asked.clear()
        shared_refresher._window_asked.update(saved[7])
        server._chats_window_fetched_at.pop(aid, None)
        app_open_warm._exits.clear()


async def case_window_due_raised_during_read_1_adds_the_window_in_the_same_job():
    aid = "acct-r16"
    asker = _Asker()

    def observer():
        with asker.lock:
            asker.due = True
    r = await _cycle_jobs(aid, _Me(during=observer), asks=(asker,))
    assert r["oks"] == [True], r
    assert r["seen"] == [{"aid": aid, "priority": "background", "caller": "walk:shared_refresher"}], r["seen"]


async def case_no_window_when_kept_and_not_asked_or_me_discarded():
    r = await _cycle_jobs("acct-r17", _Me(), asks=(_Asker(),))
    assert r["oks"] == [True] and r["seen"] == [], ("WS-kept, nobody asked: no window", r)
    aid = "acct-r18"
    r = await _cycle_jobs(aid, _Me(during=lambda: relay_cache.invalidate("users_me", aid)), ws_since=None)
    assert r["oks"] == [False] and r["seen"] == [], ("a discarded /users/me: the job retries, no window now", r)
    r = await _cycle_jobs("acct-r19", _Me(), ws_since=None, window_at=None)
    assert r["oks"] == [True] and r["seen"] == [], ("no window held: the open reads page 0 itself", r)


async def case_one_window_read_per_cycle_whatever_asked():
    aid = "acct-r20"
    r = await _cycle_jobs(aid, _Me(), asks=(_Asker(True), _Asker(True)), ws_since=None,
                          at=(ASK, ASK + 30.0, ASK + 600.0))
    assert r["oks"] == [True, True, True], r
    assert len(r["seen"]) == 2, ("one window read per Cycle", r["seen"])


async def case_default_reader_is_the_roster_rewarm_on_the_background_lane():
    aid = "acct-r21"
    client = _MeAndChats(aid)
    r = await _cycle_jobs(aid, client, ws_since=None, reader=False)
    assert r["oks"] == [True], r
    assert client.chats == [{"bg_held": 1, "total_free": server._ACCOUNT_LANE_TOTAL - 1, "lease": aid,
                             "priority": "background"}], client.chats
    assert r["roster"] is not None and r["roster"]["unread"] == 1, ("the roster count rewarmed", r["roster"])
    assert server._lanes_for(aid)[1].held == 0


async def case_dead_session_error_from_the_window_marks_the_creator_dead():
    aid = "acct-r22"
    client = _MeAndChats(aid, chats_exc=OFAPIError('400 {"error":{"code":301,"message":"Wrong user."}}'))
    r = await _cycle_jobs(aid, client, ws_since=None, reader=False)
    assert r["oks"] == [False] and r["state"].last == {aid: 1.0}, ("the window failed: no Last refresh", r)
    dead = await account_health.dead_session_map()
    assert aid in dead and dead[aid].reason == "wrong_user", dead
    assert r["evicted"] == [aid], r


class _Slot:

    def __init__(self, held: dict) -> None:
        self.held, self.lock = held, threading.Lock()

    def snapshot(self, aid):
        with self.lock:
            return self.held.get(aid)

    def window_due(self, _aid):
        return False


async def case_note_values_from_a_worker_thread_publishes_once_on_the_loop():
    aid, other = "acct-r9", "acct-r10"
    slot = _Slot({aid: {"n": 3, "at": 1}})
    got: list = []
    loop_thread = threading.get_ident()
    saved = (dict(shared_refresher._contributors), shared_refresher._state, shared_refresher._relay_loop,
             events.publish)
    events.publish = lambda e: got.append((e, threading.get_ident()))

    def moved(v):
        with slot.lock:
            slot.held[aid] = v
        shared_refresher.note_values(aid)

    try:
        shared_refresher.note_values(aid)
        shared_refresher.register("t", slot)
        assert shared_refresher.snapshot(aid)["values"] == {"t": {"n": 3, "at": 1}}
        assert shared_refresher.snapshot(other)["values"] == {"t": None}
        shared_refresher._relay_loop = asyncio.get_running_loop()
        shared_refresher._state = shared_refresher_decide.State(
            shown={aid: {"cycle_s": 600.0, "live": "up", "values": {"t": {"n": 3, "at": 1}}}})
        seq = shared_refresher.snapshot(aid)["seq"]
        await asyncio.to_thread(moved, {"n": 4, "at": 2})
        for _ in range(3):
            await asyncio.sleep(0)
        assert len(got) == 1, got
        (ev, thread), = got
        assert thread == loop_thread, "published on the Relay loop, not the worker"
        assert ev["__account_id"] == aid and ev["creator_refreshed"]["values"] == {"t": {"n": 4, "at": 2}}, ev
        assert ev["creator_refreshed"]["seq"] == seq + 1
        got.clear()
        await asyncio.to_thread(moved, {"n": 4, "at": 3})
        await asyncio.to_thread(shared_refresher.note_values, other)
        for _ in range(3):
            await asyncio.sleep(0)
        assert got == [], got
        assert shared_refresher.snapshot(aid)["values"] == {"t": {"n": 4, "at": 3}}, "rows carry the newest `at`"
    finally:
        shared_refresher._contributors.clear()
        shared_refresher._contributors.update(saved[0])
        shared_refresher._state, shared_refresher._relay_loop, events.publish = saved[1:]


_harness.run()
