#!/usr/bin/env python3
from __future__ import annotations

import copy
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import events_decide as ed  # noqa: E402
from events_decide import (  # noqa: E402
    BATCH_MAX, RING_MAX, Append, Deliver, Emit, Head, Knobs, Open, Published, Resync, Rings, Send, Stream,
    coalesce, decide_ring, decide_stream, replay, window_s)

try:
    if __name__ == "__main__":
        raise ImportError
    import pytest
    table = pytest.mark.parametrize
except ImportError:
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark

E = "abc123"
A, B = "9101", "9102"
KNOBS = Knobs(min_rate=5.0, window_ms=100.0, max_window_ms=250.0)
OFF = Knobs(min_rate=5.0, window_ms=0.0, max_window_ms=250.0)


def dm(aid: str, mid: int, fan: int = 1) -> dict:
    return {"api2_chat_message": {"id": mid, "fromUser": {"id": fan}}, "__account_id": aid}


def typing(aid: str, fan: int, n: int) -> dict:
    return {"chat_typing": {"fan_id": fan, "n": n}, "__account_id": aid}


def publish(st: Rings, *frames) -> Rings:
    for f in frames:
        st = decide_ring(st, Published(f))
    return st


def flood(aid: str, n: int, st: Rings | None = None) -> Rings:
    st = st or Rings(E)
    return publish(st, *(dm(aid, st.seq + i + 1) for i in range(n)))


def connect(st: Rings, last: str | None, *, sees=(A, B), knobs=KNOBS, wants=None):
    return replay(st, last, lambda k: k in sees, wants or (lambda f: True), knobs)


def replayed(effects) -> list[int]:
    return [f["api2_chat_message"]["id"] for e in effects if isinstance(e, Emit) for f in e.frames]


def shape(effects) -> list:
    out = []
    for e in effects:
        out.append(("Emit", len(e.frames)) if isinstance(e, Emit) else
                   ("Head", e.eid) if isinstance(e, Head) else (type(e).__name__,))
    return out


def test_ids_are_one_seq_across_every_ring():
    st, seen = Rings(E), []
    for f in (dm(A, 1), dm(B, 2), {"permissions_changed": {}, "__agency": "owner-1"}, dm(A, 3)):
        st = decide_ring(st, Published(f))
        seen.append(ed.head_id(st))
    assert seen == [f"{E}.1", f"{E}.2", f"{E}.3", f"{E}.4"]
    assert {k: [s for s, _ in r] for k, r in st.rings.items()} == {A: [1, 4], B: [2], "": [3]}


@table("frame, key", [
    (dm(A, 1), A),
    ({"permissions_changed": {}, "__agency": "owner-1"}, ""),
    ({"permissions_changed": {}, "__agency": "owner-1", "__account_id": A}, ""),
    ({"toasts": {}}, ""),
    ({"toasts": {}, "__account_id": ""}, ""),
    ({"toasts": {}, "__account_id": 9101}, "9101"),
])
def test_ring_key(frame, key):
    assert ed.ring_key(frame) == key


@table("n, kept_from, evicted", [
    (RING_MAX - 1, 1, None),
    (RING_MAX, 1, None),
    (RING_MAX + 1, 2, 1),
    (RING_MAX + 10, 11, 10),
])
def test_a_ring_keeps_the_newest_ring_max(n, kept_from, evicted):
    assert RING_MAX == 256
    st = flood(A, n)
    assert [s for s, _ in st.rings[A]] == list(range(kept_from, n + 1))
    assert st.evicted.get(A) == evicted


def test_one_rings_overflow_leaves_the_others_alone():
    st = publish(Rings(E), dm(B, 1))
    st = flood(A, RING_MAX + 5, st)
    assert [s for s, _ in st.rings[B]] == [1] and B not in st.evicted and st.evicted[A] == 6


FULL = flood(A, RING_MAX + 5)


@table("last, resync, first, last_replayed", [
    (None, False, None, None),
    ("", False, None, None),
    (f"{E}.0", True, 6, 261),
    (f"{E}.4", True, 6, 261),
    (f"{E}.5", False, 6, 261),
    (f"{E}.6", False, 7, 261),
    (f"{E}.200", False, 201, 261),
    (f"{E}.260", False, 261, 261),
    (f"{E}.261", False, None, None),
    (f"{E}.262", True, None, None),
    ("other.6", True, None, None),
    ("garbage", True, None, None),
    (f"{E}.x", True, None, None),
])
def test_replay_from_a_last_id(last, resync, first, last_replayed):
    effects = connect(FULL, last)
    ids = replayed(effects)
    want = list(range(first, last_replayed + 1)) if first else []
    assert ids == want, (last, ids[:3], ids[-3:])
    assert (Resync() in effects) == resync, last
    if resync:
        assert effects[0] == Resync(), "resync goes out before anything replayed"
    assert effects[-1] == Head(f"{E}.261"), "the head comes last, the stream's id at connect"


@table("knobs, chunks", [
    (KNOBS, [("Emit", BATCH_MAX), ("Emit", 256 - BATCH_MAX)]),
    (OFF, [("Emit", 1)] * 256),
])
def test_replay_chunks(knobs, chunks):
    assert shape(connect(FULL, f"{E}.5", knobs=knobs)) == chunks + [("Head", f"{E}.261")]


def test_replay_merges_rings_in_seq_order_and_filters_what_the_stream_may_see():
    st = Rings(E)
    for i in range(1, 13):
        st = publish(st, dm((A, B, "9103")[i % 3], i))
    assert replayed(connect(st, f"{E}.2", sees=(A, B, "9103"))) == list(range(3, 13))
    assert replayed(connect(st, f"{E}.2", sees=(A,))) == [3, 6, 9, 12]
    agency = [{"permissions_changed": {"n": n}, "__agency": o} for n, o in ((1, "me"), (2, "them"))]
    st2 = publish(Rings(E), *agency)
    effects = connect(st2, f"{E}.0", sees=(), wants=lambda f: f.get("__agency") == "me")
    assert [f["permissions_changed"]["n"] for e in effects if isinstance(e, Emit) for f in e.frames] == [1]


def test_another_creators_overflow_never_resyncs_a_stream_that_cannot_see_it():
    st = publish(Rings(E), dm(B, 1))
    st = flood(A, RING_MAX + 5, st)
    assert shape(connect(st, f"{E}.0", sees=(B,))) == [("Emit", 1), ("Head", f"{E}.{RING_MAX + 6}")]
    assert Resync() in connect(st, f"{E}.0", sees=(A, B))


def test_an_agency_ring_overflow_resyncs_every_stream():
    st = publish(Rings(E), *({"toasts": {"n": i}} for i in range(RING_MAX + 1)))
    assert connect(st, f"{E}.0", sees=(), wants=lambda f: False)[0] == Resync()


def test_replay_coalesces_within_a_chunk_only():
    st = publish(Rings(E), typing(A, 7, 1), dm(A, 2), typing(A, 7, 3), typing(A, 8, 4))
    (emit, head) = connect(st, f"{E}.0")
    assert [(ed.first_key(f), f[ed.first_key(f)].get("n") or f[ed.first_key(f)]["id"]) for f in emit.frames] == [
        ("api2_chat_message", 2), ("chat_typing", 3), ("chat_typing", 4)]
    chunks = connect(st, f"{E}.0", knobs=OFF)
    assert len([e for e in chunks if isinstance(e, Emit)]) == 4, "one frame per chunk: nothing to coalesce"


def test_decide_ring_never_mutates_its_input():
    st = flood(A, RING_MAX)
    frozen = (st.seq, copy.copy(dict(st.rings)), dict(st.evicted))
    nxt = decide_ring(st, Published(dm(A, 999)))
    assert (st.seq, dict(st.rings), dict(st.evicted)) == frozen
    assert nxt.evicted == {A: 1} and st.evicted == {}


@table("rate, knobs, window", [
    (0.0, KNOBS, 0.0),
    (5.0, KNOBS, 0.0),
    (5.01, KNOBS, 0.1),
    (50.0, KNOBS, 0.1),
    (50.01, KNOBS, 0.25),
    (50.01, Knobs(5.0, 300.0, 250.0), 0.3),
    (1e6, OFF, 0.0),
    (0.01, Knobs(0.0, 100.0, 250.0), 0.25),
])
def test_window(rate, knobs, window):
    assert window_s(rate, knobs) == window


def test_rate_decays_with_tau():
    st = Stream(rate=10.0, rate_at=100.0)
    assert math.isclose(ed.rate_now(st, 101.0), 10.0 / math.e)
    nxt, _ = decide_stream(st, Deliver(101.0, False, 0, 0.0, KNOBS))
    assert math.isclose(nxt.rate, 10.0 / math.e + 1.0) and nxt.rate_at == 101.0


def _deliver(st: Stream, now: float, *, open_n=0, deadline=0.0, ends=False, knobs=KNOBS):
    return decide_stream(st, Deliver(now, ends, open_n, deadline, knobs))


@table("rate_before, open_n, deadline, now, ends, effect", [
    (0.0, 0, 0.0, 10.0, False, Send()),
    (4.0, 0, 0.0, 10.0, False, Send()),
    (5.0, 0, 0.0, 10.0, False, Open(10.1)),
    (60.0, 0, 0.0, 10.0, False, Open(10.25)),
    (60.0, 1, 10.05, 10.0, False, Append()),
    (60.0, BATCH_MAX - 1, 10.05, 10.0, False, Append()),
    (60.0, BATCH_MAX, 10.05, 10.0, False, Open(10.25)),
    (60.0, 3, 10.0, 10.0, False, Open(10.25)),
    (0.0, 3, 10.0, 10.0, False, Send()),
    (60.0, 3, 0.0, 10.0, False, Open(10.25)),
    (60.0, 3, 10.05, 10.0, True, Append(close=True)),
    (60.0, 0, 0.0, 10.0, True, Send()),
    (60.0, BATCH_MAX, 10.05, 10.0, True, Send()),
])
def test_deliver(rate_before, open_n, deadline, now, ends, effect):
    st = Stream(rate=rate_before, rate_at=now)
    nxt, got = _deliver(st, now, open_n=open_n, deadline=deadline, ends=ends)
    assert got == effect, (rate_before, open_n, deadline, ends, got)
    assert nxt == Stream(rate_before + 1.0, now)


def test_window_off_sends_everything_alone():
    st = Stream(rate_at=0.0)
    for _ in range(100):
        st, effect = _deliver(st, 0.0, knobs=OFF)
        assert effect == Send()


@table("frames, kept", [
    ([typing(A, 1, 1), typing(A, 1, 2)], [2]),
    ([typing(A, 1, 1), typing(A, 2, 2), typing(A, 1, 3)], [2, 3]),
    ([typing(A, 1, 1), typing(B, 1, 2)], [1, 2]),
    ([dm(A, 1), dm(A, 1), dm(A, 1)], [1, 1, 1]),
    ([{"chat_queue_update": {"id": 5, "n": 1}}, {"chat_queue_update": {"id": 5, "n": 2}},
      {"chat_queue_update": {"id": 6, "n": 3}}], [2, 3]),
    ([{"chat_typing": {"n": 1}}, {"chat_typing": {"n": 2}}], [1, 2]),
    ([{"chat_queue_finish": {"id": 5, "n": 1}}, {"chat_queue_finish": {"id": 5, "n": 2}}], [1, 2]),
    ([{"creator_refreshed": {"account_id": A, "n": 1}, "__account_id": A},
      {"creator_refreshed": {"account_id": B, "n": 2}, "__account_id": B},
      {"creator_refreshed": {"account_id": A, "n": 3}, "__account_id": A}], [2, 3]),
])
def test_coalesce(frames, kept):
    out = coalesce(frames)
    assert [f[ed.first_key(f)].get("n", f[ed.first_key(f)].get("id")) for f in out] == kept
    assert out[-1] is frames[-1], "the last frame is always kept (the batch keeps its id)"


def item(aid, event_type):
    return ed.PersistItem(aid, event_type, {}, {"__account_id": aid})


def pid(event_type, persistable):
    return ed.inbox_row(A, event_type, persistable)["provider_event_id"]


@table("batch, rows", [
    ([], []),
    ([item(A, "api2_chat_message")], [(A, "api2_chat_message")]),
    ([item(A, "typing")], []),
    ([item(A, "a"), item(B, "typing"), item(B, "b"), item(A, "c")], [(A, "a"), (B, "b"), (A, "c")]),
    ([item(A, None)], [(A, "unknown")]),
])
def test_persist_plan(batch, rows):
    got = ed.persist_plan(batch)
    assert [(r["account_id"], r["event_type"]) for r in got] == rows
    assert all(r["source"] == "of_ws" for r in got)


@table("persistable, want", [
    ({"id": 5}, "t:5"),
    ({"messageId": 6, "eventId": 7}, "t:6"),
    ({"eventId": 7}, "t:7"),
    ({"id": None, "eventId": 7}, "t:7"),
    ({"x": 1}, None),
    ("not a dict", None),
])
def test_inbox_row_dedup_key(persistable, want):
    assert pid("t", persistable) == want


OWNER, OTHER = "owner-1", "owner-2"
CLAMP = frozenset({A})


@table("scope, accounts, account_id, seen", [
    ("all", None, A, True),
    ("all", CLAMP, A, True),
    ("all", CLAMP, B, False),
    ("all", frozenset(), A, False),
    (f"model:{A}", None, A, True),
    (f"model:{A}", CLAMP, A, True),
    (f"model:{A}", None, B, False),
    (f"model:{B}", CLAMP, B, False),
    (f"model:{A}", CLAMP, int(A), True),
    ("all", CLAMP, int(B), False),
    ("model:", None, A, False),
    ("bogus", None, A, False),
])
def test_sees(scope, accounts, account_id, seen):
    assert ed.sees(scope, accounts, account_id) is seen


@table("scope, accounts, agencies, event, wanted", [
    ("all", CLAMP, frozenset({OWNER}), {"permissions_changed": {}, "__agency": OWNER}, True),
    (f"model:{B}", frozenset(), frozenset({OWNER}), {"permissions_changed": {}, "__agency": OWNER}, True),
    ("all", None, frozenset({OTHER}), {"permissions_changed": {}, "__agency": OWNER}, False),
    ("all", None, frozenset(), {"permissions_changed": {}, "__agency": OWNER}, False),
    ("all", CLAMP, frozenset({"1"}), {"permissions_changed": {}, "__agency": 1}, True),
    ("all", CLAMP, frozenset({OTHER}), {"permissions_changed": {}, "__agency": OWNER, "__account_id": A},
     False),
    ("all", None, frozenset(), {"toasts": {}}, True),
    ("all", CLAMP, frozenset({OWNER}), {"toasts": {}}, False),
    (f"model:{A}", None, frozenset(), {"toasts": {}}, False),
    ("all", CLAMP, frozenset({OWNER}), dm(A, 1), True),
    ("all", CLAMP, frozenset({OWNER}), dm(B, 1), False),
    ("all", None, frozenset(), dm(B, 1), True),
    (f"model:{A}", None, frozenset(), dm(A, 1), True),
    (f"model:{A}", None, frozenset(), dm(B, 1), False),
    ("all", CLAMP, frozenset(), {"toasts": {}, "__account_id": int(A)}, True),
])
def test_wants(scope, accounts, agencies, event, wanted):
    assert ed.wants(scope, accounts, agencies, event) is wanted


@table("event, account_id, noise", [
    ({"post_published": {"id": 1, "user_id": int(A)}}, A, False),
    ({"post_published": {"id": 1, "user_id": A}}, int(A), False),
    ({"post_published": {"id": 1, "user_id": 77}}, A, True),
    ({"post_published": {"id": 1, "user_id": int(A)}}, None, True),
    ({"post_expire": {"id": 1}}, A, True),
    ({"post_updated": {"id": 1}, "__account_id": A}, A, True),
    ({"post_fundraising_updated": {"id": 1}}, A, True),
    ({"post_published": "x"}, A, True),
    ({"api2_chat_message": {"id": 1}}, A, False),
    ("not a dict", A, False),
])
def test_is_feed_noise(event, account_id, noise):
    assert ed.is_feed_noise(event, account_id) is noise


@table("payload, fan", [
    ({"id": 501}, 501),
    ({"id": "501"}, 501),
    ({"user_id": 502}, 502),
    ({"fromUser": {"id": 503}}, 503),
    ({"user": {"id": 504}}, 504),
    ({"id": "x", "user_id": 505}, 505),
    ({"id": 1, "user_id": 2}, 1),
    ({"fromUser": "x", "user": {"id": 506}}, 506),
    ({}, None),
    (None, None),
    ([501], None),
])
def test_typing_fan_id(payload, fan):
    assert ed.typing_fan_id(payload) == fan


@table("last_at, now, due", [
    (None, 0.0, True),
    (10.0, 10.0, False),
    (10.0, 12.999, False),
    (10.0, 13.0, True),
    (10.0, 20.0, True),
])
def test_typing_due(last_at, now, due):
    assert ed.typing_due(last_at, now, 3.0) is due


def test_sse_types():
    assert ed.STATE_TYPES <= ed.SSE_TYPES
    assert ed.ENDS_STREAM <= ed.STATE_TYPES
    assert not (ed.FEED_POST_TYPES & ed.SSE_TYPES)
    assert "typing" not in ed.SSE_TYPES and "chat_typing" in ed.SSE_TYPES
    assert "creator_refreshed" in ed.SSE_TYPES and "creator_refreshed" not in ed.STATE_TYPES
    assert ed.COALESCE == {"chat_typing": "fan_id", "chat_queue_update": "id", "creator_refreshed": "account_id"}


def _ended_rings(*frames, evicted=None):
    return ed.Rings(E, len(frames), {"": tuple((i + 1, f) for i, f in enumerate(frames))},
                    {"": evicted} if evicted is not None else {})


_END = {"permissions_changed": {}}
_OTHER = {"chat_responded": {"fan_id": 1}}


def test_ended_since(frames, since, evicted, wants, expected):
    assert ed.ended_since(_ended_rings(*frames, evicted=evicted), since, lambda f: wants) is expected


test_ended_since.rows = [
    ((_END,), 1, None, True, False),
    ((_OTHER, _END), 1, None, True, True),
    ((_OTHER, _END), 1, None, False, False),
    ((_END, _OTHER), 1, None, True, False),
    ((), 5, 5, True, False),
    ((), 5, 6, True, True),
]


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
