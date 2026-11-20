#!/usr/bin/env python3
"""events_decide's any-scope routing (phase-01 1b, ticket 23): `creator_warmed` and the money events the rail and bell
seed from (`transaction_recorded`, `purchase_notified`, a `toasts` frame carrying a tip or purchase toast) reach a
model-scoped subscriber for any Creator in its accessible set (the `accounts` clamp the Relay resolves at subscribe,
owner or chatter), not only the Creator its scope names. Never one outside that set (another Agency's), never an
unclamped subscriber's other Creators; every other type routes as before (scope, then the clamp).

Pure tables over `events_decide.wants` (the shell's one routing read). Runs as a script (repo convention) or pytest:
    ./venv/bin/python service/tests/test_events_any_scope.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import events_decide as ed  # noqa: E402

try:
    if __name__ == "__main__":
        raise ImportError  # script mode uses the runner below, even with pytest installed
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark

A, B, C = "9201", "9202", "9301"          # A and B: one Agency's Creators; C: another Agency's
MINE = frozenset({A, B})                   # the subscriber's accessible set (owner's, or a chatter's union)
OWNER = "owner-1"


def warmed(aid) -> dict:
    return {"creator_warmed": {"account_id": str(aid), "at": "2026-11-09T10:00:00Z"}, "__account_id": aid}


def tx(aid) -> dict:
    return {"transaction_recorded": {"fan_id": 7}, "__account_id": aid}


def bought(aid) -> dict:
    return {"purchase_notified": {"notif_id": "1", "fan_id": 7}, "__account_id": aid}


def toast(aid, *types: str) -> dict:
    return {"toasts": [{"id": i, "type": t, "text": "x"} for i, t in enumerate(types)], "__account_id": aid}


def replied(aid) -> dict:
    return {"chat_responded": {"fan_id": 7, "by": "", "at": 1}, "__account_id": aid}


def refreshed(aid) -> dict:
    return {"creator_refreshed": {"account_id": str(aid), "seq": 1}, "__account_id": aid}


def dm(aid) -> dict:
    return {"api2_chat_message": {"id": 1, "fromUser": {"id": 7}}, "__account_id": aid}


@table("scope, accounts, event, wanted", [
    # A tab scoped to A gets B's warm and money events: B is in its accessible set.
    (f"model:{A}", MINE, warmed(B), True),
    (f"model:{A}", MINE, tx(B), True),
    (f"model:{A}", MINE, bought(B), True),
    (f"model:{A}", MINE, toast(B, "tip"), True),
    (f"model:{A}", MINE, toast(B, "tips"), True),
    (f"model:{A}", MINE, toast(B, "purchases"), True),
    (f"model:{A}", MINE, toast(B, "paided_message"), True),
    (f"model:{A}", MINE, toast(B, "favorited", "tip"), True),       # one money toast in the frame is enough
    (f"model:{A}", MINE, warmed(int(B)), True),
    (f"model:{A}", MINE, replied(B), True),                          # a reply moves B's row in A's All Models lists
    (f"model:{A}", MINE, replied(C), False),
    (f"model:{A}", None, replied(B), False),                      # an int id compares as its str
    (f"model:{A}", MINE, refreshed(B), True),                        # the Shared refresher's snapshot, any tab of B
    (f"model:{A}", MINE, refreshed(C), False),                       # ... never past the clamp
    (f"model:{A}", None, refreshed(B), False),
    # ... never another Agency's Creator, whatever the type.
    (f"model:{A}", MINE, warmed(C), False),
    (f"model:{A}", MINE, tx(C), False),
    (f"model:{A}", MINE, bought(C), False),
    (f"model:{A}", MINE, toast(C, "tip"), False),
    # ... nor for a subscriber with no accessible set (unclamped: the anonymous escape hatch).
    (f"model:{A}", None, warmed(B), False),
    (f"model:{A}", None, tx(B), False),
    (f"model:{A}", frozenset(), warmed(B), False),
    # Every other type routes as before: the scope names the Creator, then the clamp.
    (f"model:{A}", MINE, dm(B), False),
    (f"model:{A}", MINE, toast(B, "favorited"), False),               # a like is not money
    (f"model:{A}", MINE, toast(B, "subscribed", "commented"), False),
    (f"model:{A}", MINE, {"toasts": {"id": 1, "type": "tip"}, "__account_id": B}, False),  # not OF's list shape
    (f"model:{A}", MINE, {"session_dead": {"dead": True}, "__account_id": B}, False),
    (f"model:{A}", MINE, {"chat_typing": {"fan_id": 7}, "__account_id": B}, False),
    (f"model:{A}", MINE, dm(A), True),
    (f"model:{A}", MINE, warmed(A), True),                           # its own Creator, as before
    ("all", MINE, warmed(B), True),
    ("all", MINE, warmed(C), False),
    ("all", None, warmed(C), True),                                  # unclamped "all" as before
    ("bogus", MINE, warmed(B), False),                               # an unknown scope still sees nothing
    # Agency-wide events keep their audience rule.
    (f"model:{A}", MINE, {"creator_warmed": {"account_id": B}, "__agency": "owner-2"}, False),
])
def test_any_scope(scope, accounts, event, wanted):
    assert ed.wants(scope, accounts, frozenset({OWNER}), event) is wanted, (scope, accounts, event)


def test_types():
    assert "creator_warmed" in ed.SSE_TYPES and "creator_refreshed" in ed.SSE_TYPES
    assert ed.ANY_SCOPE_TYPES == frozenset({"creator_warmed", "creator_refreshed", "chat_read_changed",
                                         "chat_responded", "transaction_recorded", "purchase_notified", "toasts"})
    assert ed.ANY_SCOPE_TYPES <= ed.SSE_TYPES
    assert not (ed.ANY_SCOPE_TYPES & ed.STATE_TYPES)


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
