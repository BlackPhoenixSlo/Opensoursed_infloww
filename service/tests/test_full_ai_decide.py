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
                              under it does not
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

Run: ./venv/bin/python service/tests/test_full_ai_decide.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_decide as fd  # noqa: E402

# OWNER-REVIEW-router.md items 1-10 and 12, in that order (spec › Interfaces).
IDS = ("promo", "says_under_18", "complains_now", "asks_if_ai", "stop", "price",
       "wants_content", "declines_buying", "says_yes_to_offer", "sexual_now", "gif_fits")
THRESHOLDS = {"promo": .7, "says_under_18": .7, "complains_now": .5, "asks_if_ai": .7,
              "stop": .6, "price": .7, "wants_content": .7, "declines_buying": .5,
              "says_yes_to_offer": .7, "sexual_now": .7, "gif_fits": .6}


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
    """Sell off: sell and tease turn chat (rows sell_off, tease_off); sext off:
    sext turns chat (row sext_off); no flag touches any other row."""
    off, nosext = {"sell_on": False}, {"sext_on": False}
    rows = [
        (({"wants_content"}, off), ("chat", "sell_off")),
        (({"says_yes_to_offer"}, {"pending_offer": True, **off}), ("chat", "sell_off")),
        ((set(), {"pending_tease": True, **off}), ("chat", "sell_off")),
        (({"wants_content", "sexual_now"}, off), ("chat", "sell_off")),
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


_harness.run()
