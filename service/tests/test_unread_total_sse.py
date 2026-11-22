#!/usr/bin/env python3
"""The Unread total from every `/users/me` OF returns (phase-02 seam 2, ticket 13). With `UNREAD_TOTAL=1` and
`SHARED_REFRESHER=1` (modules reloaded) one observer in the OF client takes `chatMessagesCount` from each 2xx
`GET /api2/v2/users/me` OF actually answered, whoever asked (the route, S4S's `_of_me`, a direct `client.me()`: health
probes, account config, the Live connection's reconnect auth), and the Creator's `freshness.values.unread_total`
becomes `{n, at}` (`at`: the read's ask time, epoch ms); a changed `n` is one `creator_refreshed`, an unchanged one
none. A cache hit is never a confirmation; a failed read (a Dead session's 401) keeps the last total. Both accounts
answers carry the slot (null before the first confirmation). Knob off (either): no key, nothing held, the same OF calls.

Between Cycles (ticket 14), at 0 OF calls: our mark read on a held unread page-0 row moves the total -1, our mark unread
on a held read row +1, each one `creator_refreshed`; Knob off, the routes hold nothing.
Ticket 22: a reply (the send route) into an unread chat then a mark read of it -> -1 once; two DMs (the transcoder)
into one read chat -> +1 once; mark all read with a DM landing after its pre-write `at` -> 1, not 0.
Ticket 21, through the Shared refresher's real Cycle job (`_job`: `/users/me`, then its window step): a lower OF number
beyond slack -> one page-0 window read in the same job, `chat_read_changed` stamped at its ask time for the flipped row,
the Creator's other chat lists dropped, a `dir=down` drift log; within slack -> no read; higher -> a `dir=up` log only;
a second drift in the same Cycle -> no read (the next Cycle's); no old window held -> `{unread: 0}` per read row on a
drift read, none (and nothing dropped) on a routine read. Knob off: no reader registered, the roster rewarm as today.

OF faked below the client (a real `OFClient` on a fake wire: no network); `events.publish` captured.
Run: ./venv/bin/python service/tests/test_unread_total_sse.py
"""
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
import events  # noqa: E402
import events_decide as ed  # noqa: E402
import of_ws  # noqa: E402
import relay_cache  # noqa: E402
import s4s_api  # noqa: E402
import shared_refresher  # noqa: E402
import shared_refresher_decide  # noqa: E402
import unread_total  # noqa: E402
from of_client import OFClient  # noqa: E402

A, B = "8131", "8132"           # the Relay's account id is the OF user id the client carries
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
    """OF: `/users/me` answers `me` (status, body); any other path a body carrying a counter too (never observed).
    `calls`: every request sent, (method, path)."""
    def __init__(self, n=3):
        self.me = (200, {"chatMessagesCount": n, "wsUrl": "wss://ws", "wsAuthToken": "t"})
        self.chats: list = []           # what `GET /chats` lists (the page-0 window)
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


@contextlib.contextmanager
def _knobs(shared: bool, unread: bool):
    """The two Knobs as env, both modules reloaded (a reload is a restart: nothing held)."""
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
    try:
        yield
    finally:
        for k, v in saved.items():
            _set(k, v)
        importlib.reload(shared_refresher)
        importlib.reload(unread_total)


@contextlib.contextmanager
def _world(wire: _Wire):
    """A's client on `wire` for the route (`_get_client`) and S4S (`ax._make_client`); A tracked (a tab open on
    it) on the running Relay loop; `creator_refreshed` captured. Yields the published list."""
    published: list = []
    client = _client(A, wire)
    orig = (server._get_client, server._resolve_account_id, s4s_api.ax._make_client, events.publish)
    server._get_client = lambda *_a: client
    server._resolve_account_id = lambda *_a: A
    s4s_api.ax._make_client = lambda _aid: client
    events.publish = published.append
    relay_cache.invalidate("users_me", A)
    shared_refresher._relay_loop = asyncio.get_running_loop()      # what `start()` captures
    shared_refresher._state = shared_refresher_decide.State(
        shown={A: {"cycle_s": 600.0, "live": "up", "values": shared_refresher._values_of(A)}})
    try:
        yield published
    finally:
        server._get_client, server._resolve_account_id, s4s_api.ax._make_client, events.publish = orig
        relay_cache.invalidate("users_me", A)


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


async def _hold_window(rows: list) -> None:
    """A's page-0 chats window held (what the Fan List and the roster badge read), as a list read left it."""
    from accounts_admin_api import _ROSTER_WINDOW_KEY
    relay_cache.invalidate("list_chats", A)
    await relay_cache.get_or_fetch("list_chats", A, _ROSTER_WINDOW_KEY, ttl_seconds=600,
                                   fetcher=lambda: {"list": rows, "hasMore": False})


def _row(fan: int, unread: bool) -> dict:
    return {"withUser": {"id": fan}, "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0,
            "lastMessage": {"id": fan * 10}}


def _of(published, kind: str) -> list:
    return [e[kind] for e in published if kind in e]


def _ns(published) -> list:
    """The `n` of each `creator_refreshed` published."""
    return [e["values"]["unread_total"]["n"] for e in _of(published, "creator_refreshed")]


async def _confirmed(wire: _Wire, pub: list) -> None:
    """The total confirmed once through the route (one `/users/me`), then the capture and the call log cleared."""
    await server.users_me()
    await _settle()
    assert _slot()["n"] == wire.me[1]["chatMessagesCount"], _slot()
    pub.clear()
    wire.calls.clear()


def _slot(aid=A):
    return shared_refresher.snapshot(aid)["values"].get("unread_total", "absent")


def _ms() -> int:
    return int(time.time() * 1000)


async def case_route_fetch_observed_cache_hit_not():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            assert _slot() is None, ("on, no confirmation yet: the key, null", _slot())
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
            await server.users_me()                     # the 60 s entry: a cache hit
            await server.users_me(max_age=1800)         # an identity reader: served, never fetched
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
            await server.users_me()                     # S4S filled the route's entry: a hit
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
            relay_cache.invalidate("users_me", A)       # the entry gone: the next read is a fetch
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
            await asyncio.to_thread(client.me)          # health probes, account config: `client.me()` direct
            await _settle()
            assert [t["n"] for t in _totals(pub)] == [4], pub
            pub.clear()
            importlib.reload(unread_total)              # a Relay restart: nothing held
            assert _slot() is None, _slot()
            wire.me = (200, {"chatMessagesCount": 2, "wsUrl": "wss://ws", "wsAuthToken": "t"})
            ws = of_ws.OFWebSocket(lambda: client, account_id=A)
            await asyncio.to_thread(ws._refresh_auth, client)   # the Live connection's (re)connect read
            await _settle()
            assert [t["n"] for t in _totals(pub)] == [2], ("the reconnect read refills the total", pub)


async def case_only_a_2xx_get_of_users_me_with_a_count():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub:
            client = _client(A, wire)
            await asyncio.to_thread(client.get_json, "/api2/v2/users/me/settings")     # another path
            await asyncio.to_thread(client.request_json, "PATCH", ME, json_body={"x": 1})   # a write
            wire.me = (200, {"name": "no counter"})                                    # Fansly-like body
            await asyncio.to_thread(client.me)
            await _settle()
            assert len(wire.calls) == 3 and pub == [] and _slot() is None, (wire.calls, pub, _slot())


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
    """It moved Last refresh but confirmed nothing: a held total may not keep looking fresh (W30-mu #19)."""
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
            assert len(wire.calls) == 2 and _slot() is None, (wire.calls, _slot())
            assert _totals(pub) == [None], ("the drop is published once, as null", pub)
            relay_cache.invalidate("users_me", A)
            wire.me = (200, {"chatMessagesCount": 2})
            await server.users_me()
            await _settle()
            assert _slot()["n"] == 2 and [t and t["n"] for t in _totals(pub)] == [None, 2], (_slot(), pub)


async def case_an_answer_without_a_counter_keeps_the_records_adjustments_and_due_read():
    """Only the total goes: per-fan records, adjustments still landing and a due window read survive (W30-mu #35)."""
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
    """W30-mu #45: a delayed counter-less answer once erased a newer confirmed total and its watermark, and an
    older valid answer then replaced it. Both kinds now order by ask time against one watermark (`seen`), kept
    while the total is unknown: an answer asked before the newest one taken changes nothing."""
    import unread_total_decide as decide
    with _knobs(True, True):
        unread_total._held[A] = decide.State()
        unread_total.observe(A, {"chatMessagesCount": 5}, 200)
        unread_total.observe(A, {"name": "no counter"}, 100)        # asked before the confirmation: stale
        assert _slot() == {"n": 5, "at": 200}, _slot()
        unread_total.observe(A, {"chatMessagesCount": 9}, 150)      # an older valid answer landing late
        assert _slot() == {"n": 5, "at": 200}, _slot()
        unread_total.observe(A, {"name": "no counter"}, 300)        # a newer one drops the total, keeps the mark
        assert _slot() is None and unread_total._held[A].seen == 300, unread_total._held[A]
        unread_total.observe(A, {"chatMessagesCount": 9}, 250)      # asked before it: still unknown
        assert _slot() is None, _slot()
        unread_total.observe(A, {"chatMessagesCount": 4}, 400)
        assert _slot() == {"n": 4, "at": 400}, _slot()


async def case_a_tab_without_the_creator_gets_no_unread_total():
    with _knobs(True, True):
        with _world(_Wire(3)) as pub:
            await server.users_me()
            await _settle()
            (e,) = pub
            assert ed.wants(f"model:{A}", frozenset({A}), frozenset(), e)
            assert ed.wants(f"model:{B}", frozenset({A, B}), frozenset(), e)    # any-scope: its All Models lists
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
            await server.of_mark_chat_read(FAN)             # already read: 0
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
            await server.of_mark_chat_unread(FAN)           # already unread: 0
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
    """A DM sent now: its `createdAt` (the Unread total's stamp for it) is after the held confirmation and any write
    already asked (2 ms on: never the same ms as them)."""
    time.sleep(0.002)
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return {"api2_chat_message": {"id": mid, "text": "hey", "price": 0, "isTip": False, "fromUser": {"id": fan},
                                  "createdAt": now, "responseType": "message"},
            "__account_id": A}


@contextlib.contextmanager
def _quiet_hooks():
    """The transcoder's automation hooks and the send route's employee lookup, no-ops (not under test)."""
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
            await server.of_mark_chat_read(FAN)             # an automation's mark read after its reply
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
            relay_cache.invalidate("list_chats", A)          # no window held: unknown prior, then our record
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

            def _dm_while_writing(method, url):      # FAN writes while OF takes the mark all
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
    """A's deeper page and its `filter=unread` list held, as a tab's reads left them."""
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
    """The `unread_total_drift` lines logged."""
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
    """The Shared refresher's real Cycle job for A on `wire` (`_job`: `/users/me` through the OF client, then the
    window step asking `window_due`): A's client for the refresher's reads, the Live connection up since `ws_since`
    (None: down) and the window last read at `window_at` (monotonic: WS-kept unless the socket is down or reconnected
    since), Cycle 600 s, a Last refresh before. Yields `job(t)`: one job asked at monotonic `t` -> (ok, ask epoch ms
    lower bound, upper bound)."""
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
            wire.me = (200, {"chatMessagesCount": 2})          # FAN read on OF web
            wire.chats = [_row(FAN, False), _row(FAN2, True), _row(FAN * 3, False)]
            ok, t0, t1 = await job(1000.0)
            assert ok and _window_reads(wire) == 1, ("one window read in the same job", ok, wire.calls)
            assert wire.calls == [("GET", ME), ("GET", CHATS)], ("1 /users/me + 1 window read", wire.calls)
            assert _flips(pub) == [(FAN, 0)], ("the flipped row only", pub)
            (flip,) = _of(pub, "chat_read_changed")
            assert t0 <= flip["at"] <= t1, ("stamped at the read's ask time", flip, t0, t1)
            assert _ns(pub) == [2], pub
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
            await et.transcode(_dm(FAN, FAN * 10 + 7))          # no row held: unknown prior, +1 slack 1
            await _settle()
            assert _slot()["n"] == 4, _slot()
            await et.transcode(_dm(FAN, FAN * 10 + 7))          # the same frame again (WS replay): counted once
            await _settle()
            assert _slot()["n"] == 4, ("a replayed DM does not move the total", _slot())
            await _hold_window([_row(FAN, True), _row(FAN2, True)])
            await _hold_other_lists()
            wire.calls.clear()
            pub.clear()
            wire.chats = [_row(FAN, False), _row(FAN2, False)]
            ok, _t0, _t1 = await job(1000.0)                     # OF 3: within the slack
            assert ok and _window_reads(wire) == 0 and _flips(pub) == [], (wire.calls, pub)
            assert drifts() == [] and _others_held() == [True, True], drifts()
            wire.me = (200, {"chatMessagesCount": 6})           # higher
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
            wire.me = (200, {"chatMessagesCount": 1})           # FAN2 read on OF web, same Cycle
            wire.chats = [_row(FAN, False), _row(FAN2, False)]
            await job(1100.0)
            assert _window_reads(wire) == 1 and _flips(pub) == [(FAN, 0)], ("no second read this Cycle", wire.calls)
            assert len(drifts()) == 2 and unread_total.window_due(A) is True, drifts()
            await job(1700.0)                                   # the next Cycle: the drift still due
            assert _window_reads(wire) == 2 and _flips(pub) == [(FAN, 0), (FAN2, 0)], (wire.calls, pub)
            assert len(drifts()) == 2 and unread_total.window_due(A) is False, drifts()


async def case_no_old_window_drift_read_clears_read_rows_routine_read_none():
    with _knobs(True, True):
        wire = _Wire(3)
        with _world(wire) as pub, _cycle(wire) as job:
            await _confirmed(wire, pub)
            relay_cache.invalidate("list_chats", A)             # the window dropped (a bust, expiry)
            wire.me = (200, {"chatMessagesCount": 1})
            wire.chats = [_row(FAN, False), _row(FAN2, True), _row(FAN * 3, False)]
            ok, t0, t1 = await job(1000.0)
            assert ok and _window_reads(wire) == 1, wire.calls
            assert _flips(pub) == [(FAN, 0), (FAN * 3, 0)], ("{unread: 0} per read row", pub)
            assert all(t0 <= c["at"] <= t1 for c in _of(pub, "chat_read_changed")), pub
        pub.clear()
        with _world(wire) as pub, _cycle(wire, ws_since=None) as job:   # socket down: Phase 1's routine read
            await _hold_other_lists()
            ok, _t0, _t1 = await job(2000.0)                     # no drift, no window held
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
        _client(A, wire).me()                           # no Relay loop: held, published by nothing
        for where, rows in _rows().items():
            got = rows[A]["freshness"]["values"]["unread_total"]
            assert got["n"] == 6 and t0 <= got["at"], (where, got)
            assert rows[B]["freshness"]["values"] == {"unread_total": None}, (where, "no total yet: null", rows[B])


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


_harness.run()
