#!/usr/bin/env python3
"""Run service/tests/test_*.py scripts in parallel for scripts/run-tests.sh.

Each script runs in its own process (it already binds its own temp DB via
_harness), `-j` at a time. Output is buffered per script and printed in name
order, so the log reads like the serial loop. A script past `--timeout` gets
SIGABRT (PYTHONFAULTHANDLER=1 prints every thread's stack first), counts as
FAILED and is named in the summary; the run goes on. SERIAL scripts run one at
a time after the parallel batch.

Times are awake time (time.monotonic = mach_absolute_time on macOS, which stops
while the machine sleeps): a closed laptop lid froze scripts for ~900 s per
Maintenance Sleep (pmset log, 11-16) and read as a test stall. Sleep never
trips the timeout; the summary names how long the machine slept.

`--pytest` runs each test_*.py as `python -m pytest -q <file>` instead (pytest
suites like slop/lib, scripts/proxy-health: one file per process, same tests).
Discovery is the dir's own test_*.py (not recursive, no *_test.py: neither suite
has such files; pytest's default would also collect those). The summary counts
files (one process each), not test cases: each file's own pytest line has those.

Exit 0 only if every script passed.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Scripts that cannot share the machine with others, with the reason. Empty: every
# script binds its own temp DB / ephemeral port.
SERIAL: dict[str, str] = {}


_LIVE: set[subprocess.Popen] = set()


def _run(py: str, path: Path, timeout: float, pytest: bool = False) -> tuple[int, float, bytes, bool]:
    env = {**os.environ, "PYTHONFAULTHANDLER": "1", "PYTHONUNBUFFERED": "1"}
    t0 = time.monotonic()
    cmd = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(path)] if pytest else [py, str(path)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=env, start_new_session=True)
    _LIVE.add(p)
    out: list[bytes] = []
    reader = threading.Thread(target=lambda: out.append(p.stdout.read()), daemon=True)
    reader.start()
    timed_out = False
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        p.send_signal(signal.SIGABRT)          # faulthandler dumps all thread stacks
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(p.pid, signal.SIGKILL)   # children too (servers a script started)
        except ProcessLookupError:
            pass
        p.wait()
    reader.join(timeout=10)
    _LIVE.discard(p)
    return p.returncode, time.monotonic() - t0, b"".join(out), timed_out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tests_dir", type=Path)
    ap.add_argument("pattern", nargs="?", default="", help="substring or glob on the script name")
    ap.add_argument("-j", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--slowest", type=int, default=10)
    ap.add_argument("--times", type=Path, help="write `seconds<TAB>status<TAB>name` per script")
    ap.add_argument("--pytest", action="store_true", help="run each file under pytest")
    a = ap.parse_args()

    pat = a.pattern
    if pat and not any(c in pat for c in "*?["):
        pat = f"*{pat}*"
    scripts = sorted(p for p in a.tests_dir.glob("test_*.py") if not pat or fnmatch.fnmatch(p.name, pat))
    if not scripts:
        print(f"✗ no {a.tests_dir}/test_*.py matches {a.pattern!r}")
        return 1
    py = sys.executable
    par = [s for s in scripts if s.name not in SERIAL]
    ser = [s for s in scripts if s.name in SERIAL]
    print(f"{len(scripts)} scripts: {len(par)} at -j {a.j}, {len(ser)} serial, timeout {a.timeout:.0f} s")

    results: dict[Path, tuple[int, float, bytes, bool]] = {}
    done = threading.Condition()

    def job(s: Path) -> None:
        r = _run(py, s, a.timeout, a.pytest)
        with done:
            results[s] = r
            done.notify_all()

    t0, w0 = time.monotonic(), time.time()
    order = par + ser

    def printer() -> None:
        for s in order:
            with done:
                done.wait_for(lambda: s in results)
            rc, dt, out, to = results[s]
            sys.stdout.write(f"▶ {s.name}\n")
            sys.stdout.flush()
            sys.stdout.buffer.write(out)
            if to:
                sys.stdout.write(f"  ✗ TIMEOUT after {a.timeout:.0f} s\n")
            elif rc != 0:
                sys.stdout.write("  ✗ FAILED\n")
            sys.stdout.flush()

    pt = threading.Thread(target=printer, daemon=True)
    pt.start()
    ex = ThreadPoolExecutor(max_workers=a.j)
    try:
        list(ex.map(job, par))
        ex.shutdown()
        for s in ser:
            job(s)
    except KeyboardInterrupt:   # scripts run in their own sessions: Ctrl-C must kill them
        ex.shutdown(wait=False, cancel_futures=True)
        for p in list(_LIVE):
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        sys.stdout.write("\n✗ interrupted\n")
        sys.stdout.flush()
        os._exit(130)           # skip finalization: the printer thread may hold stdout
    pt.join()
    wall = time.monotonic() - t0
    slept = (time.time() - w0) - wall

    failed = [s.name for s in order if results[s][0] != 0 and not results[s][3]]
    timed = [s.name for s in order if results[s][3]]
    slow = sorted(order, key=lambda s: -results[s][1])[: a.slowest]
    print(f"──── {a.slowest} slowest ────")
    for s in slow:
        print(f"  {results[s][1]:7.1f} s  {s.name}")
    if a.times:
        a.times.write_text("".join(
            f"{results[s][1]:.1f}\t{'TIMEOUT' if results[s][3] else 'PASS' if results[s][0] == 0 else 'FAIL'}\t{s.name}\n"
            for s in order))
    print(f"{'pytest' if a.pytest else 'backend'}: {len(order) - len(failed) - len(timed)} files passed, {len(failed)} failed, "
          f"{len(timed)} timed out, wall {wall:.0f} s awake"
          + (f" (+{slept:.0f} s machine asleep)" if slept > 30 else ""))
    for n in failed:
        print(f"  ✗ FAILED   {n}")
    for n in timed:
        print(f"  ✗ TIMEOUT  {n}")
    return 0 if not failed and not timed else 1


if __name__ == "__main__":
    sys.exit(main())
