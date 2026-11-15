#!/usr/bin/env python3
"""test_full_ai_heat — the Heat check's pure parts (ticket 96, spec 06), plain assert.

  case_level_of_table        2.49 -> 2, 2.5 -> 3, 3.5 -> 4, 0 -> 0 (`heat_of`'s rounding, a tie up)
  case_over_table            her level above the cap; at cap 4 nothing is over
  case_wording_is_intensity  REPLY_LEVEL is INTENSITY turned on her: same shape, his -> her
  case_wording_in_catalog    REPLY_LEVEL pinned to docs/prompts NEW-155 and its README row
  case_version_moves         HEAT_VERSION moves with the wording
  case_no_mode_check         `_heat_jev` and `_heat_check` read no Mode

Run: ./venv/bin/python service/tests/test_full_ai_heat.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB before any db import

import inspect  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from automations import _heat_jev as hj  # noqa: E402
from automations import _router_jev as rj  # noqa: E402
from automations import full_ai_turn  # noqa: E402

_DOCS = Path(__file__).resolve().parents[2] / "docs" / "prompts"


def case_level_of_table():
    for score, want in ((2.49, 2), (2.5, 3), (3.5, 4), (0, 0), (0.49, 0), (0.5, 1), (4.0, 4)):
        assert hj.level_of(score) == want, (score, hj.level_of(score), want)


def case_over_table():
    for score, cap, want in ((4.0, 3, True), (3.0, 3, False), (3.5, 3, True), (3.49, 3, False),
                             (2.5, 2, True), (2.49, 2, False), (1.5, 1, True), (1.0, 1, False)):
        assert hj.over(score, cap) is want, (score, cap, want)
    for score in (0, 1.5, 2.5, 3.5, 4.0):
        assert hj.over(score, 4) is False, score


def case_wording_is_intensity():
    swap = lambda t: (t.replace("the fan writes", "she writes").replace("fan_new_messages", "her_reply")   # noqa: E731
                      .replace("with her", "with him").replace("to see", "to show him")
                      .replace(" he ", " she ").replace("He ", "She ").replace(" her ", " his "))
    assert hj.REPLY_LEVEL["instructions"] == swap(rj.INTENSITY["instructions"]), hj.REPLY_LEVEL["instructions"]
    assert len(hj.REPLY_LEVEL["criteria"]) == len(rj.INTENSITY["criteria"]) == 5
    for mine, his in zip(hj.REPLY_LEVEL["criteria"], rj.INTENSITY["criteria"]):
        assert mine == swap(his), (mine, swap(his))


def case_wording_in_catalog():
    doc = (_DOCS / "new" / "current-repo.md").read_text(encoding="utf-8")
    assert "### NEW-155 " in doc
    entry = doc.split("### NEW-155 ", 1)[1].split("\n### ", 1)[0]
    assert "owner OK" in entry.split("\n", 1)[0], entry.split("\n", 1)[0]
    assert hj.HEAT_VERSION in entry, "version line"
    block = entry.split("```text\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(block) == hj.REPLY_LEVEL, block
    readme = (_DOCS / "README.md").read_text(encoding="utf-8")
    assert "| NEW-155 |" in readme, "README index row"


def case_version_moves():
    real = hj.REPLY_LEVEL
    try:
        hj.REPLY_LEVEL = {**real, "instructions": real["instructions"] + " "}
        assert hj.heat_version() != hj.HEAT_VERSION
    finally:
        hj.REPLY_LEVEL = real
    assert hj.heat_version() == hj.HEAT_VERSION and len(hj.HEAT_VERSION) == 12


def case_no_mode_check():
    src = Path(hj.__file__).read_text(encoding="utf-8")
    assert "mode ==" not in src and "mode !=" not in src and ".mode" not in src
    fn = inspect.getsource(full_ai_turn._heat_check)
    assert "mode" not in fn.replace("Mode check", ""), "the Heat check reads no Mode"


_harness.run()
