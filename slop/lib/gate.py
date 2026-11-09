"""The machine gate (README "The machine gate"): loads the machine's one gate.

The gate is ~/.slop/gate.py, outside git here: one file every repo and harness on the machine
shares (versioned by ~/.slop's own git), never copied in. slop/run holds one slot and takes
admission once for its whole invocation. Nested `machine_gate(wait, evidence, max_threads_proc)`
supplies the scenario evidence folder and its declared per-process thread limit (the scenario's
`MAX_THREADS_PROC` for this --scale; the gate caps it at SLOP_MAX_THREADS_PROC_CEIL) to the guard,
and its declared per-run socket limit (`MAX_SOCKETS_RUN`, honoured only for an exclusive run; the
gate caps it at SLOP_MAX_SOCKETS_RUN_CEIL), and checks that the gate exists. `exclusive(argv)`: a
--scale of medium or larger with --users >= 120 runs alone (README "medium/120 runs go alone");
`slop/run` asks it (`python3 slop/lib/gate.py <args>` prints `--exclusive` or nothing) before it
re-execs under `gate.py run`. A missing gate is INFRA,
never a silent skip. SLOP_GATE=off: no gate (only where nothing else runs: deploy/fleet/calibrate.sh's
containers, which have no ~/.slop).
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from pathlib import Path

GATE = Path.home() / ".slop/gate.py"
EXCLUSIVE_USERS = 120  # with --scale >= medium: the run goes alone


def _arg(argv: list[str], flag: str) -> str | None:
    for i, a in enumerate(argv):
        if a == flag and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def exclusive(argv: list[str]) -> bool:
    """--scale medium or larger (anything but small, the only smaller one) and --users >= 120."""
    users = _arg(argv, "--users") or ""
    return (_arg(argv, "--scale") or "small") != "small" and users.isdigit() and int(users) >= EXCLUSIVE_USERS


def nice10() -> None:
    """Give harness and child processes foreground-friendly priority."""
    os.setpriority(os.PRIO_PROCESS, 0, max(10, os.getpriority(os.PRIO_PROCESS, 0)))


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
def machine_gate(wait: bool = True, evidence: Path | None = None, max_threads_proc: int | None = None,
                 max_sockets_run: int | None = None):
    """Yields {"lock_wait_s": seconds in the gate (slot + admission + stagger), "load_at_start": 1-min load,
    + "max_threads_proc" / "max_sockets_run" when declared}."""
    if os.environ.get("SLOP_GATE") == "off":
        yield {}
        return
    g = _load()
    limits = {k: v for k, v in (("max_threads_proc", max_threads_proc), ("max_sockets_run", max_sockets_run)) if v}
    gate = g.Gate(cmd=f"slop/run {' '.join(sys.argv[1:])}", no_wait=not wait,
                  evidence_dir=str(evidence) if evidence else None, exclusive=exclusive(sys.argv[1:]), **limits)
    try:
        gate.__enter__()
    except g.Busy as e:
        raise Busy(str(e)) from None
    try:
        yield {"lock_wait_s": gate.wait_s, "load_at_start": gate.load_at_start, **limits}
    finally:
        gate.__exit__(None, None, None)


if __name__ == "__main__":  # slop/run: `--exclusive` for gate.py run when this run goes alone
    print("--exclusive" if exclusive(sys.argv[1:]) else "")
