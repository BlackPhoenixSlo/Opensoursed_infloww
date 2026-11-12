"""Crash recovery for lib/stack.py: what a run killed past its teardown (SIGKILL, a crash,
the gate's guard) leaves behind, put right by the next Stack.

- Process groups: each run records its owner and every group it spawns, as (pid, start
  time), in `slop/evidence/.stack-*.json` (RunState). A Stack sweeps them at start: an
  owner that is gone (or whose pid now belongs to a younger process) loses its groups. A
  group is the run's while its leader still has the recorded start time, or, the leader
  gone, while the group still has members and no other process holds the leader's pid (a
  pgid is not reused while its group lives), so a reused pid is never hit and members that
  outlive their leader are still reaped. The state file stays until every group is empty.
- App files `next` rewrites: the app-lock holder keeps their originals in
  `app/.next/slop.state.json` (AppFiles). Its own exit puts them back; a holder that died
  first leaves the file for the next holder. Either way a file is restored only if it still
  holds what slop last saw there (else a user's edit or branch switch: WARN, leave it).

No start time readable (no `ps`, as in the relay image without /proc): None; the Stack
then WARNs once and records nothing, never fails.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

from slop.lib import procs
from slop.lib.report import write_atomic

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "slop/evidence"
APP_FILES = ("tsconfig.json", "next-env.d.ts")
APP_LOCK, APP_STATE = "app/.next/slop.lock", "app/.next/slop.state.json"
_warned = False
KILL_WAIT_S = 3  # a group's SIGTERM -> SIGKILL, then as long again for it to empty


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
    return not procs.alive(pid, owner.get("start"))


def _ours(group: dict) -> bool:
    """The recorded group still has members of the run: its leader is the recorded process, or the leader is
    gone, no process holds its pid and the group is not empty (a pgid is not handed out while its group lives)."""
    pgid = group.get("pid")
    if not isinstance(pgid, int) or pgid <= 1 or not procs.group_alive(pgid):
        return False
    if not procs.exists(pgid):
        return True  # leader gone, members left
    try:
        if os.getpgid(pgid) != pgid:
            return False
    except (ProcessLookupError, PermissionError):
        return False
    return procs.start_time(pgid) == group.get("start")


def _signal(groups: list[dict], sig: int) -> None:
    for g in groups:
        try:
            os.killpg(g["pid"], sig)
        except (ProcessLookupError, PermissionError):
            pass


def _wait(groups: list[dict]) -> list[dict]:
    deadline = time.monotonic() + KILL_WAIT_S
    while groups and time.monotonic() < deadline:
        time.sleep(0.05)
        groups = [g for g in groups if _ours(g)]
    return groups


def kill_groups(groups: list[dict]) -> list[dict]:
    """SIGTERM each group still the run's; SIGKILL whatever member is left after KILL_WAIT_S. -> the groups
    that still have members after that (their record is kept for the next sweep)."""
    live = [g for g in groups if _ours(g)]
    _signal(live, signal.SIGTERM)
    live = _wait(live)
    _signal(live, signal.SIGKILL)
    return _wait(live)


def sweep(state_dir: Path | None = None) -> None:
    """Reap the groups of every run whose owner is gone; drop its state file once every group is empty."""
    for path in sorted((state_dir or STATE_DIR).glob(".stack-*.json")):
        state = _read_json(path)
        if state is None or not _gone(state.get("owner") or {}):
            continue
        groups = state.get("groups") or []
        if groups:
            print(f"slop: reaping {len(groups)} process group(s) of a dead run ({path.name})", file=sys.stderr)
        left = kill_groups(groups)
        if left:
            print(f"slop: WARN {len(left)} process group(s) of a dead run survived SIGKILL "
                  f"({', '.join(str(g['pid']) for g in left)}); kept in {path.name} for the next sweep", file=sys.stderr)
            write_json(path, {**state, "groups": left})
        else:
            path.unlink(missing_ok=True)


class RunState:
    """This run's owner and spawned groups, written on the first record()."""

    def __init__(self, state_dir: Path | None = None):
        self.dir, self.path, self.groups = state_dir or STATE_DIR, None, []
        self.owner: dict | None = None

    def record(self, pid: int) -> None:
        global _warned
        if self.owner is None:
            start = procs.start_time(os.getpid())
            if start is None:
                if not _warned:
                    print("slop: WARN cannot read process start times (no /proc, no ps): a run killed past its "
                          "teardown leaves its processes for you to stop", file=sys.stderr)
                    _warned = True
                return
            self.owner = {"pid": os.getpid(), "start": start}
            self.dir.mkdir(parents=True, exist_ok=True)
            self.path = self.dir / f".stack-{os.getpid()}-{time.time_ns()}.json"
        start = procs.start_time(pid)
        if start is not None:  # None: it already exited
            self.groups.append({"pid": pid, "start": start})
            write_json(self.path, {"owner": self.owner, "groups": self.groups})

    def close(self, left: list[dict] = ()) -> None:
        """The run is done: drop its record, or keep it naming only `left`, the groups that still have members
        (kill_groups' result): this owner exits soon and the next sweep reaps them."""
        if self.path is not None:
            if left:
                write_json(self.path, {"owner": self.owner, "groups": list(left)})
            else:
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
        """In-process exit: put back each original whose file still holds what slop last saw (note_written);
        a file changed since (a user's edit during the run) is kept, one WARN line. Nothing saved yet (a start
        cut before save() finished): a no-op, so a killed holder's state file stays for the next holder."""
        if not self.state:
            return
        self._put_back(self.state, "during this slop run")
        self.state = {}

    def _reap(self) -> None:
        old = _read_json(self.state_path)
        if old is not None:
            self._put_back(old, "since a killed slop run last saw it")

    def _put_back(self, state: dict, when: str) -> None:
        originals, written = _saved(state)
        kept = []
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
                kept.append(str(path))
            elif action == "restore":
                _put(path, encoded)
        if kept:
            print(f"slop: WARN {', '.join(kept)} changed {when} (not slop's rewrite); keeping it", file=sys.stderr)
        self.state_path.unlink(missing_ok=True)


def _reap_action(path: Path, name: str, encoded: str | None, written: dict) -> str:
    """What a holder's exit, or the next holder for a dead one, does to a file: "keep" (it holds the original),
    "restore" (it still holds what slop last saw there) or "conflict" (changed since: a user's edit or branch
    switch, kept).
    `encoded` None = the original was absent; "" = it was empty. ValueError: corrupt (not base64 text)."""
    now = content_hash(path)
    orig = _original(encoded)
    orig = None if orig is None else hashlib.sha256(orig).hexdigest()
    if now == orig:
        return "keep"
    if name not in written or now != written[name]:
        return "conflict"
    return "restore"


def checkout_view(app: Path, names: tuple[str, ...], state_path: Path) -> dict[str, bytes | None]:
    """`names` under `app` as the checkout holds them once slop is done with them (None = absent, b"" = empty):
    the saved originals where the holder's exit (live) or the next holder's _reap (dead) restores them, one
    rule for both (_reap_action), so no holder pid is trusted; else disk. Read-only: never writes, warns or
    unlinks; a malformed state file or entry reads as no state for that file (disk). Unreadable disk raises
    OSError."""
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
            if _reap_action(path, name, encoded, written) == "restore":
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
