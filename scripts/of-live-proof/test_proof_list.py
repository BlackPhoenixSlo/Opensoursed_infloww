"""A Phase's proof list CLI (`proof_list.main`, run by proofs/phase2.py): ids, the record check and the sweep check.

Expected behaviour from docs/spec/ofm-not-yet/phase-02-content-chat-writes.md (Interfaces, `proofs/phase2.py`) and
ticket 29: `--ids` prints the comma-joined proof ids; `--check-records <dir>` exits 1 unless every proof has a capture
record whose `proof.verdict` is `pass` or `parked` with a non-empty `reason`; `--check-sweep <sweep> <dir>` exits 1 if a
proof whose record shows `kind: live, verdict: pass` is still in the sweep's `ny`, or one without that pass is missing
from `ny` (D1). Proofs and records here are planted.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import proof_list
from proof_core import Proof, Write

HERE = Path(__file__).parent

A = Proof(id="p2.alpha", phase=2, page="home/index", control="Record video", kind="live")
B = Proof(id="p2.beta", phase=2, page="vault/index", control="More", kind="mocked")
PROOFS = (A, B)


def record(proof, **verdict):
    return {"id": f"{proof.page.split('/')[0]}--{proof.control.lower().replace(' ', '-')}",
            "label": proof.control, "pages": [proof.page], "phase": 2, "source": "of-js",
            "proof": {"kind": proof.kind, **verdict}}


def write(folder, *recs):
    folder.mkdir(exist_ok=True)
    for r in recs:
        (folder / f"{r['id']}.json").write_text(json.dumps(r))
    return folder


def sweep(tmp_path, **ny):
    """A sweep file: {page: [ny labels]} -> [[page, {"ny", "dis", "ro"}]]."""
    f = tmp_path / "sweep.json"
    f.write_text(json.dumps([[page, {"ny": labels, "dis": [], "ro": []}] for page, labels in ny.items()]))
    return f


def run(argv, capsys):
    code = proof_list.main(PROOFS, argv, prog="test")
    return code, capsys.readouterr().out


def test_ids_are_comma_joined(capsys):
    assert run(["--ids"], capsys) == (0, "p2.alpha,p2.beta\n")


CLEAN = (dict(verdict="pass", reason=""), dict(verdict="parked", reason="no Proof fan named"))


def test_record_check_passes_clean_records(tmp_path, capsys):
    d = write(tmp_path / "c", record(A, **CLEAN[0]), record(B, **CLEAN[1]))
    assert run(["--check-records", str(d)], capsys)[0] == 0


@pytest.mark.parametrize("bad", [
    None,                                        # no record for the proof
    dict(verdict="fail", reason="x"),            # neither pass nor parked
    dict(verdict="parked", reason="  "),         # parked with no reason
    dict(verdict="parked"),                      # parked, reason missing
    dict(verdict="pass", branches={"a": "parked"}),  # a branch verdict without its reason
    dict(verdict="pass", reason="", branches={"a": "fail"}),  # a branch verdict neither pass nor parked
])
def test_record_check_fails_a_planted_bad_record(tmp_path, capsys, bad):
    recs = [record(A, **CLEAN[0])] + ([record(B, **bad)] if bad is not None else [])
    code, out = run(["--check-records", str(write(tmp_path / "c", *recs))], capsys)
    assert code == 1 and "p2.beta" in out and "p2.alpha" not in out.split("check-records:")[0], out


def test_record_check_fails_two_records_for_one_proof(tmp_path, capsys):
    twin = {**record(A, **CLEAN[0]), "id": "home--record-video-2"}
    d = write(tmp_path / "c", record(A, **CLEAN[0]), twin, record(B, **CLEAN[1]))
    code, out = run(["--check-records", str(d)], capsys)
    assert code == 1 and "p2.alpha" in out, out


def test_record_check_missing_dir_is_2(tmp_path, capsys):
    assert run(["--check-records", str(tmp_path / "nope")], capsys)[0] == 2


def test_sweep_check_passes_a_clean_sweep(tmp_path, capsys):
    # A passed live: its title dropped (absent from ny); B mocked-only: keeps the title.
    d = write(tmp_path / "c", record(A, verdict="pass", reason=""), record(B, **CLEAN[1]))
    f = sweep(tmp_path, **{"home/index": ["Search"], "vault/index": ["More"]})
    assert run(["--check-sweep", str(f), str(d)], capsys)[0] == 0


@pytest.mark.parametrize("ny", [
    {"home/index": ["Record video"], "vault/index": ["More"]},   # live pass, title still there
    {"home/index": [], "vault/index": []},                       # parked/mocked, title gone
    {"home/index": []},                                          # a proof's page not swept
])
def test_sweep_check_fails_a_planted_bad_sweep(tmp_path, capsys, ny):
    d = write(tmp_path / "c", record(A, verdict="pass", reason=""), record(B, **CLEAN[1]))
    assert run(["--check-sweep", str(sweep(tmp_path, **ny)), str(d)], capsys)[0] == 1


def test_an_overlay_replaces_its_pages_of_the_sweep(tmp_path, capsys):
    # The dated sweep keeps A's title; a re-sweep of home/index after A's Live pass overlays it (ticket 10 precedent).
    d = write(tmp_path / "c", record(A, verdict="pass", reason=""), record(B, **CLEAN[1]))
    base = sweep(tmp_path, **{"home/index": ["Record video"], "vault/index": ["More"]})
    ov = tmp_path / "ov.json"
    ov.write_text(json.dumps([["home/index", {"ny": [], "dis": [], "ro": []}], ["other/page", {"ny": ["X"]}]]))
    assert run(["--check-sweep", str(base), str(d)], capsys)[0] == 1
    assert run(["--check-sweep", str(base), str(d), "--overlay", str(ov)], capsys)[0] == 0
    assert proof_list.overlaid([["a", 1], ["b", 2]], [["b", 3], ["c", 4]]) == [["a", 1], ["b", 3]]


def test_overlay_needs_check_sweep(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        proof_list.main(PROOFS, ["--ids", "--overlay", str(tmp_path / "x.json")], prog="test")
    assert e.value.code == 2


def test_a_mocked_pass_is_not_a_live_pass(tmp_path, capsys):
    # B's Mocked proof passed: no Live-proof pass, so its title stays (D1).
    d = write(tmp_path / "c", record(A, verdict="pass", reason=""), record(B, verdict="pass", reason=""))
    f = sweep(tmp_path, **{"home/index": [], "vault/index": []})
    code, out = run(["--check-sweep", str(f), str(d)], capsys)
    assert code == 1 and "p2.beta" in out, out


@pytest.mark.parametrize("phase", ["phase2.py", "phase4.py"])
def test_phase_cli_runs_isolated(tmp_path, phase):
    """The shipped command line (`python -I .../proofs/phase<N>.py`) imports its siblings from any directory."""
    out = subprocess.run([sys.executable, "-I", str(HERE / "proofs" / phase), "--ids"],
                         capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stderr


def test_phase2_sweep_check_passes_on_the_dated_sweep_with_the_live_overlay(tmp_path):
    """D1, Phase 2: the dated sweep with the 2026-11-21 re-sweep of its Live-passed pages over it (home/index, vault/list,
    the list page) and the 2026-11-21 messages/chat re-sweep at dead.py SWEEP_QUERY (ticket 33's own bubbles, their three
    controls Not yet) has no problem; the bare dated file still flags those passes (the guard is not relaxed)."""
    docs = HERE.parents[1] / "docs" / "of-manager"
    cmd = [sys.executable, "-I", str(HERE / "proofs" / "phase2.py"), "--check-sweep", str(docs / "not-yet-sweep-2026-11-20.json"),
           str(docs / "captures")]
    overlays = ["--overlay", str(docs / "not-yet-sweep-2026-11-21-live.json"), "--overlay", str(docs / "not-yet-sweep-2026-11-21-own-bubbles.json")]
    out = subprocess.run([*cmd, *overlays], capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 1 and "still has the Not-yet title" in out.stdout, out.stdout


# ofm-not-yet ticket 35: a proof tagged never-titled (its control was Wired before this effort) has no title to drop
# its `control` is its real sweep labels joined; each must be off `ny` and on new-post/index.html
T = Proof(id="p2.gamma", phase=2, page="new-post/index", control="Add labels; Expiration period; Your target",
          kind="live", tags=frozenset({proof_list.NEVER_TITLED}))
F = Proof(id="p2.eps", phase=2, page="new-post/index", control="Add labels; Labels, expiration and target",
          kind="live", tags=frozenset({proof_list.NEVER_TITLED}))
U = Proof(id="p2.delta", phase=2, page="new-post/index", control="Add labels", kind="live")


@pytest.mark.parametrize("proof,ny,passed,problem", [
    (T, ["Schedule post"], False, None),                   # tagged, real labels, untitled: ok
    (T, [], True, None),                                   # ... after a Live pass too
    (T, ["Your target"], False, "'Your target' still titled"),   # one real label titled: a problem
    (T, ["Expiration period"], True, "'Expiration period' still titled"),   # ... after a Live pass too
    (F, [], False, "no control labelled 'Labels, expiration and target'"),   # a made-up label: a problem
    (U, [], False, "lost the Not-yet title"),              # untagged, untitled: the existing problem
    (T, None, False, "not in the sweep"),                  # tagged, page not swept: still a problem
])
def test_sweep_check_never_titled(tmp_path, proof, ny, passed, problem):
    d = write(tmp_path / "c", record(proof, verdict="pass" if passed else "parked", reason="" if passed else "x"))
    pages = {} if ny is None else {"new-post/index": ny}
    out = proof_list.check_sweep((proof,), json.loads(sweep(tmp_path, **pages).read_text()), d)
    assert (out == []) if problem is None else (len(out) == 1 and problem in out[0]), out


# ticket 53: a host a proof names (`Proof.hosts`) must be named from its capture: a `facts.<name>_host` of its record.
HOSTED = Proof(id="p2.hosted", phase=2, page="home/index", control="Record video", kind="live",
               arm=(Write("PUT", "/upload/{file}", host="store.example.net"),), effect=lambda b, a: True,
               undo=(Write("DELETE", "/api2/v2/posts/{id}"),))


@pytest.mark.parametrize("facts, ok", [
    ({"upload_host": "store.example.net"}, True),
    (None, False),                                           # the record names no host
    ({"upload_host": "other.example.net"}, False),           # another host
    ({"upload_host": "store.example.net.evil"}, False),      # a lookalike
    ({"note": "store.example.net"}, False),                  # named, but not as a host fact
])
def test_record_check_holds_a_proofs_hosts_to_its_record(tmp_path, capsys, facts, ok):
    rec = record(HOSTED, **CLEAN[0]) | ({"facts": facts} if facts is not None else {})
    code, out = proof_list.main((HOSTED,), ["--check-records", str(write(tmp_path / "c", rec))], prog="test"), \
        capsys.readouterr().out
    assert (code == 0) == ok, out
    if not ok:
        assert "p2.hosted" in out and "store.example.net" in out, out


# never-titled is self-declared (any proof could tag itself and skip D1's Live pass), so the tagged ids are pinned here;
# adding one needs evidence its controls were Wired, never Not-yet titled, before ofm-not-yet (cite it in the proof)
NEVER_TITLED_ALLOWED = {"p2.post-labels-expiry-target"}


def test_never_titled_is_pinned():
    import importlib
    tagged = {p.id for f in sorted((HERE / "proofs").glob("*.py")) if f.stem != "__init__"
              for p in getattr(importlib.import_module(f"proofs.{f.stem}"), "PROOFS", ()) if proof_list.NEVER_TITLED in p.tags}
    assert tagged == NEVER_TITLED_ALLOWED
