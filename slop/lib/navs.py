"""Pages a flow in files of its own adds to shared scenarios: every lib/<flow>_nav.py (never public when the flow is
not) may define
  MY_AUTOMATIONS  sidebar pages under My Automations (scenarios/2026-11-07-ai-chatter-nav.py)
  SWEEP_ROUTES    signed-in routes for the page sweep (scenarios/2026-10-28-dashboard-load.py)
  TABS            (name, path, ready selector) live tabs (scenarios/2026-10-24-big-model-dm-flood.py)
and nothing else upper-case: a typo would drop that flow's coverage silently, so any other name is an error.
"""
from __future__ import annotations

import importlib
from pathlib import Path

NAMES = frozenset({"MY_AUTOMATIONS", "SWEEP_ROUTES", "TABS"})


def extras(attr: str) -> tuple:
    """Every lib/*_nav.py's `attr`, joined in file order."""
    if attr not in NAMES:
        raise KeyError(f"navs.extras({attr!r}): not one of {sorted(NAMES)}")
    out = []
    for m in sorted(Path(__file__).parent.glob("*_nav.py")):
        mod = importlib.import_module(f"slop.lib.{m.stem}")
        bad = {n for n in vars(mod) if n.isupper() and n not in NAMES}
        if bad:
            raise KeyError(f"lib/{m.name} defines {sorted(bad)}: not one of {sorted(NAMES)}")
        out.extend(getattr(mod, attr, ()))
    return tuple(out)
