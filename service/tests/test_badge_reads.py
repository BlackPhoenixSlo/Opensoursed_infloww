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
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import account_health  # noqa: E402
import accounts as account_registry  # noqa: E402

_harness.make_client()
import server  # noqa: E402
import app_open_warm  # noqa: E402
import badge_reads  # noqa: E402
import events  # noqa: E402
import events_persist  # noqa: E402
import of_call_counter  # noqa: E402
import of_pacing  # noqa: E402
import of_ws  # noqa: E402
import proxies  # noqa: E402
import proxy_health  # noqa: E402
import relay_cache  # noqa: E402
import relay_hooks  # noqa: E402
import shared_refresher  # noqa: E402
import unread_total  # noqa: E402
from unread_total_decide import Restricted  # noqa: E402
from accounts_admin_api import _ROSTER_WINDOW_KEY  # noqa: E402
from of_client import OFAPIError, OFClient  # noqa: E402

A, B = "8231", "8232"
_CREATORS = (A, B)
CHATS = "/api2/v2/chats"
ME = "/api2/v2/users/me"
F, G, K = 9301, 9302, 9303

account_registry.get_account = lambda aid: {"id": aid} if aid in _CREATORS else None
account_registry.is_account = lambda aid: aid in _CREATORS
account_registry.get_platform = lambda aid: "onlyfans"
account_registry.list_accounts = lambda include_watchers=False: [{"id": a, "has_session": True} for a in _CREATORS]
account_registry.get_role = lambda aid: None
events_persist.enqueue = lambda *_a, **_k: None
of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0


class _Resp:
    def __init__(self, url, status, body, headers=None):
        self.url, self.status_code, self.ok = url, status, 200 <= status < 300
        self.text, self.headers = json.dumps(body), headers or {}

    def json(self):
        return json.loads(self.text)


class _Wire:
    def __init__(self, unread=(), more=None, window=None):
        self.unread, self.more, self.page2, self.fail, self.me = list(unread), more, None, None, None
        self.window, self.hold = window, None
        self.calls: list = []
        self.at: list = []

    def _answer(self, method, url):
        u = urlsplit(url)
        if u.path == ME and self.me is not None:
            return _Resp(url, 200, {"id": int(A), "chatMessagesCount": self.me})
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((u.path, q))
        self.at.append(badge_reads._clock())
        off, lim = int(q["offset"]), int(q["limit"])
        if self.window is not None and method == "GET" and u.path == CHATS and "filter" not in q:
            if self.hold is not None:
                assert self.hold.wait(5), "the held window read was never released"
            if self.fail is not None:
                return _Resp(url, *self.fail)
            rows = self.window[off:off + lim]
            return _Resp(url, 200, {"list": rows, "hasMore": off + lim < len(self.window)})
        assert method == "GET" and u.path == CHATS and q.get("filter") == "unread", (method, url)
        if self.fail is not None:
            return _Resp(url, *self.fail)
        if off and self.page2 is not None:
            return _Resp(url, *self.page2)
        rows = self.unread[off:off + lim]
        more = off + lim < len(self.unread) if self.more is None else self.more
        return _Resp(url, 200, {"list": rows, "hasMore": more})

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


class _Clock:
    def __init__(self):
        self.t = int(time.time() * 1000)

    def __call__(self) -> int:
        return self.t


_LOG: list = []
_DOWN: set = set()
_DEAD: set = set()
_UNPUMPED: set = set()


@contextlib.contextmanager
def _world(wire: _Wire, tabs=frozenset({A}), knob: str | None = None, unread: bool = True, real_live: bool = False,
           seeded: bool = True):
    saved_env = {k: os.environ.get(k) for k in ("SHARED_REFRESHER", "UNREAD_TOTAL", "BADGE_READS")}
    os.environ["SHARED_REFRESHER"] = "1"
    for k, v in (("UNREAD_TOTAL", "1" if unread else None), ("BADGE_READS", knob)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    clock, published, lines = _Clock(), [], []
    _LOG.clear()

    class _Cap(logging.Handler):
        def emit(self, rec):
            msg = rec.getMessage()
            _LOG.append(msg)
            if msg.startswith("badge_read "):
                lines.append(msg)
    cap = _Cap()
    logging.getLogger("of-relay.badge_reads").addHandler(cap)
    for m in (shared_refresher, unread_total, badge_reads):
        importlib.reload(m)
    if seeded:
        badge_reads._seeded.update(_CREATORS)
    client = _client(A, wire)
    orig = (server._load_client, events.open_tab_accounts, events.publish, badge_reads._clock, of_ws.connected_since)
    server._load_client = lambda *_a, **_k: client
    events.open_tab_accounts = lambda: tabs
    events.publish = published.append
    badge_reads._clock = unread_total._clock = clock
    up = time.monotonic()
    for held in (_DOWN, _DEAD, _UNPUMPED):
        held.clear()
    of_ws.connected_since = lambda aid: None if str(aid) in _DOWN else up
    if not real_live:
        shared_refresher.live = lambda aid: ("dead" if aid in _DEAD else None if aid in _UNPUMPED
                                             else "down" if aid in _DOWN else "up")
    try:
        yield clock, published, lines
    finally:
        logging.getLogger("of-relay.badge_reads").removeHandler(cap)
        server._load_client, events.open_tab_accounts, events.publish, badge_reads._clock, of_ws.connected_since = orig
        for a in _CREATORS:
            relay_cache.invalidate("list_chats", a)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in (shared_refresher, unread_total, badge_reads):
            importlib.reload(m)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def _row(fan: int, unread: bool = True, muted=False) -> dict:
    return {"withUser": {"id": fan}, "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0,
            "isMutedNotifications": muted,
            "lastMessage": {"id": fan * 10, "createdAt": _iso(int(time.time() * 1000) - 60_000)}}


async def _hold_window(rows: list, aid=A, *, fetched_at: int | None = None) -> None:
    relay_cache.invalidate("list_chats", aid)
    await relay_cache.get_or_fetch("list_chats", aid, _ROSTER_WINDOW_KEY, ttl_seconds=600,
                                   fetcher=lambda: {"list": rows, "hasMore": False,
                                                    "fetched_at": fetched_at})


async def _hold_other(aid=A) -> tuple:
    key = (10, 0, "recent", "unread", None, None)
    await relay_cache.get_or_fetch("list_chats", aid, key, ttl_seconds=600, fetcher=lambda: {"list": []})
    return key


def _window(aid=A) -> list:
    return relay_cache.peek("list_chats", aid, _ROSTER_WINDOW_KEY)["list"]


async def _frame(n: int, aid=A) -> None:
    await events.handle_event({"__account_id": aid, "chat_messages": n, "count_priority_chat": 0,
                               "count_call_request_chat": 0, "unread_tips": 0})


async def _tick_at(clock: _Clock, t: int) -> None:
    clock.t = t
    await badge_reads.tick()
    for task in list(badge_reads._reads):
        await task


def _flips(published) -> list:
    return [(e["chat_read_changed"]["fan_id"], e["chat_read_changed"]["unread"], e["chat_read_changed"]["at"])
            for e in published if "chat_read_changed" in e]


def _walk_calls() -> int:
    return sum(n for caller, path, aid, _s, n in of_call_counter.snapshot()["rows"]
               if caller == "walk:badge_attribution" and aid == A)


def _ints(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _ints(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _ints(v)
    elif isinstance(x, int) and not isinstance(x, bool):
        yield x


async def case_onlyfans_read_flips_dot():
    assert badge_reads.on_frame in relay_hooks.inbound_message, "registered through badge_reads_wiring"
    wire = _Wire(unread=[_row(K)] + [_row(2000 + i) for i in range(9)])
    with _world(wire) as (clock, pub, lines):
        await _hold_window([_row(F), _row(K)])
        other = await _hold_other()
        before, t = _walk_calls(), clock.t
        await _frame(11)
        await _frame(10)
        await _frame(77, aid=B)
        await _tick_at(clock, t + 1499)
        assert wire.calls == [], ("no read before the 1.5 s decide wait", wire.calls)
        await _tick_at(clock, t + 1500)
        assert [(p, q["filter"], q["limit"], q["offset"]) for p, q in wire.calls] == [(CHATS, "unread", "10", "0")]
        assert _flips(pub) == [(F, 0, t + 1500)], ("{F, 0} stamped at the ask time", pub)
        assert [r["hasUnread"] for r in _window()] == [False, True] and _window()[0]["unreadMessagesCount"] == 0
        assert relay_cache.peek("list_chats", A, other) is None, "the other list_chats entries dropped"
        assert lines == [f"badge_read account={A} kind=frame calls=1 rows=10 counter=10 complete=1 mismatch=0 "
                         "flips=1 restricted=0"], lines
        assert _walk_calls() - before == 1, "of_call_stats counts the read as walk:badge_attribution"
        await _tick_at(clock, t + 5000)
        assert len(wire.calls) == 1, ("B (no Open tab) and A's decided frame: no more reads", wire.calls)
        assert not {10, 11, 77} & set(_ints(pub)), ("the OF counter in no publish", pub)


async def case_deep_fan_flips_dot():
    window = [_row(1000 + i, unread=False) for i in range(25)]
    wire = _Wire(unread=[_row(G)])
    with _world(wire) as (clock, pub, _lines):
        await _hold_window(window)
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert _flips(pub) == [], ("first read: no previous set, no off-window flip", pub)
        assert len(wire.calls) == 1
        wire.unread = []
        held = _window()
        clock.t += 5000
        await _frame(0)
        await _tick_at(clock, clock.t + 1500)
        assert [(f, u) for f, u, _at in _flips(pub)] == [(G, 0)], pub
        assert _window() == held, "G has no held row: the window untouched"


async def case_same_value_frame_reads():
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, pub, lines):
        await _hold_window([_row(F, unread=False)])
        await _frame(1)
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert len(wire.calls) == 1, wire.calls
        assert [(f, u) for f, u, _at in _flips(pub)] == [(F, 1)], ("read in the window, in the list", pub)
        assert _window()[0]["hasUnread"] is True and _window()[0]["unreadMessagesCount"] == 1
        clock.t += 5000
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert len(wire.calls) == 2, ("a same-value frame: one read", wire.calls)
        assert len(lines) == 2, lines


_429 = (429, {"error": {"code": 0, "message": "Too many requests. Please allow 0 seconds"}})


async def case_incomplete_list_never_reads_fans():
    unread = [_row(1000 + i) for i in range(35)]
    legs = [
        ("two full pages, hasMore, counter 35", 35, None, 2, "complete=0 mismatch=0"),
        ("page-2 error", 35, (500, {"error": "x"}), 2, "complete=0 mismatch=0"),
        ("page-2 429 twice (paced's one retry)", 35, _429, 3, "complete=0 mismatch=0"),
        ("duplicate-only page 2", 35, (200, {"list": unread[:10], "hasMore": True}), 2, "complete=0 mismatch=0"),
    ]
    for why, counter, page2, calls, flags in legs:
        wire = _Wire(unread=unread)
        wire.page2 = page2
        with _world(wire) as (clock, pub, lines):
            await _hold_window([_row(F)] + unread[:3])
            await _frame(counter)
            await _tick_at(clock, clock.t + 1500)
            assert len(wire.calls) == calls, (why, wire.calls)
            assert _flips(pub) == [], (why, "no (fan, 0) from an incomplete list", pub)
            assert len(lines) == 1 and flags in lines[0], (why, lines)
    wire = _Wire(unread=[])
    with _world(wire) as (clock, pub, lines):
        await _hold_window([_row(F)])
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert _flips(pub) == [] and len(lines) == 1, (pub, lines)
        assert "rows=0 counter=1 complete=0 mismatch=1 flips=0" in lines[0], lines


async def _frame_after(clock: _Clock, seconds: float, n: int, step_ms: int) -> None:
    await asyncio.sleep(seconds)
    clock.t += step_ms
    await _frame(n)


async def case_one_page_read_waits_for_the_trailing_frame():
    others = [_row(2000 + i) for i in range(9)]
    legs = [("frame 0.3 s after the answer", others, None, 0.3, 300, "counter=10 complete=1 mismatch=0 flips=1", [F]),
            ("no frame within 1 s", others, None, 1.5, 300, "counter=11 complete=0 mismatch=1 flips=0", []),
            ("matching frame stamped at the ask, not after", others, None, 0.3, 0, "complete=0 mismatch=1 flips=0",
             []),
            ("two pages, page 2 shifted empty", others + [_row(2009)], (200, {"list": [], "hasMore": False}), 0.3,
             300, "calls=2 rows=10 counter=11 complete=0 mismatch=1 flips=0", [])]
    for why, unread, page2, late, step, flags, cleared in legs:
        wire = _Wire(unread=[_row(K)] + unread)
        wire.page2 = page2
        with _world(wire) as (clock, pub, lines):
            await _hold_window([_row(F), _row(K)])
            await _frame(11)
            trailing = asyncio.create_task(_frame_after(clock, late, 10, step))
            await _tick_at(clock, clock.t + 1500)
            assert len(lines) == 1 and flags in lines[0], (why, lines)
            assert [f for f, u, _at in _flips(pub) if u == 0] == cleared, (why, pub)
            await trailing


async def case_one_frame_during_the_read_judges_it():
    others = [_row(2000 + i) for i in range(9)]
    legs = [("one frame mid-read, list matches it", others, [10], None, "counter=10 complete=1 mismatch=0 flips=1",
             [F]),
            ("two frames mid-read can cancel", others, [12, 10], None, "counter=10 complete=0 mismatch=0 flips=0", []),
            ("one frame mid-read, list off by one", others, [12], None, "counter=12 complete=0 mismatch=1 flips=0", []),
            ("two pages, one frame mid-read", others + [_row(2009)], [11],
             (200, {"list": [_row(2009)], "hasMore": False}),
             "calls=2 rows=11 counter=11 complete=0 mismatch=0 flips=0", [])]
    for why, unread, mid, page2, flags, cleared in legs:
        wire = _Wire(unread=[_row(K)] + unread)
        wire.page2 = page2
        with _world(wire) as (clock, pub, lines):
            await _hold_window([_row(F), _row(K)])
            await _frame(11)
            answer, pending = wire._answer, list(mid)

            def page_one_with_frames(method, url):
                while pending:
                    clock.t += 100
                    badge_reads.on_frame(A, "chat_messages", {"chat_messages": pending.pop(0)})
                return answer(method, url)
            wire._answer = page_one_with_frames
            await _tick_at(clock, clock.t + 1500)
            assert len(lines) == 1 and flags in lines[0], (why, lines)
            assert [f for f, u, _at in _flips(pub) if u == 0] == cleared, (why, pub)


def _starts(wire: _Wire) -> list:
    return [t for t, (_p, q) in zip(wire.at, wire.calls) if q["offset"] == "0"]


async def case_gap_full_and_lean():
    for knob, gap in (("full", 5000), ("lean", 15000)):
        wire = _Wire(unread=[_row(F)])
        with _world(wire, knob=knob) as (clock, _pub, _lines):
            t0 = clock.t
            for i in range(10):
                clock.t = t0 + i * 300
                await _frame(1)
            for s in range(0, 40_000, 1000):
                await _tick_at(clock, t0 + s)
            starts = _starts(wire)
            assert len(starts) == 2 and starts[1] - starts[0] == gap, (knob, [t - t0 for t in starts])
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, _pub, lines):
        t0 = clock.t
        for i in range(200):
            clock.t = t0 + i * 18_000
            await _frame(1)
            await _tick_at(clock, clock.t + 1500)
        assert len(_starts(wire)) == 200 and len(lines) == 200, len(_starts(wire))
    for knob, gap in (("full", 5000), ("lean", 15000)):
        wire = _Wire(unread=[_row(F)])
        with _world(wire, knob=knob) as (clock, _pub, _lines):
            answer, paced = wire._answer, [1300]

            def held_page_one(method, url):
                if paced:
                    clock.t += paced.pop()
                return answer(method, url)
            wire._answer = held_page_one
            t0 = clock.t
            await _frame(1)
            for s in range(1500, 40_000, 500):
                if s == 3000:
                    clock.t = max(clock.t, t0 + s)
                    await _frame(1)
                if t0 + s > clock.t:
                    await _tick_at(clock, t0 + s)
            starts = _starts(wire)
            assert len(starts) == 2 and starts[1] - starts[0] >= gap, (knob, [t - t0 for t in starts])


_HELD = (429, {"error": {"code": 0, "message": "Too many requests. Please allow 0 seconds"}}, {"Retry-After": "1"})


@contextlib.contextmanager
def _note_reads():
    noted: list = []
    real = app_open_warm.note_read
    app_open_warm.note_read = noted.append
    try:
        yield noted
    finally:
        app_open_warm.note_read = real


async def case_429_holds_exit():
    for why, page2, fail, calls in (("page 2", _HELD, None, 3), ("page 1", None, _HELD, 2)):
        wire = _Wire(unread=[_row(1000 + i) for i in range(35)])
        wire.page2, wire.fail = page2, fail
        with _world(wire) as (clock, _pub, _lines), _note_reads() as noted:
            await _frame(35)
            await _tick_at(clock, clock.t + 1500)
            assert len(wire.calls) == calls, (why, wire.calls)
            assert app_open_warm.exit_held_s(A) > 0, (why, "a terminal 429 holds the exit")
            assert noted == [A], (why, "the read, failed or not, noted on the exit", noted)
            wire.page2 = wire.fail = None
            wire.calls.clear()
            clock.t += 10_000
            await _tick_at(clock, clock.t + 1500)
            assert wire.calls == [], (why, "no read while the exit is held", wire.calls)
            await asyncio.sleep(app_open_warm.exit_held_s(A) + 0.05)
            await _tick_at(clock, clock.t + 1000)
            assert len(wire.calls) == 2, (why, "one retry after the hold, without another frame", wire.calls)
            assert noted == [A, A], (why, "one note_read per read", noted)
            await _tick_at(clock, clock.t + 10_000)
            assert len(wire.calls) == 2, (why, wire.calls)


async def case_switch_off_and_lean():
    wire = _Wire(unread=[_row(F)])
    with _world(wire, knob="off") as (clock, pub, lines):
        await _hold_window([_row(F)], fetched_at=clock.t)
        await events.handle_event(_echo(F, 1))
        assert _flips(pub) == [] and _window()[0]["hasUnread"] is True, ("off: an echo flips nothing", pub)
        with _busting(wire) as bust:
            server._chats_window_fetched_at[A] = server._time_mod.monotonic()
            assert A in await bust(_User()) and wire.calls == [], ("off: ?bust= serves held, 0 calls", wire.calls)
        unread_total.set_restricted_unread(A, Restricted(0, False, 0), 0)
        for i in range(20):
            clock.t += 6000
            await _frame(20 - i)
            await _tick_at(clock, clock.t + 1500)
        assert wire.calls == [] and lines == [], (wire.calls, lines)
        assert unread_total.snapshot(A)["n"] == 1, ("the Red circle still follows the counter", unread_total.snapshot(A))
    with _world(wire, knob="sometimes") as (clock, _pub, _lines):
        assert [m for m in _LOG if "BADGE_READS" in m] == ["badge_reads_bad_knob BADGE_READS='sometimes'; full"], _LOG
        for _ in range(2):
            await _frame(1)
            await _tick_at(clock, clock.t + 1500)
            clock.t += 3500
        assert [t - _starts(wire)[0] for t in _starts(wire)] == [0, 5000], "full: the 5 s gap"
    with _world(wire, knob="") as (clock, _pub, _lines):
        assert badge_reads.MODE == "full" and not [m for m in _LOG if "BADGE_READS" in m], _LOG
    wire = _Wire(unread=[_row(F)])
    with _world(wire, unread=False) as (clock, _pub, lines):
        await _frame(3)
        await _tick_at(clock, clock.t + 1500)
        assert wire.calls == [] and badge_reads._frames == {} and not badge_reads.ENABLED, wire.calls


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


@contextlib.contextmanager
def _swap(module, name, fn):
    real = getattr(module, name)
    setattr(module, name, fn)
    try:
        yield
    finally:
        setattr(module, name, real)


def _dm(fan: int, mid: int, aid=A) -> dict:
    return {"api2_chat_message": {"id": mid, "text": "hey", "price": 0, "isTip": False, "fromUser": {"id": fan},
                                  "createdAt": _iso(int(time.time() * 1000)), "responseType": "message"},
            "__account_id": aid}


RF, MF, MF2, NF = 9401, 9402, 9403, 9404


async def _seed(clock: _Clock, n: int) -> None:
    await _frame(n)
    await _tick_at(clock, clock.t + 1500)
    assert badge_reads.unread_set(A) is not None


async def case_restricted_unread_feeds_red():
    wire = _Wire(unread=[_row(RF)] + [_row(2000 + i) for i in range(9)])
    async with _registry(RF):
        with _world(wire) as (clock, _pub, lines):
            noted: list = []
            with _swap(shared_refresher, "note_values", noted.append):
                await _hold_window([_row(1000 + i, unread=False) for i in range(25)])
                await _frame(10)
                assert unread_total.snapshot(A)["n"] is None and badge_reads.restricted_unread(A) is None
                noted.clear()
                await _tick_at(clock, clock.t + 1500)
            assert badge_reads.restricted_unread(A) == 1 and noted == [A], (badge_reads.restricted_unread(A), noted)
            restricted, at = unread_total._r[A]
            assert (restricted.n, at) == (1, clock.t), ("R at the read's ask time", unread_total._r[A])
            assert unread_total.snapshot(A)["n"] == 9, ("red = counter - R", unread_total.snapshot(A))
            assert lines[-1].endswith("complete=1 mismatch=0 flips=0 restricted=1"), lines
            view = badge_reads.unread_set(A)
            assert view.fans == frozenset([RF] + [2000 + i for i in range(9)]) and view.asked_at == clock.t, view
            importlib.reload(badge_reads)
            assert badge_reads.unread_set(A) is None, "a restart holds no set"


async def case_landed_mute_rescores_held_restricted_unread():
    wire = _Wire(unread=[_row(RF), _row(F)])
    async with _registry(RF):
        with _world(wire) as (clock, _pub, _lines):
            await _hold_window([_row(F)])
            await _seed(clock, 2)
            assert (badge_reads.restricted_unread(A), unread_total.snapshot(A)["n"]) == (1, 1)
            calls = len(wire.calls)
            for muted, counter, restricted in ((True, 1, 0), (False, 2, 1)):
                clock.t += 100
                relay_hooks.fire_mute(RF, muted, account_id=A)
                await _frame(counter)
                got = (badge_reads.restricted_unread(A), unread_total.snapshot(A)["n"])
                assert got == (restricted, 1), (muted, got)
            assert len(wire.calls) == calls


async def case_muted_dm_keeps_restricted():
    wire = _Wire(unread=[_row(RF)])
    async with _registry(RF, MF, MF2):
        with _world(wire) as (clock, _pub, _lines):
            await _hold_window([_row(MF, unread=False, muted=True)])
            await _seed(clock, 1)
            assert badge_reads.restricted_unread(A) == 1
            relay_hooks.fire_mute(MF2, True, account_id=A)
            for fan, mid in ((MF, 1), (MF2, 2)):
                wire.calls.clear()
                clock.t += 6000
                await events.handle_event(_dm(fan, fan * 10 + mid))
                await _frame(1)
                await _tick_at(clock, clock.t + 1500)
                assert wire.calls == [], (fan, "a DM explains its frame: 0 list calls", wire.calls)
                assert badge_reads.restricted_unread(A) == 1, (fan, badge_reads.restricted_unread(A))
                assert fan not in badge_reads.unread_set(A).fans


async def case_unmuted_elsewhere_heals_held_row():
    wire = _Wire(unread=[_row(F), _row(K), _row(MF)])
    with _world(wire) as (clock, pub, _lines):
        await _hold_window([_row(F, muted=True), _row(K)])
        relay_hooks.fire_mute(MF, True, account_id=A)
        await _seed(clock, 3)
        assert [r["isMutedNotifications"] for r in _window()] == [False, False], _window()
        assert badge_reads._muted[(A, MF)] == (False, clock.t), ("stamped at the ask", badge_reads._muted)
        wire.unread = [_row(K), _row(MF)]
        clock.t += 6000
        await _frame(2)
        await _tick_at(clock, clock.t + 1500)
        assert [(f, u) for f, u, _at in _flips(pub)] == [(F, 0)], ("F read elsewhere now flips", pub)


async def case_newer_dm_survives_read():
    wire = _Wire(unread=[_row(F)])
    loop = asyncio.get_running_loop()
    with _world(wire) as (clock, _pub, lines):
        await _seed(clock, 1)
        answer = wire._answer

        def _dm_while_reading(method, url):
            clock.t += 1
            asyncio.run_coroutine_threadsafe(events.handle_event(_dm(NF, NF * 10)), loop).result(10)
            return answer(method, url)
        wire._answer = _dm_while_reading
        clock.t += 6000
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert len(wire.calls) == 2 and "complete=1" in lines[-1], (wire.calls, lines)
        view = badge_reads.unread_set(A)
        assert NF in view.fans and F in view.fans, ("the newer DM survives the read's replace", view)


def _echo(fan, mid: int, aid=A) -> dict:
    return {"api2_chat_message": {"id": mid, "text": "on it", "chatUserId": fan,
                                  "createdAt": _iso(int(time.time() * 1000))}, "__account_id": aid}


def _outbound(mid: int, aid=A) -> dict:
    return {"api2_chat_message": {"id": mid, "text": "on it", "fromUser": {"id": int(aid)},
                                  "createdAt": _iso(int(time.time() * 1000))}, "__account_id": aid}


async def case_explained_frames_cost_nothing():
    legs = (("ordinary Inbound DM", _dm(NF, NF * 10), -400), ("chatUserId echo", _echo(K, 1), -1000),
            ("Outbound echo", _outbound(2), 1000))
    for why, msg, msg_after_frame in legs:
        wire = _Wire(unread=[_row(K)])
        with _world(wire) as (clock, pub, lines):
            t = clock.t
            for at, ev in sorted(((t + msg_after_frame, msg), (t, None)), key=lambda x: x[0]):
                clock.t = at
                await (events.handle_event(ev) if ev else _frame(1))
            for dt in (1500, 2500, 5000):
                await _tick_at(clock, t + dt)
            assert wire.calls == [] and lines == [] and _flips(pub) == [], (why, wire.calls, pub)
            clock.t = t + 10_000
            await _frame(1)
            await _tick_at(clock, clock.t + 1500)
            assert len(wire.calls) == 1, (why, "an unexplained frame still reads", wire.calls)
    with _world(_Wire()) as (_clock, _pub, _lines):
        for bad in (None, [], "x", {"api2_chat_message": None}, {"api2_chat_message": {"id": 1, "chatUserId": "x"}},
                    {"api2_chat_message": {"id": 1, "chatUserId": {"id": 1}}}, {"api2_chat_message": {"fromUser": 7}},
                    {"chat_messages": -1}, {"chat_messages": True}, {"chat_messages": "3"}):
            badge_reads.on_frame(A, None, bad)
            badge_reads.on_frame(A, "api2_chat_message", bad)
        assert not [m for m in _LOG if m.startswith("badge_reads_frame_failed")], _LOG
    await _intent_sites_cost_nothing()


async def case_echo_branch_flips_read():
    assert not hasattr(relay_hooks, "creator_echo"), "no echo hook (SH14)"
    deep = 9305
    wire = _Wire(unread=[_row(F), _row(K), _row(deep)])
    with _world(wire) as (clock, pub, lines):
        await _hold_window([_row(F), _row(K), _row(G, unread=False)])
        await _seed(clock, 3)
        assert badge_reads.unread_set(A).fans == {F, K, deep}
        wire.calls.clear()
        t = clock.t = clock.t + 6000
        await events.handle_event(_echo(F, 1))
        assert _flips(pub) == [(F, 0, t)], ("{F, 0} at the echo's arrival, before any tick", pub)
        assert [(r["hasUnread"], r["unreadMessagesCount"]) for r in _window()] == [(False, 0), (True, 1), (False, 0)]
        assert badge_reads.unread_set(A).fans == {K, deep}, badge_reads.unread_set(A)
        clock.t = t + 200
        await _frame(2)
        for dt in (1700, 5000):
            await _tick_at(clock, t + dt)
        assert wire.calls == [] and len(lines) == 1, ("the echo explains its frame", wire.calls)
        clock.t = t + 10_000
        await events.handle_event(_echo(G, 2))
        assert _flips(pub) == [(F, 0, t)], ("a read Fan outside the set: nothing to flip", pub)
        held = _window()
        await events.handle_event(_echo(deep, 3))
        assert _flips(pub)[1:] == [(deep, 0, t + 10_000)] and _window() == held, ("past the window, in the set", pub)
        assert badge_reads.unread_set(A).fans == {K}


def _grey(aid=A):
    return unread_total.snapshot(aid)["grey"]


async def case_ineligible_creators_read_nothing():
    dead: dict = {}

    async def dead_map():
        return dict(dead)
    legs = (("no Open tab", frozenset({B}), {}, {}, None),
            ("Dead session", frozenset({A}), {A: account_health.DeadSession()}, {}, "dead"),
            ("proxy down", frozenset({A}), {}, {"px-a": "down"}, "proxy_down"))
    for why, tabs, dead_now, bad, cause in legs:
        wire = _Wire(unread=[_row(F)])
        dead.clear()
        dead.update(dead_now)
        with _world(wire, tabs=tabs, real_live=True) as (clock, _pub, lines), _refresher() as refresh, \
                _swap(account_health, "dead_session_map", dead_map), \
                _swap(proxy_health, "bad_reasons", lambda b=bad: dict(b)), \
                _swap(proxies, "get_for_account", lambda aid: {"label": "px-a"} if aid == A else None):
            _DOWN.add(A)
            t = clock.t
            for i in range(6):
                clock.t = t + i * 6000
                await refresh()
                await _frame(5 - i)
                for dt in (1500, 3000, 4500):
                    await _tick_at(clock, t + i * 6000 + dt)
            assert wire.calls == [] and lines == [], (why, wire.calls)
            assert badge_reads.unread_set(A) is None, why
            if cause:
                assert _grey() == cause, (why, unread_total.snapshot(A))
            if cause == "dead":
                dead.clear()
                _DOWN.discard(A)
                await refresh()
                clock.t += 6000
                await _frame(1)
                await _tick_at(clock, clock.t + 1500)
                assert len(wire.calls) == 1 and _grey() != "dead", ("back: it reads", unread_total.snapshot(A))
    calls: list = []

    def boom():
        calls.append(1)
        raise RuntimeError("proxy registry down")
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, _pub, lines), _swap(proxy_health, "bad_reasons", boom):
        t = clock.t
        await _frame(1)
        for s in range(1000, 10_001, 1000):
            await _tick_at(clock, t + s)
        assert len(wire.calls) == 1 and len(calls) == 2, ("the last answer stands, one check per 5 s", calls)
        assert sum(m.startswith("badge_reads_proxy_check_failed") for m in _LOG) == 2, _LOG


def _polls(lines) -> int:
    return sum(" kind=poll " in m for m in lines)


@contextlib.contextmanager
def _refresher():
    with _swap(app_open_warm, "refresh", lambda *_a, **_k: None):
        yield shared_refresher.tick


def _slots(published, aid=A) -> list:
    return [e["creator_refreshed"]["values"]["unread_total"] for e in published
            if "creator_refreshed" in e and e["creator_refreshed"]["account_id"] == aid]


async def case_socket_down_polls_15s():
    for knob in (None, "lean"):
        wire = _Wire(unread=[_row(F)])
        with _world(wire, knob=knob) as (clock, _pub, lines):
            _DOWN.add(A)
            t = clock.t
            for s in range(0, 61_000, 1000):
                await _tick_at(clock, t + s)
            assert [x - t for x in _starts(wire)] == [15000, 30000, 45000, 60000], (knob, _starts(wire))
            assert _polls(lines) == 4 == len(lines), (knob, lines)
            _DOWN.discard(A)
            for s in range(61_000, 120_000, 1000):
                await _tick_at(clock, t + s)
            assert len(_starts(wire)) == 4, (knob, "reconnected: no more polls", _starts(wire))
    for why, unpumped, blip_s in (("no socket expected (refresher `live` None)", True, 120), ("a 14 s blip", False, 14)):
        wire = _Wire(unread=[_row(F)])
        with _world(wire) as (clock, _pub, _lines):
            _DOWN.add(A)
            if unpumped:
                _UNPUMPED.add(A)
            t = clock.t
            for s in range(0, 120_000, 1000):
                if s == blip_s * 1000:
                    _DOWN.discard(A)
                await _tick_at(clock, t + s)
            assert wire.calls == [], (why, wire.calls)
    wire = _Wire(unread=[_row(F), _row(G, muted=True), _row(RF)])
    async with _registry(RF):
        with _world(wire) as (clock, pub, lines), _refresher() as refresh:
            await _frame(9)
            await _tick_at(clock, clock.t + 1500)
            assert "counter=9 complete=0 mismatch=1" in lines[-1], lines
            _DOWN.add(A)
            t = clock.t = clock.t + 10_000
            await _tick_at(clock, t)
            await _tick_at(clock, t + 15_000)
            snap = unread_total.snapshot(A)
            assert snap["grey"] is None and snap["n"] == 1, ("2 rows OF counts - R 1; the pre-drop counter 9 unused", snap)
            assert snap["at"] == t + 15_000 and "complete=1" in lines[-1], (snap, lines)
            wire.fail = (500, {"error": "x"})
            for s in range(20_000, 80_000, 1000):
                clock.t = t + s
                if s % 5000 == 0:
                    await refresh()
                await _tick_at(clock, t + s)
            got = [(x["grey"], x["v"]) for x in _slots(pub)]
            assert [g for g, _v in got] == [None, "stale"] and got[1][1] == got[0][1] + 1, got
            assert _slots(pub)[1]["n"] == 1, "stale: a grey circle, never a frozen number on its own"
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, _pub, _lines):
        _DOWN.add(A)
        t = clock.t = int(time.time() * 1000) - 100_000
        await _tick_at(clock, t)
        await _tick_at(clock, t + 15_000)
        assert unread_total.snapshot(A)["grey"] is None, unread_total.snapshot(A)
        wire.me = 4
        await asyncio.to_thread(server._load_client(A).me)
        snap = unread_total.snapshot(A)
        assert snap["at"] > t + 15_000 and snap["n"] == 4 and snap["grey"] is None, \
            ("a /users/me during the outage keeps the poll's confirmation", snap)
    wire = _Wire(unread=[_row(1000 + i) for i in range(30)])
    with _world(wire) as (clock, _pub, lines):
        await _frame(30)
        _DOWN.add(A)
        for s in range(0, 46_000, 1000):
            await _tick_at(clock, clock.t + 1000)
        assert _polls(lines) >= 2 and all("complete=0" in m for m in lines), lines
        assert _grey() == "socket_down", ("an incomplete poll confirms nothing", unread_total.snapshot(A))
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, _pub, lines):
        _DOWN.add(A)
        t, grey = clock.t, []
        for s in range(0, 7_200_000, 5000):
            await _tick_at(clock, t + s)
            grey.append((t + s, _grey()))
        starts = _starts(wire)
        worst = max(sum(1 for y in starts if x <= y < x + 3_600_000) for x in starts)
        assert worst == 240 and len(starts) == 479, (worst, len(starts))
        assert {b - a for a, b in zip(starts, starts[1:])} == {badge_reads.POLL_MS}, "paced by the poll, no cap"
        assert all(g != "capped" for _at, g in grey), [g for _at, g in grey if g == "capped"][:3]


class _User:
    account_ids = list(_CREATORS)


@contextlib.contextmanager
def _roster(wire: _Wire):
    import accounts_admin_api
    client = _client(A, wire)
    saved = (server._get_request_user, server._load_client)
    server._get_request_user = lambda: _User()
    server._load_client = lambda *_a, **_k: client

    class _R:
        headers: dict = {}

    async def fold(ahead_s: float = 0) -> None:
        for a in _CREATORS:
            relay_cache.invalidate("roster_count", a)
            accounts_admin_api._roster_last.pop(a, None)
        stamp = int((time.time() + ahead_s) * 1000)
        relay_cache.patch("list_chats", A, lambda key, value: (
            {**value, "fetched_at": stamp} if key == _ROSTER_WINDOW_KEY else None
        ))
        await accounts_admin_api.admin_accounts_roster_counts(_R())
    try:
        yield fold
    finally:
        server._get_request_user, server._load_client = saved
        for a in _CREATORS:
            relay_cache.invalidate("roster_count", a)
            server._chats_window_fetched_at.pop(a, None)
            accounts_admin_api._roster_last.pop(a, None)


async def case_fold_rescores_from_set():
    wire = _Wire(unread=[_row(F)])
    writes: list = []
    real = unread_total.set_restricted_unread
    window = [_row(F), _row(RF)]
    restricted_f = {**_row(F), "canSendMessage": False, "canNotSendReason": "muted"}

    def rec(aid, r, at):
        writes.append((aid, r.n))
        real(aid, r, at)
    for knob, set_held in ((None, True), ("off", False)):
        with _world(wire, knob=knob) as (clock, _pub, _lines), _roster(wire) as fold:
            await _hold_window(window)
            if set_held:
                await _seed(clock, 1)
            else:
                wire.calls.clear()
                await _frame(1)
                await _tick_at(clock, clock.t + 1500)
                assert badge_reads.unread_set(A) is None and wire.calls == [], "BADGE_READS=off: no read, no set"
            async with _registry(RF):
                with _swap(unread_total, "set_restricted_unread", rec):
                    writes.clear()
                    await fold()
                    assert writes == [(A, 0 if set_held else 1)], (knob, "R from the set, else the window", writes)
                    if not set_held:
                        continue
                    async with _registry(F):
                        writes.clear()
                        await fold()
                        assert writes == [(A, 1)], ("restricted here: the next fold excludes him", writes)
                    await _hold_window([restricted_f, _row(RF)])
                    writes.clear()
                    await fold(ahead_s=5)
                    assert writes == [(A, 1)], ("restricted on OF: his newer window row excludes him", writes)
                    restricted, at = unread_total._r[A]
                    assert (restricted.n, at) == (1, badge_reads._sets[A].as_of), \
                        ("R at the set's own time, not the window's: a read landing later still writes", unread_total._r[A])
                    await _hold_window(window)
                    writes.clear()
                    await fold(ahead_s=10)
                    assert writes == [(A, 0)], ("unrestricted: he counts again", writes)
                    await _hold_window([restricted_f, _row(RF)])
                    writes.clear()
                    await fold(ahead_s=-60)
                    assert writes == [(A, 0)], ("a window older than his row leaves it", writes)
                    with _swap(events, "open_tab_accounts", lambda: frozenset()):
                        await _tick_at(clock, clock.t + 1000)
                    assert badge_reads.unread_set(A) is None, "the tab closed: no set held"
                    await _hold_window(window)
                    writes.clear()
                    await fold()
                    assert writes == [(A, 1)], ("no set: R from the window again", writes)


class _Chatter:
    account_ids = [A]


@contextlib.contextmanager
def _busting(wire: _Wire):
    import accounts_admin_api
    client = _client(A, wire)
    saved = (server._get_request_user, accounts_admin_api._get_request_chatter, server._load_client)
    server._load_client = lambda *_a, **_k: client

    class _R:
        headers: dict = {}

    async def bust(who) -> dict:
        server._get_request_user = lambda: who if isinstance(who, _User) else None
        accounts_admin_api._get_request_chatter = lambda: who if isinstance(who, _Chatter) else None
        return (await accounts_admin_api.admin_accounts_roster_counts(_R(), bust=A))["counts"]
    try:
        yield bust
    finally:
        server._get_request_user, accounts_admin_api._get_request_chatter, server._load_client = saved
        for a in _CREATORS:
            relay_cache.invalidate("roster_count", a)
            server._chats_window_fetched_at.pop(a, None)
            accounts_admin_api._roster_last.pop(a, None)


def _window_reads(wire: _Wire) -> int:
    return sum(1 for _p, q in wire.calls if "filter" not in q and q["offset"] == "0")


async def case_hover_cooldown_shared():
    wire = _Wire(unread=[_row(F)], window=[_row(F), _row(G, unread=False)])
    with _world(wire) as (clock, _pub, lines), _busting(wire) as bust:
        t0 = clock.t
        first = await bust(_User())
        assert _window_reads(wire) == 1 and first[A]["unread"] == 1, (wire.calls, first)
        wire.window = [_row(F), _row(G)]
        clock.t = t0 + 5_000
        second = await bust(_Chatter())
        assert _window_reads(wire) == 1 and second[A]["unread"] == 1, ("5 s later: the held fold", wire.calls)
        clock.t = t0 + 31_000
        third = await bust(_Chatter())
        assert _window_reads(wire) == 2 and third[A]["unread"] == 2, ("31 s later: a second read", third)
        assert [ln.split(" calls=")[0] for ln in lines] == [f"badge_read account={A} kind=hover"] * 2, lines
        assert badge_reads._gates.get(A) is None, ("hover reads are no Attribution start", badge_reads._gates)
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert [q.get("filter") for _p, q in wire.calls[-1:]] == ["unread"] and len(lines) == 3, wire.calls

        wire.window = [_row(F), _row(G), _row(K)]
        wire.hold = threading.Event()
        clock.t = t0 + 70_000
        reads = _window_reads(wire)
        lead = asyncio.create_task(bust(_User()))
        for _ in range(500):
            if _window_reads(wire) > reads:
                break
            await asyncio.sleep(0.01)
        assert _window_reads(wire) == reads + 1, "the leader's read is on the wire"
        clock.t += 2_000
        follow = asyncio.create_task(bust(_Chatter()))
        await asyncio.sleep(0.1)
        assert not follow.done(), "the follower waits for the leader's read"
        wire.hold.set()
        a, b = await asyncio.gather(lead, follow)
        assert _window_reads(wire) == reads + 1 and a == b, (wire.calls, a, b)
        assert {r["withUser"]["id"] for r in _window()} == {F, G, K}, "the page-0 entry fresh after"
        assert [ln.split(" calls=")[0] for ln in lines].count(f"badge_read account={A} kind=hover") == 3, lines

    wire = _Wire(window=[_row(F)])
    wire.fail = (500, {"error": {"code": 0, "message": "boom"}})
    with _world(wire) as (clock, _pub, lines), _busting(wire) as bust:
        wire.hold = threading.Event()
        lead = asyncio.create_task(bust(_User()))
        for _ in range(500):
            if _window_reads(wire):
                break
            await asyncio.sleep(0.01)
        follow = asyncio.create_task(bust(_Chatter()))
        await asyncio.sleep(0.1)
        wire.hold.set()
        a, b = await asyncio.gather(lead, follow)
        assert a == b == {A: {"unread": 0, "owe_reply": 0, "as_of": 0}}, (a, b)
        calls = len(wire.calls)
        clock.t += 5_000
        await bust(_Chatter())
        assert len(wire.calls) == calls and _window_reads(wire) == 1, ("5 s later: held, 0 calls", wire.calls)
        assert lines == [], ("a failed read writes no kind=hover line", lines)

    wire = _Wire(window=[_row(F)])
    with _world(wire, unread=False) as (clock, _pub, lines), _busting(wire) as bust:
        await bust(_User())
        clock.t += 5_000
        await bust(_Chatter())
        assert _window_reads(wire) == 2 and lines == [], ("UNREAD_TOTAL off: every bust reads", wire.calls, lines)


class _Writer:
    def __init__(self, n: int, fail: bool = False):
        self.loop, self.n, self.fail = asyncio.get_running_loop(), n, fail
        self.calls: list = []

    def _write(self, name: str, *_a):
        self.calls.append(name)
        if self.fail:
            raise OFAPIError(f"OF 500 on {name}")
        asyncio.run_coroutine_threadsafe(_frame(self.n), self.loop).result(10)
        return {}

    def __getattr__(self, name):
        if name in ("mark_chat_read", "mark_chat_unread", "mark_all_chats_read", "mute_chat", "unmute_chat"):
            return lambda *a: self._write(name, *a)
        raise AttributeError(name)


@contextlib.contextmanager
def _routes(writer: _Writer, clock: _Clock):
    import read_flip
    with _swap(server, "_get_client", lambda *_a, **_k: writer), \
            _swap(server, "_resolve_account_id", lambda *_a, **_k: A), _swap(read_flip, "now_ms", clock):
        yield


async def _intent_sites_cost_nothing():
    from types import SimpleNamespace
    from automations import full_ai_live, welcome_chatter_for_info
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, _pub, _lines):
        writer = _Writer(1)
        await _hold_window([_row(F)])
        await _seed(clock, 1)
        turn = SimpleNamespace(client=writer, cfg=SimpleNamespace(account_id=A), c=SimpleNamespace(fan_id=F))
        sites = [
            ("mark read", lambda: server.of_mark_chat_read(F)),
            ("mark unread", lambda: server.of_mark_chat_unread(F)),
            ("mark all read", lambda: server.of_mark_all_chats_read()),
            ("mute", lambda: server.of_mute_chat(F)),
            ("unmute", lambda: server.of_unmute_chat(F)),
            ("full_ai_live", lambda: full_ai_live._after_burst(A, F, (datetime(2000, 1, 1), 0), writer, 1)),
            ("welcome_chatter_for_info", lambda: welcome_chatter_for_info._turn_mark_read(turn)),
        ]
        with _routes(writer, clock):
            for site, call in sites:
                await _hold_window([_row(F)])
                clock.t += 6000
                wire.calls.clear()
                before = len(writer.calls)
                await call()
                assert len(writer.calls) == before + 1, (site, writer.calls)
                await _tick_at(clock, clock.t + 1500)
                assert wire.calls == [], (site, "its frame beat the response: 0 list calls", wire.calls)
                if site == "mark read":
                    assert F not in badge_reads.unread_set(A).fans, "a landed read applies ReadDone to the set"
                if site == "mark unread":
                    assert F in badge_reads.unread_set(A).fans, "a landed unread applies UnreadDone to the set"
                if site == "mark all read":
                    await _frame(1)
                    await _tick_at(clock, clock.t + 1500)
                    assert wire.calls == [], ("a second frame 1.5 s after the response: mark-all explains it", wire.calls)
                    await _frame(1)
                    await _tick_at(clock, clock.t + 1500)
                    assert len(wire.calls) == 1, ("3 s after the response (inside the 5 s max): explained no more",
                                                  wire.calls)
                    wire.calls.clear()


async def case_failed_write_retires_intent():
    wire = _Wire(unread=[_row(F)])
    with _world(wire) as (clock, _pub, _lines):
        writer = _Writer(1, fail=True)
        with _routes(writer, clock):
            try:
                await server.of_mark_chat_read(F)
                raise AssertionError("the OF error reaches the caller")
            except server.HTTPException:
                pass
        clock.t += 100
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert len(wire.calls) == 1, ("the write did not land: its intent hides no other frame", wire.calls)


async def case_held_answer_does_not_reopen_local_read():
    for seeded in (False, True):
        wire = _Wire(unread=[_row(F)])
        with _world(wire) as (clock, pub, _lines):
            await _hold_window([_row(F)])
            if seeded:
                await _seed(clock, 1)
                clock.t += 6000
            await _frame(1)
            entered, release = threading.Event(), threading.Event()
            answer = wire._answer

            def held_answer(method, url):
                entered.set()
                assert release.wait(5)
                return answer(method, url)

            wire._answer = held_answer
            reader = asyncio.create_task(_tick_at(clock, clock.t + 1500))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                clock.t += 10
                badge_reads.on_read_flip(A, F, 0, clock.t)
                await _hold_window([_row(F, unread=False)])
            finally:
                release.set()
                await reader
            assert _flips(pub) == [] and not _window()[0]["hasUnread"]
            assert F not in badge_reads.unread_set(A).fans


async def case_known_contradiction_reconciles_elsewhere_drop():
    for event in (_echo(G, 21), _dm(K, 22)):
        wire = _Wire(unread=[_row(F), _row(K)])
        with _world(wire) as (clock, pub, _lines):
            await _hold_window([_row(F), _row(G, unread=False), _row(K)])
            await _seed(clock, 2)
            wire.calls.clear()
            wire.unread = [_row(K)]
            clock.t += 6000
            await events.handle_event(event)
            clock.t += 200
            await _frame(1)
            await _tick_at(clock, clock.t + 1500)
            assert len(wire.calls) == 1 and [(f, u) for f, u, _ in _flips(pub)] == [(F, 0)]


async def case_incomplete_restricted_grey_or_confirmed_floor():
    async with _registry(RF):
        for actionable in (4, 9):
            wire = _Wire(unread=[_row(RF)])
            with _world(wire) as (clock, _pub, _lines):
                await _seed(clock, 1)
                wire.unread = [_row(2000 + i) for i in range(actionable)]
                wire.more = True
                clock.t += 6000
                await _frame(26)
                await _tick_at(clock, clock.t + 1500)
                assert RF in badge_reads.unread_set(A).fans
                slot = unread_total.snapshot(A)
                assert (slot["n"], slot["grey"]) == ((None, "r_unknown") if actionable < 9 else (9, None)), slot
                clock.t += 100
                await _frame(0)
                slot = unread_total.snapshot(A)
                assert (slot["n"], slot["grey"]) == (None, "r_unknown"), slot


async def case_settle_rejects_two_counter_frames():
    wire = _Wire(unread=[_row(K)])
    with _world(wire) as (clock, pub, lines):
        await _hold_window([_row(F), _row(K)])
        await _frame(2)

        answered = threading.Event()
        answer = wire._answer

        def signal_answer(method, url):
            response = answer(method, url)
            answered.set()
            return response

        wire._answer = signal_answer

        async def trailing():
            assert await asyncio.to_thread(answered.wait, 15)
            await asyncio.sleep(0.3)
            clock.t += 100
            await _frame(3)
            clock.t += 100
            await _frame(1)

        frames = asyncio.create_task(trailing())
        await _tick_at(clock, clock.t + 1500)
        await frames
        assert any("complete=0" in line for line in lines) and _flips(pub) == []


async def case_replayed_echo_does_not_clear_newer_dm():
    for seen in (False, True):
        wire = _Wire(unread=[_row(F)])
        with _world(wire) as (clock, pub, _lines):
            await _hold_window([_row(F)])
            await _seed(clock, 1)
            echo = _echo(F, 123)
            echo["api2_chat_message"]["createdAt"] = _iso(clock.t + 1)
            if seen:
                clock.t += 10
                await events.handle_event(echo)
            clock.t += 20
            dm = _dm(F, F * 10 + 1)
            dm["api2_chat_message"]["createdAt"] = _iso(clock.t)
            await events.handle_event(dm)
            pub.clear()
            clock.t += 1
            await events.handle_event(echo)
            assert not _flips(pub) and F in badge_reads.unread_set(A).fans and _window()[0]["hasUnread"]


async def case_off_mode_watches_unpeeked_drop():
    import badge_watch
    wire = _Wire()
    with _world(wire, knob="off") as (clock, _pub, _lines):
        records = []
        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        handler = Capture()
        badge_watch.log.addHandler(handler)
        try:
            await _frame(2)
            badge_watch.note_unpeeked(A, F)
            await _frame(1)
            await _tick_at(clock, clock.t + 1500)
        finally:
            badge_watch.log.removeHandler(handler)
        assert any(f"badge_unpeeked_drop account={A} chat={F} " in line for line in records)
        assert not wire.calls


async def case_mute_uses_resolved_account_without_header():
    import relay_host
    wire = _Wire()
    request = server._request_ctx.set(None)
    try:
        with _world(wire) as (clock, _pub, _lines), _swap(server, "_active_for", lambda _req: lambda: A):
            await _hold_window([_row(F)])

            def answer(method, url):
                assert (method, urlsplit(url).path) == ("POST", f"/api2/v2/chats/{F}/mute")
                return _Resp(url, 200, {"success": True})

            wire._answer = answer
            assert not relay_host.request_account_header()
            await server.of_mute_chat(F)
            assert badge_reads._muted[(A, F)] == (True, clock.t)
    finally:
        server._request_ctx.reset(request)


async def case_window_mute_normalizes_fan_id():
    with _world(_Wire()):
        row = _row(F)
        row["withUser"]["id"] = str(F)
        await _hold_window([row])
        relay_hooks.fire_mute(F, True, account_id=A)
        assert _window()[0]["isMutedNotifications"] is True


def case_wiring_registers_hooks_once():
    import badge_reads_wiring
    import relay_hooks
    from fastapi import FastAPI

    badge_reads_wiring.wire(FastAPI())
    badge_reads_wiring.wire(FastAPI())
    assert sum(h.__module__ == "badge_reads" and h.__name__ == "on_frame" for h in relay_hooks.inbound_message) == 1
    assert sum(h.__module__ == "badge_reads" and h.__name__ == "start" for h in relay_hooks.background_loops) == 1


def case_mute_hook_uses_resolved_account():
    with _world(_Wire()) as (clock, _pub, _lines):
        relay_hooks.fire_mute(F, True, account_id=A)
        assert badge_reads._muted[(A, F)] == (True, clock.t)
        relay_hooks.fire_mute(F, False, account_id=A)
        assert badge_reads._muted[(A, F)] == (False, clock.t)


async def case_receipt_patch_preserves_prior_dm_delta():
    wire = _Wire()
    with _world(wire) as (clock, _pub, _lines):
        await _hold_window([_row(F, unread=False)])
        await _seed(clock, 0)
        wire.calls.clear()
        wire.unread = [_row(F)]
        clock.t += 6000
        await events.handle_event(_dm(F, F * 10 + 1))
        assert _window()[0]["hasUnread"]
        clock.t += 200
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert wire.calls == []



async def _held_read(wire: _Wire, clock: _Clock, during) -> None:
    entered, release = threading.Event(), threading.Event()
    answer = wire._answer

    def held_answer(method, url):
        entered.set()
        assert release.wait(5)
        return answer(method, url)

    wire._answer = held_answer
    reader = asyncio.create_task(_tick_at(clock, clock.t + 1500))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        await during()
    finally:
        release.set()
        await reader


async def case_mark_read_landing_mid_read_stays_read():
    import read_flip
    for seeded in (False, True):
        wire = _Wire(unread=[_row(F)])
        with _world(wire) as (clock, pub, _lines):
            await _hold_window([_row(F)])
            if seeded:
                await _seed(clock, 1)
                clock.t += 6000
            await _frame(1)

            async def mark_read_lands():
                write_at = clock.t - 50
                clock.t += 10
                await read_flip.after_write(A, F, 0, {}, at=write_at)
            await _held_read(wire, clock, mark_read_lands)
            assert [(f, u) for f, u, _ in _flips(pub)] == [(F, 0)], (seeded, pub)
            assert F not in badge_reads.unread_set(A).fans, (seeded, badge_reads.unread_set(A))


async def case_one_echo_explains_one_drop():
    wire = _Wire(unread=[_row(F), _row(K)])
    with _world(wire) as (clock, pub, _lines):
        await _hold_window([_row(F), _row(K)])
        await _seed(clock, 2)
        wire.calls.clear()
        wire.unread = []
        clock.t += 6000
        await events.handle_event(_echo(F, 41))
        for n in (1, 0):
            clock.t += 200
            await _frame(n)
        await _tick_at(clock, clock.t + 1500)
        assert len(wire.calls) == 1 and (K, 0) in [(f, u) for f, u, _ in _flips(pub)], (wire.calls, pub)


async def case_reply_echo_explains_its_frame():
    import read_flip
    for echo_first in (False, True):
        wire = _Wire(unread=[_row(F)])
        with _world(wire) as (clock, _pub, _lines):
            await _hold_window([_row(F)])
            await _seed(clock, 1)
            wire.calls.clear()
            wire.unread = []
            clock.t += 6000
            if echo_first:
                await events.handle_event(_echo(F, 51))
            read_flip.after_reply(A, F, clock.t - 300)
            if not echo_first:
                clock.t += 100
                await events.handle_event(_echo(F, 51))
            clock.t += 200
            await _frame(0)
            await _tick_at(clock, clock.t + 1500)
            assert wire.calls == [], (echo_first, "the reply's echo explains its frame", wire.calls)

async def case_socket_up_r_unknown_reads_once():
    wire = _Wire(unread=[_row(F)])
    with _world(wire, seeded=False) as (clock, _pub, lines):
        t = clock.t
        await _tick_at(clock, t)
        assert len(wire.calls) == 1 and lines[0].startswith(f"badge_read account={A} kind=frame "), lines
        assert not unread_total.restricted_unknown(A), "the read published R"
        for s in range(1000, 60_001, 1000):
            await _tick_at(clock, t + s)
        assert len(wire.calls) == 1, ("R known: no more reads", wire.calls)
    wire = _Wire(unread=[_row(F)])
    wire.fail = (500, {"error": "boom"})
    with _world(wire, seeded=False) as (clock, _pub, _lines):
        t = clock.t
        for s in range(0, 60_001, 1000):
            await _tick_at(clock, t + s)
        assert len(wire.calls) == 1 and unread_total.restricted_unknown(A), ("one ask per lifetime", wire.calls)
    wire = _Wire(unread=[_row(F)])
    with _world(wire, seeded=False) as (clock, _pub, lines):
        _DOWN.add(A)
        t = clock.t
        for s in range(0, 15_001, 1000):
            await _tick_at(clock, t + s)
        assert [x - t for x in _starts(wire)] == [15000] and _polls(lines) == 1, ("socket down: poll only", lines)


_harness.run()
