#!/usr/bin/env python3
"""
send_followup_decide.decide — table tests over the follow-up drip's pure phase machine.

No DB, no LLM, no OF: every row is (entry, event[, thresholds]) -> (entry', effects).
The tables lock the ordering rules run() used to carry inline:

  case_tick_table:        only an EXPIRED cooldown resumes (strict >); reply keeps the
                          cycle and steps, restart bumps the cycle and resets the steps.
  case_seen_table:        the sweep's precedence, top to bottom: cooling -> done phases
                          (reply after the drip -> restart 72h) -> reply mid-drip (26h)
                          -> silence anchor -> 7-day cap -> next step -> 18h gap -> guard
                          -> Send. Saves exactly where run() always saved (not on cooling,
                          a finished drip with no reply, guard or Send). Only the guard's
                          hold is an effect (Wait); every other hold is just no Send.
  case_sent_table:        a returned send records the step; the third ends the drip.
  case_thresholds_table:  _resolve_step_thresholds' overrides and fallbacks.
  case_pick_step_table:   _pick_next_step: the first unsent due step, in step order.
  case_whole_drip_walk:   one fan from silence through steps 1-3, a reply, the restart
                          cooldown and a fresh cycle.

Run: ./venv/bin/python service/tests/test_send_followup_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from automations.send_followup_decide import (  # noqa: E402
    _STEP_THRESHOLDS_H, Complete, Cooldown, Entry, Resume, Save, Seen, Send, Sent, Tick,
    Wait, _pick_next_step, _resolve_step_thresholds, decide,
)

N = datetime(2026, 10, 30, 12, 0, 0)


def h(hours: float) -> datetime:
    """`hours` before N (negative = after)."""
    return N - timedelta(hours=hours)


def iso(hours: float) -> str:
    return h(hours).isoformat()


def sent(**steps: float) -> dict:
    """sent(s1=40, s2=10) -> {"1": iso 40h ago, "2": iso 10h ago}."""
    return {k[1:]: iso(v) for k, v in steps.items()}


TRACK = Entry()


def _check(rows) -> None:
    """Run every row, collect every mismatch, fail once naming them all."""
    bad = []
    for row in rows:
        rid, entry, ev, want_entry, want_fx = row[:5]
        thresholds = row[5] if len(row) > 5 else _STEP_THRESHOLDS_H
        got_entry, got_fx = decide(entry, ev, thresholds)
        if got_fx != want_fx:
            bad.append(f"{rid}: effects {got_fx} != {want_fx}")
        if want_entry is not None and got_entry != want_entry:
            bad.append(f"{rid}: entry {got_entry} != {want_entry}")
    assert not bad, "\n  " + "\n  ".join(bad)


# ── Tick: the time-only pass over every state row ─────────────────────

RC = Entry(phase="reply_cooldown", cycle=2, silence_started_at=h(40), fan_last_reply_at=h(27),
           cooldown_until=h(0.01), messages_sent=sent(s1=30))
XC = Entry(phase="restart_cooldown", cycle=1, silence_started_at=h(200), fan_last_reply_at=h(73),
           cooldown_until=h(1), messages_sent=sent(s1=170, s2=130, s3=80))

TICK_ROWS = [
    ("reply cooldown expired -> tracking, same cycle and steps, anchor cleared",
     RC, Tick(N), replace(RC, phase="tracking", silence_started_at=None, cooldown_until=None),
     [Save(), Resume()]),
    ("restart cooldown expired -> tracking, cycle+1, steps reset, anchor cleared",
     XC, Tick(N), replace(XC, phase="tracking", cycle=2, messages_sent={}, silence_started_at=None,
                          cooldown_until=None), [Save(), Resume()]),
    ("reply cooldown not yet over -> untouched",
     replace(RC, cooldown_until=h(-1)), Tick(N), replace(RC, cooldown_until=h(-1)), []),
    ("cooldown ending exactly now is not over (strict >)",
     replace(XC, cooldown_until=N), Tick(N), replace(XC, cooldown_until=N), []),
    ("a cooldown with no end stays put",
     replace(RC, cooldown_until=None), Tick(N), replace(RC, cooldown_until=None), []),
    ("tracking is not a cooldown", replace(TRACK, cooldown_until=h(5)), Tick(N), None, []),
    ("completed with a stale cooldown_until is not resumed",
     Entry(phase="completed", cooldown_until=h(5)), Tick(N), None, []),
    ("all_sent_waiting is not resumed by time", Entry(phase="all_sent_waiting"), Tick(N), None, []),
]


def case_tick_table():
    _check(TICK_ROWS)


# ── Seen: one eligible fan in the sweep ───────────────────────────────

WAITING = Entry(phase="all_sent_waiting", silence_started_at=h(130), messages_sent=sent(s1=104, s2=66, s3=10))
DONE = Entry(phase="completed", silence_started_at=h(200), messages_sent=sent(s1=174))
A70 = Entry(silence_started_at=h(70), messages_sent=sent(s1=40))   # step 1 out 40h ago, step 2 due


def seen(last_in=None, last_out=None, guarded=False) -> Seen:
    return Seen(N, h(last_in) if last_in is not None else None,
                h(last_out) if last_out is not None else None, guarded)


SEEN_ROWS = [
    # cooling wins over everything, and saves nothing
    ("reply cooldown: nothing, even with a fresh reply", replace(RC, cooldown_until=h(-3)),
     seen(last_in=1, last_out=30), None, []),
    ("restart cooldown: nothing", replace(XC, cooldown_until=h(-3)), seen(last_out=200), None, []),
    # done phases: a reply after the anchor restarts (72h), else wait
    ("finished drip + reply after the anchor -> restart cooldown 72h", WAITING, seen(last_in=2, last_out=10),
     replace(WAITING, phase="restart_cooldown", cooldown_until=N + timedelta(hours=72), fan_last_reply_at=h(2)),
     [Save(), Cooldown("restart")]),
    ("cap-retired + reply -> the same restart", DONE, seen(last_in=1),
     replace(DONE, phase="restart_cooldown", cooldown_until=N + timedelta(hours=72), fan_last_reply_at=h(1)),
     [Save(), Cooldown("restart")]),
    ("finished drip, reply only from before the anchor -> wait", WAITING, seen(last_in=140, last_out=10),
     WAITING, []),
    ("finished drip, a reply newer than OUR last send but older than the anchor -> wait (anchor, not last out)",
     WAITING, seen(last_in=135, last_out=150), WAITING, []),
    ("finished drip, no inbound at all -> wait", WAITING, seen(last_out=10), WAITING, []),
    ("cap-retired, no inbound -> nothing, nothing saved", DONE, seen(last_out=10), DONE, []),
    ("cap-retired, reply only from before the anchor -> nothing", DONE, seen(last_in=250, last_out=10),
     DONE, []),
    ("finished drip with no anchor + any inbound -> restart", replace(WAITING, silence_started_at=None),
     seen(last_in=500), None, [Save(), Cooldown("restart")]),
    # tracking: his reply pauses the drip (26h), before any anchor/cap/step logic
    ("reply mid-drip -> reply cooldown 26h", A70, seen(last_in=5, last_out=40),
     replace(A70, phase="reply_cooldown", cooldown_until=N + timedelta(hours=26), fan_last_reply_at=h(5)),
     [Save(), Cooldown("reply")]),
    ("first contact was his -> reply cooldown", TRACK, seen(last_in=5),
     replace(TRACK, phase="reply_cooldown", cooldown_until=N + timedelta(hours=26), fan_last_reply_at=h(5)),
     [Save(), Cooldown("reply")]),
    ("reply beats the cap (silent 300h but he just wrote)", Entry(silence_started_at=h(300)),
     seen(last_in=1, last_out=300), None, [Save(), Cooldown("reply")]),
    ("inbound at the same instant as ours is not a reply (strict >)", TRACK, seen(last_in=30, last_out=30),
     replace(TRACK, silence_started_at=h(30)), [Send(1, 30.0)]),
    # silence anchor
    ("no messages: anchor = now, nothing due, anchor saved", TRACK, seen(),
     replace(TRACK, silence_started_at=N), [Save()]),
    ("no anchor: anchor = our last message", TRACK, seen(last_in=40, last_out=30),
     replace(TRACK, silence_started_at=h(30)), [Send(1, 30.0)]),
    ("a stored anchor is kept, not moved to our last send", A70, seen(last_in=80, last_out=40),
     A70, [Send(2, 70.0)]),
    # 7-day cap
    ("silent just over 7 days -> completed, no send", Entry(silence_started_at=h(168.01)), seen(last_out=168.01),
     Entry(phase="completed", silence_started_at=h(168.01)), [Save(), Complete()]),
    ("silent exactly 7 days still drips (strict >)", Entry(silence_started_at=h(168)), seen(last_out=168),
     None, [Send(1, 168.0)]),
    ("cap beats gap and guard", Entry(silence_started_at=h(200), messages_sent=sent(s1=1)),
     seen(last_out=1, guarded=True), None, [Save(), Complete()]),
    # step thresholds
    ("25.9h silent: not due", TRACK, seen(last_out=25.9), None, [Save()]),
    ("26h silent: step 1 (>=)", TRACK, seen(last_out=26), None, [Send(1, 26.0)]),
    ("70h silent, nothing sent: step 1 first, never 2", TRACK, seen(last_out=70), None, [Send(1, 70.0)]),
    ("63h after step 1 (sent 40h ago... anchor 63h): step 2 not due",
     Entry(silence_started_at=h(63), messages_sent=sent(s1=37)), seen(last_out=37), None, [Save()]),
    ("121h, steps 1+2 out: step 3", Entry(silence_started_at=h(121), messages_sent=sent(s1=95, s2=57)),
     seen(last_out=57), None, [Send(3, 121.0)]),
    ("all three out but still tracking: nothing due",
     Entry(silence_started_at=h(150), messages_sent=sent(s1=124, s2=86, s3=30)), seen(last_out=30), None,
     [Save()]),
    ("custom thresholds {10,20,30}: 12h silent -> step 1", TRACK, seen(last_out=12), None, [Send(1, 12.0)],
     {1: 10, 2: 20, 3: 30}),
    # 18h minimum gap
    ("step 2 due but step 1 went out 14h ago -> gap, anchor saved",
     Entry(silence_started_at=h(70), messages_sent=sent(s1=14)), seen(last_out=14),
     Entry(silence_started_at=h(70), messages_sent=sent(s1=14)), [Save()]),
    ("gap is measured from the LATEST step", Entry(silence_started_at=h(130), messages_sent=sent(s1=60, s2=10)),
     seen(last_out=10), None, [Save()]),
    ("17.99h since the last step -> gap", Entry(silence_started_at=h(70), messages_sent=sent(s1=17.99)),
     seen(last_out=17.99), None, [Save()]),
    ("exactly 18h since the last step -> send (not <)", Entry(silence_started_at=h(70), messages_sent=sent(s1=18)),
     seen(last_out=18), None, [Send(2, 70.0)]),
    ("an unparseable send time does not block", Entry(silence_started_at=h(70), messages_sent={"1": "garbage"}),
     seen(last_out=40), None, [Send(2, 70.0)]),
    # contact guard: only a DUE, gap-clear step is held, and nothing is saved
    ("due + guarded -> held, nothing saved", TRACK, seen(last_out=30, guarded=True),
     replace(TRACK, silence_started_at=h(30)), [Wait()]),
    ("not due + guarded -> not_due (the guard is never reached)", TRACK, seen(last_out=5, guarded=True),
     None, [Save()]),
    ("gap + guarded -> gap (checked first)", Entry(silence_started_at=h(70), messages_sent=sent(s1=14)),
     seen(last_out=14, guarded=True), None, [Save()]),
    ("an unknown phase is treated as tracking", Entry(phase="weird"), seen(last_out=30), None, [Send(1, 30.0)]),
    ("tracking with a stale cooldown_until: Seen ignores it (only Tick reads it)",
     replace(TRACK, silence_started_at=h(30), cooldown_until=h(5)), seen(last_out=30), None, [Send(1, 30.0)]),
]


def case_seen_table():
    _check(SEEN_ROWS)


# ── Sent: OF returned the send ────────────────────────────────────────

SENT_ROWS = [
    ("step 1 recorded, still tracking", replace(TRACK, silence_started_at=h(30)), Sent(1, N),
     replace(TRACK, silence_started_at=h(30), messages_sent={"1": N.isoformat()}), [Save()]),
    ("step 2 keeps step 1", A70, Sent(2, N),
     replace(A70, messages_sent={**A70.messages_sent, "2": N.isoformat()}), [Save()]),
    ("the third step ends the drip",
     Entry(silence_started_at=h(121), messages_sent=sent(s1=95, s2=57)), Sent(3, N),
     Entry(phase="all_sent_waiting", silence_started_at=h(121),
           messages_sent={**sent(s1=95, s2=57), "3": N.isoformat()}), [Save()]),
    ("cycle, anchor and reply time ride along", replace(RC, phase="tracking", cooldown_until=None), Sent(2, N),
     replace(RC, phase="tracking", cooldown_until=None, messages_sent={**RC.messages_sent, "2": N.isoformat()}),
     [Save()]),
    # run() only feeds Sent after a tracking Send; any other phase is pinned as is:
    # the step is recorded and the phase kept, unless it is the third.
    ("Sent on reply_cooldown: recorded, phase kept", RC, Sent(2, N),
     replace(RC, messages_sent={**RC.messages_sent, "2": N.isoformat()}), [Save()]),
    ("Sent on completed: recorded, phase kept", DONE, Sent(2, N),
     replace(DONE, messages_sent={**DONE.messages_sent, "2": N.isoformat()}), [Save()]),
    ("Sent on restart_cooldown with all three: all_sent_waiting", XC, Sent(3, N),
     replace(XC, phase="all_sent_waiting", messages_sent={**XC.messages_sent, "3": N.isoformat()}),
     [Save()]),
]


def case_sent_table():
    _check(SENT_ROWS)
    e = Entry(messages_sent=sent(s1=40))
    decide(e, Sent(2, N), _STEP_THRESHOLDS_H)
    assert e.messages_sent == sent(s1=40), "decide must not mutate the entry it was given"


# ── Thresholds ────────────────────────────────────────────────────────

D = {1: 26, 2: 64, 3: 120}
THRESHOLD_ROWS = [
    ({}, D), (None, D), ({"step_hours": [10, 20, 30]}, {1: 10.0, 2: 20.0, 3: 30.0}),
    ({"step_hours": [10]}, {1: 10.0, 2: 64, 3: 120}),
    ({"step_hours": ["x", 50, None]}, {1: 26, 2: 50.0, 3: 120}),
    ({"step_hours": [0, -5, 100]}, {1: 26, 2: 64, 3: 100.0}),
    ({"step_hours": [26, 64, 256]}, D),                 # step 3 over the 168h cap -> default
    ({"step_hours": [168]}, D),                         # at the cap is invalid too
    ({"step_hours": [167.9]}, {1: 167.9, 2: 64, 3: 120}),
    ({"step_hours": "26,64,120"}, D),                   # not a list
    ({"step_hours": (30, 70, 130)}, {1: 30.0, 2: 70.0, 3: 130.0}),
]


def case_thresholds_table():
    bad = [f"{p!r}: {_resolve_step_thresholds(p)} != {w}" for p, w in THRESHOLD_ROWS
           if _resolve_step_thresholds(p) != w]
    assert not bad, "\n  " + "\n  ".join(bad)
    assert _STEP_THRESHOLDS_H == D, "defaults moved"


PICK_ROWS = [
    (25.99, {}, None), (26, {}, 1), (70, {}, 1), (70, {"1": "x"}, 2), (63.9, {"1": "x"}, None),
    (120, {"1": "x", "2": "x"}, 3), (119.9, {"1": "x", "2": "x"}, None),
    (200, {"1": "x", "2": "x", "3": "x"}, None),
    (70, {"2": "x"}, 1),                    # an earlier unsent step goes first
    (130, {"1": "x", "3": "x"}, 2),
]


def case_pick_step_table():
    bad = [f"{s}h {sorted(m)}: {_pick_next_step(s, m)} != {w}" for s, m, w in PICK_ROWS
           if _pick_next_step(s, m) != w]
    assert not bad, "\n  " + "\n  ".join(bad)
    assert _pick_next_step(12, {}, {1: 10, 2: 20, 3: 30}) == 1


# ── A whole drip, event by event ──────────────────────────────────────

def case_whole_drip_walk():
    t0 = datetime(2026, 10, 1, 0, 0)

    def at(hours: float) -> datetime:
        return t0 + timedelta(hours=hours)

    e = Entry()
    log: list[tuple[float, list]] = []

    def step(hours, last_in=None, last_out=0.0, ev=None):
        nonlocal e
        ev = ev or Seen(at(hours), at(last_in) if last_in is not None else None, at(last_out))
        e, fx = decide(e, ev, _STEP_THRESHOLDS_H)
        log.append((hours, fx))
        sends = [f for f in fx if isinstance(f, Send)]
        if sends:
            e, more = decide(e, Sent(sends[0].step, at(hours)), _STEP_THRESHOLDS_H)
            log.append((hours, more))
        return fx

    assert step(1) == [Save()]
    assert e.silence_started_at == at(0)
    assert step(26) == [Send(1, 26.0)]
    assert step(40, last_out=26) == [Save()]          # 40h < 64h
    assert step(64, last_out=26) == [Send(2, 64.0)]                    # 38h after step 1
    assert step(120, last_out=64) == [Send(3, 120.0)]                  # 56h after step 2
    assert e.phase == "all_sent_waiting", e
    assert step(130, last_out=120) == []
    assert step(131, last_in=130.5, last_out=120) == [Save(), Cooldown("restart")]
    assert e.cooldown_until == at(131 + 72)
    assert step(150, last_in=130.5, last_out=120) == []
    assert step(203, ev=Tick(at(203))) == []                           # exactly the end: not over
    assert step(203.5, ev=Tick(at(203.5))) == [Save(), Resume()]
    assert (e.phase, e.cycle, e.messages_sent, e.silence_started_at) == ("tracking", 2, {}, None)
    # cycle 2: his reply (130.5h) is older than a chatter's answer (190h) -> not a reply;
    # the new anchor is that answer, so step 1 waits for 26h of fresh silence
    assert step(204, last_in=130.5, last_out=190) == [Save()]
    assert e.silence_started_at == at(190)
    assert step(216, last_in=130.5, last_out=190) == [Send(1, 26.0)]
    assert e.cycle == 2 and list(e.messages_sent) == ["1"]


_harness.run()
