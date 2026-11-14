#!/usr/bin/env python3
"""test_full_ai_decide — Full AI Chat's Route table (`full_ai_decide`) and the
Router's constants (`_router_jev`), pure, plain assert.

  case_constants_pinned       thresholds, MODEL, the question ids and the
                              QUESTION_VERSION literal; a wording edit fails
                              here until the pin moves on purpose
  case_state_shape_moves_question_version  STATE_VERSION, THREAD_LINES,
                              PURCHASE_DAYS, PURCHASE_KINDS each move the
                              digest; PURCHASE_KINDS order does not
  case_fired_at_the_edge     `fired`: at its threshold a question fires, just
                              under it does not; test Mode adds TEST_THRESHOLDS
                              ids (skipped when absent), Shadow never reads them
  case_otherwise_is_chat      no row holds → chat, row `otherwise`, the fired
                              set kept
  case_rows_at_the_edge       every Route table row at its threshold fires,
                              just under it does not; `fired` agrees
  case_rows_in_order          each row beats every row below it
  case_precedence             complains_now > stop > sell/tease/Pending tease;
                              tease on price or a decline, beating sext;
                              wants_content beats price and declines; a
                              Pending tease sells; says_yes counted only
                              with a Pending offer or Pending tease
  case_route_flags            sell off: rows sell_off, tease_off; sext off:
                              row sext_off; rows 1-5 untouched
  case_jev_failed_is_chat     `jev_ok` false: chat, Heat 1, `jev_failed`
  case_heat_is_his_level_plus_one  Heat = min(4, his level + 1), his level the
                              Score rounded, a tie up; 1 when Jev failed
  case_arm_of_is_a_fixed_20_pct_holdout  `arm_of` deterministic, ~20 % holdout
                              over 10,000 Fans; HOLDOUT_PCT 20, SALT_VER 1
  case_decide_module_is_pure  full_ai_decide imports stdlib and the Router's
                              constants only
  case_r10_every_flag_combination  R10 over every fired set of the flagged rows,
                              Pending offer / tease and flag combination: an off
                              row is dropped, the first remaining row matches
  case_r10_shadow_equals_the_old_table  flags on: the pre-R10 table, nothing dropped
  case_r10_dropped_contents   `dropped` names the removed rows in walk order
  case_test_mode_questions    Shadow asks exactly QUESTIONS + intensity; test Mode
                              adds asks_subject / asks_format (Choices) and the
                              DRAFT Nouls counter_offer / offer_moment; DRAFT set
  case_question_version_by_mode  Shadow's digest is the pre-03b literal; test
                              Mode's moves with DRAFT, a Choice option, a wording,
                              a TEST_THRESHOLDS value (and left its pre-47B value)
  case_choice_of              argmax; a tie or a missing answer → anything / any
  case_sell_rows_every_combination  (ticket 47) haggle / offer_moment over every
                              fired set × draft_on × sell_on × open Offer ×
                              Pending tease (× Pending offer × sext_on): the
                              frozen pre-47 table plus the spec's two rows
  case_sell_rows_dropped      `dropped` worked rows: a DRAFT id that fired but
                              did not count, haggle → sell_off, offer_moment
                              names nothing
  case_shadow_equals_the_pre_47_table  draft_on false: a frozen copy of the
                              pre-ticket-47 `decide_turn` over every fired set
                              of the 11 Phase 01 ids × every other fact
  case_scene_questions        sext scene: the 4 SCENE ids asked only with
                              `scene` (Nouls / Choices, not DRAFT); test digest
                              left its pre-scene value and moves with their
                              wording; Shadow's never; choice_or_none / defaults
  case_scene_rows             scene_on alone -> sext row `scene_on`; scene_offer
                              needs a scene + sell_on, after offer_moment, drop
                              names nothing; sext off drops scene_on
  case_scene_off_is_the_old_table  `scene` false: every fired set with the scene
                              ids decides as without them (ignored, not dropped)

Run: ./venv/bin/python service/tests/test_full_ai_decide.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import ast  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import get_args  # noqa: E402

from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_decide as fd  # noqa: E402
from automations import full_ai_sell  # noqa: E402

# OWNER-REVIEW-router.md items 1-10 and 12, in that order (spec › Interfaces).
IDS = ("promo", "says_under_18", "complains_now", "asks_if_ai", "stop", "price",
       "wants_content", "declines_buying", "says_yes_to_offer", "sexual_now", "gif_fits")
THRESHOLDS = {"promo": .7, "says_under_18": .7, "complains_now": .5, "asks_if_ai": .7,
              "stop": .6, "price": .7, "wants_content": .7, "declines_buying": .5,
              "says_yes_to_offer": .7, "sexual_now": .7, "gif_fits": .6}
# The DRAFT test-Mode Nouls' thresholds (ticket 47 phase B; ASSUMPTION: unprobed .7).
TEST_THRESHOLDS = {"counter_offer": .7, "offer_moment": .7, "scene_on": .7, "scene_offer": .7}
# `question_version("test")` before ticket 47 phase B put `TEST_THRESHOLDS` in it.
PRE_47B_TEST_VERSION = "4e30e9162a1e"
# `question_version("test")` before the sext scene (origin/main c847cb09f).
PRE_SCENE_TEST_VERSION = "8878043c1f4f"


def _quiet(**over: float) -> dict[str, float]:
    return {**dict.fromkeys(IDS, 0.0), **over}


def case_constants_pinned():
    rows = [
        (rj.MODEL, "jev-1.14.0", "MODEL"),
        (rj.TIMEOUT_S, 10.0, "TIMEOUT_S"),
        (rj.MAX_RETRIES, 1, "MAX_RETRIES"),
        (rj.THREAD_LINES, 12, "THREAD_LINES"),
        (tuple(rj.QUESTIONS), IDS, "question ids, in order"),
        (rj.THRESHOLDS, THRESHOLDS, "THRESHOLDS"),
        (set(rj.THRESHOLDS), set(rj.QUESTIONS), "one threshold per question"),
        (rj.TEST_THRESHOLDS, TEST_THRESHOLDS, "TEST_THRESHOLDS"),
        (set(rj.TEST_THRESHOLDS), set(rj.TEST_NOULS), "one test threshold per DRAFT Noul"),
        (len(rj.INTENSITY["criteria"]), 5, "intensity levels"),
        (rj.STATE_VERSION, 1, "STATE_VERSION"),
        (rj.PURCHASE_DAYS, 7, "PURCHASE_DAYS"),
        (rj.PURCHASE_KINDS, ("tip", "ppv_message", "ppv_post"), "PURCHASE_KINDS"),
        # The digest of the wording, thresholds, levels, model and state shape.
        # Moving it is the point: a Decision row asked under other wording reads apart.
        (rj.QUESTION_VERSION, "b3202b420ab0", "QUESTION_VERSION"),
        (rj.question_version(), rj.QUESTION_VERSION, "question_version() at import"),
    ]
    for got, exp, label in rows:
        assert got == exp, f"constants[{label}]: got {got!r}, expected {exp!r}"


def case_state_shape_moves_question_version():
    """Each state-shape input is in the digest: changing one moves it."""
    for name, other in (("STATE_VERSION", 2), ("THREAD_LINES", 13), ("PURCHASE_DAYS", 8),
                        ("PURCHASE_KINDS", ("tip", "ppv_message"))):
        real = getattr(rj, name)
        setattr(rj, name, other)
        try:
            moved = rj.question_version()
        finally:
            setattr(rj, name, real)
        assert moved != rj.QUESTION_VERSION, (name, moved)
    assert rj.question_version() == rj.QUESTION_VERSION
    # Order-blind: the kinds are a set to the SQL that reads them.
    real = rj.PURCHASE_KINDS
    rj.PURCHASE_KINDS = tuple(reversed(real))
    try:
        assert rj.question_version() == rj.QUESTION_VERSION
    finally:
        rj.PURCHASE_KINDS = real


def case_fired_at_the_edge():
    for q, t in THRESHOLDS.items():
        assert rj.fired(_quiet(**{q: t})) == frozenset({q}), (q, "at threshold")
        assert rj.fired(_quiet(**{q: round(t - .01, 2)})) == frozenset(), (q, "just under")
    assert rj.fired(_quiet()) == frozenset()
    quiet = _quiet(**dict.fromkeys(TEST_THRESHOLDS, 0.0))
    for q, t in TEST_THRESHOLDS.items():
        at, under = {**quiet, q: t}, {**quiet, q: round(t - .01, 2)}
        assert rj.fired(at, "test") == frozenset({q}), (q, "test, at threshold")
        assert rj.fired(under, "test") == frozenset(), (q, "test, just under")
        assert rj.fired({**quiet, q: 1.0}) == rj.fired({**quiet, q: 1.0}, "shadow") == frozenset(), q
    both = {**quiet, "counter_offer": .9, "offer_moment": .7, "price": .7}
    assert rj.fired(both, "test") == frozenset({"counter_offer", "offer_moment", "price"})
    assert rj.fired(both) == frozenset({"price"})
    # A test id absent from `answers` is not fired; a missing Shadow id still raises.
    assert rj.fired(_quiet(price=.8), "test") == frozenset({"price"})
    assert rj.fired(_quiet(offer_moment=.8), "test") == frozenset({"offer_moment"})
    for mode in ("shadow", "test"):
        try:
            rj.fired({k: v for k, v in quiet.items() if k != "price"}, mode)
        except KeyError:
            continue
        raise AssertionError(mode)


def _facts(fired=(), intensity=0.0, *, pending_offer=False, pending_tease=False, jev_ok=True,
           **flags) -> fd.Facts:
    return fd.Facts(fired=frozenset(fired), intensity=intensity, pending_offer=pending_offer,
                    pending_tease=pending_tease, jev_ok=jev_ok, **flags)


def case_otherwise_is_chat():
    rows = [
        (_facts(), ("chat", 1, "otherwise", frozenset())),
        (_facts({"gif_fits"}, 1.2), ("chat", 2, "otherwise", frozenset({"gif_fits"}))),
    ]
    for facts, exp in rows:
        d = fd.decide_turn(facts)
        assert (d.route, d.heat, d.row, d.fired) == exp, (facts, d)


# The Route table in first-match order (ticket 27; D42-D44, Opus a-c, R9):
# (question, extra facts, Route, row). says_yes_to_offer counts only with a
# Pending offer or Pending tease set.
TABLE = (
    ("promo", {}, "no_send", "promo"),
    ("says_under_18", {}, "no_send", "says_under_18"),
    ("complains_now", {}, "make_right", "complains_now"),
    ("asks_if_ai", {}, "ai_dare", "asks_if_ai"),
    ("stop", {}, "chat", "stop"),
    ("wants_content", {}, "sell_now", "sell"),
    ("says_yes_to_offer", {"pending_offer": True}, "sell_now", "sell"),
    ("price", {}, "tease", "tease_price"),
    ("declines_buying", {}, "tease", "tease_decline"),
    ("sexual_now", {}, "sext", "sexual_now"),
)


def _route(answers: dict[str, float], **facts) -> tuple[str, str]:
    d = fd.decide_turn(_facts(rj.fired(answers), 1.0, **facts))
    return d.route, d.row


def case_rows_at_the_edge():
    """Every row at its threshold fires, just under it does not (chat,
    `otherwise`; `fired` at the edge is case_fired_at_the_edge); the Decision
    keeps the fired set."""
    for q, extra, route, row in TABLE:
        t = THRESHOLDS[q]
        at, under = _quiet(**{q: t}), _quiet(**{q: round(t - .01, 2)})
        assert _route(at, **extra) == (route, row), (q, _route(at, **extra))
        assert _route(under, **extra) == ("chat", "otherwise"), (q, _route(under, **extra))
        assert fd.decide_turn(_facts({q}, **extra)).fired == frozenset({q}), q


def case_rows_in_order():
    """Each row beats every row below it, all firing together."""
    for i, (q, extra, route, row) in enumerate(TABLE):
        later = {x for x, *_ in TABLE[i:]}
        extras = {k: v for _, e, *_ in TABLE[i:] for k, v in e.items()}
        d = fd.decide_turn(_facts(later, **extras))
        assert (d.route, d.row, d.fired) == (route, row, frozenset(later)), (q, d)


def case_precedence():
    rows = [
        # complains_now beats stop; stop beats sell, tease and a Pending tease.
        (({"complains_now", "stop"}, {}), ("make_right", "complains_now")),
        (({"stop", "wants_content"}, {}), ("chat", "stop")),
        (({"stop", "says_yes_to_offer"}, {"pending_offer": True}), ("chat", "stop")),
        (({"stop", "price"}, {}), ("chat", "stop")),
        (({"stop", "declines_buying"}, {}), ("chat", "stop")),
        (({"stop"}, {"pending_tease": True}), ("chat", "stop")),
        # price or declines_buying: tease, declines no veto; tease beats sext.
        (({"price"}, {}), ("tease", "tease_price")),
        (({"declines_buying"}, {}), ("tease", "tease_decline")),
        (({"price", "declines_buying"}, {}), ("tease", "tease_price")),
        (({"declines_buying", "sexual_now"}, {}), ("tease", "tease_decline")),
        (({"price", "sexual_now"}, {}), ("tease", "tease_price")),
        # wants_content (or a counted yes) with price or declines_buying: sell now.
        (({"wants_content", "price"}, {}), ("sell_now", "sell")),
        (({"wants_content", "declines_buying"}, {}), ("sell_now", "sell")),
        (({"says_yes_to_offer", "declines_buying"}, {"pending_offer": True}), ("sell_now", "sell")),
        # A Pending tease with nothing fired sells; rows promo to stop still beat it.
        ((set(), {"pending_tease": True}), ("sell_now", "sell")),
        (({"price"}, {"pending_tease": True}), ("sell_now", "sell")),
        (({"promo"}, {"pending_tease": True}), ("no_send", "promo")),
        (({"says_under_18"}, {"pending_tease": True}), ("no_send", "says_under_18")),
        (({"complains_now"}, {"pending_tease": True}), ("make_right", "complains_now")),
        (({"asks_if_ai"}, {"pending_tease": True}), ("ai_dare", "asks_if_ai")),
        # says_yes_to_offer counts only with a Pending offer or Pending tease.
        (({"says_yes_to_offer"}, {}), ("chat", "otherwise")),
        (({"says_yes_to_offer", "sexual_now"}, {}), ("sext", "sexual_now")),
        (({"says_yes_to_offer"}, {"pending_offer": True}), ("sell_now", "sell")),
        (({"says_yes_to_offer"}, {"pending_tease": True}), ("sell_now", "sell")),
        ((set(), {"pending_offer": True}), ("chat", "otherwise")),
        # gif_fits is never read.
        (({"gif_fits"}, {}), ("chat", "otherwise")),
        (({"gif_fits", "sexual_now"}, {}), ("sext", "sexual_now")),
    ]
    for (fired, extra), exp in rows:
        d = fd.decide_turn(_facts(fired, **extra))
        assert (d.route, d.row) == exp, (fired, extra, (d.route, d.row), exp)


def case_route_flags():
    """Sell off: sell and tease turn chat (rows sell_off, tease_off) unless a later
    row matches (R10: wants_content + sexual_now is sext); sext off: sext turns chat
    (row sext_off); no flag touches any other row."""
    off, nosext = {"sell_on": False}, {"sext_on": False}
    rows = [
        (({"wants_content"}, off), ("chat", "sell_off")),
        (({"says_yes_to_offer"}, {"pending_offer": True, **off}), ("chat", "sell_off")),
        ((set(), {"pending_tease": True, **off}), ("chat", "sell_off")),
        (({"wants_content", "sexual_now"}, off), ("sext", "sexual_now")),
        (({"price"}, off), ("chat", "tease_off")),
        (({"declines_buying"}, off), ("chat", "tease_off")),
        (({"sexual_now"}, off), ("sext", "sexual_now")),
        (({"sexual_now"}, nosext), ("chat", "sext_off")),
        (({"wants_content", "sexual_now"}, nosext), ("sell_now", "sell")),
        (({"price", "sexual_now"}, nosext), ("tease", "tease_price")),
        (({"promo"}, {**off, **nosext}), ("no_send", "promo")),
        (({"complains_now"}, {**off, **nosext}), ("make_right", "complains_now")),
        (({"asks_if_ai"}, {**off, **nosext}), ("ai_dare", "asks_if_ai")),
        (({"stop"}, {**off, **nosext}), ("chat", "stop")),
        ((set(), {**off, **nosext}), ("chat", "otherwise")),
    ]
    for (fired, extra), exp in rows:
        d = fd.decide_turn(_facts(fired, **extra))
        assert (d.route, d.row) == exp, (fired, extra, (d.route, d.row), exp)
    assert fd.Facts.__dataclass_fields__["sell_on"].default is True      # all on in Shadow
    assert fd.Facts.__dataclass_fields__["sext_on"].default is True


def case_jev_failed_is_chat():
    """`jev_ok` false: chat, Heat 1, row `jev_failed`, never a no_send."""
    for fired, extra in ((set(), {}), ({"promo"}, {}), ({"says_under_18", "sexual_now"}, {}),
                         (set(), {"pending_tease": True}), (set(), {"sell_on": False})):
        d = fd.decide_turn(_facts(fired, 3.0, jev_ok=False, **extra))
        assert (d.route, d.heat, d.row) == ("chat", 1, "jev_failed"), (fired, extra, d)


# Heat = min(4, his level + 1), his level the `intensity` Score rounded to the
# nearest level, a tie up (D44): the ticket's edges, then the tie edges.
HEAT_EDGES = ((0.0, 1), (1.5, 3), (3.6, 4), (4.0, 4),
              (0.49, 1), (0.5, 2), (1.49, 2), (2.5, 4), (2.49, 3), (3.49, 4))


def case_heat_is_his_level_plus_one():
    # On every Route: each fired set below lands on a different one.
    for fired in ((), {"sexual_now"}, {"wants_content"}, {"price"}, {"complains_now"},
                  {"asks_if_ai"}, {"promo"}, {"stop"}):
        for intensity, heat in HEAT_EDGES:
            d = fd.decide_turn(_facts(fired, intensity))
            assert d.heat == heat, (fired, intensity, d.heat, heat)
    for intensity in (0.0, 2.5, 4.0):        # Jev failed: Heat 1 whatever the Score
        assert fd.decide_turn(_facts(intensity=intensity, jev_ok=False)).heat == 1, intensity


def case_arm_of_is_a_fixed_20_pct_holdout():
    """`arm_of` is deterministic and gives about 20 % holdout over 10,000 Fans
    (holdout below 20 of 100, `salt_ver` 1; ADR-0035)."""
    assert (fd.HOLDOUT_PCT, fd.SALT_VER) == (20, 1), (fd.HOLDOUT_PCT, fd.SALT_VER)
    arms = [fd.arm_of("acct_a", fan) for fan in range(10_000)]
    assert set(arms) == {"treatment", "holdout"}, set(arms)
    n = arms.count("holdout")
    assert 1_900 <= n <= 2_100, n                                           # 20 % +- 1 pp
    # Pinned literals, as QUESTION_VERSION is: a salt, hash or split change (or
    # a per-process hash) fails here until the pin moves on purpose (new SALT_VER).
    assert n == 1976, n
    assert [fd.arm_of("acct_b", f) for f in range(10_000)].count("holdout") == 1957
    assert arms[:8] == ["treatment", "treatment", "holdout"] + ["treatment"] * 5, arms[:8]
    assert [fd.arm_of("acct_b", f) for f in range(8)] == [
        "holdout", "treatment", "treatment", "treatment", "holdout", "holdout", "treatment", "treatment"]


_STDLIB = {"__future__", "dataclasses", "hashlib", "math", "typing"}


def case_decide_module_is_pure():
    tree = ast.parse(Path(fd.__file__).read_text(encoding="utf-8"))
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    froms = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= _STDLIB, mods
    assert froms <= _STDLIB | {"automations._router_jev"}, froms
    # From the Router only its constants (UPPER_CASE names), never `ask`.
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "automations._router_jev":
            names = [a.name for a in n.names]
            assert all(x.isupper() for x in names), names


# R10 (ticket 34): the flagged rows in walk order. An off flag drops its row and the
# walk goes on; reaching `otherwise` names the first kind dropped.
_FLAGGED_Q = ("wants_content", "says_yes_to_offer", "price", "declines_buying", "sexual_now")


def _r10_expect(fired, pending_offer, pending_tease, sell_on, sext_on):
    """The spec's R10 walk written out (Interfaces › full_ai_decide)."""
    rows = (
        ("sell", "sell_now", sell_on, "wants_content" in fired
         or ("says_yes_to_offer" in fired and pending_offer) or pending_tease),
        ("tease_price", "tease", sell_on, "price" in fired),
        ("tease_decline", "tease", sell_on, "declines_buying" in fired and "price" not in fired),
        ("sexual_now", "sext", sext_on, "sexual_now" in fired),
    )
    dropped: list[str] = []
    for row, route, on, match in rows:
        if match and on:
            return route, row, tuple(dropped)
        if match:
            dropped.append(row)
    # Named by the first drop, a literal table rather than the code's own walk.
    end = {"sell": "sell_off", "tease_price": "tease_off", "tease_decline": "tease_off",
           "sexual_now": "sext_off"}[dropped[0]] if dropped else "otherwise"
    return "chat", end, tuple(dropped)


def _combos():
    from itertools import product
    for bits in product((False, True), repeat=len(_FLAGGED_Q) + 4):
        fired = {q for q, b in zip(_FLAGGED_Q, bits) if b}
        yield fired, *bits[len(_FLAGGED_Q):]


def case_r10_every_flag_combination():
    n = 0
    for fired, po, pt, sell_on, sext_on in _combos():
        d = fd.decide_turn(_facts(fired, 1.4, pending_offer=po, pending_tease=pt,
                                  sell_on=sell_on, sext_on=sext_on))
        exp = _r10_expect(fired, po, pt, sell_on, sext_on)
        assert (d.route, d.row, d.dropped) == exp, (fired, po, pt, sell_on, sext_on, d, exp)
        assert (d.heat, d.fired) == (2, frozenset(fired)), d
        n += 1
    assert n == 2 ** 9, n


def _pre_r10(fired, po, pt):
    """The table before R10 with every flag on (ticket 27's rows, verbatim logic)."""
    if "wants_content" in fired or ("says_yes_to_offer" in fired and po) or pt:
        return "sell_now", "sell"
    if "price" in fired or "declines_buying" in fired:
        return "tease", "tease_price" if "price" in fired else "tease_decline"
    if "sexual_now" in fired:
        return "sext", "sexual_now"
    return "chat", "otherwise"


def case_r10_shadow_equals_the_old_table():
    """Shadow passes every flag on (the `Facts` defaults): the same Route and row as
    before R10, nothing dropped, on every combination and every TABLE row."""
    for fired, po, pt, _s, _x in _combos():
        d = fd.decide_turn(fd.Facts(frozenset(fired), 1.0, po, pt, True))
        assert ((d.route, d.row), d.dropped) == (_pre_r10(fired, po, pt), ()), (fired, po, pt, d)
    for q, extra, route, row in TABLE:
        d = fd.decide_turn(_facts({q}, **extra))
        assert (d.route, d.row, d.dropped) == (route, row, ()), (q, d)
    assert fd.Decision("chat", 1, "otherwise", frozenset()).dropped == ()


def case_r10_dropped_contents():
    off, nosext = {"sell_on": False}, {"sext_on": False}
    rows = [
        (({"wants_content"}, off), ("chat", "sell_off", ("sell",))),
        (({"wants_content", "sexual_now"}, off), ("sext", "sexual_now", ("sell",))),
        (({"wants_content", "price", "sexual_now"}, off),
         ("sext", "sexual_now", ("sell", "tease_price"))),
        (({"price"}, off), ("chat", "tease_off", ("tease_price",))),
        (({"declines_buying"}, off), ("chat", "tease_off", ("tease_decline",))),
        (({"price", "sexual_now"}, off), ("sext", "sexual_now", ("tease_price",))),
        (({"declines_buying", "sexual_now"}, off), ("sext", "sexual_now", ("tease_decline",))),
        (({"wants_content", "sexual_now"}, {**off, **nosext}),
         ("chat", "sell_off", ("sell", "sexual_now"))),
        (({"price", "sexual_now"}, {**off, **nosext}),
         ("chat", "tease_off", ("tease_price", "sexual_now"))),
        (({"sexual_now"}, nosext), ("chat", "sext_off", ("sexual_now",))),
        ((set(), {"pending_tease": True, **off}), ("chat", "sell_off", ("sell",))),
        # says_yes with no Pending offer is no sell row, so nothing is dropped.
        (({"says_yes_to_offer"}, off), ("chat", "otherwise", ())),
        # Rows 1-5 come before every flagged row: nothing is dropped.
        (({"complains_now", "wants_content"}, off), ("make_right", "complains_now", ())),
        (({"stop", "sexual_now"}, {**off, **nosext}), ("chat", "stop", ())),
    ]
    for (fired, extra), exp in rows:
        d = fd.decide_turn(_facts(fired, **extra))
        assert (d.route, d.row, d.dropped) == exp, (fired, extra, d, exp)
    # A Jev failure walks no row.
    assert fd.decide_turn(_facts({"wants_content"}, jev_ok=False, **off)).dropped == ()


# ── Test-Mode Router questions (03b ticket 43) ──────────────────────────

# Spec › Interfaces `Ask` (ticket 10 r3's subjects, "anything" included) and formats; the
# Sell executor's own Literals, so a Choice label is always an `Ask` value.
SUBJECTS = ("feet", "butt", "tits", "pussy", "nude", "lingerie", "bikini", "shower", "toy",
            "masturbation", "blowjob", "sex", "anything")
FORMATS = ("photo", "video", "any")
assert SUBJECTS == get_args(full_ai_sell.Subject) and FORMATS == get_args(full_ai_sell.Format)
TEST_IDS = {"asks_subject", "asks_format", "counter_offer", "offer_moment"}


def case_test_mode_questions():
    """Shadow asks exactly `QUESTIONS` + `intensity`; test Mode adds the two Choices and the
    two DRAFT Nouls; the DRAFT set names gif_fits, counter_offer, offer_moment."""
    for shadow in (rj._questions(), rj._questions("shadow")):
        assert list(shadow) == [*IDS, "intensity"], list(shadow)
    test = rj._questions("test")
    assert set(test) == {*IDS, "intensity"} | TEST_IDS, sorted(test)
    kinds = {q: type(v).__name__ for q, v in test.items() if q in TEST_IDS}
    assert kinds == {"asks_subject": "Choice", "asks_format": "Choice",
                     "counter_offer": "Noul", "offer_moment": "Noul"}, kinds
    assert tuple(test["asks_subject"].criteria) == SUBJECTS, tuple(test["asks_subject"].criteria)
    assert tuple(test["asks_format"].criteria) == FORMATS, tuple(test["asks_format"].criteria)
    assert all(test[q].model_dump() == v.model_dump() for q, v in rj._questions().items())
    assert rj.DRAFT == frozenset({"gif_fits", "counter_offer", "offer_moment"}), rj.DRAFT
    assert not TEST_IDS & set(rj.QUESTIONS) and not TEST_IDS & set(rj.THRESHOLDS)


def case_question_version_by_mode():
    """Shadow's digest is the pre-03b literal; test Mode's moves with a DRAFT member, a Choice
    option or a DRAFT Noul's wording, and Shadow's never does."""
    assert rj.question_version() == rj.question_version("shadow") == "b3202b420ab0"
    base = rj.question_version("test")
    assert base != rj.QUESTION_VERSION, base
    assert base != PRE_47B_TEST_VERSION, base
    real_draft, real_choices = rj.DRAFT, rj.TEST_CHOICES
    real_nouls, real_thresholds = rj.TEST_NOULS, rj.TEST_THRESHOLDS
    fmt = real_choices["asks_format"]
    for label, name, other in (
            ("drop a DRAFT member", "DRAFT", real_draft - {"offer_moment"}),
            ("add a DRAFT member", "DRAFT", real_draft | {"price"}),
            ("drop a Choice option", "TEST_CHOICES",
             {**real_choices, "asks_format": {**fmt, "criteria": {
                 k: v for k, v in fmt["criteria"].items() if k != "video"}}}),
            ("reword a DRAFT Noul", "TEST_NOULS",
             {**real_nouls, "counter_offer": {**real_nouls["counter_offer"], "instructions": "x"}}),
            ("move a test threshold", "TEST_THRESHOLDS", {**real_thresholds, "offer_moment": .6})):
        setattr(rj, name, other)
        try:
            moved, shadow = rj.question_version("test"), rj.question_version()
        finally:
            setattr(rj, name, {"DRAFT": real_draft, "TEST_CHOICES": real_choices,
                               "TEST_NOULS": real_nouls, "TEST_THRESHOLDS": real_thresholds}[name])
        assert moved != base, label
        assert shadow == "b3202b420ab0", label
    assert rj.question_version("test") == base


def case_choice_of():
    """Argmax over the Choice's probabilities; a tie at the top or a missing answer is
    anything / any."""
    rows = [
        ({"asks_subject": {"feet": .7, "butt": .2, "anything": .1}}, "asks_subject", "feet"),
        ({"asks_subject": {"feet": .3, "anything": .6, "tits": .1}}, "asks_subject", "anything"),
        ({"asks_format": {"photo": .1, "video": .8, "any": .1}}, "asks_format", "video"),
        ({"asks_subject": {"feet": .45, "butt": .45, "anything": .1}}, "asks_subject", "anything"),
        ({"asks_format": {"photo": .45, "video": .45, "any": .1}}, "asks_format", "any"),
        ({"asks_format": {"photo": .5, "video": .2}}, "asks_subject", "anything"),   # missing
        ({}, "asks_format", "any"),
        ({"asks_subject": {}}, "asks_subject", "anything"),
        ({"asks_subject": {"face": .9, "feet": .1}}, "asks_subject", "anything"),       # not offered
    ]
    for choices, qid, want in rows:
        got = rj.choice_of(choices, qid)
        assert got == want, (choices, qid, got, want)



# ── Sell rows haggle / offer_moment (03b ticket 47) ─────────────────────

_SELL_Q = ("complains_now", "wants_content", "says_yes_to_offer", "price", "declines_buying",
           "sexual_now", "counter_offer", "offer_moment")


def _before_sext(dropped: tuple[str, ...], row: str) -> tuple[str, ...]:
    """`row` placed after the sell / tease drops and before a dropped sexual_now."""
    i = dropped.index("sexual_now") if "sexual_now" in dropped else len(dropped)
    return (*dropped[:i], row, *dropped[i:])


def _sell_expect(fired, po, pt, oo, draft_on, sell_on, sext_on):
    """The expected (route, row, dropped), from the frozen pre-47 table (`_decide_before_47`,
    below) on the fired set without the DRAFT ids, changed only as the spec says (Interfaces ›
    full_ai_decide, Contracts › DRAFT gate): haggle right after rows 1-5, offer_moment after the
    tease rows and before sexual_now; a dropped haggle names sell_off, a dropped offer_moment
    names nothing; draft_on false = normal routing with each fired DRAFT id in `dropped`."""
    old = _decide_before_47(fd.Facts(fired - {"counter_offer", "offer_moment"}, 1.4, po, pt, True,
                                     sell_on=sell_on, sext_on=sext_on))
    if old.row in ("promo", "says_under_18", "complains_now", "asks_if_ai", "stop"):
        return old.route, old.row, ()
    co, om = "counter_offer" in fired, "offer_moment" in fired
    om_reached = om and old.row not in ("sell", "tease_price", "tease_decline")
    if not draft_on:
        dropped = (("counter_offer",) if co else ()) + old.dropped
        return old.route, old.row, _before_sext(dropped, "offer_moment") if om_reached else dropped
    haggle = co and (oo or pt)
    if haggle and sell_on:
        return "sell_now", "haggle", ()
    if om_reached and sell_on:
        return "sell_now", "offer_moment", ()
    row = "sell_off" if haggle and old.route == "chat" else old.row      # sell off from here on
    dropped = (("haggle",) if haggle else ()) + old.dropped
    return old.route, row, _before_sext(dropped, "offer_moment") if om_reached else dropped


def case_sell_rows_every_combination():
    from itertools import product
    n = 0
    for bits in product((False, True), repeat=len(_SELL_Q) + 6):
        fired = frozenset(q for q, b in zip(_SELL_Q, bits) if b)
        po, pt, oo, draft_on, sell_on, sext_on = bits[len(_SELL_Q):]
        d = fd.decide_turn(fd.Facts(fired, 1.4, po, pt, True, sell_on=sell_on, sext_on=sext_on,
                                    open_offer=oo, draft_on=draft_on))
        exp = _sell_expect(fired, po, pt, oo, draft_on, sell_on, sext_on)
        assert (d.route, d.row, d.dropped) == exp, (sorted(fired), bits[len(_SELL_Q):], d, exp)
        assert (d.heat, d.fired) == (2, fired), d
        n += 1
    assert n == 2 ** 14, n
    # Rows 1-5 each beat haggle and offer_moment, every flag and state on.
    for q in ("promo", "says_under_18", "complains_now", "asks_if_ai", "stop"):
        d = fd.decide_turn(_facts({q, "counter_offer", "offer_moment"}, pending_tease=True,
                                  open_offer=True, draft_on=True))
        assert (d.row, d.dropped) == (q, ()), (q, d)


def case_sell_rows_dropped():
    on, oo, pt = {"draft_on": True}, {"open_offer": True}, {"pending_tease": True}
    off, nosext = {"sell_on": False}, {"sext_on": False}
    rows = [
        # draft_questions off: the DRAFT id is dropped by name, routing as before.
        (({"counter_offer"}, oo), ("chat", "otherwise", ("counter_offer",))),
        (({"counter_offer", "wants_content"}, oo), ("sell_now", "sell", ("counter_offer",))),
        (({"counter_offer"}, pt), ("sell_now", "sell", ("counter_offer",))),
        (({"offer_moment"}, {}), ("chat", "otherwise", ("offer_moment",))),
        (({"offer_moment", "sexual_now"}, {}), ("sext", "sexual_now", ("offer_moment",))),
        (({"counter_offer", "offer_moment"}, oo), ("chat", "otherwise", ("counter_offer", "offer_moment"))),
        (({"counter_offer", "wants_content"}, {**oo, **off}),
         ("chat", "sell_off", ("counter_offer", "sell"))),
        # draft_on: haggle needs an open Offer or a Pending tease, and beats sell.
        (({"counter_offer"}, {**on, **oo}), ("sell_now", "haggle", ())),
        (({"counter_offer"}, {**on, **pt}), ("sell_now", "haggle", ())),
        (({"counter_offer", "wants_content"}, {**on, **oo}), ("sell_now", "haggle", ())),
        (({"counter_offer"}, on), ("chat", "otherwise", ())),
        (({"counter_offer", "sexual_now"}, on), ("sext", "sexual_now", ())),
        # The sell flag drops haggle and names sell_off.
        (({"counter_offer"}, {**on, **oo, **off}), ("chat", "sell_off", ("haggle",))),
        (({"counter_offer"}, {**on, **pt, **off}), ("chat", "sell_off", ("haggle", "sell"))),
        (({"counter_offer", "sexual_now"}, {**on, **oo, **off}), ("sext", "sexual_now", ("haggle",))),
        # offer_moment: after the tease rows, before sexual_now.
        (({"offer_moment"}, on), ("sell_now", "offer_moment", ())),
        (({"offer_moment", "sexual_now"}, on), ("sell_now", "offer_moment", ())),
        (({"offer_moment", "price"}, on), ("tease", "tease_price", ())),
        (({"offer_moment", "wants_content"}, on), ("sell_now", "sell", ())),
        # The sell flag drops offer_moment and names nothing (no sell-off line).
        (({"offer_moment"}, {**on, **off}), ("chat", "otherwise", ("offer_moment",))),
        (({"offer_moment", "sexual_now"}, {**on, **off}), ("sext", "sexual_now", ("offer_moment",))),
        (({"offer_moment", "sexual_now"}, {**on, **off, **nosext}),
         ("chat", "sext_off", ("offer_moment", "sexual_now"))),
        (({"offer_moment", "price"}, {**on, **off}), ("chat", "tease_off", ("tease_price", "offer_moment"))),
        # Rows 1-5 first: nothing dropped.
        (({"complains_now", "counter_offer"}, {**on, **oo}), ("make_right", "complains_now", ())),
        (({"stop", "offer_moment"}, {**on, **off}), ("chat", "stop", ())),
    ]
    for (fired, extra), exp in rows:
        d = fd.decide_turn(_facts(fired, **extra))
        assert (d.route, d.row, d.dropped) == exp, (fired, extra, d, exp)
    # A Jev failure walks no row, DRAFT ids included.
    d = fd.decide_turn(_facts({"counter_offer", "offer_moment"}, jev_ok=False, **on, **oo))
    assert (d.route, d.row, d.dropped) == ("chat", "jev_failed", ()), d


def _decide_before_47(facts):
    """FROZEN: `full_ai_decide.decide_turn` as it was before ticket 47 (main f3ad378e1),
    copied verbatim so the Shadow proof compares against the real previous table."""
    f = facts.fired
    if not facts.jev_ok:
        return fd.Decision("chat", 1, "jev_failed", f)
    heat = fd.heat_of(facts.intensity)
    for q, route in fd._FIRST:
        if q in f:
            return fd.Decision(route, heat, q, f)
    sell = "wants_content" in f or ("says_yes_to_offer" in f and facts.pending_offer) or facts.pending_tease
    tease = "tease_price" if "price" in f else "tease_decline" if "declines_buying" in f else ""
    flagged = (("sell", "sell_now", facts.sell_on, bool(sell), "sell_off"),
               (tease, "tease", facts.sell_on, bool(tease), "tease_off"),
               ("sexual_now", "sext", facts.sext_on, "sexual_now" in f, "sext_off"))
    dropped: list[str] = []
    end = "otherwise"
    for row, route, on, match, off_row in flagged:
        if match and on:
            return fd.Decision(route, heat, row, f, tuple(dropped))
        if match:
            end = off_row if not dropped else end
            dropped.append(row)
    return fd.Decision("chat", heat, end, f, tuple(dropped))


def case_shadow_equals_the_pre_47_table():
    """Shadow (draft_on false, the default; flags on and off alike): the same Decision as the
    pre-47 table on every fired set of the 11 Phase 01 ids, whatever open Offer says."""
    from itertools import product
    n = 0
    for bits in product((False, True), repeat=len(IDS) + 6):
        fired = frozenset(q for q, b in zip(IDS, bits) if b)
        po, pt, oo, jev_ok, sell_on, sext_on = bits[len(IDS):]
        facts = fd.Facts(fired, 2.6, po, pt, jev_ok, sell_on=sell_on, sext_on=sext_on, open_offer=oo)
        assert fd.decide_turn(facts) == _decide_before_47(facts), (sorted(fired), bits[len(IDS):])
        n += 1
    assert n == 2 ** 17, n
    # Today's caller (full_ai_turn._route) passes no new keyword: draft_on and open_offer default off.
    assert (fd.Facts(frozenset(), 0.0, False, False, True).draft_on,
            fd.Facts(frozenset(), 0.0, False, False, True).open_offer) == (False, False)


# ── Sext scene (config `sext_scene`, owner 2026-11-14) ─────────────────

SCENE_IDS = {"scene_on": "Noul", "scene_offer": "Noul", "scene_stage": "Choice", "offer_level": "Choice"}


def case_scene_questions():
    """The SCENE ids join test Mode's request only with `scene`; never DRAFT; the test digest
    moved off its pre-scene value and moves with their wording; Shadow's never."""
    assert rj.SCENE == frozenset(SCENE_IDS) and not rj.SCENE & rj.DRAFT
    off, on = rj._questions("test"), rj._questions("test", scene=True)
    assert set(on) - set(off) == set(SCENE_IDS), sorted(set(on) - set(off))
    assert {q: type(on[q]).__name__ for q in SCENE_IDS} == SCENE_IDS
    assert list(on["scene_stage"].criteria) == ["opening", "building", "peak", "after", "none"]
    assert list(on["offer_level"].criteria) == ["soft", "nude", "explicit"]
    assert list(rj._questions("shadow", scene=True)) == [*IDS, "intensity"]
    assert rj.CHOICE_DEFAULT["scene_stage"] == "building" and rj.CHOICE_DEFAULT["offer_level"] == "any"
    base = rj.question_version("test")
    assert base != PRE_SCENE_TEST_VERSION, base
    real = rj.TEST_NOULS
    rj.TEST_NOULS = {**real, "scene_on": {**real["scene_on"], "instructions": "x"}}
    try:
        assert rj.question_version("test") != base
        assert rj.question_version() == "b3202b420ab0"
    finally:
        rj.TEST_NOULS = real
    real_keys = rj.SCENE_STATE_KEYS
    rj.SCENE_STATE_KEYS = ("purchases",)
    try:
        assert rj.question_version("test") != base
    finally:
        rj.SCENE_STATE_KEYS = real_keys
    rows = [   # (choices, qid, choice_of, choice_or_none)
        ({"scene_stage": {"peak": .8, "building": .2}}, "scene_stage", "peak", "peak"),
        ({"scene_stage": {"peak": .5, "building": .5}}, "scene_stage", "building", None),
        ({}, "scene_stage", "building", None),
        (None, "scene_stage", "building", None),
        ({"offer_level": {"nude": .6, "soft": .4}}, "offer_level", "nude", "nude"),
        ({"offer_level": {"any": .9}}, "offer_level", "any", None),     # "any" is never offered
        ({}, "offer_level", "any", None),
    ]
    for choices, qid, want, want_none in rows:
        assert rj.choice_of(choices or {}, qid) == want, (choices, qid)
        assert rj.choice_or_none(choices, qid) == want_none, (choices, qid)
    # test Mode fires them at .7; Shadow never reads them.
    q = _quiet(scene_on=.7, scene_offer=.69)
    assert rj.fired(q, "test") == frozenset({"scene_on"}) and rj.fired(q) == frozenset()


def case_scene_rows():
    """Worked rows with `scene` on (every flag on unless named)."""
    on, nosell, nosext = {"scene": True}, {"scene": True, "sell_on": False}, {"scene": True, "sext_on": False}
    rows = [
        (({"scene_on"}, on), ("sext", "scene_on", ())),
        (({"scene_on", "sexual_now"}, on), ("sext", "sexual_now", ())),
        (({"scene_on"}, nosext), ("chat", "sext_off", ("scene_on",))),
        (({"scene_offer"}, on), ("chat", "otherwise", ())),                 # no scene: nothing
        (({"scene_offer", "scene_on"}, on), ("sell_now", "scene_offer", ())),
        (({"scene_offer", "sexual_now"}, on), ("sell_now", "scene_offer", ())),
        (({"scene_offer", "scene_on"}, nosell), ("sext", "scene_on", ("scene_offer",))),
        (({"scene_offer", "scene_on"}, {**nosell, "sext_on": False}),
         ("chat", "sext_off", ("scene_offer", "scene_on"))),
        (({"scene_offer", "scene_on", "wants_content"}, on), ("sell_now", "sell", ())),
        (({"scene_offer", "scene_on", "price"}, on), ("tease", "tease_price", ())),
        (({"scene_offer", "scene_on", "offer_moment"}, {**on, "draft_on": True}),
         ("sell_now", "offer_moment", ())),
        (({"scene_offer", "scene_on", "stop"}, on), ("chat", "stop", ())),
    ]
    for (fired, flags), want in rows:
        d = fd.decide_turn(_facts(fired, 2.0, **flags))
        assert (d.route, d.row, d.dropped) == want, (sorted(fired), flags, d)


def case_scene_off_is_the_old_table():
    """`scene` false (Shadow, live, flag off): the scene ids are ignored, not recorded — every
    fired set decides exactly as without them."""
    from itertools import product
    ids = ("wants_content", "price", "sexual_now", "offer_moment", "counter_offer")
    n = 0
    for bits in product((False, True), repeat=len(ids) + 6):
        base = frozenset(q for q, b in zip(ids, bits) if b)
        so, sf, sell_on, sext_on, draft_on, oo = bits[len(ids):]
        extra = {q for q, b in (("scene_on", so), ("scene_offer", sf)) if b}
        kw = dict(sell_on=sell_on, sext_on=sext_on, draft_on=draft_on, open_offer=oo)
        with_ids = fd.decide_turn(_facts(base | extra, 2.0, **kw))
        without = fd.decide_turn(_facts(base, 2.0, **kw))
        assert (with_ids.route, with_ids.row, with_ids.dropped) == \
            (without.route, without.row, without.dropped), (sorted(base | extra), kw)
        n += 1
    assert n == 2 ** 11, n


_harness.run()
