import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from slop.lib import procs, recovery, stack

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
        start = procs.start_time(p.pid)
        assert start
        state.write_text(json.dumps({"owner": dead_owner, "groups": [{"pid": p.pid, "start": start}]}))
        recovery.sweep(tmp_path)
        assert p.wait(timeout=10) != 0
    finally:
        _stop(p)


def _orphaned_group(script: str):
    """A group whose leader (sh) exits after starting `script`'s members: (leader record, member pid)."""
    p = subprocess.Popen(["sh", "-c", f"{script} & echo $!; read _"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         text=True, start_new_session=True)
    member = int(p.stdout.readline())
    group = {"pid": p.pid, "start": procs.start_time(p.pid)}
    p.stdin.close()
    p.wait(timeout=10)
    assert procs.group_alive(p.pid) and not procs.exists(p.pid)
    return group, member


def test_members_outliving_their_leader_are_reaped(tmp_path):
    """Red on leader-only tracking: the leader exited, the sweep dropped the record, the member kept running."""
    group, member = _orphaned_group("trap '' TERM; while :; do sleep 1; done")  # ignores SIGTERM: escalated
    try:
        state = tmp_path / ".stack-x.json"
        state.write_text(json.dumps({"owner": {"pid": os.getpid(), "start": OLD_START}, "groups": [group]}))
        recovery.sweep(tmp_path)
        assert _gone(member) and not procs.group_alive(group["pid"]) and not state.exists()
    finally:
        if procs.group_alive(group["pid"]):
            os.killpg(group["pid"], signal.SIGKILL)


def test_record_stays_while_a_group_has_members(tmp_path, monkeypatch, capsys):
    """A member that survives SIGKILL (stuck in the kernel): the record is kept, the next sweep finishes it."""
    group, member = _orphaned_group("sleep 60")
    try:
        state = tmp_path / ".stack-x.json"
        state.write_text(json.dumps({"owner": {"pid": os.getpid(), "start": OLD_START}, "groups": [group]}))
        monkeypatch.setattr(recovery, "KILL_WAIT_S", 0.3)
        monkeypatch.setattr(recovery, "_signal", lambda *_a: None)  # nothing dies
        recovery.sweep(tmp_path)
        assert "survived SIGKILL" in capsys.readouterr().err
        assert json.loads(state.read_text())["groups"] == [group] and not _gone(member, 0)
        monkeypatch.undo()
        recovery.sweep(tmp_path)
        assert _gone(member) and not state.exists()
    finally:
        if procs.group_alive(group["pid"]):
            os.killpg(group["pid"], signal.SIGKILL)


def test_live_owner_with_unreadable_start_keeps_its_groups(tmp_path, monkeypatch):
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        group = {"pid": p.pid, "start": procs.start_time(p.pid)}
        state = tmp_path / ".stack-x.json"
        state.write_text(json.dumps({"owner": {"pid": os.getpid(), "start": "s"}, "groups": [group]}))
        real = procs.start_time
        monkeypatch.setattr(procs, "start_time", lambda pid: None if pid == os.getpid() else real(pid))
        recovery.sweep(tmp_path)  # ps failed for a live owner: not dead
        assert p.poll() is None and state.exists()
    finally:
        _stop(p)


def test_stack_without_ps_or_proc_warns_once_and_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(procs.shutil, "which", lambda _name: None)
    monkeypatch.setattr(procs, "PROC", tmp_path / "no-proc")
    monkeypatch.setattr(recovery, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(recovery, "_warned", False)
    assert procs.start_time(os.getpid()) is None
    s = stack.Stack(ui=False, fault=None, logdir=tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    kids = [s._spawn(["sleep", "30"], dict(os.environ), f"p{i}.log", cwd=tmp_path) for i in range(2)]
    s.__exit__(None, None, None)
    assert all(p.wait(timeout=10) is not None for p in kids)
    assert capsys.readouterr().err.count("WARN cannot read process start times") == 1
    assert not list((tmp_path / "state").glob(".stack-*"))


def _app(tmp_path):
    app = tmp_path / "app"
    (app / ".next").mkdir(parents=True)
    (app / "tsconfig.json").write_text("original")
    return app, recovery.AppFiles(app, stack.RESTORE, app / ".next/slop.state.json")


def _ui_stack(tmp_path, monkeypatch, **kw):
    app, _files = _app(tmp_path)
    monkeypatch.setattr(stack, "ROOT", tmp_path)
    monkeypatch.setattr(stack, "APP_LOCK", app / ".next/slop.lock")
    monkeypatch.setattr(stack, "APP_STATE", app / ".next/slop.state.json")
    monkeypatch.setattr(recovery, "STATE_DIR", tmp_path / "state")
    return app, stack.Stack(ui=True, fault=None, logdir=tmp_path / "logs", **kw)


def test_exit_restores_a_boot_rewrite_after_the_last_poll(tmp_path, monkeypatch, capsys):
    """Boot aborted: `next` rewrote its files after the poll loop's last note, then exited. _wait's own exit
    notes it (slop's rewrite), so the in-process exit restores it (without that note: kept, WARN)."""
    app, s = _ui_stack(tmp_path, monkeypatch)
    s._lock = stack._lock_app()
    s._app_files.save()

    class Booted:
        def poll(self):
            (app / "tsconfig.json").write_text("next dev rewrite")
            (app / "next-env.d.ts").write_text("generated")
            return 1
    with pytest.raises(SystemExit, match="exited during startup"):
        s._wait("next dev", "http://127.0.0.1:9/login", 5, Booted(), app=True)
    s.__exit__(None, None, None)
    assert (app / "tsconfig.json").read_text() == "original"
    assert not (app / "next-env.d.ts").exists()
    assert not (app / ".next/slop.state.json").exists()
    assert "WARN" not in capsys.readouterr().err


def test_exit_keeps_a_user_edit_made_during_the_run(tmp_path, capsys):
    """R5-7: a file changed since slop last saw it (an edit while the UI stack ran) is kept, one WARN line;
    the other is restored (red before: restore() put every original back, the edit lost)."""
    app, files = _app(tmp_path)
    files.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    (app / "next-env.d.ts").write_text("generated")
    files.note_written()  # a _wait tick
    (app / "tsconfig.json").write_text("user edit")
    files.restore()
    assert _disk(app) == {"tsconfig.json": b"user edit", "next-env.d.ts": None}
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "WARN" in err and "tsconfig.json changed during this slop run" in err


def test_relay_wait_after_a_user_edit_keeps_the_edit(tmp_path, monkeypatch, capsys):
    """R6-1: only `next`'s boot waits note its rewrites; a relay (re)start's wait after a user edit must not
    record that edit as slop's (red before: every _wait noted, the exit put the original back over the edit)."""
    app, s = _ui_stack(tmp_path, monkeypatch)
    s._lock = stack._lock_app()
    s._app_files.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    s._app_files.note_written()  # next dev's boot wait
    (app / "tsconfig.json").write_text("user edit")

    class Exited:
        def poll(self):
            return 1
    with pytest.raises(SystemExit, match="relay exited during startup"):
        s._wait("relay", "http://127.0.0.1:9/livez", 5, Exited())  # a relay restart (start_relay)
    s.__exit__(None, None, None)
    assert (app / "tsconfig.json").read_text() == "user edit"
    assert "tsconfig.json changed during this slop run" in capsys.readouterr().err


def test_start_failing_before_save_keeps_a_dead_holders_originals(tmp_path, monkeypatch):
    """R6-3: a start cut before this run saved anything (here: reaping a killed holder's leftovers fails) must not
    drop that holder's state file (red before: the exit's restore() of an empty state unlinked it, the originals
    lost); the next holder still puts them back."""
    app, s = _ui_stack(tmp_path, monkeypatch)
    monkeypatch.setattr(stack, "PY", Path(sys.executable))
    dead = recovery.AppFiles(app, stack.RESTORE, app / ".next/slop.state.json")
    dead.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    dead.note_written()  # then SIGKILL
    kept = dead.state_path.read_bytes()

    def reap():
        raise OSError("disk full")
    monkeypatch.setattr(s._app_files, "_reap", reap)
    with pytest.raises(OSError, match="disk full"):
        s.__enter__()
    assert dead.state_path.read_bytes() == kept
    recovery.AppFiles(app, stack.RESTORE, dead.state_path).save()  # the next holder
    assert (app / "tsconfig.json").read_text() == "original"


def _member_outliving_its_leader(s, tmp_path):
    """A group whose leader (sh) dies on SIGTERM while a member ignores it: -> (leader pid, member pid)."""
    marker = tmp_path / "member"
    p = s._spawn(["sh", "-c", f"sh -c 'trap \"\" TERM; while :; do sleep 0.2; done' & echo $! > {marker}; wait"],
                 dict(os.environ), "p.log", cwd=tmp_path)
    deadline = time.monotonic() + 10
    while not (marker.exists() and marker.read_text().strip()):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    return p.pid, int(marker.read_text())


@pytest.mark.parametrize("survives_kill", [False, True])
def test_teardown_reaps_members_that_outlive_their_leader(tmp_path, monkeypatch, capsys, survives_kill):
    """R5-2: teardown waits for the group, not just its leader: a member ignoring SIGTERM is SIGKILLed; one that
    survives SIGKILL keeps the run record naming its group (red before: leader waited, record unlinked, the
    member orphaned with nothing left to reap it)."""
    monkeypatch.setattr(recovery, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(recovery, "KILL_WAIT_S", 0.3)
    s = stack.Stack(ui=False, fault=None, logdir=tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    leader, member = _member_outliving_its_leader(s, tmp_path)
    try:
        if survives_kill:
            monkeypatch.setattr(recovery, "_signal", lambda *_a: None)  # stuck in the kernel: nothing dies
        s.__exit__(None, None, None)
        records = list((tmp_path / "state").glob(".stack-*.json"))
        if survives_kill:
            assert procs.group_alive(leader) and len(records) == 1, records
            assert [g["pid"] for g in json.loads(records[0].read_text())["groups"]] == [leader]
            assert "survived SIGKILL" in capsys.readouterr().err
        else:
            assert _gone(member, 3) and not procs.group_alive(leader) and not records
    finally:
        if procs.group_alive(leader):
            os.killpg(leader, signal.SIGKILL)


def test_failed_start_tears_down_what_it_started(tmp_path, monkeypatch):
    """R5-6: the second relay fails to spawn after the app lock, the saved app files and the first relay:
    __enter__ tears all of it down (red before: lock held, relay running, temp dir left until a sweep)."""
    app, s = _ui_stack(tmp_path, monkeypatch, shards=2, apps=(0,))
    monkeypatch.setattr(stack, "PY", Path(sys.executable))
    cmds = iter([["sleep", "30"], [str(tmp_path / "no-such-relay")]])
    monkeypatch.setattr(s, "py_cmd", lambda script: next(cmds))  # how _start spawns each relay
    try:
        with pytest.raises(FileNotFoundError):
            s.__enter__()
        first = s.shard_pids[0]
        assert _gone(first, 3) and not s.tmp.exists() and s._lock is None
        os.close(stack._lock_app())  # free again
        assert (app / "tsconfig.json").read_text() == "original" and not (app / ".next/slop.state.json").exists()
        assert not list((tmp_path / "state").glob(".stack-*.json"))
    finally:
        for p in s.procs:
            _stop(p)


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
    view = recovery.checkout_view(app, stack.RESTORE, files.state_path)
    recovery.AppFiles(app, stack.RESTORE, files.state_path).save()  # the next holder reaps
    assert view == _disk(app)
    if case == "empty-original-deleted":
        assert view["next-env.d.ts"] == b""  # empty, not absent


@pytest.mark.parametrize("edit, want", [(None, b"original"), (b"user edit", b"user edit")])
def test_live_holders_view_is_what_its_exit_restores(tmp_path, edit, want):
    app, files = _app(tmp_path)
    files.save()
    (app / "tsconfig.json").write_text("next dev rewrite")
    (app / "next-env.d.ts").write_text("generated")
    files.note_written()
    if edit:
        (app / "tsconfig.json").write_bytes(edit)
    view = recovery.checkout_view(app, stack.RESTORE, files.state_path)
    files.restore()
    assert view == _disk(app) == {"tsconfig.json": want, "next-env.d.ts": None}


@pytest.mark.parametrize("state", ["{", "[]", '{"originals": 1}', '{"originals": {"tsconfig.json": "%%%"}}',
                                   '{"originals": {"tsconfig.json": 7}, "written": {}}'])
def test_view_of_malformed_state_is_disk_and_read_only(tmp_path, state, capsys):
    app, files = _app(tmp_path)
    files.state_path.write_text(state)
    assert recovery.checkout_view(app, stack.RESTORE, files.state_path) == _disk(app)
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


def test_prod_build_rewrite_is_noted_as_slops(tmp_path, monkeypatch, capsys):
    """R7-1: `next build`'s app-file rewrite is noted while it builds (as a boot's), so a run killed after the
    build leaves the next holder slop's rewrite to put back, and the run's own exit restores it, no WARN (red
    before: a separate `kept` copy restored blindly, nothing noted: a kill mid-build left the rewrite as a
    'user edit', kept dirty with a false WARN)."""
    app, s = _ui_stack(tmp_path, monkeypatch)
    s.logdir.mkdir(parents=True, exist_ok=True)
    s._lock = stack._lock_app()
    s._app_files.save()

    class Build:
        pid, returncode, polls = 0, None, 0

        def poll(self):
            self.polls += 1
            if self.polls == 1:
                (app / "tsconfig.json").write_text("build rewrite")
                (app / "next-env.d.ts").write_text("generated")
                return None
            self.returncode = 0
            return 0
    spawned = []

    def fake_spawn(cmd, env, log, cwd, mode="w"):
        if spawned:
            raise SystemExit("stop before next start")
        spawned.append(cmd)
        return Build()
    monkeypatch.setattr(s, "_spawn", fake_spawn)
    monkeypatch.setattr(stack.time, "sleep", lambda _: None)
    with pytest.raises(SystemExit, match="stop before next start"):
        s._prod_app({}, 0)
    assert spawned and spawned[0][-2:] == ["build", "--turbopack"]
    # killed here: the next holder's view is the originals (slop's rewrite), not a conflict
    assert recovery.checkout_view(app, recovery.APP_FILES, app / ".next/slop.state.json") == {
        "tsconfig.json": b"original", "next-env.d.ts": None}
    s.__exit__(None, None, None)
    assert (app / "tsconfig.json").read_text() == "original"
    assert not (app / "next-env.d.ts").exists()
    assert "WARN" not in capsys.readouterr().err


def test_teardown_never_signals_a_reaped_leaders_pid(tmp_path, monkeypatch):
    """R8-1: a leader already reaped (a finished `next build`, a relay that died) is not SIGTERMed at teardown:
    its pid may lead another process group by now (red before: killpg on every entry of `procs`)."""
    _app_dir, s = _ui_stack(tmp_path, monkeypatch)
    s.logdir.mkdir(parents=True, exist_ok=True)
    s.tmp.mkdir(parents=True, exist_ok=True)

    class Reaped:
        pid, returncode = 999_999, 0

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0
    s.procs = [Reaped()]
    sent = []
    monkeypatch.setattr(stack.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    s.__exit__(None, None, None)
    assert (999_999, signal.SIGTERM) not in sent and s.procs == []
