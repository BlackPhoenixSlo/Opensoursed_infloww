#!/usr/bin/env python3
from __future__ import annotations

import random
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

from automations._common import (  # noqa: E402 — pure functions, no DB needed
    guard_offplatform,
    scan_offplatform,
)

FLAGGED = [
    "that's cute. fine, text me the details and i'll be at victoria harbour "
    "thursday mornin. just don't keep me waitin too long, hoceky boy",
    "text me ur number, i'll hit u up when i'm ready. till then, keep dreamin "
    "bout that sea palne",
]

LEAKS = [
    "my number is 555 123 4567 call me",
    "drop ur email its ava@example.com",
    "add me on snap babe",
    "whats ur snap",
    "send me ur insta handle",
    "find me on instagram",
    "give me your number",
    "lets meet up irl this weekend",
    "come see me tomorrow at the pier",
    "i'll be at the harbour friday around 8pm",
    "lets link up in person sometime",
]

CLEAN = [
    "haha ur so sweet, what u up to tonight babe",
    "mmm i'll be in bed thinking about u",
    "omg i had the longest monday at work lol",
    "tell me more about ur trip, sounds amazing",
    "i love when u talk to me like that",
    "aww how old are ya? bet ur a charmer",
    "i wanna see all of u right here",
    "snap out of it lol ur trouble",
    "that was instant chemistry babe",
    "send me ur thoughts on it",
    "give me a kiss",
    "share ur day with me",
]


def case_flags_real_leaks() -> None:
    for t in FLAGGED + LEAKS:
        reasons = scan_offplatform(t)
        assert reasons, f"expected a leak flag, got none for: {t!r}"


def case_no_false_positives() -> None:
    for t in CLEAN:
        reasons = scan_offplatform(t)
        assert not reasons, f"false positive {reasons} on benign line: {t!r}"


def case_guard_swaps_whole_message() -> None:
    leak = "text me ur number babe i'll be at the bar saturday"
    out, reasons = guard_offplatform(leak, random.Random("seed"))
    assert reasons, "guard should report the leak reasons"
    assert out != leak, "guard must replace a leaking message, not pass it through"
    assert not scan_offplatform(out), f"deflection must itself be clean, got: {out!r}"

    good = "haha ur so sweet, tell me more about ur day"
    out2, reasons2 = guard_offplatform(good, random.Random("seed"))
    assert out2 == good and not reasons2, "clean text must pass through unchanged"


def case_seeded_pick_is_stable() -> None:
    leak = "whats ur number"
    a = guard_offplatform(leak, random.Random("fan:123"))[0]
    b = guard_offplatform(leak, random.Random("fan:123"))[0]
    assert a == b, "same seed must yield the same deflection (deterministic retry)"


if __name__ == "__main__":
    case_flags_real_leaks()
    case_no_false_positives()
    case_guard_swaps_whole_message()
    case_seeded_pick_is_stable()
    print("test_offplatform_guard: all cases passed")
