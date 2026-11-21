"""Seam 2, ticket 08: the driver's pure rules in proof_core: which proofs never start (`not_started`), when a post's
undo is forced (`undo_deadline`) and how long a write waits for pacing (`pace_wait`).

Expected values come from the spec (docs/spec/ofm-not-yet/phase-00-live-capture-proof-harness.md, stories 9, 10,
13, 22, 24, 28, 56) and ticket 08 as trimmed by D27 (refusal only: no owner-go run path).
"""
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
    # delete-at-once: deleted within 60 s of the write, so forced 10 s before (5 s pacing + 5 s headroom)
    (P(tags={"delete_at_once"}), "POST", "/api2/v2/lists", {"name": "x"}, AT + timedelta(seconds=50)),
    (P(arm=[Write("POST", "/api2/v2/posts")], tags={"post", "delete_at_once"}), "POST", "/api2/v2/posts",
     {"text": "x"}, AT + timedelta(seconds=50)),
    # scheduled post: undo forced 10 minutes before its time
    (P(arm=[Write("POST", "/api2/v2/posts")], tags={"post"}), "POST", "/api2/v2/posts", _sched(31),
     AT + timedelta(minutes=21)),
    (P(arm=[Write("POST", "/api2/v2/posts")]), "POST", "/api2/v2/posts", _sched(240), AT + timedelta(minutes=230)),
    (P(arm=[Write("POST", "/api2/v2/posts")], tags={"post", "delete_at_once"}), "POST", "/api2/v2/posts",
     _sched(31), AT + timedelta(seconds=50)),
    # no deadline: not a post, not delete-at-once, or a post body with no schedule
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
    """Ticket 64: a settled or trigger text wait fills `{marker}` / `{fan}` (prove._wait_text, both callers)."""
    seen = []

    class Frame:
        def wait_for_function(self, js, arg, **kw):
            seen.append(arg)

    prove._wait_text(Frame(), "body", want, "oi-proof-r1", fan)
    assert seen == [["body", waited]]


def test_text_wait_with_fan_but_no_proof_fan_is_refused():
    with pytest.raises(ValueError, match="no Proof fan"):
        prove._wait_text(object(), "body", "to {fan}", "oi-proof-r1", None)
