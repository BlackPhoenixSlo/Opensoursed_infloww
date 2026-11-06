"""The machine gate (README "The machine gate"): loads the machine's one gate.

The gate is ~/.slop/gate.py, outside git here: one file every repo and harness on the machine
shares (versioned by ~/.slop's own git), never copied in. `machine_gate(wait, evidence)` holds one
of its SLOP_MAX_RUNS slots from before the stack starts until teardown, waits for admission (load,
machine threads) and the start stagger, renices this process to 10, and runs its thread guard over this process tree (a
breach SIGKILLs the tree, writes <evidence>/thread-guard.txt and exits 75). A missing gate is INFRA,
never a silent skip. SLOP_GATE=off: no gate (only where nothing else runs: deploy/fleet/calibrate.sh's
containers, which have no ~/.slop).
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from pathlib import Path

GATE = Path(os.environ.get("SLOP_GATE_PY") or Path.home() / ".slop/gate.py")


class Busy(Exception):
    """The gate gave up or is missing: one line, the run's INFRA reason."""


def _load():
    if not GATE.is_file():
        raise Busy(f"{GATE} missing: it is the machine's slot gate (slop/README.md \"The machine "
                   f"gate\"). Restore it: `git -C {GATE.parent} checkout -- gate.py` (~/.slop is its git repo). "
                   "SLOP_GATE=off runs ungated: only on a host with nothing else on it")
    spec = importlib.util.spec_from_file_location("slop_machine_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def machine_gate(wait: bool = True, evidence: Path | None = None):
    """Yields {"lock_wait_s": seconds in the gate (slot + admission + stagger), "load_at_start": 1-min load}."""
    if os.environ.get("SLOP_GATE") == "off":
        yield {}
        return
    g = _load()
    gate = g.Gate(cmd=f"slop/run {' '.join(sys.argv[1:])}", no_wait=not wait,
                  evidence_dir=str(evidence) if evidence else None)
    try:
        gate.__enter__()
    except g.Busy as e:
        raise Busy(str(e)) from None
    try:
        yield {"lock_wait_s": gate.wait_s, "load_at_start": gate.load_at_start}
    finally:
        gate.__exit__(None, None, None)
