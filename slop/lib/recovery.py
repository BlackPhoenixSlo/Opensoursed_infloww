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
KILL_WAIT_S = 3


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
    pid = owner.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        return True
    return not procs.alive(pid, owner.get("start"))


def _ours(group: dict) -> bool:
    pgid = group.get("pid")
    if not isinstance(pgid, int) or pgid <= 1 or not procs.group_alive(pgid):
        return False
    if not procs.exists(pgid):
        return True
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
    live = [g for g in groups if _ours(g)]
    _signal(live, signal.SIGTERM)
    live = _wait(live)
    _signal(live, signal.SIGKILL)
    return _wait(live)


def sweep(state_dir: Path | None = None) -> None:
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
        if start is not None:
            self.groups.append({"pid": pid, "start": start})
            write_json(self.path, {"owner": self.owner, "groups": self.groups})

    def close(self, left: list[dict] = ()) -> None:
        if self.path is not None:
            if left:
                write_json(self.path, {"owner": self.owner, "groups": list(left)})
            else:
                self.path.unlink(missing_ok=True)
            self.path, self.owner, self.groups = None, None, []


def content_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class AppFiles:

    def __init__(self, app: Path, names: tuple[str, ...], state: Path):
        self.app, self.names, self.state_path = app, names, state
        self.state: dict = {}

    def save(self) -> None:
        self._reap()
        self.state = {"originals": {f: base64.b64encode(p.read_bytes()).decode() if (p := self.app / f).exists()
                                    else None for f in self.names},
                      "written": {f: content_hash(self.app / f) for f in self.names}}
        write_json(self.state_path, self.state)

    def note_written(self) -> None:
        now = {f: content_hash(self.app / f) for f in self.names}
        if self.state and now != self.state["written"]:
            self.state["written"] = now
            write_json(self.state_path, self.state)

    def restore(self) -> None:
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
    now = content_hash(path)
    orig = _original(encoded)
    orig = None if orig is None else hashlib.sha256(orig).hexdigest()
    if now == orig:
        return "keep"
    if name not in written or now != written[name]:
        return "conflict"
    return "restore"


def checkout_view(app: Path, names: tuple[str, ...], state_path: Path) -> dict[str, bytes | None]:
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
            pass
    return out


def _saved(state) -> tuple[dict, dict]:
    if not isinstance(state, dict):
        return {}, {}
    originals, written = state.get("originals"), state.get("written")
    return (originals if isinstance(originals, dict) else {}), (written if isinstance(written, dict) else {})


def _original(encoded) -> bytes | None:
    if encoded is None:
        return None
    if not isinstance(encoded, str):
        raise ValueError(f"not a string: {encoded!r}")
    return base64.b64decode(encoded, validate=True)


def _put(path: Path, encoded: str | None) -> None:
    b = _original(encoded)
    if b is None:
        path.unlink(missing_ok=True)
    # unchanged: leave its mtime to watchers
    elif not path.exists() or path.read_bytes() != b:
        path.write_bytes(b)
