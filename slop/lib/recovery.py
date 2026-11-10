"""Crash recovery for lib/stack.py: what a run killed past its teardown (SIGKILL, a crash,
the gate's guard) leaves behind, put right by the next Stack.

- Process groups: each run records its owner and every group it spawns, as (pid, start
  time), in `slop/evidence/.stack-*.json` (RunState). A Stack sweeps them at start: an
  owner that is gone (or whose pid now belongs to a younger process) loses its groups, and
  a group is signalled only while its leader still has the recorded start time, so a
  reused pid is never hit.
- App files `next` rewrites: the app-lock holder keeps their originals in
  `app/.next/slop.state.json` (AppFiles). Its own exit puts them back; a holder that died
  first leaves the file, and the next holder restores a file only if it still holds what
  slop last saw there (else a user's edit or branch switch: WARN, leave it).

No start time readable (no `ps`, as in the relay image without /proc): None; the Stack
then WARNs once and records nothing, never fails.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from slop.lib.report import write_atomic

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "slop/evidence"
APP_FILES = ("tsconfig.json", "next-env.d.ts")
APP_LOCK, APP_STATE = "app/.next/slop.lock", "app/.next/slop.state.json"
PROC = Path("/proc")
_warned = False


def identity(pid: int) -> str | None:
    """`pid`'s start time: /proc/<pid>/stat field 22 (ticks since boot) on Linux, else `ps -o lstart`
    in the C locale (its text is locale-dependent). It survives exec (a venv python re-execs as
    `Python`), and pid + start time is one process. None when unreadable or gone; never raises."""
    if PROC.is_dir():
        try:
            return "ticks " + (PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            return None
    ps = shutil.which("ps")
    if ps is None:
        return None
    try:
        r = subprocess.run([ps, "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                           env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def write_json(path: Path, obj) -> None:
    write_atomic(path, json.dumps(obj))


def _read_json(path: Path) -> dict | None:
    try:
        state = json.loads(path.read_text())
        if not isinstance(state, dict):
            raise ValueError("not an object")
        return state
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        print(f"slop: WARN corrupt {path}: {e}; discarding it", file=sys.stderr)
        path.unlink(missing_ok=True)
        return None


def _gone(owner: dict) -> bool:
    """The recorded owner is dead: its pid is free, or reused by a process with another start time.
    Alive but unreadable (ps failed) counts as alive."""
    pid = owner.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass  # exists, another user's
    now = identity(pid)
    return now is not None and now != owner.get("start")


def _same_leader(group: dict) -> bool:
    pid = group.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        if os.getpgid(pid) != pid:
            return False
    except (ProcessLookupError, PermissionError):
        return False
    return identity(pid) == group.get("start")


def _kill_groups(groups: list[dict]) -> None:
    """SIGTERM each group whose leader is still the recorded process; SIGKILL what is left after 3 s."""
    live = []
    for g in groups:
        if _same_leader(g):
            try:
                os.killpg(g["pid"], signal.SIGTERM)
                live.append(g)
            except (ProcessLookupError, PermissionError):
                pass
    deadline = time.monotonic() + 3
    while live and time.monotonic() < deadline:
        time.sleep(0.05)
        live = [g for g in live if _same_leader(g)]
    for g in live:
        try:
            os.killpg(g["pid"], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def sweep(state_dir: Path | None = None) -> None:
    """Reap the groups of every run whose owner is gone, and drop its state file."""
    for path in sorted((state_dir or STATE_DIR).glob(".stack-*.json")):
        state = _read_json(path)
        if state is None or not _gone(state.get("owner") or {}):
            continue
        groups = state.get("groups") or []
        if groups:
            print(f"slop: reaping {len(groups)} process group(s) of a dead run ({path.name})", file=sys.stderr)
        _kill_groups(groups)
        path.unlink(missing_ok=True)


class RunState:
    """This run's owner and spawned groups, written on the first record()."""

    def __init__(self, state_dir: Path | None = None):
        self.dir, self.path, self.groups = state_dir or STATE_DIR, None, []
        self.owner: dict | None = None

    def record(self, pid: int) -> None:
        global _warned
        if self.owner is None:
            start = identity(os.getpid())
            if start is None:
                if not _warned:
                    print("slop: WARN cannot read process start times (no /proc, no ps): a run killed past its "
                          "teardown leaves its processes for you to stop", file=sys.stderr)
                    _warned = True
                return
            self.owner = {"pid": os.getpid(), "start": start}
            self.dir.mkdir(parents=True, exist_ok=True)
            self.path = self.dir / f".stack-{os.getpid()}-{time.time_ns()}.json"
        start = identity(pid)
        if start is not None:  # None: it already exited
            self.groups.append({"pid": pid, "start": start})
            write_json(self.path, {"owner": self.owner, "groups": self.groups})

    def close(self) -> None:
        if self.path is not None:
            self.path.unlink(missing_ok=True)
            self.path, self.owner, self.groups = None, None, []


def content_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class AppFiles:
    """The app files `next` rewrites (`names` under `app`), for the app-lock holder only."""

    def __init__(self, app: Path, names: tuple[str, ...], state: Path):
        self.app, self.names, self.state_path = app, names, state
        self.state: dict = {}

    def save(self) -> None:
        """Reap a dead holder's leftovers, then record this run's originals."""
        self._reap()
        self.state = {"originals": {f: base64.b64encode(p.read_bytes()).decode() if (p := self.app / f).exists()
                                    else None for f in self.names},
                      "written": {f: content_hash(self.app / f) for f in self.names}}
        write_json(self.state_path, self.state)

    def note_written(self) -> None:
        """What the files hold now (slop's or its `next`'s rewrite): what the crash reaper may undo."""
        now = {f: content_hash(self.app / f) for f in self.names}
        if self.state and now != self.state["written"]:
            self.state["written"] = now
            write_json(self.state_path, self.state)

    def restore(self) -> None:
        """In-process exit: put every original back, whatever the run's `next` did to it."""
        for name, encoded in self.state.get("originals", {}).items():
            _put(self.app / name, encoded)
        self.state_path.unlink(missing_ok=True)
        self.state = {}

    def _reap(self) -> None:
        old = _read_json(self.state_path)
        if old is None:
            return
        originals, written = _saved(old)
        for name, encoded in originals.items():
            if name not in self.names:
                continue
            path = self.app / name
            try:
                action = _reap_action(path, name, encoded, written)
            except ValueError:
                print(f"slop: WARN {self.state_path}: saved original of {name} is corrupt; keeping {path}",
                      file=sys.stderr)
                continue
            if action == "conflict":
                print(f"slop: WARN {path} changed since a killed slop run last saw it; keeping it", file=sys.stderr)
            elif action == "restore":
                _put(path, encoded)
        self.state_path.unlink(missing_ok=True)


def _reap_action(path: Path, name: str, encoded: str | None, written: dict) -> str:
    """What the next holder does to a dead holder's file: "keep" (it holds the original), "restore" (it still
    holds what slop last saw there) or "conflict" (changed since: a user's edit or branch switch, kept).
    `encoded` None = the original was absent; "" = it was empty. ValueError: corrupt (not base64 text)."""
    now = content_hash(path)
    orig = _original(encoded)
    orig = None if orig is None else hashlib.sha256(orig).hexdigest()
    if now == orig:
        return "keep"
    if name not in written or now != written[name]:
        return "conflict"
    return "restore"


def checkout_view(app: Path, names: tuple[str, ...], state_path: Path, live: bool) -> dict[str, bytes | None]:
    """`names` under `app` as the checkout holds them once slop is done with them (None = absent, b"" = empty):
    a live holder's saved originals (its exit restores them, whatever `next` wrote); a dead holder's originals
    where the next holder's _reap restores them; else disk. Read-only: never writes, warns or unlinks; a
    malformed state file or entry reads as no state for that file (disk). Unreadable disk raises OSError."""
    try:
        originals, written = _saved(json.loads(state_path.read_text()))
    except (OSError, ValueError):
        originals, written = {}, {}
    out: dict[str, bytes | None] = {}
    for name in names:
        path = app / name
        out[name] = path.read_bytes() if path.exists() else None
        if name not in originals:
            continue
        encoded = originals[name]
        try:
            if live or _reap_action(path, name, encoded, written) == "restore":
                out[name] = _original(encoded)
        except ValueError:
            pass  # corrupt: disk stands
    return out


def _saved(state) -> tuple[dict, dict]:
    """(originals, written) of a state file's JSON; a malformed part reads as empty."""
    if not isinstance(state, dict):
        return {}, {}
    originals, written = state.get("originals"), state.get("written")
    return (originals if isinstance(originals, dict) else {}), (written if isinstance(written, dict) else {})


def _original(encoded) -> bytes | None:
    """A saved original: None = it was absent, b"" = empty. ValueError if corrupt (lenient base64 would read
    junk as b"", an empty file)."""
    if encoded is None:
        return None
    if not isinstance(encoded, str):
        raise ValueError(f"not a string: {encoded!r}")
    return base64.b64decode(encoded, validate=True)


def _put(path: Path, encoded: str | None) -> None:
    b = _original(encoded)
    if b is None:
        path.unlink(missing_ok=True)
    elif not path.exists() or path.read_bytes() != b:  # unchanged: leave its mtime to watchers
        path.write_bytes(b)
