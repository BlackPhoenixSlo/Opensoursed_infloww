#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

import unread_total_decide as d  # noqa: E402
from unread_total_decide import (  # noqa: E402
    LOG_DRIFT, READ, UNKNOWN, UNREAD, WINDOW_READ, DmIn, ReadFlip, Reply, State,
)

T0 = 1_700_000_000_000


def case_count():
    rows = [
        ({"chatMessagesCount": 12}, 12, "int: OF's number"),
        ({"chatMessagesCount": 0}, 0, "zero is a number"),
        ({"chatMessagesCount": True}, None, "bool is no count"),
        ({"chatMessagesCount": "3"}, None, "str is no count"),
        ({"chatMessagesCount": 3.0}, None, "float is no count"),
        ({"chatMessagesCount": -1}, None, "negative is no count"),
        ({"chatMessagesCount": None}, None, "null is no count"),
        ({"name": "x"}, None, "missing (Fansly, another body)"),
        ([], None, "not a dict"),
        (None, None, "no body"),
    ]
    for body, want, why in rows:
        assert d.count(body) == want, (why, body, d.count(body))


def case_first_confirmation():
    st, actions = d.reconcile(State(), 12, T0, T0 + 50)
    assert st == State(n=12, at=T0, seen=T0), st
    assert actions == (), actions


def case_confirmation_adopts():
    down, up = (LOG_DRIFT, WINDOW_READ), (LOG_DRIFT,)
    rows = [
        (State(n=12, at=T0), 1, T0 + 1000, State(n=1, at=T0 + 1000, due=T0 + 1000, seen=T0 + 1000), down, "lower: OF's number"),
        (State(n=1, at=T0), 7, T0 + 1000, State(n=7, at=T0 + 1000, seen=T0 + 1000), up, "higher: OF's number"),
        (State(n=3, at=T0), 0, T0 + 1000, State(n=0, at=T0 + 1000, due=T0 + 1000, seen=T0 + 1000), down, "to zero"),
    ]
    for held, observed, asked, want, acts, why in rows:
        st, actions = d.reconcile(held, observed, asked, asked + 10)
        assert st == want and actions == acts, (why, st, actions)


def case_unchanged_n():
    st, actions = d.reconcile(State(n=3, at=T0), 3, T0 + 1000, T0 + 1010)
    assert st == State(n=3, at=T0 + 1000, seen=T0 + 1000), ("`at` is the newest confirmation's ask time", st)
    assert actions == (), ("an unchanged `n`: no action", actions)


def case_older_read_never_wins():
    held = State(n=3, at=T0 + 2000, seen=T0 + 2000)
    for observed in (3, 5):
        st, actions = d.reconcile(held, observed, T0 + 1000, T0 + 2500)
        assert st == held and actions == (), (observed, st, actions)
    st, actions = d.reconcile(held, 5, T0 + 2000, T0 + 2500)
    assert st == State(n=5, at=T0 + 2000, seen=T0 + 2000) and actions == (LOG_DRIFT,), (st, actions)


def case_slot():
    up = T0 - 1
    rows = [
        (State(), d.Restricted(0, False, 0), up, {"n": None, "at": None, "grey": "unseeded"}, "no confirmation: an object, grey"),
        (State(n=3, at=T0), d.Restricted(0, False, 0), up, {"n": 3, "at": T0, "grey": None}, "confirmed"),
        (State(n=11, at=T0), d.Restricted(4, False, 0), up, {"n": 7, "at": T0, "grey": None}, "owner amendment #3: 11 - 4 only_friends"),
        (State(n=2, at=T0), d.Restricted(5, False, 0), up, {"n": 0, "at": T0, "grey": None}, "floored at 0"),
        (State(n=5, at=T0), None, up, {"n": None, "at": T0, "grey": "r_unknown"}, "R unknown: never OF's raw number"),
        (State(n=5, at=T0), d.Restricted(1, False, 0), None, {"n": 4, "at": T0, "grey": "socket_down"}, "socket down: `n` kept, grey"),
    ]
    for st, r, up_since, want, why in rows:
        assert d.slot(st, r, up_since, T0 + 10) == want, (why, d.slot(st, r, up_since, T0 + 10))


def case_slot_bounds_uncertain_floor_by_latest_confirmation():
    restricted = d.Restricted(1, True, 12)
    for n, expected in ((15, 12), (9, 9), (8, None), (0, None)):
        slot = d.slot(State(n=n, at=T0), restricted, T0 - 1, T0 + 10)
        assert slot == {"n": expected, "at": T0, "grey": "r_unknown" if expected is None else None}, slot


def case_grey_reason():
    rows = [
        (State(), 0, T0, "unseeded", "no confirmation since start"),
        (State(), None, None, "unseeded", "first cause wins over socket_down and r_unknown"),
        (State(n=3, at=T0), 0, None, "socket_down", "live not up"),
        (State(n=3, at=T0), None, None, "socket_down", "socket_down before r_unknown"),
        (State(n=3, at=T0), 0, T0 + 1, "socket_down", "up again, no confirmation after the reconnect"),
        (State(n=3, at=T0 + 1), 0, T0 + 1, None, "a confirmation at the reconnect"),
        (State(n=3, at=T0 + 2), None, T0, "r_unknown", "no R since start"),
        (State(n=3, at=T0 + 2), 0, T0, None, "all known"),
    ]
    for st, r, up_since, want, why in rows:
        assert d.grey_reason(st, r, up_since, T0 + 10) == want, (why, d.grey_reason(st, r, up_since, T0 + 10))


FAN, FAN2 = 501, 502


def _held(n=3, at=T0):
    return State(n=n, at=at)


def case_prior_from_the_held_row():
    rows = [
        ({"withUser": {"id": FAN}, "hasUnread": True, "unreadMessagesCount": 2}, UNREAD, "flag set"),
        ({"withUser": {"id": FAN}, "hasUnread": False, "unreadMessagesCount": 0}, READ, "flag clear"),
        ({"withUser": {"id": FAN}, "hasUnread": False, "unreadMessagesCount": 2}, UNREAD,
         "flag clear, a count: unread, as the app reads it (W30-mu #9)"),
        ({"withUser": {"id": FAN}, "unreadMessagesCount": 1}, UNREAD, "no flag: the count"),
        ({"withUser": {"id": FAN}}, READ, "no flag, no count"),
        (None, UNKNOWN, "no row held"),
    ]
    for row, want, why in rows:
        assert d.prior_of(_held(), FAN, row) == want, (why, row)


def case_adjust_known_prior():
    rows = [
        (DmIn(FAN, READ), 4, "DM into a read chat: +1"),
        (DmIn(FAN, UNREAD), 3, "DM into an unread chat: 0 (chats, not messages)"),
        (ReadFlip(FAN, 0, T0 + 10, UNREAD), 2, "our mark read on an unread chat: -1"),
        (ReadFlip(FAN, 0, T0 + 10, READ), 3, "our mark read on a read chat: 0"),
        (ReadFlip(FAN, 1, T0 + 10, READ), 4, "our mark unread on a read chat: +1"),
        (ReadFlip(FAN, 1, T0 + 10, UNREAD), 3, "our mark unread on an unread chat: 0"),
    ]
    for ev, want, why in rows:
        st = d.adjust(_held(3), ev, T0 + 20)
        assert st.n == want and st.at == T0, (why, st)


def case_clamped_at_zero():
    st = d.adjust(_held(0), ReadFlip(FAN, 0, T0 + 10, UNREAD), T0 + 20)
    assert st.n == 0, st
    st = d.adjust(st, DmIn(FAN2, READ), T0 + 30)
    assert st.n == 1, ("a clamped move is not owed back", st)


def case_no_total_yet():
    st = d.adjust(State(), DmIn(FAN, READ), T0 + 10)
    assert st.n is None and d.slot(st, d.Restricted(0, False, 0), T0, T0)["grey"] == "unseeded", st


def case_flips_kept_until_a_read_asked_after_they_landed():
    st = d.adjust(_held(3), ReadFlip(FAN, 0, T0 + 100, UNREAD), T0 + 500)
    st = d.adjust(st, DmIn(FAN2, READ), T0 + 400)
    assert st.n == 3, st
    st2, actions = d.reconcile(st, 3, T0 + 300, T0 + 600)
    assert st2.n == 3 and st2.at == T0 + 300, ("OF's 3 - the flip + the DM", st2)
    assert LOG_DRIFT not in actions, actions
    st3, actions = d.reconcile(st, 3, T0 + 550, T0 + 600)
    assert (st3.n, st3.adj) == (3, ()) and actions == (), (st3, actions)


def case_ordering():
    unread_row = {"withUser": {"id": FAN}, "hasUnread": True}
    st, _ = d.reconcile(_held(3), 4, T0 + 150, T0 + 160)
    st = d.adjust(st, DmIn(FAN, READ, T0 + 100), T0 + 200)
    assert st.n == 4 and st.adj == (), ("counted once", st)
    assert d.prior_of(st, FAN, None) == UNREAD, "the record still says unread"
    st2, actions = d.reconcile(st, 4, T0 + 300, T0 + 310)
    assert st2.n == 4 and actions == (), ("no false drift, no window read", st2, actions)
    st = d.adjust(_held(3), DmIn(FAN, READ, T0 + 100), T0 + 160)
    assert st.n == 4, st
    st, actions = d.reconcile(st, 4, T0 + 150, T0 + 170)
    assert st.n == 4 and st.adj == () and actions == (), (st, actions)
    st = _held(1)
    st = d.adjust(st, DmIn(FAN, d.prior_of(st, FAN, unread_row), T0 + 120), T0 + 125)
    st = d.adjust(st, ReadFlip(FAN, 0, T0 + 110, d.prior_of(st, FAN, None)), T0 + 130)
    assert st.n == 1 and d.prior_of(st, FAN, None) == UNREAD, ("the newer DM stands", st)
    st = d.adjust(st, ReadFlip(FAN, 0, T0 + 140, d.prior_of(st, FAN, None)), T0 + 150)
    assert st.n == 0 and d.prior_of(st, FAN, None) == READ, st
    st = d.adjust(_held(1), ReadFlip(FAN, 0, T0 + 110, UNREAD), T0 + 130)
    st, actions = d.reconcile(st, 1, T0 + 115, T0 + 140)
    assert st.n == 0, ("the landed read is kept", st, actions)
    st, actions = d.reconcile(st, 0, T0 + 200, T0 + 210)
    assert (st.n, st.adj) == (0, ()) and actions == (), (st, actions)
    st = d.adjust(_held(3), Reply(FAN, UNREAD), T0 + 200)
    st = d.adjust(st, DmIn(FAN, d.prior_of(st, FAN, None), T0 + 150), T0 + 260)
    assert st.n == 2 and d.prior_of(st, FAN, None) == READ, st


def case_reconcile_reapplies_after_ask():
    st = d.adjust(_held(3), DmIn(FAN, READ), T0 + 100)
    st = d.adjust(st, DmIn(FAN2, READ), T0 + 300)
    st2, actions = d.reconcile(st, 4, T0 + 200, T0 + 350)
    assert st2.n == 5 and st2.at == T0 + 200 and actions == (), ("OF's 4 + FAN2's DM", st2, actions)
    st3, actions = d.reconcile(st2, 5, T0 + 400, T0 + 450)
    assert (st3.n, st3.at, st3.adj) == (5, T0 + 400, ()) and actions == (), ("FAN2's DM is in OF's number now", st3)
    st4, actions = d.reconcile(st2, 1, T0 + 250, T0 + 450)
    assert st4.n == 2, ("OF's 1 + FAN2's DM still after the ask", st4)


def case_drift():
    st = d.adjust(_held(3), DmIn(FAN, READ), T0 + 100)
    assert d.expected(st, T0 + 50) == 3 and d.expected(st, T0 + 200) == 4
    assert d.expected(State(), T0) is None
    rows = [
        (4, (), "OF agrees: no drift"),
        (2, (LOG_DRIFT, WINDOW_READ), "OF lower: a read made elsewhere, drift down"),
        (6, (LOG_DRIFT,), "OF higher: drift up, logged only"),
    ]
    for observed, want, why in rows:
        _st, actions = d.reconcile(st, observed, T0 + 200, T0 + 250)
        assert sorted(actions) == sorted(want), (why, actions)
    _st, actions = d.reconcile(d.adjust(State(), DmIn(FAN, READ), T0), 9, T0 + 10, T0 + 20)
    assert LOG_DRIFT not in actions, ("a first confirmation has nothing to drift from", actions)


def case_adjust_unknown_prior():
    rows = [
        (DmIn(FAN, UNKNOWN), 4, 1, "DM, unknown: +1, slack +1"),
        (ReadFlip(FAN, 0, T0 + 10, UNKNOWN), 2, 0, "mark read, unknown: -1 (a tab saw it unread)"),
        (ReadFlip(FAN, 1, T0 + 10, UNKNOWN), 4, 1, "mark unread, unknown: +1, slack +1"),
        (Reply(FAN, UNKNOWN), 3, 1, "reply, unknown: 0, slack +1"),
    ]
    for ev, want, slack, why in rows:
        st = d.adjust(_held(3), ev, T0 + 20)
        assert (st.n, d.slack(st)) == (want, slack), (why, st)


def case_reply():
    for prior, want in ((UNREAD, 2), (READ, 3)):
        st = d.adjust(_held(3), Reply(FAN, prior), T0 + 20)
        assert st.n == want and d.slack(st) == 0, (prior, st)


def case_prior_of_order():
    unread_row = {"withUser": {"id": FAN}, "hasUnread": True}
    st = d.adjust(_held(3), Reply(FAN, UNREAD), T0 + 20)
    assert d.prior_of(st, FAN, unread_row) == READ, "our record beats the held row"
    assert d.prior_of(st, FAN, None) == READ, "our record beats no row"
    assert d.prior_of(st, FAN2, unread_row) == UNREAD, "no record: the held row"
    assert d.prior_of(st, FAN2, None) == UNKNOWN, "no record, no row"
    st = d.adjust(st, DmIn(FAN, READ), T0 + 30)
    assert d.prior_of(st, FAN, None) == UNREAD, "the latest record"
    st, _ = d.reconcile(st, 3, T0 + 100, T0 + 110)
    assert d.prior_of(st, FAN, None) == UNREAD, "a record outlives the next confirmation"
    st, _ = d.reconcile(st, 3, T0 + 200, T0 + 210)
    assert d.prior_of(st, FAN, None) == UNKNOWN, "... not the one after (one Cycle)"


def case_reply_then_mark_read_once():
    st = d.adjust(_held(3), Reply(FAN, d.prior_of(_held(3), FAN, {"withUser": {"id": FAN}, "hasUnread": True})),
                  T0 + 20)
    st = d.adjust(st, ReadFlip(FAN, 0, T0 + 25, d.prior_of(st, FAN, None)), T0 + 30)
    assert st.n == 2, ("-1 once", st)


def case_two_dms_into_one_read_chat():
    read_row = {"withUser": {"id": FAN}, "hasUnread": False}
    for row in (read_row, None):
        st = _held(3)
        for t in (T0 + 10, T0 + 20):
            st = d.adjust(st, DmIn(FAN, d.prior_of(st, FAN, row)), t)
        assert st.n == 4, ("+1 once", row, st)


def case_mark_all():
    st = d.adjust(_held(5), DmIn(FAN2, READ), T0 + 50)
    st = d.adjust(st, DmIn(FAN, READ), T0 + 200)
    st = d.adjust(st, ReadFlip(None, 0, T0 + 100, UNKNOWN), T0 + 300)
    assert st.n == 1 and d.slack(st) == 0, st
    assert d.prior_of(st, FAN2, None) == READ and d.prior_of(st, FAN, None) == UNREAD, st
    st0 = d.adjust(_held(5), ReadFlip(None, 0, T0 + 100, UNKNOWN), T0 + 300)
    assert st0.n == 0, ("no DM after it: 0", st0)
    st2, _ = d.reconcile(st, 7, T0 + 80, T0 + 310)
    assert st2.n == 1, st2
    st3 = d.adjust(st, DmIn(FAN2, d.prior_of(st, FAN2, None)), T0 + 400)
    assert st3.n == 2, ("a DM after the mark all moves as usual", st3)
    FAN3 = 503
    st4 = d.adjust(st0, DmIn(FAN3, UNKNOWN, T0 + 60), T0 + 350)
    assert st4.n == 0 and d.slack(st4) == 0, ("read by the mark all", st4)
    st5 = d.adjust(st4, DmIn(FAN3, d.prior_of(st4, FAN3, None), T0 + 360), T0 + 370)
    assert st5.n == 1, ("one made after it counts", st5)


def case_slack():
    st = d.adjust(_held(3), DmIn(FAN, UNKNOWN), T0 + 100)
    rows = [
        (4, (), "OF agrees"),
        (3, (), "lower within slack: no drift"),
        (2, (LOG_DRIFT, WINDOW_READ), "lower beyond slack: drift down"),
    ]
    for observed, want, why in rows:
        st2, actions = d.reconcile(st, observed, T0 + 200, T0 + 210)
        assert actions == want and d.slack(st2) == 0, (why, actions, st2)
    st = d.adjust(st, DmIn(FAN2, UNKNOWN), T0 + 300)
    st2, _ = d.reconcile(st, 4, T0 + 200, T0 + 310)
    assert st2.n == 5 and d.slack(st2) == 1, st2


def case_drift_actions():
    st = d.adjust(_held(3), DmIn(FAN, UNKNOWN), T0 + 100)
    rows = [
        (4, (), None, "OF agrees: nothing"),
        (3, (), None, "lower within slack: no read, no log"),
        (2, (LOG_DRIFT, WINDOW_READ), T0 + 200, "lower beyond slack: one window read + the drift log"),
        (6, (LOG_DRIFT,), None, "higher: logged only, no read"),
    ]
    for observed, want, due, why in rows:
        st2, actions = d.reconcile(st, observed, T0 + 200, T0 + 210)
        assert actions == want and st2.due == due, (why, actions, st2)
    assert d.reconcile(State(), 0, T0, T0)[0].due is None, "a first confirmation asks no read"


def case_one_window_read_per_drift():
    st, actions = d.reconcile(_held(5), 3, T0 + 100, T0 + 110)
    assert WINDOW_READ in actions and st.due == T0 + 100, (actions, st)
    st2, actions = d.reconcile(st, 1, T0 + 200, T0 + 210)
    assert actions == (LOG_DRIFT,) and st2.due == T0 + 200, ("no second ask; due moves to it", actions, st2)
    assert d.read_window(st2, T0 + 50).due == T0 + 200, "a read asked before the drift's confirmation: still due"
    assert d.read_window(st2, T0 + 150).due == T0 + 200, "a read in flight since the first drift does not serve the second"
    for asked in (T0 + 200, T0 + 300):
        assert d.read_window(st2, asked).due is None, ("a read asked at or after it serves it", asked)
    done = d.read_window(st2, T0 + 300)
    assert (done.n, done.at, done.adj, done.rec) == (st2.n, st2.at, st2.adj, st2.rec), "only `due` moves"
    assert d.read_window(_held(5), T0 + 300) == _held(5), "nothing pending: unchanged"
    st3, actions = d.reconcile(done, 0, T0 + 400, T0 + 410)
    assert WINDOW_READ in actions and st3.due == T0 + 400, (actions, st3)
    st4 = d.adjust(st2, DmIn(FAN, READ), T0 + 220)
    assert st4.due == T0 + 200, ("a move keeps the drift pending", st4)


FAN3 = 503


def _r(fan, unread, created=None):
    row = {"withUser": {"id": fan}, "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0}
    if created is not None:
        row["lastMessage"] = {"id": fan * 10, "createdAt": created}
    return row


ASK = 1_763_632_800_000
BEFORE, AFTER = "2025-11-20T09:59:00+00:00", "2025-11-20T10:00:01Z"


def case_flips_with_old_rows():
    old = [_r(FAN, True, BEFORE), _r(FAN2, False, BEFORE), _r(FAN3, True, BEFORE), _r(504, True, BEFORE)]
    new = [_r(FAN, False, BEFORE), _r(FAN2, True, BEFORE), _r(FAN3, True, BEFORE), _r(505, False, BEFORE)]
    for drift in (True, False):
        assert d.flips(old, new, ASK, drift) == [(FAN, 0), (FAN2, 1)], drift
    assert d.flips(old, old, ASK, True) == [], "nothing flipped"
    by_count = [{"withUser": {"id": FAN}, "unreadMessagesCount": 0}]
    assert d.flips([{"withUser": {"id": FAN}, "unreadMessagesCount": 2}], by_count, ASK, False) == [(FAN, 0)], \
        "no flag: the count"
    assert d.flips([], new, ASK, True) == [], "an empty held window: nothing to flip (rows new to it)"
    assert d.flips(old, [{"withUser": {}}, "x", None], ASK, True) == [], "rows without a fan skipped"


def case_flips_without_old_rows():
    new = [_r(FAN, False, BEFORE), _r(FAN2, True, BEFORE), _r(FAN3, False)]
    assert d.flips(None, new, ASK, True) == [(FAN, 0), (FAN3, 0)], "drift read: every read row cleared"
    assert d.flips(None, new, ASK, False) == [], "routine read: none"


def case_flips_never_clear_newer():
    old = [_r(FAN, True, BEFORE), _r(FAN2, True, BEFORE)]
    new = [_r(FAN, False, AFTER), _r(FAN2, False, BEFORE)]
    assert d.flips(old, new, ASK, True) == [(FAN2, 0)], "FAN's last message is newer than the ask"
    assert d.flips(None, new, ASK, True) == [(FAN2, 0)], "no old rows alike"
    at_ask = [_r(FAN, False, "2025-11-20T10:00:00.000Z")]
    assert d.flips(None, at_ask, ASK, True) == [(FAN, 0)], "at the ask time: not newer"
    assert d.flips(None, [_r(FAN, False, "garbage")], ASK, True) == [(FAN, 0)], "undated: cleared"
    newer_unread = [_r(FAN, True, AFTER)]
    assert d.flips([_r(FAN, False, BEFORE)], newer_unread, ASK, True) == [(FAN, 1)], "a newer unread still flips"



REG = 601


def case_excluded_from_badges():
    reg = {REG}
    unread = {"withUser": {"id": FAN}, "hasUnread": True}
    rows = [
        (REG, unread, True, "our registry member"),
        (FAN, {**unread, "canSendMessage": False, "canNotSendReason": "only_friends"}, True, "only_friends"),
        (FAN, {**unread, "canSendMessage": False, "canNotSendReason": "chat_unavailable"}, True, "chat_unavailable"),
        (FAN, {**unread, "canSendMessage": False, "canNotSendReason": None}, True, "no reason"),
        (FAN, unread, False, "field absent: sendable"),
        (FAN, {**unread, "canSendMessage": True}, False, "sendable"),
        (FAN, {"withUser": {"id": FAN, "isRestricted": True}, "hasUnread": True}, False, "OF isRestricted alone"),
        ("abc", unread, False, "non-int fan"),
        (None, unread, False, "no fan"),
        ([REG], unread, False, "unhashable fan"),
        (str(REG), unread, True, "str fan id matches the registry"),
        (REG, None, True, "registry member, non-dict row"),
        (FAN, "x", False, "non-dict row"),
        ("abc", {"canSendMessage": False}, True, "non-int fan, not sendable"),
    ]
    for fan, row, want, why in rows:
        assert d.excluded_from_badges(fan, row, reg) is want, (why, fan, row)


def case_of_counts():
    def row(**kw):
        return {"withUser": {"id": FAN}, "hasUnread": True, "unreadMessagesCount": 1, **kw}
    rows = [
        (row(), True, "sendable unread, field absent"),
        (row(canSendMessage=True, isMutedNotifications=False), True, "sendable unread"),
        (row(canSendMessage=False, canNotSendReason="only_friends"), True, "only_friends unread"),
        (row(canSendMessage=False, canNotSendReason="muted", isMutedNotifications=False), True,
         "Restricted unread (OF reason muted)"),
        (row(canSendMessage=False, canNotSendReason="muted", isMutedNotifications=True), False,
         "Restricted and notification-muted"),
        (row(canSendMessage=False, canNotSendReason="chat_unavailable"), False, "chat_unavailable unread"),
        (row(isMutedNotifications=True), False, "muted"),
        (row(hasUnread=False, unreadMessagesCount=0), False, "read"),
        ({"withUser": {"id": FAN}, "unreadMessagesCount": 2}, True, "unread by count"),
        ("x", False, "non-dict row"),
    ]
    for r, want, why in rows:
        assert d.of_counts(r) is want, (why, r)


def case_amber_count():
    me = 999

    def row(fan=FAN, **kw):
        return {"withUser": {"id": fan}, "unreadMessagesCount": 0, "isMutedNotifications": False,
                "lastMessage": {"fromUser": {"id": fan}}, **kw}
    filler = [row(7000 + i, lastMessage={"fromUser": {"id": me}}) for i in range(25)]
    rows = [
        ([row()], None, 1, "read, Fan-last, not muted"),
        ([row(unreadMessagesCount=2)], None, 0, "unread"),
        ([row(lastMessage={"fromUser": {"id": me}})], None, 0, "Creator-last"),
        ([row(lastMessage={"fromUser": {"id": str(me)}})], None, 0, "Creator-last, str id"),
        ([row(lastMessage={})], None, 0, "no last sender"),
        ([row(isMutedNotifications=True)], None, 0, "muted"),
        ([{k: v for k, v in row().items() if k != "isMutedNotifications"}], None, 0, "mute field absent"),
        ([row(isMutedNotifications=None)], None, 0, "mute field null"),
        ([row(REG)], None, 0, "registry Fan"),
        ([row(canSendMessage=False, canNotSendReason="only_friends")], None, 0, "only_friends"),
        ([row(canSendMessage=False, canNotSendReason="chat_unavailable")], None, 0, "not sendable"),
        ([row(withUser={"id": FAN, "isRestricted": True})], None, 1, "OF isRestricted alone"),
        ([row()], frozenset({FAN}), 0, "in the Unread set, read row"),
        ([row()], frozenset({FAN2}), 1, "set names another Fan"),
        ([row()], frozenset(), 1, "empty set"),
        ([row(), row(), row(FAN2)], None, 2, "duplicate Fan once"),
        ([row(), row(unreadMessagesCount=1)], None, 1, "first row per Fan decides"),
        ([row(withUser={})], None, 0, "no Fan id"),
        (filler + [row()], None, 0, "26th row past the window"),
        (filler[:24] + [row()], None, 1, "25th row in the window"),
        (filler[:24] + [filler[0], row()], None, 1, "a duplicate takes no window slot"),
        ([], None, 0, "empty"),
    ]
    for rs, fans, want, why in rows:
        assert d.amber_count(rs, me, {REG}, fans) == want, (why, d.amber_count(rs, me, {REG}, fans))
    assert d.amber_count(rows[0][0], str(me), {REG}, None) == 1, "me as str"


def case_overlay():
    me, ask = 999, T0

    def row(fan=FAN, unread=0, sender=None):
        return {"withUser": {"id": fan}, "unreadMessagesCount": unread, "hasUnread": bool(unread),
                "isMutedNotifications": False, "lastMessage": {"id": 1, "fromUser": {"id": fan if sender is None else sender}}}
    creator_last = {**row(), "lastMessage": {"id": 1, "fromUser": {"id": me}}}
    unread = {**row(), "unreadMessagesCount": 1, "hasUnread": True}
    rows = [
        ([row()], {FAN: {d.ECHO: ask + 1}}, ask, [creator_last], "echo after ask, read Fan-last -> Creator-last"),
        ([row()], {FAN: {d.ECHO: ask}}, ask, [row()], "echo at the ask: unchanged"),
        ([row()], {FAN: {d.ECHO: ask - 1}}, ask, [row()], "echo before ask: unchanged"),
        ([row(unread=2)], {FAN: {d.ECHO: ask + 1}}, ask, [creator_last], "echo on an unread row: read, Creator-last"),
        ([row()], {FAN: {d.DM: ask + 1}}, ask, [unread], "DM after ask on a read row -> unread"),
        ([row(unread=3)], {FAN: {d.DM: ask + 1}}, ask, [{**row(unread=3)}], "DM on an unread row: count kept"),
        ([row(sender=me)], {FAN: {d.DM: ask + 1}}, ask, [unread], "DM: Fan-last again"),
        ([row()], {FAN: {d.ECHO: ask + 1, d.DM: ask + 2}}, ask, [unread], "echo then DM -> unread"),
        ([row()], {FAN: {d.DM: ask + 1, d.ECHO: ask + 2}}, ask, [creator_last], "DM then echo -> Creator-last"),
        ([row()], {FAN: {d.DM: ask + 1, d.READ: ask + 2}}, ask, [row()], "DM then our read -> read, Fan-last"),
        ([row()], {FAN: {d.ECHO: ask + 1, d.READ: ask + 2}}, ask, [creator_last], "echo then a read: still Creator-last"),
        ([row()], {FAN: {d.READ: ask + 1, d.DM: ask + 2}}, ask, [unread], "read then DM -> unread"),
        ([row()], {FAN: {d.UNREAD: ask + 1}}, ask, [unread], "mark unread -> unread"),
        ([row()], {FAN: {d.DM: ask + 1, d.ECHO: ask + 1}}, ask, [unread], "same ms echo and DM: the DM last"),
        ([row()], {FAN: {d.DM: ask + 1, d.READ: ask + 1}}, ask, [unread], "same ms read and DM: the DM last"),
        ([row()], {FAN: {d.UNREAD: ask + 1, d.READ: ask + 1}}, ask, [unread], "same ms read and unread: unread last"),
        ([row()], {FAN2: {d.ECHO: ask + 1}}, ask, [row()], "Fan not in window: no row added"),
        ([row()], {FAN: {d.ECHO: ask + 1}}, None, [row()], "no ask time: unchanged"),
        ([], {FAN: {d.DM: ask + 1}}, ask, [], "empty"),
    ]
    for rs, events, asked, want, why in rows:
        before = repr(rs)
        assert d.overlay(rs, events, asked, me) == want, (why, d.overlay(rs, events, asked, me))
        assert repr(rs) == before, ("input not mutated", why)
    assert d.amber_count(d.overlay([row()], {FAN: {d.ECHO: ask + 1}}, ask, str(me)), me, set(), None) == 0, "me as str"


def case_reply_row_fence():
    me = 999

    def row(created=None, sender=FAN):
        last = {"id": 1, "fromUser": {"id": sender}}
        if created is not None:
            last["createdAt"] = created
        return {"withUser": {"id": FAN}, "unreadMessagesCount": 0, "hasUnread": False,
                "isMutedNotifications": False, "lastMessage": last}

    def replied(r):
        return {**r, "lastMessage": {**r["lastMessage"], "fromUser": {"id": me}}}
    newer, older = d.created_ms(row(AFTER)), d.created_ms(row(BEFORE))
    rows = [
        (row(AFTER), ASK, row(AFTER), "fan-last newer than the reply: kept"),
        (row(AFTER), newer, row(AFTER), "fan-last at the reply's ms: the Fan's message last"),
        (row(BEFORE), ASK, replied(row(BEFORE)), "fan-last older: Creator-last"),
        (row(), ASK, replied(row()), "no createdAt: Creator-last"),
        (row(AFTER, sender=me), ASK, row(AFTER, sender=me), "Creator-last newer: Creator-last"),
    ]
    for r, at, want, why in rows:
        assert d.reply_row(r, me, at) == want, (why, d.reply_row(r, me, at))
    assert d.overlay([row(AFTER)], {FAN: {d.ECHO: ASK}}, older, me) == [row(AFTER)], "overlay echo older than the row"
    assert d.amber_count(d.overlay([row(AFTER)], {FAN: {d.ECHO: ASK}}, older, me), me, set(), None) == 1

def case_amber_one_predicate():
    me = 999
    owed = {"withUser": {"id": REG}, "unreadMessagesCount": 0, "isMutedNotifications": False,
            "lastMessage": {"fromUser": {"id": REG}}}
    assert d.amber_count([owed], me, {REG}, None) == 0
    real = d.excluded_from_badges
    d.excluded_from_badges = lambda fan, row, ids: fan != REG and real(fan, row, ids)
    try:
        assert d.amber_count([owed], me, {REG}, None) == 1, "amber follows the one predicate"
    finally:
        d.excluded_from_badges = real


def case_ws_confirmation():
    st = d.adjust(_held(3), DmIn(FAN, UNKNOWN), T0 + 100)
    for observed in (0, 2, 3, 6):
        st2, actions = d.reconcile(st, observed, T0 + 200, T0 + 210, via="ws")
        assert actions == () and st2.n == observed and st2.due is None, (observed, actions, st2)
        assert st2.at == T0 + 200 and st2.seen == T0 + 200, st2
    due = State(n=5, at=T0, seen=T0, due=T0)
    st2, actions = d.reconcile(due, 1, T0 + 50, T0 + 60, via="ws")
    assert st2.due == T0 and actions == (), ("a frame neither serves nor asks a window read", st2)
    st2, actions = d.reconcile(_held(3), 3, T0 + 300, T0 + 310, via="ws")
    assert actions == () and st2.n == 3 and st2.at == T0 + 300, ("same value: `at` moves", st2)
    st2, actions = d.reconcile(State(), 4, T0, T0, via="ws")
    assert actions == () and st2.n == 4, ("a first frame seeds the total", st2)


def case_frame_vs_users_me_order():
    st, _ = d.reconcile(State(), 4, T0 + 200, T0 + 200, via="ws")
    st2, actions = d.reconcile(st, 5, T0 + 100, T0 + 300)
    assert st2 == st and actions == (), ("a /users/me asked before the frame changes nothing", st2)
    st, _ = d.reconcile(State(), 5, T0 + 200, T0 + 200)
    st2, actions = d.reconcile(st, 4, T0 + 100, T0 + 300, via="ws")
    assert st2 == st and actions == (), ("a frame received before the /users/me ask changes nothing", st2)
    st, _ = d.reconcile(State(), 4, T0 + 100, T0 + 100, via="ws")
    st2, _ = d.reconcile(st, 5, T0 + 200, T0 + 300)
    assert (st2.n, st2.at) == (5, T0 + 200), ("a /users/me asked after the frame wins", st2)
    st, _ = d.reconcile(State(), 5, T0 + 100, T0 + 300)
    st2, _ = d.reconcile(st, 4, T0 + 200, T0 + 200, via="ws")
    assert (st2.n, st2.at) == (4, T0 + 200), ("a frame received after the /users/me ask wins", st2)


def case_adjust_vs_ws_at():
    held, _ = d.reconcile(State(), 3, T0 + 100, T0 + 100, via="ws")
    assert held.ws_at == T0 + 100, held
    rows = [
        (ReadFlip(FAN, 0, T0 + 50, UNREAD), T0 + 200, 3, READ, "mark read asked before the frame: counted"),
        (ReadFlip(FAN, 0, T0 + 100, UNREAD), T0 + 200, 3, READ, "mark read asked at the frame: counted"),
        (ReadFlip(FAN, 0, T0 + 150, UNREAD), T0 + 200, 2, READ, "mark read asked after the frame: -1"),
        (ReadFlip(FAN, 1, T0 + 50, READ), T0 + 200, 3, UNREAD, "mark unread before the frame: counted"),
        (ReadFlip(FAN, 1, T0 + 150, READ), T0 + 200, 4, UNREAD, "mark unread after the frame: +1"),
        (Reply(FAN, UNREAD), T0 + 100, 3, READ, "reply landed at the frame: counted"),
        (Reply(FAN, UNREAD), T0 + 150, 2, READ, "reply landed after the frame: -1"),
        (DmIn(FAN, READ, T0 + 50), T0 + 200, 3, UNREAD, "DM made before the frame: counted"),
        (DmIn(FAN, UNKNOWN, T0 + 100), T0 + 200, 3, UNREAD, "DM at the frame: counted, no slack"),
        (DmIn(FAN, READ, T0 + 150), T0 + 200, 4, UNREAD, "DM after the frame: +1"),
    ]
    for ev, now, want, rec, why in rows:
        st = d.adjust(held, ev, now)
        assert st.n == want and d.prior_of(st, FAN, None) == rec, (why, st)
        assert st.ws_at == T0 + 100, (why, st)
        if want == 3:
            assert st.adj == () and d.slack(st) == 0, (why, st)
    st = d.adjust(held, ReadFlip(None, 0, T0 + 50, UNKNOWN), T0 + 200)
    assert st.n == 3 and st.adj == (), ("mark all asked before the frame: counted", st)
    st = d.adjust(held, ReadFlip(None, 0, T0 + 150, UNKNOWN), T0 + 200)
    assert st.n == 0, ("mark all asked after the frame: moves", st)
    me, _ = d.reconcile(held, 5, T0 + 200, T0 + 300)
    assert me.ws_at == T0 + 100, ("a /users/me leaves `ws_at`", me)
    st = d.adjust(me, ReadFlip(FAN, 0, T0 + 50, UNREAD), T0 + 400)
    assert st.n == 5, ("both confirmations already count it", st)
    st = d.adjust(_held(3), ReadFlip(FAN, 0, T0 + 50, UNREAD), T0 + 200)
    assert st.n == 2, ("no frame taken: moves as before", st)


def case_badge_version():
    a = {"n": 3, "at": T0}
    rows = [
        (None, None, 0, 0, "nothing then nothing"),
        (None, a, 0, 1, "the slot appears"),
        (a, {"n": 3, "at": T0 + 5}, 1, 1, "`at` alone"),
        (a, {"n": 2, "at": T0}, 1, 2, "`n` moved"),
        (a, {"n": None, "at": T0}, 4, 5, "`n` to unknown"),
        (a, {"n": 3, "at": T0, "grey": "r_unknown"}, 1, 2, "any other key"),
        (a, None, 2, 3, "the slot goes"),
    ]
    for prev, nxt, v, want, why in rows:
        assert d.badge_version(prev, nxt, v) == want, (why, prev, nxt, v)



def case_phase_c_causes():
    held, polled = State(n=3, at=T0), State(n=3, at=T0, poll_at=T0)
    rows = [
        (State(), 0, T0 - 1, T0, "dead", "dead", "dead since boot: dead, not unseeded"),
        (State(), None, None, T0, "proxy_down", "proxy_down", "proxy down since boot"),
        (held, 0, T0 - 1, None, "dead", "dead", "Dead session"),
        (held, None, None, None, "dead", "dead", "dead before socket_down and r_unknown"),
        (held, 0, None, None, "proxy_down", "proxy_down", "proxy down before socket_down"),
        (polled, 0, None, T0 + 45_000, None, None, "socket down, polled 45 s ago: confirmed"),
        (polled, 0, None, T0 + 45_001, None, "stale", "socket down, newest poll older than 45 s"),
        (polled, None, None, T0 + 1_000, None, "r_unknown", "polled, no R"),
        (State(n=3, at=T0 + 5, poll_at=T0), 0, None, T0 + 10, None, None, "a /users/me during the outage"),
        (State(n=3, at=T0 + 50_000, poll_at=T0), 0, None, T0 + 50_000, None, "stale", "a /users/me: the poll ages"),
        (State(n=3, at=T0 + 5, poll_at=T0, ws_at=T0 + 5), 0, None, T0 + 10, None, "socket_down",
         "a frame after the poll: that poll was an earlier outage's"),
        (polled, 0, T0 + 1, T0 + 10, None, "socket_down", "a poll before the reconnect: no confirmation since"),
        (polled, 0, T0 - 1, T0 + 60_000, None, None, "socket up: never stale"),
    ]
    for st, r, up_since, now, cause, want, why in rows:
        assert d.grey_reason(st, r, up_since, now, cause) == want, (why, d.grey_reason(st, r, up_since, now, cause))
    assert d.slot(polled, d.Restricted(1, False, 0), None, T0 + 50_000) == {"n": 2, "at": T0, "grey": "stale"}, "stale keeps `n`"


def case_poll_confirmation():
    st = d.adjust(_held(3), DmIn(FAN, UNKNOWN), T0 + 100)
    for observed in (0, 2, 6):
        st2, actions = d.reconcile(st, observed, T0 + 200, T0 + 210, via="poll")
        assert actions == () and st2.n == observed and st2.due is None, (observed, actions, st2)
        assert (st2.at, st2.seen, st2.poll_at, st2.ws_at) == (T0 + 200, T0 + 200, T0 + 200, None), st2
    due = State(n=5, at=T0, seen=T0, due=T0)
    st2, actions = d.reconcile(due, 1, T0 + 50, T0 + 60, via="poll")
    assert st2.due == T0 and actions == (), ("a poll neither serves nor asks a window read", st2)
    st2, _ = d.reconcile(State(n=5, at=T0, seen=T0 + 100), 4, T0 + 50, T0 + 60, via="poll")
    assert st2 == State(n=5, at=T0, seen=T0 + 100), ("a poll asked before the newest answer changes nothing", st2)
    st3, _ = d.reconcile(d.reconcile(State(), 4, T0, T0, via="poll")[0], 4, T0 + 10, T0 + 10, via="ws")
    assert st3.poll_at == T0 and st3.at == T0 + 10, ("a later frame confirms; the poll stamp stays", st3)


def case_adjust_keeps_poll_confirmation():
    state = State(n=3, at=T0, poll_at=T0)
    moved = d.adjust(state, ReadFlip(FAN, 0, T0 + 5, UNREAD), T0 + 10)
    assert moved.poll_at == T0 and d.slot(moved, d.Restricted(0, False, 0), None, T0 + 10)["grey"] is None


_harness.run()
