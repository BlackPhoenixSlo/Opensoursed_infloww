"""Catch stale cross-module imports before a scenario starts its stack."""

import importlib.util
import importlib
import runpy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted((ROOT / "lib").glob("*.py")) + sorted((ROOT / "scenarios").glob("*.py"))


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_imports(path, monkeypatch):
    if path.parent.name == "lib":
        if path.stem == "relay":
            monkeypatch.setenv("DEMO_SHOTS_ROOT", str(ROOT.parent))
            monkeypatch.setattr(runpy, "run_path", lambda *_a, **_kw: None)
        sys.path.insert(0, str(path.parent))
        try:
            importlib.import_module(f"slop.lib.{path.stem}")
        finally:
            sys.path.remove(str(path.parent))
        return
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
