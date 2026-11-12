"""lib/nightly.py tables. venv/bin/python -m pytest slop/lib/test_nightly.py"""
from __future__ import annotations

import argparse
import json

import pytest

from slop.lib import nightly as nt
from slop.lib import procs

NAMES = ["a-ui", "b-vol", "c-vol", "d-new", "2026-11-03-os-ping-push", "2026-11-01-notifications-feed-volume"]
DOC = {"scenarios": {"a-ui": {"sha": "x"}, "b-vol": {"sha": "x"}, "c-vol": {"sha": "x"},
                     "2026-11-03-os-ping-push": {"sha": "x"},
                     "2026-11-01-notifications-feed-volume": {"sha": "x"}}}


def test_volume_runs_medium_120_without_ui(tmp_path):
    assert nt.KNOBS["volume"] == ["--scale=medium", "--users=120", "--no-ui"]
    night = nt.Night(tmp_path, tee=False)
    calls = []

    def capture(argv, cwd, env):
        calls.append((argv, cwd, env))
        return 0, None, "", False, ""

    night.stream = capture
    assert night.run("volume", "example")["verdict"] == "OK"
    assert calls[0][0] == [str(nt.RUN), "example", "--scale=medium", "--users=120", "--no-ui"]


@pytest.mark.parametrize("ages,weekday,full,word", [
    ({}, 0, True, "no map entry"),
    ({"a" * 40: 201}, 0, True, "201 commits behind HEAD (> 200)"),
    ({"a" * 40: 500, "b" * 40: 1}, 0, True, "500 commits"),  # the oldest sha counts
    ({"a" * 40: 3, "b" * 40: None}, 0, True, "not ancestors of HEAD: bbbbbbb"),  # divergent/newer: stale
    ({"a" * 40: 0}, 6, True, "Sunday"),
    ({"a" * 40: 5}, 5, False, "not Sunday"),
])
def test_map_rule(ages, weekday, full, word):
    got, why = nt.map_rule(ages, weekday)
    assert got is full and word in why


@pytest.mark.parametrize("smoke,phases,ages,weekday,want", [
    (False, ["all", "volume", "map"], {"x": 3}, 1,  # volume first; day 0: the first 3 sorted volume names
     {"volume": ["2026-11-01-notifications-feed-volume", "2026-11-03-os-ping-push", "b-vol"], "all": NAMES,
      "map": ["d-new"]}),
    (False, ["map", "all"], {"x": 300}, 1, {"all": NAMES, "map": NAMES}),  # PHASES order, full refresh
    (True, ["all", "volume", "map"], {"x": 300}, 6,  # smoke: never the full map; a missing smoke name dropped
     {"volume": ["2026-11-01-notifications-feed-volume"], "all": ["2026-11-03-os-ping-push"], "map": ["d-new"]}),
])
def test_build_plan(smoke, phases, ages, weekday, want, monkeypatch):
    monkeypatch.setattr(nt.covmap, "is_volume", lambda p: p.stem in
                        {"b-vol", "c-vol", "2026-11-03-os-ping-push", "2026-11-01-notifications-feed-volume"})
    plan, why = nt.build_plan({n: nt.SLOP / "scenarios" / f"{n}.py" for n in NAMES}, DOC, phases, smoke, ages, weekday)
    assert plan == want and list(plan) == list(want)
    assert why.startswith("smoke") == smoke


@pytest.mark.parametrize("names,day,want", [
    (["d", "b", "a", "c", "e"], 0, ["a", "b", "c"]),
    (["d", "b", "a", "c", "e"], 1, ["d", "e", "a"]),  # wraps
    (["d", "b", "a", "c", "e"], 2, ["b", "c", "d"]),
    (["b", "a"], 9, ["a", "b"]),  # fewer than k: all
    ([], 5, []),
])
def test_volume_slice(names, day, want):
    assert nt.volume_slice(names, day, 3) == want


def test_volume_rotation_covers_all():
    names = [f"s{i:02d}" for i in range(54)]
    seen = {n for d in range(18) for n in nt.volume_slice(names, 739000 + d)}
    assert seen == set(names)


def C(status, budget=False, name=None):
    return {"name": name or f"c-{status}", "status": status, **({"budget": True} if budget else {})}


@pytest.mark.parametrize("code,checks,meta,map_run,tail,want", [
    (0, [C("pass")], {}, False, "", ("OK", [], None)),
    (0, None, None, False, "", ("OK", [], None)),  # the exit code decides, not the files
    (1, [C("pass"), C("fail")], {}, False, "", ("FAIL", ["c-fail"], None)),
    (1, [C("pass"), C("fail", budget=True)], {}, False, "", ("FAIL", ["c-fail"], None)),
    (1, [C("pass"), C("fail", budget=True)], {}, True, "", ("RED (coverage)", ["c-fail"], None)),
    (1, [C("fail", budget=True), C("fail")], {}, True, "", ("FAIL", ["c-fail", "c-fail"], None)),
    (1, [C("skip")], {}, False, "", ("SKIP", [], None)),
    (1, None, None, False, "ImportError: x", ("INFRA", [], "exit 1 without invariants.json: ImportError")),
    (1, [], {}, False, "", ("INFRA", [], "without invariants.json")),
    (3, [C("fail", name="stack started")], {"infra": "stack: boom"}, False, "", ("INFRA", ["stack started"], "stack: boom")),
    (3, None, None, False, "", ("INFRA", [], "slop/run exit 3")),
    (2, None, None, True, "slop: --map needs a clean tree", ("INFRA", [], "exit 2: slop: --map needs a clean tree")),
    (-9, None, None, False, "", ("INFRA", [], "slop/run exit -9")),
    (75, None, None, False, "INFRA: machine lock x still held after 7201s by pid 9 | gate: y",
     ("INFRA", [], "machine gate: exit 75: INFRA: machine lock")),  # no INFRA line seen: the tail
])
def test_verdict(code, checks, meta, map_run, tail, want):
    v, failed, infra = nt.verdict(code, checks, meta, map_run=map_run, tail=tail)
    assert (v, failed) == want[:2]
    assert (infra is None) if want[2] is None else want[2] in infra


@pytest.mark.parametrize("gate_line,want", [
    ("INFRA: machine lock /x still held after 7201s by pid 9 (SLOP_LOCK_WAIT_S)",
     "machine gate: machine lock /x still held after 7201s"),
    ("INFRA: thread guard tripped at 2026-11-06T01:00:00Z", "machine gate: thread guard tripped"),
])
def test_verdict_gate_exit_75(gate_line, want):
    v, failed, infra = nt.verdict(75, None, None, tail="last | lines", gate_line=gate_line)
    assert (v, failed) == ("INFRA", []) and infra.startswith(want)


@pytest.mark.parametrize("first,rerun,want", [
    ("FAIL", "OK", "FLAKY"), ("FAIL", "FAIL", "FAIL"), ("FAIL", "INFRA", "INFRA"), ("FAIL", "SKIP", "FAIL"),
    ("FAIL", None, "FAIL"), ("OK", None, "OK"), ("INFRA", None, "INFRA"),
])
def test_settle(first, rerun, want):
    assert nt.settle(first, rerun) == want


@pytest.mark.parametrize("again,verdict,folder,failed,infra", [
    (dict(verdict="OK", folder="F2", failed=[], infra=None, p95={"k": 2}), "FLAKY", "F2", ["x"], None),
    (dict(verdict="FAIL", folder="F2", failed=["y"], infra=None, p95={}), "FAIL", "F2", ["y"], None),
    (dict(verdict="INFRA", folder=None, failed=[], infra="slop/run exit -9", p95={}), "INFRA", None, ["x"],
     "slop/run exit -9"),  # died before a folder: '-' in the digest
])
def test_merge_rerun(again, verdict, folder, failed, infra):
    first = {"phase": "all", "scenario": "s", "verdict": "FAIL", "seconds": 10.0, "folder": "F1", "failed": ["x"],
             "infra": None, "p95": {"k": 1}, "exit": 1, "untimed": []}
    m = nt.merge_rerun(first, {**again, "seconds": 5.0, "untimed": []})
    assert (m["verdict"], m["folder"], m["rerun_folder"], m["failed"], m["infra"]) == (verdict, "F1", folder, failed, infra)
    assert m["first_verdict"] == "FAIL" and m["seconds"] == 15.0 and m["p95"] == (again["p95"] or {"k": 1})
    assert nt._folders(m) == f"F1 -> re-run {folder or '-'}"


@pytest.mark.parametrize("vs,code,word", [
    (["OK", "OK"], 0, "OK"), (["OK", "FLAKY", "SKIP"], 0, "OK"), (["OK", "FAIL", "FLAKY"], 1, "RED"),
    (["FAIL", "INFRA"], 3, "INFRA"), ([], 0, "OK"), (["OK", "RED (coverage)"], 0, "OK"),
    (["SKIP", "SKIP"], 3, "SKIPPED"),  # every check skipped everywhere: nothing proved, never OK
])
def test_exit_and_headline(vs, code, word):
    assert nt.exit_code(vs) == code
    assert nt.exit_code(vs, infra=True) == 3 and nt.headline("S", vs, infra=True).startswith("NIGHTLY INFRA")
    h = nt.headline("20261105T000000Z", vs)
    assert h.startswith(f"NIGHTLY {word} 20261105T000000Z: ")
    counts = h.split(": ")[1].split(" of ")[0].split("/")
    assert sum(map(int, counts)) == len(vs) and h.endswith(f" of {len(vs)}")


@pytest.mark.parametrize("cur,names,replaced,added,missing,keep", [
    ({"a": {"sha": "old"}, "z": {"sha": "z"}}, ["a", "b"], ["a"], ["b"], [], "z"),
    ({"z": {"sha": "z"}}, ["c"], [], [], ["c"], "z"),  # not in the folder's map.json: reported, nothing done
    ({}, [], [], [], [], None),
])
def test_merge_map(cur, names, replaced, added, missing, keep):
    got = {"scenarios": {"a": {"sha": "new"}, "b": {"sha": "new"}, "z": {"sha": "NOT-ASKED"}}, "version": 1}
    doc, r, a, m = nt.merge_map({"scenarios": cur, "version": 1}, got, names)
    assert (r, a, m) == (replaced, added, missing)
    assert all(doc["scenarios"][n] == {"sha": "new"} for n in r + a)
    if keep:
        assert doc["scenarios"][keep] == {"sha": "z"}  # entries not named stay as they were


def test_folder_line_round_trip(tmp_path):
    from slop.lib.report import FOLDER_LINE, parse_folder_line
    p = tmp_path / "20261105T000000Z-x-ab12"
    assert parse_folder_line(FOLDER_LINE.format(path=p)) == p
    assert parse_folder_line("slop: x scale=small -> /tmp/y") is None


def test_child_env_leaves_the_gate():
    env = {"PATH": "/bin", "SLOP_GATED": "1", "SLOP_GATE_PID": "9", "SLOP_GATE_WAIT_S": "3",
           "SLOP_GATE_LOAD": "2.0", "SLOP_LOCK_WAIT_S": "60"}
    assert nt.child_env(env) == {"PATH": "/bin", "SLOP_LOCK_WAIT_S": "7200", "SLOP_NIGHTLY": "1"}
    nt.scrub_gate_env(env)
    assert nt.child_env(env) == {"PATH": "/bin", "SLOP_LOCK_WAIT_S": "7200", "SLOP_NIGHTLY": "1"}
    assert "SLOP_GATED" not in env


def test_child_env_drops_every_gate_var():
    """R5-9: every SLOP_GATE*, not 4 names: an exclusive or ungated parent's flag never reaches the children
    (red before: SLOP_GATE_EXCLUSIVE made every child gate exclusive)."""
    env = {"PATH": "/bin", "SLOP_GATE": "off", "SLOP_GATE_EXCLUSIVE": "1", "SLOP_GATE_LATER": "x", "SLOP_GATED": "1"}
    assert nt.child_env(env) == {"PATH": "/bin", "SLOP_LOCK_WAIT_S": "7200", "SLOP_NIGHTLY": "1"}
    assert nt.scrub_gate_env(env) and env == {"PATH": "/bin"}


@pytest.mark.parametrize("env,had,left", [
    ({"PATH": "/bin"}, False, {"PATH": "/bin"}),
    ({"PATH": "/bin", "SLOP_GATED": "1", "SLOP_GATE_PID": "1"}, True, {"PATH": "/bin"}),  # pid 1: live, reused
    ({"SLOP_GATED": "1", "SLOP_GATE_PID": "abc"}, True, {}),  # non-numeric pid
    ({"SLOP_GATE_PID": "9", "SLOP_GATE_WAIT_S": "3", "SLOP_GATE_LOAD": "2"}, True, {}),
])
def test_scrub_gate_env(env, had, left):
    assert nt.scrub_gate_env(env) is had and env == left


@pytest.mark.parametrize("phases,smoke,want", [
    ("all,volume,map", False, ["--phases=all,volume,map", "--folder=/e/N"]),
    ("volume", True, ["--phases=volume", "--smoke", "--folder=/e/N"]),
])
def test_child_argv_from_parsed_options(phases, smoke, want):
    args = argparse.Namespace(phases=phases, smoke=smoke, detach=True, dry=False, apply_map=None, folder=None)
    assert nt.child_argv(args, nt.Path("/e/N")) == want


@pytest.mark.parametrize("argv", [["--det"], ["--detac"], ["--sm"], ["--phase=volume"]])
def test_no_abbreviations(argv, capsys):
    with pytest.raises(SystemExit) as e:
        nt.main(argv, {})
    assert e.value.code == 2 and "unrecognized arguments" in capsys.readouterr().err


def test_stream_timeout_kills_a_child_in_its_own_session(tmp_path):
    """As gate.py run: the workload sits in a session of its own, holding the pipe; the timeout reaps it too."""
    inner = "import subprocess, time; subprocess.Popen(['sh', '-c', 'echo $$; exec sleep 60'], start_new_session=True); time.sleep(60)"
    n = nt.Night(tmp_path, tee=True)
    t0 = nt.time.time()
    code, _, tail, killed, _ = n.stream([nt.sys.executable, "-c", inner], tmp_path, timeout=3)
    assert killed and code < 0 and nt.time.time() - t0 < 20
    assert not procs.exists(int(tail))


def R(phase, name, v, p95=None, **kw):
    r = {"phase": phase, "scenario": name, "verdict": v, "p95": p95 or {}, "seconds": 1.0, "folder": f"F-{name}",
         "failed": [], "infra": None, "run_phases": None, **kw}
    return {"untimed": [] if r["run_phases"] else [r["seconds"]], **r}  # as row_of: no run phases = untimed


def test_changes():
    prev = [R("all", "a", "OK", {"GET /x": 100}), R("all", "b", "FAIL"), R("volume", "c", "OK", {"k": 10})]
    now = [R("all", "a", "FAIL", {"GET /x": 125}), R("all", "b", "FLAKY"), R("volume", "c", "OK", {"k": 11}),
           R("volume", "new", "FAIL"), R("all", "infra-new", "INFRA")]
    c = nt.changes(now, prev)
    assert c["newly_red"] == ["all a", "volume new"] and c["newly_green"] == ["all b"]
    assert c["newly_infra"] == ["all infra-new"]
    assert c["p95"] == ["all a GET /x: 100 -> 125 ms (+25%)"]  # c: +10% stays out
    assert nt.changes(now, None)["first"] is True


def _folder(root, name, meta, checks):
    d = root / name
    d.mkdir()
    (d / "metrics.json").write_text(json.dumps(meta))
    (d / "invariants.json").write_text(json.dumps(checks))
    return d


def test_digest_from_fake_folders(tmp_path):
    ok = _folder(tmp_path, "T1-a-ok", {"p95_vs_last_green": {"GET /x": 9}, "params": {"lock_wait_s": 7.2}}, [C("pass")])
    bad = _folder(tmp_path, "T2-b-bad", {}, [C("pass"), C("fail", name="nothing dropped")])
    inf = _folder(tmp_path, "T3-c-inf", {"infra": "stack: port taken"}, [C("fail", name="stack started")])
    rows = [nt.row_of("all", "a", ok, 12.3, 0), nt.row_of("all", "b", bad, 20, 1),
            nt.row_of("volume", "c", inf, 5, 3), nt.row_of("map", "d", None, 1, 2, "slop: --map needs a clean tree")]
    assert [r["verdict"] for r in rows] == ["OK", "FAIL", "INFRA", "INFRA"]
    assert rows[0]["p95"] == {"GET /x": 9} and "slop/run exit 2: slop: --map needs" in rows[3]["infra"]
    vs = [r["verdict"] for r in rows]
    s = {"headline": nt.headline("S", vs), "sha": "abc1234", "smoke": True, "started": "t0", "ended": "t1",
         "load_start": 1.0, "load_end": 2.0, "cores": 16, "rows": rows,
         "phases": {"all": {"wall_s": 32}, "volume": {"wall_s": 5}, "map": {"wall_s": 1}},
         "changes": nt.changes(rows, None), "prev": None,
         "map": {"rule": "smoke: unmapped only", "mapped": [], "unmapped_left": ["d"], "restored": "restored"}}
    md = nt.digest(s)
    assert md.splitlines()[0] == "NIGHTLY INFRA S: 1/0/1/2/0 of 4"
    assert "| b | FAIL | 20 | T2-b-bad | nothing dropped |" in md
    assert "infra: stack: port taken" in md and "latest" not in md
    assert "- unmapped left: d" in md
    assert "gate wait: 7s total, max 7s (a)" in md


def test_digest_green_night_is_short():
    rows = [R("all", f"s{i}", "OK") for i in range(60)] + [R("volume", f"v{i}", "OK") for i in range(40)]
    s = {"headline": nt.headline("S", ["OK"] * 100), "sha": "a", "smoke": False, "started": "", "ended": "",
         "load_start": 0.0, "load_end": 0.0, "cores": 1, "rows": rows,
         "phases": {"all": {"wall_s": 1}, "volume": {"wall_s": 1}}, "changes": nt.changes(rows, rows), "prev": "P",
         "map": {"rule": "r", "mapped": ["x", "y"], "unmapped_left": [], "restored": "restored"}}
    md = nt.digest(s)
    assert len(md.splitlines()) <= 60 and "60 OK rows not listed" in md


def test_digest_invalid_map_has_no_refresh_or_unmapped_list():
    s = {"headline": "NIGHTLY INFRA S", "sha": "abc", "smoke": False,
         "started": "", "ended": "", "load_start": 0.0, "load_end": 0.0,
         "cores": 1, "rows": [], "phases": {}, "changes": {"first": True},
         "map": {"rule": "refresh", "mapped": ["a"], "unmapped_left": ["b"],
                 "restored": "restored", "map_error": "invalid JSON"}}
    md = nt.digest(s)
    assert "- INFRA: invalid JSON" in md
    assert "- entries refreshed: n/a" in md
    assert "unmapped left" not in md
    assert "ship:" not in md


def test_dry_invalid_map_is_one_line_infra(tmp_path, monkeypatch, capsys):
    bad_map = tmp_path / "map.json"
    bad_map.write_text("{invalid")
    monkeypatch.setattr(nt.covmap, "MAP", bad_map)
    monkeypatch.setattr(nt, "scrub_gate_env", lambda _env: False)
    monkeypatch.setattr(nt.gate, "nice10", lambda: None)

    assert nt.main(["--dry"], {}) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    lines = captured.err.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("slop: INFRA slop/map.json invalid: Expecting property name")
    assert lines[0].endswith("(restore: git checkout slop/map.json, or slop/run all --map)")


def test_prev_same_phases_and_smoke_earlier_only(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "EVIDENCE", tmp_path)
    def night(name, smoke, phases, done=True):
        d = tmp_path / name
        d.mkdir()
        if done:
            (d / "done").write_text("0\n")
        (d / "summary.json").write_text(json.dumps({"rows": [], "smoke": smoke, "phase_names": phases}))
    night("20261101T000000Z-nightly-aaaa", False, ["all", "volume", "map"])
    night("20261102T000000Z-nightly-bbbb", True, ["all", "volume", "map"])  # smoke: not a full night's prev
    night("20261103T000000Z-nightly-cccc", False, ["all"])  # other phases
    night("20261109T000000Z-nightly-dddd", False, ["all", "volume", "map"])  # later: never a prev
    night("20261104T000000Z-nightly-ffff", False, ["all", "volume", "map"], done=False)  # unfinished: never
    out = tmp_path / "20261105T000000Z-nightly-eeee"
    assert nt._prev(out, False, ["all", "volume", "map"])[0] == "20261101T000000Z-nightly-aaaa"
    assert nt._prev(out, True, ["all", "volume", "map"])[0] == "20261102T000000Z-nightly-bbbb"


def test_stream_timeout_kills_and_logs(tmp_path):
    n = nt.Night(tmp_path, tee=True)
    code, folder, tail, killed, _ = n.stream(["sh", "-c", "echo started; sleep 30"], tmp_path, timeout=0.5)
    assert killed and code < 0 and tail == "started" and folder is None and n.proc is None
    assert "started" in (tmp_path / "run.log").read_text()
    assert n.stream(["sh", "-c", "echo slop: folder /x/y; exit 2"], tmp_path, timeout=5)[:2] == (2, nt.Path("/x/y"))


def test_app_deps_install_runs_in_the_gate(tmp_path, monkeypatch):
    """pnpm install goes through `gate.py run --`, env without SLOP_GATE*; gate exit 75 = INFRA preflight."""
    gate = tmp_path / "gate.py"
    gate.write_text('import os, sys\nprint("argv", *sys.argv[1:], "gated", os.environ.get("SLOP_GATED"), '
                    '"wait", os.environ.get("SLOP_LOCK_WAIT_S"))\nprint("INFRA: no slot free after 7200s", '
                    'file=sys.stderr)\nsys.exit(75)\n')
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "pnpm-lock.yaml").write_text("lock\n")
    monkeypatch.setattr(nt, "GATE_PY", gate)
    monkeypatch.setattr(nt, "APP", tmp_path / "app")
    monkeypatch.setenv("SLOP_GATED", "stale")
    n = nt.Night(tmp_path, tee=True)
    assert n.install_app_deps("app/node_modules missing") == "pnpm install preflight: machine gate: no slot free after 7200s"
    log = (tmp_path / "run.log").read_text()
    assert "argv run -- pnpm install --frozen-lockfile gated None wait 7200" in log


def test_app_deps_install_timeout_includes_gate_wait(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(nt, "APP", tmp_path / "app")
    night = nt.Night(tmp_path, tee=False)
    seen = []
    def timed_out(argv, cwd, *, env, timeout):
        seen.append(timeout)
        return -9, None, "", True, ""
    monkeypatch.setattr(night, "stream", timed_out)
    err = night.install_app_deps("missing")
    assert seen == [nt.INSTALL_DEADLINE_S]
    assert f"timed out after {nt.INSTALL_DEADLINE_S}s" in err
    assert "gate wait 7200s" in err


def test_apply_map_invalid_current_map_is_infra(tmp_path, monkeypatch):
    import json
    d = tmp_path / "night"
    d.mkdir()
    (d / "summary.json").write_text(json.dumps({"map": {"mapped": ["a"]}}))
    (d / "map.json").write_text(json.dumps({"scenarios": {"a": {"sha": "x"}}}))
    current = tmp_path / "map.json"
    current.write_text("{")
    monkeypatch.setattr(nt.covmap, "MAP", current)
    assert nt.apply_map(str(d)) == 3


def test_invalid_map_phase_keeps_rows_and_reports_infra(tmp_path, monkeypatch):
    map_file = tmp_path / "map.json"
    map_file.write_text("{")
    night_out = tmp_path / "night"
    night_out.mkdir()
    monkeypatch.setattr(nt.covmap, "MAP", map_file)
    calls = iter([{"scenarios": {}}, nt.covmap.MapInvalid("invalid JSON")])
    def load():
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(nt.covmap, "load_map", load)
    monkeypatch.setattr(nt.covmap, "git", lambda *a: "")
    class Night:
        out = night_out
        status = {"done": 0}
        def mark(self, **kw):
            pass
        def run(self, phase, name):
            return R(phase, name, "OK")
        def stop_child(self):
            pass
        def say(self, *lines):
            pass
    rows, result = nt._map_phase(Night(), ["a"], "refresh", ["a"])
    assert rows[0]["verdict"] == "INFRA"
    assert "invalid JSON" in rows[0]["infra"]
    assert result["map_error"] == rows[0]["infra"]
    assert result["mapped"] == [] and result["unmapped_left"] == []
    assert (night_out / "map.json").read_text() == "{"


def _ph(startup, seeding, execution, teardown, calls=1, failed=0, waits=()):
    return {"startup_s": startup, "seeding_s": seeding, "execution_s": execution, "teardown_s": teardown,
            "seed_calls": calls, "seed_failed": failed, "waits": list(waits)}


def test_merge_rerun_sums_both_attempts_gate_wait_and_run_phases():
    """Red on the first-attempt-only merge: a FAIL's re-run gate wait and phases were dropped (2 + 3 -> 2)."""
    first = {"phase": "all", "scenario": "s", "verdict": "FAIL", "seconds": 10.0, "folder": "F1", "failed": ["x"],
             "infra": None, "p95": {}, "exit": 1, "gate_wait_s": 2.0, "untimed": [],
             "run_phases": _ph(1.0, 2.0, 3.0, 4.0, waits=[{"name": "relay", "seconds": 1.0, "polls": 2}])}
    again = {**first, "verdict": "OK", "seconds": 20.0, "folder": "F2", "failed": [], "gate_wait_s": 3.0,
             "run_phases": _ph(10.0, 20.0, 30.0, 40.0, calls=2, failed=1,
                               waits=[{"name": "relay", "seconds": 3.0, "polls": 4}])}
    m = nt.merge_rerun(first, again)
    assert m["seconds"] == 30.0 and m["gate_wait_s"] == 5.0
    assert m["run_phases"] == _ph(11.0, 22.0, 33.0, 44.0, calls=3, failed=1,
                                  waits=[{"name": "relay", "seconds": 1.0, "polls": 2},
                                         {"name": "relay", "seconds": 3.0, "polls": 4}])


@pytest.mark.parametrize("a,b,want,untimed", [
    (None, None, None, [1.0, 2.0]),  # neither attempt reached a folder with phases
    (_ph(1.0, None, None, 0.5, calls=0), None, _ph(1.0, None, None, 0.5, calls=0), [2.0]),  # re-run died early
    (_ph(1.0, None, None, 0.5, calls=0), _ph(2.0, 3.0, 4.0, 5.0), _ph(3.0, 3.0, 4.0, 5.5), []),  # null + n = n
])
def test_merge_rerun_phases_with_missing_attempts(a, b, want, untimed):
    """A partial merge (one attempt untimed) keeps that attempt's wall seconds apart, not inside the phases."""
    first = {"verdict": "FAIL", "seconds": 1.0, "folder": "F1", "failed": ["x"], "infra": None, "p95": {},
             "gate_wait_s": None, "run_phases": a, "untimed": [] if a else [1.0]}
    m = nt.merge_rerun(first, {**first, "verdict": "INFRA", "folder": None, "seconds": 2.0, "gate_wait_s": 4.0,
                               "run_phases": b, "untimed": [] if b else [2.0]})
    assert m["run_phases"] == want and m["gate_wait_s"] == 4.0 and m["untimed"] == untimed and m["seconds"] == 3.0


def test_row_of_copies_run_phases_and_gate_wait(tmp_path):
    ph = _ph(1.5, 0.5, 2.0, 1.0, waits=[{"name": "relay", "seconds": 1.2, "polls": 2}])
    d = _folder(tmp_path, "T-a", {"params": {"lock_wait_s": 4.5}, "run_phases": ph}, [C("pass")])
    r = nt.row_of("all", "a", d, 9.0, 0)
    assert r["run_phases"] == ph and r["gate_wait_s"] == 4.5 and r["untimed"] == []
    none = nt.row_of("all", "a", None, 61.0, 75)  # e.g. a gate exit 75 after a long slot wait: no folder
    assert none["run_phases"] is None and none["untimed"] == [61.0]
    nulls = _folder(tmp_path, "T-b", {"run_phases": _ph(None, None, None, None, calls=0)}, [C("pass")])
    assert nt.row_of("all", "b", nulls, 3.0, 3)["untimed"] == [3.0]  # never reached a stack: phases cover nothing


def test_digest_totals_timed_attempts_and_lists_untimed_apart(tmp_path):
    """A timed FAIL whose re-run died untimed, a timed OK, an untimed INFRA with seconds: the share's denominator is
    the timed attempts' measured run seconds; untimed attempts and gate wait are shown apart."""
    first = {**R("all", "f", "FAIL"), "seconds": 40.0, "gate_wait_s": 2.0, "run_phases": _ph(10.0, 2.0, 20.0, 5.0),
             "untimed": []}
    again = {**R("all", "f", "INFRA", seconds=30.0), "folder": None, "gate_wait_s": None}
    ok = {**R("all", "o", "OK"), "seconds": 100.0, "gate_wait_s": 3.0, "run_phases": _ph(30.0, 4.0, 50.0, 10.0),
          "untimed": []}
    rows = [nt.merge_rerun(first, again), ok, {**R("volume", "i", "INFRA", seconds=25.0), "gate_wait_s": None}]
    s = {"headline": "H", "sha": "a", "smoke": False, "started": "", "ended": "", "load_start": 0.0,
         "load_end": 0.0, "cores": 1, "rows": rows, "phases": {"all": {"wall_s": 1}, "volume": {"wall_s": 1}},
         "changes": nt.changes(rows, None), "prev": None}
    md = nt.digest(s)
    # 4 attempts (f, its re-run, o, i), 2 timed; startup 10+30, seeding 2+4, execution 20+50, teardown 5+10;
    # share 6 / 131 s = 4.6 %; untimed f's re-run 30 s + i 25 s; gate 2 + 3
    assert ("run phases (2 of 4 attempts timed): startup 40s · seeding 6s · execution 70s · teardown 15s; seeding "
            "4.6% of 131s measured run seconds; untimed 2 attempts, 55s wall (no run phases); gate wait 5s"
            ) in md.splitlines(), md


def test_prev_rotated_volume_rows(tmp_path, monkeypatch):
    """Each rotated volume scenario's baseline is its own last nightly, not just the newest one."""
    monkeypatch.setattr(nt, "EVIDENCE", tmp_path)

    def night(stamp, rows, phases=("volume", "all", "map")):
        d = tmp_path / f"{stamp}-nightly-ab"
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({"rows": rows, "smoke": False, "phase_names": list(phases)}))
        (d / "done").write_text("")

    night("20261110T0100Z", [R("volume", "v1", "FAIL"), R("all", "a", "FAIL")], ("all", "volume", "map"))
    night("20261111T0100Z", [R("volume", "v2", "OK"), R("all", "a", "OK")])
    name, rows = nt._prev(tmp_path / "20261112T0100Z-nightly-ab", False, ["volume", "all", "map"])
    assert name == "20261111T0100Z-nightly-ab"
    assert {(r["phase"], r["scenario"], r["verdict"]) for r in rows} == {
        ("volume", "v2", "OK"), ("all", "a", "OK"), ("volume", "v1", "FAIL")}  # old `all` row not merged
    c = nt.changes([R("volume", "v1", "FAIL"), R("volume", "v2", "OK")], rows)
    assert c["newly_red"] == []  # v1 was already red on its last night
    assert nt._prev(tmp_path / "20261110T0000Z-nightly-ab", False, ["volume", "all", "map"]) == (None, None)
