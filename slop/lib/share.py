"""`slop/run <args> --share`: a Shared run (CONTEXT.md). An exact concurrent request (the same argument vector in
the same order, checkout, working directory, source and caller env: the Run identity, lib/identity.py) waits
outside the machine gate for the live run and prints its output, prefixed by one `slop: shared run of pid N
(started T)` line, and exits with its exit code. Never an earlier finished run. Opt-in only: no env var turns it
on, nightly never passes it, refused with --map and nightly. Per checkout (files in its gitignored
slop/evidence/.share/, all kept: a run's log is small; delete them by hand only while no `--share` run is live):

  <key>.lock                  flock only, never unlinked: the leader holds LOCK_EX for its whole run
  <key>.json                  the live generation {nonce, pid, pid_start, argv, cwd, checkout, source_id, env_id,
                              started}; the leader is live while pid runs with start time pid_start (lib/procs.py)
  <key>.<nonce>.log           the leader's tee'd output; never rewritten once its result exists
  <key>.<nonce>.result.json   {nonce, exit, source_id_end, finished}; never written for a cancelled leader

A follower ends INFRA exit 3, with the leader's log, when the leader was cancelled or died without a result,
its source changed during the run (no re-key, no re-election, no automatic re-run: re-run), the leader did not
publish within PUBLISH_WAIT_S, or SLOP_SHARE_WAIT_S ran out; its own cancellation stops only itself (exit 3).
Stdlib only (`slop/run` starts it with python3, before the gate). Tests: lib/test_share.py."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # run as a script by slop/run

from slop.lib import identity, procs  # noqa: E402
from slop.lib.report import EVIDENCE, write_atomic  # noqa: E402

FLAG = "--share"
WAIT_S = 7200  # SLOP_SHARE_WAIT_S default: gate slot wait 3600 + scenario timeout 1800 + admission margin
PUBLISH_WAIT_S, STEP_S = 10, 0.2  # a leader holding the lock may not have written <key>.json yet
START_CHECK_S = 5  # a follower checks its leader's start time (pid reuse) this often; its pid every STEP_S
INFRA = 3
SIGS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
_held: list[int] | None = None  # set by _deferred(): signals are recorded, raised when it ends


class Stopped(Exception):
    """SIGINT/SIGTERM/SIGHUP to this process (later ones are ignored while it cleans up)."""


def key(argv: list[str], checkout: Path, cwd: str, source_id: str, env_id: str) -> str:
    return hashlib.sha256(json.dumps([argv, os.path.realpath(checkout), cwd, source_id, env_id]).encode()).hexdigest()


def main(argv: list[str], *, run: list[str] | None = None, root: Path | str = ROOT,
         share_dir: Path | str | None = None) -> int:
    args = [a for a in argv if a != FLAG]
    if args[:1] == ["nightly"] or "--map" in args:
        print("slop: --share is refused with --map and nightly (map writes and the sweep always run fresh)",
              file=sys.stderr)
        return 2
    root = Path(root)
    run = run or [str(ROOT / "slop" / "run")]
    try:
        src = identity.source_id(root)
    except Exception as e:  # no identity, no sharing: a Fresh run is always correct
        print(f"slop: WARN --share: source_id unreadable ({type(e).__name__}: {e}); running fresh", flush=True)
        os.execvp(run[0], [*run, *args])
    env = identity.env_id(os.environ)[0]
    cwd = os.path.realpath(os.getcwd())
    k = key(args, root, cwd, src, env)
    d = Path(share_dir) if share_dir else EVIDENCE / ".share"
    d.mkdir(parents=True, exist_ok=True)
    wait_s = float(os.environ.get("SLOP_SHARE_WAIT_S") or WAIT_S)
    fd = os.open(d / f"{k}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    with _stop_signals():
        try:
            end = time.monotonic() + PUBLISH_WAIT_S
            while True:
                if _trylock(fd, fcntl.LOCK_EX):
                    meta = {"nonce": secrets.token_hex(8), "pid": os.getpid(),
                            "pid_start": procs.start_time(os.getpid()), "argv": args, "cwd": cwd,
                            "checkout": str(root), "source_id": src, "env_id": env,
                            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
                    return _lead(d, k, meta, run, root)
                meta = _read(d / f"{k}.json")
                if meta and not (d / f"{k}.{meta['nonce']}.result.json").exists() and _leader_alive(meta):
                    return _follow(fd, d, k, meta, wait_s)
                if time.monotonic() >= end:  # a finished, dead or missing generation and the lock still held
                    print(f"slop: INFRA shared run did not publish within {PUBLISH_WAIT_S}s "
                          f"(lock held, no live generation in {d / k}.json); re-run", flush=True)
                    return INFRA
                time.sleep(STEP_S)
        except Stopped as e:  # a follower, or a request that has not published: a leader handles its own
            print(f"slop: INFRA shared run: stopped ({e}) before running a child; a live leader keeps running",
                  flush=True)
            return INFRA
        finally:
            os.close(fd)  # the lock goes with it


def _lead(d: Path, k: str, meta: dict, run: list[str], root: Path) -> int:
    """Publish this generation, run the child (it queues for the gate itself), tee its output, then the result.
    Cancelled anywhere from publication until the result write starts: stop the child as nightly does, no result."""
    nonce, p, out = meta["nonce"], None, sys.stdout.buffer
    with open(d / f"{k}.{nonce}.log", "wb") as log:
        try:
            write_atomic(d / f"{k}.json", json.dumps(meta) + "\n")
            with _deferred():  # a signal inside Popen must not leave its child unsupervised
                p = subprocess.Popen([*run, *meta["argv"]], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            _tee(p.stdout, out, log)
            code = _shell_code(p.wait())
            with _deferred(raising=False):  # finished: publish; a signal now is dropped, the result stands
                try:
                    end = identity.source_id(root)
                except Exception:
                    end = None
                write_atomic(d / f"{k}.{nonce}.result.json", json.dumps(
                    {"nonce": nonce, "exit": code, "source_id_end": end,
                     "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
            return code
        except Stopped as e:
            procs.stop_child(p)  # SIGINT, its whole tree after 60 s; nothing if no child yet
            if p is not None:
                _tee(p.stdout, out, log)
            _tee([f"slop: INFRA shared run: leader cancelled ({e}); no result published\n".encode()], out, log)
            if p is not None:
                p.wait()
            return INFRA  # cancelled: never the child's code (a child stopped by SIGINT may exit 0)
        finally:
            if p is not None and p.poll() is None:  # crashed in here: never leave a stack behind ungated
                procs.kill_tree(p)


def _follow(fd: int, d: Path, k: str, meta: dict, wait_s: float) -> int:
    """Wait (no gate slot, no stack) for this nonce's result, or for its leader to be gone; replay its files.
    Polled, never a blocking lock: a later generation may hold the lock long after this one's result exists."""
    pid, nonce = meta["pid"], meta["nonce"]
    res_path = d / f"{k}.{nonce}.result.json"
    print(f"slop: shared run of pid {pid} (started {meta.get('started')})", flush=True)
    end, timed_out, checked = time.monotonic() + wait_s, False, -START_CHECK_S

    def leader_alive() -> bool:  # pid per poll; its start time (a `ps` off Linux) at most every START_CHECK_S
        nonlocal checked
        if not procs.exists(pid):
            return False
        if time.monotonic() - checked < START_CHECK_S:
            return True
        checked = time.monotonic()
        return _leader_alive(meta)
    while not (res_path.exists() or not leader_alive() or _trylock(fd, fcntl.LOCK_SH)):
        if time.monotonic() >= end:
            timed_out = True
            break
        time.sleep(STEP_S)
    fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(FileNotFoundError):
        sys.stdout.buffer.write((d / f"{k}.{nonce}.log").read_bytes())
        sys.stdout.buffer.flush()
    res = None if timed_out else _read(res_path)
    why = (f"waited SLOP_SHARE_WAIT_S={wait_s:g}s; the leader keeps running" if timed_out
           else "leader cancelled/died without a result" if res is None
           else "source changed during the run; re-run" if res.get("source_id_end") != meta.get("source_id")
           else None)
    if why:
        print(f"slop: INFRA shared run of pid {pid}: {why}", flush=True)
        return INFRA
    return res["exit"]


def _leader_alive(meta: dict) -> bool:
    """The generation's leader still runs: its pid, with its recorded start time (a reused pid is not it)."""
    pid = meta.get("pid")
    return isinstance(pid, int) and procs.alive(pid, meta.get("pid_start"))


def _trylock(fd: int, kind: int) -> bool:
    try:
        fcntl.flock(fd, kind | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _shell_code(code: int) -> int:
    return 128 - code if code < 0 else code  # a signal exit as a shell reports it


def _tee(src, out, log) -> None:
    lines = iter(src.readline, b"") if hasattr(src, "readline") else src
    for line in lines:
        log.write(line)
        log.flush()
        with contextlib.suppress(BrokenPipeError):  # our caller gone: the run still finishes for followers
            out.write(line)
            out.flush()


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _deferred(raising: bool = True):
    """Record stop signals instead of raising them; raise Stopped for the first one when the block ends."""
    global _held
    _held = []
    try:
        yield
    finally:
        got, _held = _held, None
        if got and raising:
            raise Stopped(signal.Signals(got[0]).name)


@contextlib.contextmanager
def _stop_signals():
    old = {s: signal.getsignal(s) for s in SIGS}

    def stop(signum, _frame):
        for s in SIGS:
            signal.signal(s, signal.SIG_IGN)
        if _held is not None:
            _held.append(signum)
            return
        raise Stopped(signal.Signals(signum).name)
    for s in SIGS:
        signal.signal(s, stop)
    try:
        yield
    finally:
        for s, h in old.items():
            signal.signal(s, h)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
