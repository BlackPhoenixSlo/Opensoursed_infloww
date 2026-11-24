#!/usr/bin/env python3
"""The Amber circle (creator-badges phase 0F), the Relay half: the guarded Owe reply fold over the held page-0 window
against Phase C's real Unread set (`badge_reads._sets`, built by `badge_reads_decide.replace_set`), and its publish on
Phase B's badge path (`values.unread_total.amber` / `amber_at`, `shared_refresher.note_values` captured), driven
through `events.handle_event` frames, `badge_reads.tick()` and the real routes, OF a fake wire counting every call.

  case_incomplete_set_guard: an incomplete latest set naming F, F's held row read and Fan-last -> F not amber; G,
                             unnamed, with an unread row -> not amber (blue); H read and Fan-last, unnamed -> amber.
  case_read_elsewhere_moves_red_to_amber: a Phase C flip `chat_read_changed {F, 0}` on a Fan-last row -> amber +1 in
                             the read that flipped it (one Attribution call, no window read), red -1, F out of the
                             Unread set; our own mark read of unread K -> amber +1 before the route's bust, kept after.
  case_mute_drops_amber:     the mute route on owed M -> amber -1; on unread F -> no publish (never +1).
  case_restrict_moves_amber_and_r: restrict owed M -> amber -1, red unchanged; restrict unread F -> R +1, red -1;
                             unrestrict each -> back; all at the route, 0 OF reads.
  case_restrict_badge_reads_off: no Unread set held -> R from the held window, the same moves at the route.
  case_lift_restores_amber_no_window_read: restrict owed M -> amber -1, the held window kept with M's row restricted
                             (`canSendMessage` false, reason "muted"); lift -> amber +1, the row sendable again; no
                             window read between, 0 OF reads.
  case_amber_unknown_until_window: no window since restart -> `amber` null; a held window -> its count, `amber_at`
                             its fetched-at stamp; dropped -> kept; an hour old with no read since -> still its count
                             (a stale Creator greys red instead).
  case_unchanged_amber_publishes_nothing: a DM to an already-unread Fan, then a window read with the same rows -> no
                             publish, Badge version unchanged.
  case_echo_clears_amber_no_call: a Creator echo (`chatUserId` F) for owed F -> amber -1 at receipt, 0 OF calls;
                             another owed Fan's echo 3 s later -> -1 again; an echo for unread M -> never amber on a
                             later refresh.
  case_dm_moves_amber_to_red: an inbound DM from owed F (hooks, then the transcode) -> amber -1, red +1, 0 OF calls.
  case_late_window_keeps_echo: a window read asked before an echo for F, landing after it with F Fan-last -> F not
                             amber, published or in the route's fold.
  case_late_window_keeps_dm: the same with a DM from F -> F not amber.
  case_echo_keeps_debounced_bust: echo for F -> amber -1; an `Outbound` echo -> the existing bust drops `list_chats`
                             and `roster_count`, amber kept (not null); a second inside 20 s -> no second bust.
  case_route_matches_after_echo: a cached roster-counts answer, then an echo for an owed Fan -> the warm answer, the
                             last-known count and the held fold give the published amber, 0 OF calls.
  case_no_fan_in_both:       DM, an Attribution set replace, our mark read (checked while in flight), an echo: at
                             every step no Fan the window counts amber is in the Unread set, and amber = that count.
  case_badge_reads_off_amber_still_moves: BADGE_READS=off -> an echo, a DM, our mark read and mark unread each move
                             amber; counter frames and ticks issue no badge read (0 OF reads).
  case_badge_reads_lean_amber_moves: BADGE_READS=lean -> the same moves; a counter frame's read waits out the 15 s
                             lean gap (none at 5 s).
  case_queue_finish_rereads_once: through `event_transcoder.transcode` with real `chat_queue_*` frames and the loop
                             driven by `badge_reads.tick()`: finish total 23 -> one page-0 window read (3 calls on the
                             wire, `walk:badge_queue`), one exact `kind=queue` line; the same frame again or total 4
                             -> none; `BADGE_READS=off`, no Open tab, Dead session, proxy down, 429 exit hold -> none;
                             `lean` -> a second finish waits its 15 s gap; a finish 1 s after an Attribution start ->
                             waits the rest of the gap (queued, no Attribution re-ask), then one read; two finishes
                             inside the gap -> one read, then one follow-up; an Attribution ask and a finish together
                             -> the Attribution read first.
  case_mass_clears_amber:    owed Fans in the held window; the mass's re-read lands with them Creator-last -> the
                             published amber falls to 0 in that read; the route's `owe_reply` too, at 0 calls.

Run:  ./venv/bin/python service/tests/test_amber_circle.py
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
from dataclasses import replace
from datetime import datetime, timezone  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import accounts as account_registry  # noqa: E402

_harness.make_client()
import server  # noqa: E402
import accounts_admin_api  # noqa: E402
import app_open_warm  # noqa: E402
import badge_reads  # noqa: E402
import badge_reads_decide  # noqa: E402
import event_transcoder  # noqa: E402
import events  # noqa: E402
import events_persist  # noqa: E402
import of_call_counter  # noqa: E402
import of_pacing  # noqa: E402
import of_ws  # noqa: E402
import proxies  # noqa: E402
import proxy_health  # noqa: E402
import read_flip  # noqa: E402
import relay_cache  # noqa: E402
import shared_refresher  # noqa: E402
import unread_total  # noqa: E402
import unread_total_decide  # noqa: E402
from accounts_admin_api import _ROSTER_WINDOW_KEY  # noqa: E402
from of_client import OFClient  # noqa: E402

ME, F, G, H = 7, 4301, 4302, 4303
A, QA = "8431", "8331"
K, M = 4304, 4305
CHATS = "/api2/v2/chats"

account_registry.get_account = lambda aid: {"id": aid} if aid in (A, QA) else None
account_registry.is_account = lambda aid: aid in (A, QA)
account_registry.get_platform = lambda aid: "onlyfans"
account_registry.list_accounts = lambda include_watchers=False: [{"id": A, "has_session": True}]
account_registry.get_role = lambda aid: None
events_persist.enqueue = lambda *_a, **_k: None


async def _seed() -> None:
    from db.engine import get_session
    from db.models import Account
    async with get_session() as s:
        s.add(Account(id=A, nickname=A))

asyncio.run(_seed())
of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def _row(fan: int, unread: int = 0, muted: bool = False) -> dict:
    return {"withUser": {"id": fan}, "hasUnread": bool(unread), "unreadMessagesCount": unread,
            "isMutedNotifications": muted,
            "lastMessage": {"id": fan * 10, "fromUser": {"id": fan},
                            "createdAt": _iso(int(time.time() * 1000) - 60_000)}}


class _Client:
    user_id = ME

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def list_chats(self, *, limit=10, offset=0, **_kw):
        return {"list": self.rows[offset:offset + limit], "hasMore": offset + limit < len(self.rows)}


async def case_incomplete_set_guard():
    aid = "acct-amber-incomplete"
    window = [_row(F), _row(G, unread=1), _row(H)]
    orig = server._load_client
    server._load_client = lambda _aid: _Client(window)
    s = badge_reads_decide.replace_set(None, [_row(F, unread=1)], 1, False)
    try:
        with badge_reads._lock:
            badge_reads._sets[aid] = s
        out = await accounts_admin_api._compute_roster_count_of(aid, bypass=True)
        assert (out["unread"], out["owe_reply"]) == (1, 1), out
    finally:
        server._load_client = orig
        with badge_reads._lock:
            badge_reads._sets.pop(aid, None)
        server.relay_cache.invalidate("list_chats", aid)
        server.relay_cache.invalidate("roster_count", aid)
        server._chats_window_fetched_at.pop(aid, None)
        accounts_admin_api._roster_last.pop(aid, None)


class _Resp:
    def __init__(self, url, body):
        self.url, self.status_code, self.ok, self.headers = url, 200, True, {}
        self.text = json.dumps(body)

    def json(self):
        return json.loads(self.text)


class _Wire:
    """OF: `GET /chats?filter=unread` pages `unread`, `GET /chats` (no filter) pages `window`; `calls` logs each."""
    def __init__(self, unread=(), window=()):
        self.unread, self.window = list(unread), list(window)
        self.calls: list = []

    def _answer(self, method, url):
        u = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((method, u.path, q.get("filter")))
        assert method == "GET" and u.path == CHATS, (method, url)
        rows = self.unread if q.get("filter") == "unread" else self.window
        off, lim = int(q["offset"]), int(q["limit"])
        return _Resp(url, {"list": rows[off:off + lim], "hasMore": off + lim < len(rows)})

    def get(self, url, headers=None, timeout=None):
        return self._answer("GET", url)

    def request(self, method, url, json=None, headers=None, timeout=None):
        return self._answer(method, url)


class _Writer:
    """OF's read-state writes (mark read / unread, mute): each answers `{}`; `calls` logs them."""
    def __init__(self):
        self.calls: list = []

    def send_message(self, fan, **kwargs):
        self.calls.append(("send_message", fan))
        return {"text": kwargs["text"]}

    def __getattr__(self, name):
        if name in ("mark_chat_read", "mark_chat_unread", "mute_chat", "unmute_chat", "restrict_user",
                    "unrestrict_user", "hide_chat", "unhide_chat"):
            return lambda *a: self.calls.append((name, *a)) or {}
        raise AttributeError(name)


class _Clock:
    def __init__(self):
        self.t = int(time.time() * 1000)

    def __call__(self) -> int:
        return self.t


@contextlib.contextmanager
def _world(wire: _Wire, badge_reads_mode: str | None = None):
    """Knobs on (`BADGE_READS` unset, or `badge_reads_mode`; modules reloaded: a restart), A's client on `wire`, A an Open tab with its Live connection up, the
    Relay clock fake; yields (clock, the Creators `note_values` was poked for)."""
    saved_env = {k: os.environ.get(k) for k in ("SHARED_REFRESHER", "UNREAD_TOTAL", "BADGE_READS")}
    os.environ.update(SHARED_REFRESHER="1", UNREAD_TOTAL="1")
    os.environ.pop("BADGE_READS", None)
    if badge_reads_mode is not None:
        os.environ["BADGE_READS"] = badge_reads_mode
    for m in (shared_refresher, unread_total, badge_reads):
        importlib.reload(m)
    c = OFClient({"headers": {"user_id": A, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                  "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                        "checksum_indexes": [1], "checksum_constant": 1}},
                  "cookies": []})
    c._x_hash, c.http = "h", wire
    clock, noted, up = _Clock(), [], time.monotonic()
    orig = (server._load_client, events.open_tab_accounts, events.publish, of_ws.connected_since)
    server._load_client = lambda *_a, **_k: c
    events.open_tab_accounts = lambda: frozenset({A})
    events.publish = lambda _e: None
    badge_reads._clock = unread_total._clock = clock
    of_ws.connected_since = lambda _aid: up
    shared_refresher.live = lambda _aid: "up"
    shared_refresher.note_values = noted.append
    try:
        yield clock, noted
    finally:
        server._load_client, events.open_tab_accounts, events.publish, of_ws.connected_since = orig
        for ns in ("list_chats", "roster_count"):
            relay_cache.invalidate(ns, A)
        server._chats_window_fetched_at.pop(A, None)
        accounts_admin_api._roster_last.pop(A, None)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in (shared_refresher, unread_total, badge_reads):
            importlib.reload(m)


@contextlib.contextmanager
def _routes(writer: _Writer, clock: _Clock):
    orig = (server._get_client, server._resolve_account_id, read_flip.now_ms)
    server._get_client = lambda *_a, **_k: writer
    server._resolve_account_id = lambda *_a, **_k: A
    read_flip.now_ms = clock
    try:
        yield
    finally:
        server._get_client, server._resolve_account_id, read_flip.now_ms = orig


async def _land_window(rows: list) -> None:
    """A page-0 window read landing (held, stamped now, folded by roster-counts): 0 OF calls."""
    relay_cache.invalidate("list_chats", A)
    await relay_cache.get_or_fetch("list_chats", A, _ROSTER_WINDOW_KEY, ttl_seconds=600,
                                   fetcher=lambda: {"list": rows, "hasMore": False, "asked_at": unread_total._clock(),
                                                    "fetched_at": unread_total._clock()})
    server._chats_window_fetched_at[A] = time.monotonic()
    await accounts_admin_api._held_roster_count(A)


async def _frame(n: int) -> None:
    await events.handle_event({"__account_id": A, "chat_messages": n, "count_priority_chat": 0,
                               "count_call_request_chat": 0, "unread_tips": 0})


async def _tick_at(clock: _Clock, t: int) -> None:
    clock.t = t
    await badge_reads.tick()
    for task in list(badge_reads._reads):
        await task


def _slot() -> dict:
    return unread_total.snapshot(A)


async def case_read_elsewhere_moves_red_to_amber():
    wire = _Wire(unread=[_row(K, unread=1)] + [_row(2000 + i, unread=1) for i in range(9)])
    with _world(wire) as (clock, noted):
        await _land_window([_row(F, unread=1), _row(K, unread=1), _row(M)])
        await _frame(11)
        before = _slot()
        assert (before["n"], before["amber"]) == (11, 1), before
        await _frame(10)
        noted.clear()
        await _tick_at(clock, clock.t + 1500)
        after = _slot()
        assert wire.calls == [("GET", CHATS, "unread")], ("one Attribution read, no window read", wire.calls)
        assert (after["n"], after["amber"]) == (10, 2) and after["v"] > before["v"], (before, after)
        assert A in noted, "published on Phase B's badge path"
        assert F not in badge_reads.unread_set(A).fans, "F counted amber, never in the Unread set too"
        writer, noted[:] = _Writer(), []
        clock.t += 1000
        with _routes(writer, clock):
            await server.of_mark_chat_read(K)
        assert writer.calls == [("mark_chat_read", K)] and len(wire.calls) == 1, (writer.calls, wire.calls)
        assert _slot()["amber"] == 3 and A in noted, ("our mark read of unread K: amber +1", _slot())
        assert relay_cache.peek("list_chats", A, _ROSTER_WINDOW_KEY) is None, "the route's bust still drops it"
        assert _slot()["amber"] == 3, ("kept across the bust", _slot())


async def case_mute_drops_amber():
    with _world(_Wire()) as (clock, noted):
        await _land_window([_row(M), _row(F, unread=1)])
        assert _slot()["amber"] == 1, _slot()
        writer = _Writer()
        with _routes(writer, clock):
            noted.clear()
            await server.of_mute_chat(M)
            assert _slot()["amber"] == 0 and A in noted, ("muting owed M: amber -1", _slot())
            await _land_window([_row(M, muted=True), _row(F, unread=1)])
            v, noted[:] = _slot()["v"], []
            await server.of_mute_chat(F)
            assert _slot()["amber"] == 0 and _slot()["v"] == v and noted == [], ("unread F: never +1", _slot())
        assert writer.calls == [("mute_chat", M), ("mute_chat", F)], writer.calls


@contextlib.asynccontextmanager
async def _unrestricted_after(*fans: int):
    try:
        yield
    finally:
        from automations._common import set_of_restricted_skip
        for fan in fans:
            await set_of_restricted_skip(A, fan, False)


async def case_restrict_moves_amber_and_r():
    wire = _Wire()
    with _world(wire) as (clock, noted):
        with badge_reads._lock:
            badge_reads._sets[A] = badge_reads_decide.replace_set(None, [_row(F, unread=1)], clock.t, True)
        await _land_window([_row(M), _row(F, unread=1)])
        await _frame(1)
        assert (_slot()["n"], _slot()["amber"]) == (1, 1), _slot()
        writer = _Writer()
        async with _unrestricted_after(M, F):
            with _routes(writer, clock):
                await server.of_restrict_user(M, request=None, ack=False, hide=False)
                assert (_slot()["n"], _slot()["amber"]) == (1, 0), ("restrict owed M: amber -1, red holds", _slot())
                await server.of_restrict_user(F, request=None, ack=False, hide=False)
                assert (_slot()["n"], _slot()["amber"]) == (0, 0), ("restrict unread F: R +1 at once", _slot())
                assert badge_reads.restricted_unread(A) == 1
                await server.of_unrestrict_user(F, request=None, unhide=False)
                assert (_slot()["n"], _slot()["amber"]) == (1, 0), ("unrestrict F: R back", _slot())
                await _land_window([_row(M), _row(F, unread=1)])
                assert (_slot()["n"], _slot()["amber"]) == (1, 0), ("a fold keeps M out while restricted", _slot())
                await server.of_unrestrict_user(M, request=None, unhide=False)
                assert (_slot()["n"], _slot()["amber"]) == (1, 1), ("unrestrict M: amber back", _slot())
        assert wire.calls == [], ("0 OF reads", wire.calls)
        assert writer.calls == [("restrict_user", M), ("restrict_user", F), ("unrestrict_user", F),
                                ("unrestrict_user", M)], writer.calls


async def case_restrict_badge_reads_off():
    with _world(_Wire(), "off") as (clock, noted):
        await _land_window([_row(M), _row(F, unread=1)])
        await _frame(1)
        assert (_slot()["n"], _slot()["amber"]) == (1, 1), _slot()
        writer = _Writer()
        async with _unrestricted_after(M, F):
            with _routes(writer, clock):
                await server.of_restrict_user(F, request=None, ack=False, hide=False)
                assert (_slot()["n"], _slot()["amber"]) == (0, 1), ("restrict unread F: R +1 at once", _slot())
                await _land_window([_row(M), _row(F, unread=1)])
                await server.of_unrestrict_user(F, request=None, unhide=False)
                assert (_slot()["n"], _slot()["amber"]) == (1, 1), ("unrestrict F: R back", _slot())


async def case_lift_restores_amber_no_window_read():
    wire = _Wire()
    with _world(wire) as (clock, noted):
        await _land_window([_row(M), _row(F, unread=1)])
        await _frame(1)
        assert _slot()["amber"] == 1, _slot()
        writer = _Writer()
        async with _unrestricted_after(M):
            with _routes(writer, clock):
                await server.of_restrict_user(M, request=None, ack=False, hide=False)
                assert _slot()["amber"] == 0, ("restrict owed M: amber -1", _slot())
                held = relay_cache.peek("list_chats", A, _ROSTER_WINDOW_KEY)
                assert held is not None, "the route patches the held window, never drops it"
                m = next(r for r in held["list"] if r["withUser"]["id"] == M)
                assert (m["canSendMessage"], m["canNotSendReason"], m["withUser"].get("isRestricted")) == \
                    (False, "muted", True), m
                noted.clear()
                await server.of_unrestrict_user(M, request=None, unhide=False)
                assert _slot()["amber"] == 1 and A in noted, ("lift M: amber +1 with no window read", _slot())
                m = next(r for r in relay_cache.peek("list_chats", A, _ROSTER_WINDOW_KEY)["list"]
                         if r["withUser"]["id"] == M)
                assert (m["canSendMessage"], m["canNotSendReason"], "isRestricted" in m["withUser"]) == \
                    (True, None, False), m
        assert wire.calls == [], ("0 OF reads", wire.calls)


async def case_amber_unknown_until_window():
    with _world(_Wire()) as (clock, noted):
        assert (_slot()["amber"], _slot()["amber_at"]) == (None, None), ("no window since restart", _slot())
        await _land_window([_row(M)])
        at = _held_window()["fetched_at"]
        clock.t = at
        assert _slot()["amber"] == 1 and abs(_slot()["amber_at"] - at) <= 1, _slot()
        relay_cache.invalidate("list_chats", A)
        accounts_admin_api.amber_refresh(A)
        assert _slot()["amber"] == 1, ("a dropped window keeps the last amber", _slot())
        v = _slot()["v"]
        clock.t = _slot()["amber_at"] + 3_600_000
        assert _slot()["amber"] == 1 and _slot()["v"] == v, ("an hour old, no read since", _slot())


async def case_unchanged_amber_publishes_nothing():
    with _world(_Wire()) as (clock, noted):
        await _land_window([_row(F, unread=1), _row(M)])
        await _frame(1)
        v, noted[:] = _slot()["v"], []
        await events.handle_event({"api2_chat_message": {
            "id": 99, "text": "hey", "price": 0, "isTip": False, "fromUser": {"id": F},
            "createdAt": _iso(int(time.time() * 1000)), "responseType": "message"}, "__account_id": A})
        await asyncio.sleep(0)
        assert noted == [] and _slot()["v"] == v and _slot()["amber"] == 1, ("DM to unread F", noted, _slot())
        time.sleep(0.002)
        await _land_window([_row(F, unread=1), _row(M)])
        assert noted == [] and _slot()["v"] == v, ("a window read, same amber: no publish", noted, _slot())


def _echo(fan: int, mid: int) -> dict:
    return {"api2_chat_message": {"id": mid, "text": "on it", "chatUserId": fan,
                                  "createdAt": _iso(int(time.time() * 1000))}, "__account_id": A}


def _outbound(mid: int) -> dict:
    return {"api2_chat_message": {"id": mid, "text": "on it", "fromUser": {"id": int(A)},
                                  "createdAt": _iso(int(time.time() * 1000))}, "__account_id": A}


def _dm(fan: int, mid: int) -> dict:
    return {"api2_chat_message": {"id": mid, "text": "hey", "price": 0, "isTip": False, "fromUser": {"id": fan},
                                  "createdAt": _iso(int(time.time() * 1000)), "responseType": "message"},
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


async def _deliver(event: dict, clock: _Clock) -> None:
    """One frame as the pump takes it, 1 ms after the last: the hooks at receipt, then the persist worker's transcode."""
    clock.t += 1
    time.sleep(0.002)
    with _quiet_hooks():
        await events.handle_event(event)
        await event_transcoder.transcode(event)


def _held_window() -> dict:
    return relay_cache.peek("list_chats", A, _ROSTER_WINDOW_KEY)


async def case_echo_clears_amber_no_call():
    wire = _Wire()
    with _world(wire) as (clock, noted):
        await _land_window([_row(F), _row(K), _row(M, unread=1)])
        assert _slot()["amber"] == 2, _slot()
        noted.clear()
        await _deliver(_echo(F, 901), clock)
        assert _slot()["amber"] == 1 and A in noted, ("echo for owed F: -1 at once", _slot())
        clock.t += 3000
        await _deliver(_echo(K, 902), clock)
        assert _slot()["amber"] == 0, ("a second echo 3 s later: -1 again", _slot())
        await _deliver(_echo(M, 903), clock)
        accounts_admin_api.amber_refresh(A)
        assert _slot()["amber"] == 0, ("unread M answered: never amber", _slot())
        assert wire.calls == [], wire.calls


async def case_dm_moves_amber_to_red():
    wire = _Wire()
    with _world(wire) as (clock, noted):
        await _land_window([_row(F), _row(M)])
        await _frame(5)
        before = _slot()
        assert (before["n"], before["amber"]) == (5, 2), before
        time.sleep(0.002)
        await _deliver(_dm(F, 911), clock)
        assert (_slot()["n"], _slot()["amber"]) == (6, 1), ("F leaves amber, lights red", _slot())
        assert wire.calls == [], wire.calls


def _late(wire: _Wire, event: dict, clock: _Clock) -> None:
    """`event` arrives while the wire answers the next page-0 window read (asked before it, landing after it)."""
    loop, answer = asyncio.get_running_loop(), wire._answer

    def _during(method, url):
        if "filter=unread" not in url:
            wire._answer = answer
            clock.t += 1
            asyncio.run_coroutine_threadsafe(events.handle_event(event), loop).result(10)
        return answer(method, url)
    wire._answer = _during


async def case_late_window_keeps_echo():
    wire = _Wire(window=[_row(F), _row(M)])
    with _world(wire) as (clock, noted):
        await _land_window([_row(F), _row(M)])
        _late(wire, _echo(F, 921), clock)
        out = await accounts_admin_api.rewarm_roster_count(A)
        assert wire.calls, "a live window read ran"
        assert out["owe_reply"] == 1 and _slot()["amber"] == 1, ("F not brought back", out, _slot())


async def case_late_window_keeps_dm():
    wire = _Wire(window=[_row(F), _row(M)])
    with _world(wire) as (clock, noted):
        await _land_window([_row(F), _row(M)])
        _late(wire, _dm(F, 931), clock)
        out = await accounts_admin_api.rewarm_roster_count(A)
        assert wire.calls, "a live window read ran"
        assert out["owe_reply"] == 1 and _slot()["amber"] == 1, ("the DM not hidden", out, _slot())


async def case_echo_keeps_debounced_bust():
    with _world(_Wire()) as (clock, noted):
        event_transcoder._last_out_bust.pop(A, None)
        await _land_window([_row(F), _row(M)])
        await _deliver(_echo(F, 941), clock)
        assert _slot()["amber"] == 1, _slot()
        await relay_cache.get_or_fetch("roster_count", A, (), ttl_seconds=300, fetcher=lambda: {"owe_reply": 1})
        await _deliver(_outbound(942), clock)
        assert relay_cache.peek("list_chats", A, _ROSTER_WINDOW_KEY) is None, "the existing bust drops the window"
        assert relay_cache.peek("roster_count", A, ()) is None, "...and the route's count"
        assert _slot()["amber"] == 1, ("published amber kept across the drop", _slot())
        await _land_window([_row(F), _row(M)])
        await _deliver(_outbound(943), clock)
        assert relay_cache.peek("list_chats", A, _ROSTER_WINDOW_KEY) is not None, "inside 20 s: no second bust"
        assert event_transcoder._OUT_BUST_DEBOUNCE_S == 20.0
        event_transcoder._last_out_bust.pop(A, None)


async def case_route_matches_after_echo():
    wire = _Wire(window=[_row(F), _row(K), _row(M, unread=1)])
    with _world(wire) as (clock, noted):
        assert (await accounts_admin_api.rewarm_roster_count(A))["owe_reply"] == 2
        calls = len(wire.calls)
        await _deliver(_echo(F, 951), clock)
        amber = _slot()["amber"]

        def _no_of():
            raise AssertionError("warm: no fetch")
        warm = await relay_cache.get_or_fetch("roster_count", A, (), ttl_seconds=300, fetcher=_no_of)
        assert amber == 1 and warm["owe_reply"] == amber, (amber, warm)
        assert accounts_admin_api._roster_last[A]["owe_reply"] == amber, accounts_admin_api._roster_last[A]
        assert (await accounts_admin_api._held_roster_count(A))["owe_reply"] == amber
        assert len(wire.calls) == calls, wire.calls


def _amber_fans() -> set:
    me, ids = accounts_admin_api._amber_ctx[A]
    held = _held_window()
    rows = unread_total_decide.overlay(held["list"], badge_reads.arrivals(A), held.get("asked_at"), me)
    return {r["withUser"]["id"] for r in rows if unread_total_decide.amber_count([r], me, ids, None)}


def _disjoint(step: str) -> None:
    view = badge_reads.unread_set(A)
    fans = _amber_fans()
    held = set() if view is None else set(view.fans)
    assert not fans & held, (step, fans, held)
    assert _slot()["amber"] == len(fans - held), (step, _slot(), fans, held)


async def case_no_fan_in_both():
    wire = _Wire(unread=[_row(F, unread=1)])
    with _world(wire) as (clock, noted):
        await _land_window([_row(F), _row(G)])
        await _frame(0)
        _disjoint("held")
        await _deliver(_dm(F, 961), clock)
        _disjoint("DM")
        clock.t += 10_000
        await _frame(1)
        await _tick_at(clock, clock.t + 1500)
        assert F in badge_reads.unread_set(A).fans
        _disjoint("set replace")
        steps: list = []

        class _InFlight(_Writer):
            def __getattr__(self, name):
                if name == "mark_chat_read":
                    return lambda fan: steps.append(_disjoint("mark read in flight")) or {}
                return super().__getattr__(name)
        clock.t += 1000
        with _routes(_InFlight(), clock):
            await server.of_mark_chat_read(F)
        assert steps == [None], steps
        assert _slot()["amber"] == 2 and F not in badge_reads.unread_set(A).fans, ("read: F owed", _slot())
        await _land_window([_row(F), _row(G)])
        _disjoint("after read")
        await _deliver(_echo(F, 962), clock)
        _disjoint("echo")
        assert _slot()["amber"] == 1, _slot()


async def _amber_moves(clock: _Clock) -> None:
    """Echo F, DM K, our mark read of M, our mark unread of G: amber 3 -> 2 -> 1 -> 2 -> 1."""
    me_last = {**_row(F), "lastMessage": {**_row(F)["lastMessage"], "fromUser": {"id": int(A)}}}
    await _land_window([_row(F), _row(K), _row(M, unread=1), _row(G)])
    assert _slot()["amber"] == 3, _slot()
    await _deliver(_echo(F, 971), clock)
    assert _slot()["amber"] == 2, ("echo", _slot())
    await _deliver(_dm(K, 972), clock)
    assert _slot()["amber"] == 1, ("DM", _slot())
    writer = _Writer()
    clock.t += 1000
    with _routes(writer, clock):
        await server.of_mark_chat_read(M)
        assert _slot()["amber"] == 2, ("our mark read", _slot())
        await _land_window([me_last, _row(K, unread=1), _row(M), _row(G)])
        clock.t += 1000
        await server.of_mark_chat_unread(G)
    assert _slot()["amber"] == 1, ("our mark unread", _slot())
    assert [c[0] for c in writer.calls] == ["mark_chat_read", "mark_chat_unread"], writer.calls


async def case_badge_reads_off_amber_still_moves():
    wire = _Wire(unread=[_row(K, unread=1)], window=[_row(K, unread=1)])
    with _world(wire, "off") as (clock, noted):
        assert not badge_reads.ENABLED and unread_total.ENABLED
        await _amber_moves(clock)
        await _frame(2)
        await _frame(5)
        await _tick_at(clock, clock.t + 20_000)
        assert wire.calls == [] and not badge_reads._reads, ("no badge read", wire.calls)


async def case_badge_reads_lean_amber_moves():
    wire = _Wire(unread=[_row(K, unread=1), _row(G, unread=1)])
    with _world(wire, "lean") as (clock, noted):
        assert badge_reads.ENABLED and badge_reads.GAP_MS == 15_000
        await _amber_moves(clock)
        wire.calls.clear()
        clock.t += 10_000
        await _frame(2)
        await _tick_at(clock, clock.t + 1500)
        first = len(wire.calls)
        assert first >= 1, ("a counter frame: one read", wire.calls)
        await _frame(3)
        await _tick_at(clock, clock.t + 5000)
        assert len(wire.calls) == first, ("inside the lean gap: no read", wire.calls)
        await _tick_at(clock, clock.t + 15_000)
        assert len(wire.calls) > first, ("past the gap: the held frame reads", wire.calls)
        assert _slot()["amber"] == 1, _slot()


def _wrow(fan: int, fan_last: bool) -> dict:
    return {"withUser": {"id": fan}, "hasUnread": False, "unreadMessagesCount": 0, "isMutedNotifications": False,
            "lastMessage": {"id": fan * 10, "fromUser": {"id": fan if fan_last else int(QA)}}}


class _QWire:
    """OF: `GET /chats` pages `window` (the page-0 window read); anything else fails the case."""
    def __init__(self, window: list):
        self.window, self.calls = window, []

    def _answer(self, method, url):
        u = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert method == "GET" and u.path == CHATS and "filter" not in q, (method, url)
        self.calls.append(q)
        off, lim = int(q["offset"]), min(int(q["limit"]), 10)     # OF answers at most 10 rows a page
        return _Resp(url, {"list": self.window[off:off + lim], "hasMore": off + lim < len(self.window)})

    def get(self, url, headers=None, timeout=None):
        return self._answer("GET", url)

    def request(self, method, url, json=None, headers=None, timeout=None):
        return self._answer(method, url)


def _of_client(wire: _QWire) -> OFClient:
    c = OFClient({"headers": {"user_id": QA, "x_bc": "bc", "x_of_rev": "rev", "user_agent": "ua"},
                  "signing": {"rules": {"static_param": "s", "start": "1", "end": "2",
                                        "checksum_indexes": [1], "checksum_constant": 1}},
                  "cookies": []})
    c._x_hash = "h"
    c.http = wire
    return c


_DEAD: set = set()
_HELD: dict = {}
_PROXY_DOWN: set = set()


@contextlib.contextmanager
def _qworld(wire: _QWire, knob: str | None = None, tabs=frozenset({QA})):
    """Both Knobs on, `BADGE_READS` = `knob`, modules reloaded (a restart), QA's client on `wire`, `tabs` the Open-tab
    Creators, the Relay clock fake, the Live connection up; `_DEAD` / `_PROXY_DOWN` / `_HELD` (exit hold seconds)
    drive eligibility; yields (clock, `badge_read` log lines)."""
    saved_env = {k: os.environ.get(k) for k in ("SHARED_REFRESHER", "UNREAD_TOTAL", "BADGE_READS")}
    os.environ.update({"SHARED_REFRESHER": "1", "UNREAD_TOTAL": "1"})
    if knob is None:
        os.environ.pop("BADGE_READS", None)
    else:
        os.environ["BADGE_READS"] = knob
    clock, lines = _Clock(), []

    class _Cap(logging.Handler):
        def emit(self, rec):
            msg = rec.getMessage()
            if msg.startswith("badge_read"):
                lines.append(msg)
    cap = _Cap()
    logger = logging.getLogger("of-relay.badge_reads")
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(cap)
    for m in (shared_refresher, unread_total, badge_reads):
        importlib.reload(m)
    client = _of_client(wire)
    orig = (server._load_client, events.open_tab_accounts, of_ws.connected_since, app_open_warm.exit_held_s,
            proxy_health.bad_reasons, proxies.get_for_account)
    server._load_client = lambda *_a, **_k: client
    events.open_tab_accounts = lambda: tabs
    badge_reads._clock = unread_total._clock = clock
    up = time.monotonic()
    for held in (_DEAD, _HELD, _PROXY_DOWN):
        held.clear()
    of_ws.connected_since = lambda aid: up
    shared_refresher.live = lambda aid: "dead" if aid in _DEAD else "up"
    app_open_warm.exit_held_s = lambda aid: _HELD.get(aid, 0.0)
    proxy_health.bad_reasons = lambda: {"px-down": "dead"} if _PROXY_DOWN else {}
    proxies.get_for_account = lambda aid: {"label": "px-down" if aid in _PROXY_DOWN else "px-ok"}
    event_transcoder._queue_finishes.clear()
    try:
        yield clock, lines
    finally:
        logger.removeHandler(cap)
        logger.setLevel(level)
        (server._load_client, events.open_tab_accounts, of_ws.connected_since, app_open_warm.exit_held_s,
         proxy_health.bad_reasons, proxies.get_for_account) = orig
        for ns in ("list_chats", "roster_count"):
            relay_cache.invalidate(ns, QA)
        server._chats_window_fetched_at.pop(QA, None)
        accounts_admin_api._roster_last.pop(QA, None)
        event_transcoder._queue_finishes.clear()
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in (shared_refresher, unread_total, badge_reads):
            importlib.reload(m)


def _fin(qid: int, total: int = 23, **kw) -> dict:
    return {"id": qid, "date": "2026-11-23T10:00:00+00:00", "isReady": True, "isDone": True, "total": total,
            "pending": 0, "isCanceled": False, **kw}


async def _finish(qid: int, total: int = 23, **kw) -> None:
    await event_transcoder.transcode({"__account_id": QA, "chat_queue_finish": _fin(qid, total, **kw)})


def _queue_calls() -> int:
    return sum(n for caller, _path, aid, _s, n in of_call_counter.snapshot()["rows"]
               if caller == "walk:badge_queue" and aid == QA)


WINDOW = [_wrow(5000 + i, fan_last=False) for i in range(25)]
READS = 3   # the 25-row window in OF's 10-row pages


async def case_queue_finish_rereads_once():
    wire = _QWire(WINDOW)
    with _qworld(wire) as (clock, lines):
        t, before = clock.t, _queue_calls()
        await _finish(1)
        await _tick_at(clock, t)
        assert len(wire.calls) == READS and all(q["offset"] in ("0", "10", "20") for q in wire.calls), wire.calls
        assert _queue_calls() - before == READS, "of_call_stats counts it as walk:badge_queue"
        assert lines == [f"badge_read account={QA} kind=queue calls=3 rows=25 counter=- complete=- mismatch=- "
                         "flips=- restricted=-"], lines
        await _finish(1)                                       # OF re-sends the finish
        await _finish(2, total=4)                              # a hand-send
        await _finish(3, total=23, isCanceled=True)
        await _tick_at(clock, t + 60_000)
        assert len(wire.calls) == READS and len(lines) == 1, (wire.calls, lines)

    # [case, make it ineligible, knob, reads once it clears: a hold waits, the others drop the ask]
    for name, setup, knob, after in (
        ("off", lambda tabs: None, "off", 0),
        ("no Open tab", lambda tabs: tabs.discard(QA), None, 0),
        ("Dead session", lambda tabs: _DEAD.add(QA), None, 0),
        ("proxy down", lambda tabs: _PROXY_DOWN.add(QA), None, 0),
        ("429 exit hold", lambda tabs: _HELD.__setitem__(QA, 30.0), None, READS),
    ):
        wire, tabs = _QWire(WINDOW), {QA}
        with _qworld(wire, knob=knob, tabs=tabs) as (clock, lines):
            setup(tabs)
            await _finish(1)
            for dt in (0, 1000, 6000):
                await _tick_at(clock, clock.t + dt)
            assert wire.calls == [] and lines == [], (name, wire.calls, lines)
            assert knob != "off" or not badge_reads._queued, "off refuses the ask itself"
            tabs.add(QA)
            _DEAD.clear(), _PROXY_DOWN.clear(), _HELD.clear()
            await _tick_at(clock, clock.t + 6000)
            await _tick_at(clock, clock.t + 6000)
            assert len(wire.calls) == after, (name, "once it clears", wire.calls)

    wire = _QWire(WINDOW[:12])                                   # a short window: 2 pages
    with _qworld(wire, knob="lean") as (clock, lines):
        t = clock.t
        await _finish(1)
        await _tick_at(clock, t)
        await _finish(2)
        await _tick_at(clock, t + 1000)
        await _tick_at(clock, t + 14_999)
        assert len(wire.calls) == 2, ("lean: the second finish waits its 15 s gap", wire.calls)
        await _tick_at(clock, t + 15_000)
        assert len(wire.calls) == 4 and all(" calls=2 rows=12 " in x for x in lines) and len(lines) == 2, (
            wire.calls, lines)

    wire = _QWire(WINDOW)
    with _qworld(wire) as (clock, lines):
        t = clock.t
        with badge_reads._lock:
            badge_reads._gates[QA] = badge_reads_decide.Gate(last_start=t - 1000)
        await _finish(1)
        await _tick_at(clock, t)
        await _tick_at(clock, t + 3999)
        assert wire.calls == [] and QA in badge_reads._queued, ("the gap Attribution reads set is shared", wire.calls)
        assert not badge_reads._gates[QA].pending, "a waiting queue ask re-asks no Attribution read"
        await _tick_at(clock, t + 4000)
        assert len(wire.calls) == READS and len(lines) == 1 and QA not in badge_reads._queued, (wire.calls, lines)

    wire = _QWire(WINDOW)
    with _qworld(wire) as (clock, lines):
        t = clock.t
        await _finish(1)
        await _tick_at(clock, t)
        await _finish(2)
        await _finish(3)
        for dt in (1000, 2000, 4999):
            await _tick_at(clock, t + dt)
        assert len(wire.calls) == READS, ("two finishes inside the gap wait", wire.calls)
        await _tick_at(clock, t + 5000)
        await _tick_at(clock, t + 10_000)
        assert len(wire.calls) == 2 * READS and len(lines) == 2, ("one follow-up for both", wire.calls, lines)

    wire = _QWire(WINDOW)
    with _qworld(wire) as (clock, lines):
        t = clock.t
        with badge_reads._lock:
            badge_reads._gates[QA] = badge_reads_decide.Gate(pending=True)     # an Attribution ask waiting
        await _finish(1)
        orig_read = badge_reads._read
        kinds: list = []

        async def _attribution(aid, kind):
            kinds.append(kind)
        badge_reads._read = _attribution
        try:
            await _tick_at(clock, t)
            assert kinds == ["frame"] and wire.calls == [], ("the Attribution read goes first", kinds, wire.calls)
            badge_reads._gates[QA] = replace(badge_reads._gates[QA], pending=True)
            await _tick_at(clock, t + 5000)
            assert kinds == ["frame"] and len(wire.calls) == READS, ("then the queue read", kinds, wire.calls)
        finally:
            badge_reads._read = orig_read


async def case_mass_clears_amber():
    owed = [_wrow(6000 + i, fan_last=True) for i in range(4)]
    rest = [_wrow(6100 + i, fan_last=False) for i in range(21)]
    answered = [_wrow(6000 + i, fan_last=False) for i in range(4)]
    wire = _QWire(owed + rest)
    with _qworld(wire) as (clock, lines):
        held = await accounts_admin_api._compute_roster_count_of(QA, bypass=True)
        assert held["owe_reply"] == 4 and unread_total.snapshot(QA)["amber"] == 4, (held, unread_total.snapshot(QA))
        wire.window, wire.calls = answered + rest, []
        await _finish(1)
        await _tick_at(clock, clock.t)
        assert len(wire.calls) == READS, wire.calls
        assert unread_total.snapshot(QA)["amber"] == 0, ("the re-read's fold publishes amber 0", unread_total.snapshot(QA))
        after = await accounts_admin_api._compute_roster_count_of(QA)
        assert after["owe_reply"] == 0 and len(wire.calls) == READS, (after, wire.calls)


async def case_send_clears_amber_before_echo():
    with _world(_Wire(), "off") as (clock, _), _routes(_Writer(), clock), _quiet_hooks():
        await _land_window([_row(F)])
        await server.send_message(None, F, server.SendMessageBody(text="answered"))
        assert _slot()["amber"] == 0, _slot()
        assert _held_window() is None


async def case_restrict_ack_hide_clears_amber():
    writer = _Writer()
    with _world(_Wire(), "off") as (clock, _), _routes(writer, clock), _quiet_hooks():
        await _land_window([_row(F), _row(M)])
        async with _unrestricted_after(F):
            result = await server.of_restrict_user(F, request=None, ack=True, hide=True)
            assert result["acked"] and result["hidden"], result
            assert _slot()["amber"] == 1, _slot()


async def case_restrict_hide_removes_cached_row():
    with _world(_Wire()) as (clock, _), _routes(_Writer(), clock):
        await _land_window([_row(F), _row(M)])
        async with _unrestricted_after(F):
            assert (await server.of_restrict_user(F, request=None, ack=False, hide=True))["hidden"]
            held = _held_window()
            assert held is None or F not in {r["withUser"]["id"] for r in held["list"]}, held
            assert _slot()["amber"] == 1, _slot()
            await _land_window([_row(M)])
            await server.of_unrestrict_user(F, request=None, unhide=True)
            assert _held_window() is None


async def case_unhide_then_page0_get_restores_amber():
    class Writer(_Writer):
        user_id = ME

        def list_chats(self, **kw):
            return _Client([_row(F), _row(M)]).list_chats(**kw)

    with _world(_Wire()) as (clock, _), _routes(Writer(), clock):
        await _land_window([_row(F), _row(M)])
        assert _slot()["amber"] == 2, _slot()
        async with _unrestricted_after(F):
            await server.of_restrict_user(F, request=None, ack=False, hide=True)
            await server.of_unrestrict_user(F, request=None, unhide=True)
            assert _held_window() is None and _slot()["amber"] == 1, _slot()
            await server.list_chats(limit=25, offset=0, order="recent", filter=None, list_id=None,
                                    query=None, search=None, refresh=False)
            assert _slot()["amber"] == 2, _slot()

async def case_late_reply_keeps_newer_fan_row():
    with _world(_Wire(), "off") as (clock, _):
        row = _row(F)
        row["lastMessage"]["createdAt"] = _iso(clock.t + 5000)
        await _land_window([row])
        assert _slot()["amber"] == 1, _slot()
        read_flip.after_reply(A, F, clock.t)
        assert _held_window()["list"] == [row] and _slot()["amber"] == 1, (_held_window(), _slot())

async def case_lift_corrects_newer_attribution_row():
    wire = _Wire(unread=[{**_row(F, unread=1), "canSendMessage": False, "canNotSendReason": "muted"}])
    with _world(wire) as (clock, _), _routes(_Writer(), clock):
        await _land_window([_row(F, unread=1)])
        async with _unrestricted_after(F):
            await server.of_restrict_user(F, request=None, ack=False, hide=False)
            clock.t += 1000
            await badge_reads._read(A, "frame")
            assert badge_reads.restricted_unread(A) == 1
            await server.of_unrestrict_user(F, request=None, unhide=False)
            assert badge_reads.restricted_unread(A) == 0


async def case_same_ms_unread_wins_over_read():
    with _world(_Wire(), "off") as (clock, _), _routes(_Writer(), clock):
        await _land_window([_row(F)])
        badge_reads.note_arrival(A, F, unread_total_decide.READ, clock.t)
        await server.of_mark_chat_unread(F)
        assert _slot()["amber"] == 0, _slot()


async def case_reply_before_first_amber_fold():
    row = _row(F)
    row["lastMessage"]["fromUser"]["id"] = ME
    wire = _Wire(window=[row])
    with _world(wire) as (clock, _):
        client = server._load_client(A)
        client.user_id = str(ME)
        with _routes(client, clock), _quiet_hooks():
            await server.list_chats(limit=25, offset=0, order="recent", filter=None, list_id=None,
                                    query=None, search=None, refresh=False)
        accounts_admin_api._amber_ctx.pop(A, None)
        read_flip.after_reply(A, F, clock.t)
        sender = _held_window()["list"][0]["lastMessage"]["fromUser"]["id"]
        folded = await accounts_admin_api._held_roster_count(A)
        assert (sender, folded["owe_reply"], _slot()["amber"]) == (ME, 0, 0)


async def case_manual_refresh_publishes_amber():
    wire = _Wire(window=[_row(F)])
    with _world(wire) as (clock, _):
        await _land_window([_row(F), _row(M)])
        client = server._load_client(A)
        loads = []
        server._load_client = lambda aid: loads.append(aid) or client
        with _routes(client, clock), _quiet_hooks():
            await server.list_chats(limit=25, offset=0, order="recent", filter=None, list_id=None,
                                    query=None, search=None, refresh=True)
        assert wire.calls and _slot()["amber"] == 1 and not loads, (wire.calls, _slot(), loads)


async def case_rejected_window_keeps_muted_amber():
    wire = _Wire(window=[_row(F)])
    with _world(wire) as (clock, _), _routes(_Writer(), clock):
        await accounts_admin_api.rewarm_roster_count(A)
        wire.calls.clear()
        stamp = _slot()["amber_at"]
        loop, answer = asyncio.get_running_loop(), wire._answer

        def during_mute(method, url):
            wire._answer = answer
            asyncio.run_coroutine_threadsafe(server.of_mute_chat(F), loop).result(10)
            return answer(method, url)

        wire._answer = during_mute
        out = await accounts_admin_api.rewarm_roster_count(A)
        assert wire.calls and out["owe_reply"] == 0 and _slot()["amber"] == 0, (out, _slot())
        assert out["as_of"] == _slot()["amber_at"] == stamp, (out, _slot(), stamp)


async def case_read_write_keeps_inflight_dm():
    with _world(_Wire(), "off") as (clock, _):
        await _land_window([_row(F, unread=1)])
        loop = asyncio.get_running_loop()

        class Writer(_Writer):
            def mark_chat_read(self, fan):
                asyncio.run_coroutine_threadsafe(_deliver(_dm(fan, 951), clock), loop).result(10)
                clock.t += 1
                return {}

        clock.t += 1
        with _routes(Writer(), clock):
            await server.of_mark_chat_read(F)
        assert _slot()["amber"] == 0, _slot()


_harness.run()
