#!/usr/bin/env python3
"""test_full_ai_mode — the Mode gate (04a ticket 64, automations/full_ai_mode.py): a `live` Turn
asks the same questions, fires the same flags and builds the same Writer request as a `test` Turn.

  case_full_table                 full(): test, live True; shadow, None, "nope" False
  case_flags_live_equals_test     every full_ai_writers `*_flag` + bundle_of / nearest_line /
                                  _sell_off_test, each key on / off: live == test; Shadow off
  case_question_version           live == test; shadow == its 9e9014c36 value
  case_questions_same_ids         _questions ids + order: live == test over every flag combination
  case_fired_same                 fired(live) == fired(test) over the threshold edge table
  case_draft_gate_same            _route's draft_on: live == test for draft_questions on / off
  case_writer_request_same        messages_for: live == test per Route
  case_rules_live_is_test         rules("live") == rules("test") but `mode`; "nope" raises; route 200
  case_no_test_compare_left       AST: no Compare against "test" in the four modules but
                                  load_turn_facts' Test chat branch

Run: ./venv/bin/python service/tests/test_full_ai_mode.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness

_harness.bootstrap()

import ast  # noqa: E402
import inspect  # noqa: E402
import asyncio  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import auth  # noqa: E402
import full_ai_api  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_rules as fr  # noqa: E402
from automations import full_ai_turn as ft  # noqa: E402
from automations import full_ai_writers as fw  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from automations.full_ai_mode import MODES, full  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402

AUTOMATIONS = Path(__file__).resolve().parents[1] / "automations"
FOUR = ("full_ai_writers.py", "_router_jev.py", "full_ai_turn.py", "full_ai_rules.py")
SHADOW_QV_9E9014C36 = "14f5d4f6222f"
KEYS = {"sext_scene": (True, False), "lead_in": (True, False), "sell_nearest": ("plain", "note", "off"),
        "sell_spacing": (True, False), "he_likes": (True, False), "sell_bundle": ("fill", "shoot"),
        "chat_tease": (True, False), "ask_implied": (True, False), "info_wide": (True, False),
        "sell_count": (True, False), "sell_on": (True, False)}


def _f(mode, **cfg):
    return SimpleNamespace(mode=mode, config={**DEFAULTS, **cfg})


def _turn_facts(mode, **cfg) -> ft.TurnFacts:
    return ft.TurnFacts(account_id="acct_mode", fan_id=1, mode=mode, anchor_key="42", state={},
                        cut_rows=[], bought=None, offer=None, fan_info={}, asked={},
                        config={**DEFAULTS, **cfg}, side="checkpoint")


def case_full_table():
    assert MODES == ("test", "shadow", "live") and fr.MODES == ("test", "live")   # rules page: no Shadow (W30 #6)
    for mode, want in (("test", True), ("live", True), ("shadow", False), (None, False), ("nope", False),
                       ("", False), ("Test", False)):
        assert full(mode) is want, mode


def case_flags_live_equals_test():
    gates = sorted(n for n in dir(fw) if n.endswith("_flag") and callable(getattr(fw, n)))
    assert len(gates) >= 8, gates
    fns = [getattr(fw, n) for n in gates] + [fw.bundle_of, fw._sell_off_test]
    pick = Pick(ref=11, media=(11, 12), previews=(), price_cents=5000, list_cents=5000, subject="anything",
                format="video", lane="vault", facts={"asked": {"subject": "feet", "format": "video"}})
    n = 0
    for fn in fns:
        for key, values in KEYS.items():
            for v in values:
                live, test, shadow = (fn(_f(m, **{key: v})) for m in ("live", "test", "shadow"))
                assert live == test, (fn.__name__, key, v, live, test)
                assert shadow in (False, "shoot"), (fn.__name__, key, v, shadow)
                n += 1
    for v in KEYS["sell_nearest"]:
        got = {m: fw.nearest_line(_f(m, sell_nearest=v), pick) for m in ("live", "test", "shadow")}
        assert got["live"] == got["test"] and got["shadow"] is None, (v, got)
        # client rule 2026-11-16: a tagged Pick gets the note unless the side says "plain"
        assert (got["live"] is not None) is (v != "plain"), (v, got)
    # Each named gate really is on for both full Modes with its key on.
    on = {**DEFAULTS, "sext_scene": True, "lead_in": True, "sell_nearest": "plain", "sell_spacing": True,
          "he_likes": True, "chat_tease": True, "ask_implied": True, "info_wide": True, "sell_count": True}
    for g in gates:
        f = getattr(fw, g)
        assert f(SimpleNamespace(mode="live", config=on)) is True, g
    assert n > 100, n


def case_question_version():
    assert rj.question_version("live") == rj.question_version("test")
    assert rj.question_version("shadow") == SHADOW_QV_9E9014C36 == rj.QUESTION_VERSION


def _dump(q: dict) -> list:
    return [(k, v.model_dump(mode="json")) for k, v in q.items()]


def case_questions_same_ids():
    n = 0
    for scene, spacing, likes, tease, implied in itertools.product((False, True), repeat=5):
        kw = dict(scene=scene, spacing=spacing, likes=likes, tease=tease, implied=implied)
        live, test = rj._questions("live", **kw), rj._questions("test", **kw)
        assert list(live) == list(test) and _dump(live) == _dump(test), kw
        assert list(rj._questions("shadow", **kw)) == [*rj.QUESTIONS, "intensity"], kw
        n += 1
    assert n == 32


def case_fired_same():
    base = {q: 0.0 for q in {**rj.THRESHOLDS, **rj.TEST_THRESHOLDS}}
    edges = {0.0, 0.5, 0.649, 0.65, 0.69, 0.6999, 0.7, 0.71, 0.9, 0.949, 0.95, 1.0}
    edges |= set(rj.THRESHOLDS.values()) | set(rj.TEST_THRESHOLDS.values())
    for q in base:
        for p in sorted(edges):
            a = {**base, q: p}
            assert rj.fired(a, "live") == rj.fired(a, "test"), (q, p)
    for p, full_want, shadow_want in ((0.65, True, False), (0.69, True, False), (0.7, True, True),
                                      (0.649, False, False)):
        a = {**base, "wants_content": p}
        assert ("wants_content" in rj.fired(a, "live")) is full_want, p
        assert ("wants_content" in rj.fired(a, "test")) is full_want, p
        assert ("wants_content" in rj.fired(a, "shadow")) is shadow_want, p
    a = {q: 1.0 for q in base}
    assert rj.fired(a, "live") == rj.fired(a, "test") > rj.fired(a, "shadow")


async def _draft_on(mode: str, draft: bool) -> bool:
    seen = []
    real_ask, real_decide = rj.ask, ft.decide_turn

    async def fake_ask(*a, **kw):
        answers = {q: 0.0 for q in {**rj.THRESHOLDS, **rj.TEST_THRESHOLDS}}
        return rj.Answers(answers, 0.0, {}, "m", 1, {})

    def spy(facts):
        seen.append(facts)
        return real_decide(facts)
    rj.ask, ft.decide_turn = fake_ask, spy
    try:
        await ft._route(_turn_facts(mode, draft_questions=draft), time.monotonic() + 30)
    finally:
        rj.ask, ft.decide_turn = real_ask, real_decide
    (f,) = seen
    return f.draft_on


async def case_draft_gate_same():
    for draft in (False, True):
        assert await _draft_on("live", draft) == await _draft_on("test", draft) == draft, draft
        assert await _draft_on("shadow", draft) is False, draft


def case_writer_request_same():
    pick = Pick(ref=11, media=(11, 12), previews=(), price_cents=5000, list_cents=5000, subject="anything",
                format="video", lane="vault", facts={"description": "a clip", "asked": {"subject": "feet", "format": "video"}})
    cfg = dict(sext_scene=True, lead_in=True, he_likes=True, chat_tease=True, ask_implied=True,
               info_wide=True, sell_nearest="note")
    n = 0
    for route, row in (("chat", "otherwise"), ("sext", "sexual_now"), ("make_right", "complains_now"),
                       ("ai_dare", "asks_if_ai"), ("sell_now", "sell"), ("tease", "otherwise")):
        for p in (None, pick) if route == "sell_now" else (None,):
            live = fw.messages_for(route, row, 2, _turn_facts("live", **cfg), p)
            test = fw.messages_for(route, row, 2, _turn_facts("test", **cfg), p)
            assert live == test, (route, row)
            n += 1
    assert n >= 6


async def case_rules_live_is_test():
    assert json.dumps(fr.rules("live")).replace('"live"', '"test"') == json.dumps(fr.rules("test"))
    assert fr.rules("live")["mode"] == "live"
    try:
        fr.rules("nope")
    except ValueError:
        pass
    else:
        raise AssertionError("rules('nope') served")
    tok = auth._request_user.set(auth.AuthedUser("u_mode", "mode_owner", frozenset({"acct_mode"})))
    try:
        got = await full_ai_api.full_ai_rules_read(mode="live")
    finally:
        auth._request_user.reset(tok)
    assert got["mode"] == "live" and got["nodes"], got.keys()
    lit = inspect.signature(full_ai_api.full_ai_rules_read).parameters["mode"].annotation
    assert "live" in str(lit), lit


def _test_compares(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text())
    out: list[tuple[str, int]] = []

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(child, ast.Compare):
                consts = [child.left, *child.comparators]
                if any(isinstance(c, ast.Constant) and c.value == "test" for c in consts):
                    out.append((name, child.lineno))
            walk(child, name)
    walk(tree, "<module>")
    return out


def case_no_test_compare_left():
    found = {f: _test_compares(AUTOMATIONS / f) for f in FOUR}
    allowed = {"full_ai_turn.py": ["load_turn_facts"]}
    for f, hits in found.items():
        assert [fn for fn, _ in hits] == allowed.get(f, []), (f, hits)
    planted = ast.parse('def g(mode):\n    return mode == "test"\n')
    assert any(isinstance(n, ast.Compare) for n in ast.walk(planted))


_harness.run()
