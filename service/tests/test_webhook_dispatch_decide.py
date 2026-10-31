#!/usr/bin/env python3
"""webhook_dispatch_decide: W7's per-DM decisions as tables. Pure: no DB, no clock.

Pins: no kind → Skip terminal (before anything else); a cooldown ending more than
MAX_DEFER_S out → Skip cooldown_far, at exactly MAX_DEFER_S → deferred to its end;
dup → WakeOnly; else Enqueue with run_at = (cooldown end or now) + delay, a
reply_mass_funnel job pinned by `test_fan`, a chat engine's by `only_fan_ids`,
`_rule_id` only when the rule is known. The dedup window is the full wait + 5 s.
targets_fan reads all three producer shapes. blast_claim claims once per
dedup window, never mutates its input, and prunes stale claims past the cap.

Run: ./venv/bin/python service/tests/test_webhook_dispatch_decide.py  (exit 0 = pass)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _harness  # noqa: E402  (its run(); binds a temp DB, nothing here touches it)

from webhook_dispatch_decide import (  # noqa: E402
    DEDUP_WINDOW_S, MAX_DEFER_S, Enqueue, Skip, WakeOnly, blast_claim, dedup_within_s, plan, targets_fan)

NOW = datetime(2026, 10, 30, 12, 0, 0)
W, F = "welcome_chatter_for_info", "reply_mass_funnel"


def s(sec: float) -> datetime:
    return NOW + timedelta(seconds=sec)


def case_plan_table():
    rows = [
        # (kind, rule_id, fan, paused_until, delay, dup) -> expected
        ((None, None, 7, None, 0, False), Skip("terminal")),
        ((None, None, 7, s(10), 0, True), Skip("terminal")),             # terminal wins over all
        ((W, 3, 7, s(MAX_DEFER_S + 1), 0, False), Skip("cooldown_far")),
        ((W, 3, 7, s(MAX_DEFER_S + 1), 0, True), Skip("cooldown_far")),  # far wins over dup
        ((W, 3, 7, s(MAX_DEFER_S), 0, False),                            # at the cap: deferred
         Enqueue({"only_fan_ids": [7], "_rule_id": 3}, s(MAX_DEFER_S), MAX_DEFER_S, True)),
        ((W, 3, 7, s(20), 4, False),                                     # cooldown end + delay
         Enqueue({"only_fan_ids": [7], "_rule_id": 3}, s(24), 24.0, True)),
        ((W, 3, 7, s(-5), 0, False),                                     # cooldown over: now
         Enqueue({"only_fan_ids": [7], "_rule_id": 3}, NOW, 0.0, False)),
        ((W, 3, 7, s(0), 0, False),                                      # ends exactly now: not deferred
         Enqueue({"only_fan_ids": [7], "_rule_id": 3}, NOW, 0.0, False)),
        ((W, 3, 7, None, 9, False),
         Enqueue({"only_fan_ids": [7], "_rule_id": 3}, s(9), 9.0, False)),
        ((W, 3, 7, None, 0, True), WakeOnly()),
        ((W, 3, 7, s(20), 0, True), WakeOnly()),                         # deferred dup
        ((F, 4, 7, None, 0, False), Enqueue({"test_fan": 7, "_rule_id": 4}, NOW, 0.0, False)),
        ((W, None, 7, None, 0, False), Enqueue({"only_fan_ids": [7]}, NOW, 0.0, False)),  # no rule id
    ]
    for args, want in rows:
        got = plan(*args, NOW)
        assert got == want, (args, got, want)


def case_dedup_window_spans_the_full_wait():
    rows = [
        ((None, 0), DEDUP_WINDOW_S),
        ((None, 9), 9 + DEDUP_WINDOW_S),
        ((s(20), 4), 24 + DEDUP_WINDOW_S),
        ((s(-5), 0), DEDUP_WINDOW_S),
    ]
    for (until, delay), want in rows:
        assert dedup_within_s(until, delay, NOW) == want, (until, delay)


def case_targets_fan_table():
    rows = [
        ({"only_fan_ids": [7, 8]}, 7, True),
        ({"only_fan_ids": [8]}, 7, False),
        ({"only_fan_ids": None}, 7, False),
        ({"test_fan": 7}, 7, True),
        ({"test_fan": 8}, 7, False),
        ({"fan_id": 7}, 7, True),
        ({"fan_id": "7"}, 7, False),           # typed: a string id is another fan
        ({}, 7, False),
        ({"only_fan_ids": [8], "test_fan": 7}, 7, True),
    ]
    for payload, fid, want in rows:
        assert targets_fan(payload, fid) is want, (payload, fid)


def case_blast_claim_table():
    k, other = ("a", 1), ("a", 2)
    # (claims, now, dedup, max) -> (claimed, claims')
    rows = [
        (({}, 100.0, 600, 10), (True, {k: 100.0})),
        (({k: 100.0}, 699.0, 600, 10), (False, {k: 100.0})),           # inside the window
        (({k: 100.0}, 700.0, 600, 10), (True, {k: 700.0})),            # window over: reclaim
        (({other: 1.0}, 700.0, 600, 10), (True, {other: 1.0, k: 700.0})),  # under the cap: kept
        (({other: 1.0}, 700.0, 600, 1), (True, {k: 700.0})),           # over the cap: stale pruned
        (({other: 650.0}, 700.0, 600, 1), (True, {other: 650.0, k: 700.0})),  # fresh survives prune
    ]
    for (claims, now, dedup, mx), want in rows:
        snap = dict(claims)
        got = blast_claim(claims, k, now, dedup, mx)
        assert got == want, (claims, now, got, want)
        assert claims == snap, "input mutated"


_harness.run()
