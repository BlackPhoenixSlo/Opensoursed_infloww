#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import asyncio
from datetime import datetime  # noqa: E402

import server  # noqa: E402
import accounts_admin_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Message  # noqa: E402
import unread_total_decide  # noqa: E402
import view_lease  # noqa: E402


def _bare(out: dict) -> dict:
    return {k: v for k, v in out.items() if k != "as_of"}


_HOLDER = ("user", "test", "tab")


def _lease(*ids: str) -> None:
    view_lease.renew(_HOLDER, list(ids), None)


_TS = datetime(2026, 6, 21, 12, 0, 0)


class _FakeClient:
    def __init__(self, me: int, recent: list[dict]):
        self.user_id = me
        self._recent = recent

    def list_chats(self, *, limit=10, offset=0, order="recent", filter=None, **_kw):
        page = self._recent[offset:offset + limit]
        return {"list": page, "hasMore": offset + limit < len(self._recent)}


def _chat(fan_id: int, *, unread: int = 0, last_from: int | None = None) -> dict:
    return {
        "withUser": {"id": fan_id},
        "unreadMessagesCount": unread,
        "isMutedNotifications": False,
        "lastMessage": {"fromUser": {"id": fan_id if last_from is None else last_from}},
    }


async def case_compute_roster_count_from_of():
    me = 999
    recent = [
        _chat(1, unread=2, last_from=1),
        _chat(2, unread=0, last_from=2),
        _chat(3, unread=0, last_from=me),
        _chat(4, unread=0, last_from=4),
        _chat(2, unread=0, last_from=2),
    ]

    fake = _FakeClient(me, recent)
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", "acct-of")
    try:
        out = await accounts_admin_api._compute_roster_count_of("acct-of")
    finally:
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", "acct-of")

    assert _bare(out) == {"unread": 1, "owe_reply": 2}, out


async def case_roster_count_caps_at_window():
    me = 5
    cap = server._ROSTER_SCAN_MAX
    recent = [_chat(1000 + i, unread=0, last_from=1000 + i) for i in range(cap * 2)]

    fake = _FakeClient(me, recent)
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", "acct-cap")
    try:
        out = await accounts_admin_api._compute_roster_count_of("acct-cap")
    finally:
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", "acct-cap")

    assert _bare(out) == {"unread": 0, "owe_reply": cap}, out


def case_unread_capped_when_full_window_all_unread():
    me = "5"
    cap = server._ROSTER_SCAN_MAX
    fold = accounts_admin_api._roster_counts_from_rows
    all_unread = [_chat(2000 + i, unread=1) for i in range(cap + 5)]
    assert fold(all_unread) == {"unread": cap, "unread_capped": True}, fold(all_unread)
    assert fold(all_unread, {2000}) == {"unread": cap - 1, "unread_capped": True}
    one_read = [_chat(3000, unread=0, last_from=int(me))] + all_unread[: cap - 1]
    assert fold(one_read) == {"unread": cap - 1}, fold(one_read)
    short = all_unread[: cap - 1]
    assert fold(short) == {"unread": cap - 1}, fold(short)


async def case_reconcile_pulls_of_read_state_into_local():
    from messages import reconcile_chats_from_of

    AID2 = "acct-2"
    async with get_session() as s:
        s.add(Account(id=AID2, nickname="Acct 2"))
        s.add(Message(account_id=AID2, fan_id=10, message_id=1001,
                      direction="in", body="hey", created_at=_TS))
        s.add(Chat(account_id=AID2, fan_id=10, last_message_id=1001, unread_count=7))
        await s.commit()

    of_payload = [{
        "withUser": {"id": 10},
        "unreadMessagesCount": 0,
        "lastMessage": {"id": 1001, "fromUser": {"id": 10},
                        "text": "hey", "createdAt": "2026-06-21T12:00:00+00:00"},
    }, {
        "withUser": {"id": 11},
        "unreadMessagesCount": 2,
        "lastMessage": {"id": 1101, "fromUser": {"id": 11},
                        "text": "hi", "createdAt": "2026-06-21T12:05:00+00:00"},
    }, {
        "withUser": {"id": 12},
        "unreadMessagesCount": 0,
        "lastMessage": {"id": 1201, "fromUser": {"id": int(AID2) if AID2.isdigit() else 0},
                        "text": "ttyl", "createdAt": "2026-06-21T12:06:00+00:00"},
    }]
    AID_NUM = "999"
    async with get_session() as s:
        s.add(Account(id=AID_NUM, nickname="Acct num"))
        s.add(Message(account_id=AID_NUM, fan_id=12, message_id=1200,
                      direction="in", body="u there", created_at=_TS))
        s.add(Chat(account_id=AID_NUM, fan_id=12, last_message_id=1200, unread_count=5))
        await s.commit()
    of_for_num = [{
        "withUser": {"id": 12},
        "unreadMessagesCount": 0,
        "lastMessage": {"id": 1201, "fromUser": {"id": 999},
                        "text": "ttyl", "createdAt": "2026-06-21T12:06:00+00:00"},
    }]

    n = await reconcile_chats_from_of(AID2, of_payload[:2])
    assert n == 2, n
    async with get_session() as s:
        assert (await s.get(Chat, (AID2, 10))).unread_count == 0, "OF-read chat zeroed"
        assert (await s.get(Chat, (AID2, 11))).unread_count == 2, "OF-unread mirrored"

    await reconcile_chats_from_of(AID_NUM, of_for_num)
    async with get_session() as s:
        ch = await s.get(Chat, (AID_NUM, 12))
        assert ch.unread_count == 0 and ch.last_message_id == 1201, ch.last_message_id
        m = await s.get(Message, (AID_NUM, 12, 1201))
        assert m is not None and m.direction == "out", "outbound reply persisted"


async def case_reconcile_runs_in_the_of_writer_never_backwards():
    import asyncio
    from db import of_writer
    from messages import reconcile_chats_from_of

    A, B = "777", "778"
    async with get_session() as s:
        for aid in (A, B):
            s.add(Account(id=aid, nickname=aid))
        s.add(Chat(account_id=A, fan_id=20, last_message_id=2005, unread_count=0))
        await s.commit()

    def page(fan, lm_id, unread):
        return [{"withUser": {"id": fan}, "unreadMessagesCount": unread,
                 "lastMessage": {"id": lm_id, "fromUser": {"id": fan}, "text": "x",
                                 "createdAt": "2026-06-21T12:00:00+00:00"}}]

    of_writer.start()
    try:
        assert of_writer.running()
        n = await asyncio.gather(reconcile_chats_from_of(A, page(20, 2001, 3)),
                                 reconcile_chats_from_of(B, page(21, 2101, 1)))
        assert n == [1, 1], n
    finally:
        await of_writer.stop()
    async with get_session() as s:
        a = await s.get(Chat, (A, 20))
        assert a.unread_count == 3 and a.last_message_id == 2005, (a.unread_count, a.last_message_id)
        b = await s.get(Chat, (B, 21))
        assert b.unread_count == 1 and b.last_message_id == 2101, (b.unread_count, b.last_message_id)
        assert (await s.get(Message, (B, 21, 2101))).direction == "in"


async def case_roster_bust_recomputes_only_target():

    class _User:
        account_ids = ["acct-x", "acct-y"]

    class _Resp:
        def __init__(self):
            self.headers: dict[str, str] = {}

    calls: list[str] = []

    async def _fake_compute(aid: str, *, bypass: bool = False) -> dict[str, int]:
        calls.append(aid)
        return {"unread": 1, "owe_reply": 0}

    orig_user = server._get_request_user
    orig_compute = accounts_admin_api._compute_roster_count_of
    server._get_request_user = lambda: _User()
    accounts_admin_api._compute_roster_count_of = _fake_compute
    _lease("acct-x", "acct-y")
    server.relay_cache.invalidate("roster_count", "acct-x")
    server.relay_cache.invalidate("roster_count", "acct-y")
    try:
        r_cold = await accounts_admin_api.admin_accounts_roster_counts(_Resp())
        assert sorted(calls) == ["acct-x", "acct-y"], calls
        assert set(r_cold["counts"]) == {"acct-x", "acct-y"}, r_cold

        await accounts_admin_api.admin_accounts_roster_counts(_Resp())
        assert len(calls) == 2, f"warm read recomputed: {calls}"

        r_bust = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust="acct-x")
        assert calls[2:] == ["acct-x"], f"bust rescanned more than target: {calls[2:]}"
        assert set(r_bust["counts"]) == {"acct-x"}, r_bust

        r_foreign = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust="acct-z")
        assert calls[3:] == [], f"foreign bust evicted/recomputed: {calls[3:]}"
        assert set(r_foreign["counts"]) == {"acct-x", "acct-y"}, r_foreign
    finally:
        _lease()
        server._get_request_user = orig_user
        accounts_admin_api._compute_roster_count_of = orig_compute
        server.relay_cache.invalidate("roster_count", "acct-x")
        server.relay_cache.invalidate("roster_count", "acct-y")


async def case_roster_counts_skip_a_watcher():

    class _User:
        account_ids = ["acct-x", "acct-w"]

    class _Resp:
        def __init__(self):
            self.headers: dict[str, str] = {}

    calls: list[str] = []

    async def _fake_compute(aid: str, *, bypass: bool = False) -> dict[str, int]:
        calls.append(aid)
        return {"unread": 1, "owe_reply": 0}

    orig_user = server._get_request_user
    orig_compute = accounts_admin_api._compute_roster_count_of
    orig_is_watcher = accounts_admin_api.account_registry.is_watcher
    server._get_request_user = lambda: _User()
    accounts_admin_api._compute_roster_count_of = _fake_compute
    accounts_admin_api.account_registry.is_watcher = lambda aid: aid == "acct-w"
    _lease("acct-x", "acct-w")
    for aid in ("acct-x", "acct-w"):
        server.relay_cache.invalidate("roster_count", aid)
    try:
        r = await accounts_admin_api.admin_accounts_roster_counts(_Resp())
        assert calls == ["acct-x"], calls
        assert set(r["counts"]) == {"acct-x"}, r
        r_bust = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust="acct-w")
        assert "acct-w" not in calls and "acct-w" not in r_bust["counts"], (calls, r_bust)
    finally:
        server._get_request_user = orig_user
        accounts_admin_api._compute_roster_count_of = orig_compute
        accounts_admin_api.account_registry.is_watcher = orig_is_watcher
        _lease()
        for aid in ("acct-x", "acct-w"):
            server.relay_cache.invalidate("roster_count", aid)


async def case_assemble_tops_up_past_of_page_cap():
    me = 7

    class _CappedClient(_FakeClient):
        def list_chats(self, *, limit=10, offset=0, order="recent", filter=None, **_kw):
            return super().list_chats(
                limit=min(int(limit), 10), offset=offset, order=order, filter=filter,
            )

    recent = [_chat(2000 + i, unread=(1 if i % 5 == 0 else 0)) for i in range(40)]
    fake = _CappedClient(me, recent)

    page = server._assemble_chats_page(fake, limit=25, offset=0, order="recent")
    rows = page["list"]
    assert len(rows) == 25, f"top-up assembled {len(rows)} rows, wanted 25"
    assert page["hasMore"] is True, page
    got = [r["withUser"]["id"] for r in rows]
    assert got == [2000 + i for i in range(25)], got[:30]


async def case_assemble_empty_page_ends_pagination():
    fake = _FakeClient(1, [])
    page = server._assemble_chats_page(fake, limit=25, offset=0, order="recent")
    assert (page["list"], page["hasMore"]) == ([], False), page

    fake2 = _FakeClient(1, [_chat(1)])
    page2 = server._assemble_chats_page(fake2, limit=25, offset=25, order="recent")
    assert (page2["list"], page2["hasMore"]) == ([], False), page2


# OF caps /chats at ~10 rows per page regardless of `limit`.
async def case_assemble_dup_only_page_breaks():
    class _StuckClient:
        def __init__(self):
            self.calls = 0
            self._page = [_chat(4000 + i) for i in range(10)]

        def list_chats(self, **_kw):
            self.calls += 1
            return {"list": list(self._page), "hasMore": True}

    fake = _StuckClient()
    page = server._assemble_chats_page(fake, limit=25, offset=0, order="recent")
    assert len(page["list"]) == 10, len(page["list"])
    assert fake.calls == 2, f"dup-only page should stop after 2 reads, made {fake.calls}"


async def case_bust_rewarms_shared_list_window():
    me = 3
    AID = "acct-bridge"
    recent = [_chat(3000 + i, unread=(1 if i < 3 else 0)) for i in range(8)]

    class _CountingClient(_FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.calls = 0

        def list_chats(self, **kw):
            self.calls += 1
            return super().list_chats(**kw)

    fake = _CountingClient(me, recent)
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", AID)
    server.relay_cache.invalidate("roster_count", AID)
    try:
        out = await accounts_admin_api._compute_roster_count_of(AID, bypass=True)
        assert _bare(out) == {"unread": 3, "owe_reply": 5}, out
        assert fake.calls == 1, f"bypass read OF {fake.calls}x, wanted 1"

        out2 = await accounts_admin_api._compute_roster_count_of(AID)
        assert _bare(out2) == _bare(out), out2
        assert fake.calls == 1, f"warm-window recompute hit OF: {fake.calls}"

        def _must_not_fetch():
            raise AssertionError("list endpoint fetcher ran — window not shared")
        resp = await server.relay_cache.get_or_fetch(
            "list_chats", AID,
            (server._ROSTER_SCAN_MAX, 0, "recent", None, None, None),
            ttl_seconds=server._LIST_CHATS_TTL, fetcher=_must_not_fetch,
        )
        got = [r["withUser"]["id"] for r in (resp.get("list") or [])]
        assert got == [3000 + i for i in range(8)], got

        server._chats_window_fetched_at[AID] = (
            server._time_mod.monotonic() - server._ROSTER_WINDOW_MAX_AGE_S - 1
        )
        out3 = await accounts_admin_api._compute_roster_count_of(AID)
        assert _bare(out3) == _bare(out), out3
        assert fake.calls == 2, f"aged window must force a live re-read: {fake.calls}"
    finally:
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", AID)
        server.relay_cache.invalidate("roster_count", AID)
        server._chats_window_fetched_at.pop(AID, None)


async def case_ws_kept_window_is_folded_past_300s_within_its_list_ttl():
    import of_ws

    me = 4
    AID = "acct-ws-kept"
    recent = [_chat(5000 + i, unread=(1 if i < 2 else 0)) for i in range(6)]

    class _CountingClient(_FakeClient):
        def __init__(self, *a):
            super().__init__(*a)
            self.calls = 0

        def list_chats(self, **kw):
            self.calls += 1
            return super().list_chats(**kw)

    class _Pump:
        connected_at: float | None = None

    fake = _CountingClient(me, recent)
    pump = _Pump()
    orig = server._load_client
    server._load_client = lambda _aid: fake
    server.relay_cache.invalidate("list_chats", AID)
    try:
        pump.connected_at = server._time_mod.monotonic()
        of_ws.register_pump(AID, pump)
        await accounts_admin_api._compute_roster_count_of(AID)
        assert fake.calls == 1, fake.calls
        aged = server._time_mod.monotonic() - server._ROSTER_WINDOW_MAX_AGE_S - 1

        pump.connected_at = aged - 1
        server._chats_window_fetched_at[AID] = aged
        out = await accounts_admin_api._compute_roster_count_of(AID)
        assert _bare(out) == {"unread": 2, "owe_reply": 4}, out
        assert fake.calls == 1, f"a WS-kept window re-read OF: {fake.calls}"

        pump.connected_at = aged + 1
        server._chats_window_fetched_at[AID] = aged
        await accounts_admin_api._compute_roster_count_of(AID)
        assert fake.calls == 2, f"a window older than the socket must re-read: {fake.calls}"

        of_ws.unregister_pump(AID)
        server._chats_window_fetched_at[AID] = aged
        await accounts_admin_api._compute_roster_count_of(AID)
        assert fake.calls == 3, f"no pump, aged window must re-read: {fake.calls}"
    finally:
        of_ws.unregister_pump(AID)
        server._load_client = orig
        server.relay_cache.invalidate("list_chats", AID)
        server._chats_window_fetched_at.pop(AID, None)


class _Resp:
    def __init__(self):
        self.headers: dict[str, str] = {}


class _CountingClient(_FakeClient):
    def __init__(self, *a):
        super().__init__(*a)
        self.calls = 0

    def list_chats(self, **kw):
        self.calls += 1
        return super().list_chats(**kw)


async def case_roster_counts_read_of_only_for_leased_creators():
    import time

    me = 9
    L, U, N = "acct-leased", "acct-idle", "acct-never"

    class _User:
        account_ids = [L, U, N]

    clients = {a: _CountingClient(me, [_chat(6000 + i, unread=(1 if i < 2 else 0)) for i in range(5)])
               for a in (L, U, N)}
    orig_user, orig_load = server._get_request_user, server._load_client
    server._get_request_user = lambda: _User()
    server._load_client = lambda aid: clients[aid]

    def clean():
        for a in (L, U, N):
            server.relay_cache.invalidate("list_chats", a)
            server.relay_cache.invalidate("roster_count", a)
            server._chats_window_fetched_at.pop(a, None)
            accounts_admin_api._roster_last.pop(a, None)
    clean()
    try:
        t0 = time.time() * 1000
        warm = await accounts_admin_api._compute_roster_count_of(U, bypass=True)
        assert clients[U].calls == 1
        server._chats_window_fetched_at[U] = server._time_mod.monotonic() - 3600
        server.relay_cache.patch("list_chats", U, lambda _key, window: {
            **window, "fetched_at": warm["as_of"] - 3600_000,
        })
        _lease(L)

        r = (await accounts_admin_api.admin_accounts_roster_counts(_Resp()))["counts"]
        assert set(r) == {L, U}, r
        assert clients[L].calls == 1, clients[L].calls
        assert clients[U].calls == 1 and clients[N].calls == 0, (clients[U].calls, clients[N].calls)
        assert _bare(r[U]) == {"unread": 2, "owe_reply": 3}, r[U]
        assert r[U]["as_of"] == warm["as_of"] - 3600_000, r[U]
        assert r[L]["as_of"] >= t0, r[L]

        server.relay_cache.invalidate("list_chats", U)
        r2 = (await accounts_admin_api.admin_accounts_roster_counts(_Resp()))["counts"]
        assert r2[U] == r[U] and clients[U].calls == 1, (r2[U], clients[U].calls)

        r3 = (await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust=N))["counts"]
        assert clients[N].calls == 1 and set(r3) == {N} and r3[N]["as_of"] >= t0, (clients[N].calls, r3)
    finally:
        _lease()
        server._get_request_user, server._load_client = orig_user, orig_load
        clean()


async def case_roster_counts_never_read_a_dead_creator():
    D = "acct-dead"

    class _User:
        account_ids = [D]

    fake = _CountingClient(9, [_chat(7000, unread=1)])
    orig_user, orig_load = server._get_request_user, server._load_client
    orig_dead = accounts_admin_api.account_health.dead_session_map
    server._get_request_user = lambda: _User()
    server._load_client = lambda _aid: fake

    async def _dead():
        return {D: object()}
    accounts_admin_api.account_health.dead_session_map = _dead
    for ns in ("list_chats", "roster_count"):
        server.relay_cache.invalidate(ns, D)
    accounts_admin_api._roster_last.pop(D, None)
    _lease(D)
    try:
        assert (await accounts_admin_api.admin_accounts_roster_counts(_Resp()))["counts"] == {}
        assert (await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust=D))["counts"] == {}
        assert fake.calls == 0, fake.calls
        accounts_admin_api._roster_last[D] = {"unread": 4, "owe_reply": 0, "as_of": 1}
        r = (await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust=D))["counts"]
        assert r == {D: {"unread": 4, "owe_reply": 0, "as_of": 1}} and fake.calls == 0, (r, fake.calls)
    finally:
        _lease()
        server._get_request_user, server._load_client = orig_user, orig_load
        accounts_admin_api.account_health.dead_session_map = orig_dead
        accounts_admin_api._roster_last.pop(D, None)


async def case_roster_counts_dead_session_flags_only_the_client_the_read_started_on():
    import client_pool
    from of_client import OFAPIError
    import account_health

    class _User:
        account_ids: list = []

    class _Resp:
        def __init__(self):
            self.headers: dict[str, str] = {}

    class _Pooled:
        def __init__(self, aid, swap_to=None):
            self.aid, self.swap_to, self.closed, self.user_id = aid, swap_to, False, 9

        def list_chats(self, **_kw):
            if self.swap_to is not None:
                client_pool._POOL[self.aid] = self.swap_to
            raise OFAPIError('400 {"error":{"code":301,"message":"Wrong user."}}')

        def close_signed_sessions(self):
            self.closed = True

    orig_user = server._get_request_user
    server._get_request_user = lambda: _User()
    try:
        for aid, swap in (("acct-swap", True), ("acct-same", False)):
            _User.account_ids = [aid]
            for ns in ("list_chats", "roster_count"):
                server.relay_cache.invalidate(ns, aid)
            fresh = _Pooled(aid) if swap else None
            stale = client_pool._POOL[aid] = _Pooled(aid, swap_to=fresh)
            _lease(aid)
            r = (await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust=aid))["counts"]
            assert _bare(r[aid]) == {"unread": 0, "owe_reply": 0}, r
            dead = await account_health.dead_session_map()
            if swap:
                assert client_pool._POOL.get(aid) is fresh and not fresh.closed, client_pool._POOL.get(aid)
                assert aid not in dead, dead
            else:
                assert client_pool._POOL.get(aid) is None and stale.closed
                assert aid in dead and dead[aid].reason == "wrong_user", dead
            client_pool._POOL.pop(aid, None)
    finally:
        _lease()
        server._get_request_user = orig_user
        accounts_admin_api._roster_last.pop("acct-swap", None)
        accounts_admin_api._roster_last.pop("acct-same", None)


async def case_every_answer_carries_server_now():
    import time
    D, X = "acct-now-dead", "acct-now-x"
    owned: list[str] = []

    class _User:
        account_ids = owned

    class _Resp:
        def __init__(self):
            self.headers: dict[str, str] = {}

    async def _fake_compute(aid: str, *, bypass: bool = False) -> dict[str, int]:
        return {"unread": 1, "owe_reply": 0, "as_of": 0}

    async def _dead():
        return {D: object()}
    orig_user, orig_compute = server._get_request_user, accounts_admin_api._compute_roster_count_of
    orig_dead = accounts_admin_api.account_health.dead_session_map
    server._get_request_user = lambda: _User()
    accounts_admin_api._compute_roster_count_of = _fake_compute
    accounts_admin_api.account_health.dead_session_map = _dead
    _lease(X, D)
    try:
        answers = {"no Creators": await accounts_admin_api.admin_accounts_roster_counts(_Resp())}
        owned[:] = [X, D]
        answers["full map"] = await accounts_admin_api.admin_accounts_roster_counts(_Resp())
        answers["bust"] = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust=X)
        answers["dead bust"] = await accounts_admin_api.admin_accounts_roster_counts(_Resp(), bust=D)
        t = time.time() * 1000
        for why, a in answers.items():
            assert isinstance(a.get("now"), int) and abs(a["now"] - t) < 5_000, (why, a)
    finally:
        _lease()
        server._get_request_user = orig_user
        accounts_admin_api._compute_roster_count_of = orig_compute
        accounts_admin_api.account_health.dead_session_map = orig_dead
        server.relay_cache.invalidate("roster_count", X)


def case_fold_exclusion_is_the_one_predicate():
    fold = accounts_admin_api._roster_counts_from_rows
    reg, of_flag, friends, plain = 4001, 4002, 4003, 4004
    rows = [
        _chat(reg, unread=1),
        {**_chat(of_flag, unread=1), "withUser": {"id": of_flag, "isRestricted": True}},
        {**_chat(friends, unread=1), "canSendMessage": False, "canNotSendReason": "only_friends"},
        _chat(plain, unread=1),
    ]
    assert fold(rows, {reg}) == {"unread": 2}, fold(rows, {reg})
    assert fold(rows[1:2], {reg})["unread"] == 1, "OF isRestricted alone counts"
    assert fold(rows[2:3], {reg})["unread"] == 0, "only_friends excluded"
    real = unread_total_decide.excluded_from_badges
    unread_total_decide.excluded_from_badges = lambda fan, row, ids: fan != reg and real(fan, row, ids)
    try:
        assert fold(rows, {reg}) == {"unread": 3}, fold(rows, {reg})
    finally:
        unread_total_decide.excluded_from_badges = real


async def case_fold_reports_restricted_unread():
    import unread_total
    from automations._common import set_of_restricted_skip
    aid, me = "acct-r", 5
    reg, friends, gone, muted_reg, plain = 4101, 4102, 4103, 4104, 4105
    rows = [
        _chat(reg, unread=1),
        {**_chat(friends, unread=1), "canSendMessage": False, "canNotSendReason": "only_friends"},
        {**_chat(gone, unread=1), "canSendMessage": False, "canNotSendReason": "chat_unavailable"},
        {**_chat(muted_reg, unread=1), "isMutedNotifications": True},
        _chat(plain, unread=1),
        _chat(reg, unread=1),
    ]
    got: list = []
    orig_set, orig_load = unread_total.set_restricted_unread, server._load_client
    unread_total.set_restricted_unread = lambda a, r, at: got.append((a, r.n, at))
    server._load_client = lambda _aid: _FakeClient(me, rows)
    real = unread_total_decide.excluded_from_badges
    server.relay_cache.invalidate("list_chats", aid)
    for f in (reg, muted_reg):
        await set_of_restricted_skip(aid, f, True)
    try:
        out = await accounts_admin_api._compute_roster_count_of(aid, bypass=True)
        assert got == [(aid, 2, out["as_of"])] and out["as_of"] > 0, (got, out)
        assert out["unread"] == 1, out
        unread_total_decide.excluded_from_badges = lambda fan, row, ids: fan != reg and real(fan, row, ids)
        out = await accounts_admin_api._compute_roster_count_of(aid)
        assert got[-1] == (aid, 1, out["as_of"]) and out["unread"] == 2, (got, out)
    finally:
        unread_total_decide.excluded_from_badges = real
        unread_total.set_restricted_unread, server._load_client = orig_set, orig_load
        for f in (reg, muted_reg):
            await set_of_restricted_skip(aid, f, False)
        server.relay_cache.invalidate("list_chats", aid)
        server._chats_window_fetched_at.pop(aid, None)
        accounts_admin_api._roster_last.pop(aid, None)


_GUARD_ME, _MUTED, _UNKNOWN, _REG, _OWED, _OWED2, _BLUE = 7, 4201, 4202, 4203, 4204, 4205, 4206


def _guard_rows() -> list[dict]:
    return [
        {**_chat(_MUTED), "isMutedNotifications": True},
        {k: v for k, v in _chat(_UNKNOWN).items() if k != "isMutedNotifications"},
        _chat(_REG),
        _chat(_OWED),
        _chat(_OWED2),
        _chat(_BLUE, unread=1),
    ]


async def _held_route_counts(aid: str, rows: list[dict]) -> tuple[dict, int]:
    from automations._common import set_of_restricted_skip

    class _User:
        account_ids = [aid]

    fake = _CountingClient(_GUARD_ME, rows)
    orig_user, orig_load = server._get_request_user, server._load_client
    server._get_request_user = lambda: _User()
    server._load_client = lambda _aid: fake
    await set_of_restricted_skip(aid, _REG, True)
    try:
        await accounts_admin_api._compute_roster_count_of(aid, bypass=True)
        server._chats_window_fetched_at[aid] = server._time_mod.monotonic() - 3600
        r = (await accounts_admin_api.admin_accounts_roster_counts(_Resp()))["counts"]
        return r[aid], fake.calls
    finally:
        server._get_request_user, server._load_client = orig_user, orig_load
        await set_of_restricted_skip(aid, _REG, False)


def _forget(aid: str) -> None:
    server.relay_cache.invalidate("list_chats", aid)
    server.relay_cache.invalidate("roster_count", aid)
    server._chats_window_fetched_at.pop(aid, None)
    accounts_admin_api._roster_last.pop(aid, None)


async def case_owe_reply_uses_amber_guards():
    aid = "acct-amber-guards"
    _forget(aid)
    try:
        out, calls = await _held_route_counts(aid, _guard_rows())
        assert _bare(out) == {"unread": 1, "owe_reply": 2} and calls == 1, (out, calls)
    finally:
        _forget(aid)


async def case_owe_reply_excludes_latest_unread_set():
    import badge_reads
    aid = "acct-amber-set"
    real = badge_reads.unread_set
    badge_reads.unread_set = lambda a: badge_reads.UnreadView(frozenset({_OWED}), 1) if a == aid else real(a)
    _forget(aid)
    try:
        out, _ = await _held_route_counts(aid, _guard_rows())
        assert _bare(out) == {"unread": 1, "owe_reply": 1}, out
        badge_reads.unread_set = real
        _forget(aid)
        out, _ = await _held_route_counts(aid, _guard_rows())
        assert _bare(out) == {"unread": 1, "owe_reply": 2}, out
    finally:
        badge_reads.unread_set = real
        _forget(aid)



async def case_invalidated_window_does_not_cache_roster_count():
    aid = "acct-invalidated-window"
    loop = asyncio.get_running_loop()

    async def invalidate():
        server.relay_cache.invalidate("list_chats", aid)

    class InvalidatedClient(_FakeClient):
        def list_chats(self, **kwargs):
            asyncio.run_coroutine_threadsafe(invalidate(), loop).result(5)
            return super().list_chats(**kwargs)

    original = server._load_client
    server._load_client = lambda _aid: InvalidatedClient(999, [_chat(1)])
    try:
        await accounts_admin_api.rewarm_roster_count(aid)
        assert accounts_admin_api.held_window(aid) is None
        assert server.relay_cache.peek_fresh("roster_count", aid, ()) is None
    finally:
        server._load_client = original
        server.relay_cache.invalidate("roster_count", aid)

_harness.run(
    case_invalidated_window_does_not_cache_roster_count,
    case_fold_reports_restricted_unread,
    case_owe_reply_uses_amber_guards,
    case_owe_reply_excludes_latest_unread_set,
    case_ws_kept_window_is_folded_past_300s_within_its_list_ttl,
    case_compute_roster_count_from_of,
    case_roster_count_caps_at_window,
    case_unread_capped_when_full_window_all_unread,
    case_fold_exclusion_is_the_one_predicate,
    case_reconcile_pulls_of_read_state_into_local,
    case_reconcile_runs_in_the_of_writer_never_backwards,
    case_roster_bust_recomputes_only_target,
    case_roster_counts_skip_a_watcher,
    case_assemble_tops_up_past_of_page_cap,
    case_assemble_empty_page_ends_pagination,
    case_assemble_dup_only_page_breaks,
    case_bust_rewarms_shared_list_window,
    case_roster_counts_read_of_only_for_leased_creators,
    case_roster_counts_never_read_a_dead_creator,
    case_roster_counts_dead_session_flags_only_the_client_the_read_started_on,
    case_every_answer_carries_server_now,
)
