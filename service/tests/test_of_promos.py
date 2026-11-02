#!/usr/bin/env python3
"""of_promos: the pure OF promo/trial helpers as tables. No DB use, no relay, no I/O.

Pins: to_cents IS of_coerce.cents_or_zero (its table lives in test_of_coerce.py). coerce_of_id is
plain int(): floats truncate, bools are ints, "123"/" 12 " parse, "12.0"/"1e3"/""/None/junk → None.
safe_int is int(float(v)): "30.0"/"1e3" parse, bool → 0/1, junk/None/NaN → default; ±inf RAISES
(BUG, see below). of_field returns the first listed key whose value is not None, else default;
falsy non-None values (0, "", False) win. normalise_of_promo reads camelCase first, snake_case /
alt spellings after; missing fields → id None, 0 counts, "" message, type "all"; is_live = not
isFinished AND canClaim is not False (absent canClaim never kills it); no nested `data` unwrap.
normalise_of_trial: name from name then trialLinkName, url from url/shareUrl/link, liveness off
isFinished only. promo_type_store sorts to "all", "expired", "all,expired" and ValueErrors on
empty/unknown; promo_type_body inverts it (unknown parts dropped, empty/None → "all") and
store(body(s)) == s for every canonical stored value; a non-canonical one comes back canonical.
extract_created_promo: list → first dict, {"items":[…]} → first dict, other dict → itself,
anything else → {}. _rows_from_payload: a list as-is; a dict's
first non-None key in order, list or None; no nested `data`; other junk → None.

BUG (asserted as current behaviour, `# BUG: see PR`): safe_int / coerce_of_id let OverflowError
out on ±inf (Python's json.loads reads `Infinity`), against "must NEVER 500" / "drift-safe".

Runs under pytest (parametrized tables) or as a script (the repo's convention, no pytest needed):
    ./venv/bin/python service/tests/test_of_promos.py
"""
from __future__ import annotations

import _harness  # noqa: F401 — MUST be first: of_promos → automation_executor → db.engine

from of_coerce import cents_or_zero  # noqa: E402
from of_promos import (  # noqa: E402
    _rows_from_payload, coerce_of_id, extract_created_promo, normalise_of_promo, normalise_of_trial,
    of_field, promo_type_body, promo_type_store, safe_int, to_cents)

try:
    import pytest
    table = pytest.mark.parametrize
except ImportError:  # script mode: the runner below calls each row
    def table(names, rows):
        def mark(fn):
            fn.rows = rows
            return fn
        return mark

INF = float("inf")


def _call(fn, *a):
    """fn(*a), or the exception class it raised (rows assert raises as a value)."""
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        return type(e)


def test_to_cents_alias():
    assert to_cents is cents_or_zero      # full table: test_of_coerce.py::test_cents


@table("v,want", [
    (123, 123),
    ("123", 123),
    (" 12 ", 12),           # int() strips whitespace
    ("0", 0),
    ("", None),
    (None, None),
    ("abc", None),
    ("12.0", None),         # int("12.0") ValueError
    ("1e3", None),
    (12.7, 12),             # float truncates toward 0
    (-12.7, -12),
    (True, 1),              # bool is an int
    ({}, None),
    ([1], None),
    (INF, OverflowError),   # BUG: see PR — "drift-safe" but raises
])
def test_coerce_of_id(v, want):
    assert _call(coerce_of_id, v) == want


@table("v,default,want", [
    (30, 0, 30),
    ("30", 0, 30),
    ("30.0", 0, 30),
    ("30.9", 0, 30),
    (" 7 ", 0, 7),
    ("1e3", 0, 1000),
    (True, 0, 1),
    (False, 9, 0),          # bool short-circuits, never the default
    (None, 0, 0),
    ("abc", 0, 0),
    ("", 0, 0),
    ({}, 0, 0),
    ([], 0, 0),
    ({"a": 1}, 5, 5),
    ("abc", -1, -1),
    (None, 7, 7),
    (float("nan"), 3, 3),   # int(nan) ValueError → default
    (INF, 0, OverflowError),     # BUG: see PR — "must NEVER 500" but raises
    ("-inf", 0, OverflowError),  # BUG: see PR
])
def test_safe_int(v, default, want):
    assert _call(safe_int, v, default) == want


@table("item,names,default,want", [
    ({"a": 1, "b": 2}, ("a", "b"), None, 1),
    ({"a": None, "b": 2}, ("a", "b"), None, 2),     # None skipped
    ({"b": 2}, ("a", "b"), None, 2),
    ({"a": 0, "b": 2}, ("a", "b"), None, 0),        # falsy non-None wins
    ({"a": "", "b": 2}, ("a", "b"), None, ""),
    ({"a": False}, ("a",), True, False),
    ({}, ("a", "b"), "d", "d"),
    ({"a": None}, ("a",), "d", "d"),
    ({"a": 1}, (), "d", "d"),
    ({"b": 2, "a": 1}, ("a", "b"), None, 1),        # names order, not dict order
])
def test_of_field(item, names, default, want):
    assert of_field(item, *names, default=default) == want


@table("item,want", [
    # liveness: isFinished × canClaim
    ({}, (False, "active", None)),
    ({"isFinished": False}, (False, "active", None)),
    ({"isFinished": False, "canClaim": True}, (False, "active", True)),
    ({"isFinished": False, "canClaim": False}, (True, "finished", False)),   # Ava's spent 9
    ({"isFinished": True}, (True, "finished", None)),
    ({"isFinished": True, "canClaim": True}, (True, "finished", True)),
    ({"isFinished": None, "canClaim": None}, (False, "active", None)),
    ({"canClaim": 0}, (False, "active", 0)),             # only an explicit False kills
    ({"isFinished": "false"}, (True, "finished", None)),  # bool("false") is True — as coded
    ({"isFinished": 0}, (False, "active", None)),
])
def test_promo_liveness(item, want):
    p = normalise_of_promo(item)
    assert (p["is_finished"], p["status"], p["can_claim"]) == want


def test_promo_defaults():
    assert normalise_of_promo({}) == {
        "of_promo_id": None, "price_cents": 0, "subscribe_counts": 0, "subscribe_days": 0,
        "message": "", "promo_type": "all", "created_at": None, "subscriber_count": 0,
        "can_claim": None, "is_finished": False, "status": "active"}


@table("item,key,want", [
    ({"id": 5}, "of_promo_id", 5),
    ({"id": "5"}, "of_promo_id", 5),
    ({"id": None, "promoId": 6}, "of_promo_id", 6),
    ({"promoId": "x"}, "of_promo_id", None),
    ({"id": 5, "promoId": 6}, "of_promo_id", 5),
    ({"price": "4.99"}, "price_cents", 499),
    ({"price": None}, "price_cents", 0),
    ({"subscribeCounts": "10"}, "subscribe_counts", 10),
    ({"subscribe_counts": 11}, "subscribe_counts", 11),
    ({"subscribeCounts": 1, "subscribe_counts": 2}, "subscribe_counts", 1),   # camelCase first
    ({"subscribeDays": "30.0"}, "subscribe_days", 30),
    ({"subscribe_days": {}}, "subscribe_days", 0),
    ({"message": "hi"}, "message", "hi"),
    ({"message": None, "text": "t"}, "message", "t"),
    ({"type": "expired"}, "promo_type", "expired"),
    ({"type": None}, "promo_type", "all"),
    ({"createdAt": "2026-07-22"}, "created_at", "2026-07-22"),
    ({"claimsCount": 3}, "subscriber_count", 3),
    ({"countSubscribers": 4}, "subscriber_count", 4),
    ({"subscribersCount": "5"}, "subscriber_count", 5),
    ({"claimsCount": None, "countSubscribers": 4}, "subscriber_count", 4),
    ({"data": {"id": 9, "claimsCount": 3}}, "of_promo_id", None),   # no nested unwrap
])
def test_promo_fields(item, key, want):
    assert normalise_of_promo(item)[key] == want


def test_trial_defaults():
    assert normalise_of_trial({}) == {
        "of_trial_id": None, "name": "", "url": None, "subscribe_days": 0, "subscribe_counts": 0,
        "claim_counts": 0, "clicks_count": 0, "expired_at": None, "created_at": None,
        "is_finished": False, "status": "active"}


@table("item,key,want", [
    ({"id": "7"}, "of_trial_id", 7),
    ({"trialId": 8}, "of_trial_id", 8),
    ({"id": "x", "trialId": 8}, "of_trial_id", None),     # "x" is present → wins, coerces to None
    ({"trialLinkName": "IG"}, "name", "IG"),
    ({"name": "N", "trialLinkName": "IG"}, "name", "N"),
    ({"name": None, "trialLinkName": "IG"}, "name", "IG"),
    ({"shareUrl": "s"}, "url", "s"),
    ({"link": "l"}, "url", "l"),
    ({"url": "u", "link": "l"}, "url", "u"),
    ({"subscribeDays": "7"}, "subscribe_days", 7),
    ({"subscribe_days": 3}, "subscribe_days", 3),
    ({"subscribe_counts": "2.0"}, "subscribe_counts", 2),
    ({"claimCounts": 1}, "claim_counts", 1),
    ({"claimsCount": 2}, "claim_counts", 2),
    ({"usedCount": "3"}, "claim_counts", 3),
    ({"clicksCounts": 4}, "clicks_count", 4),
    ({"clickCounts": "5"}, "clicks_count", 5),
    ({"clicksCounts": []}, "clicks_count", 0),
    ({"expiredAt": "e", "createdAt": "c"}, "expired_at", "e"),
    ({"isFinished": True}, "status", "finished"),
    ({"isFinished": True}, "is_finished", True),
    ({"isFinished": False, "canClaim": False}, "status", "active"),   # trials ignore canClaim
    ({"isFinished": None}, "status", "active"),
])
def test_trial_fields(item, key, want):
    assert normalise_of_trial(item)[key] == want


@table("value,want", [
    ("all", "all"),
    ("expired", "expired"),
    (["all"], "all"),
    (["expired", "all"], "all,expired"),       # canonical order
    (("all", "expired", "all"), "all,expired"),
    ("", ValueError),
    (None, ValueError),
    ([], ValueError),
    ("both", ValueError),
    ("all,expired", ValueError),               # the stored form is not a create value
    (["all", "x"], ValueError),
])
def test_promo_type_store(value, want):
    assert _call(promo_type_store, value) == want


@table("stored,want", [
    ("all", "all"),
    ("expired", "expired"),
    ("all,expired", ["all", "expired"]),
    (None, "all"),
    ("", "all"),
    ("junk", "all"),
    ("junk,expired", "expired"),
    ("expired,all", ["expired", "all"]),       # order as stored
])
def test_promo_type_body(stored, want):
    assert promo_type_body(stored) == want


@table("stored,want", [
    ("all", "all"),
    ("expired", "expired"),
    ("all,expired", "all,expired"),
    ("expired,all", "all,expired"),            # non-canonical → canonical order
    ("junk", "all"),
    ("junk,expired", "expired"),
    (None, "all"),
    ("", "all"),
])
def test_promo_type_round_trip(stored, want):
    assert promo_type_store(promo_type_body(stored)) == want


@table("res,want", [
    ([{"id": 1}], {"id": 1}),
    ([{"id": 1}, {"id": 2}], {"id": 1}),
    ({"items": [{"id": 3}]}, {"id": 3}),
    ({"id": 4}, {"id": 4}),
    ({"items": []}, {"items": []}),            # wrapper with nothing → the wrapper itself
    ({"items": [5]}, {"items": [5]}),
    ({}, {}),
    ([], {}),
    ([1], {}),
    (["x", {"id": 1}], {}),                    # only res[0] is looked at
    (None, {}),
    ("x", {}),
    (7, {}),
])
def test_extract_created_promo(res, want):
    assert extract_created_promo(res) == want


IL = ("items", "list")
LI = ("list", "items")


@table("raw,keys,want", [
    ([], IL, []),
    ([{"id": 1}, 2], IL, [{"id": 1}, 2]),         # items untouched; the pager skips non-dicts
    ({"items": [1]}, IL, [1]),
    ({"list": [2]}, IL, [2]),
    ({"items": [1], "list": [2]}, IL, [1]),
    ({"items": [1], "list": [2]}, LI, [2]),
    ({"items": None, "list": [2]}, IL, [2]),      # None skipped
    ({"items": {}, "list": [2]}, IL, None),       # first non-None non-list → unusable
    ({"items": "x"}, IL, None),
    ({"data": {"list": [1]}}, IL, None),          # no nested `data` unwrap
    ({"rows": [1]}, IL, None),
    ({}, IL, None),
    ({"items": [1]}, (), None),
    (None, IL, None),
    ("x", IL, None),
    ((1, 2), IL, None),
    (7, IL, None),
])
def test_rows_from_payload(raw, keys, want):
    assert _rows_from_payload(raw, keys) == want


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            for row in getattr(fn, "rows", [()]):
                fn(*(row if isinstance(row, tuple) else (row,)))
                n += 1
    print(f"all {n} cases passed")
