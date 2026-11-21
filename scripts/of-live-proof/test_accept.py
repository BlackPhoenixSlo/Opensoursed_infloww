"""accept.py's parsing (ticket 77): batches of at most N with Lockout proofs last, the evidence folder from run.sh's
output, and which failed batches retry a proof alone (only a Page.goto timeout or "no Mirror frame", run_ok true).
Reports planted; prove.py's run_ok verdict on planted reports too."""
import pytest

import accept
import prove
from proof_core import Proof


def p(pid, *tags):
    return Proof(id=pid, phase=3, page="settings/x", control=pid, kind="live", tags=frozenset(tags))


def rep(*proofs, exit=1, **run):
    return {"exit": exit, "run_ok": True,
            "proofs": [{"proof": i, "state": s, "problems": list(pr)} for i, s, *pr in proofs], "parked": [], **run}


def test_batches_cut_at_size_and_put_lockout_last_with_its_flag():
    proofs = [p("a"), p("lock1", "lockout"), p("b"), p("c"), p("d"), p("e"), p("lock2", "lockout")]
    assert accept.batches(proofs, 4) == [(["a", "b", "c", "d"], False), (["e"], False), (["lock1", "lock2"], True)]
    assert accept.batches(proofs, 1)[-2:] == [(["lock1"], True), (["lock2"], True)]


def test_phase3_list_holds_its_lockout_proofs_last():
    got = accept.batches(accept.phase_proofs(3), 4)
    assert all(len(ids) <= 4 for ids, _ in got)
    flags = [lk for _, lk in got]
    assert flags == sorted(flags) and flags[-1] is True
    assert "settings--trial-create-link" in {i for ids, _ in got for i in ids}   # WIRED_PROOFS join the run


def test_evidence_folder_from_output():
    out = "ofm-live-proof: stale lock taken over\nofm-live-proof: evidence slop/evidence/20261121T1-ofm-fake-abc\nx"
    assert accept.evidence_of(out) == "slop/evidence/20261121T1-ofm-fake-abc"
    assert accept.evidence_of("ofm-live-proof: refused: lock held by pid 1 (x): one run at a time") is None


def test_passed_batch_retries_nothing():
    assert accept.retry_ids(rep(("a", "pass"), exit=0)) == []


def test_goto_timeout_and_no_mirror_frame_retry_alone():
    r = rep(("a", "pass"), ("b", "fail", "TimeoutError: Page.goto: Timeout 30000ms exceeded."),
            ("c", "fail", "RuntimeError: no Mirror frame /of-mirror/pages/x on about:blank"))
    assert accept.retry_ids(r) == ["b", "c"]


def test_parked_proof_beside_a_retryable_failure_still_retries():
    timeout = ("b", "fail", "TimeoutError: Page.goto: Timeout 30000ms exceeded.")
    assert accept.retry_ids(rep(("a", "parked"), timeout)) == ["b"]   # prove's proof_ok: parked is no failure


def test_any_other_failure_is_fail_not_retry():
    timeout = ("b", "fail", "TimeoutError: Page.goto: Timeout 30000ms exceeded.")
    assert accept.retry_ids(rep(("a", "fail", "effect did not hold"), timeout)) is None
    assert accept.retry_ids(rep(("b", "fail", "TimeoutError: Page.goto: Timeout", "wire: unarmed write"))) is None
    assert accept.retry_ids(rep(("b", "fail", "TimeoutError: Frame.wait_for_function: Timeout 30000ms"))) is None
    assert accept.retry_ids(rep(("b", "fail"))) is None   # no problem named


def test_run_ok_false_or_missing_is_fail_even_with_only_retryable_proofs():
    timeout = ("b", "fail", "TimeoutError: Page.goto: Timeout 30000ms exceeded.")
    assert accept.retry_ids(rep(timeout, run_ok=False)) is None   # a solo retry can never hide this batch
    assert accept.retry_ids(rep(("a", "pass"), exit=0, run_ok=False)) is None
    r = rep(timeout)
    del r["run_ok"]
    assert accept.retry_ids(r) is None   # a report without the verdict (older prove.py) is FAIL


def test_failed_run_with_every_proof_passing_is_fail():
    assert accept.retry_ids(rep(("a", "pass"))) is None


def _run_rep(**over):
    r = {"preflight": [], "harness": [], "session_leaks": [], "trees_changed": False, "not_run": [], "refused": [],
         "undo_log": [], "teardown": {"temp_deleted": True}, "parked": [{"proof": "p"}],
         "proofs": [{"proof": "a", "state": "fail"}]}
    r.update(over)
    return r


def test_prove_run_ok_is_the_run_verdict_without_proof_states():
    assert prove.run_ok(_run_rep(), 2, True) is True   # a failing proof leaves the run verdict alone
    assert prove.run_ok(_run_rep(), 2, False) is False   # no session secrets to scan for
    assert prove.run_ok(_run_rep(), 3, True) is False   # a proof neither run nor parked


@pytest.mark.parametrize("key,val", [
    ("error", "Boom"), ("preflight", ["x"]), ("harness", ["census"]), ("offhost", ["h"]), ("niceness_low", [1]),
    ("trees_changed", True), ("session_leaks", ["s"]), ("not_run", ["c"]), ("refused", ["r"]),
    ("undo_log", ["row 1 pending"]), ("teardown", {"temp_deleted": False}), ("teardown", {})])
def test_prove_run_ok_false_on_each_run_failure(key, val):
    assert prove.run_ok(_run_rep(**{key: val}), 2, True) is False


def test_sweep_port_on_a_phase_without_sweep_sections_is_refused_before_any_batch(monkeypatch, capsys):
    monkeypatch.setattr(accept, "run", lambda *a: pytest.fail("a batch ran"))
    with pytest.raises(SystemExit) as e:
        accept.main(["--phase", "2", "--sweep-port", "3091"])
    assert e.value.code == 2 and "no sweep sections" in capsys.readouterr().err


def test_committed_sweep_check_runs_with_the_committed_overlays_and_an_own_sweep_without(monkeypatch, tmp_path):
    monkeypatch.setattr(accept, "phase_proofs", lambda n: [])
    cmds = []
    monkeypatch.setattr(accept, "check", lambda label, cmd, env=None: cmds.append(cmd) or True)
    assert accept.main(["--phase", "3"]) == 0
    sweep_cmd = next(c for c in cmds if "--check-sweep" in c)
    assert sweep_cmd[sweep_cmd.index("--check-sweep") + 1] == str(accept.COMMITTED_SWEEP)
    assert [sweep_cmd[i + 1] for i, x in enumerate(sweep_cmd) if x == "--overlay"] == [str(f) for f in accept.COMMITTED_OVERLAYS]
    assert all(f.is_file() for f in accept.COMMITTED_OVERLAYS)
    cmds.clear()
    assert accept.main(["--phase", "3", "--sweep", str(tmp_path / "own.json")]) == 0
    assert "--overlay" not in next(c for c in cmds if "--check-sweep" in c)
