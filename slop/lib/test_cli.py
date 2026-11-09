import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop.lib import cli, covmap, report


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
