#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402

from dataclasses import replace  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import badge_reads_decide as d  # noqa: E402
import unread_total_decide as utd  # noqa: E402
from badge_reads_decide import DmIn, Echo, Gate, Intent, ReadDone, Start, UnreadDone, Wait  # noqa: E402

T0 = 1_800_000_000_000
F, G, H = 501, 502, 503


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def _row(fan: int, unread: bool = True, muted=False, at: int = T0 - 60_000, **kw) -> dict:
    r = {"withUser": {"id": fan}, "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0,
         "lastMessage": {"id": fan * 10, "createdAt": _iso(at)}, **kw}
    if muted is not None:
        r["isMutedNotifications"] = muted
    return r


def _rows(n: int, start: int = 1000) -> list:
    return [_row(start + i) for i in range(n)]


def case_explained():
    def explain(at, dms, echoes, intents):
        return d.explain(d.CounterFrame(at, None),
                         [d.Activity(t, None, None) for t in dms],
                         [d.Activity(t, None, None) for t in echoes], intents)

    assert not explain(T0, (), (), ())[0]
    for window, is_dm in ((d.DM_WINDOW_MS, True), (d.ECHO_WINDOW_MS, False)):
        for dt in (-window - 1, -window, window, window + 1):
            near = (T0 + dt,)
            assert explain(T0, near if is_dm else (), () if is_dm else near, ())[0] == (abs(dt) <= window)
    live, gone = Intent(1, F, T0 - 100), Intent(2, F, T0 - 6000)
    assert explain(T0, (), (), (live,))[0] and not explain(T0, (), (), (gone,))[0]
    assert not explain(T0, (), (), (Intent(3, F, T0 - 100, retired=True),))[0]
    ok, _dms, _echoes, left = explain(T0, (), (), (live,))
    assert ok and not explain(T0 + 10, (), (), left)[0]
    every = (Intent(4, None, T0 - 100),)
    ok1, _dms, _echoes, every = explain(T0, (), (), every)
    assert ok1 and explain(T0 + 10, (), (), every)[0]
    ok, _dms, _echoes, kept = explain(T0, (T0 - 100,), (), (live,))
    assert ok and kept == (live,)

    for kind, delta, expected, want in (
        ("echo", -1, 0, False),
        ("dm", -1, 0, False),
        ("dm", 1, 1, True),
        ("echo", -1, -1, True),
        ("dm", -1, None, True),
        ("echo", None, 0, True),
    ):
        event = (d.Activity(T0 - 200, F, expected),)
        assert d.explain(d.CounterFrame(T0, delta), event if kind == "dm" else (),
                         event if kind == "echo" else (), ())[0] is want

    two = (Intent(5, G, T0 - 50), Intent(6, F, T0 - 100))
    _ok, _dms, _echoes, spent = explain(T0, (), (), two)
    assert [i.used for i in spent] == [False, True], ("the oldest live intent is spent first", spent)


def case_activity_explains_one_frame():
    for delta in (-1, None):
        echo = (d.Activity(T0 - 200, F, delta),)
        ok, _dms, spent, _i = d.explain(d.CounterFrame(T0, -1), (), echo, ())
        assert ok and not d.explain(d.CounterFrame(T0 + 100, -1), (), spent, ())[0], (delta, "one echo, one frame")
    dm = (d.Activity(T0 - 100, F, 1),)
    ok, spent, _e, _i = d.explain(d.CounterFrame(T0, None), dm, (), ())
    assert ok and not d.explain(d.CounterFrame(T0 + 100, None), spent, (), ())[0], "a DM explains one frame"
    both = (d.Activity(T0 - 100, None, None), d.Activity(T0 - 50, F, -1))
    _ok, _dms, left, _i = d.explain(d.CounterFrame(T0, -1), (), both, ())
    assert [a.used for a in left] == [False, True], ("a known match is spent before an unknown one", left)
    ok, _dms, left, _i = d.explain(d.CounterFrame(T0 + 100, 1), (), left, ())
    assert ok and all(a.used for a in left), "the unknown one explains the next frame"


def case_gate():
    full, lean = d.GAP_MS["full"], d.GAP_MS["lean"]
    assert (full, lean) == (5000, 15000)
    g, v = d.admit(Gate(), T0, full, 0.0)
    assert v == Start() and g.in_flight and g.last_start == T0 and not g.pending, (g, v)
    g, v = d.admit(g, T0 + 9000, full, 0.0)
    assert isinstance(v, Wait) and g.pending and g.in_flight, ("in flight: pending", g, v)
    g, v = d.admit(g, T0 + 9500, full, 0.0)
    assert isinstance(v, Wait) and g.pending, ("a second ask in flight: still one pending", g, v)
    g = d.done(g)
    assert not g.in_flight and g.pending, g
    g, v = d.admit(g, T0 + 10_000, full, 0.0)
    assert v == Start() and not g.pending and g.last_start == T0 + 10_000, ("exactly one follow-up", g, v)
    g = d.done(g)
    for gap in (full, lean):
        got, v = d.admit(g, T0 + 10_000 + gap - 1, gap, 0.0)
        assert v == Wait(T0 + 10_000 + gap) and got.pending and not got.in_flight, (gap, got, v)
        got, v = d.admit(got, T0 + 10_000 + gap, gap, 0.0)
        assert v == Start(), (gap, v)
    for gap in (full, lean):
        paced, _v = d.admit(Gate(), T0, gap, 0.0)
        paced = d.done(paced, T0 + 1300)
        _got, v = d.admit(paced, T0 + gap, gap, 0.0)
        assert v == Wait(T0 + 1300 + gap), ("the gap counts from page 1's send", gap, v)
        for sent in (None, T0 - 1):
            _got, v = d.admit(d.done(d.admit(Gate(), T0, gap, 0.0)[0], sent), T0 + gap, gap, 0.0)
            assert v == Start(), ("no later send time: from the admit", gap, sent, v)
    got, v = d.admit(g, T0 + 60_000, full, 2.5)
    assert v == Wait(T0 + 62_500) and got.pending and not got.in_flight, ("exit held", got, v)
    g, t = Gate(), T0
    for _ in range(120):
        g, v = d.admit(g, t, full, 0.0)
        assert v == Start(), (t, v)
        g, t = d.done(g), t + full
    got, v = d.admit(g, t - 1, full, 0.0)
    assert v == Wait(t) and got.pending, ("121st inside the gap waits for the gap only", got, v)
    g, v = d.admit(got, t, full, 0.0)
    assert t - T0 < 3_600_000 and v == Start() and g.in_flight and not g.pending, ("121st in the hour", g, v)


def case_gate_queue_fairness():
    gap = d.GAP_MS["full"]
    for gate, now, hold, ask, queued, verdict, pending in (
        (Gate(), T0, 0, True, True, Start(), False),
        (Gate(), T0, 0, False, True, Start(queue=True), False),
        (Gate(last_start=T0, queue_next=True), T0 + gap - 1, 0, True, True, Wait(T0 + gap), True),
        (Gate(queue_next=True), T0, 2, True, True, Wait(T0 + 2000), True),
        (Gate(queue_next=True), T0, 0, True, True, Start(queue=True), True),
        (Gate(pending=True), T0, 0, False, False, Start(), False),
        (Gate(), T0, 2, False, True, Wait(T0 + 2000), False),
    ):
        actual, decision = d.admit(gate, now, gap, hold, attribution=ask, queued=queued)
        assert (decision, actual.pending) == (verdict, pending)
        assert actual.queue_next == (queued and decision == Start() or isinstance(decision, Wait) and gate.queue_next)


def case_complete():
    friends = {"canSendMessage": False, "canNotSendReason": "only_friends"}
    rows = [
        (_rows(3), False, False, 3, 0, True, False, "no further page, rows = counter"),
        (_rows(3), False, False, None, 0, True, False, "no further page, counter unknown"),
        ([], False, False, 1, 0, False, True, "no further page, 0 rows, counter 1"),
        (_rows(20), True, False, 35, 0, False, False, "two full pages with hasMore, counter 35"),
        (_rows(12), False, True, 12, 0, False, False, "partial (page-2 429 / duplicate-only page)"),
        (_rows(3), False, False, 3, 2, False, False, "two frames since the ask can cancel out"),
        (_rows(3) + [_row(9, **friends)], False, False, 4, 0, True, False, "only_friends counts"),
        (_rows(3) + [_row(9, canSendMessage=False, canNotSendReason="chat_unavailable")], False, False, 3, 0,
         True, False, "a row OF's counter leaves out"),
        (_rows(3) + [_row(9, muted=True)], False, False, 3, 0, True, False, "a muted row is not counted"),
        (_rows(3), False, False, 4, 0, False, True, "no further page, count below the counter"),
        (_rows(20), True, False, None, 0, False, False, "more pages, counter unknown"),
    ]
    for got_rows, more, partial, counter, since, want, mis, why in rows:
        assert d.complete(got_rows, more, partial, counter, since, 1) is want, (why, "complete")
        assert d.mismatch(got_rows, more, partial, counter, since, 1) is mis, (why, "mismatch")
    assert d.FRAME_LAG_MS == 1000
    for got_rows, more, partial, counter, calls, want, mis, why in (
        (_rows(3), False, False, 3, 1, True, False, "one page, one frame, counts match: complete"),
        (_rows(3), False, False, 4, 1, False, True, "one page, one frame, off by one: mismatch"),
        (_rows(3), False, False, 3, 2, False, False, "two pages can drop a row"),
        (_rows(3), True, False, 3, 1, False, False, "more pages behind"),
        (_rows(3), False, True, 3, 1, False, False, "partial"),
        (_rows(3), False, False, None, 1, False, False, "counter unknown (poll)"),
    ):
        assert d.complete(got_rows, more, partial, counter, 1, calls) is want, (why, "complete")
        assert d.mismatch(got_rows, more, partial, counter, 1, calls) is mis, (why, "mismatch")
    for calls, mis, want in ((1, True, True), (2, True, False), (1, False, False), (2, False, False)):
        assert d.settles(calls, mis) is want, (calls, mis)
    for counted, counter, frame_at, want, why in (
        (10, 10, T0 + 1, True, "matching frame after the ask"),
        (10, 11, T0 + 300, False, "frame after the ask, still off by one"),
        (10, 10, T0, False, "matching frame at the ask (newer_than_ask: equal is not newer)"),
        (10, 10, T0 - 500, False, "matching frame older than the ask"),
        (10, 10, None, False, "no frame within FRAME_LAG_MS: never complete"),
    ):
        assert d.settle_outcome(counted, counter, frame_at, T0, 1) == (want, not want), why
        assert d.settle_outcome(counted, counter, frame_at, T0, 2) == (False, False), why


def case_activity_delta():
    state = d.UnreadSet(T0, entries={1: (None, T0)}, gone={2: T0})
    for fan, row, prior, dm, echo in (
        (1, {"hasUnread": False}, True, 0, -1),
        (2, {"hasUnread": True}, False, 1, 0),
        (3, {"hasUnread": True}, True, 0, -1),
        (3, {"hasUnread": False}, False, 1, 0),
        (3, None, None, None, None),
    ):
        assert d.prior_unread(state, fan, row) is prior
        assert d.expected_delta("dm", False, prior) == dm
        assert d.expected_delta("dm", True, prior) == 0
        assert d.expected_delta("echo", False, prior) == echo
    for replied, now, want, why in (
        ((True, T0), T0 + d.ECHO_WINDOW_MS, True, "our reply's echo: his state before the reply"),
        ((True, T0), T0 + d.ECHO_WINDOW_MS + 1, False, "too late to be that reply's echo"),
        (None, T0, False, "no reply: the held state"),
    ):
        assert d.echo_prior(state, 2, None, replied, now) is want, why
    assert d.reply_prior((True, T0), False, T0 + 400) == (True, T0), "a second part keeps the first part's prior"
    assert d.reply_prior((True, T0), False, T0 + d.ECHO_WINDOW_MS + 1) == (False, T0 + d.ECHO_WINDOW_MS + 1)
    assert d.reply_prior(None, None, T0) == (None, T0)


def case_diff():
    prev = d.replace_set(None, [_row(G)], T0 - 10_000, True)
    fresh = d.apply(prev, DmIn(G, T0 + 1, False))
    late = T0 + 1
    rows = [
        ([_row(F)], None, [], True, [(F, 0)], "window unread, absent from a complete list"),
        ([_row(F)], None, [], False, [], "same, incomplete list"),
        ([_row(F, muted=True)], None, [], True, [], "muted"),
        ([_row(F, muted=None)], None, [], True, [], "isMutedNotifications missing"),
        ([_row(F, at=late)], None, [], True, [], "last message after the ask"),
        ([_row(F, at=T0)], None, [], True, [(F, 0)], "last message at the ask"),
        ([_row(F, False)], None, [_row(F)], False, [(F, 1)], "window read, in an incomplete list"),
        ([_row(F, False)], None, [_row(F)], True, [(F, 1)], "window read, in a complete list"),
        ([_row(F)], None, [_row(F)], True, [], "window unread, in the list"),
        ([_row(F, False)], None, [], True, [], "window read, absent"),
        ([_row(F)], prev, [], True, [(F, 0), (G, 0)], "off-window G in the previous set, complete list"),
        ([_row(F)], prev, [], False, [], "same, incomplete list"),
        ([_row(F)], prev, [_row(F), _row(G)], True, [], "G still in the list"),
        ([], prev, [_row(G), _row(H)], False, [(H, 1)], "off-window H new in the list"),
        ([], None, [_row(H)], True, [], "no previous set: no off-window flip"),
        (None, prev, [], True, [(G, 0)], "no window held: every fan off-window"),
        ([], fresh, [], True, [], "G's set entry newer than the ask"),
    ]
    for window, p, unread, complete, want, why in rows:
        got = d.diff(window, p, unread, complete, T0, fence=p)
        assert got == want, (why, got)


def case_diff_fences_newer_reads():
    prev = d.replace_set(None, [_row(F), _row(G)], T0 - 1, True)
    prev = d.apply(prev, ReadDone(F, T0 + 1))
    assert d.diff([_row(F, False)], prev, [_row(F)], False, T0, fence=prev) == []
    assert d.diff([_row(G, False)], prev, [_row(G)], False, T0, window_at=T0 + 1, fence=prev) == []
    assert d.diff([], prev, [_row(F)], False, T0, fence=prev) == []
    assert d.diff([_row(F, False)], None, [_row(F), _row(H)], True, T0, fence=prev) == []


def case_write_landed_during_read_fences_it():
    prev = d.replace_set(None, [_row(F), _row(G)], T0 - 100, True)
    prev = d.apply(prev, ReadDone(F, T0 - 50, landed=T0 + 10))
    assert d.diff([], prev, [_row(F), _row(G)], True, T0, fence=prev) == [], "landed after the ask: fenced"
    assert F not in d.replace_set(prev, [_row(F), _row(G)], T0, True).fans
    first = d.apply(d.UnreadSet(T0 - 1), ReadDone(F, T0 - 50, landed=T0 + 10))
    assert F not in d.replace_set(first, [_row(F)], T0, True).fans, "the first read's journal keeps it"
    listed = d.replace_set(None, [_row(F)], T0, True)
    assert F not in d.apply(listed, ReadDone(F, T0 - 50, landed=T0 + 10)).fans, "lands after a stale list"
    dm = d.apply(prev, DmIn(F, T0 + 20, False))
    assert F in dm.fans and d.apply(d.apply(d.replace_set(None, [_row(G)], T0 - 100, True),
                                            DmIn(F, T0 - 20, False)),
                                    ReadDone(F, T0 - 50, landed=T0 + 10)).fans == {F, G}, "a DM during the write wins"
    assert d.apply(prev, ReadDone(G, T0 - 200, landed=T0 - 150)) == prev, "landed before the set's ask: ignored"


def case_bulk_preserves_newer_entry():
    prev = d.replace_set(None, [_row(F)], T0, True)
    prev = d.apply(prev, DmIn(G, T0 + 2, False))
    assert d.apply(prev, ReadDone(None, T0 + 1)).fans == {G}


def case_mute_changes():
    rows = [
        ([_row(F, muted=True)], {}, [_row(F)], {F: False}, "unmuted elsewhere: the list row wins"),
        ([_row(F)], {}, [_row(F, muted=True)], {F: True}, "a muted list row wins too"),
        ([_row(F)], {}, [_row(F)], {}, "agrees: no change"),
        ([_row(F, muted=None)], {}, [_row(F)], {F: False}, "held flag missing"),
        ([_row(F, muted=True)], {}, [_row(F, muted=None)], {}, "list flag missing: nothing known"),
        ([], {}, [_row(F)], {}, "fan not held anywhere"),
        (None, {}, [_row(F)], {}, "no window held"),
        ([_row(F, muted=False)], {F: (True, T0 - 1)}, [_row(F)], {F: False}, "our mute before the ask: the list wins"),
        ([_row(F, muted=True)], {F: (True, T0)}, [_row(F)], {F: False}, "our mute at the ask"),
        ([_row(F, muted=True)], {F: (True, T0 + 1)}, [_row(F)], {}, "our mute after the ask stands"),
        ([], {F: (True, T0 - 1)}, [_row(F)], {F: False}, "off-window fan, mute map only"),
        ([_row(F, muted=True), _row(F)], {}, [_row(F), _row(F, muted=True)], {F: False}, "first row per fan"),
    ]
    for window, held, unread, want, why in rows:
        assert d.mute_changes(window, T0, unread, held, T0) == want, (why, d.mute_changes(window, T0, unread, held, T0))
    newer = [
        ([_row(F, muted=True)], T0 + 1, {}, {}, "window asked after the read: its row stands"),
        ([_row(F, muted=True)], T0 - 1, {}, {F: False}, "window asked before the read: the list wins"),
        ([_row(F, muted=True)], None, {}, {F: False}, "window ask unknown: the list wins"),
        ([], T0 + 1, {F: (True, T0 - 1)}, {F: False}, "a newer window not holding the fan: the mute map still heals"),
    ]
    for window, window_at, held, want, why in newer:
        got = d.mute_changes(window, window_at, [_row(F)], held, T0)
        assert got == want, (why, got)


REG =frozenset({701, 702, 703, 704})


def _send(fan, **kw):
    return _row(fan, canSendMessage=True, **kw)


def case_unread_set_and_restricted():
    ask = T0
    rows = [_send(f) for f in (701, 702, 703)] + [_send(801), _send(802)]
    st = d.replace_set(None, rows, ask, True)
    def r(state, ids):
        return d.restricted_unread(state, ids).n
    assert r(st, REG) == 3 and st.fans == frozenset({701, 702, 703, 801, 802}), st
    dm = d.apply(st, DmIn(704, ask + 10, False))
    assert r(dm, REG) == 4 and 704 in dm.fans, ("a 0-call add with no row: counts as in the registry", dm)
    assert r(d.apply(dm, DmIn(805, ask + 10, False)), REG) == 4, "a 0-call add outside the registry does not count"
    assert r(d.apply(st, UnreadDone(704, ask + 10)), REG) == 4, "our mark unread adds like a DM"
    assert r(d.apply(dm, Echo(704, ask + 20)), REG) == 3 and r(d.apply(dm, ReadDone(704, ask + 20)), REG) == 3
    assert r(d.apply(dm, ReadDone(None, ask + 20)), REG) == 0 and d.apply(dm, ReadDone(None, ask + 20)).fans == set()
    assert d.apply(st, ReadDone(701, ask)) == st and d.apply(st, DmIn(704, ask - 5, False)) == st, \
        "an event at or before the set's ask leaves it"
    assert d.apply(dm, ReadDone(704, ask + 5)) == dm, "older than the fan's own entry: the newer one stands"
    assert d.apply(st, DmIn(704, ask + 10, True)) == st, "a muted DM never raises R"
    again = d.replace_set(dm, [_send(f) for f in (701, 702, 703)], ask + 5, True)
    assert 704 in again.fans and r(again, REG) == 4, ("a DM after the ask survives a complete replace", again)
    gone = d.replace_set(dm, [_send(f) for f in (701, 702)], ask + 50, True)
    assert 704 not in gone.fans and 703 not in gone.fans, ("a complete read asked after the DM replaces it", gone)
    part = d.replace_set(st, [_send(701)], ask + 50, False)
    assert part.fans == st.fans and r(part, REG) == 3, ("an incomplete read only adds", part)
    read = d.apply(st, ReadDone(702, ask + 10))
    assert 702 not in d.replace_set(read, rows, ask + 5, True).fans, "a read after the ask survives the replace"
    assert 702 not in d.replace_set(read, rows, ask + 5, False).fans, "... an incomplete one too"
    cut = d.apply(st, ReadDone(None, ask + 10))
    assert d.replace_set(cut, rows, ask + 5, True).fans == set(), "mark all read after the ask survives the replace"
    real = utd.excluded_from_badges
    utd.excluded_from_badges = lambda fan, row, ids: fan not in (701, 704) and real(fan, row, ids)
    try:
        assert r(st, REG) == 2 and r(dm, REG) == 2, "the predicate alone decides, rows and 0-call adds alike"
    finally:
        utd.excluded_from_badges = real
    up = ask - 1
    total = utd.State(n=11, at=ask)
    assert utd.slot(total, d.restricted_unread(st, REG), up, ask)["n"] == 8, "counter 11, R 3 -> red 8"
    friends = {"canSendMessage": False, "canNotSendReason": "only_friends"}
    gone_chat = {"canSendMessage": False, "canNotSendReason": "chat_unavailable"}
    ex = [_send(900 + i) for i in range(7)] + [_row(910 + i, **friends) for i in range(4)] \
        + [_row(920 + i, **gone_chat) for i in range(2)]
    assert d.complete(ex, False, False, 11, 0, 1), "11 rows pass of_counts"
    st = d.replace_set(None, ex, ask, True)
    restricted = d.restricted_unread(st, frozenset())
    assert restricted.n == 4 and utd.slot(total, restricted, up, ask)["n"] == 7, restricted
    restricted_on_of = {"canSendMessage": False, "canNotSendReason": "muted"}
    st = d.apply(d.replace_set(None, [_send(900), _send(901)], ask, True), DmIn(902, ask + 20, False))
    win = [_row(900, **restricted_on_of), _row(901, **restricted_on_of), _row(902, **restricted_on_of), _send(950)]
    fresh = d.refresh_rows(st, win, ask + 10)
    assert fresh.fans == st.fans and r(fresh, frozenset()) == 2, ("a newer window row replaces the set's row", fresh)
    assert fresh.entries[902] == st.entries[902], "an entry newer than the window keeps its own row"
    assert d.refresh_rows(st, win, ask) == st, "a window at the set's ask leaves it"
    assert r(d.refresh_rows(fresh, [_send(900)], ask + 30), frozenset()) == 1, "unrestricted on OF: counts again"


def case_newer_than_ask():
    assert d.newer_than_ask(T0, T0) is False and d.newer_than_ask(T0 + 1, T0) is True
    assert d.newer_than_ask(T0 - 1, T0) is False and d.newer_than_ask(None, T0) is False, "undated: not newer"
    stale = [_row(F, at=T0 + 5_000)]
    assert d.diff(stale, None, [], True, T0) == [], "the fence holds the stale-read row"
    real = d.newer_than_ask
    d.newer_than_ask = lambda _at, _asked: False
    try:
        assert d.diff(stale, None, [], True, T0) == [(F, 0)], "fence patched off: the stale-read row flips"
    finally:
        d.newer_than_ask = real
    held = d.apply(d.replace_set(None, [_row(F)], T0, True), DmIn(G, T0 + 10, False))
    assert G in d.replace_set(held, [_row(F)], T0 + 5, True).fans, "the fence keeps the newer DM"
    d.newer_than_ask = lambda _at, _asked: False
    try:
        assert G not in d.replace_set(held, [_row(F)], T0 + 5, True).fans, "fence patched off: the DM is erased"
    finally:
        d.newer_than_ask = real


def case_hover():
    assert d.HOVER_COOLDOWN_MS == 30_000
    for why, last, in_flight, now, off, counter_on, want in (
        ("no bust read yet", None, False, T0, False, True, "read"),
        ("in flight 5 s in", T0, True, T0 + 5_000, False, True, "join"),
        ("in flight past 30 s", T0, True, T0 + 31_000, False, True, "join"),
        ("landed, 5 s in", T0, False, T0 + 5_000, False, True, "held"),
        ("landed, 29.999 s in", T0, False, T0 + 29_999, False, True, "held"),
        ("landed, 30 s in", T0, False, T0 + 30_000, False, True, "read"),
        ("landed, 31 s in", T0, False, T0 + 31_000, False, True, "read"),
        ("off, idle", None, False, T0, True, True, "held"),
        ("off, past 30 s", T0, False, T0 + 31_000, True, True, "held"),
        ("off without the counter", None, False, T0, True, False, "direct"),
        ("no counter, landed 5 s in", T0, False, T0 + 5_000, False, False, "direct"),
        ("no counter, in flight", T0, True, T0 + 1_000, False, False, "direct"),
    ):
        assert d.hover(last, in_flight, now, off, counter_on) == want, why


def case_intent_lifetime():
    tail, hard = d.INTENT_TAIL_MS, d.INTENT_MAX_MS
    assert (tail, hard) == (1500, 5000)
    i = Intent(1, F, T0)
    assert not d.intent_live(i, T0 - 1), "nothing before its creation"
    resp = d.respond((i,), 1, T0 + 400)
    assert resp[0].responded == T0 + 400, resp
    assert d.intent_live(resp[0], T0 + 400 + tail) and not d.intent_live(resp[0], T0 + 400 + tail + 1), \
        "response at t: live until t + 1.5 s"
    assert d.intent_live(i, T0 + hard) and not d.intent_live(i, T0 + hard + 1), "no response: dies at creation + 5 s"
    late = d.respond((i,), 1, T0 + 4900)[0]
    assert not d.intent_live(late, T0 + hard + 1), "the hard max holds past a late response"
    assert not d.intent_live(d.retire((i,), 1)[0], T0 + 1), "a write that did not land: dead at once"
    twin = Intent(2, F, T0)
    both = d.retire(d.respond((i, twin), 2, T0 + 400), 1)
    assert both == (replace(i, retired=True), replace(twin, responded=T0 + 400)), \
        ("same fan, same ms: each write stamps only its own intent", both)
    ok, _dms, _echoes, spent = d.explain(d.CounterFrame(T0 + 10, None), (), (), (i,))
    assert ok and not d.explain(d.CounterFrame(T0 + 20, None), (), (), spent)[0], "one frame spent"
    assert d.prune(spent, T0 + 20) == () and d.prune(d.retire((i,), 1), T0 + 20) == (), "spent / retired dropped"
    assert d.prune((i,), T0 + hard + d.DECIDE_AFTER_MS) == (i,), "a frame up to its end may still be undecided"
    assert d.prune((i,), T0 + hard + d.DECIDE_AFTER_MS + 1) == (), "past that, dropped"
    assert not d.should_record(True, _row(F, unread=False)), "only_if_unread, held row read: not recorded"
    assert d.should_record(True, _row(F)) and d.should_record(True, None), "held row unread or unknown: recorded"
    assert d.should_record(False, _row(F, unread=False)), "without only_if_unread: always recorded"


_harness.run()
