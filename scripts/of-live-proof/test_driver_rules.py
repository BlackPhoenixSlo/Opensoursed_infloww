from datetime import datetime, timedelta, timezone

import pytest

from proof_core import Proof, Write, not_started, pace_problems, pace_wait, undo_deadline
import prove

AT = datetime(2026, 11, 21, 3, 10, tzinfo=timezone.utc)
YES = lambda before, after: True  # noqa: E731
DEL = (Write("DELETE", "/api2/v2/lists/{id}"),)


def P(arm=(Write("POST", "/api2/v2/lists"),), undo=DEL, tags=(), kind="live", id="p.x", trigger=(("click", "#x"),)):
    return Proof(id=id, phase=0, page="collections/index", control="x", kind=kind, tags=frozenset(tags),
                 arm=tuple(arm), undo=tuple(undo), effect=YES if arm else None, trigger=trigger)


CHAT = P(arm=[Write("POST", "/api2/v2/chats/{fan}/messages")], undo=[Write("DELETE", "/api2/v2/messages/{id}")])
QUEUE = P(arm=[Write("POST", "/api2/v2/messages/queue")], undo=[Write("DELETE", "/api2/v2/messages/queue/{id}")])
STREAM_BY_PATH = P(arm=[Write("POST", "/api2/v2/streams", body_must={"x": 1})], undo=[Write("DELETE", "/api2/v2/streams/{id}")])
PARK = "parked: Proof fan unset; the run never picks a Fan (--proof-fan names it)"
STREAM = "stream start: needs the owner's stream go; no owner-go run path yet (ticket 126)"
IRREV = "irreversible: needs the owner's go naming this proof; no owner-go run path yet (ticket 126)"


@pytest.mark.parametrize("proof, of, fan, want", [
    (P(tags={"message"}), "fake", None, PARK),
    (P(tags={"message"}), "live", None, PARK),
    (CHAT, "fake", None, PARK),
    (QUEUE, "live", None, PARK),
    (P(tags={"message"}), "live", "555", None),
    (P(tags={"message"}), "fake", "555", None),
    (P(kind="mocked"), "live", "555", "mocked: not run live"),
    (P(kind="mocked"), "fake", None, None),
    (P(tags={"stream_start"}), "live", "555", STREAM),
    (STREAM_BY_PATH, "live", None, STREAM),
    (P(tags={"stream_start"}), "fake", None, None),
    (P(tags={"irreversible"}, undo=()), "live", "555", IRREV),
    (P(tags={"irreversible"}, undo=()), "fake", None, None),
    (P(), "live", None, None),
    (P(arm=()), "live", None, None),
    (P(tags={"message"}, kind="mocked"), "live", None, "mocked: not run live"),
], ids=["message tag, no fan, fake", "message tag, no fan, live", "chat send by path, no tag", "queue by path, live",
        "message, fan named, live", "message, fan named, fake", "mocked under live", "mocked under fake runs",
        "stream tag under live", "stream by path, no tag, live", "stream under fake starts (the guard decides)",
        "irreversible under live", "irreversible under fake starts (the guard decides)", "plain write proof",
        "read proof", "mocked wins over parking"])
def test_not_started(proof, of, fan, want):
    assert not_started(proof, of, fan) == want


def _sched(minutes):
    return {"isScheduled": 1, "scheduledDate": (AT + timedelta(minutes=minutes)).isoformat()}


@pytest.mark.parametrize("proof, method, path, body, want", [
    (P(tags={"delete_at_once"}), "POST", "/api2/v2/lists", {"name": "x"}, AT + timedelta(seconds=50)),
    (P(arm=[Write("POST", "/api2/v2/posts")], tags={"post", "delete_at_once"}), "POST", "/api2/v2/posts",
     {"text": "x"}, AT + timedelta(seconds=50)),
    (P(arm=[Write("POST", "/api2/v2/posts")], tags={"post"}), "POST", "/api2/v2/posts", _sched(31),
     AT + timedelta(minutes=21)),
    (P(arm=[Write("POST", "/api2/v2/posts")]), "POST", "/api2/v2/posts", _sched(240), AT + timedelta(minutes=230)),
    (P(arm=[Write("POST", "/api2/v2/posts")], tags={"post", "delete_at_once"}), "POST", "/api2/v2/posts",
     _sched(31), AT + timedelta(seconds=50)),
    (P(), "POST", "/api2/v2/lists", {"name": "x"}, None),
    (P(arm=[Write("POST", "/api2/v2/posts")]), "POST", "/api2/v2/posts", {"text": "x"}, None),
    (P(arm=[Write("POST", "/api2/v2/posts")]), "POST", "/api2/v2/posts", {"isScheduled": 1, "scheduledDate": "soon"},
     None),
    (P(arm=[Write("POST", "/api2/v2/lists")]), "POST", "/api2/v2/lists", _sched(31), None),
], ids=["delete-at-once list", "delete-at-once post", "scheduled 31 min", "scheduled 4 h", "both: earlier wins",
        "tracer", "unscheduled post", "unparseable schedule", "schedule keys on a non-post"])
def test_undo_deadline(proof, method, path, body, want):
    assert undo_deadline(proof, method, path, body, AT) == want


@pytest.mark.parametrize("last, now, want", [
    (None, AT, 0.0),
    (AT, AT, 5.0),
    (AT, AT + timedelta(seconds=2), 3.0),
    (AT, AT + timedelta(seconds=5), 0.0),
    (AT, AT + timedelta(seconds=9), 0.0),
], ids=["first write", "same instant", "2 s later", "exactly 5 s", "9 s later"])
def test_pace_wait(last, now, want):
    assert pace_wait(last, now) == pytest.approx(want)


def WL(seq, method, seconds, verdict="allow"):
    return {"seq": seq, "method": method, "path": "/api2/v2/lists", "verdict": verdict,
            "time": (AT + timedelta(seconds=seconds)).isoformat()}


@pytest.mark.parametrize("wire, want", [
    ([WL(1, "POST", 0), WL(2, "GET", 1, "read"), WL(3, "DELETE", 5, "reversal"), WL(4, "POST", 10.5)], []),
    ([WL(1, "POST", 0), WL(2, "POST", 1, "refused"), WL(3, "POST", 5)], []),
    ([WL(1, "POST", 0), WL(2, "DELETE", 4.9, "reversal")],
     ["wire lines 1 and 2: forwarded writes 4.9 s apart, under the 5 s pace"]),
    ([WL(2, "POST", 3), WL(1, "POST", 0)], ["wire lines 1 and 2: forwarded writes 3.0 s apart, under the 5 s pace"]),
    ([], []),
], ids=["paced, reads between", "a refused write is not paced", "reversal too soon", "out of seq order", "empty"])
def test_pace_problems(wire, want):
    assert pace_problems(wire) == want


@pytest.mark.parametrize("want, fan, waited", [("{marker}", None, "oi-proof-r1"),
                                               ("(1 day free trial)", None, "(1 day free trial)"),
                                               ("to {fan}", "7", "to 7")])
def test_text_waits_fill_marker_and_fan(want, fan, waited):
    seen = []

    class Frame:
        def wait_for_function(self, js, arg, **kw):
            seen.append(arg)

    prove._wait_text(Frame(), "body", want, "oi-proof-r1", fan)
    assert seen == [["body", waited]]


def test_text_wait_with_fan_but_no_proof_fan_is_refused():
    with pytest.raises(ValueError, match="no Proof fan"):
        prove._wait_text(object(), "body", "to {fan}", "oi-proof-r1", None)



def _log(root, folder, *rows):
    import json
    d = root / "slop" / "evidence" / folder
    d.mkdir(parents=True)
    (d / "undo-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_an_earlier_live_failed_or_not_reversible_row_refuses_the_next_live_run(tmp_path, monkeypatch):
    monkeypatch.setattr(prove, "ROOT", tmp_path)
    w = {"method": "POST", "path": "/api2/v2/chats/1/messages"}
    _log(tmp_path, "20261121T231838Z-ofm-live-aaa", {"row": 1, "proof": "p2.bubble-unsend-ppv", "state": "FAILED",
                                                      "write": w, "of_id": "9"})
    _log(tmp_path, "20261121T232000Z-ofm-live-bbb", {"row": 1, "proof": "p.x", "state": "not reversible", "write": w},
         {"row": 2, "proof": "p.y", "state": "undone", "write": w})
    _log(tmp_path, "20261121T233000Z-ofm-fake-ccc", {"row": 1, "proof": "p.z", "state": "FAILED", "write": w})
    got = prove.earlier_pending("live", "now")
    assert len(got) == 2 and "aaa/undo-log.jsonl: row 1 (p2.bubble-unsend-ppv) FAILED" in got[0] \
        and "OnlyFans id 9" in got[0] and "clear the row by hand" in got[0] and "(p.x) not reversible" in got[1], got
    assert prove.earlier_pending("fake", "now") == []
    with (tmp_path / "slop/evidence/20261121T231838Z-ofm-live-aaa/undo-log.jsonl").open("a") as f:
        f.write('{"row": 1, "state": "cleared by hand"}\n')
    assert [p for p in prove.earlier_pending("live", "now") if "aaa" in p] == []



def test_another_worktrees_unresolved_live_log_blocks_via_the_shared_index_until_cleared(tmp_path, monkeypatch):
    import run_lock
    here, there = tmp_path / "here", tmp_path / "there"
    (here / "slop" / "evidence").mkdir(parents=True)
    monkeypatch.setattr(prove, "ROOT", here)
    monkeypatch.setattr(run_lock.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    w = {"method": "POST", "path": "/api2/v2/chats/1/messages"}
    _log(there, "20261122T010000Z-ofm-live-ddd", {"row": 1, "proof": "p2.bubble-unsend-ppv", "state": "FAILED",
                                                   "write": w, "of_id": "9"})
    other = there / "slop/evidence/20261122T010000Z-ofm-live-ddd/undo-log.jsonl"
    assert prove.earlier_pending("live", "now", "creatorx") == []
    run_lock.index_update("creatorx", add=other)
    got = prove.earlier_pending("live", "now", "creatorx")
    assert len(got) == 1 and str(other.resolve()) in got[0] and "FAILED" in got[0], got
    assert prove.earlier_pending("live", "now", "othercreator") == []
    assert prove.earlier_pending("fake", "now", "creatorx") == []
    with other.open("a") as f:
        f.write('{"row": 1, "state": "cleared by hand"}\n')
    assert prove.earlier_pending("live", "now", "creatorx") == []
    assert run_lock.index_logs("creatorx") == []
    run_lock.index_update("creatorx", add=tmp_path / "gone" / "x-ofm-live-eee" / "undo-log.jsonl")
    assert "gone: check by hand" in prove.earlier_pending("live", "now", "creatorx")[0]


def test_a_live_runs_log_is_listed_while_it_runs_and_settles_out_when_resolved(tmp_path, monkeypatch):
    import run_lock
    monkeypatch.setattr(run_lock.tempfile, "gettempdir", lambda: str(tmp_path))
    log = tmp_path / "e" / "x-ofm-live-fff" / "undo-log.jsonl"
    log.parent.mkdir(parents=True)
    run_lock.index_update("c", add=log)
    log.write_text('{"row": 1, "proof": "p.x", "state": "FAILED", "write": {"method": "POST", "path": "/a"}}\n')
    prove._index_settle("c", log)
    assert run_lock.index_logs("c") == [log.resolve()]
    with log.open("a") as f:
        f.write('{"row": 1, "state": "undone"}\n')
    prove._index_settle("c", log)
    assert run_lock.index_logs("c") == []


def test_an_unreadable_shared_index_blocks_and_writes_are_atomic(tmp_path, monkeypatch):
    import run_lock
    monkeypatch.setattr(run_lock.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(prove, "ROOT", tmp_path / "here")
    run_lock.index_update("c", add=tmp_path / "e" / "x-ofm-live-ggg" / "undo-log.jsonl")
    assert not list(tmp_path.glob("*.tmp"))
    run_lock._index_path("c").write_text('["half a wri')
    got = prove.earlier_pending("live", "now", "c")
    assert len(got) == 1 and "check it by hand" in got[0], got
    with pytest.raises(ValueError):
        run_lock.index_update("c", drop=[])
    prove._index_settle("c", tmp_path / "missing" / "undo-log.jsonl")
