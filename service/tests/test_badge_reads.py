#!/usr/bin/env python3
"""Badge reads, the shell (creator-badges phase 0C), through `events.handle_event` with real `chat_messages` frames,
a real `OFClient` on a fake wire serving `/chats?filter=unread` (OF's Unread list) and failing anything else, the
Relay clock injected (`badge_reads._clock`), the loop driven by `badge_reads.tick()`, `events.publish` captured.

  case_onlyfans_read_flips_dot:  held window with F unread, frame 11 -> 10, nothing to explain it -> no read before
                                 1.5 s, then exactly one `filter=unread` call as `walk:badge_attribution`;
                                 `chat_read_changed {F, 0}` at the ask time, F's held row patched, the other
                                 `list_chats` entries dropped, one exact `badge_read` line; a Creator with no Open
                                 tab -> 0 reads; the OF counter appears in no publish.
  case_deep_fan_flips_dot:       G past the window (row 30): the first read only builds the set (no off-window flip);
                                 a later Complete list without him -> `chat_read_changed {G, 0}`, window untouched.
  case_same_value_frame_reads:   a frame with the value unchanged -> one read; F read in the window and in the list
                                 -> `{F, 1}`.
  case_incomplete_list_never_reads_fans: counter 35, two full pages with `hasMore` -> 2 calls, no (fan, 0); a page-2
                                 error, a page-2 429 past paced's one retry (kept on the read for the exit hold) or a
                                 duplicate-only page -> partial, no (fan, 0); no further page, 0 rows, counter 1 ->
                                 `mismatch=1`, no flip.
  case_one_page_read_waits_for_the_trailing_frame: F read on OF, the list already without him, his counter frame
                                 landing 0.3 s after the answer -> judged by it: complete, `{F, 0}`; no frame within
                                 1 s -> `mismatch=1`, never complete; a matching frame not after the ask
                                 (`newer_than_ask`) -> `mismatch=1`; two pages (page 2 shifted empty) -> no wait.
  case_one_frame_during_the_read_judges_it: F read on OF, his counter frame landing while page 1 is in flight, the
                                 list matching it -> complete at once, `{F, 0}`; two frames mid-read, or one the list
                                 is off by, or two pages -> incomplete, no flip.
  case_gap_and_cap_full_and_lean: 10 frames in 3 s -> one read and exactly one follow-up >= 5 s later (lean 15 s);
                                 200 frames over a fake hour -> 120 reads and one `badge_read_capped` line; page 1
                                 held 1.3 s past the admit (the pacer) -> OF still sees starts >= the gap apart.
  case_429_holds_exit:           a terminal 429 on page 2 (kept on the read) or page 1 -> the exit held
                                 (`app_open_warm.exit_held_s` > 0); the next frame reads nothing until it ends; each
                                 read, failed or not, is noted on the exit queue once (`note_read`).
  case_switch_off_and_lean:      `BADGE_READS=off` -> 0 list calls on 20 unexplained frames, the Red circle still
                                 follows the counter, an echo flips nothing, `?bust=` answers the held fold at 0
                                 calls; a bogus value -> `full` with one warning, empty -> `full` silently;
                                 UNREAD_TOTAL off -> inert.
  case_restricted_unread_feeds_red: a registry fan past window row 25 in a Complete list -> R 1 (`set_restricted_unread`
                                 at the ask time, `note_values` poked), Phase B's red = counter - 1, `restricted=1`.
  case_muted_dm_keeps_restricted: a DM + same-value frame from a muted registry fan (held row muted, or muted through
                                 `relay_hooks.mute`) -> 0 list calls, R unchanged.
  case_newer_dm_survives_read:   a DM landing while a read is in flight whose answer lacks that fan -> he stays in
                                 `unread_set`.
  case_explained_frames_cost_nothing: an ordinary Inbound DM 0.4 s before a frame, a `chatUserId` echo 1 s before
                                 one, an `Outbound` echo 1 s after one -> 0 list calls each; an unexplained frame
                                 later -> one read; `on_frame` given malformed events never raises; each Write intent
                                 site with its frame delivered before the write returns -> 0 list calls: mark read, mark
                                 unread, mark all read (explains frames until 1.5 s after its response), mute, unmute
                                 routes, `full_ai_live` and `welcome_chatter_for_info` mark-read; a landed read / unread
                                 moves the Unread set.
  case_echo_branch_flips_read:   a Creator echo for unread F -> `chat_read_changed {F, 0}` at the echo's arrival before
                                 any tick, F's held row patched read, `unread_set` drops F, its frame 0 OF calls; an echo
                                 for a read Fan outside the set publishes nothing; one for a Fan past the window but in
                                 the set -> `{fan, 0}`, window untouched; no `creator_echo` hook.
  case_ineligible_creators_read_nothing: through the refresher's real `live`: no Open tab, Dead session, proxy down ->
                                 0 reads on unexplained frames and no socket-down poll; the latter two carry Grey
                                 `dead` / `proxy_down`; the session back -> its next frame reads, the cause gone; the
                                 proxy check raising -> the last answer stands, reads go on, one check per 5 s.
  case_socket_down_polls_15s:    `connected_since` None on an eligible Creator -> a `kind=poll` read every 15 s from 15 s
                                 after the drop (lean too), none after reconnect; no socket expected (`live` None) or a
                                 blip under 15 s -> none; a live `/users/me` mid-outage keeps the poll's confirmation; a Complete poll -> slot `grey` null, `n` = `of_counts` rows -
                                 R (the counter from before the drop plays no part); polls failing for 45 s -> `stale` on the refresher's 5 s re-read, no frame, one
                                 republish (Badge version +1) and none while unchanged; an incomplete poll -> stays
                                 grey; a two-hour outage -> <= 120 reads in any 3600 s, `capped` while capped and
                                 cleared by the next admitted poll.
  case_fold_rescores_from_set:   a set held -> a roster-counts fold writes R from the set (rows from a newer window,
                                 the registry as loaded): restricted here or on OF -> excluded at that fold,
                                 unrestricted -> counts again, an older window leaves a row; no set -> R from the window.
  case_hover_cooldown_shared:    the owner and a Chatter `?bust=` A 5 s apart -> 1 window read, the second answered
                                 from the held fold; 31 s later -> a second read; two concurrent busts while the
                                 read's wire is held -> 1 read, both answers equal, the page-0 entry fresh after;
                                 each read one `kind=hover` line; hover reads leave the Attribution gate (and its
                                 hourly cap) untouched. A failing window read: leader and follower get equal zeros,
                                 a bust 5 s later is held at 0 calls, no `kind=hover` line. UNREAD_TOTAL off: every
                                 bust reads, as before the cooldown, no line.
  case_failed_write_retires_intent: a mark-read route whose OF write errors, then an unrelated frame -> one list call.
Run: ./venv/bin/python service/tests/test_badge_reads.py
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
events_persist.enqueue = lambda *_a, **_k: None     # the event_inbox write is not under test
of_pacing.PAGE_GAP_S, of_pacing.JITTER_S = 0.0, 0.0


class _Resp:
    def __init__(self, url, status, body, headers=None):
        self.url, self.status_code, self.ok = url, status, 200 <= status < 300
        self.text, self.headers = json.dumps(body), headers or {}

    def json(self):
        return json.loads(self.text)


class _Wire:
    """OF: `GET /chats?filter=unread` pages `unread` by offset/limit (`more` forces `hasMore`); `page2` overrides
    the offset-10 answer, `fail` every answer ((status, body[, headers])); `me` set: `/users/me` answers that
    `chatMessagesCount` (not in `calls`). With `window` set, `GET /chats` with no filter pages it (the page-0 window
    read), waiting on `hold` when set, `fail` answering it too. Anything else fails the case. `calls`: (path, query)
    per request; `at`: the Relay clock at each."""
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


_LOG: list = []     # every badge_reads log message of the current world, its import included
_DOWN: set = set()  # the Creators whose Live connection is down (`of_ws.connected_since` None)
_DEAD: set = set()
_UNPUMPED: set = set()


@contextlib.contextmanager
def _world(wire: _Wire, tabs=frozenset({A}), knob: str | None = None, unread: bool = True, real_live: bool = False):
    """Both Knobs on (`unread` False: UNREAD_TOTAL off), `BADGE_READS` = `knob` (None: unset), modules reloaded (a
    restart), A's client on `wire`, `tabs` the Open-tab Creators, the Relay clock fake, the Live connection up but for
    `_DOWN`; the refresher's `live` "up" / "down" from `_DOWN` ("dead" for `_DEAD`, None for `_UNPUMPED`) unless
    `real_live` (then the case drives `shared_refresher.tick`); yields (clock, published, badge_read log lines)."""
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


async def _hold_window(rows: list, aid=A) -> None:
    relay_cache.invalidate("list_chats", aid)
    await relay_cache.get_or_fetch("list_chats", aid, _ROSTER_WINDOW_KEY, ttl_seconds=600,
                                   fetcher=lambda: {"list": rows, "hasMore": False})


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
    """The loop's tick at Relay time `t`, then the read it started (if any) run to its end."""
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
        await _frame(77, aid=B)                     # B: no Open tab
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


async def case_gap_and_cap_full_and_lean():
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
        assert len(_starts(wire)) == 120 and len(lines) == 120, len(_starts(wire))
        assert [m for m in _LOG if m.startswith("badge_read_capped")] == [f"badge_read_capped account={A}"], _LOG
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
    """`app_open_warm.note_read` recorded (the exit queue's "a read started here")."""
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
            await _frame(35)
            await _tick_at(clock, clock.t + 1500)
            assert wire.calls == [], (why, "no read while the exit is held", wire.calls)
            await asyncio.sleep(app_open_warm.exit_held_s(A) + 0.05)
            await _tick_at(clock, clock.t + 1000)
            assert len(wire.calls) == 2, (why, "the held frame's read, after the hold", wire.calls)
            assert noted == [A, A], (why, "one note_read per read", noted)


async def case_switch_off_and_lean():
    wire = _Wire(unread=[_row(F)])
    with _world(wire, knob="off") as (clock, pub, lines):
        await _hold_window([_row(F)])
        await events.handle_event(_echo(F, 1))
        assert _flips(pub) == [] and _window()[0]["hasUnread"] is True, ("off: an echo flips nothing", pub)
        with _busting(wire) as bust:
            server._chats_window_fetched_at[A] = server._time_mod.monotonic()
            assert A in await bust(_User()) and wire.calls == [], ("off: ?bust= serves held, 0 calls", wire.calls)
        unread_total.set_restricted_unread(A, 0, 0)
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
    """One frame and its read: the Unread set held from the wire's list."""
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
            assert unread_total._r[A] == (1, clock.t), ("R at the read's ask time", unread_total._r[A])
            assert unread_total.snapshot(A)["n"] == 9, ("red = counter - R", unread_total.snapshot(A))
            assert lines[-1].endswith("complete=1 mismatch=0 flips=0 restricted=1"), lines
            view = badge_reads.unread_set(A)
            assert view.fans == frozenset([RF] + [2000 + i for i in range(9)]) and view.asked_at == clock.t, view
            importlib.reload(badge_reads)
            assert badge_reads.unread_set(A) is None, "a restart holds no set"


async def case_muted_dm_keeps_restricted():
    import relay_host
    wire = _Wire(unread=[_row(RF)])
    async with _registry(RF, MF, MF2):
        with _world(wire) as (clock, _pub, _lines), _swap(relay_host, "request_account_header", lambda: A):
            await _hold_window([_row(MF, unread=False, muted=True)])
            await _seed(clock, 1)
            assert badge_reads.restricted_unread(A) == 1
            relay_hooks.fire_mute(MF2, True)
            for fan, mid in ((MF, 1), (MF2, 2)):
                wire.calls.clear()
                clock.t += 6000
                await events.handle_event(_dm(fan, fan * 10 + mid))
                await _frame(1)
                await _tick_at(clock, clock.t + 1500)
                assert wire.calls == [], (fan, "a DM explains its frame: 0 list calls", wire.calls)
                assert badge_reads.restricted_unread(A) == 1, (fan, badge_reads.restricted_unread(A))
                assert fan not in badge_reads.unread_set(A).fans


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
        await _frame(1)
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
    """`shared_refresher.tick()` (its 5 s loop) with its `/users/me` jobs dropped: only its re-read and publish."""
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
        t = clock.t = int(time.time() * 1000) - 100_000      # the polls asked before the live /users/me below
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
        assert worst <= 120 and len(starts) >= 200, (worst, len(starts))
        capped = [at for at, g in grey if g == "capped"]
        assert capped, "capped while the cap is spent"
        after = [s for s in starts if s > capped[0]]
        assert after and all(g != "capped" for at, g in grey if after[0] <= at < after[0] + 5000), grey[-5:]


class _User:
    account_ids = list(_CREATORS)


@contextlib.contextmanager
def _roster(wire: _Wire):
    """roster-counts as the owner, A's client on `wire`, A unleased: its held window folded at 0 OF calls."""
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
        server._chats_window_fetched_at[A] = server._time_mod.monotonic() + ahead_s
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
        writes.append((aid, r))
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
                    assert unread_total._r[A] == (1, badge_reads._sets[A].as_of), \
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
    """`?bust=A` as the given principal (the owner `_User` or a `_Chatter`), A's client on `wire`; yields the call,
    which answers `counts`."""
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
    """OF's read-state writes on a fake client: each delivers counter frame `n` through `events.handle_event` before
    it returns (the frame beats the response); `fail` raises an OF error instead, no frame."""
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
    """The relay's routes as A on `writer`, read_flip's pre-write time on the Relay clock."""
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


_harness.run()
