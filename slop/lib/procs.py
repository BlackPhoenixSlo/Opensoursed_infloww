"""Process liveness for the harness, one place (lib/recovery.py, lib/nightly.py, lib/share.py).

A pid alone is not a process: pids are reused (after a reboot within minutes). `start_time(pid)` + pid is one
process; `alive(pid, start)` holds both. A process group outlives its leader: `group_alive(pgid)` asks the
kernel whether any member is left (a pgid is not handed out again while its group has a member).
EPERM (another user's process) counts as alive here, on purpose: a harness probe must never declare a live
run dead (a stale record is only kept a while longer). ~/.slop/procinfo.py agrees for a pid (`alive`: EPERM
alive) but decides the other way for a process GROUP (`groups_alive`: EPERM = only others' processes, not the
run's), on purpose too: a slot must never stay held by a foreign group.
Stdlib only: lib/share.py runs it under the system python3, before the gate.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

PROC = Path("/proc")
TERM_GRACE_S = 30  # kill_tree: a tree's SIGTERM -> SIGKILL


def lstart(pid: int) -> str | None:
    """`ps -o lstart= -p <pid>` in the C locale (its text is locale-dependent); None if gone or no ps."""
    ps = shutil.which("ps")
    if ps is None:
        return None
    try:
        r = subprocess.run([ps, "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                           env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def start_time(pid: int) -> str | None:
    """`pid`'s start time: /proc/<pid>/stat field 22 (ticks since boot) on Linux, else lstart(). It survives
    exec (a venv python re-execs as `Python`), and pid + start time is one process. None when unreadable or
    gone; never raises."""
    if PROC.is_dir():
        try:
            return "ticks " + (PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return None
    return lstart(pid)


def exists(pid: int) -> bool:
    """Some process holds `pid` (another user's counts)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError):
        return False
    return True


def alive(pid: int, start: str | None = None) -> bool:
    """`pid` runs and, given its recorded `start`, is still that process (an unreadable start time counts as
    alive: never declare a live process dead on a failed `ps`)."""
    if not exists(pid):
        return False
    if start is None:
        return True
    now = start_time(pid)
    return now is None or now == start


def group_alive(pgid: int) -> bool:
    """Process group `pgid` has a member left (its leader may be gone)."""
    if not isinstance(pgid, int) or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError):
        return False
    return True


def tree_order(root: int, kids: dict[int, list[int]]) -> list[int]:
    """`root` and its descendants in `kids` (ppid -> pids), children before parents, each pid once."""
    out: list[int] = []
    seen: set[int] = set()

    def walk(pid: int) -> None:
        if pid in seen:
            return
        seen.add(pid)
        for k in kids.get(pid, []):
            walk(k)
        out.append(pid)
    walk(root)
    return out


def stop_child(p: subprocess.Popen | None) -> None:
    """SIGINT a running `slop/run` (gate.py run forwards it; KeyboardInterrupt: its stack tears down),
    past 60 s its whole tree (kill_tree). lib/nightly.py's children and lib/share.py's leader."""
    if p is None or p.poll() is not None:
        return
    p.send_signal(signal.SIGINT)
    try:
        p.wait(60)
    except subprocess.TimeoutExpired:
        kill_tree(p)


def kill_tree(p: subprocess.Popen) -> None:
    """SIGTERM then (TERM_GRACE_S on) SIGKILL `p` and every descendant, children first, then reap `p`.
    By ppid, not process group: gate.py run starts its workload in a session of its own, which must not
    outlive the wrapper (slot released, workload ungated, its stdout holding a pipe open)."""
    def snapshot() -> dict[int, list[int]]:
        kids: dict[int, list[int]] = {}
        for ln in subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout.splitlines():
            pid, ppid = map(int, ln.split())
            kids.setdefault(ppid, []).append(pid)
        return kids
    pids = tree_order(p.pid, snapshot())
    for sig, grace in ((signal.SIGTERM, TERM_GRACE_S), (signal.SIGKILL, 5)):
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, sig)
        end = time.time() + grace
        while time.time() < end and (p.poll() is None or any(exists(x) for x in pids if x != p.pid)):
            time.sleep(0.2)
        if p.poll() is not None and not any(exists(x) for x in pids if x != p.pid):
            break
    with contextlib.suppress(subprocess.TimeoutExpired):
        p.wait(5)
