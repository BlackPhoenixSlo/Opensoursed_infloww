#!/usr/bin/env python3
"""
funnel_decide.decide — table tests over reply_mass_funnel's pure per-fan status
machine (docs/reducer-scan.md, Non-React #9).

No DB, no LLM, no OF: every row is (entry, event) -> (entry', effects).

  case_due_table:        past the script's end -> done; else nothing (go on).
  case_past_end_table:   past the end is done on EVERY event (never an IndexError).
  case_checked_table:    the precedence run() used to carry inline: offer taken
                         (halt, or a `next.bought` branch, stamped) beats the reply
                         gate; no reply -> the interval walk, a spent window's
                         `next.ignored` branch (never early); a reply -> Generate.
                         keyword beats bought inside a branch; loop guard; off-end.
  case_blocked_unreachable_table:  blocked backs off and stays pending; a dead
                         chat ends the walk.
  case_sent_table:       routeless PPV is terminal; linear +1 with the sent step's
                         first interval; last step -> done; `next` routes (keyword
                         only on a substantive reply), guard armed only with `next`.
  case_whole_funnel_walk:  one fan: wait, reply, send, keyword branch, PPV, bought.
  case_offer_since_table:  the `bought` fact's baseline: our last PPV, else the broadcast.

Run: ./venv/bin/python service/tests/test_funnel_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from automations import funnel_decide as fd  # noqa: E402
from automations.funnel_decide import (  # noqa: E402
    Block, Blocked, Branch, Checked, Complete, Convert, Due, Entry, Facts, Generate, Save,
    Script, Sent, Unreachable, Wait, decide,
)

N = datetime(2026, 10, 30, 12, 0, 0)


def m(minutes: float) -> datetime:
    """`minutes` after N."""
    return N + timedelta(minutes=minutes)


# ── House funnel ──────────────────────────────────────────────────────

LINEAR = [{"step": 1, "messages": ["a"], "check_intervals_min": [3, 5, 7]},
          {"step": 2, "messages": ["b"]},
          {"step": 3, "messages": ["c"]}]
BRANCHY = [
    {"step": 1, "messages": ["hi"], "check_intervals_min": [3, 5, 7],
     "next": {"bought": 4, "ignored": 3, "keyword": {"more": 5}, "default": 2}},
    {"step": 2, "messages": ["more"]},
    {"step": 3, "messages": ["nudge"]},
    {"step": 4, "type": "paid_ppv", "messages": ["ppv"], "next": {"default": 5}},
    {"step": 5, "messages": ["thanks"]},
]
ROUTELESS_PPV = [{"step": 1, "messages": ["a"]},
                 {"step": 2, "type": "paid_ppv", "messages": ["ppv"]},
                 {"step": 3, "messages": ["never"]}]
# A `next.bought` whose only other key is default; a branch with no bought key.
BOUGHT_OFF_END = [{"step": 1, "messages": ["a"], "next": {"bought": 9}}]
NO_BOUGHT_KEY = [{"step": 1, "messages": ["a"], "next": {"default": 1}}]
# A keyword-only `next` (no default): a miss falls back to +1.
# A backward route: step 3 (idx 2) loops back to step 1 (idx 0).
BACKWARD = [{"step": 1, "messages": ["a"], "check_intervals_min": [1, 2, 3]},
            {"step": 2, "messages": ["b"]},
            {"step": 3, "messages": ["c"], "check_intervals_min": [6, 8, 12],
             "next": {"default": 1}}]
# Jumped onto idx 2 (an `ignored` route) from idx 0's 2-long list; idx 1 (c - 1)
# has a 4-long one: the window that runs out is the SENT step's (2 checks).
JUMP_IGNORED = [{"step": 1, "messages": ["a"], "check_intervals_min": [2, 5]},
                {"step": 2, "messages": ["b"], "check_intervals_min": [1, 1, 1, 1]},
                {"step": 3, "messages": ["c"], "next": {"ignored": 4}},
                {"step": 4, "messages": ["d"]}]
KW_ONLY = [{"step": 1, "messages": ["a"], "next": {"keyword": {"more": 3}}},
           {"step": 2, "messages": ["b"]},
           {"step": 3, "messages": ["c"]}]


def script(steps, max_hops=20) -> Script:
    return Script(steps=steps, num_to_idx={s["step"]: i for i, s in enumerate(steps)},
                  max_hops=max_hops)


P0 = Entry(current_step=0, next_check_at=N, check_count=0, status="pending", hops=0)
QUIET = Facts()
REPLIED = Facts(replied=True, substantive=True, reply_text="ok")
MORE = Facts(replied=True, substantive=True, reply_text="send <b>MORE</b> pls")
MORE_EMOJI = Facts(replied=True, substantive=False, reply_text="more")
BOUGHT = Facts(bought=True)
BOUGHT_MORE = Facts(replied=True, bought=True, substantive=True, reply_text="more")


def _check(rows) -> None:
    """Run every row, collect every mismatch, fail once naming them all."""
    bad = []
    for rid, entry, ev, sc, want_entry, want_fx in rows:
        got_entry, got_fx = decide(entry, ev, sc)
        if got_fx != want_fx:
            bad.append(f"{rid}: effects {got_fx} != {want_fx}")
        if want_entry is not None and got_entry != want_entry:
            bad.append(f"{rid}: entry {got_entry} != {want_entry}")
    assert not bad, "\n  " + "\n  ".join(bad)


def case_due_table():
    _check([
        ("inside the script: nothing, go on to the gates",
         P0, Due(N), script(LINEAR), P0, []),
        ("on the last step: still inside", replace(P0, current_step=2), Due(N), script(LINEAR),
         replace(P0, current_step=2), []),
        ("past the end (a shortened funnel): done, saved, completed",
         replace(P0, current_step=3), Due(N), script(LINEAR),
         replace(P0, current_step=3, status="done"), [Save(), Complete()]),
        ("an empty-after-edit index far past the end: done",
         replace(P0, current_step=9), Due(N), script(LINEAR),
         replace(P0, current_step=9, status="done"), [Save(), Complete()]),
    ])


def case_past_end_table():
    """The past-the-end guard runs before any event is read, so a shell that
    skipped Due still cannot index past the script."""
    past = replace(P0, current_step=3)
    done = replace(past, status="done")
    _check([(f"past the end x {type(ev).__name__}: done, completed", past, ev,
             script(LINEAR), done, [Save(), Complete()])
            for ev in (Due(N), Checked(N, QUIET), Checked(N, REPLIED), Checked(N, BOUGHT),
                       Blocked(N, ("no_media",)), Unreachable(N), Sent(N, REPLIED))])


def case_checked_table():
    s_lin, s_br = script(LINEAR), script(BRANCHY)
    _check([
        # ── offer taken beats everything else on the check
        ("bought, no `next`: halt done/offer_taken, converted",
         P0, Checked(N, BOUGHT), s_lin, replace(P0, status="done", last_error="offer_taken"),
         [Save(), Convert()]),
        ("bought AND replied, no `next`: still offer_taken, never a send",
         P0, Checked(N, Facts(replied=True, bought=True, substantive=True, reply_text="hi")),
         s_lin, replace(P0, status="done", last_error="offer_taken"), [Save(), Convert()]),
        ("bought, a `next` with no bought key: offer_taken (the legacy halt)",
         P0, Checked(N, BOUGHT), script(NO_BOUGHT_KEY),
         replace(P0, status="done", last_error="offer_taken"), [Save(), Convert()]),
        ("bought, `next.bought`: branch now, stamped, hop counted, due at once",
         P0, Checked(N, BOUGHT), s_br,
         replace(P0, current_step=3, last_ppv_sent_at=N, hops=1, check_count=0, next_check_at=N),
         [Save(), Branch()]),
        ("bought + a keyword reply, `next.bought`: the keyword route wins (precedence)",
         P0, Checked(N, BOUGHT_MORE), s_br,
         replace(P0, current_step=4, last_ppv_sent_at=N, hops=1, next_check_at=N),
         [Save(), Branch()]),
        ("bought, `next.bought` to an unknown step: +1 fallback off the end -> done",
         P0, Checked(N, BOUGHT), script(BOUGHT_OFF_END),
         replace(P0, current_step=1, last_ppv_sent_at=N, hops=1, status="done"),
         [Save(), Complete(), Branch()]),
        ("bought branch at the hop cap: done/loop_guard, not routed",
         replace(P0, hops=19), Checked(N, BOUGHT), s_br,
         replace(P0, hops=20, last_ppv_sent_at=N, status="done", last_error="loop_guard"),
         [Save(), Complete(), Branch()]),
        # ── no reply: the interval walk (step 0 polls on its own list)
        ("no reply, check 0 -> check 1 at the list's next gap (+5)",
         P0, Checked(N, QUIET), s_lin, replace(P0, check_count=1, next_check_at=m(5)),
         [Save(), Wait()]),
        ("no reply, check 1 -> check 2 (+7)",
         replace(P0, check_count=1), Checked(N, QUIET), s_lin,
         replace(P0, check_count=2, next_check_at=m(7)), [Save(), Wait()]),
        ("no reply, list spent -> the 10-minute fallback forever",
         replace(P0, check_count=2), Checked(N, QUIET), s_lin,
         replace(P0, check_count=3, next_check_at=m(10)), [Save(), Wait()]),
        ("no reply on step 2 polls on the SENT step's list (step 1: default [2,4,10])",
         replace(P0, current_step=2), Checked(N, QUIET), s_lin,
         replace(P0, current_step=2, check_count=1, next_check_at=m(4)), [Save(), Wait()]),
        ("no reply, `next.ignored`, window not spent: wait, never branched early",
         replace(P0, check_count=1), Checked(N, QUIET), s_br,
         replace(P0, check_count=2, next_check_at=m(7)), [Save(), Wait()]),
        ("no reply, `next.ignored`, window spent (check 2 of [3,5,7]): branch now",
         replace(P0, check_count=2), Checked(N, QUIET), s_br,
         replace(P0, current_step=2, check_count=0, next_check_at=N, hops=1),
         [Save(), Branch()]),
        ("no reply, `next.ignored`, at the hop cap: done/loop_guard",
         replace(P0, check_count=2, hops=2), Checked(N, QUIET), script(BRANCHY, max_hops=3),
         replace(P0, check_count=2, hops=3, status="done", last_error="loop_guard"),
         [Save(), Complete(), Branch()]),
        # ── a reply: generate + send, nothing moves yet
        ("replied, linear: Generate, entry untouched", replace(P0, check_count=2),
         Checked(N, REPLIED), s_lin, replace(P0, check_count=2), [Generate()]),
        ("replied with a keyword, branchy: still Generate (the send routes)",
         P0, Checked(N, MORE), s_br, P0, [Generate()]),
        # ── more precedence cells
        ("bought + a plain (non-keyword) reply, `next.bought`: the bought route, no send",
         P0, Checked(N, Facts(replied=True, bought=True, substantive=True, reply_text="ok")), s_br,
         replace(P0, current_step=3, last_ppv_sent_at=N, hops=1, next_check_at=N),
         [Save(), Branch()]),
        ("no reply, `next.ignored`, window over-spent (check 5 of [3,5,7]): branch now",
         replace(P0, check_count=5), Checked(N, QUIET), s_br,
         replace(P0, current_step=2, check_count=0, next_check_at=N, hops=1),
         [Save(), Branch()]),
        # ── a routeless PPV step (it is terminal only on Sent)
        ("routeless PPV step, bought: offer_taken, converted",
         replace(P0, current_step=1), Checked(N, BOUGHT), script(ROUTELESS_PPV),
         replace(P0, current_step=1, status="done", last_error="offer_taken"), [Save(), Convert()]),
        ("routeless PPV step, no reply: waits on step 1's list (default [2,4,10] -> +4)",
         replace(P0, current_step=1), Checked(N, QUIET), script(ROUTELESS_PPV),
         replace(P0, current_step=1, check_count=1, next_check_at=m(4)), [Save(), Wait()]),
        ("routeless PPV step, replied: Generate",
         replace(P0, current_step=1), Checked(N, REPLIED), script(ROUTELESS_PPV),
         replace(P0, current_step=1), [Generate()]),
        # ── S8 (F1): after a `next` jump (idx 0 -> keyword -> idx 4) the reply-wait
        #    reads the SENT step's list (idx 0's [3,5,7] -> +5), not idx 3's (c - 1,
        #    default [2,4,10] -> +4): `last_sent_step` says which step went out.
        ("after a `next` jump the wait reads the sent step's intervals (S8)",
         replace(P0, current_step=4, hops=1, last_sent_step=0), Checked(N, QUIET), s_br,
         replace(P0, current_step=4, hops=1, last_sent_step=0, check_count=1, next_check_at=m(5)),
         [Save(), Wait()]),
        ("a linear walk is unchanged: the sent step IS c - 1 (default [2,4,10] -> +4)",
         replace(P0, current_step=2, last_sent_step=1), Checked(N, QUIET), s_lin,
         replace(P0, current_step=2, last_sent_step=1, check_count=1, next_check_at=m(4)),
         [Save(), Wait()]),
        ("a legacy row (last_sent_step None) after a jump keeps the old c - 1 rule (+4)",
         replace(P0, current_step=4, hops=1), Checked(N, QUIET), s_br,
         replace(P0, current_step=4, hops=1, check_count=1, next_check_at=m(4)), [Save(), Wait()]),
        ("after a BACKWARD `next` jump (idx 2 -> idx 0) the wait reads idx 2's [6,8,12] (+8)",
         replace(P0, current_step=0, hops=1, last_sent_step=2), Checked(N, QUIET), script(BACKWARD),
         replace(P0, current_step=0, hops=1, last_sent_step=2, check_count=1, next_check_at=m(8)),
         [Save(), Wait()]),
        ("a spent window after a jump: `next.ignored` counts the SENT step's list",
         replace(P0, current_step=2, hops=1, last_sent_step=0, check_count=1), Checked(N, QUIET),
         script(JUMP_IGNORED),
         replace(P0, current_step=3, hops=2, last_sent_step=0, check_count=0, next_check_at=N),
         [Save(), Branch()]),
    ])


def case_blocked_unreachable_table():
    _check([
        ("blocked: reasons recorded, fallback back-off, still pending",
         replace(P0, check_count=1), Blocked(N, ("no_media", "empty_text")), script(LINEAR),
         replace(P0, check_count=2, next_check_at=m(10), last_error="blocked:no_media,empty_text"),
         [Save(), Block()]),
        ("blocked by banned words", P0, Blocked(N, ("banned_words",)), script(LINEAR),
         replace(P0, check_count=1, next_check_at=m(10), last_error="blocked:banned_words"),
         [Save(), Block()]),
        ("unreachable chat: done, completed (not left due forever)",
         replace(P0, current_step=1), Unreachable(N), script(LINEAR),
         replace(P0, current_step=1, status="done"), [Save(), Complete()]),
        ("blocked on a branchy step: same back-off, `next` untouched",
         P0, Blocked(N, ("no_media",)), script(BRANCHY),
         replace(P0, check_count=1, next_check_at=m(10), last_error="blocked:no_media"),
         [Save(), Block()]),
        ("unreachable on a branchy step: done, no route taken",
         P0, Unreachable(N), script(BRANCHY), replace(P0, status="done"), [Save(), Complete()]),
    ])


def case_sent_table():
    s_br = script(BRANCHY)
    _check([
        ("linear step 0 sent: step 1, its first check at the sent step's intervals[0]",
         replace(P0, check_count=2), Sent(N, REPLIED), script(LINEAR),
         replace(P0, current_step=1, check_count=0, next_check_at=m(3), last_sent_step=0), [Save()]),
        ("linear step 1 sent: default [2,4,10] -> +2",
         replace(P0, current_step=1), Sent(N, REPLIED), script(LINEAR),
         replace(P0, current_step=2, next_check_at=m(2), last_sent_step=1), [Save()]),
        ("linear last step sent: off the end -> done",
         replace(P0, current_step=2), Sent(N, REPLIED), script(LINEAR),
         replace(P0, current_step=3, status="done", last_sent_step=2), [Save(), Complete()]),
        ("routeless PPV sent: terminal, stamped, handed off",
         replace(P0, current_step=1), Sent(N, REPLIED), script(ROUTELESS_PPV),
         replace(P0, current_step=2, status="done", last_ppv_sent_at=N, last_sent_step=1),
         [Save(), Complete()]),
        ("PPV with `next` sent: stamped, routed by default, hop counted",
         replace(P0, current_step=3), Sent(N, REPLIED), s_br,
         replace(P0, current_step=4, last_ppv_sent_at=N, hops=1, next_check_at=m(2), last_sent_step=3),
         [Save()]),
        ("branchy step sent, keyword reply -> keyword target (step 5)",
         P0, Sent(N, MORE), s_br,
         replace(P0, current_step=4, hops=1, next_check_at=m(3), last_sent_step=0), [Save()]),
        ("branchy step sent, keyword only as a reaction (not substantive) -> default",
         P0, Sent(N, MORE_EMOJI), s_br,
         replace(P0, current_step=1, hops=1, next_check_at=m(3), last_sent_step=0),
         [Save()]),
        ("branchy step sent, plain reply -> default (step 2)",
         P0, Sent(N, REPLIED), s_br,
         replace(P0, current_step=1, hops=1, next_check_at=m(3), last_sent_step=0),
         [Save()]),
        ("linear send never bumps hops (guard only with `next`)",
         replace(P0, hops=19), Sent(N, REPLIED), script(LINEAR),
         replace(P0, current_step=1, hops=19, next_check_at=m(3), last_sent_step=0), [Save()]),
        ("keyword-only `next`, the keyword misses, no default: +1 fallback, hop counted",
         P0, Sent(N, REPLIED), script(KW_ONLY),
         replace(P0, current_step=1, hops=1, next_check_at=m(2), last_sent_step=0), [Save()]),
        ("branchy send at the hop cap: done/loop_guard",
         replace(P0, hops=19), Sent(N, REPLIED), s_br,
         replace(P0, hops=20, status="done", last_error="loop_guard", last_sent_step=0),
         [Save(), Complete()]),
        ("a `next` jump stamps the SENT step (idx 0), not its target (idx 4)",
         replace(P0, last_sent_step=3), Sent(N, MORE), s_br,
         replace(P0, current_step=4, hops=1, next_check_at=m(3), last_sent_step=0), [Save()]),
    ])


def case_whole_funnel_walk():
    """One fan through BRANCHY: silent, then a plain reply (default -> step 2),
    step 2 sent linear (-> 3), then he buys: step 3 has no `next`, so the
    purchase halts him offer_taken."""
    s = script(BRANCHY)
    e = P0
    e, fx = decide(e, Due(N), s)
    assert fx == []
    e, fx = decide(e, Checked(N, QUIET), s)
    assert fx == [Save(), Wait()] and e.next_check_at == m(5)
    e, fx = decide(e, Checked(m(5), REPLIED), s)
    assert fx == [Generate()]
    e, fx = decide(e, Sent(m(5), REPLIED), s)
    assert fx == [Save()] and (e.current_step, e.hops, e.check_count) == (1, 1, 0)
    assert e.next_check_at == m(8)
    e, fx = decide(e, Checked(m(8), REPLIED), s)
    assert fx == [Generate()]
    e, fx = decide(e, Sent(m(8), REPLIED), s)
    assert fx == [Save()] and (e.current_step, e.hops) == (2, 1), e
    e, fx = decide(e, Checked(m(10), BOUGHT), s)
    assert fx == [Save(), Convert()] and (e.status, e.last_error) == ("done", "offer_taken")


def case_entry_from_row_round_trips():
    class Row:
        current_step, next_check_at, check_count, status = 2, N, 1, "pending"
        last_error, last_ppv_sent_at, hops, last_sent_step = "blocked:x", m(-5), None, 1
    e = Entry.from_row(Row())
    assert e == Entry(2, N, 1, "pending", "blocked:x", m(-5), None, 1)
    assert set(vars(e)) == {"current_step", "next_check_at", "check_count", "status",
                            "last_error", "last_ppv_sent_at", "hops", "last_sent_step"}


def case_send_shape_table():
    """step_number / ppv_send_kwargs: what _send_step hands OF, pure."""
    rows = [
        ("a number", fd.step_number({"step": 3}), 3),
        ("a numeric string", fd.step_number({"step": "4"}), 4),
        ("missing", fd.step_number({}), None),
        ("junk", fd.step_number({"step": "x"}), None),
        ("PPV: price, text free, media + clamped previews",
         fd.ppv_send_kwargs({"price": 30}, [1, 2], [2, 9]),
         {"price": 30, "locked_text": False, "media_files": [1, 2], "previews": [2]}),
        ("PPV: no price -> the default, locked_text opt-in",
         fd.ppv_send_kwargs({"locked_text": True}, [1], []),
         {"price": fd.DEFAULT_PPV_PRICE, "locked_text": True, "media_files": [1]}),
        ("PPV: a junk price -> the default; no media -> no media keys",
         fd.ppv_send_kwargs({"price": "abc"}, [], [1]),
         {"price": fd.DEFAULT_PPV_PRICE, "locked_text": False}),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, got, want in rows if got != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def case_offer_since_table():
    rows = [
        ("no PPV sent yet: since the broadcast", P0, m(-120), m(-120)),
        ("after our PPV: since it", replace(P0, last_ppv_sent_at=m(-10)), m(-120), m(-10)),
        ("no broadcast time, no PPV: no baseline", P0, None, None),
    ]
    bad = [f"{rid}: {got} != {want}" for rid, e, started, want in rows
           if (got := fd.offer_since(e, started)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


_harness.run()
