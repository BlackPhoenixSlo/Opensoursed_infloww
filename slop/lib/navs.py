from __future__ import annotations

import importlib
from pathlib import Path

NAMES = frozenset({"MY_AUTOMATIONS", "SWEEP_ROUTES", "TABS"})


def extras(attr: str) -> tuple:
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
