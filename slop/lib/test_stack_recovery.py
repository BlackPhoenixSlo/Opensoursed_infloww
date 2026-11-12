import base64
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from slop.lib import recovery, stack

OLD_START = "Mon Jan  1 00:00:00 2001"


def _gone(pid: int, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _stop(p: subprocess.Popen) -> None:
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()


def test_reexecing_python_child_is_reaped_after_its_owner_dies(tmp_path):
    """A venv python re-execs (macOS framework python: comm `python` -> `Python`); its start time stays."""
    owner_code = ("import subprocess, sys, time\n"
                  "from pathlib import Path\n"
                  "from slop.lib import recovery\n"
                  "rs = recovery.RunState(Path(sys.argv[1]))\n"
                  "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], start_new_session=True)\n"
                  "rs.record(p.pid)\n"
                  "print(p.pid, flush=True)\n"
                  "time.sleep(120)\n")
    owner = subprocess.Popen([sys.executable, "-c", owner_code, str(tmp_path)], cwd=stack.ROOT,
                             env={**os.environ, "PYTHONPATH": str(stack.ROOT)}, stdout=subprocess.PIPE, text=True)
    child = int(owner.stdout.readline())
    try:
        time.sleep(1.5)  # past the re-exec
        recovery.sweep(tmp_path)  # owner alive: untouched
        assert not _gone(child, 0.2) and len(list(tmp_path.glob(".stack-*.json"))) == 1
        owner.kill()
        owner.wait()
        recovery.sweep(tmp_path)
        assert _gone(child), "orphaned relay-like python survived the sweep"
        assert not list(tmp_path.glob(".stack-*.json"))
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait()
        if not _gone(child, 0):
            os.killpg(child, signal.SIGKILL)


def test_reused_pid_with_another_start_time_survives(tmp_path):
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        dead_owner = {"pid": os.getpid(), "start": OLD_START}  # this pid, another process's start: gone
        state = tmp_path / ".stack-x.json"
        state.write_text(json.dumps({"owner": dead_owner, "groups": [{"pid": p.pid, "start": OLD_START}]}))
        recovery.sweep(tmp_path)
        assert p.poll() is None and not state.exists()
        start = recovery.identity(p.pid)
        assert start
        state.write_text(json.dumps({"owner": dead_owner, "groups": [{"pid": p.pid, "start": start}]}))
        recovery.sweep(tmp_path)
        assert p.wait(timeout=10) != 0
    finally:
        _stop(p)


def test_live_owner_with_unreadable_start_keeps_its_groups(tmp_path, monkeypatch):
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        group = {"pid": p.pid, "start": recovery.identity(p.pid)}
        state = tmp_path / ".stack-x.json"
        state.write_text(json.dumps({"owner": {"pid": os.getpid(), "start": "s"}, "groups": [group]}))
        real = recovery.identity
        monkeypatch.setattr(recovery, "identity", lambda pid: None if pid == os.getpid() else real(pid))
        recovery.sweep(tmp_path)  # ps failed for a live owner: not dead
        assert p.poll() is None and state.exists()
    finally:
        _stop(p)


def test_stack_without_ps_or_proc_warns_once_and_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(recovery.shutil, "which", lambda _name: None)
    monkeypatch.setattr(recovery, "PROC", tmp_path / "no-proc")
    monkeypatch.setattr(recovery, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(recovery, "_warned", False)
    assert recovery.identity(os.getpid()) is None
    s = stack.Stack(ui=False, fault=None, logdir=tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    procs = [s._spawn(["sleep", "30"], dict(os.environ), f"p{i}.log", cwd=tmp_path) for i in range(2)]
    s.__exit__(None, None, None)
    assert all(p.wait(timeout=10) is not None for p in procs)
    assert capsys.readouterr().err.count("WARN cannot read process start times") == 1
    assert not list((tmp_path / "state").glob(".stack-*"))


def test_linux_proc_start_ticks(tmp_path, monkeypatch):
    (tmp_path / "123").mkdir()
    rest = " ".join(["S"] + [str(i) for i in range(4, 53)])  # field 3 on; field 22 holds "22"
    (tmp_path / "123/stat").write_text(f"123 (a b) c) {rest}\n")
    monkeypatch.setattr(recovery, "PROC", tmp_path)
    assert recovery.identity(123) == "ticks 22"
    assert recovery.identity(124) is None


def _app(tmp_path):
    app = tmp_path / "app"
    (app / ".next").mkdir(parents=True)
    (app / "tsconfig.json").write_text("original")
    return app, recovery.AppFiles(app, stack.RESTORE, app / ".next/slop.state.json")


def test_exit_restores_even_when_next_never_got_ready(tmp_path, monkeypatch, capsys):
    """Boot aborted / prod mode: no `written` beyond the start; the in-process exit restores anyway."""
    app, _files = _app(tmp_path)
    monkeypatch.setattr(stack, "ROOT", tmp_path)
    monkeypatch.setattr(stack, "APP_LOCK", app / ".next/slop.lock")
    monkeypatch.setattr(stack, "APP_STATE", app / ".next/slop.state.json")
    monkeypatch.setattr(recovery, "STATE_DIR", tmp_path / "state")
    s = stack.Stack(ui=True, fault=None, logdir=tmp_path / "logs")
    s._lock = stack._lock_app()
    s._app_files.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    (app / "next-env.d.ts").write_text("generated")
    s.__exit__(None, None, None)
    assert (app / "tsconfig.json").read_text() == "original"
    assert not (app / "next-env.d.ts").exists()
    assert not (app / ".next/slop.state.json").exists()
    assert "WARN" not in capsys.readouterr().err


def test_crash_reaper_restores_only_what_slop_last_saw(tmp_path, capsys):
    app, files = _app(tmp_path)
    files.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    (app / "next-env.d.ts").write_text("generated")
    files.note_written()  # a _wait tick; then the run is SIGKILLed
    (app / "next-env.d.ts").write_text("user recreated")
    nxt = recovery.AppFiles(app, stack.RESTORE, app / ".next/slop.state.json")
    nxt.save()  # the next lock holder
    assert (app / "tsconfig.json").read_text() == "original"
    assert (app / "next-env.d.ts").read_text() == "user recreated"
    assert capsys.readouterr().err.count("WARN") == 1
    assert json.loads((app / ".next/slop.state.json").read_text())["originals"]["tsconfig.json"] == \
        base64.b64encode(b"original").decode()


def test_corrupt_state_is_discarded(tmp_path, capsys):
    app, files = _app(tmp_path)
    (app / ".next/slop.state.json").write_text("{")
    (tmp_path / ".stack-bad.json").write_text("[")
    files.save()
    recovery.sweep(tmp_path)
    assert not (tmp_path / ".stack-bad.json").exists()
    assert capsys.readouterr().err.count("WARN corrupt") == 2


def test_node_modules_copy_is_atomic_for_concurrent_first_runs(tmp_path):
    from slop.lib import clone_modules
    main, work = tmp_path / "main", tmp_path / "work"
    (main / "app/node_modules").mkdir(parents=True)
    (work / "app").mkdir(parents=True)
    for i in range(100):
        (main / "app/node_modules" / f"file{i}").write_text(str(i))
    link = work / "app/node_modules"
    link.symlink_to(main / "app/node_modules", target_is_directory=True)
    helper = clone_modules.__file__
    procs = [subprocess.Popen([sys.executable, helper, str(main), str(work)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for p in procs:
        _out, err = p.communicate(timeout=30)
        assert p.returncode == 0, err.decode()
    dest = work / "app/node_modules"
    assert len(list(dest.iterdir())) == 100
    assert not (dest / "node_modules").exists()
    assert not dest.is_symlink()
    assert len(list((main / "app/node_modules").iterdir())) == 100
    assert not list((work / "app/.next").glob("slop-node_modules.tmp.*"))


def _disk(app):
    return {f: (app / f).read_bytes() if (app / f).exists() else None for f in stack.RESTORE}


@pytest.mark.parametrize("case", ["rewrite-unchanged", "user-edit-after", "user-deleted-after",
                                  "empty-original-deleted", "absent-original-created", "never-rewritten"])
def test_dead_holders_view_is_what_the_next_holder_leaves(tmp_path, case):
    """checkout_view(live=False) before the next holder's _reap == disk after it, file by file."""
    app, files = _app(tmp_path)
    if case == "empty-original-deleted":
        (app / "next-env.d.ts").write_text("")
    files.save()
    if case != "never-rewritten":
        (app / "tsconfig.json").write_text("next dev rewrite")
        if case == "empty-original-deleted":
            (app / "next-env.d.ts").unlink()
        else:
            (app / "next-env.d.ts").write_text("generated")
        files.note_written()  # then SIGKILL
    if case == "user-edit-after":
        (app / "tsconfig.json").write_text("user edit")
    elif case == "user-deleted-after":
        (app / "tsconfig.json").unlink()
    view = recovery.checkout_view(app, stack.RESTORE, files.state_path, live=False)
    recovery.AppFiles(app, stack.RESTORE, files.state_path).save()  # the next holder reaps
    assert view == _disk(app)
    if case == "empty-original-deleted":
        assert view["next-env.d.ts"] == b""  # empty, not absent


def test_live_holders_view_is_what_its_exit_restores(tmp_path):
    app, files = _app(tmp_path)
    files.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    (app / "next-env.d.ts").write_text("generated")  # not yet noted: restore() puts it back anyway
    view = recovery.checkout_view(app, stack.RESTORE, files.state_path, live=True)
    files.restore()
    assert view == _disk(app) == {"tsconfig.json": b"original", "next-env.d.ts": None}


@pytest.mark.parametrize("state", ["{", "[]", '{"originals": 1}', '{"originals": {"tsconfig.json": "%%%"}}',
                                   '{"originals": {"tsconfig.json": 7}, "written": {}}'])
def test_view_of_malformed_state_is_disk_and_read_only(tmp_path, state, capsys):
    app, files = _app(tmp_path)
    files.state_path.write_text(state)
    for live in (True, False):
        assert recovery.checkout_view(app, stack.RESTORE, files.state_path, live) == _disk(app)
    assert files.state_path.read_text() == state and capsys.readouterr().err == ""
    before = _disk(app)
    recovery.AppFiles(app, stack.RESTORE, files.state_path).save()  # the next holder: never raises on it
    assert _disk(app) == before


SIDE = """import http.server, os, signal, sys
srv = http.server.HTTPServer(("127.0.0.1", int(os.environ["SIDE_PORT"])), http.server.SimpleHTTPRequestHandler)
def term(*_):
    open(os.environ["SIDE_MARK"], "a").write("drained\\n")
    sys.exit(0)
signal.signal(signal.SIGTERM, term)
print("up", flush=True)
srv.serve_forever()
"""


def test_sidecar_stop_is_a_sigterm_drain_and_start_reuses_port_env_and_log(tmp_path, monkeypatch):
    """stop_sidecar: SIGTERM, waits for the exit (its handler ran), reaped; start_sidecar: same port and env, log
    appended, health waited for."""
    monkeypatch.setattr(recovery, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(stack, "ROOT", tmp_path)
    monkeypatch.setattr(stack, "PY", sys.executable)
    (tmp_path / "side.py").write_text(SIDE)
    (tmp_path / "logs").mkdir()
    s = stack.Stack(ui=False, fault=None, logdir=tmp_path / "logs", sidecars={"side": ("side.py", "SIDE_PORT", "/")})
    s._relay_envs.append(dict(os.environ, SIDE_MARK=str(tmp_path / "mark")))
    try:
        s.start_sidecar("side", timeout=20)
        first = s.sidecar_procs["side"]
        _, took = s.stop_sidecar("side", grace_s=10)
        assert took is not None and first.poll() == 0 and first not in s.procs
        assert (tmp_path / "mark").read_text() == "drained\n"
        s.start_sidecar("side", timeout=20)
        assert s.sidecar_procs["side"].pid != first.pid and s.sidecar_procs["side"].poll() is None
        assert (tmp_path / "logs" / s._log("side", 0)).read_text().count("up") == 2
    finally:
        s.__exit__(None, None, None)
