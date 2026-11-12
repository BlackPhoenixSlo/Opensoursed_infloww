import asyncio
import binascii
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop.lib import cli, covmap, report


def test_http_route_prefix_and_expected_4xx():
    import httpx
    from slop.lib.client import Http, Recorder

    async def go():
        rec = Recorder()
        h = Http("http://127.0.0.1:9", rec, prefix="edge ")
        await h.c.aclose()
        h.c = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(404)),
                                base_url="http://127.0.0.1:9")
        try:
            await h.get("/a/12")
            await h.get("/b", route="named", expect=(404,))
            assert list(rec.calls) == ["edge GET /a/:id", "edge named"]
            assert len(rec.errors) == 1 and "GET /a/12 -> 404" in rec.errors[0]
        finally:
            await h.aclose()
    asyncio.run(go())


def test_stop_proc_can_repeat(monkeypatch):
    from slop.lib.stack import Stack

    class Proc:
        pid = 12345

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(os, "killpg", lambda *_: None)
    stack = Stack.__new__(Stack)
    stack.procs = [Proc()]
    stack._stop_proc(12345, 0)
    stack._stop_proc(12345, 0)
    assert not stack.procs


def _three_scenarios(monkeypatch, tmp_path):
    """`slop/run all` over a, b, c with the real run_one; only the stack and machine-wide state are faked."""
    ev = tmp_path / "evidence"
    ev.mkdir()
    monkeypatch.setattr(cli, "scenarios", lambda: {n: tmp_path / f"{n}.py" for n in ("a", "b", "c")})
    monkeypatch.setattr(cli, "load", lambda _p: SimpleNamespace(UI=False))
    monkeypatch.setattr(cli, "run_dir", lambda name, tag: ev / name)
    monkeypatch.setattr(report, "EVIDENCE", ev)
    monkeypatch.setattr(cli, "_nice", lambda: None)
    monkeypatch.setattr(cli.netloss, "wire_off_stale", lambda: None)
    monkeypatch.setenv("SLOP_GATE", "off")
    monkeypatch.setattr(sys, "argv", ["slop/run", "all"])
    for n in "abc":
        (ev / n / "screenshots").mkdir(parents=True)
    return ev


def test_sigterm_stops_remaining_scenarios(monkeypatch, tmp_path):
    ev, entered = _three_scenarios(monkeypatch, tmp_path), []

    async def stack(name, *_a):
        entered.append(name)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(cli, "_run_stack", stack)
    assert cli.main() == 3
    assert entered == ["a"]
    assert "infra: signal SIGTERM; stack torn down" in (ev / "a/summary.txt").read_text()


def test_sigterm_after_teardown_still_writes_the_report(monkeypatch, tmp_path):
    ev, entered = _three_scenarios(monkeypatch, tmp_path), []

    async def stack(name, *_a):
        entered.append(name)

    def checks(*_a):
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(cli, "_run_stack", stack)
    monkeypatch.setattr(cli, "_stock_checks", checks)
    assert cli.main() == 3
    assert entered == ["a"]
    assert "INFRA FAILURE" in (ev / "a/summary.txt").read_text()


def test_estimate_matches_sharded_green(monkeypatch, tmp_path):
    args = SimpleNamespace(scale="small", users=2, seed=1, no_ui=True, shards=None,
                           profile=False, map=False, net=None)
    path = tmp_path / "fleet.py"
    monkeypatch.setattr(cli, "load", lambda _p: SimpleNamespace(SHARDS=3, UI=False))
    want = cli._run_knobs("fleet", args, {}, False, 3, None)
    monkeypatch.setattr(cli, "_green_runs", lambda _n: iter([(path, {"seconds": 40, "params": want})]))
    secs, source = cli._estimates(["fleet"], {"scenarios": {"fleet": {"seconds": 80}}},
                                  args, {"fleet": path}, {})
    assert secs == {"fleet": 40} and source == "evidence"


def test_break_import_error_is_inconclusive(monkeypatch, tmp_path):
    def bad(_path):
        raise ImportError("missing dependency")
    monkeypatch.setattr(cli, "load", bad)
    assert cli.break_one("bad", tmp_path / "bad.py", None, {}) == "INCONCLUSIVE"


def test_invalid_map_is_infra(monkeypatch, tmp_path, capsys):
    bad_map = tmp_path / "map.json"
    bad_map.write_text("{invalid")
    monkeypatch.setattr(covmap, "MAP", bad_map)
    monkeypatch.setattr(sys, "argv", ["slop/run", "--list"])

    assert cli.main() == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("slop: INFRA slop/map.json invalid: Expecting property name")
    assert lines[0].endswith("(restore: git checkout slop/map.json, or slop/run all --map)")


def test_unrelated_runtime_error_with_map_message_propagates(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["slop/run", "--list"])
    message = f"{covmap.MAP}: invalid JSON; refusing to discard map entries"
    monkeypatch.setattr(covmap, "load_map", lambda: (_ for _ in ()).throw(RuntimeError(message)))

    with pytest.raises(RuntimeError, match="invalid JSON"):
        cli.main()


def test_load_registers_the_module_for_dataclasses(tmp_path):
    p = tmp_path / "2099-01-01-dc.py"
    p.write_text("from __future__ import annotations\nfrom dataclasses import dataclass\n\n\n"
                 "@dataclass\nclass Row:\n    n: int = 1\n")
    assert cli.load(p).Row().n == 1


def test_bad_import_is_one_infra_row_and_the_rest_run(monkeypatch, tmp_path, capsys):
    """The real load: a scenario whose import raises is an INFRA row; the next scenario still runs."""
    ev = tmp_path / "evidence"
    for n in ("bad", "good"):
        (ev / n / "screenshots").mkdir(parents=True)
    (tmp_path / "bad.py").write_text("import slop_no_such_module_xyz\n")
    (tmp_path / "good.py").write_text("UI = False\n")
    monkeypatch.setattr(cli, "scenarios", lambda: {n: tmp_path / f"{n}.py" for n in ("bad", "good")})
    monkeypatch.setattr(cli, "run_dir", lambda name, tag: ev / name)
    monkeypatch.setattr(report, "EVIDENCE", ev)
    monkeypatch.setattr(cli, "_nice", lambda: None)
    monkeypatch.setattr(cli.netloss, "wire_off_stale", lambda: None)
    monkeypatch.setenv("SLOP_GATE", "off")
    monkeypatch.setattr(sys, "argv", ["slop/run", "all"])
    ran = []

    async def stack(name, *_a):
        ran.append(name)
    monkeypatch.setattr(cli, "_run_stack", stack)
    assert cli.main() == 3
    assert ran == ["good"]
    out = capsys.readouterr().out
    assert "slop: INFRA bad: scenario import/knobs failed: ModuleNotFoundError" in out
    assert "slop: OK   good" in out
    assert "slop_scenario_bad" not in sys.modules


def test_socket_limit_per_scale():
    mod = SimpleNamespace(MAX_SOCKETS_RUN={"medium": 26000})
    assert cli.socket_limit(mod, "medium") == 26000
    assert cli.socket_limit(mod, "small") is None
    assert cli.socket_limit(SimpleNamespace(), "medium") is None


@pytest.mark.parametrize("argv,want", [
    (["relay-admission", "--scale=medium", "--users=200", "--no-ui"], True),
    (["relay-admission", "--scale=medium", "--users=120", "--no-ui"], True),
    (["relay-admission", "--scale", "huge", "--users", "500"], True),
    (["relay-admission", "--scale=medium", "--users=119"], False),
    (["relay-admission", "--scale=small", "--users=200"], False),
    (["relay-admission", "--users=200"], False),  # default scale small
    (["relay-admission", "--scale=medium"], False),  # default users 20
    (["--changed"], False),
])
def test_exclusive_is_medium_120_or_more(argv, want):
    from slop.lib import gate
    assert gate.exclusive(argv) is want


def test_slop_run_asks_for_exclusive():
    root = Path(__file__).resolve().parents[1]
    run = lambda *a: subprocess.run([sys.executable, str(root / "lib/gate.py"), *a], capture_output=True,
                                    text=True).stdout.strip()
    assert run("x", "--scale=medium", "--users=119") == ""
    assert run("x", "--scale=medium", "--users=120") == "--exclusive"
    assert run("x", "--scale=medium", "--users=200") == "--exclusive"
    assert run("x", "--scale=small") == ""


@pytest.mark.parametrize("users,exclusive", [(119, False), (120, True), (200, True)])
def test_actual_runner_forwards_volume_gate_choice(tmp_path, users, exclusive):
    """Exercise slop/run's shell re-exec, stopping at the machine gate."""
    if not (Path.home() / ".slop/gate.py").is_file():
        pytest.skip("machine gate unavailable")
    capture = tmp_path / "gate-argv"
    shim = tmp_path / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "$HOME/.slop/gate.py" ]; then\n'
        '  printf "%s\\n" "$@" > "$SLOP_CAPTURE"\n'
        "  exit 0\n"
        "fi\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n"
    )
    shim.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "SLOP_GATED"}
    env.update(PATH=f"{tmp_path}:{env['PATH']}", SLOP_CAPTURE=str(capture))
    root = Path(__file__).resolve().parents[1]
    args = ["x", "--scale=medium", f"--users={users}", "--no-ui"]
    subprocess.run(["bash", str(root / "run"), *args], env=env, check=True, capture_output=True, text=True)
    forwarded = capture.read_text().splitlines()
    assert forwarded[1:4 if exclusive else 3] == (["run", "--exclusive", "--"] if exclusive else ["run", "--"])
    assert forwarded[-len(args):] == args


def test_thread_limit_per_scale():
    mod = SimpleNamespace(MAX_THREADS_PROC={"medium": 3000})
    assert cli.thread_limit(mod, "medium") == 3000
    assert cli.thread_limit(mod, "small") is None
    assert cli.thread_limit(SimpleNamespace(), "medium") is None


# --- Run identity: a Break baseline is reused only at an equal Run identity (lib/identity.py) ---

BREAK_FAULT = "sweep-enqueued-every-pass"


def _break_setup(monkeypatch, tmp_path):
    """`slop/run s --break [--baseline=...]` through cli.main() with the real run_one and break logic; only the
    stack is faked: a targeted check passes without the fault and fails with it. Returns (evidence dir, faults
    started per run_one: None for a baseline run)."""
    from slop.lib.faults import FAULTS
    ev, started, n = tmp_path / "evidence", [], iter(range(1000))
    ev.mkdir()
    monkeypatch.setattr(cli, "scenarios", lambda: {"s": tmp_path / "s.py"})
    monkeypatch.setattr(cli, "load", lambda _p: SimpleNamespace(UI=False, FAULT=BREAK_FAULT))

    def run_dir(name, tag):
        d = ev / f"{next(n):03d}-{name}-{tag or 'run'}"
        (d / "screenshots").mkdir(parents=True)
        return d
    monkeypatch.setattr(cli, "run_dir", run_dir)
    monkeypatch.setattr(report, "EVIDENCE", ev)
    monkeypatch.setattr(cli, "_nice", lambda: None)
    monkeypatch.setattr(cli.netloss, "wire_off_stale", lambda: None)
    monkeypatch.setenv("SLOP_GATE", "off")

    async def stack(name, mod, out, rep, rec, args, params, ui, shards, fault, *_a):
        started.append(fault)
        for t in FAULTS[BREAK_FAULT].targets:
            rep.check(t, fault is None)
    monkeypatch.setattr(cli, "_run_stack", stack)
    return ev, started


def _green_folder(tmp_path, **identity) -> Path:
    """A green no-fault run folder of scenario `s` at the default knobs, with these params added."""
    from slop.lib.faults import FAULTS
    d = tmp_path / "green"
    d.mkdir()
    args = SimpleNamespace(scale="small", users=20, seed=1, profile=False, map=False, net=None)
    knobs = cli._run_knobs("s", args, {}, False, 1, None)
    (d / "metrics.json").write_text(json.dumps({"params": {**knobs, "git_sha": "abc1234", "git_dirty": False,
                                                           **identity}, "infra": None}))
    (d / "invariants.json").write_text(json.dumps([{"name": t, "ok": True, "status": "pass"}
                                                   for t in FAULTS[BREAK_FAULT].targets]))
    return d


def _runs(ev: Path) -> list[Path]:
    return [d for d in ev.iterdir() if d.is_dir() and not d.is_symlink()]  # not `latest`


def _break(monkeypatch, *extra) -> int:
    monkeypatch.setattr(sys, "argv", ["slop/run", "s", "--break", *extra])
    return cli.main()


def test_baseline_from_other_source_is_refused(monkeypatch, tmp_path, capsys):
    """Red on the knob-only comparison: a green folder from other source (same knobs) was reused silently."""
    ev, started = _break_setup(monkeypatch, tmp_path)
    old = "0" * 64
    g = _green_folder(tmp_path, source_id=old, source_id_end=old, env_id="e", env_names=[])
    assert _break(monkeypatch, f"--baseline={g}") == 3
    out = capsys.readouterr().out
    assert "other knobs" not in out  # identity facts are not knobs: the refusal must say which part differs
    assert any(line.lstrip().startswith("inconclusive:") and "source" in line for line in out.splitlines()), out
    assert started == [] and not list(ev.iterdir())  # no fault run, no fault-run folder


def test_legacy_baseline_without_identity_is_refused(monkeypatch, tmp_path, capsys):
    """Red on the knob-only comparison: a pre-identity folder from another commit was reused silently."""
    ev, started = _break_setup(monkeypatch, tmp_path)
    g = _green_folder(tmp_path)
    assert _break(monkeypatch, f"--baseline={g}") == 3
    out = capsys.readouterr().out
    assert "recorded before Run identity (no source_id): re-run without --baseline" in out
    assert started == [] and not list(ev.iterdir())


def _sources(monkeypatch, *ids):
    """identity.source_id returns these, in call order (then the last one again)."""
    seq = list(ids)
    monkeypatch.setattr(cli.identity, "source_id", lambda _root: seq.pop(0) if len(seq) > 1 else seq[0])


def _same_identity_folder(tmp_path, src="a" * 64, **over):
    h, names = cli.identity.env_id(os.environ)
    return _green_folder(tmp_path, **{"source_id": src, "source_id_end": src, "env_id": h, "env_names": names,
                                      **over})


def test_baseline_at_equal_identity_is_reused(monkeypatch, tmp_path, capsys):
    ev, started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, "a" * 64)
    g = _same_identity_folder(tmp_path)
    assert _break(monkeypatch, f"--baseline={g}") == 0
    out = capsys.readouterr().out
    assert "mutation CAUGHT" in out and f"baseline: {g.resolve()}" in out
    assert started == [BREAK_FAULT] and len(_runs(ev)) == 1  # the fault run only


@pytest.mark.parametrize("env,want", [
    ({"SLOP_IDENTITY_PROBE": "1"}, "added ['SLOP_IDENTITY_PROBE']"),
    ({"SLOP_GATE": "on"}, "env value changed (values are not stored)"),  # guard policy is identity
])
def test_baseline_from_other_env_is_refused(monkeypatch, tmp_path, capsys, env, want):
    ev, started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, "a" * 64)
    g = _same_identity_folder(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert _break(monkeypatch, f"--baseline={g}") == 3
    out = capsys.readouterr().out
    assert any(line.lstrip().startswith("inconclusive:") and want in line for line in out.splitlines()), out
    assert started == [] and not list(ev.iterdir())


def test_raced_baseline_is_refused(monkeypatch, tmp_path, capsys):
    ev, started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, "a" * 64)
    g = _same_identity_folder(tmp_path, source_id_end="b" * 64)
    assert _break(monkeypatch, f"--baseline={g}") == 3
    assert "source_id != source_id_end" in capsys.readouterr().out
    assert started == [] and not list(ev.iterdir())


@pytest.mark.parametrize("ids", [("a" * 64, "b" * 64, "b" * 64), ("a" * 64, "a" * 64, "b" * 64)])
def test_fault_run_on_other_source_than_the_baseline_is_inconclusive(monkeypatch, tmp_path, capsys, ids):
    """--baseline: identity check, then the fault run's start and end source (an edit at or during it)."""
    ev, started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, *ids)
    g = _same_identity_folder(tmp_path)
    assert _break(monkeypatch, f"--baseline={g}") == 3
    out = capsys.readouterr().out
    assert "inconclusive: raced" in out and "mutation INCONCLUSIVE" in out
    assert started == [BREAK_FAULT]


@pytest.mark.parametrize("ids,runs", [
    (("a" * 64, "a" * 64, "b" * 64, "b" * 64), [None, BREAK_FAULT]),  # edit between baseline and fault run
    (("a" * 64, "a" * 64, "a" * 64, "b" * 64), [None, BREAK_FAULT]),  # edit during the fault run
    (("a" * 64, "b" * 64), [None]),                                   # the baseline raced: no fault run
])
def test_break_without_baseline_catches_an_edit(monkeypatch, tmp_path, capsys, ids, runs):
    _ev, started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, *ids)
    assert _break(monkeypatch) == 3
    assert "inconclusive: raced" in capsys.readouterr().out
    assert started == runs


def test_break_without_baseline_on_one_source_is_caught(monkeypatch, tmp_path, capsys):
    _ev, started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, "a" * 64)
    assert _break(monkeypatch) == 0
    assert "mutation CAUGHT" in capsys.readouterr().out and started == [None, BREAK_FAULT]


def test_every_run_records_identity_names_never_values(monkeypatch, tmp_path):
    ev, _started = _break_setup(monkeypatch, tmp_path)
    _sources(monkeypatch, "a" * 64, "b" * 64)
    monkeypatch.setenv("SLOP_IDENTITY_SECRET", "s3cr3t-value")
    monkeypatch.setattr(sys, "argv", ["slop/run", "s"])
    assert cli.main() == 0
    (run,) = _runs(ev)
    text = (run / "metrics.json").read_text()
    p = json.loads(text)["params"]
    assert (p["source_id"], p["source_id_end"]) == ("a" * 64, "b" * 64)
    assert p["env_id"] and "SLOP_IDENTITY_SECRET" in p["env_names"] and "PATH" in p["env_names"]
    assert "s3cr3t-value" not in text and "s3cr3t-value" not in (run / "summary.txt").read_text()


@pytest.mark.parametrize("err", [subprocess.CalledProcessError(128, ["git"], stderr=b"fatal"),
                                 binascii.Error("Incorrect padding"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "x")])
def test_unreadable_source_warns_runs_and_is_refused_as_unreadable(monkeypatch, tmp_path, capsys, err):
    """A failed source read records null with one WARN line (never a crash before the stack); a later
    --baseline of that folder names the unreadable source, not a legacy folder."""
    ev, started = _break_setup(monkeypatch, tmp_path)

    def broken(_root):
        raise err
    monkeypatch.setattr(cli.identity, "source_id", broken)
    monkeypatch.setattr(sys, "argv", ["slop/run", "s"])
    assert cli.main() == 0 and started == [None]
    (run,) = _runs(ev)
    p = json.loads((run / "metrics.json").read_text())["params"]
    assert p["source_id"] is None and p["source_id_end"] is None
    out = capsys.readouterr().out
    assert out.count("slop: WARN source_id unreadable: ") == 2, out  # start and end

    _sources(monkeypatch, "a" * 64)
    assert _break(monkeypatch, f"--baseline={run}") == 3
    out = capsys.readouterr().out
    assert "its source could not be read" in out and "recorded before" not in out
    assert started == [None] and _runs(ev) == [run]


def test_p95_vs_last_green_compares_across_identities(monkeypatch, tmp_path, capsys):
    """`p95 within ... of the last green run` picks a green run of other source and env (same knobs and world)."""
    ev, _started = _break_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "EVIDENCE", ev)
    monkeypatch.setattr(cli, "load", lambda _p: SimpleNamespace(UI=False, P95_VS_LAST=(1.5, 50)))

    async def stack(name, mod, out, rep, rec, *_a):
        rep.metric("p95_vs_last_green", {"GET /x": 100})
    monkeypatch.setattr(cli, "_run_stack", stack)
    _sources(monkeypatch, "a" * 64)
    args = SimpleNamespace(scale="small", users=20, seed=1, profile=False, map=False, net=None)
    last = ev / "000-s-green"  # an earlier green run of scenario s
    last.mkdir()
    (last / "metrics.json").write_text(json.dumps({
        "params": {**cli._run_knobs("s", args, {}, False, 1, None), "git_sha": "old1234", "git_dirty": True,
                   "source_id": "b" * 64, "source_id_end": "b" * 64, "env_id": "other", "env_names": ["ELSEWHERE"]},
        "infra": None, "p95_vs_last_green": {"GET /x": 90}}))
    (last / "invariants.json").write_text(json.dumps([{"name": "x", "ok": True, "status": "pass"}]))
    monkeypatch.setattr(sys, "argv", ["slop/run", "s"])
    assert cli.main() == 0, capsys.readouterr().out
    run = next(d for d in _runs(ev) if d != last)
    (check,) = [c for c in json.loads((run / "invariants.json").read_text()) if c["name"].startswith("p95 within")]
    assert check["status"] == "pass" and check["last_green"] == "000-s-green", check


def test_estimates_still_match_across_identities(monkeypatch, tmp_path):
    """Identity facts are run facts, not knobs: --changed estimates compare across commits."""
    args = SimpleNamespace(scale="small", users=2, seed=1, no_ui=True, shards=None, profile=False, map=False, net=None)
    want = cli._run_knobs("s", args, {}, False, 1, None)
    other = {**want, "source_id": "b" * 64, "source_id_end": "c" * 64, "env_id": "x", "env_names": ["Y"]}
    path = tmp_path / "s.py"
    monkeypatch.setattr(cli, "load", lambda _p: SimpleNamespace(UI=False))
    monkeypatch.setattr(cli, "_green_runs", lambda _n: iter([(path, {"seconds": 40, "params": other})]))
    secs, source = cli._estimates(["s"], {"scenarios": {"s": {"seconds": 80}}}, args, {"s": path}, {})
    assert secs == {"s": 40} and source == "evidence"


# --- Run phases through the real run_one/_run_stack: a fake Stack below the stack runner, a controlled clock ---

class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def tick(self, s):
        self.t += s


def _phased(monkeypatch, tmp_path, run, *, enter=None, exit_=None, argv=("s",)):
    """`slop/run s` through cli.main() with the real run_one, _run_stack, Ctx and ProcMon; only the Stack class,
    the scenario module and the clock are fake. The fake Stack's start takes 5 s (its relay wait: 5 s, 6 polls),
    its exit 4 s; `enter(stack, clock)` runs inside its start, with the real Stack's partial-start cleanup on a
    raise, `exit_(stack, clock)` inside its exit before the temp dir goes. Returns (evidence dir, clock)."""
    ev, clock = tmp_path / "evidence", _Clock()
    ev.mkdir()
    monkeypatch.setattr(cli.phases, "now", clock)
    monkeypatch.setattr(cli, "scenarios", lambda: {"s": tmp_path / "s.py"})
    monkeypatch.setattr(cli, "load", lambda _p: SimpleNamespace(UI=False, run=run))

    def run_dir(name, tag):
        d = ev / f"{name}-{tag or 'run'}"
        (d / "screenshots").mkdir(parents=True)
        return d
    monkeypatch.setattr(cli, "run_dir", run_dir)
    monkeypatch.setattr(report, "EVIDENCE", ev)
    monkeypatch.setattr(cli, "_nice", lambda: None)
    monkeypatch.setattr(cli.netloss, "wire_off_stale", lambda: None)
    monkeypatch.setenv("SLOP_GATE", "off")

    class FakeStack:
        def __init__(self, **_kw):
            self.shards, self.relay, self.app, self.app_urls = 1, "http://127.0.0.1:9", None, {}
            self.relay_env, self.relay_pid, self.tmp = {0: {}}, 2 ** 22 + 7, tmp_path / "stack-tmp"
            self.db, self.sessions = self.tmp / "relay.db", self.tmp / "sessions"
            self.waits, self.teardown_s, self.sidecar_procs, self.extra_ports = [], None, {}, {}
            self.tmp.mkdir()

        def __enter__(self):
            try:
                clock.tick(5)
                self.waits.append({"name": "relay", "seconds": 5.0, "polls": 6})
                if enter:
                    enter(self, clock)
            except BaseException:
                self.__exit__(None, None, None)
                raise
            return self

        def __exit__(self, *_exc):
            clock.tick(4)
            if exit_:
                exit_(self, clock)
            self.teardown_s = 4.0
            shutil.rmtree(self.tmp, ignore_errors=True)
    monkeypatch.setattr(cli, "Stack", FakeStack)
    monkeypatch.setattr(sys, "argv", ["slop/run", *argv])
    return ev, clock


def _phases_of(ev):
    (run,) = _runs(ev)
    m = json.loads((run / "metrics.json").read_text())
    return run, m, m["run_phases"]


def _seed_profile(monkeypatch, clock, name, seconds, error=None):
    async def build(world):
        clock.tick(seconds)
        if error:
            raise error
        return world
    monkeypatch.setitem(sys.modules, f"slop.seed.profiles.{name}", SimpleNamespace(build=build))


def test_green_run_records_four_phases_that_sum_to_seconds(monkeypatch, tmp_path):
    async def run(ctx):
        clock.tick(1)
        await ctx.build("t2_fake")
        clock.tick(3)
        ctx.check("x", True)
    ev, clock = _phased(monkeypatch, tmp_path, run)
    _seed_profile(monkeypatch, clock, "t2_fake", 2)
    assert cli.main() == 0
    run_, m, ph = _phases_of(ev)
    assert ph == {"startup_s": 5.0, "seeding_s": 2.0, "execution_s": 4.0, "teardown_s": 4.0, "seed_calls": 1,
                  "seed_failed": 0, "waits": [{"name": "relay", "seconds": 5.0, "polls": 6}]}
    assert m["seconds"] == 15.0
    assert ("run phases: startup 5.0s · seeding 2.0s · execution 4.0s · teardown 4.0s; seeds 1 (0 failed); "
            "waits (s/polls): relay 5.0s/6; gate wait -") in (run_ / "summary.txt").read_text().splitlines()


def test_stack_that_fails_to_start_charges_startup_and_its_cleanup(monkeypatch, tmp_path):
    def enter(_stack, clock):
        clock.tick(2)
        raise SystemExit("slop: relay exited during startup")
    ev, _clock = _phased(monkeypatch, tmp_path, None, enter=enter)
    assert cli.main() == 3
    _run, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["teardown_s"], ph["seeding_s"], ph["execution_s"]) == (7.0, 4.0, None, None)
    assert ph["seed_calls"] == 0 and len(ph["waits"]) == 1 and m["seconds"] == 11.0
    assert "stack: slop: relay exited during startup" in m["infra"]
    assert ("run phases: startup 7.0s · seeding - · execution - · teardown 4.0s; seeds 0 (0 failed); "
            "waits (s/polls): relay 5.0s/6; gate wait -") in (_run / "summary.txt").read_text().splitlines()


def test_scenario_that_fails_to_load_records_every_phase_null(monkeypatch, tmp_path):
    ev, _clock = _phased(monkeypatch, tmp_path, None)

    def load(_p):
        raise ImportError("no such scenario module")
    monkeypatch.setattr(cli, "load", load)
    assert cli.main() == 3
    run_, _m, ph = _phases_of(ev)
    assert [ph[k] for k in ("startup_s", "seeding_s", "execution_s", "teardown_s")] == [None] * 4
    assert (ph["seed_calls"], ph["waits"]) == (0, [])
    assert ("run phases: startup - · seeding - · execution - · teardown -; seeds 0 (0 failed); waits (s/polls): -; "
            "gate wait -") in (run_ / "summary.txt").read_text().splitlines()


def test_overlapping_seeds_count_once_and_execution_excludes_them(monkeypatch, tmp_path):
    async def run(ctx):
        clock.tick(1)
        await asyncio.gather(ctx.build("t2_a"), ctx.build("t2_b"), return_exceptions=True)
        clock.tick(3)
        ctx.check("x", True)
    ev, clock = _phased(monkeypatch, tmp_path, run)

    async def build_a(world):  # seeds 0..4 s after the gather starts
        await asyncio.sleep(0)
        clock.tick(3)
        return world

    async def build_b(world):  # 1..6 s, raises: the union is 6 s, not 4 + 5
        clock.tick(1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        clock.tick(2)
        raise ValueError("seed broke")
    monkeypatch.setitem(sys.modules, "slop.seed.profiles.t2_a", SimpleNamespace(build=build_a))
    monkeypatch.setitem(sys.modules, "slop.seed.profiles.t2_b", SimpleNamespace(build=build_b))
    assert cli.main() == 0
    _run, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["seeding_s"], ph["execution_s"], ph["teardown_s"]) == (5.0, 6.0, 4.0, 4.0)
    assert (ph["seed_calls"], ph["seed_failed"], m["seconds"]) == (2, 1, 19.0)


def test_seed_cancelled_after_teardown_began_stays_in_teardown(monkeypatch, tmp_path):
    """A ctx.build still running when mod.run returns: asyncio.run cancels it after the stack's exit; its end must
    not reopen execution (the 2 s after it are teardown's)."""
    async def bg(ctx):
        try:
            await ctx.build("t2_hang")
        finally:
            clock.tick(2)

    async def run(ctx):
        clock.tick(1)
        tasks.append(asyncio.create_task(bg(ctx)))
        await asyncio.sleep(0)
    tasks: list = []
    ev, clock = _phased(monkeypatch, tmp_path, run)

    async def hang(_world):
        clock.tick(2)
        await asyncio.sleep(30)
    monkeypatch.setitem(sys.modules, "slop.seed.profiles.t2_hang", SimpleNamespace(build=hang))
    cli.main()
    _run, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["seeding_s"], ph["execution_s"], ph["teardown_s"]) == (5.0, 2.0, 1.0, 6.0)
    assert (ph["seed_calls"], ph["seed_failed"], m["seconds"]) == (1, 1, 14.0)


def test_raising_seed_profile_still_counts_as_seeding(monkeypatch, tmp_path):
    async def run(ctx):
        clock.tick(1)
        await ctx.build("t2_fake_bad")
    ev, clock = _phased(monkeypatch, tmp_path, run)
    _seed_profile(monkeypatch, clock, "t2_fake_bad", 3, ValueError("seed broke"))
    assert cli.main() == 3
    _run, m, ph = _phases_of(ev)
    assert (ph["seeding_s"], ph["seed_calls"], ph["seed_failed"]) == (3.0, 1, 1)
    assert (ph["startup_s"], ph["execution_s"], ph["teardown_s"], m["seconds"]) == (5.0, 1.0, 4.0, 13.0)
    assert "scenario crashed: ValueError: seed broke" in m["infra"]


def test_timed_out_run_records_phases_reached_and_teardown(monkeypatch, tmp_path):
    async def run(ctx):
        clock.tick(2)
        await asyncio.sleep(30)  # the real --timeout=1 alarm cuts it
    ev, clock = _phased(monkeypatch, tmp_path, run, argv=("s", "--timeout=1"))
    assert cli.main() == 3
    _run, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["seeding_s"], ph["execution_s"], ph["teardown_s"]) == (5.0, 0.0, 2.0, 4.0)
    assert m["seconds"] == 11.0 and "timed out after 1s" in m["infra"]


def test_sigtermed_run_records_phases_reached_and_teardown(monkeypatch, tmp_path):
    async def run(ctx):
        clock.tick(1)
        await ctx.build("t2_fake")
        clock.tick(2)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(30)
    ev, clock = _phased(monkeypatch, tmp_path, run)
    _seed_profile(monkeypatch, clock, "t2_fake", 2)
    assert cli.main() == 3
    run_, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["seeding_s"], ph["execution_s"], ph["teardown_s"]) == (5.0, 2.0, 3.0, 4.0)
    assert m["seconds"] == 14.0 and "signal SIGTERM; stack torn down" in m["infra"]
    assert "run phases: startup 5.0s · seeding 2.0s · execution 3.0s · teardown 4.0s" in (run_ / "summary.txt").read_text()


def test_sigterm_during_startup_charges_the_partial_cleanup_to_teardown(monkeypatch, tmp_path):
    def enter(_stack, clock):
        clock.tick(1)
        os.kill(os.getpid(), signal.SIGTERM)
    ev, _clock = _phased(monkeypatch, tmp_path, None, enter=enter)
    assert cli.main() == 3
    _run, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["seeding_s"], ph["execution_s"], ph["teardown_s"]) == (6.0, None, None, 4.0)
    assert m["seconds"] == 10.0 and "signal SIGTERM" in m["infra"]


def test_teardown_cut_short_by_timeout_is_finished_and_charged_to_teardown(monkeypatch, tmp_path):
    """--timeout lands inside the stack's exit; run_one finishes the teardown and its seconds stay teardown's."""
    def exit_(_stack, _clock):
        if not cut:
            cut.append(1)
            time.sleep(5)  # the real --timeout=1 alarm cuts it here

    async def run(ctx):
        clock.tick(2)
    cut: list = []
    ev, clock = _phased(monkeypatch, tmp_path, run, exit_=exit_, argv=("s", "--timeout=1"))
    assert cli.main() == 3
    _run, m, ph = _phases_of(ev)
    assert (ph["startup_s"], ph["seeding_s"], ph["execution_s"], ph["teardown_s"]) == (5.0, 0.0, 2.0, 8.0)
    assert m["seconds"] == 15.0 and "timed out after 1s" in m["infra"]


def test_relay_env_port_template():
    ports = {"BIO_PORT": 4100}
    assert cli._with_ports("http://127.0.0.1:{BIO_PORT}/x", ports) == "http://127.0.0.1:4100/x"
    assert cli._with_ports("0.5", ports) == "0.5"
    assert cli._with_ports("{OTHER}", ports) == "{OTHER}"
