#!/usr/bin/env python3
"""badge_reads_decide (creator-badges phase 0C), as tables. Pure: no clock, no I/O; times are passed (epoch ms).

  case_explained:       a same-value frame (counter unchanged) with no DM, echo or intent is unexplained; a DM at
                        ±0.5 s explains, 0.51 s not; an echo (`Echo` or `Outbound`) at ±1.5 s explains, 1.51 s not;
                        a live intent explains, an expired or retired one not; a single-fan intent is spent by one
                        frame, a mark-all intent explains two; a DM-explained frame spends no intent.
  case_gate:            idle -> Start; in flight -> pending, then exactly one follow-up; inside the gap ->
                        Wait(last_start + gap), full 5 s and lean 15 s; the 121st start inside 3600 s -> Capped, the
                        first after the oldest slides out -> Start; an exit hold -> Wait; page 1 sent 1.3 s after the
                        admit (pacer) -> the gap counts from the send, an earlier or no send time -> from the admit.
  case_complete:        no further page and `of_counts` rows equal the counter -> complete; no further page, counter
                        unknown -> complete; no further page, 0 rows, counter 1 -> incomplete + mismatch; 20 rows with
                        `hasMore`, counter 35 -> incomplete; partial (page-2 429, duplicate-only page) -> incomplete;
                        rows equal the counter but a frame since the ask -> incomplete; only a one-page mismatch
                        waits for the next frame (`settles`), two pages or a match never; that frame completes it
                        only matching and newer than the ask (`settled`), no frame -> never.
  case_diff:            window unread + absent from a complete list -> (fan, 0); incomplete -> none; muted (True or
                        missing) -> none; last message after the ask -> none; window read + in any list -> (fan, 1);
                        off-window fan in the previous set and absent from a complete list -> (fan, 0), incomplete ->
                        none; off-window fan new in the list -> (fan, 1); no previous set -> no off-window flip.
                        An off-window fan whose set entry is newer than the ask -> none.
  case_unread_set_and_restricted: R = set fans OF counts and `excluded_from_badges` removes: 3 restricted rows -> 3;
                        a DM from a registry fan not in the set -> 4; his echo or read -> 3; mark all read -> 0; an
                        event at or before the set's ask -> unchanged; a DM after the ask survives a complete replace
                        without him; an incomplete replace keeps a held fan it missed; a muted DM -> unchanged; the
                        predicate patched False for one fan -> R - 1; counter 11, R 3 -> red 8; owner amendment #3: 7
                        sendable + 4 `only_friends` + 2 `chat_unavailable`, counter 11 -> complete, R 4, red 7.
  case_unread_set_and_restricted (refresh_rows): a window newer than a fan's entry replaces its row (restricted on OF
                        -> R counts it, unrestricted -> not); an entry newer than the window, or a window at the
                        ask, keeps its row; fans outside the set are not added.
  case_complete (one frame): one page, no more pages, not partial, counter known and exactly one frame since the ask
                        -> judged by counts; 2+ frames, two pages, more pages, partial or no counter -> incomplete.
  case_newer_than_ask:  equal -> false, after -> true; `diff` and `replace_set` decide only through it.
  case_hover:           no bust read yet -> read; one in flight -> join (even past 30 s); landed inside 30 s ->
                        held, at 30 s -> read; `BADGE_READS=off` -> held always; UNREAD_TOTAL off -> direct (every
                        bust reads, as before the cooldown).
  case_intent_lifetime: response at t -> live until t + 1.5 s; no response -> dies at creation + 5 s (a late response
                        too); retired -> dead at once; one frame spent; pruned once no undecided frame can need it;
                        two intents on the same fan and ms stamped apart (by id); `only_if_unread` with the held row read -> not recorded, unread or unknown -> recorded.
Run: ./venv/bin/python service/tests/test_badge_reads_decide.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402

from dataclasses import replace  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import badge_reads_decide as d  # noqa: E402
import unread_total_decide as utd  # noqa: E402
from badge_reads_decide import Capped, DmIn, Echo, Gate, Intent, ReadDone, Start, UnreadDone, Wait  # noqa: E402

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
    assert d.explained(T0, (), (), ()) is False, "same-value frame, nothing to explain it: unexplained"
    for why, dms, echoes, want in (
        ("DM 0.5 s before", (T0 - 500,), (), True), ("DM 0.5 s after", (T0 + 500,), (), True),
        ("DM 0.51 s before", (T0 - 510,), (), False), ("DM 0.51 s after", (T0 + 510,), (), False),
        ("echo 1.5 s before", (), (T0 - 1500,), True), ("echo 1.5 s after", (), (T0 + 1500,), True),
        ("echo 1.51 s before", (), (T0 - 1510,), False), ("echo 1.51 s after", (), (T0 + 1510,), False),
        ("Outbound echo 1 s before", (), (T0 - 1000,), True), ("DM 1 s away is no echo", (T0 - 1000,), (), False),
    ):
        assert d.explained(T0, dms, echoes, ()) is want, why
    live, gone = Intent(1, F, T0 - 100), Intent(2, F, T0 - 6000)
    assert d.explained(T0, (), (), (live,)) and not d.explained(T0, (), (), (gone,)), "live intent explains, expired not"
    assert not d.explained(T0, (), (), (Intent(3, F, T0 - 100, retired=True),)), "a retired intent explains nothing"
    ok, left = d.explain(T0, (), (), (live,))
    assert ok and not d.explain(T0 + 10, (), (), left)[0], ("a single-fan intent is spent by one frame", left)
    every = (Intent(4, None, T0 - 100),)
    ok1, every = d.explain(T0, (), (), every)
    assert ok1 and d.explain(T0 + 10, (), (), every)[0], "a mark-all intent explains two frames"
    ok, kept = d.explain(T0, (T0 - 100,), (), (live,))
    assert ok and kept == (live,), "a frame a DM explains spends no intent"
    two = (Intent(5, G, T0 - 50), Intent(6, F, T0 - 100))
    _ok, spent = d.explain(T0, (), (), two)
    assert [i.used for i in spent] == [False, True], ("the oldest live intent is spent first", spent)


def case_gate():
    full, lean, cap = d.GAP_MS["full"], d.GAP_MS["lean"], d.CAP_PER_HOUR
    assert (full, lean, cap) == (5000, 15000, 120)
    g, v = d.admit(Gate(), T0, full, cap, 0.0)
    assert v == Start() and g.in_flight and g.last_start == T0 and g.starts == (T0,) and not g.pending, (g, v)
    g, v = d.admit(g, T0 + 9000, full, cap, 0.0)
    assert isinstance(v, Wait) and g.pending and g.in_flight, ("in flight: pending", g, v)
    g, v = d.admit(g, T0 + 9500, full, cap, 0.0)
    assert isinstance(v, Wait) and g.pending, ("a second ask in flight: still one pending", g, v)
    g = d.done(g)
    assert not g.in_flight and g.pending, g
    g, v = d.admit(g, T0 + 10_000, full, cap, 0.0)
    assert v == Start() and not g.pending and g.starts == (T0, T0 + 10_000), ("exactly one follow-up", g, v)
    g = d.done(g)
    for gap in (full, lean):
        got, v = d.admit(g, T0 + 10_000 + gap - 1, gap, cap, 0.0)
        assert v == Wait(T0 + 10_000 + gap) and got.pending and not got.in_flight, (gap, got, v)
        got, v = d.admit(got, T0 + 10_000 + gap, gap, cap, 0.0)
        assert v == Start(), (gap, v)
    for gap in (full, lean):
        paced, _v = d.admit(Gate(), T0, gap, cap, 0.0)
        paced = d.done(paced, T0 + 1300)
        _got, v = d.admit(paced, T0 + gap, gap, cap, 0.0)
        assert v == Wait(T0 + 1300 + gap), ("the gap counts from page 1's send", gap, v)
        for sent in (None, T0 - 1):
            _got, v = d.admit(d.done(d.admit(Gate(), T0, gap, cap, 0.0)[0], sent), T0 + gap, gap, cap, 0.0)
            assert v == Start(), ("no later send time: from the admit", gap, sent, v)
    got, v = d.admit(g, T0 + 60_000, full, cap, 2.5)
    assert v == Wait(T0 + 62_500) and got.pending and not got.in_flight, ("exit held", got, v)
    g, t = Gate(), T0
    for _ in range(cap):
        g, v = d.admit(g, t, full, cap, 0.0)
        assert v == Start(), (t, v)
        g, t = d.done(g), t + 10_000
    g, v = d.admit(g, T0 + 3_599_999, full, cap, 0.0)
    assert v == Capped() and g.pending and not g.in_flight and len(g.starts) == cap, ("121st in the hour", g, v)
    g, v = d.admit(g, T0 + 3_600_000, full, cap, 0.0)
    assert v == Start() and len(g.starts) == cap, ("the oldest slid out", g, v)


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
        assert d.settled(counted, counter, frame_at, T0) is want, why


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
        assert d.diff(window, p, unread, complete, T0) == want, (why, d.diff(window, p, unread, complete, T0))


REG = frozenset({701, 702, 703, 704})     # our registry


def _send(fan, **kw):
    return _row(fan, canSendMessage=True, **kw)


def case_unread_set_and_restricted():
    ask = T0
    rows = [_send(f) for f in (701, 702, 703)] + [_send(801), _send(802)]
    st = d.replace_set(None, rows, ask, True)
    r = d.restricted_unread
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
    assert utd.slot(utd.State(n=11, at=ask), r(st, REG), up, ask)["n"] == 8, "counter 11, R 3 -> red 8"
    friends = {"canSendMessage": False, "canNotSendReason": "only_friends"}
    gone_chat = {"canSendMessage": False, "canNotSendReason": "chat_unavailable"}
    ex = [_send(900 + i) for i in range(7)] + [_row(910 + i, **friends) for i in range(4)] \
        + [_row(920 + i, **gone_chat) for i in range(2)]
    assert d.complete(ex, False, False, 11, 0, 1), "11 rows pass of_counts"
    st = d.replace_set(None, ex, ask, True)
    assert r(st, frozenset()) == 4 and utd.slot(utd.State(n=11, at=ask), 4, up, ask)["n"] == 7, r(st, frozenset())
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
        ("off without the counter", None, False, T0, True, False, "held"),
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
    ok, spent = d.explain(T0 + 10, (), (), (i,))
    assert ok and not d.explain(T0 + 20, (), (), spent)[0], "one frame spent"
    assert d.prune(spent, T0 + 20) == () and d.prune(d.retire((i,), 1), T0 + 20) == (), "spent / retired dropped"
    assert d.prune((i,), T0 + hard + d.DECIDE_AFTER_MS) == (i,), "a frame up to its end may still be undecided"
    assert d.prune((i,), T0 + hard + d.DECIDE_AFTER_MS + 1) == (), "past that, dropped"
    assert not d.should_record(True, _row(F, unread=False)), "only_if_unread, held row read: not recorded"
    assert d.should_record(True, _row(F)) and d.should_record(True, None), "held row unread or unknown: recorded"
    assert d.should_record(False, _row(F, unread=False)), "without only_if_unread: always recorded"


_harness.run()
