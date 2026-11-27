#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import importlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chatter, ChatterUser, User, UserAccount  # noqa: E402

_harness.make_client()
import server  # noqa: E402
import automation_executor as ax  # noqa: E402
import events  # noqa: E402
import events_decide as ed  # noqa: E402
import of_ws  # noqa: E402
import relay_cache  # noqa: E402
import s4s_api  # noqa: E402
import shared_refresher  # noqa: E402
import shared_refresher_decide  # noqa: E402
import unread_total  # noqa: E402
from unread_total_decide import Restricted  # noqa: E402
from of_client import OFClient  # noqa: E402

A, B = "8131", "8132"
_CREATORS = (A, B)
ME = "/api2/v2/users/me"
CHATS = "/api2/v2/chats"

account_registry.get_account = lambda aid: {"id": aid} if aid in _CREATORS else None
account_registry.list_accounts = lambda include_watchers=False: [{"id": a, "has_session": True} for a in _CREATORS]
account_registry.is_account = lambda aid: aid in _CREATORS
account_registry.get_role = lambda aid: None
account_registry.get_active_account_id = lambda: A


async def _setup() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        s.add(boss)
        s.add_all([Account(id=a, nickname=a) for a in _CREATORS])
        cid = uuid.uuid4().hex
        s.add(Chatter(id=cid, username="chat", password="pw", display_name="Chat",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=a) for a in _CREATORS])
        s.add(ChatterUser(chatter_id=cid, user_id=boss.id, created_at=datetime.utcnow()))


asyncio.run(_setup())


class _Resp:
    def __init__(self, url, status, body):
        self.url, self.status_code, self.ok = url, status, 200 <= status < 300
        self.text, self.headers = json.dumps(body), {}

    def json(self):
        return json.loads(self.text)


class _Wire:
    def __init__(self, n=3):
        self.me = (200, {"chatMessagesCount": n, "wsUrl": "wss://ws", "wsAuthToken": "t"})
        self.chats: list = []
        self.calls = []

    def _answer(self, method, url):
        path = urlsplit(url).path
        self.calls.append((method, path))
        if method == "GET" and path == ME:
            return _Resp(url, *self.me)
        if method == "GET" and path == CHATS:
            return _Resp(url, 200, {"list": self.chats, "hasMore": False})
        return _Resp(url, 200, {"chatMessagesCount": 99})

    def get(self, url, headers=None, timeout=None):
        return self._answer("GET", url)

    def request(self, method, url, json=None, headers=None, timeout=None):
        return self._answer(method, url)


def _client(aid: str, wire: _Wire) -> OFClient:
    c = OFClient({"headers": {"user_id": aid, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                  "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                        "checksum_indexes": [1], "checksum_constant": 1}},
                  "cookies": []})
    c._x_hash = "h"
    c.http = wire
    return c


def _r0() -> None:
    for a in _CREATORS:
        unread_total.set_restricted_unread(a, Restricted(0, False, 0), 0)


@contextlib.contextmanager
def _knobs(shared: bool, unread: bool, r_known: bool = True):
    saved = {k: os.environ.get(k) for k in ("SHARED_REFRESHER", "UNREAD_TOTAL")}

    def _set(k, v):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _set("SHARED_REFRESHER", "1" if shared else None)
    _set("UNREAD_TOTAL", "1" if unread else None)
    importlib.reload(shared_refresher)
    importlib.reload(unread_total)
    if r_known:
        _r0()
    try:
        yield
    finally:
        for k, v in saved.items():
            _set(k, v)
        importlib.reload(shared_refresher)
        importlib.reload(unread_total)


_UP_LONG_AGO = -1e10


@contextlib.contextmanager
def _live(since: float | None):
    saved = of_ws.connected_since
    of_ws.connected_since = lambda _a: since
    try:
        yield
    finally:
        of_ws.connected_since = saved


@contextlib.contextmanager
def _world(wire: _Wire):
    published: list = []
    client = _client(A, wire)
    live = _live(_UP_LONG_AGO)
    live.__enter__()
    orig = (server._get_client, server._resolve_account_id, ax._make_client, events.publish)
    server._get_client = lambda *_a: client
    server._resolve_account_id = lambda *_a: A
    ax._make_client = lambda _aid: client
    events.publish = published.append
    relay_cache.invalidate("users_me", A)
    shared_refresher._relay_loop = asyncio.get_running_loop()
    shared_refresher._state = shared_refresher_decide.State(
        shown={A: {"cycle_s": 600.0, "live": "up", "values": shared_refresher._values_of(A)}})
    try:
        yield published
    finally:
        server._get_client, server._resolve_account_id, ax._make_client, events.publish = orig
        relay_cache.invalidate("users_me", A)
        live.__exit__(None, None, None)


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


def _totals(published) -> list:
    out = []
    for e in published:
        assert list(e) == ["creator_refreshed", "__account_id"] and e["__account_id"] == A, e
        out.append(e["creator_refreshed"]["values"]["unread_total"])
    return out


FAN, FAN2 = 9101, 9102


async def _hold_window(rows: list, *, fetched_at: int | None = None) -> None:
    from accounts_admin_api import _ROSTER_WINDOW_KEY
    relay_cache.invalidate("list_chats", A)
    await relay_cache.get_or_fetch("list_chats", A, _ROSTER_WINDOW_KEY, ttl_seconds=600,
                                   fetcher=lambda: {"list": rows, "hasMore": False,
                                                    "fetched_at": fetched_at})


def _row(fan: int, unread: bool) -> dict:
    return {"withUser": {"id": fan}, "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0,
            "lastMessage": {"id": fan * 10}}


def _of(published, kind: str) -> list:
    return [e[kind] for e in published if kind in e]


def _ns(published) -> list:
    return [e["values"]["unread_total"]["n"] for e in _of(published, "creator_refreshed")]


async def _confirmed(wire: _Wire, pub: list) -> None:
    await server.users_me()
    await _settle()
    assert _slot()["n"] == wire.me[1]["chatMessagesCount"], _slot()
    pub.clear()
    wire.calls.clear()


_UNSEEDED = {"n": None, "at": None, "v": 0, "grey": "unseeded", "amber": None, "amber_at": None}


def _slot(aid=A):
    return shared_refresher.snapshot(aid)["values"].get("unread_total", "absent")


def _ms() -> int:
    return int(time.time() * 1000)


async def case_route_fetch_observed_cache_hit_not():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            assert _slot() == _UNSEEDED, ("on, no confirmation yet: an object, grey", _slot())
            t0 = _ms()
            me = await server.users_me()
            t1 = _ms()
            await _settle()
            assert me["chatMessagesCount"] == 3 and wire.calls == [("GET", ME)], (me, wire.calls)
            (got,) = _totals(pub)
            assert got["n"] == 3 and t0 <= got["at"] <= t1, ("`at`: the read's ask time", got, t0, t1)
            assert _slot() == got, _slot()
            pub.clear()
            wire.me = (200, {"chatMessagesCount": 5})
            await server.users_me()
            await server.users_me(max_age=1800)
            await _settle()
            assert wire.calls == [("GET", ME)], ("cache hits reach no OF", wire.calls)
            assert pub == [] and _slot() == got, ("a cache hit is never a confirmation", pub, _slot())


async def case_s4s_fetch_observed():
    with _knobs(True, True):
        wire = _Wire(7)
        with _world(wire) as pub:
            t0 = _ms()
            me = await s4s_api._of_me(A)
            await _settle()
            assert me is not None and wire.calls == [("GET", ME)], (me, wire.calls)
            (got,) = _totals(pub)
            assert got["n"] == 7 and t0 <= got["at"], got
            pub.clear()
            await server.users_me()
            await _settle()
            assert wire.calls == [("GET", ME)] and pub == [], (wire.calls, pub)


async def case_unchanged_n_publishes_nothing():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            await server.users_me()
            await _settle()
            first = _slot()
            pub.clear()
            relay_cache.invalidate("users_me", A)
            time.sleep(0.002)
            await server.users_me()
            await _settle()
            assert len(wire.calls) == 2, wire.calls
            assert pub == [], ("an unchanged `n` publishes nothing", pub)
            assert _slot()["n"] == 3 and _slot()["at"] > first["at"], ("rows carry the newest `at`", first, _slot())
            relay_cache.invalidate("users_me", A)
            wire.me = (200, {"chatMessagesCount": 1})
            await server.users_me()
            await _settle()
            assert [t["n"] for t in _totals(pub)] == [1], ("OF's number adopted, published once", pub)


async def case_direct_reads_observed_health_and_reconnect_auth():
    with _knobs(True, True):
        wire = _Wire(4)
        with _world(wire) as pub:
            client = _client(A, wire)
            await asyncio.to_thread(client.me)
            await _settle()
            assert [t["n"] for t in _totals(pub)] == [4], pub
            pub.clear()
            importlib.reload(unread_total)
            assert _slot() == _UNSEEDED, _slot()
            _r0()
            wire.me = (200, {"chatMessagesCount": 2, "wsUrl": "wss://ws", "wsAuthToken": "t"})
            ws = of_ws.OFWebSocket(lambda: client, account_id=A)
            await asyncio.to_thread(ws._refresh_auth, client)
            await _settle()
            assert [t["n"] for t in _totals(pub)] == [2], ("the reconnect read refills the total", pub)


async def case_only_a_2xx_get_of_users_me_with_a_count():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            client = _client(A, wire)
            await asyncio.to_thread(client.get_json, "/api2/v2/users/me/settings")
            await asyncio.to_thread(client.request_json, "PATCH", ME, json_body={"x": 1})
            wire.me = (200, {"name": "no counter"})
            await asyncio.to_thread(client.me)
            await _settle()
            assert len(wire.calls) == 3 and pub == [] and _slot() == _UNSEEDED, (wire.calls, pub, _slot())


async def case_dead_session_keeps_its_last_total():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            await server.users_me()
            await _settle()
            held = _slot()
            assert held is not None and held["n"] == 3, held
            pub.clear()
            relay_cache.invalidate("users_me", A)
            wire.me = (401, {"error": {"code": 401, "message": "Please login"}})
            raised = None
            try:
                await server.users_me()
            except Exception as e:  # noqa: BLE001 — _proxy's answer to OF's 401
                raised = e
            await _settle()
            assert raised is not None and len(wire.calls) == 2, (raised, wire.calls)
            assert pub == [] and _slot() == held, ("frozen at its last `at`", pub, _slot(), held)


async def case_an_answer_without_a_counter_drops_the_held_total():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            await server.users_me()
            await _settle()
            assert _slot()["n"] == 3, _slot()
            pub.clear()
            relay_cache.invalidate("users_me", A)
            wire.me = (200, {"name": "no counter"})
            await server.users_me()
            await _settle()
            assert len(wire.calls) == 2 and _slot()["n"] is None and _slot()["grey"] == "unseeded", (wire.calls, _slot())
            assert [t["n"] for t in _totals(pub)] == [None], ("the drop is published once, `n` null", pub)
            relay_cache.invalidate("users_me", A)
            wire.me = (200, {"chatMessagesCount": 2})
            await server.users_me()
            await _settle()
            assert _slot()["n"] == 2 and [t["n"] for t in _totals(pub)] == [None, 2], (_slot(), pub)


async def case_an_answer_without_a_counter_keeps_the_records_adjustments_and_due_read():
    import unread_total_decide as decide
    with _knobs(True, True):
        rec, adj = {7: (True, 150)}, (decide.Adj(stamp=900, delta=-1),)
        unread_total._held[A] = decide.State(n=3, at=100, base=4, adj=adj, rec=rec, due=100)
        unread_total.observe(A, {"name": "no counter"}, 200)
        st = unread_total._held[A]
        assert (st.n, st.at, st.base) == (None, None, None), st
        assert st.rec == rec and st.adj == adj and st.due == 100, st
        unread_total.observe(A, {"name": "no counter"}, 300)
        assert unread_total._held[A] == decide.replace(st, seen=300), "nothing held to drop: only the mark moves"


async def case_answers_of_both_kinds_order_by_their_ask_time():
    import unread_total_decide as decide
    with _knobs(True, True), _live(_UP_LONG_AGO):
        unread_total._held[A] = decide.State()
        unread_total.observe(A, {"chatMessagesCount": 5}, 200)
        unread_total.observe(A, {"name": "no counter"}, 100)
        assert _slot() == {"n": 5, "at": 200, "v": 1, "grey": None, "amber": None, "amber_at": None}, _slot()
        unread_total.observe(A, {"chatMessagesCount": 9}, 150)
        assert _slot() == {"n": 5, "at": 200, "v": 1, "grey": None, "amber": None, "amber_at": None}, _slot()
        unread_total.observe(A, {"name": "no counter"}, 300)
        assert _slot() == {**_UNSEEDED, "v": 2} and unread_total._held[A].seen == 300, unread_total._held[A]
        unread_total.observe(A, {"chatMessagesCount": 9}, 250)
        assert _slot() == {**_UNSEEDED, "v": 2}, _slot()
        unread_total.observe(A, {"chatMessagesCount": 4}, 400)
        assert _slot() == {"n": 4, "at": 400, "v": 3, "grey": None, "amber": None, "amber_at": None}, _slot()


async def case_a_tab_without_the_creator_gets_no_unread_total():
    with _knobs(True, True):
        with _world(_Wire(3)) as pub:
            await server.users_me()
            await _settle()
            (e,) = pub
            assert ed.wants(f"model:{A}", frozenset({A}), frozenset(), e)
            assert ed.wants(f"model:{B}", frozenset({A, B}), frozenset(), e)
            assert not ed.wants(f"model:{B}", frozenset({B}), frozenset(), e), "never outside the clamp"


async def case_mark_read_on_a_held_unread_row_minus_one_no_list_read():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, True), _row(FAN2, False)])
            await server.of_mark_chat_read(FAN)
            await _settle()
            assert _ns(pub) == [2], pub
            assert [(c["fan_id"], c["unread"]) for c in _of(pub, "chat_read_changed")] == [(FAN, 0)], pub
            assert [c for c in wire.calls if c[0] == "GET"] == [], ("0 OF reads: the write only", wire.calls)
            pub.clear()
            await _hold_window([_row(FAN, False), _row(FAN2, False)])
            await server.of_mark_chat_read(FAN)
            await _settle()
            assert _of(pub, "creator_refreshed") == [] and _slot()["n"] == 2, (pub, _slot())
            relay_cache.invalidate("list_chats", A)


async def case_mark_unread_on_a_held_read_row_plus_one():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, False)])
            await server.of_mark_chat_unread(FAN)
            await _settle()
            assert _ns(pub) == [4], pub
            assert [c for c in wire.calls if c[0] == "GET"] == [], wire.calls
            pub.clear()
            await _hold_window([_row(FAN, True)])
            await server.of_mark_chat_unread(FAN)
            await _settle()
            assert _of(pub, "creator_refreshed") == [] and _slot()["n"] == 4, (pub, _slot())
            relay_cache.invalidate("list_chats", A)


async def case_knob_off_routes_hold_nothing():
    with _knobs(True, False):
        wire = _Wire(3)
        with _world(wire) as pub:
            await _hold_window([_row(FAN, True)])
            await server.of_mark_chat_read(FAN)
            await server.of_mark_chat_unread(FAN)
            await _settle()
            assert unread_total._held == {} and _of(pub, "creator_refreshed") == [], (unread_total._held, pub)
            assert [k for e in pub for k in e if k != "__account_id"] == ["chat_read_changed"] * 2, pub
            assert [c for c in wire.calls if c[0] == "GET"] == [], wire.calls
            relay_cache.invalidate("list_chats", A)


def _dm(fan: int, mid: int) -> dict:
    time.sleep(0.002)
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return {"api2_chat_message": {"id": mid, "text": "hey", "price": 0, "isTip": False, "fromUser": {"id": fan},
                                  "createdAt": now, "responseType": "message"},
            "__account_id": A}


@contextlib.contextmanager
def _quiet_hooks():
    import employees
    import webhook_dispatch

    async def _none(*_a, **_k):
        return None
    names = ("on_inbound_message", "on_inbound_image", "on_inbound_tip")
    orig = [getattr(webhook_dispatch, n) for n in names] + [employees.resolve_outbound_employee_id]
    for n in names:
        setattr(webhook_dispatch, n, _none)
    employees.resolve_outbound_employee_id = _none
    try:
        yield
    finally:
        for n, f in zip(names, orig):
            setattr(webhook_dispatch, n, f)
        employees.resolve_outbound_employee_id = orig[-1]


async def case_reply_into_unread_then_mark_read_minus_one_once():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub, _quiet_hooks():
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, True)])
            await server.send_message(request=None, chat_id=FAN, body=server.SendMessageBody(text="hi"))
            assert relay_cache.peek("list_chats", A, _window_key()) is None, "the send route dropped the window"
            await _settle()
            assert _ns(pub) == [2], ("the reply moved it", pub)
            await server.of_mark_chat_read(FAN)
            await _settle()
            assert _ns(pub) == [2] and _slot()["n"] == 2, ("-1 once", pub, _slot())
            assert [c for c in wire.calls if c[0] == "GET"] == [], wire.calls


async def case_two_dms_into_one_read_chat_plus_one_once():
    import event_transcoder as et
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub, _quiet_hooks():
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, False)])
            await et.transcode(_dm(FAN, FAN * 10 + 1))
            await et.transcode(_dm(FAN, FAN * 10 + 2))
            await _settle()
            assert _ns(pub) == [4] and _slot()["n"] == 4, ("+1 once", pub, _slot())
            relay_cache.invalidate("list_chats", A)
            await et.transcode(_dm(FAN2, FAN2 * 10 + 1))
            await et.transcode(_dm(FAN2, FAN2 * 10 + 2))
            await _settle()
            assert _ns(pub) == [4, 5] and _slot()["n"] == 5, ("+1 once, no row held", pub, _slot())
            assert wire.calls == [], wire.calls


async def case_mark_all_keeps_a_dm_after_its_pre_write_at():
    import event_transcoder as et
    with _knobs(True, True):
        wire = _Wire(3)
        loop = asyncio.get_running_loop()
        with _world(wire) as pub, _quiet_hooks():
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, False), _row(FAN2, True)])
            answer = wire._answer

            def _dm_while_writing(method, url):
                if urlsplit(url).path.endswith("/chats/mark-as-read"):
                    asyncio.run_coroutine_threadsafe(et.transcode(_dm(FAN, FAN * 10 + 5)), loop).result(10)
                return answer(method, url)
            wire._answer = _dm_while_writing
            await server.of_mark_all_chats_read()
            await _settle()
            assert _ns(pub)[-1] == 1 and _slot()["n"] == 1, ("the DM after the write's ask stays", pub, _slot())
            assert [c for c in wire.calls if c[0] == "GET"] == [], wire.calls
            relay_cache.invalidate("list_chats", A)


def _window_key():
    from accounts_admin_api import _ROSTER_WINDOW_KEY
    return _ROSTER_WINDOW_KEY


_OTHER_LISTS = ((25, 25, "recent", None, None, None), (25, 0, "recent", "unread", None, None))


async def _hold_other_lists() -> None:
    for key in _OTHER_LISTS:
        await relay_cache.get_or_fetch("list_chats", A, key, ttl_seconds=600, fetcher=lambda: {"list": [], "hasMore": False})


def _others_held() -> list:
    return [relay_cache.peek("list_chats", A, k) is not None for k in _OTHER_LISTS]


def _window_reads(wire: _Wire) -> int:
    return sum(1 for c in wire.calls if c == ("GET", CHATS))


def _flips(pub) -> list:
    return [(c["fan_id"], c["unread"]) for c in _of(pub, "chat_read_changed")]


@contextlib.contextmanager
def _drift_log():
    records: list = []
    h = logging.Handler()
    h.emit = records.append
    lg = logging.getLogger("of-relay.unread_total")
    old = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        yield lambda: [m for r in records if (m := r.getMessage()).startswith("unread_total_drift")]
    finally:
        lg.removeHandler(h)
        lg.setLevel(old)


@contextlib.contextmanager
def _cycle(wire: _Wire, *, ws_since=50.0, window_at=100.0):
    client = _client(A, wire)
    saved = (server._load_client, of_ws.connected_since, shared_refresher._clock)
    server._load_client = lambda *_a, **_k: client
    of_ws.connected_since = lambda a: ws_since if a == A else None
    server._chats_window_fetched_at[A] = window_at
    shared_refresher._window_asked.clear()
    shared_refresher._state = shared_refresher_decide.State(
        last={A: 1.0}, shown={A: {"cycle_s": 600.0, "live": "up", "values": shared_refresher._values_of(A)}})

    async def job(t: float):
        shared_refresher._clock = lambda: t
        t0 = _ms()
        ok = await shared_refresher._job(A)
        t1 = _ms()
        await _settle()
        return ok, t0, t1
    try:
        yield job
    finally:
        server._load_client, of_ws.connected_since, shared_refresher._clock = saved
        server._chats_window_fetched_at.pop(A, None)
        shared_refresher._window_asked.clear()
        relay_cache.invalidate("list_chats", A)


async def case_drift_down_one_window_read_flips_the_row_and_drops_the_other_lists():
    with _knobs(True, True):
        assert shared_refresher._window_reader is unread_total.window_read, "on: Phase 2's reader registered"
        wire = _Wire(3)
        with _world(wire) as pub, _cycle(wire) as job, _drift_log() as drifts:
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, True), _row(FAN2, True), _row(FAN * 3, False)])
            await _hold_other_lists()
            wire.me = (200, {"chatMessagesCount": 2})
            wire.chats = [_row(FAN, False), _row(FAN2, True), _row(FAN * 3, False)]
            ok, t0, t1 = await job(1000.0)
            assert ok and _window_reads(wire) == 1, ("one window read in the same job", ok, wire.calls)
            assert wire.calls == [("GET", ME), ("GET", CHATS)], ("1 /users/me + 1 window read", wire.calls)
            assert _flips(pub) == [(FAN, 0)], ("the flipped row only", pub)
            (flip,) = _of(pub, "chat_read_changed")
            assert t0 <= flip["at"] <= t1, ("stamped at the read's ask time", flip, t0, t1)
            assert _ns(pub) == [2, 2], ("n 2; the read's first Amber fold republishes it", pub)
            assert _others_held() == [False, False], "the other lists dropped"
            held = relay_cache.peek("list_chats", A, _window_key())
            assert held is not None and held["list"] == wire.chats, ("the new window kept", held)
            assert drifts() == [f"unread_total_drift account={A} dir=down expected=3 observed=2"], drifts()
            assert unread_total.window_due(A) is False, "served"


async def case_within_slack_no_read_higher_logs_only():
    import event_transcoder as et
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub, _quiet_hooks(), _cycle(wire) as job, _drift_log() as drifts:
            await _confirmed(wire, pub)
            relay_cache.invalidate("list_chats", A)
            await et.transcode(_dm(FAN, FAN * 10 + 7))
            await _settle()
            assert _slot()["n"] == 4, _slot()
            await et.transcode(_dm(FAN, FAN * 10 + 7))
            await _settle()
            assert _slot()["n"] == 4, ("a replayed DM does not move the total", _slot())
            await _hold_window([_row(FAN, True), _row(FAN2, True)])
            await _hold_other_lists()
            wire.calls.clear()
            pub.clear()
            wire.chats = [_row(FAN, False), _row(FAN2, False)]
            ok, _t0, _t1 = await job(1000.0)
            assert ok and _window_reads(wire) == 0 and _flips(pub) == [], (wire.calls, pub)
            assert drifts() == [] and _others_held() == [True, True], drifts()
            wire.me = (200, {"chatMessagesCount": 6})
            ok, _t0, _t1 = await job(2000.0)
            assert ok and _window_reads(wire) == 0 and _flips(pub) == [], (wire.calls, pub)
            assert drifts() == [f"unread_total_drift account={A} dir=up expected=3 observed=6"], drifts()
            assert _ns(pub) == [3, 6] and _others_held() == [True, True], pub


async def case_second_drift_in_the_same_cycle_no_read():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub, _cycle(wire) as job, _drift_log() as drifts:
            await _confirmed(wire, pub)
            await _hold_window([_row(FAN, True), _row(FAN2, True)])
            wire.me = (200, {"chatMessagesCount": 2})
            wire.chats = [_row(FAN, False), _row(FAN2, True)]
            await job(1000.0)
            assert _window_reads(wire) == 1 and _flips(pub) == [(FAN, 0)], (wire.calls, pub)
            wire.me = (200, {"chatMessagesCount": 1})
            wire.chats = [_row(FAN, False), _row(FAN2, False)]
            await job(1100.0)
            assert _window_reads(wire) == 1 and _flips(pub) == [(FAN, 0)], ("no second read this Cycle", wire.calls)
            assert len(drifts()) == 2 and unread_total.window_due(A) is True, drifts()
            await job(1700.0)
            assert _window_reads(wire) == 2 and _flips(pub) == [(FAN, 0), (FAN2, 0)], (wire.calls, pub)
            assert len(drifts()) == 2 and unread_total.window_due(A) is False, drifts()


async def case_no_old_window_drift_read_clears_read_rows_routine_read_none():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub, _cycle(wire) as job:
            await _confirmed(wire, pub)
            relay_cache.invalidate("list_chats", A)
            wire.me = (200, {"chatMessagesCount": 1})
            wire.chats = [_row(FAN, False), _row(FAN2, True), _row(FAN * 3, False)]
            ok, t0, t1 = await job(1000.0)
            assert ok and _window_reads(wire) == 1, wire.calls
            assert _flips(pub) == [(FAN, 0), (FAN * 3, 0)], ("{unread: 0} per read row", pub)
            assert all(t0 <= c["at"] <= t1 for c in _of(pub, "chat_read_changed")), pub
        pub.clear()
        with _world(wire) as pub, _cycle(wire, ws_since=None) as job:
            await _hold_other_lists()
            ok, _t0, _t1 = await job(2000.0)
            assert ok and _window_reads(wire) == 2, wire.calls
            assert _flips(pub) == [] and _others_held() == [True, True], ("none, nothing dropped", pub)


async def case_knob_off_no_reader_the_rewarm_as_today():
    with _knobs(True, False):
        assert shared_refresher._window_reader is None, "off: Phase 1's default reader"
        wire = _Wire(3)
        with _world(wire) as pub, _cycle(wire, ws_since=None) as job:
            await _hold_window([_row(FAN, True)])
            await _hold_other_lists()
            wire.chats = [_row(FAN, False)]
            ok, _t0, _t1 = await job(1000.0)
            assert ok and wire.calls == [("GET", ME), ("GET", CHATS)], wire.calls
            assert _flips(pub) == [] and _others_held() == [True, True], pub


def _login(path: str, username: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post(path, json={"username": username, "password": "pw"})
    assert r.status_code == 200, f"{username} login failed: {r.status_code} {r.text}"
    return c


def _rows() -> dict:
    owner = {a["id"]: a for a in _login("/auth/login", "boss").get("/admin/accounts").json()["accounts"]}
    r = _login("/chatter/login", "chat").get("/chatter/me/accounts")
    assert r.status_code == 200, (r.status_code, r.text[:200])
    chatter = {a["account_id"]: a for a in r.json()}
    assert set(owner) == set(chatter) == set(_CREATORS), (sorted(owner), sorted(chatter))
    return {"owner": owner, "chatter": chatter}


def case_both_accounts_answers_carry_the_total():
    with _knobs(True, True):
        wire = _Wire(6)
        t0 = _ms()
        _client(A, wire).me()
        for where, rows in _rows().items():
            got = rows[A]["freshness"]["values"]["unread_total"]
            assert got["n"] == 6 and t0 <= got["at"], (where, got)
            assert rows[B]["freshness"]["values"] == {"unread_total": _UNSEEDED}, (where, "no total yet", rows[B])


def case_knob_off_no_key_same_calls():
    for shared, unread in ((True, False), (False, True), (False, False)):
        with _knobs(shared, unread):
            assert not unread_total.ENABLED, (shared, unread)
            wire = _Wire(6)
            _client(A, wire).me()
            assert wire.calls == [("GET", ME)], ("the observer makes no OF call", wire.calls)
            assert unread_total.snapshot(A) is None and "unread_total" not in shared_refresher.snapshot(A)["values"]
            for where, rows in _rows().items():
                for aid, row in rows.items():
                    values = (row.get("freshness") or {}).get("values", {})
                    assert "unread_total" not in values, (shared, unread, where, aid, row)
                    assert ("freshness" in row) is shared, (shared, unread, where, row)


async def case_badge_excluded_stamp():
    import unread_total_decide
    from automations._common import set_of_restricted_skip
    reg, friends, of_flag, plain = 7001, 7002, 7003, 7004
    page = {"list": [
        _row(reg, True),
        {**_row(friends, True), "canSendMessage": False, "canNotSendReason": "only_friends"},
        {**_row(of_flag, True), "withUser": {"id": of_flag, "isRestricted": True}},
        _row(plain, True),
    ]}
    real = unread_total_decide.excluded_from_badges

    def stamps(out):
        return {r["withUser"]["id"]: {k for k in ("badgeExcluded", "isRestricted") if r["withUser"].get(k)}
                for r in out["list"]}

    await set_of_restricted_skip(A, reg, True)
    try:
        got = stamps(await server._annotate_chat_rows(A, page))
        assert got == {reg: {"badgeExcluded", "isRestricted"}, friends: {"badgeExcluded"},
                       of_flag: {"isRestricted"}, plain: set()}, got
        assert "badgeExcluded" not in page["list"][1]["withUser"], "the held window is never stamped"
        unread_total_decide.excluded_from_badges = lambda fan, row, ids: fan != reg and real(fan, row, ids)
        got = stamps(await server._annotate_chat_rows(A, page))
        assert got[reg] == {"isRestricted"} and got[friends] == {"badgeExcluded"}, got
    finally:
        unread_total_decide.excluded_from_badges = real
        await set_of_restricted_skip(A, reg, False)


class _NoOF(_Wire):
    def _answer(self, method, url):
        raise AssertionError(f"an OF call: {method} {url}")


def _frame(n, aid=A) -> dict:
    return {"__account_id": aid, "chat_messages": n, "count_priority_chat": 0, "count_call_request_chat": 0,
            "unread_tips": 0}


async def _feed(n, aid=A) -> tuple[int, int]:
    t0 = _ms()
    await events.handle_event(_frame(n, aid))
    t1 = _ms()
    await _settle()
    return t0, t1


class _User:
    account_ids = list(_CREATORS)


@contextlib.contextmanager
def _roster(wire: _Wire):
    import accounts_admin_api
    client = _client(A, wire)
    saved = (server._get_request_user, server._load_client)
    server._get_request_user = lambda: _User()
    server._load_client = lambda *_a, **_k: client
    for a in _CREATORS:
        relay_cache.invalidate("roster_count", a)
        accounts_admin_api._roster_last.pop(a, None)

    class _R:
        headers: dict = {}

    async def counts(**kw) -> dict:
        return (await accounts_admin_api.admin_accounts_roster_counts(_R(), **kw))["counts"]
    try:
        yield counts
    finally:
        server._get_request_user, server._load_client = saved
        for a in _CREATORS:
            relay_cache.invalidate("roster_count", a)
            relay_cache.invalidate("list_chats", a)
            server._chats_window_fetched_at.pop(a, None)
            accounts_admin_api._roster_last.pop(a, None)


async def _fold(counts, rows: list) -> dict:
    await _hold_window(rows, fetched_at=_ms())
    return (await counts())[A]


@contextlib.asynccontextmanager
async def _registry(*fans):
    from automations._common import set_of_restricted_skip
    for f in fans:
        await set_of_restricted_skip(A, f, True)
    try:
        yield
    finally:
        for f in fans:
            await set_of_restricted_skip(A, f, False)


def _send_row(fan: int, unread=True, **kw) -> dict:
    return {**_row(fan, unread), "lastMessage": {"id": fan * 10, "fromUser": {"id": fan}}, **kw}


async def case_counter_frame_sets_total():
    with _knobs(True, True):
        wire = _NoOF()
        with _world(wire) as pub:
            unread_total.set_restricted_unread(A, Restricted(0, False, 0), _ms())
            await _settle()
            assert pub == [] and _slot() == _UNSEEDED, ("R alone: no confirmation, nothing published", pub)
            t0, t1 = await _feed(3)
            (got,) = _totals(pub)
            assert got == {"n": 3, "at": got["at"], "v": 1, "grey": None, "amber": None, "amber_at": None} and t0 <= got["at"] <= t1, (got, t0, t1)
            assert _slot() == got, _slot()
            pub.clear()
            time.sleep(0.002)
            t0, _t1 = await _feed(3)
            assert pub == [], ("a same-value frame publishes nothing", pub)
            assert _slot()["n"] == 3 and _slot()["v"] == 1 and _slot()["at"] >= t0 > got["at"], _slot()


async def case_frame_before_seed_then_me():
    with _knobs(True, True):
        with _world(_NoOF()):
            unread_total.set_restricted_unread(A, Restricted(0, False, 0), 0)
            t1 = _ms()
            time.sleep(0.002)
            await _feed(4)
            unread_total.observe(A, {"chatMessagesCount": 5}, t1)
            assert _slot()["n"] == 4, _slot()


async def case_mark_read_frame_before_after_write():
    with _knobs(True, True):
        wire = _Wire(3)
        loop = asyncio.get_running_loop()
        with _world(wire) as pub:
            await _feed(3)
            await _hold_window([_row(FAN, True), _row(FAN2, True), _row(FAN2 + 1, True)])
            pub.clear()
            answer = wire._answer

            def _frame_while_writing(method, url):
                if method == "POST" and urlsplit(url).path.endswith(f"/chats/{FAN}/mark-as-read"):
                    time.sleep(0.002)
                    asyncio.run_coroutine_threadsafe(events.handle_event(_frame(2)), loop).result(10)
                return answer(method, url)
            wire._answer = _frame_while_writing
            await server.of_mark_chat_read(FAN)
            await _settle()
            assert _slot()["n"] == 2 and _ns(pub) == [2], ("counted once, by the frame", pub, _slot())
            assert [(c["fan_id"], c["unread"]) for c in _of(pub, "chat_read_changed")] == [(FAN, 0)], pub
            relay_cache.invalidate("list_chats", A)


async def case_send_frame_before_response():
    with _knobs(True, True):
        wire = _Wire(3)
        loop = asyncio.get_running_loop()
        with _world(wire) as pub, _quiet_hooks():
            await _feed(3)
            await _hold_window([_row(FAN, True), _row(FAN2, True)])
            answer = wire._answer
            pub.clear()

            def send(method, url):
                if method == "POST" and urlsplit(url).path.endswith(f"/chats/{FAN}/messages"):
                    time.sleep(0.002)
                    asyncio.run_coroutine_threadsafe(events.handle_event(_frame(2)), loop).result(10)
                return answer(method, url)

            wire._answer = send
            await server.send_message(request=None, chat_id=FAN, body=server.SendMessageBody(text="hi"))
            await _settle()
            assert _slot()["n"] == 2 and _ns(pub) == [2], (pub, _slot())


async def case_dm_then_counter():
    import event_transcoder as et
    with _knobs(True, True):
        wire = _NoOF()
        with _world(wire) as pub, _quiet_hooks():
            await _feed(3)
            await _hold_window([_row(FAN, False)])
            pub.clear()
            await et.transcode(_dm(FAN, FAN * 10 + 1))
            await _settle()
            time.sleep(0.002)
            await _feed(4)
            assert _ns(pub) == [4] and _slot()["n"] == 4, ("+1 once", pub, _slot())
            relay_cache.invalidate("list_chats", A)


async def case_counter_never_asks_window():
    with _knobs(True, True):
        with _world(_NoOF()) as pub, _drift_log() as drifts:
            unread_total.set_restricted_unread(A, Restricted(0, False, 0), 0)
            unread_total.observe(A, {"chatMessagesCount": 5}, _ms() - 10)
            await _settle()
            await _feed(2)
            assert _slot()["n"] == 2 and unread_total.window_due(A) is False, _slot()
            assert drifts() == [], drifts()
            assert _ns(pub) == [5, 2], pub


async def case_malformed_frames():
    with _knobs(True, True):
        with _world(_NoOF()) as pub:
            unread_total.set_restricted_unread(A, Restricted(0, False, 0), 0)
            for bad in (True, -1, "3", {"count": 3}, None, 2.0):
                await events.handle_event({"__account_id": A, "chat_messages": bad})
            await events.handle_event({"__account_id": A, "unread_tips": 4})
            await _settle()
            assert A not in unread_total._held and _slot() == _UNSEEDED and _of(pub, "creator_refreshed") == [], pub


async def case_restricted_subtracted():
    reg = 7101
    with _knobs(True, True):
        wire = _NoOF()
        with _world(wire), _roster(wire) as counts:
            async with _registry(reg):
                await _fold(counts, [_send_row(reg), _send_row(7102), _send_row(7103, False)])
                await _feed(3)
                assert _slot()["n"] == 2, ("an unread unmuted registry row is Restricted unread", _slot())
                await _fold(counts, [_send_row(reg, isMutedNotifications=True), _send_row(7102)])
                assert _slot()["n"] == 3, ("a muted one OF never counted: not subtracted", _slot())


async def case_only_friends_worked_example():
    sendable = [_send_row(7200 + i, canSendMessage=True) for i in range(7)]
    friends = [_send_row(7300 + i, canSendMessage=False, canNotSendReason="only_friends") for i in range(4)]
    gone = [_send_row(7400 + i, canSendMessage=False, canNotSendReason="chat_unavailable") for i in range(2)]
    with _knobs(True, True):
        wire = _NoOF()
        with _world(wire), _roster(wire) as counts:
            await _fold(counts, sendable + friends + gone)
            await _feed(11)
            assert _slot()["n"] == 7, _slot()
            assert unread_total._r[A][0].n == 4, unread_total._r[A]
            assert (await counts())[A]["unread"] == 7, "roster-counts answers the Red circle"


async def case_restricted_newest_wins():
    with _knobs(True, True):
        with _world(_NoOF()):
            unread_total.set_restricted_unread(A, Restricted(2, False, 0), 2000)
            unread_total.set_restricted_unread(A, Restricted(5, False, 0), 1000)
            await _feed(10)
            assert _slot()["n"] == 8, ("an older R changes nothing", _slot())
            unread_total.set_restricted_unread(A, Restricted(5, False, 0), 3000)
            assert _slot()["n"] == 5, _slot()


async def case_r_unknown_until_a_fold():
    reg = 7501
    with _knobs(True, True, r_known=False):
        wire = _NoOF()
        with _world(wire) as pub, _roster(wire) as counts:
            async with _registry(reg):
                await _feed(5)
                assert _slot()["n"] is None and _slot()["v"] == 1, ("R unknown: never OF's raw 5", _slot())
                assert _ns(pub) == [None], pub
                await _fold(counts, [_send_row(reg), _send_row(7502)])
                await _settle()
                assert _slot()["n"] == 4 and _slot()["v"] == 3, ("R and the first Amber fold each move v", _slot())
                assert _ns(pub)[0] is None and _ns(pub)[-1] == 4 and 5 not in _ns(pub), pub


async def _tick() -> None:
    import account_health
    import app_open_warm
    import transaction_ingest
    import view_lease

    async def _readable():
        return [A]

    async def _no_dead():
        return {}
    patch = [(events, "open_tab_accounts", lambda: frozenset({A})), (transaction_ingest, "live_account_ids", _readable),
             (view_lease, "leased_ids", lambda *_a: set()), (account_health, "dead_session_map", _no_dead),
             (app_open_warm, "pending", lambda _a: False), (app_open_warm, "refresh", lambda *_a, **_k: None)]
    saved = [(m, k, getattr(m, k)) for m, k, _ in patch]
    for m, k, v in patch:
        setattr(m, k, v)
    try:
        await shared_refresher.tick()
    finally:
        for m, k, v in saved:
            setattr(m, k, v)
    await _settle()


async def case_grey_reasons():
    from accounts_admin_api import _red

    with _knobs(True, True, r_known=False):
        wire = _NoOF()
        with _world(wire) as pub, _roster(wire) as counts:
            assert _slot() == _UNSEEDED, _slot()
            await _feed(5)
            assert _slot()["grey"] == "r_unknown" and _slot()["n"] is None, _slot()
            await _fold(counts, [_send_row(7552)])
            await _settle()
            await _tick()
            folded = _slot()
            assert folded["grey"] is None and folded["n"] == 5, folded
            assert _slot() == folded and unread_total.snapshot(A) == folded, "a read alone moves nothing"
            pub.clear()
            with _live(None):
                assert _red(A, {"unread": 0, "as_of": 0})["unread"] == 5
                shared_refresher._values_noted(A)
                assert unread_total.snapshot(A) == folded and not pub
            await _feed(5)
            assert _slot()["grey"] is None and _slot()["v"] == folded["v"] and not pub
            with _live(None):
                assert unread_total.snapshot(A)["grey"] is None
                assert unread_total.badge_versions(frozenset({A})) == {A: folded["v"]}
                await _tick()
                (down,) = _totals(pub)
                assert down["grey"] == "socket_down" and down["n"] == 5 and down["v"] == folded["v"] + 1, down
                assert pub[-1]["creator_refreshed"]["live"] == "down", pub
            pub.clear()
            time.sleep(0.002)
            with _live(time.monotonic()):
                await _tick()
                assert _totals(pub) == [down] and pub[-1]["creator_refreshed"]["live"] == "up", pub
                pub.clear()
                time.sleep(0.002)
                await _feed(5)
                (back,) = _totals(pub)
                assert back["grey"] is None and back["n"] == 5 and back["v"] == down["v"] + 1, back


async def case_non_of_creator_has_no_total():
    real = account_registry.get_platform
    account_registry.get_platform = lambda aid: "fansly" if aid == B else "onlyfans"
    try:
        with _knobs(True, True):
            rows = await asyncio.to_thread(_rows)
            for where, by in rows.items():
                assert by[B]["freshness"]["values"] == {"unread_total": None}, (where, by[B])
                assert by[A]["freshness"]["values"]["unread_total"]["grey"] == "unseeded", (where, by[A])
    finally:
        account_registry.get_platform = real


async def case_roster_counts_from_red():
    cap = 25
    rows = [_send_row(7600 + i) for i in range(cap)] + [_send_row(7700, False)]
    with _knobs(True, True):
        wire = _NoOF()
        with _world(wire), _roster(wire) as counts:
            folded = await _fold(counts, rows)
            assert folded["unread"] == cap and folded.get("unread_capped") is True, ("no slot yet: today's fold", folded)
            await _feed(40)
            got = (await counts())[A]
            slot = _slot()
            assert got == {"unread": 40, "owe_reply": folded["owe_reply"], "as_of": slot["at"]}, (got, slot)
            with _live(None):
                await _tick()
                assert (await counts())[A] == folded


async def case_untracked_creator_frame_held():
    with _knobs(True, True):
        with _world(_NoOF()) as pub:
            unread_total.set_restricted_unread(B, Restricted(0, False, 0), 0)
            await _feed(6, B)
            assert _of(pub, "creator_refreshed") == [], ("no Open tab on B: nothing published", pub)
            rows = await asyncio.to_thread(_rows)
            for where, by in rows.items():
                got = by[B]["freshness"]["values"]["unread_total"]
                assert got["n"] == 6 and got["v"] == 1, (where, got)


def _keys(o) -> set:
    if isinstance(o, dict):
        return set(o) | {k for v in o.values() for k in _keys(v)}
    if isinstance(o, list):
        return {k for v in o for k in _keys(v)}
    return set()


_RAW = {"raw", "chat_messages", "chatMessagesCount", "of_total"}


async def case_raw_never_published():
    with _knobs(True, True):
        wire = _NoOF()
        with _world(wire) as pub, _roster(wire) as counts:
            await _fold(counts, [_send_row(7950 + i, canSendMessage=False, canNotSendReason="only_friends")
                                 for i in range(2)] + [_send_row(7960)])
            await _feed(5)
            rows = await asyncio.to_thread(_rows)
            sub = events._register(f"model:{A}", frozenset({A}), frozenset(), True, None)
            try:
                ping = _ping_data(sub)
            finally:
                await events.unsubscribe("all", sub.q)
            assert ping["badge"] == {A: pub[-1]["creator_refreshed"]["values"]["unread_total"]["v"]}, ping
            route = await counts()
            seen = [r[A] for r in rows.values()] + [e["creator_refreshed"] for e in pub] + [ping, route]
            assert pub, "published"
            for o in seen:
                assert not (_keys(o) & _RAW), o
            for o in [r[A] for r in rows.values()] + [e["creator_refreshed"] for e in pub]:
                ut = o["freshness"]["values"]["unread_total"] if "freshness" in o else o["values"]["unread_total"]
                assert ut["n"] in (None, 3) and {"n", "at", "v", "grey"} <= set(ut), ut
            assert _ns(pub)[-1] == 3, pub
            assert route[A]["unread"] == 3, route


def _ping_data(sub) -> dict:
    return json.loads(events._ping(sub, shared_refresher).decode().split("data: ", 1)[1])


async def case_ping_badge_only_open_tabs_in_clamp():
    with _knobs(True, True):
        with _world(_NoOF()):
            await _feed(3)
            await _feed(6, B)
            await _feed(7, B)
            subs = {k: events._register("all", acc, frozenset(), tab, None) for k, acc, tab in [
                ("tab_a", frozenset({A}), True), ("all_tabs", None, True), ("notifier", frozenset({A, B}), False)]}
            try:
                got = {k: _ping_data(s) for k, s in subs.items()}
                for k, p in got.items():
                    assert p.get("badge") == {A: 1}, (k, p, "B has a version but no Open tab")
                    assert set(p["fresh"]) <= {A}, (k, p)
                assert unread_total.badge_versions(frozenset({A, B})) == {A: 1, B: 2}
                subs["tab_b"] = events._register("all", frozenset({B}), frozenset(), True, None)
                got = {k: _ping_data(s).get("badge") for k, s in subs.items()}
                assert got == {"tab_a": {A: 1}, "all_tabs": {A: 1, B: 2}, "notifier": {A: 1, B: 2},
                               "tab_b": {B: 2}}, ("B open now: each clamp keeps its own", got)
            finally:
                for s in subs.values():
                    await events.unsubscribe("all", s.q)
    with _knobs(True, False):
        sub = events._register("all", frozenset({A}), frozenset(), True, None)
        try:
            assert "badge" not in _ping_data(sub) and "fresh" in _ping_data(sub), _ping_data(sub)
        finally:
            await events.unsubscribe("all", sub.q)
    writes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if writes:
        await asyncio.wait(writes, timeout=5)


class _Req:
    headers: dict = {}

    async def is_disconnected(self) -> bool:
        return False


async def _opening() -> dict:
    import events_wire as ew
    gen = events.sse_stream(_Req(), "all", accounts=frozenset({A}), tab=True)
    try:
        assert await gen.__anext__() == ew.CONNECTED
        return json.loads((await gen.__anext__()).decode().split("data: ", 1)[1])
    finally:
        await gen.aclose()


async def case_restart_opening_ping_carries_nothing_fresh():
    with _knobs(True, True, r_known=False):
        wire = _NoOF()
        with _world(wire), _roster(wire) as counts:
            p = await _opening()
            assert p["fresh"] == {} and (p.get("badge") or {}).get(A, 0) == 0, p
            assert _slot() == _UNSEEDED, _slot()
            await _feed(5)
            assert _slot()["grey"] == "r_unknown" and _slot()["n"] is None, _slot()
            assert (await _opening()).get("badge") == {A: 1}
            await _fold(counts, [_send_row(7561)])
            await _settle()
            await _tick()
            assert _slot()["grey"] is None and _slot()["n"] == 5, _slot()


async def case_restart_one_window_read_folds_r():
    reg = 7565
    with _knobs(True, True, r_known=False):
        wire = _Wire(5)
        wire.chats = [_send_row(reg), _send_row(7566), _send_row(7567, False)]
        with _world(wire) as pub, _roster(wire), _cycle(wire, window_at=None) as job:
            async with _registry(reg):
                await _opening()
                await _feed(5)
                assert _slot()["grey"] == "r_unknown" and _slot()["n"] is None, _slot()
                ok, _t0, _t1 = await job(1000.0)
                assert ok and wire.calls == [("GET", ME), ("GET", CHATS)], ("one window read", wire.calls)
                assert _slot()["grey"] is None and _slot()["n"] == 4, _slot()
                assert set(_ns(pub)) <= {None, 4} and _ns(pub)[-1] == 4, ("never OF's raw 5", _ns(pub))
                assert (await _opening())["badge"] == {A: _slot()["v"]}, _slot()
                ok, _t0, _t1 = await job(2000.0)
                assert ok and _window_reads(wire) == 1, ("once per boot", wire.calls)


async def case_cold_route_calls():
    import view_lease
    holder = ("user", "sse-test", "tab")
    with _knobs(True, True):
        wire = _Wire(3)
        wire.chats = [_send_row(7800), _send_row(7801, False)]
        with _world(wire), _roster(wire) as counts:
            view_lease.renew(holder, [A], None)
            try:
                unread_total.set_restricted_unread(A, Restricted(0, False, 0), 0)
                await _feed(4)
                got = (await counts())[A]
                await _feed(3)
                assert wire.calls == [("GET", CHATS)], wire.calls
                assert got["unread"] == 4 and _slot()["n"] == 3, (got, _slot())
            finally:
                view_lease.renew(holder, [], None)


async def case_knob_off_counter_ignored():
    with _knobs(True, False):
        wire = _NoOF()
        with _world(wire) as pub, _roster(wire) as counts:
            unread_total.set_restricted_unread(A, Restricted(0, False, 0), 0)
            await _feed(3)
            got = await _fold(counts, [_send_row(7900), _send_row(7901, False, isMutedNotifications=False)])
            assert unread_total._held == {} and unread_total._r == {}, (unread_total._held, unread_total._r)
            assert "unread_total" not in shared_refresher.snapshot(A)["values"] and pub == [], pub
            assert got == {"unread": 1, "owe_reply": 1, "as_of": got["as_of"]}, got


_harness.run()
