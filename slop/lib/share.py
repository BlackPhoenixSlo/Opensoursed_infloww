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
    sys.path.insert(0, str(ROOT))

from slop.lib import identity, procs  # noqa: E402
from slop.lib.report import EVIDENCE, write_atomic  # noqa: E402

FLAG = "--share"
# gate slot wait 3600 + scenario timeout 1800 + admission margin
WAIT_S = 7200
# a leader holding the lock may not have written <key>.json yet
PUBLISH_WAIT_S, STEP_S = 10, 0.2
START_CHECK_S = 5
INFRA = 3
SIGS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
_held: list[int] | None = None


class Stopped(Exception):
    pass


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
    except Exception as e:
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
                if time.monotonic() >= end:
                    print(f"slop: INFRA shared run did not publish within {PUBLISH_WAIT_S}s "
                          f"(lock held, no live generation in {d / k}.json); re-run", flush=True)
                    return INFRA
                time.sleep(STEP_S)
        except Stopped as e:
            print(f"slop: INFRA shared run: stopped ({e}) before running a child; a live leader keeps running",
                  flush=True)
            return INFRA
        finally:
            os.close(fd)


def _lead(d: Path, k: str, meta: dict, run: list[str], root: Path) -> int:
    nonce, p, out = meta["nonce"], None, sys.stdout.buffer
    with open(d / f"{k}.{nonce}.log", "wb") as log:
        try:
            write_atomic(d / f"{k}.json", json.dumps(meta) + "\n")
            # a signal inside Popen must not leave its child unsupervised
            with _deferred():
                p = subprocess.Popen([*run, *meta["argv"]], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            _tee(p.stdout, out, log)
            code = _shell_code(p.wait())
            with _deferred(raising=False):
                try:
                    end = identity.source_id(root)
                except Exception:
                    end = None
                write_atomic(d / f"{k}.{nonce}.result.json", json.dumps(
                    {"nonce": nonce, "exit": code, "source_id_end": end,
                     "finished": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
            return code
        except Stopped as e:
            procs.stop_child(p)
            if p is not None:
                _tee(p.stdout, out, log)
            _tee([f"slop: INFRA shared run: leader cancelled ({e}); no result published\n".encode()], out, log)
            if p is not None:
                p.wait()
            return INFRA
        finally:
            if p is not None and p.poll() is None:
                procs.kill_tree(p)


def _follow(fd: int, d: Path, k: str, meta: dict, wait_s: float) -> int:
    pid, nonce = meta["pid"], meta["nonce"]
    res_path = d / f"{k}.{nonce}.result.json"
    print(f"slop: shared run of pid {pid} (started {meta.get('started')})", flush=True)
    end, timed_out, checked = time.monotonic() + wait_s, False, -START_CHECK_S

    def leader_alive() -> bool:
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
    pid = meta.get("pid")
    return isinstance(pid, int) and procs.alive(pid, meta.get("pid_start"))


def _trylock(fd: int, kind: int) -> bool:
    try:
        fcntl.flock(fd, kind | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _shell_code(code: int) -> int:
    return 128 - code if code < 0 else code


def _tee(src, out, log) -> None:
    lines = iter(src.readline, b"") if hasattr(src, "readline") else src
    for line in lines:
        log.write(line)
        log.flush()
        with contextlib.suppress(BrokenPipeError):
            out.write(line)
            out.flush()


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _deferred(raising: bool = True):
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
