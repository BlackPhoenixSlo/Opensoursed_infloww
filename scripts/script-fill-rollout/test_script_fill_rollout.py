"""Rollout driver, describe side (Phase 3a). The fill side (3b) is test_script_fill_rollout_fill.py.

Seam 1: `rollout_decide` tables (spec docs/spec/phase-03-rollout-to-every-creator.md, Testing Decisions).
Driver: `rollout.py` run in-process (and once as a killed subprocess) against the in-process fake relay of
fake_relay.py (fixtures in conftest.py), standing in for the slop scenario's real relay until the slop-runner runs
`script-fill-rollout`.

Run: venv/bin/python -m pytest scripts/script-fill-rollout -q
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import rollout
import rollout_core as core
import rollout_decide as rd
from fake_relay import BASE, ITEM_MC_REAL, SESSION, Cr, Fake, journal, kinds, run

HERE = Path(__file__).resolve().parent


# ── Seam 1: rollout_decide tables ───────────────────────────────────────────


@pytest.mark.parametrize("acct,want", [
    (BASE, (True, None)),
    ({**BASE, "role": "watcher"}, (False, "watcher")),
    ({**BASE, "platform": "fansly"}, (False, "not_onlyfans")),
    ({**BASE, "has_session": False}, (False, "no_session")),
    ({**BASE, "session_dead_at": "2026-11-20T10:00:00"}, (False, "dead_session")),
    ({**BASE, "is_active": False}, (False, "deactivated")),
    # first reason wins
    ({**BASE, "platform": "fansly", "has_session": False}, (False, "not_onlyfans")),
    ({**BASE, "session_dead_at": "x", "is_active": False}, (False, "dead_session")),
])
def test_eligible_reasons(acct, want):
    assert rd.eligible(acct) == want


def test_roster_splits_accounts_and_watchers_in_order():
    payload = {"accounts": [{**BASE, "id": "a"}, {**BASE, "id": "b", "is_active": False}, {**BASE, "id": "c"}],
               "watchers": [{**BASE, "id": "w"}]}
    ok, skipped = rd.roster(payload)
    assert [a["id"] for a in ok] == ["a", "c"]
    assert [(a["id"], why) for a, why in skipped] == [("b", "deactivated"), ("w", "watcher")]


@pytest.mark.parametrize("described,goal,want", [
    (0, 1000, 250), (1, 1000, 250), (249, 1000, 250), (250, 1000, 500), (344, 1000, 500),
    (999, 1000, 1000), (1000, 1000, 1000), (1200, 1000, 1000),
    (0, 300, 250), (250, 300, 300), (299, 300, 300), (300, 300, 300), (0, 120, 120), (0, 0, 0),
])
def test_next_target(described, goal, want):
    assert rd.next_target(described, goal) == want


B = {"described": 250, "target": 500, "goal": 1000, "complete": True, "jev": {"ready": True}, "zero_sweeps": 0}


@pytest.mark.parametrize("name,before,after,progress,cap,want", [
    ("cap 429 at start", B, None, {"http": 429}, {}, "defer"),
    ("key 424 at start", B, None, {"http": 424}, {}, "open:key"),
    ("pre: capped", B, None, None, {"capped": True}, "defer"),
    ("pre: key missing", B, None, None, {"key_missing": True}, "open:key"),
    ("pre: Jev not ready", {**B, "jev": {"ready": False}}, None, None, {}, "open:jev_not_ready"),
    ("pre: at goal", {**B, "described": 1000}, None, None, {"capped": True}, "done"),
    ("pre: ready", B, None, None, {"capped": False}, "continue"),
    ("pre: empty incomplete mirror", {**B, "described": 0, "goal": 0, "complete": False}, None, None, {},
     "open:mirror_incomplete"),
    ("progress capped", B, {"described": 400}, {"capped": True}, {}, "defer"),
    ("jev_capped short of slice", B, {"described": 400}, {"error": "no Jev reading (jev_capped)"}, {}, "defer"),
    ("jev_capped but slice reached", B, {"described": 500}, {"error": "no Jev reading (jev_capped)"}, {},
     "continue"),
    ("key_error mid-sweep", B, {"described": 260}, {"key_error": {"message": "x"}}, {}, "open:key"),
    ("reached slice", B, {"described": 500}, {}, {}, "continue"),
    ("reached goal", {**B, "described": 750, "target": 1000}, {"described": 1000}, {}, {}, "done"),
    ("goal below 1000, complete", {**B, "goal": 300, "target": 300}, {"described": 300, "goal": 300}, {}, {},
     "done"),
    ("goal below 1000, page-capped", {**B, "goal": 300, "target": 300, "complete": False},
     {"described": 300, "goal": 300}, {}, {}, "open:mirror_incomplete"),
    ("page-capped but 1000 reached", {**B, "described": 750, "target": 1000, "complete": False},
     {"described": 1000}, {}, {}, "done"),
    ("one zero-progress sweep", B, {"described": 250}, {"error": "boom"}, {}, "continue"),
    ("two zero-progress sweeps", {**B, "zero_sweeps": 1}, {"described": 250}, {"stop": {"message": "x"}}, {},
     "open:no_progress"),
])
def test_sweep_outcome(name, before, after, progress, cap, want):
    assert rd.sweep_outcome(before, after, progress, cap) == want, name


@pytest.mark.parametrize("cb,ca,want", [
    ({"day": "2026-11-20", "spent_millicents": 1000, "cap_millicents": 10000},
     {"day": "2026-11-20", "spent_millicents": 3500}, 2500),
    ({"day": "2026-11-20", "spent_millicents": 9000, "cap_millicents": 10000},
     {"day": "2026-11-21", "spent_millicents": 1500}, 2500),          # across 00:00 UTC: 1500 + (10000 - 9000)
    ({"day": "2026-11-20", "spent_millicents": 10500, "cap_millicents": 10000},
     {"day": "2026-11-21", "spent_millicents": 700}, 700),            # old day already past its cap
    ({"day": "2026-11-20", "spent_millicents": 3000}, {"day": "2026-11-20", "spent_millicents": 3000}, 0),
])
def test_sweep_spend(cb, ca, want):
    assert rd.sweep_spend(cb, ca) == want


def test_run_spend_over_days():
    lines = [
        {"kind": "sweep", "cap_before": {"day": "d1", "spent_millicents": 0}, "cap_after": {"day": "d1",
                                                                                          "spent_millicents": 4000}},
        {"kind": "sweep", "cap_before": {"day": "d1", "spent_millicents": 9000, "cap_millicents": 10000},
         "cap_after": {"day": "d2", "spent_millicents": 2000}},
        {"kind": "sweep_start", "cap_before": {"day": "d2", "spent_millicents": 0}},
        {"kind": "sweep", "cap_before": {"day": "d3", "spent_millicents": 100}, "cap_after": {"day": "d3",
                                                                                            "spent_millicents": 600}},
    ]
    assert rd.run_spend(lines) == 4000 + 3000 + 500


@pytest.mark.parametrize("spent,running,want", [
    # ceiling 20000 mc, 250 x 20 mc = 5000 per sweep reserved
    (0, 0, True), (15000, 0, True), (15001, 0, False),
    (10000, 1, True), (10001, 1, False),
    (5000, 2, True), (5001, 2, False), (0, 2, True),
])
def test_may_sweep(spent, running, want):
    assert rd.may_sweep(spent, running, 20000, 250, 20) is want


@pytest.mark.parametrize("window,want", [
    ({}, None),
    ({"livez": {"status": 200, "seconds": 0.1}}, None),
    ({"livez": {"status": 200, "seconds": 2.0}}, None),
    ({"livez": {"status": 200, "seconds": 2.01}}, "livez_slow"),
    ({"livez": {"status": 503, "seconds": 0.1}}, "livez_down"),
    ({"livez": {"status": 0, "seconds": 5}}, "livez_down"),
    ({"errors_in_a_row": 2}, None),
    ({"errors_in_a_row": 3}, "errors"),
    ({"stops": [["a", "Stopped: # items in a row failed."], ["b", "Stopped: # items in a row failed."]]},
     "same_error"),
    ({"stops": [["a", "TimeoutError"], ["b", "ValueError"]]}, None),
    ({"stops": [["a", "TimeoutError"], ["b", None], ["c", "TimeoutError"]]}, None),
    ({"stops": [["a", "TimeoutError"], ["a", "TimeoutError"]]}, None),    # one Creator twice is not two
    ({"stops": [["a", "TimeoutError"]]}, None),
    ({"jev": [["a", False], ["b", False]]}, "jev"),
    ({"jev": [["a", False], ["b", True]]}, None),
    ({"jev": [["a", False]]}, None),
])
def test_pause_reason(window, want):
    assert rd.pause_reason(window) == want


@pytest.mark.parametrize("status,want", [(0, "retry"), (500, "retry"), (503, "retry"), (403, "open"),
                                         (404, "open"), (302, "open"), (400, "open")])
def test_retry_class(status, want):
    assert rd.retry_class(status) == want


def test_before_of_reads_summary_and_plan():
    plan = {"coverage": {"described": 120, "goal": 590}, "jev": {"ready": False, "reason": "NudeNet missing"}}
    assert rd.before_of({"complete": True}, plan, 1) == {
        "described": 120, "goal": 590, "complete": True, "jev": {"ready": False, "reason": "NudeNet missing"},
        "zero_sweeps": 1}
    assert rd.before_of({}, {"coverage": {}})["complete"] is False


@pytest.mark.parametrize("journal_state,before,want", [
    ({"state": "open", "reason": "key"}, {"described": 1000, "goal": 1000}, "open: key"),
    ({"state": "deferred", "until": 86400.0}, None, "open: deferred until 1970-01-02T00:00:00Z"),
    ({"state": "running"}, None, "running"),
    ({"state": "pending"}, None, "unreadable"),
    ({"state": "done"}, {"described": 300, "goal": 300, "complete": True}, "done"),
    ({"state": "pending"}, {"described": 300, "goal": 300, "complete": False}, "open: mirror_incomplete"),
    ({"state": "pending"}, {"described": 1000, "goal": 1000, "complete": False}, "done"),
    ({"state": "pending"}, {"described": 250, "goal": 600, "complete": True}, "pending"),
])
def test_report_state(journal_state, before, want):
    assert rd.report_state(journal_state, before) == want


def test_error_class_only_for_stopped_sweeps():
    assert rd.error_class({"error": "no frames (gone)"}) is None
    assert rd.error_class({"stop": {"message": "Stopped: 50 items in a row failed."},
                           "error": "Stopped: 50 items in a row failed."}) == "Stopped: # items in a row failed."
    assert rd.error_class({"aborted": True, "error": "RuntimeError: x 12"}) == "RuntimeError"


def test_throughput_counts_overlap_once():
    lines = [
        {"kind": "sweep", "creator": "a", "before": 0, "after": 100, "started": 0, "ended": 600},
        {"kind": "sweep", "creator": "b", "before": 250, "after": 450, "started": 300, "ended": 900},
        {"kind": "sweep_start", "creator": "c", "started": 0},
    ]
    tp = rd.throughput(lines)
    assert tp["creators"] == {"a": 10.0, "b": 20.0}
    assert tp["run"] == 20.0          # 300 items over the 15-minute union, not 20 summed minutes
    lines.append({"kind": "sweep", "creator": "a", "before": 100, "after": 130, "started": 1200, "ended": 1260})
    tp = rd.throughput(lines)
    assert tp["creators"]["a"] == round(130 / 11, 2)
    assert tp["run"] == round(330 / 16, 2)


def _ln(kind, creator=None, **kw):
    return {"t": "2026-11-21T00:00:00Z", "mode": "describe", "kind": kind, "creator": creator, **kw}


def _sw(c, before, after, outcome, **kw):
    return _ln("sweep", c, before=before, after=after, outcome=outcome,
               cap_before={"day": "d", "spent_millicents": 0}, cap_after={"day": "d", "spent_millicents": 100},
               started=0, ended=60, **kw)


HEAD = [_ln("run_start", ceiling_mc=40000, eligible=2), _ln("roster", eligible=["a", "b"])]


def test_resume_after_each_kind():
    st = rd.resume(HEAD)
    assert st["ceiling_mc"] == 40000 and st["eligible"] == 2 and st["creators"] == {} and st["spent_mc"] == 0
    j = HEAD + [_ln("sweep_start", "a", target=250, before=0)]
    assert rd.resume(j)["creators"]["a"]["state"] == "running"
    assert rd.resume(j)["creators"]["a"]["sweep"]["target"] == 250
    j += [_sw("a", 0, 250, "continue")]
    c = rd.resume(j)["creators"]["a"]
    assert c["state"] == "pending" and "sweep" not in c and c["zero_sweeps"] == 0
    j += [_ln("sweep_start", "a", target=500, before=250), _sw("a", 250, 300, "defer"),
          _ln("defer", "a", until=1000.0)]
    assert rd.resume(j, now=999.0)["creators"]["a"]["state"] == "deferred"
    assert rd.resume(j, now=1000.0)["creators"]["a"]["state"] == "pending"
    j += [_ln("sweep_start", "a", target=500, before=300), _sw("a", 300, 1000, "done")]
    st = rd.resume(j)
    assert st["creators"]["a"]["state"] == "done" and st["spent_mc"] == 300
    for k in ("measure", "collect", "skip", "roster", "pause", "report"):
        assert rd.resume(j + [_ln(k, "a")])["creators"]["a"]["state"] == "done", k


def test_resume_opens_sticky_only_for_no_progress():
    j = HEAD + [_ln("open", "a", reason="no_progress"), _ln("open", "b", reason="key")]
    c = rd.resume(j)["creators"]
    assert (c["a"]["state"], c["a"]["sticky"]) == ("open", True)
    assert (c["b"]["state"], c["b"]["sticky"]) == ("open", False)


@pytest.mark.parametrize("line", [_ln("open", "a", reason="collect_unreadable_403"),
                                  _ln("open", "a", reason="mirror_incomplete"), _ln("defer", "a", until=5.0)])
def test_resume_open_or_defer_never_drops_an_in_flight_sweep(line):
    j = HEAD + [_ln("sweep_start", "a", target=250, before=0), line]
    c = rd.resume(j, now=10.0)["creators"]["a"]
    assert c["state"] == "running" and c["sweep"]["target"] == 250
    st = rd.resume(j + [_sw("a", 0, 250, "continue")])            # only a sweep line settles it
    assert st["creators"]["a"]["state"] == "pending" and "sweep" not in st["creators"]["a"]
    assert st["spent_mc"] == 100


def test_resume_one_of_three_slots_in_flight():
    j = HEAD + [_ln("sweep_start", c, target=250, before=0) for c in ("a", "b", "c")]
    j += [_sw("a", 0, 250, "continue"), _sw("c", 0, 120, "done")]
    c = rd.resume(j)["creators"]
    assert [c[k]["state"] for k in ("a", "b", "c")] == ["pending", "running", "done"]


def test_resume_zero_sweeps_skip_cap_defers():
    j = HEAD + [_sw("a", 250, 250, "continue"), _sw("a", 250, 250, "defer"), _ln("defer", "a", until=5.0)]
    assert rd.resume(j, now=10.0)["creators"]["a"]["zero_sweeps"] == 1
    j += [_sw("a", 250, 250, "open:no_progress")]
    assert rd.resume(j)["creators"]["a"]["zero_sweeps"] == 2
    j += [_sw("a", 250, 260, "continue")]
    assert rd.resume(j)["creators"]["a"]["zero_sweeps"] == 0


def test_sanitise_drops_ids_names_sequences_and_long_digit_runs():
    report = {"generated": "2026-11-21T10:00:00Z",
              "run": {"added": 900, "minutes": 30.0, "items_per_min": 30.0, "spent_mc": 1234567,
                      "ceiling_mc": 360000, "eligible": 18},
              "creators": [
                  {"id": "312345678", "username": "alicefans", "nickname": "Alice Wonder", "state": "done",
                   "complete": True, "describable": 1500, "described_before": 100, "described_after": 1000,
                   "terminal": 4, "spend": {"deepinfra": 52000, "typesafe": 1800}, "sweep_minutes": 30.0,
                   "items_per_min": 30.0, "sequences": ["Shower Tease 3"]},
                  {"id": "498765432", "username": "bobby_b", "nickname": "Bob", "state": "skip: dead_session"},
              ]}
    text = rd.sanitise(report)
    for secret in ("312345678", "498765432", "alicefans", "Alice Wonder", "bobby_b", "Shower Tease 3"):
        assert secret not in text
    assert re.search(r"\bBob\b", text) is None
    assert re.search(r"\d{6,}", text) is None
    assert "C01" in text and "C02" in text and "Items/minute" in text and "30.0" in text
    full = rd.render(report)
    assert "312345678" in full and "alicefans" in full


# ── Driver against the fake relay ───────────────────────────────────────────

def test_refuses_non_loopback_without_a_request(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no request may leave for a non-loopback relay")
    monkeypatch.setattr(core._OPENER, "open", boom)
    for url in ("https://example.com", "http://10.0.0.5:8000", "http://relay.local:8000", "ftp://127.0.0.1"):
        assert run(url, tmp_path, "measure") == 2


def test_cli_help_and_non_loopback_exit_under_isolated_python(tmp_path):
    script = str(HERE / "rollout.py")
    assert subprocess.run([sys.executable, "-I", script, "--help"], capture_output=True).returncode == 0
    r = subprocess.run([sys.executable, "-I", script, "measure", "--relay", "https://example.com"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "loopback" in r.stderr


def test_script_folder_goes_after_the_standard_library_on_sys_path():
    code = ("import runpy, sys; d = sys.argv[1]; runpy.run_path(d + '/rollout.py', run_name='x'); "
            "print(sys.path.index(d) == len(sys.path) - 1)")
    r = subprocess.run([sys.executable, "-I", "-c", code, str(HERE)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "True", r.stderr


def test_journal_read_skips_a_line_cut_by_a_kill(tmp_path):
    j = core.Journal(tmp_path / "j.jsonl", "apply")
    j.write("plan", "100", sequence="S")
    with open(j.path, "ab") as fh:
        fh.write(b'{"creator": "100", "kind": "apply", "undo": [{"id": 2, "med')   # killed mid-write
    assert [ln["kind"] for ln in j.read()] == ["plan"]
    j.write("readback", "100", sequence="S")              # never glued onto the cut line
    assert [ln["kind"] for ln in j.read()] == ["plan", "readback"]
    assert len(j.path.read_text().splitlines()) == 3


def test_driver_imports_stdlib_only():
    for name in ("rollout.py", "rollout_core.py", "rollout_fill.py", "rollout_decide.py"):
        src = (HERE / name).read_text()
        assert not re.search(r"^\s*(import|from) +(httpx|requests|sqlalchemy|fastapi|db|service)\b", src, re.M)


def test_refuses_non_master_and_missing_session(serve, tmp_path, monkeypatch):
    fake = Fake([Cr("100", "a")])
    url = serve(fake)
    fake.is_admin = False
    assert run(url, tmp_path, "measure") == 2
    assert run(url, tmp_path, "measure", "--owner-session") == 0   # operator vouches: owns every Creator
    fake.is_admin = True
    monkeypatch.setenv("SFR_SESSION", "wrong")
    assert run(url, tmp_path, "measure") == 2
    monkeypatch.delenv("SFR_SESSION")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert run(url, tmp_path, "measure") == 2
    assert fake.posts == []


def test_signs_in_through_hidden_prompt_and_keeps_cookie_out_of_journal(serve, tmp_path, monkeypatch, capsys):
    fake = Fake([Cr("100", "a")])
    url = serve(fake)
    monkeypatch.delenv("SFR_SESSION")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "master")
    monkeypatch.setattr(core.getpass, "getpass", lambda prompt="": "pw")
    assert run(url, tmp_path, "measure") == 0
    assert [p[0] for p in fake.posts] == ["/auth/login"]
    assert SESSION not in (tmp_path / "j.jsonl").read_text()
    assert SESSION not in capsys.readouterr().out


def test_refuses_relay_without_phase_1a(serve, tmp_path):
    fake = Fake([Cr("100", "a")])
    fake.phase1a = False
    url = serve(fake)
    assert run(url, tmp_path, "measure") == 2
    assert run(url, tmp_path, "describe", "--live") == 2
    assert fake.posts == []


def test_roster_reasons_listed_once_and_journaled_once_per_run(serve, tmp_path, capsys):
    extra = [{**BASE, "id": "201", "username": "fans", "platform": "fansly"},
             {**BASE, "id": "202", "username": "nosess", "has_session": False},
             {**BASE, "id": "203", "username": "dead", "session_dead_at": "2026-11-20T00:00:00"},
             {**BASE, "id": "204", "username": "off", "is_active": False}]
    fake = Fake([Cr("100", "a")], extra_accounts=extra, watchers=[{**BASE, "id": "205", "username": "w"}])
    url = serve(fake)
    assert run(url, tmp_path, "measure") == 0
    out = capsys.readouterr().out
    for cid, why in (("201", "not_onlyfans"), ("202", "no_session"), ("203", "dead_session"),
                     ("204", "deactivated"), ("205", "watcher")):
        assert out.count(f"skip {cid} ") == 1 and why in out
    assert len(kinds(tmp_path, "roster")) == 1
    assert {ln["creator"]: ln["reason"] for ln in kinds(tmp_path, "skip")}["203"] == "dead_session"
    assert run(url, tmp_path, "describe", "--live") == 0
    assert len(kinds(tmp_path, "roster")) == 2
    started = {p[1] for p in fake.posts if p[0].endswith("/describe-all")}
    assert started == {"100"}   # skipped Creators are never worked


def test_measure_records_the_numbers(serve, tmp_path):
    fake = Fake([Cr("100", "a", describable=600, terminal=10, described=120, spent=2500)])
    url = serve(fake)
    assert run(url, tmp_path, "measure") == 0
    (m,) = kinds(tmp_path, "measure")
    assert (m["count"], m["complete"], m["described"], m["goal"], m["target_remaining"], m["sequences"]) == \
        (600, True, 120, 590, 470, 2)
    assert m["cap"]["spent_millicents"] == 2500 and m["cap"]["capped"] is False
    assert fake.posts == []


def test_dry_run_of_every_mode_writes_nothing(serve, tmp_path):
    fake = Fake([Cr("100", "a", described=0), Cr("101", "b", complete=False, collect_pauses=1),
                 Cr("102", "c", spent=100000)])
    url = serve(fake)
    before = {c.id: (c.described, c.spent, c.complete) for c in fake.cr.values()}
    for mode in rollout.MODES:
        assert run(url, tmp_path, mode) in (0, 4), mode
    assert {p[0] for p in fake.posts} <= {"/admin/saved-replies/fill/plan"}   # read-only: writes nothing
    assert {c.id: (c.described, c.spent, c.complete) for c in fake.cr.values()} == before
    assert not kinds(tmp_path, "sweep_start") and not kinds(tmp_path, "run_start") and not kinds(tmp_path, "collect")


def test_collect_answers_pause_and_reports_page_capped_mirror(serve, tmp_path):
    b = Cr("101", "b", describable=0, complete=False, collect_pauses=1, collect_items=300)
    c = Cr("102", "c", describable=400, complete=False, collect_complete=False)
    a = Cr("100", "a")
    fake = Fake([a, b, c])
    url = serve(fake)
    assert run(url, tmp_path, "collect", "--live") == 0
    col = {ln["creator"]: ln for ln in kinds(tmp_path, "collect")}
    assert set(col) == {"101", "102"}                       # A's mirror is complete: no Collect
    assert col["101"]["pauses"] == 1 and col["101"]["complete"] is True
    assert col["102"]["complete"] is False
    assert [(ln["creator"], ln["reason"]) for ln in kinds(tmp_path, "open")] == [("102", "mirror_incomplete")]
    assert [p[1] for p in fake.posts if p[0] == "/admin/vault-ai/collect"] == ["101", "102"]   # one each per run
    # describe then works C on what its mirror holds and leaves it open, not done
    assert run(url, tmp_path, "describe", "--live") == 0
    assert c.described == 400
    assert kinds(tmp_path, "open")[-1] == {**kinds(tmp_path, "open")[-1], "creator": "102",
                                           "reason": "mirror_incomplete"}


def test_three_creators_sweep_in_parallel_in_250_steps(serve, tmp_path):
    crs = [Cr("100", "a", describable=1200, per_poll=40), Cr("101", "b", describable=600, described=100,
                                                              per_poll=40),
           Cr("102", "c", describable=300, terminal=20, per_poll=40)]
    fake = Fake(crs)
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live", "--slots", "3") == 0
    assert fake.max_running == 3
    targets = {}
    for path, aid, body in fake.posts:
        if path.endswith("/describe-all"):
            targets.setdefault(aid, []).append(body["target"])
    assert targets == {"100": [250, 500, 750, 1000], "101": [250, 500, 600], "102": [250, 280]}
    assert [c.described for c in crs] == [1000, 600, 280]
    sweeps = kinds(tmp_path, "sweep")
    for c in crs:   # the journal's recount is the DB's count
        assert [s for s in sweeps if s["creator"] == c.id][-1]["after"] == c.described
    assert {s["creator"]: s["outcome"] for s in sweeps if s["outcome"] == "done"} == \
        {"100": "done", "101": "done", "102": "done"}
    rs = kinds(tmp_path, "run_start")
    assert len(rs) == 1 and rs[0]["ceiling_mc"] == 3 * 200 * 100 and rs[0]["eligible"] == 3
    # a re-run finds everything done and starts nothing
    n = len(fake.posts)
    assert run(url, tmp_path, "describe", "--live") == 0
    assert len(fake.posts) == n and len(kinds(tmp_path, "run_start")) == 1


def test_slots_one_runs_one_at_a_time(serve, tmp_path):
    fake = Fake([Cr("100", "a", describable=300), Cr("101", "b", describable=300)])
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live", "--slots", "1") == 0
    assert fake.max_running == 1
    with pytest.raises(SystemExit) as e:   # usage: argparse's exit 2
        run(url, tmp_path, "describe", "--live", "--slots", "4")
    assert e.value.code == 2


def test_stops_jev_not_ready_low_ceiling_and_cap(serve, tmp_path):
    jev = Cr("100", "a", jev_ready=False)
    ok = Cr("101", "b", describable=250)
    fake = Fake([jev, ok])
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0          # open does not change the exit code
    assert [(o["creator"], o["reason"]) for o in kinds(tmp_path, "open")] == [("100", "jev_not_ready")]
    assert not any(aid == "100" for p, aid, _ in fake.posts)
    assert ok.described == 250

    fake2 = Fake([Cr("300", "x")])
    url2 = serve(fake2)
    j2 = tmp_path / "low"
    j2.mkdir()
    assert run(url2, j2, "describe", "--live", "--ceiling-cents", "10") == 3   # 10c < one 250 x 20 mc sweep
    assert fake2.posts == []
    assert [p["reason"] for p in kinds(j2, "pause")] == ["ceiling"]

    capped = Cr("400", "y", spent=100000, cap=100000)
    mid = Cr("401", "z", describable=600, cap=3000)                 # caps out after 300 items mid-sweep
    fake3 = Fake([capped, mid])
    url3 = serve(fake3)
    j3 = tmp_path / "cap"
    j3.mkdir()
    assert run(url3, j3, "describe", "--live") == 4
    d = {ln["creator"]: ln for ln in kinds(j3, "defer")}
    assert set(d) == {"400", "401"}
    assert d["400"]["until"] % 86400 == 0 and d["400"]["until"] > time.time()
    assert not any(aid == "400" and p.endswith("/describe-all") for p, aid, _ in fake3.posts)
    # same day: deferred Creators are skipped, still exit 4, nothing new starts
    n = len(fake3.posts)
    assert run(url3, j3, "describe", "--live") == 4 and len(fake3.posts) == n


def test_jev_down_box_wide_pauses_without_looping(serve, tmp_path):
    fake = Fake([Cr("100", "a", jev_ready=False), Cr("101", "b", jev_ready=False), Cr("102", "c")])
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 3
    assert [p["reason"] for p in kinds(tmp_path, "pause")] == ["jev"]
    assert fake.posts == []


def test_two_zero_progress_sweeps_open_no_progress(serve, tmp_path):
    z = Cr("100", "a", zero=True)
    fake = Fake([z])
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0
    assert len([p for p in fake.posts if p[0].endswith("/describe-all")]) == 2
    (o,) = kinds(tmp_path, "open")
    assert o["reason"] == "no_progress" and "in a row" in o["detail"]
    n = len(fake.posts)
    assert run(url, tmp_path, "describe", "--live") == 0 and len(fake.posts) == n   # sticky: not retried


def test_ceiling_counts_journaled_spend_across_runs(serve, tmp_path):
    a = Cr("100", "a", describable=1000, per_poll=250)
    fake = Fake([a])
    url = serve(fake)
    # ceiling 60c = 6000 mc; reserve 5000 per sweep; real spend 2500 mc per 250 items
    assert run(url, tmp_path, "describe", "--live", "--ceiling-cents", "60") == 3
    assert a.described == 250 and rd.resume(journal(tmp_path))["spent_mc"] == 2500
    assert run(url, tmp_path, "describe", "--live", "--ceiling-cents", "60") == 3
    assert a.described == 250   # 2500 + 5000 > 6000
    assert run(url, tmp_path, "describe", "--live", "--ceiling-cents", "200") == 0
    assert a.described == 1000
    assert [r["ceiling_mc"] for r in kinds(tmp_path, "run_start")] == [6000, 20000]


def test_resume_after_kill_awaits_running_sweeps_and_skips_done(serve, tmp_path):
    crs = [Cr("100", "a", describable=500, per_poll=1), Cr("101", "b", describable=500, per_poll=1),
           Cr("102", "c", describable=500, per_poll=1), Cr("103", "d", describable=250, described=250)]
    fake = Fake(crs)
    url = serve(fake)
    code = ("import sys; sys.path.insert(0, %r); import rollout, rollout_core; rollout_core.POLL_S = 0.02; "
            "sys.exit(rollout.main(sys.argv[1:]))" % str(HERE))
    env = {**os.environ, "SFR_SESSION": SESSION}
    p = subprocess.Popen([sys.executable, "-c", code, "describe", "--relay", url, "--live",
                          "--journal", str(tmp_path / "j.jsonl")], env=env, stdout=subprocess.DEVNULL,
                         start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline and len(kinds(tmp_path, "sweep_start")) < 3:
        time.sleep(0.02)
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()
    assert len(kinds(tmp_path, "sweep_start")) == 3 and not kinds(tmp_path, "sweep")
    assert all(c.running_target == 250 for c in crs[:3])
    for c in crs[:3]:
        c.per_poll = 50
    assert run(url, tmp_path, "describe", "--live") == 0
    for c in crs[:3]:   # each in-flight sweep awaited (no second start while it ran), then stepped on
        ev = [e for e in fake.events if e[1] == c.id]
        assert ev == [("start", c.id, 250), ("end", c.id, 250), ("start", c.id, 500), ("end", c.id, 500)]
        assert c.described == 500
    assert not any(aid == "103" for path, aid, _ in fake.posts)   # done Creator: no sweep
    first = kinds(tmp_path, "sweep")[:3]
    assert {s["creator"] for s in first} == {"100", "101", "102"} and all(s["target"] == 250 for s in first)


def test_report_full_and_sanitised(serve, tmp_path, monkeypatch):
    clock = iter(range(1_800_000_000, 1_900_000_000, 6))   # 6 s per reading: sweeps take minutes, not ms
    monkeypatch.setattr(rollout, "now", lambda: float(next(clock)))
    crs = [Cr("312345678", "alicefans", describable=600, per_poll=50),
           Cr("498765432", "bobby_b", describable=300, per_poll=50)]
    fake = Fake(crs, extra_accounts=[{**BASE, "id": "555555555", "username": "deadgirl",
                                      "session_dead_at": "2026-11-20T00:00:00"}])
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0
    assert run(url, tmp_path, "report") == 0
    full = (tmp_path / "rollout-report-full.md").read_text()
    text = (tmp_path / "report.md").read_text()
    assert oct((tmp_path / "rollout-report-full.md").stat().st_mode & 0o777) == "0o600"
    assert "312345678" in full and "alicefans" in full and "skip: dead_session" in full
    for secret in ("312345678", "498765432", "555555555", "alicefans", "Alicefans", "bobby_b", "Bobby_B",
                   "deadgirl"):
        assert secret not in text
    assert re.search(r"\d{6,}", text) is None
    assert "Items/minute" in text and "C01" in text and "C03" in text
    rows = [r for r in text.splitlines() if r.startswith("| C")]
    done = [r for r in rows if "| done |" in r]
    ipm = [c.strip() for c in next(r for r in text.splitlines() if r.startswith("| Creator")).split("|")] \
        .index("Items/minute")
    assert len(done) == 2 and all(float(r.split("|")[ipm]) > 0 for r in done)
    assert "deepinfra" in text and "deepseek" not in text   # describe purposes only
    assert kinds(tmp_path, "report")
    assert oct((tmp_path / "j.jsonl").stat().st_mode & 0o777) == "0o600"


def test_unreadable_creator_is_opened_not_retried_forever(serve, tmp_path):
    bad, good = Cr("100", "a"), Cr("101", "b", describable=250)
    bad.forbidden = True
    fake = Fake([bad, good])
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0
    assert [(o["creator"], o["reason"]) for o in kinds(tmp_path, "open")] == [("100", "unreadable_403")]
    assert good.described == 250


DA, PLAN_P = "/admin/vault-ai/describe-all", "/admin/vault-ai/describe-all/plan"
COL_STATUS, COL_CONT = "/admin/vault-ai/collect/status", "/admin/vault-ai/collect/continue"


def test_failing_start_is_retried_after_a_sleep_then_opened(serve, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "POLL_S", 0.05)
    bad, good = Cr("100", "a"), Cr("101", "b", describable=250)
    fake = Fake([bad, good])
    fake.fail[(DA, "100")] = 500
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0
    hits = fake.hits[(DA, "100")]
    assert len(hits) == rd.RETRY_BUDGET                               # bounded, never forever
    assert all(b - a >= 0.05 for a, b in zip(hits, hits[1:]))       # each retry waits a poll interval
    assert [(o["creator"], o["reason"]) for o in kinds(tmp_path, "open")] == [("100", "relay_errors")]
    assert good.described == 250


def test_failing_target_probe_is_bounded(serve, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "POLL_S", 0.02)
    a = Cr("100", "a")
    fake = Fake([a])
    fake.fail[(PLAN_P, "100")] = lambda c: None if not fake.hits[(PLAN_P, "100")] or \
        len(fake.hits[(PLAN_P, "100")]) % 2 else 502   # the read at 1000 answers, the read at t fails
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0
    assert [o["reason"] for o in kinds(tmp_path, "open")] == ["relay_errors"]
    assert len(fake.hits[(PLAN_P, "100")]) == 2 * rd.RETRY_BUDGET and not fake.posts


@pytest.mark.parametrize("status", [403, 500])
def test_unreadable_recount_keeps_the_sweep_in_flight_and_counts_it_next_run(serve, tmp_path, status):
    a = Cr("100", "a", describable=250, per_poll=250)
    fake = Fake([a])
    fake.fail[(PLAN_P, "100")] = lambda c: status if c.described > 0 else None
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 3
    assert len(kinds(tmp_path, "sweep_start")) == 1 and not kinds(tmp_path, "sweep")
    assert not kinds(tmp_path, "open")                                  # no line drops the in-flight sweep
    assert [p["reason"] for p in kinds(tmp_path, "pause")] == ["recount_unreadable"]
    assert rd.resume(journal(tmp_path))["creators"]["100"]["state"] == "running"
    fake.fail.clear()
    assert run(url, tmp_path, "describe", "--live") == 0
    (sw,) = kinds(tmp_path, "sweep")
    assert (sw["before"], sw["after"], sw["outcome"]) == (0, 250, "done")
    assert rd.resume(journal(tmp_path))["spent_mc"] == 250 * ITEM_MC_REAL   # the sweep's spend is not lost
    assert len([p for p in fake.posts if p[0] == DA]) == 1                 # awaited, never restarted


def test_redirects_are_not_followed(serve, tmp_path):
    other = Fake([Cr("100", "a")])
    url2 = serve(other)
    fake = Fake([Cr("100", "a")])
    fake.redirect_me = url2 + "/auth/me"
    url = serve(fake)
    assert run(url, tmp_path, "measure") == 2
    assert other.seen == []                          # the session cookie never left for the Location


def test_collect_poll_loop_is_bounded(serve, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "POLL_S", 0.01)
    gone, ok = Cr("100", "a", complete=False), Cr("101", "b", complete=False, collect_items=5)
    fake = Fake([gone, ok])
    fake.fail[(COL_STATUS, "100")] = 403
    url = serve(fake)
    assert run(url, tmp_path, "collect", "--live") == 0
    assert len(fake.hits[(COL_STATUS, "100")]) == rd.RETRY_BUDGET
    assert [(o["creator"], o["reason"]) for o in kinds(tmp_path, "open")] == [("100", "collect_unreadable_403")]
    assert [c["creator"] for c in kinds(tmp_path, "collect")] == ["101"]

    sick = Fake([Cr("200", "s", complete=False)])
    sick.fail[(COL_STATUS, "200")] = 500
    j2 = tmp_path / "sick"
    j2.mkdir()
    assert run(serve(sick), j2, "collect", "--live") == 3
    assert [p["reason"] for p in kinds(j2, "pause")] == ["errors"]
    assert len(sick.hits[(COL_STATUS, "200")]) == rd.RETRY_BUDGET

    stuck = Fake([Cr("300", "p", complete=False, collect_pauses=1)])
    stuck.fail[(COL_CONT, "300")] = 500
    j3 = tmp_path / "stuck"
    j3.mkdir()
    assert run(serve(stuck), j3, "collect", "--live") == 3
    assert len(stuck.hits[(COL_CONT, "300")]) == rd.RETRY_BUDGET


def test_dry_run_reserves_running_sweeps_like_the_live_run(serve, tmp_path, capsys):
    fake = Fake([Cr("100", "a"), Cr("101", "b"), Cr("102", "c")])
    url = serve(fake)
    j = core.Journal(tmp_path / "j.jsonl", "describe")
    for cid in ("100", "101"):
        j.write("sweep_start", cid, target=250, before=0, cap_before={}, started=0.0, goal=600, complete=True)
    # ceiling 140c = 14,000 mc; each sweep reserves 250 x 20 = 5,000: two running + one more is 15,000
    assert run(url, tmp_path, "describe", "--ceiling-cents", "140") == 3
    out = capsys.readouterr().out
    assert "describe 102: would pause" in out and fake.posts == []
    assert run(url, tmp_path, "describe", "--ceiling-cents", "150") == 0
    assert "describe 102: would sweep to target 250" in capsys.readouterr().out


def test_collect_open_never_drops_a_sweep_left_in_flight(serve, tmp_path):
    # a describe run was killed with a sweep in flight; the sweep then finished on the server (250 items, 2,500 mc)
    a = Cr("100", "a", describable=250, described=250, spent=250 * ITEM_MC_REAL, complete=False)
    fake = Fake([a])
    fake.fail[(COL_STATUS, "100")] = 403
    url = serve(fake)
    core.Journal(tmp_path / "j.jsonl", "describe").write(
        "sweep_start", "100", target=250, before=0, started=0.0, goal=250, complete=False,
        cap_before={"day": rollout.utc_day(), "spent_millicents": 0, "cap_millicents": 100000})
    assert run(url, tmp_path, "collect", "--live") == 0
    assert [o["reason"] for o in kinds(tmp_path, "open")] == ["collect_unreadable_403"]
    run(url, tmp_path, "describe", "--live")
    (sw,) = kinds(tmp_path, "sweep")                                    # the in-flight sweep was awaited
    assert (sw["before"], sw["after"]) == (0, 250)
    assert rd.resume(journal(tmp_path))["spent_mc"] == 250 * ITEM_MC_REAL   # its spend reached run_spend
    assert not [p for p in fake.posts if p[0] == DA]


SUMMARY_P = "/admin/vault-ai/cache/summary"


def test_failing_summary_is_retried_on_its_own_status_and_skips_the_plan_read(serve, tmp_path):
    bad, good = Cr("100", "a"), Cr("101", "b", describable=250)
    fake = Fake([bad, good])
    fake.fail[(SUMMARY_P, "100")] = 503
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 0
    assert [(o["creator"], o["reason"]) for o in kinds(tmp_path, "open")] == [("100", "relay_errors")]
    assert len(fake.hits[(SUMMARY_P, "100")]) == rd.RETRY_BUDGET
    assert (PLAN_P, "100") not in fake.hits                            # no plan read after a failed summary
    assert good.described == 250


def test_collect_that_stays_paused_ends_after_the_pause_budget(serve, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "POLL_S", 0.001)
    assert rd.COLLECT_PAUSE_BUDGET < 50                                # the fake heals at 50
    stuck, ok = Cr("100", "a", complete=False, collect_pauses=1, collect_stuck=True), \
        Cr("101", "b", complete=False, collect_items=5)
    fake = Fake([stuck, ok])
    url = serve(fake)
    assert run(url, tmp_path, "collect", "--live") == 0
    assert len(fake.hits[(COL_CONT, "100")]) == rd.COLLECT_PAUSE_BUDGET
    assert [(o["creator"], o["reason"]) for o in kinds(tmp_path, "open")] == [("100", "collect_paused")]
    assert [c["creator"] for c in kinds(tmp_path, "collect")] == ["101"]


def test_status_4xx_while_running_is_retried_not_recounted(serve, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "POLL_S", 0.02)
    a = Cr("100", "a", describable=250, per_poll=250)
    fake = Fake([a])
    fake.fail[(DA + "/status", "100")] = 403
    url = serve(fake)
    assert run(url, tmp_path, "describe", "--live") == 3
    hits = fake.hits[(DA + "/status", "100")]
    assert len(hits) == rd.RETRY_BUDGET
    assert all(b - a >= 0.02 for a, b in zip(hits, hits[1:]))       # each retry waits a poll interval
    assert len(kinds(tmp_path, "sweep_start")) == 1 and not kinds(tmp_path, "sweep") and not kinds(tmp_path, "open")
    assert [p["reason"] for p in kinds(tmp_path, "pause")] == ["recount_unreadable"]
    assert rd.resume(journal(tmp_path))["creators"]["100"]["state"] == "running"
    fake.fail.clear()
    assert run(url, tmp_path, "describe", "--live") == 0
    (sw,) = kinds(tmp_path, "sweep")                                    # one journal line holds the whole spend
    assert (sw["before"], sw["after"], sw["outcome"]) == (0, 250, "done")
    assert rd.resume(journal(tmp_path))["spent_mc"] == 250 * ITEM_MC_REAL
    assert len([p for p in fake.posts if p[0] == DA]) == 1
