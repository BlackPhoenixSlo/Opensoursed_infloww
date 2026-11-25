from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import sys
from pathlib import Path

GATE = Path.home() / ".slop/gate.py"
EXCLUSIVE_USERS = 120


SCALES = ("small", "medium", "huge")


class ArgError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgError(message)


def add_load_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--scale", choices=list(SCALES), default="small")
    ap.add_argument("--users", type=int, default=20, help="concurrent simulated users per actor pool")


def exclusive(argv: list[str]) -> bool:
    ap = _Parser(add_help=False, allow_abbrev=False)
    add_load_args(ap)
    ns, _ = ap.parse_known_args(argv)
    return goes_alone(ns.scale, ns.users)


def goes_alone(scale: str, users: int) -> bool:
    return scale != "small" and users >= EXCLUSIVE_USERS


def nice10() -> None:
    os.setpriority(os.PRIO_PROCESS, 0, max(10, os.getpriority(os.PRIO_PROCESS, 0)))


class Busy(Exception):
    pass


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
                 max_sockets_run: int | None = None, exclusive: bool = False):
    if os.environ.get("SLOP_GATE") == "off":
        yield {}
        return
    g = _load()
    limits = {k: v for k, v in (("max_threads_proc", max_threads_proc), ("max_sockets_run", max_sockets_run)) if v}
    gate = g.Gate(cmd=f"slop/run {' '.join(sys.argv[1:])}", no_wait=not wait,
                  evidence_dir=str(evidence) if evidence else None, exclusive=exclusive, **limits)
    try:
        gate.__enter__()
    except g.Busy as e:
        raise Busy(str(e)) from None
    try:
        yield {"lock_wait_s": gate.wait_s, "load_at_start": gate.load_at_start, **limits}
    finally:
        gate.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        print("--exclusive" if exclusive(sys.argv[1:]) else "")
    except ArgError as e:
        print(f"slop: cannot tell whether this run goes alone (--scale/--users): {e}", file=sys.stderr)
        sys.exit(2)
