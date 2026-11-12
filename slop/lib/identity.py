"""Run identity (CONTEXT.md): what makes two slop runs the same run beyond their knobs: the source a run
executes and the caller environment that reaches its stack. Recorded as run facts in every run folder
(`source_id` at start, `source_id_end` after teardown, `env_id`, `env_names`); a Break baseline is reused only
at an equal identity (lib/breakit.py). Stdlib only."""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from slop.lib import recovery
# APP_FILES: files `next` rewrites in place while a stack runs (lib/stack.py RESTORE, APP_STATE): read as the
# checkout holds them once slop is done with them (lib/recovery.py checkout_view; no app-lock pid is trusted).
from slop.lib.recovery import APP_FILES, APP_STATE

LOCK_SHA = ".slop-lock-sha"  # in app/node_modules: sha256 of the pnpm-lock.yaml it was installed from (nightly)
DEPS_META = (".package-lock.json", ".modules.yaml", ".pnpm/lock.yaml")  # per node_modules: what got installed
MANIFEST_CAP = 5000  # entries a symlinked directory input may hold to count by content (_manifest); more: no id

# Caller env that never changes how a run executes: shell/session noise, the gate's own bookkeeping
# (GATE_ENV, set by ~/.slop/gate.py; lib/nightly.py strips every SLOP_GATE* for its children) and admission-only knobs
# (waits, machine limits, SLOP_NIGHTLY: lib/nightly.py sets it for its children, the gate reads it for its
# reserved slot; an honour-system flag, it changes admission, never the run). Everything else is identity,
# guard limits, SLOP_GATE, SLOP_GATE_EXCLUSIVE and PATH included.
GATE_ENV = ("SLOP_GATED", "SLOP_GATE_PID", "SLOP_GATE_WAIT_S", "SLOP_GATE_LOAD")
VOLATILE = frozenset((
    "AI_AGENT", "SHLVL", "PWD", "OLDPWD", "_", "SSH_AUTH_SOCK", "COLUMNS", "LINES", "GIT_EDITOR", "MallocNanoZone",
    *GATE_ENV,
    "SLOP_LOCK_WAIT_S", "SLOP_WIRE_LOCK_WAIT_S", "SLOP_LOAD_TIMEOUT", "SLOP_START_STAGGER_S", "SLOP_MAX_RUNS",
    "SLOP_MAX_LOAD", "SLOP_MAX_THREADS_MACHINE", "SLOP_MAX_SOCKETS", "SLOP_SHARE_WAIT_S", "SLOP_NIGHTLY"))
VOLATILE_PREFIXES = ("CLAUDE", "T3CODE", "XPC_", "__CF", "TERM")


def _git(root: Path, *a: str) -> bytes:
    return subprocess.run(["git", *a], cwd=root, capture_output=True, check=True, timeout=60).stdout


def _file(p: Path) -> bytes:
    """A file input's content hash. A symlink is hashed by what it resolves to (its target's content, a
    directory by a manifest of every path and content under it: _manifest); a dangling or unreadable target,
    a directory over MANIFEST_CAP entries or a link cycle or loop raises OSError, so the checkout has no
    source_id and no baseline or shared run is reused (lib/cli.py _source_id, lib/share.py)."""
    return _entry(p, _Walk())


@dataclass
class _Walk:
    """One _file call's walk over symlinked directories: entries left (MANIFEST_CAP in all), directories open."""
    left: int = field(default_factory=lambda: MANIFEST_CAP)
    open: set = field(default_factory=set)


def _entry(p: Path, walk: _Walk) -> bytes:
    if p.is_symlink():
        try:
            target = p.resolve()
        except RuntimeError as e:  # Python < 3.13: a link loop (a -> b -> a)
            raise OSError(f"symlink {p}: {e}") from e
        if target.is_dir():
            return b"link-dir:" + _manifest(target, walk)
        if not target.is_file():
            raise OSError(f"symlink {p} -> {os.readlink(p)}: target missing or not a file")
        return b"link:" + hashlib.sha256(target.read_bytes()).hexdigest().encode()
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest().encode()
    return b"dir" if p.is_dir() else b"missing"


def _manifest(d: Path, walk: _Walk) -> bytes:
    """sha256 over every entry under directory `d` (relative path + _entry content; symlinks inside followed the
    same way). Past MANIFEST_CAP entries in all, a link back into a directory being walked, or an unreadable
    directory: OSError (fails closed: no reuse)."""
    if d in walk.open:
        raise OSError(f"symlinked directory {d}: link cycle; not hashed")
    walk.open.add(d)
    h = hashlib.sha256()

    def fail(e: OSError):
        raise e
    for top, dirs, files in os.walk(d, onerror=fail):
        dirs.sort()
        for name in sorted(dirs + files):
            p = Path(top) / name
            walk.left -= 1
            if walk.left < 0:
                raise OSError(f"symlinked directory over {MANIFEST_CAP} entries ({d}): not hashed")
            rel = os.fsencode(p.relative_to(d))
            h.update(rel + b"\0" + (b"dir" if p.is_dir() and not p.is_symlink() else _entry(p, walk)) + b"\n")
    walk.open.discard(d)
    return h.hexdigest().encode()


def deps_id(root: Path) -> bytes:
    """The installed dependencies, cheaply (no tree walk): the venv's site-packages distributions (dist-info /
    egg-info names carry name and version) and, for app/ and web/, the package manager's install metadata
    (npm's node_modules/.package-lock.json, pnpm's .modules.yaml and .pnpm/lock.yaml; whichever exist).
    Not file content (accepted limitation, orch R5-11): a package edited in place under site-packages or
    node_modules, without its install metadata changing, leaves this equal. pip/npm/pnpm installs change the
    metadata; hashing every installed file per run costs too much."""
    h = hashlib.sha256()
    for sp in sorted((root / "venv/lib").glob("python*/site-packages")):
        dists = sorted(d.name for d in sp.iterdir() if d.name.endswith((".dist-info", ".egg-info")))
        h.update(b"\0site\0" + sp.parent.name.encode() + b"\0" + "\n".join(dists).encode())
    for tree in ("app", "web"):
        for meta in DEPS_META:
            h.update(b"\0" + f"{tree}/node_modules/{meta}".encode() + b"\0" + _file(root / tree / "node_modules" / meta))
    return h.hexdigest().encode()


def source_id(root: Path) -> str:
    """sha256 of the source a run executes: HEAD, the tracked diff, every untracked non-ignored file, and the
    ignored stack inputs (app/.env* contents, the app dependency lock stamp, the venv's resolved python, the
    installed dependencies: deps_id). A symlinked input counts by its target's content (_file)."""
    root = Path(root)
    skip = [f":(exclude)app/{name}" for name in APP_FILES]  # hashed as the checkout holds them (checkout_view)
    h = hashlib.sha256()
    h.update(b"head\0" + _git(root, "rev-parse", "HEAD").strip())
    h.update(b"\0diff\0" + _git(root, "diff", "HEAD", "--binary", "--no-ext-diff", "--", ".", *skip))
    untracked = _git(root, "ls-files", "-o", "--exclude-standard", "-z", "--", ".", *skip).split(b"\0")
    for rel in sorted(filter(None, untracked)):
        h.update(b"\0untracked\0" + rel + b"\0" + _file(root / os.fsdecode(rel)))
    view = recovery.checkout_view(root / "app", APP_FILES, root / APP_STATE)
    for name, data in view.items():
        h.update(b"\0app\0" + name.encode() + b"\0" + (b"missing" if data is None else hashlib.sha256(data).digest()))
    for p in sorted((root / "app").glob(".env*")):
        h.update(b"\0env-file\0" + p.name.encode() + b"\0" + _file(p))
    h.update(b"\0lock-sha\0" + _file(root / "app/node_modules" / LOCK_SHA))
    h.update(b"\0python\0" + os.path.realpath(root / "venv/bin/python").encode())
    h.update(b"\0deps\0" + deps_id(root))
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
