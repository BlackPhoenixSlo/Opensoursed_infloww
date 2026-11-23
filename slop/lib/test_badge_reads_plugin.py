"""lib/badge_reads_relay.py starts the badge reads loop at relay startup (CHATTERLY_TEST_MODE skips the product's)."""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent


class _App:
    def __init__(self):
        self.startup = []

    def on_event(self, name):
        assert name == "startup"
        return self.startup.append


def test_plugin_is_loaded_by_relay_glob():
    assert "badge_reads_relay" in {p.stem for p in LIB.glob("*_relay.py")}


def test_startup_starts_badge_reads(monkeypatch: pytest.MonkeyPatch):
    plugin = importlib.import_module("slop.lib.badge_reads_relay")
    calls = []
    monkeypatch.setitem(sys.modules, "badge_reads", types.SimpleNamespace(start=lambda: calls.append(1)))
    app = _App()
    plugin.wire(app, None, None)
    for hook in app.startup:
        asyncio.run(hook())
    assert calls == [1]
