#!/usr/bin/env python3
"""
No loop may compute its own sleep without a floor.

2026-08-21: `transaction_ingest` slept for `interval - elapsed`. A cycle that
overran its interval made that negative, `asyncio.sleep()` returned instantly,
and the loop spun. The box sat at 100% CPU for ~4 hours; Hostinger applied a
CPU cap; the cap outlived the fix by ~18 hours. One missing `max()`.

Two halves:
  1. A STATIC guard over every module under service/ — any `sleep(...)` whose
     delay is computed by subtraction must be wrapped in `max(...)`. Parsed
     with `ast`, not grep, so `max(FLOOR, interval - elapsed)` reads as safe
     and `sleep(interval - elapsed)` does not. A checker that cries wolf gets
     deleted; this one should only fire on the real shape.
  2. Unit cases for `cadence`, including the two properties that actually
     matter: the floor survives a raising body, and cancellation is not
     delayed by it.

Deliberate exception: put `# cadence-ok: <reason>` on the sleep line.

Plain-assert standalone script (no pytest), run via:
    ./venv/bin/python service/tests/test_loop_cadence_guard.py
Exit 0 = all pass.
"""
from __future__ import annotations

import ast
import asyncio
import sys
import time
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
for _p in (_SERVICE, _SERVICE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from cadence import cadence  # noqa: E402

_failures: list[str] = []


def _expect(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


# ── Half 1: the static guard ────────────────────────────────────────────

def _unguarded_subtractions(tree: ast.AST) -> bool:
    """True if `tree` contains a subtraction that is NOT inside a max() call.

    Descent stops at `max(...)`: everything under it is guarded by definition,
    which is what keeps `max(FLOOR, interval - elapsed)` from being flagged."""
    found = False

    def walk(node: ast.AST) -> None:
        nonlocal found
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "max":
            return                      # guarded subtree — do not descend
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            found = True
            return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)
    return found


def _is_sleep(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "sleep"
    if isinstance(func, ast.Attribute):
        return func.attr == "sleep"
    return False


def _scan(path: Path) -> list[tuple[int, str]]:
    try:
        src = path.read_text()
    except Exception:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    lines = src.splitlines()
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_sleep(node.func) and node.args):
            continue
        if not _unguarded_subtractions(node.args[0]):
            continue
        line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        if "cadence-ok" in line:
            continue
        hits.append((node.lineno, line.strip()))
    return hits


def case_no_unguarded_computed_sleeps() -> None:
    skip = ("__pycache__", "/tests/", "/node_modules/")
    offenders, scanned = [], 0
    for p in sorted(_SERVICE.rglob("*.py")):
        s = str(p)
        if any(k in s for k in skip) or p.name.startswith(("_drive_", "_verify_", "_send_", "_wipe_")):
            continue
        scanned += 1
        for lineno, text in _scan(p):
            offenders.append(f"{p.relative_to(_SERVICE)}:{lineno}  {text}")
    _expect(f"no unguarded computed sleeps ({scanned} modules scanned)",
            not offenders,
            detail="\n      " + "\n      ".join(offenders))


def case_guard_actually_detects_the_2026_08_21_bug() -> None:
    """The checker must fail on the real shape — otherwise case 1 passing
    proves only that the checker is blind."""
    bad = ast.parse("import asyncio\nasync def f():\n    await asyncio.sleep(INTERVAL - elapsed)\n")
    good = ast.parse("import asyncio\nasync def f():\n    await asyncio.sleep(max(FLOOR, INTERVAL - elapsed))\n")
    plain = ast.parse("import asyncio\nasync def f():\n    await asyncio.sleep(30)\n")

    def hits(tree):
        return any(_unguarded_subtractions(n.args[0])
                   for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and _is_sleep(n.func) and n.args)

    _expect("guard FLAGS sleep(interval - elapsed)", hits(bad))
    _expect("guard ALLOWS sleep(max(floor, interval - elapsed))", not hits(good))
    _expect("guard ALLOWS a plain constant sleep", not hits(plain))


# ── Half 2: cadence behaviour ───────────────────────────────────────────

def case_floor_holds_when_the_body_raises() -> None:
    """The exception path is the real spin risk: fail fast, retry instantly."""
    async def run():
        t0 = time.monotonic()
        try:
            async with cadence(interval_s=10, floor_s=0.25, name="t"):
                raise RuntimeError("cycle blew up immediately")
        except RuntimeError:
            pass
        return time.monotonic() - t0
    took = asyncio.run(run())
    _expect("floor still applied when the body raises", took >= 0.25, detail=f"took {took:.3f}s")


def case_cancellation_is_not_delayed() -> None:
    """Awaiting in `finally` during shutdown would hold the container open for
    a full interval and turn a clean stop into a SIGKILL."""
    async def run():
        async def loop():
            while True:
                async with cadence(interval_s=60, floor_s=60, name="t"):
                    pass
        task = asyncio.create_task(loop())
        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        return time.monotonic() - t0
    took = asyncio.run(run())
    _expect("cancellation is immediate, not held for the interval",
            took < 1.0, detail=f"took {took:.3f}s")


def case_zero_floor_is_rejected() -> None:
    async def run():
        try:
            async with cadence(interval_s=10, floor_s=0):
                pass
            return None
        except ValueError as e:
            return e
    err = asyncio.run(run())
    _expect("floor_s=0 is rejected (that IS the bug)", isinstance(err, ValueError))


for c in (case_no_unguarded_computed_sleeps,
          case_guard_actually_detects_the_2026_08_21_bug,
          case_floor_holds_when_the_body_raises,
          case_cancellation_is_not_delayed,
          case_zero_floor_is_rejected):
    c()

print()
if _failures:
    print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
    sys.exit(1)
print("all cases passed")
