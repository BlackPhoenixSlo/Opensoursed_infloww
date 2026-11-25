from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

PROC = Path("/proc")
TERM_GRACE_S = 30


def lstart(pid: int) -> str | None:
    ps = shutil.which("ps")
    if ps is None:
        return None
    try:
        r = subprocess.run([ps, "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                           env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


# survives exec (a venv python re-execs as `Python`); never raises
def start_time(pid: int) -> str | None:
    if PROC.is_dir():
        try:
            return "ticks " + (PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return None
    return lstart(pid)


def exists(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError):
        return False
    return True


# EPERM counts as alive on purpose: a probe must never declare a live run dead
def alive(pid: int, start: str | None = None) -> bool:
    if not exists(pid):
        return False
    if start is None:
        return True
    now = start_time(pid)
    return now is None or now == start


def group_alive(pgid: int) -> bool:
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
    if p is None or p.poll() is not None:
        return
    p.send_signal(signal.SIGINT)
    try:
        p.wait(60)
    except subprocess.TimeoutExpired:
        kill_tree(p)


# by ppid, not process group: gate.py run starts its workload in its own session, which must not outlive the wrapper
def kill_tree(p: subprocess.Popen) -> None:
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
