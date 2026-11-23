"""state-reducers' FANLIST_REWARM wants the return's `?bust=` to re-read OF: its wait must clear the Relay's Hover
cooldown, or the bust answers the held, pre-flip count."""
import importlib
from pathlib import Path

import pytest

from slop.lib.cli import SCEN, load

ROOT = Path(__file__).resolve().parents[2]
m = load(SCEN / "2026-10-29-state-reducers.py")


@pytest.fixture
def decide(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "service"))
    return importlib.import_module("badge_reads_decide")


@pytest.mark.parametrize("off,counter_on", [(False, True), (False, False)])
def test_the_return_bust_reads_of_after_the_wait(decide, off, counter_on):
    last_start = 1_700_000_000_000
    now = last_start + int(m.HOVER_COOLDOWN_S * 1000)
    assert decide.hover(last_start, False, now, off, counter_on) in ("read", "direct")


def test_a_bust_inside_the_cooldown_answers_the_held_count(decide):
    last_start = 1_700_000_000_000
    assert decide.hover(last_start, False, last_start + decide.HOVER_COOLDOWN_MS - 1, False, True) == "held"
