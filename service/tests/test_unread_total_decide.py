#!/usr/bin/env python3
"""unread_total_decide (phase-02 seam 3), as tables. Pure: no clock, no I/O; times are passed (epoch ms).

  case_count:                 an int `chatMessagesCount` (>= 0) is OF's number; bool, str, float, negative, missing or
                              a non-dict body -> None (no confirmation).
  case_first_confirmation:    no total yet: OF's number adopted at the read's ask time, published.
  case_confirmation_adopts:   a confirmation adopts OF's number whatever the held one; a changed `n` publishes (and,
                              unexplained by any adjustment, logs drift).
  case_unchanged_n:           the same `n`: `at` moves to the ask time, nothing published.
  case_older_read_never_wins: a read asked before the held `at` (landed late) changes nothing, publishes nothing.
  case_slot:                  `values.unread_total`: null before the first confirmation, else `{n, at}`.
  case_prior_from_the_held_row: the held page-0 row's flag is the chat's prior; no row -> unknown.
  case_adjust_known_prior:    the adjustment table, known prior: DM into read +1 / unread 0; our mark read on unread
                              -1 / read 0; mark unread on read +1 / unread 0.
  case_clamped_at_zero:       a move never takes the total below 0.
  case_no_total_yet:          before the first confirmation nothing moves (`n` stays null).
  case_flips_stamped_pre_write: a flip is stamped with its pre-write `at`, a DM with its arrival: a confirmation asked
                              between them re-applies the DM only.
  case_reconcile_reapplies_after_ask: OF's number plus only the adjustments stamped after the read's ask time; those
                              stay held for the next confirmation, the rest are dropped.
  case_drift:                 expected = the held value at the ask time; OF lower or higher -> `log_drift`; equal or
                              a first confirmation -> none.
  case_adjust_unknown_prior:  the table's unknown column: DM +1 slack +1; mark read -1; mark unread +1 slack +1;
                              reply 0 slack +1.
  case_reply:                 a reply into an unread chat -1, into a read chat 0.
  case_prior_of_order:        our own record this Cycle first (what our flips, replies and DMs set), then the held row,
                              else unknown; a record lives until the second confirmation after it.
  case_reply_then_mark_read_once: a reply into an unread chat then a mark read of it (window dropped by then) -> -1 once.
  case_two_dms_into_one_read_chat: +1 once, held row or not.
  case_mark_all:              `n` = the chats that got a DM stamped after the mark all's pre-write `at`; a confirmation
                              asked before that `at` re-applies it.
  case_slack:                 unknown-prior moves add slack; a lower OF number within it is no drift, beyond it is;
                              slack resets at each confirmation (only moves after the ask stay counted).
  case_drift_actions:         OF lower than expected beyond slack -> `window_read` + `log_drift` (the drift pending
                              from that ask); within slack -> none; higher -> `log_drift` only.
  case_one_window_read_per_drift: a second drift while one is pending asks no second read; a window read asked at or
                              after the drift's confirmation serves it, one asked before leaves it pending; a drift
                              after that asks again (the refresher holds it to its next Cycle).
  case_flips_with_old_rows:   old vs new page-0 rows: each fan whose unread state flipped, either way; a row new to
                              or gone from the window, or unchanged, none; drift or not alike.
  case_flips_without_old_rows: no old window held: a drift read -> `(fan, 0)` per read row; a routine read -> none.
  case_flips_never_clear_newer: a row whose `lastMessage` is newer than the read's ask time is never cleared, with or
                              without old rows; undated rows are.

Run: ./venv/bin/python service/tests/test_unread_total_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import unread_total_decide as d  # noqa: E402
from unread_total_decide import (  # noqa: E402
    LOG_DRIFT, PUBLISH, READ, UNKNOWN, UNREAD, WINDOW_READ, DmIn, ReadFlip, Reply, State,
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
    assert st == State(n=12, at=T0), st
    assert actions == (PUBLISH,), actions


def case_confirmation_adopts():
    down, up = (PUBLISH, LOG_DRIFT, WINDOW_READ), (PUBLISH, LOG_DRIFT)
    rows = [
        (State(n=12, at=T0), 1, T0 + 1000, State(n=1, at=T0 + 1000, due=T0 + 1000), down, "lower: OF's number"),
        (State(n=1, at=T0), 7, T0 + 1000, State(n=7, at=T0 + 1000), up, "higher: OF's number"),
        (State(n=3, at=T0), 0, T0 + 1000, State(n=0, at=T0 + 1000, due=T0 + 1000), down, "to zero"),
    ]
    for held, observed, asked, want, acts, why in rows:
        st, actions = d.reconcile(held, observed, asked, asked + 10)
        assert st == want and actions == acts, (why, st, actions)


def case_unchanged_n():
    st, actions = d.reconcile(State(n=3, at=T0), 3, T0 + 1000, T0 + 1010)
    assert st == State(n=3, at=T0 + 1000), ("`at` is the newest confirmation's ask time", st)
    assert actions == (), ("an unchanged `n` publishes nothing", actions)


def case_older_read_never_wins():
    held = State(n=3, at=T0 + 2000)
    for observed in (3, 5):
        st, actions = d.reconcile(held, observed, T0 + 1000, T0 + 2500)
        assert st == held and actions == (), (observed, st, actions)
    st, actions = d.reconcile(held, 5, T0 + 2000, T0 + 2500)   # same ask time: a confirmation, adopted
    assert st == State(n=5, at=T0 + 2000) and actions == (PUBLISH, LOG_DRIFT), (st, actions)


def case_slot():
    assert d.slot(State()) is None
    assert d.slot(State(n=3, at=T0)) == {"n": 3, "at": T0}


FAN, FAN2 = 501, 502


def _held(n=3, at=T0):
    return State(n=n, at=at)


def case_prior_from_the_held_row():
    rows = [
        ({"withUser": {"id": FAN}, "hasUnread": True, "unreadMessagesCount": 2}, UNREAD, "flag set"),
        ({"withUser": {"id": FAN}, "hasUnread": False, "unreadMessagesCount": 0}, READ, "flag clear"),
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
    assert st.n is None and d.slot(st) is None, st


def case_flips_stamped_pre_write():
    st = d.adjust(_held(3), ReadFlip(FAN, 0, T0 + 100, UNREAD), T0 + 500)    # write asked T0+100, landed T0+500
    st = d.adjust(st, DmIn(FAN2, READ), T0 + 400)
    assert st.n == 3, st
    st2, actions = d.reconcile(st, 2, T0 + 300, T0 + 600)   # asked after the flip's pre-write `at`, before the DM
    assert st2.n == 3 and st2.at == T0 + 300, ("OF's 2 + the DM; the flip is in OF's number", st2)
    assert PUBLISH not in actions, actions


def case_reconcile_reapplies_after_ask():
    st = d.adjust(_held(3), DmIn(FAN, READ), T0 + 100)          # 4
    st = d.adjust(st, DmIn(FAN2, READ), T0 + 300)               # 5
    st2, actions = d.reconcile(st, 4, T0 + 200, T0 + 350)
    assert st2.n == 5 and st2.at == T0 + 200 and actions == (), ("OF's 4 + FAN2's DM", st2, actions)
    st3, actions = d.reconcile(st2, 5, T0 + 400, T0 + 450)
    assert (st3.n, st3.at, st3.adj) == (5, T0 + 400, ()) and actions == (), ("FAN2's DM is in OF's number now", st3)
    st4, actions = d.reconcile(st2, 1, T0 + 250, T0 + 450)
    assert st4.n == 2 and PUBLISH in actions, ("OF's 1 + FAN2's DM still after the ask", st4)


def case_drift():
    st = d.adjust(_held(3), DmIn(FAN, READ), T0 + 100)          # held 4 from T0+100
    assert d.expected(st, T0 + 50) == 3 and d.expected(st, T0 + 200) == 4
    assert d.expected(State(), T0) is None
    rows = [
        (4, (), "OF agrees: no drift"),
        (2, (PUBLISH, LOG_DRIFT, WINDOW_READ), "OF lower: a read made elsewhere, drift down"),
        (6, (PUBLISH, LOG_DRIFT), "OF higher: drift up, logged only"),
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
    st = d.adjust(st, ReadFlip(FAN, 0, T0 + 25, d.prior_of(st, FAN, None)), T0 + 30)   # the automation's mark read
    assert st.n == 2, ("-1 once", st)


def case_two_dms_into_one_read_chat():
    read_row = {"withUser": {"id": FAN}, "hasUnread": False}
    for row in (read_row, None):
        st = _held(3)
        for t in (T0 + 10, T0 + 20):
            st = d.adjust(st, DmIn(FAN, d.prior_of(st, FAN, row)), t)
        assert st.n == 4, ("+1 once", row, st)


def case_mark_all():
    st = d.adjust(_held(5), DmIn(FAN2, READ), T0 + 50)              # before the mark all's `at`: read by it
    st = d.adjust(st, DmIn(FAN, READ), T0 + 200)                    # after it: stays unread
    st = d.adjust(st, ReadFlip(None, 0, T0 + 100, UNKNOWN), T0 + 300)
    assert st.n == 1 and d.slack(st) == 0, st
    assert d.prior_of(st, FAN2, None) == READ and d.prior_of(st, FAN, None) == UNREAD, st
    st0 = d.adjust(_held(5), ReadFlip(None, 0, T0 + 100, UNKNOWN), T0 + 300)
    assert st0.n == 0, ("no DM after it: 0", st0)
    st2, _ = d.reconcile(st, 7, T0 + 80, T0 + 310)                  # asked before the mark all: it re-applies
    assert st2.n == 1, st2
    st3 = d.adjust(st, DmIn(FAN2, d.prior_of(st, FAN2, None)), T0 + 400)
    assert st3.n == 2, ("a DM after the mark all moves as usual", st3)


def case_slack():
    st = d.adjust(_held(3), DmIn(FAN, UNKNOWN), T0 + 100)           # 4, slack 1 (FAN may have been unread)
    rows = [
        (4, (), "OF agrees"),
        (3, (PUBLISH,), "lower within slack: no drift"),
        (2, (PUBLISH, LOG_DRIFT, WINDOW_READ), "lower beyond slack: drift down"),
    ]
    for observed, want, why in rows:
        st2, actions = d.reconcile(st, observed, T0 + 200, T0 + 210)
        assert actions == want and d.slack(st2) == 0, (why, actions, st2)
    st = d.adjust(st, DmIn(FAN2, UNKNOWN), T0 + 300)                # after the next ask: re-applied, still slack
    st2, _ = d.reconcile(st, 4, T0 + 200, T0 + 310)
    assert st2.n == 5 and d.slack(st2) == 1, st2


def case_drift_actions():
    st = d.adjust(_held(3), DmIn(FAN, UNKNOWN), T0 + 100)           # 4, slack 1
    rows = [
        (4, (), None, "OF agrees: nothing"),
        (3, (PUBLISH,), None, "lower within slack: no read, no log"),
        (2, (PUBLISH, LOG_DRIFT, WINDOW_READ), T0 + 200, "lower beyond slack: one window read + the drift log"),
        (6, (PUBLISH, LOG_DRIFT), None, "higher: logged only, no read"),
    ]
    for observed, want, due, why in rows:
        st2, actions = d.reconcile(st, observed, T0 + 200, T0 + 210)
        assert actions == want and st2.due == due, (why, actions, st2)
    assert d.reconcile(State(), 0, T0, T0)[0].due is None, "a first confirmation asks no read"


def case_one_window_read_per_drift():
    st, actions = d.reconcile(_held(5), 3, T0 + 100, T0 + 110)
    assert WINDOW_READ in actions and st.due == T0 + 100, (actions, st)
    st2, actions = d.reconcile(st, 1, T0 + 200, T0 + 210)            # a second drift, the first still pending
    assert actions == (PUBLISH, LOG_DRIFT) and st2.due == T0 + 200, ("no second ask; due moves to it", actions, st2)
    assert d.read_window(st2, T0 + 50).due == T0 + 200, "a read asked before the drift's confirmation: still due"
    assert d.read_window(st2, T0 + 150).due == T0 + 200, "a read in flight since the first drift does not serve the second"
    for asked in (T0 + 200, T0 + 300):
        assert d.read_window(st2, asked).due is None, ("a read asked at or after it serves it", asked)
    done = d.read_window(st2, T0 + 300)
    assert (done.n, done.at, done.adj, done.rec) == (st2.n, st2.at, st2.adj, st2.rec), "only `due` moves"
    assert d.read_window(_held(5), T0 + 300) == _held(5), "nothing pending: unchanged"
    st3, actions = d.reconcile(done, 0, T0 + 400, T0 + 410)          # a later read made elsewhere
    assert WINDOW_READ in actions and st3.due == T0 + 400, (actions, st3)
    st4 = d.adjust(st2, DmIn(FAN, READ), T0 + 220)
    assert st4.due == T0 + 200, ("a move keeps the drift pending", st4)


FAN3 = 503


def _r(fan, unread, created=None):
    row = {"withUser": {"id": fan}, "hasUnread": unread, "unreadMessagesCount": 1 if unread else 0}
    if created is not None:
        row["lastMessage"] = {"id": fan * 10, "createdAt": created}
    return row


ASK = 1_763_632_800_000                     # 2025-11-20T10:00:00Z
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


_harness.run()
