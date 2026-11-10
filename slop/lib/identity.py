"""Run identity (CONTEXT.md): what makes two slop runs the same run beyond their knobs: the source a run
executes and the caller environment that reaches its stack. Recorded as run facts in every run folder
(`source_id` at start, `source_id_end` after teardown, `env_id`, `env_names`); a Break baseline is reused only
at an equal identity (lib/breakit.py). Stdlib only."""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from slop.lib import recovery
from slop.lib.recovery import APP_FILES, APP_LOCK, APP_STATE

# Files `next` rewrites in place while a stack runs (lib/stack.py RESTORE, APP_LOCK, APP_STATE): read as the
# checkout holds them once slop is done with them (lib/recovery.py checkout_view).
LOCK_SHA = ".slop-lock-sha"  # in app/node_modules: sha256 of the pnpm-lock.yaml it was installed from (nightly)

# Caller env that never changes how a run executes: shell/session noise, the gate's own bookkeeping
# (GATE_ENV, set by ~/.slop/gate.py; lib/nightly.py strips it for its children) and admission-only waits.
# Everything else is identity, guard limits, SLOP_GATE, SLOP_GATE_EXCLUSIVE and PATH included.
GATE_ENV = ("SLOP_GATED", "SLOP_GATE_PID", "SLOP_GATE_WAIT_S", "SLOP_GATE_LOAD")
VOLATILE = frozenset((
    "AI_AGENT", "SHLVL", "PWD", "OLDPWD", "_", "SSH_AUTH_SOCK", "COLUMNS", "LINES", "GIT_EDITOR", "MallocNanoZone",
    *GATE_ENV,
    "SLOP_LOCK_WAIT_S", "SLOP_WIRE_LOCK_WAIT_S", "SLOP_LOAD_TIMEOUT", "SLOP_START_STAGGER_S", "SLOP_MAX_RUNS",
    "SLOP_MAX_LOAD", "SLOP_MAX_THREADS_MACHINE", "SLOP_MAX_SOCKETS", "SLOP_SHARE_WAIT_S"))
VOLATILE_PREFIXES = ("CLAUDE", "T3CODE", "XPC_", "__CF", "TERM")


def _git(root: Path, *a: str) -> bytes:
    return subprocess.run(["git", *a], cwd=root, capture_output=True, check=True, timeout=60).stdout


def _live_holder(root: Path) -> bool:
    """A live process holds the app lock (its pid, as lib/stack.py writes it, still runs). Read, never locked:
    taking the lock even briefly could refuse a stack starting at that moment."""
    try:
        pid = int((root / APP_LOCK).read_text().split()[1])
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ValueError, IndexError, OverflowError):
        return False
    return True


def _file(p: Path) -> bytes:
    if p.is_symlink():
        return b"link:" + os.readlink(p).encode()
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest().encode()
    return b"dir" if p.is_dir() else b"missing"


def source_id(root: Path) -> str:
    """sha256 of the source a run executes: HEAD, the tracked diff, every untracked non-ignored file, and the
    ignored stack inputs (app/.env* contents, the app dependency lock stamp, the venv's resolved python)."""
    root = Path(root)
    skip = [f":(exclude)app/{name}" for name in APP_FILES]  # hashed as the checkout holds them (checkout_view)
    h = hashlib.sha256()
    h.update(b"head\0" + _git(root, "rev-parse", "HEAD").strip())
    h.update(b"\0diff\0" + _git(root, "diff", "HEAD", "--binary", "--no-ext-diff", "--", ".", *skip))
    untracked = _git(root, "ls-files", "-o", "--exclude-standard", "-z", "--", ".", *skip).split(b"\0")
    for rel in sorted(filter(None, untracked)):
        h.update(b"\0untracked\0" + rel + b"\0" + _file(root / os.fsdecode(rel)))
    view = recovery.checkout_view(root / "app", APP_FILES, root / APP_STATE, _live_holder(root))
    for name, data in view.items():
        h.update(b"\0app\0" + name.encode() + b"\0" + (b"missing" if data is None else hashlib.sha256(data).digest()))
    for p in sorted((root / "app").glob(".env*")):
        h.update(b"\0env-file\0" + p.name.encode() + b"\0" + _file(p))
    h.update(b"\0lock-sha\0" + _file(root / "app/node_modules" / LOCK_SHA))
    h.update(b"\0python\0" + os.path.realpath(root / "venv/bin/python").encode())
    return h.hexdigest()


def env_id(env) -> tuple[str, list[str]]:
    """(sha256, names) over every caller env var not VOLATILE. Only the hash and the names are kept: a value
    never leaves this function (each is hashed before it joins the digest)."""
    names = sorted(k for k in env if k not in VOLATILE and not k.startswith(VOLATILE_PREFIXES))
    h = hashlib.sha256()
    for k in names:
        h.update(k.encode() + b"=" + hashlib.sha256(env[k].encode(errors="surrogateescape")).digest() + b"\0")
    return h.hexdigest(), names


def baseline_problem(base: dict, cur: dict) -> str | None:
    """Why a saved baseline's params `base` are not this run's identity `cur` ({source_id, env_id, env_names}),
    or None. One line; names the part that differs, never an env value."""
    if "source_id" not in base:
        return "recorded before Run identity (no source_id): re-run without --baseline"
    if not base["source_id"] or not base.get("source_id_end"):
        return ("its source could not be read at its start or end (WARN source_id unreadable in its log): "
                "re-run without --baseline")
    if not cur["source_id"]:
        return "this checkout's source could not be read now (WARN source_id unreadable above)"
    if base["source_id"] != base["source_id_end"]:
        return ("raced: its source changed during the run (source_id != source_id_end); "
                "re-run with nobody editing the checkout")
    if base["source_id"] != cur["source_id"]:
        return "source differs (HEAD, a tracked or untracked file, or a stack input changed since it ran)"
    have, want = set(base.get("env_names") or ()), set(cur["env_names"])
    if have != want:
        return f"env vars differ: added {sorted(want - have)}, removed {sorted(have - want)}"
    if base.get("env_id") != cur["env_id"]:
        return "env value changed (values are not stored)"
    return None


def raced(runs: list[dict]) -> str | None:
    """Why a Break verdict's runs (baseline first) did not all run one source, start and end, or None."""
    ids = [x for p in runs for x in (p.get("source_id"), p.get("source_id_end"))]
    if not all(ids):
        return ("source unreadable at the start or end of the baseline or the fault run (WARN source_id "
                "unreadable): fix what it names, then re-run")
    if len(set(ids)) == 1:
        return None
    return ("raced: source changed between or during the baseline and the fault run (start/end "
            + " -> ".join(x[:12] for x in ids) + "); re-run with nobody editing the checkout")
