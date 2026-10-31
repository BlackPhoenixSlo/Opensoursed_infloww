#!/usr/bin/env python3
"""automations._fm_relevance — characterisation tables for the FM auto-reply's
off-script decision table (`fired` / `decide`). Pins every row's threshold
edge (>= YES, >= ANNOYED_YES/CONFUSED_YES, <= NO), row order, the hard NO_AI
rows deciding by their own action (even `script`, which stops later rows),
and a missing action reading as `script`. Pure; no Jev call.

Run: ./venv/bin/python service/tests/test_fm_relevance_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from automations._fm_relevance import (  # noqa: E402
    ANNOYED_YES,
    CONFUSED_YES,
    NO,
    NO_AI,
    QUESTIONS,
    REASONS,
    YES,
    decide,
    fired,
)

# On-script baseline: every row off (natural settled yes).
_BASE = {"stop": 0.0, "promo": 0.0, "price": 0.0, "wants_content": 0.0, "annoyed": 0.0,
         "confused": 0.0, "asks": 0.0, "answered": 1.0, "natural": 1.0}


def _a(**kw):
    return {**_BASE, **kw}


def case_constants_pinned():
    rows = [
        (YES, 0.7, "YES"), (NO, 0.3, "NO"), (ANNOYED_YES, 0.5, "ANNOYED_YES"),
        (CONFUSED_YES, 0.5, "CONFUSED_YES"),
        (NO_AI, frozenset({"stop", "promo", "price"}), "NO_AI"),
        (REASONS, ("stop", "promo", "price", "wants_content", "annoyed", "confused",
                   "question", "not_a_reply"), "REASONS order"),
        (set(QUESTIONS), set(_BASE), "question ids == answer keys"),
    ]
    for got, exp, label in rows:
        assert got == exp, f"constants[{label}]: got {got!r}, expected {exp!r}"


def case_fired():
    rows = [
        (_a(), [], "baseline: nothing"),
        (_a(natural=0.5), [], "natural in band: nothing"),
        (_a(natural=0.3), ["not_a_reply"], "natural == NO fires"),
        (_a(natural=0.31), [], "natural just above NO"),
        (_a(stop=0.7), ["stop"], "stop == YES fires"),
        (_a(stop=0.69), [], "stop just below YES"),
        (_a(promo=0.7), ["promo"], "promo"),
        (_a(price=0.7), ["price"], "price"),
        (_a(wants_content=0.7), ["wants_content"], "wants_content"),
        (_a(annoyed=0.5), ["annoyed"], "annoyed == 0.5 fires"),
        (_a(annoyed=0.49), [], "annoyed below 0.5"),
        (_a(confused=0.5), ["confused"], "confused == 0.5 fires"),
        (_a(confused=0.49), [], "confused below 0.5"),
        (_a(asks=0.7, answered=0.3), ["question"], "asks yes + answered <= NO"),
        (_a(asks=0.7, answered=0.31), [], "asks yes but answered above NO"),
        (_a(asks=0.69, answered=0.0), [], "asks below YES"),
        ({k: 1.0 for k in _BASE} | {"answered": 0.0, "natural": 0.0}, list(REASONS),
         "everything fires, in REASONS order"),
        (_a(natural=0.0, stop=0.9, annoyed=0.6), ["stop", "annoyed", "not_a_reply"],
         "row order, not dict order"),
    ]
    for a, exp, label in rows:
        got = fired(a)
        assert got == exp, f"fired[{label}]: got {got!r}, expected {exp!r}"


def case_fired_missing_key_raises():
    rows = [
        # (missing key, asks, raises, label)
        ("stop", 0.0, True, "no stop"),
        ("natural", 0.0, True, "no natural"),
        ("answered", 0.9, True, "no answered while asks is yes"),
        ("answered", 0.0, False, "no answered while asks is no: short-circuit, not read"),
    ]
    for missing, asks, raises, label in rows:
        a = _a(asks=asks)
        del a[missing]
        try:
            fired(a)
            got = False
        except KeyError:
            got = True
        assert got is raises, f"fired[{label}]: raised={got}, expected {raises}"


def case_decide():
    ALL_AI = {r: "ai" for r in REASONS}
    rows = [
        # (answers, actions, expected, label)
        (_a(), ALL_AI, None, "nothing fires -> send block"),
        (_a(stop=0.9), {}, None, "missing action = script"),
        (_a(stop=0.9), {"stop": "stop"}, "stop", "hard row with stop action"),
        (_a(stop=0.9, annoyed=0.9), {"stop": "script", "annoyed": "ai"}, None,
         "hard row at script decides None, later rows NOT read"),
        (_a(price=0.9, wants_content=0.9), {"price": "script", "wants_content": "ai"}, None,
         "price at script blocks wants_content ai"),
        (_a(price=0.9), {"price": "ppv"}, "price", "price ppv"),
        (_a(price=0.9), {"price": "ai"}, "price",
         "PIN: decide returns price even for a disallowed 'ai' action (CHOICES not enforced)"),
        (_a(promo=0.9, stop=0.9), {"stop": "stop", "promo": "stop"}, "stop", "first hard row wins"),
        (_a(promo=0.9, price=0.9), {"promo": "script", "price": "ppv"}, None,
         "promo at script decides before price"),
        (_a(annoyed=0.9), {"annoyed": "script"}, None, "soft row at script skipped"),
        (_a(annoyed=0.9, confused=0.9), {"annoyed": "script", "confused": "ai"}, "confused",
         "soft row at script -> next soft row"),
        (_a(wants_content=0.9, annoyed=0.9), {"wants_content": "ppv", "annoyed": "stop"},
         "wants_content", "first non-script soft row"),
        (_a(asks=0.9, answered=0.1), {"question": "ai"}, "question", "question"),
        (_a(natural=0.1), {"not_a_reply": "stop"}, "not_a_reply", "not_a_reply"),
        (_a(natural=0.1), {"not_a_reply": "script"}, None, "not_a_reply at script"),
        (_a(annoyed=0.9), {"annoyed": "bogus"}, "annoyed",
         "PIN: unknown action string counts as non-script"),
        (_a(annoyed=0.9, stop=0.1), ALL_AI, "annoyed", "below-threshold hard row ignored"),
    ]
    for a, actions, exp, label in rows:
        got = decide(a, actions)
        assert got == exp, f"decide[{label}]: got {got!r}, expected {exp!r}"


_harness.run(case_constants_pinned, case_fired, case_fired_missing_key_raises, case_decide)
