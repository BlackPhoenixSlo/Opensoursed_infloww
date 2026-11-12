"""Shared run (lib/share.py) through `share.main` with an injected child command: a tiny script that counts its
starts in a file, blocks on a barrier file and exits with a chosen code. Each schedule asserts exit codes,
printed lines and the child-start count. venv/bin/python -m pytest slop/lib/test_share.py"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from slop.lib import identity, nightly, share

REPO = Path(__file__).resolve().parents[2]
PREFIX = b"slop: shared run of pid "

CHILD = r"""
import os, signal, sys, time
a = dict(x.split("=", 1) for x in sys.argv[2:] if "=" in x)
with open(a["count"], "a") as f:
    f.write("start\n")
def stopped(*_):
    if "stopped" in a:
        open(a["stopped"], "w").write("SIGINT\n")
    if "close" not in a:
        print("child stopped", flush=True)
    sys.exit(int(a.get("stopcode", 3)))
signal.signal(signal.SIGINT, stopped)
print("child of", sys.argv[1], flush=True)
print("slop: folder /tmp/fake-" + sys.argv[1], flush=True)
if "close" in a:  # stdout closed, process alive: the leader is in p.wait(), not in its tee
    os.close(1)
    os.close(2)  # stderr is the same pipe
while "barrier" in a and not os.path.exists(a["barrier"]):
    time.sleep(0.05)
if "touch" in a:
    open(a["touch"], "w").write("edited mid-run\n")
if "signal" in a:
    os.kill(os.getpid(), getattr(signal, "SIG" + a["signal"]))
sys.exit(int(a.get("code", 0)))
"""

DRIVER = r"""
import json, sys
sys.path.insert(0, {repo!r})
from slop.lib import share
cfg = json.loads(sys.argv[1])
sys.exit(share.main(sys.argv[2:], run=cfg["run"], root=cfg["root"], share_dir=cfg["dir"]))
"""


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def w(tmp_path):
    """A throwaway checkout, a share dir, the child script and the knobs every request of a test shares."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("count\nbarrier\nstopped\nshare/\n")
    (root / "x.py").write_text("x = 1\n")
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    child = tmp_path / "child.py"
    child.write_text(CHILD)

    class W:
        dir = root / "share"
        count, barrier = root / "count", root / "barrier"
        cfg = json.dumps({"run": [sys.executable, str(child)], "root": str(root), "dir": str(root / "share")})
        procs: list[subprocess.Popen] = []

        def args(self, *extra: str) -> list[str]:
            return ["scen", "--scale=small", f"count={self.count}", f"barrier={self.barrier}", *extra]

        def start(self, *extra: str, env: dict | None = None) -> subprocess.Popen:
            p = subprocess.Popen([sys.executable, "-c", DRIVER.format(repo=str(REPO)), self.cfg,
                                  *self.args(*extra), "--share"], cwd=root, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=env)
            self.procs.append(p)
            return p

        def starts(self) -> int:
            return len(self.count.read_text().splitlines()) if self.count.exists() else 0

        def until(self, pred, timeout: float = 15) -> None:
            end = time.time() + timeout
            while not pred():
                assert time.time() < end, "timed out waiting"
                time.sleep(0.05)

        def release(self) -> None:
            self.barrier.write_text("go\n")

        def key(self, *extra: str) -> str:
            return share.key(self.args(*extra), root, os.path.realpath(root), identity.source_id(root),
                             identity.env_id(os.environ)[0])

    yield W()
    W.barrier.write_text("go\n")  # let any orphaned child end
    for p in W.procs:
        if p.poll() is None:
            p.kill()
        p.wait()


def _out(p: subprocess.Popen, timeout: float = 30) -> tuple[int, bytes]:
    out, _ = p.communicate(timeout=timeout)
    return p.returncode, out


def _lead_and_follow(w, *extra: str):
    """A leader whose child is blocked on the barrier, and a follower that has joined it."""
    lead = w.start(*extra)
    w.until(lambda: w.starts() == 1)
    fol = w.start(*extra)
    first = fol.stdout.readline()
    assert first.startswith(PREFIX + str(lead.pid).encode() + b" (started "), first
    return lead, fol


def test_leader_alone_runs_its_child_and_prints_its_output(w):
    w.release()
    code, out = _out(w.start())
    assert code == 0 and w.starts() == 1
    assert out.splitlines() == [b"child of scen", b"slop: folder /tmp/fake-scen"]


def test_follower_joins_one_execution_with_the_same_output_and_exit(w):
    lead, fol = _lead_and_follow(w)
    w.release()
    (lc, lo), (fc, fo) = _out(lead), _out(fol)
    assert lc == fc == 0 and w.starts() == 1
    assert fo == lo and PREFIX not in lo


@pytest.mark.parametrize("extra, code", [("code=1", 1), ("code=3", 3), ("code=75", 75), ("signal=TERM", 143)])
def test_exit_codes_pass_through_verbatim(w, extra, code):
    lead, fol = _lead_and_follow(w, extra)
    w.release()
    (lc, lo), (fc, fo) = _out(lead), _out(fol)
    assert lc == fc == code and w.starts() == 1 and fo == lo


def test_follower_cancelled_stops_only_itself(w):
    lead, fol = _lead_and_follow(w)
    fol.send_signal(signal.SIGTERM)
    fc, fo = _out(fol)
    assert fc == 3 and b"slop: INFRA shared run: stopped (SIGTERM) before running a child" in fo
    assert lead.poll() is None
    w.release()
    lc, lo = _out(lead)
    assert lc == 0 and w.starts() == 1 and b"slop: folder /tmp/fake-scen" in lo


def test_leader_cancelled_leaves_followers_its_log_and_infra(w):
    lead, fol = _lead_and_follow(w)
    lead.send_signal(signal.SIGTERM)
    lc, lo = _out(lead)
    fc, fo = _out(fol)
    assert lc == 3 and b"child stopped" in lo  # stopped as nightly stops a child: SIGINT first
    assert b"slop: INFRA shared run: leader cancelled (SIGTERM)" in lo and b"follower stopped" not in lo
    assert fc == 3 and lo in fo
    assert b"slop: INFRA shared run of pid %d: leader cancelled/died without a result" % lead.pid in fo
    assert w.starts() == 1 and not list(w.dir.glob("*.result.json"))  # cancelled: no result published


def test_cancelled_leader_is_infra_even_when_its_child_exits_0(w):
    """R5-8: a child that exits 0 on the leader's SIGINT is no success (red before: the leader returned it)."""
    lead, fol = _lead_and_follow(w, "stopcode=0")
    lead.send_signal(signal.SIGTERM)
    (lc, lo), (fc, fo) = _out(lead), _out(fol)
    assert lc == 3 and b"child stopped" in lo and b"leader cancelled (SIGTERM)" in lo
    assert fc == 3 and b"leader cancelled/died without a result" in fo and not list(w.dir.glob("*.result.json"))


def test_leader_cancelled_after_its_child_closed_stdout_stops_it_gracefully(w):
    marker = w.count.parent / "stopped"
    lead, fol = _lead_and_follow(w, "close=1", f"stopped={marker}")
    w.until(lambda: b"slop: folder" in (w.dir / f"{w.key('close=1', f'stopped={marker}')}.{_nonce(w, 'close=1', f'stopped={marker}')}.log").read_bytes())
    time.sleep(0.3)  # the tee has seen EOF: the leader sits in p.wait()
    lead.send_signal(signal.SIGTERM)
    lc, lo = _out(lead)
    fc, fo = _out(fol)
    assert marker.read_text() == "SIGINT\n"  # nightly's graceful stop, not kill_tree's SIGTERM
    assert lc == 3 and b"slop: INFRA shared run: leader cancelled (SIGTERM)" in lo and b"follower stopped" not in lo
    assert fc == 3 and b"leader cancelled/died without a result" in fo and w.starts() == 1


def test_leader_died_leaves_followers_infra(w):
    lead, fol = _lead_and_follow(w)
    lead.kill()
    fc, fo = _out(fol)
    assert fc == 3 and b"child of scen" in fo
    assert b"leader cancelled/died without a result" in fo
    assert w.starts() == 1


def test_source_changed_mid_run_is_infra_with_no_second_child(w):
    lead, fol = _lead_and_follow(w, f"touch={w.count.parent / 'new.py'}")
    w.release()
    (lc, lo), (fc, fo) = _out(lead), _out(fol)
    assert lc == 0
    assert fc == 3 and lo in fo and b"source changed during the run; re-run" in fo
    assert w.starts() == 1


def test_a_later_request_leads_fresh(w):
    """Proves only that a request after the run ended leads a new execution (the lock is free by then); the
    "never serve a finished generation" mutation is caught by the rollover/publication-gap schedules below."""
    w.release()
    assert _out(w.start())[0] == 0
    code, out = _out(w.start())
    assert code == 0 and PREFIX not in out and w.starts() == 2


def _nonce(w, *extra: str) -> str:
    return json.loads((w.dir / f"{w.key(*extra)}.json").read_text())["nonce"]


def _hold(w) -> int:
    """This test as a leader that holds the lock but has not published its <key>.json yet."""
    w.dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(w.dir / f"{w.key()}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _publish(w, nonce: str, log: bytes, result: dict | None = None) -> None:
    k = w.key()
    (w.dir / f"{k}.{nonce}.log").write_bytes(log)
    (w.dir / f"{k}.json").write_text(json.dumps({"nonce": nonce, "pid": os.getpid(), "started": "T",
                                                 "source_id": identity.source_id(w.count.parent)}))
    if result is not None:
        (w.dir / f"{k}.{nonce}.result.json").write_text(json.dumps({"nonce": nonce, **result}))


@pytest.mark.parametrize("stale", [False, True], ids=["no-json-yet", "rollover-old-nonce-finished"])
def test_publication_gap_of_1s_joins_the_new_generation(w, stale):
    src = identity.source_id(w.count.parent)
    fd = _hold(w)
    if stale:  # A finished (result published), B leads before the follower reads
        _publish(w, "a", b"A output\n", {"exit": 1, "source_id_end": src})
    fol = w.start()
    time.sleep(1)
    _publish(w, "b", b"B output\n")
    assert fol.stdout.readline() == PREFIX + b"%d (started T)\n" % os.getpid()
    _publish(w, "b", b"B output\n", {"exit": 0, "source_id_end": src})
    os.close(fd)
    code, out = _out(fol)
    assert code == 0 and out == b"B output\n" and w.starts() == 0


def test_publication_gap_over_10s_is_infra_did_not_publish(w):
    fd = _hold(w)
    _publish(w, "a", b"A output\n", {"exit": 0, "source_id_end": "x"})
    t0 = time.time()
    code, out = _out(w.start())
    os.close(fd)
    assert code == 3 and b"slop: INFRA shared run did not publish" in out and b"A output" not in out
    assert 10 <= time.time() - t0 < 20 and w.starts() == 0


def test_rollover_returns_a_while_b_still_runs(w):
    """A published its result; the lock is held again (B's run): the follower answers with A at once."""
    src = identity.source_id(w.count.parent)
    fd = _hold(w)
    _publish(w, "a", b"A output\n")
    fol = w.start()
    assert fol.stdout.readline() == PREFIX + b"%d (started T)\n" % os.getpid()
    _publish(w, "a", b"A output\n", {"exit": 1, "source_id_end": src})
    _publish(w, "b", b"B output\n")  # B leads; the lock stays held for its whole run
    code, out = _out(fol, timeout=10)
    os.close(fd)
    assert code == 1 and out == b"A output\n" and w.starts() == 0


def test_a_new_leader_never_deletes_an_earlier_generation(w):
    """Another caller's shorter SLOP_SHARE_WAIT_S must not remove a generation a default-wait follower may still read."""
    k = w.key()
    w.dir.mkdir(parents=True, exist_ok=True)
    old = [w.dir / f"{k}.a.log", w.dir / f"{k}.a.result.json"]
    for f in old:
        f.write_text("A\n")
        os.utime(f, (time.time() - 3600,) * 2)
    w.release()
    code, _ = _out(w.start(env={**os.environ, "SLOP_SHARE_WAIT_S": "1"}))
    assert code == 0 and w.starts() == 1 and all(f.read_text() == "A\n" for f in old)


def _in_process(w, monkeypatch, capfdbinary, *extra: str) -> tuple[int, bytes]:
    monkeypatch.chdir(w.count.parent)
    cfg = json.loads(w.cfg)
    code = share.main([*w.args(*extra), "--share"], run=cfg["run"], root=cfg["root"], share_dir=cfg["dir"])
    return code, capfdbinary.readouterr().out


@pytest.mark.parametrize("where", ["publication", "spawn"])
def test_leader_cancelled_while_publishing_or_spawning_never_orphans_a_child(w, monkeypatch, capfdbinary, where):
    """A signal inside write_atomic (before any child) or inside Popen (child forked, not yet returned)."""
    marker = w.count.parent / "stopped"
    kids = []
    if where == "publication":
        real = share.write_atomic

        def hit(*a):
            os.kill(os.getpid(), signal.SIGTERM)
            real(*a)
        monkeypatch.setattr(share, "write_atomic", hit)
    else:
        real = subprocess.Popen

        def hit(cmd, *a, **k):
            p = real(cmd, *a, **k)
            if "barrier=" not in " ".join(map(str, cmd)):  # identity's git calls
                return p
            kids.append(p)
            w.until(lambda: w.starts() == 1)  # the child is running and blocked on the barrier
            os.kill(os.getpid(), signal.SIGTERM)
            return p
        monkeypatch.setattr(share.subprocess, "Popen", hit)
    code, out = _in_process(w, monkeypatch, capfdbinary, f"stopped={marker}")
    assert b"slop: INFRA shared run: leader cancelled (SIGTERM)" in out and b"follower stopped" not in out
    assert not list(w.dir.glob("*.result.json"))
    if where == "publication":
        assert code == 3 and w.starts() == 0
    else:
        assert code == 3 and marker.read_text() == "SIGINT\n" and kids[0].poll() is not None
    [lock] = w.dir.glob("*.lock")  # released: the next request can lead
    fcntl.flock(os.open(lock, os.O_RDWR), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_follower_wait_is_bounded(w):
    lead = w.start()
    w.until(lambda: w.starts() == 1)
    fol = w.start(env={**os.environ, "SLOP_SHARE_WAIT_S": "1"})  # admission-only: same Run identity
    fc, fo = _out(fol)
    assert fc == 3 and fo.startswith(PREFIX) and b"SLOP_SHARE_WAIT_S=1" in fo
    assert lead.poll() is None
    w.release()
    assert _out(lead)[0] == 0 and w.starts() == 1


@pytest.mark.parametrize("argv", [["nightly", "--share"], ["x", "--map", "--share"]])
def test_share_refused_with_map_and_nightly(w, argv, capsys):
    assert share.main(argv, run=["false"], root=w.count.parent, share_dir=w.dir) == 2
    assert "refused" in capsys.readouterr().err and w.starts() == 0


@pytest.mark.parametrize("argv", [["nightly", "--share"], ["x", "--map", "--share"]])
def test_slop_run_routes_share_before_the_gate(argv):
    p = subprocess.run([str(REPO / "slop/run"), *argv], capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and "--share is refused" in p.stderr, p


def test_nightly_children_never_share(tmp_path, monkeypatch):
    cmds = []
    monkeypatch.setattr(nightly.Night, "stream", lambda self, cmd, *a, **k: (cmds.append(cmd), (0, None, "", False, ""))[1])
    n = nightly.Night(tmp_path, tee=False)
    for phase in nightly.PHASES:
        n.run(phase, "s")
    args = nightly.argparse.Namespace(phases="all,volume,map", smoke=True)
    assert len(cmds) == 3 and not any("--share" in c for c in [*cmds, nightly.child_argv(args, tmp_path)])


def test_leader_liveness_is_pid_and_start_time():
    """A reused pid (another start time) is not the leader: no follower waits on an unrelated process."""
    me = os.getpid()
    assert share._leader_alive({"pid": me, "pid_start": share.procs.start_time(me)})
    assert not share._leader_alive({"pid": me, "pid_start": "Mon Jan  1 00:00:00 2001"})
    assert share._leader_alive({"pid": me})  # a generation published before pid_start: pid only
    assert not share._leader_alive({"pid": "x"})


def test_follower_reads_the_leader_start_time_at_most_every_few_seconds(tmp_path, monkeypatch):
    """The follower polls every STEP_S: a pid probe each time, the start time (a `ps` off Linux) once per START_CHECK_S."""
    calls = []
    real = share.procs.start_time
    monkeypatch.setattr(share.procs, "start_time", lambda pid: (calls.append(pid), real(pid))[1])
    me = os.getpid()
    meta = {"pid": me, "pid_start": real(me), "nonce": "n", "source_id": "s"}
    lock = tmp_path / "k.lock"
    held, fd = os.open(lock, os.O_RDWR | os.O_CREAT), os.open(lock, os.O_RDWR)
    share.fcntl.flock(held, share.fcntl.LOCK_EX)  # the live leader's lock: another open file, so it conflicts
    try:
        assert share._follow(fd, tmp_path, "k", meta, wait_s=1.0) == share.INFRA  # SLOP_SHARE_WAIT_S ran out
    finally:
        os.close(held), os.close(fd)
    assert len(calls) == 1


def test_share_stays_stdlib_only():
    """slop/run starts it with the system python3 before the gate: it imports with no site-packages, and
    without lib/nightly.py."""
    code = "import sys; sys.path.insert(0, %r); import slop.lib.share; print('slop.lib.nightly' in sys.modules)"
    out = subprocess.run([sys.executable, "-I", "-S", "-c", code % str(REPO)], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
