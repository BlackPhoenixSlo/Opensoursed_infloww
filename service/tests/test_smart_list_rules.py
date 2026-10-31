#!/usr/bin/env python3
"""smart_list_rules — table tests over the pure Smart Lists rule engine (the shell
is smart_lists_api: it loads normalised fans from the DB and maps a 422 to the
route). No DB, no loop:

  case_numeric_table:     every numeric op incl. between, on a v1 top-level field
                          (lifetime_spend), a ledger fact (total_spend:creator:all)
                          and last_active_days (None never matches).
  case_date_table:        within_last / more_than / between, expires_at
                          within_next; a missing date never matches.
  case_enum_table:        status / renew ==, != (case-insensitive); other ops False.
  case_tag_table:         has / not_has (case-insensitive); other ops False.
  case_resolve_match:     blank rules = everyone; all vs any; fan_id None skipped;
                          output sorted.
  case_validate_errors:   unknown field / unknown op per field kind / bad values ->
                          422 with the exact text the routes always answered.
  case_max_rules:         _MAX_RULES rules accepted, one more -> 422 "at most 20 rules".
  case_validate_defaults: scope / timeframe / days defaults; values coerced.
  case_rule_readers:      recent_spend windows (default 30, clamped 1..3650, bad
                          days skipped); which fields read the roster snapshot.
  case_reexported:        smart_lists_api re-exports the names it and its importers use
                          as the same objects.

Run: ./venv/bin/python service/tests/test_smart_list_rules.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

from fastapi import HTTPException  # noqa: E402

import smart_list_rules as R  # noqa: E402
from smart_list_rules import _eval_rule, _validate_rules, resolve  # noqa: E402

_OPS_NUM = (">", ">=", "<", "<=", "==", "!=")


def _fan(**kw) -> dict:
    return {"fan_id": 1, **kw}


def case_numeric_table():
    # (fan, rule, expected)
    rows = []
    for field, fan in (
        ("lifetime_spend", _fan(lifetime_spend=500)),
        ("total_spend", _fan(facts={"total_spend:creator:all": 500})),
        ("last_active_days", _fan(last_active_days=500)),
    ):
        for op, v, want in (
            (">", 499, True), (">", 500, False),
            (">=", 500, True), (">=", 501, False),
            ("<", 501, True), ("<", 500, False),
            ("<=", 500, True), ("<=", 499, False),
            ("==", 500, True), ("==", 499, False),
            ("!=", 499, True), ("!=", 500, False),
            ("between", [400, 600], True), ("between", [500, 500], True),
            ("between", [501, 600], False),
            ("has", 500, False),  # not a numeric op
        ):
            rows.append((fan, {"field": field, "op": op, "value": v}, want))
    # scoped / timeframed ledger key, missing fact = 0
    rows += [
        (_fan(facts={"tips_spend:org:30d": 900}),
         {"field": "tips_spend", "op": ">=", "value": 900, "scope": "org", "timeframe": "30d"}, True),
        (_fan(facts={"tips_spend:org:30d": 900}),
         {"field": "tips_spend", "op": ">=", "value": 900}, False),
        (_fan(), {"field": "total_spend", "op": "==", "value": 0}, True),
        (_fan(last_active_days=None), {"field": "last_active_days", "op": ">=", "value": 0}, False),
        (_fan(recent_spend={30: 700}), {"field": "recent_spend", "op": ">=", "value": 700}, True),
        (_fan(recent_spend={"7": 700}),
         {"field": "recent_spend", "op": ">=", "value": 700, "days": 7}, True),
        (_fan(recent_spend={7: 700}), {"field": "recent_spend", "op": ">=", "value": 700}, False),
    ]
    for fan, rule, want in rows:
        got = _eval_rule(rule, fan)
        assert got is want, f"{rule} on {fan}: {got} != {want}"


def case_date_table():
    def f(ago):
        return _fan(facts={"sub_start": ago, "expires_at": ago})
    rows = [
        (f(3), "sub_start", "within_last", 7, True),
        (f(7), "sub_start", "within_last", 7, True),
        (f(8), "sub_start", "within_last", 7, False),
        (f(-1), "sub_start", "within_last", 7, False),  # future date is not "last"
        (f(31), "sub_start", "more_than", 30, True),
        (f(30), "sub_start", "more_than", 30, False),
        (f(10), "sub_start", "between", [5, 10], True),
        (f(5), "sub_start", "between", [5, 10], True),
        (f(11), "sub_start", "between", [5, 10], False),
        (f(-2), "expires_at", "within_next", 3, True),
        (f(-3), "expires_at", "within_next", 3, True),
        (f(-4), "expires_at", "within_next", 3, False),
        (f(0), "expires_at", "within_next", 3, False),  # already passed / now
        (f(None), "sub_start", "within_last", 9999, False),
        (f(None), "sub_start", "more_than", 0, False),
        (f(3), "sub_start", ">=", 0, False),  # not a date op
    ]
    for fan, field, op, v, want in rows:
        got = _eval_rule({"field": field, "op": op, "value": v}, fan)
        assert got is want, f"{field} {op} {v} on {fan}: {got} != {want}"
    # scoped date key
    fan = _fan(facts={"last_purchase_at:org": 2})
    assert _eval_rule({"field": "last_purchase_at", "op": "within_last", "value": 3,
                       "scope": "org"}, fan) is True
    assert _eval_rule({"field": "last_purchase_at", "op": "within_last", "value": 3}, fan) is False


def case_enum_table():
    rows = [
        (_fan(status="active"), "status", "==", "active", True),
        (_fan(status="Active"), "status", "==", "ACTIVE", True),
        (_fan(status="expired"), "status", "==", "active", False),
        (_fan(status="expired"), "status", "!=", "active", True),
        (_fan(status="active"), "status", "!=", "active", False),
        (_fan(status=None), "status", "!=", "active", True),
        (_fan(renew="off"), "renew", "==", "off", True),
        (_fan(renew="on"), "renew", "==", "off", False),
        (_fan(renew="on"), "renew", "!=", "off", True),
        (_fan(renew=None), "renew", "==", "off", False),
        (_fan(status="active"), "status", "has", "active", False),
    ]
    for fan, field, op, v, want in rows:
        got = _eval_rule({"field": field, "op": op, "value": v}, fan)
        assert got is want, f"{field} {op} {v} on {fan}: {got} != {want}"


def case_tag_table():
    rows = [
        (_fan(tags=["whale", "vip"]), "has", "whale", True),
        (_fan(tags=["Whale"]), "has", "WHALE", True),
        (_fan(tags=["vip"]), "has", "whale", False),
        (_fan(tags=None), "has", "whale", False),
        (_fan(tags=["vip"]), "not_has", "whale", True),
        (_fan(tags=["whale"]), "not_has", "whale", False),
        (_fan(tags=None), "not_has", "whale", True),
        (_fan(tags=["whale"]), "==", "whale", False),
    ]
    for fan, op, v, want in rows:
        got = _eval_rule({"field": "tag", "op": op, "value": v}, fan)
        assert got is want, f"tag {op} {v} on {fan}: {got} != {want}"
    assert _eval_rule({"field": "bogus", "op": "==", "value": 1}, _fan()) is False


def case_resolve_match():
    fans = [
        {"fan_id": 3, "lifetime_spend": 100, "tags": ["vip"]},
        {"fan_id": 1, "lifetime_spend": 900, "tags": []},
        {"fan_id": 2, "lifetime_spend": 900, "tags": ["vip"]},
        {"fan_id": None, "lifetime_spend": 900, "tags": ["vip"]},
    ]
    big = {"field": "lifetime_spend", "op": ">=", "value": 500}
    vip = {"field": "tag", "op": "has", "value": "vip"}
    rows = [
        (None, [1, 2, 3]),
        ({}, [1, 2, 3]),
        ({"rules": []}, [1, 2, 3]),
        ({"rules": [big]}, [1, 2]),
        ({"rules": [big, vip]}, [2]),
        ({"match": "all", "rules": [big, vip]}, [2]),
        ({"match": "ANY", "rules": [big, vip]}, [1, 2, 3]),
        ({"match": "nonsense", "rules": [big, vip]}, [2]),  # anything but any = all
    ]
    for rules, want in rows:
        got = resolve(rules, fans)
        assert got == want, f"{rules}: {got} != {want}"


def _err(rules_obj) -> tuple[int, str]:
    try:
        _validate_rules(rules_obj)
    except HTTPException as e:
        return e.status_code, e.detail
    raise AssertionError(f"accepted: {rules_obj}")


def case_validate_errors():
    def one(**r):
        return {"rules": [r]}
    rows = [
        ("x", "rules must be an object"),
        ({"match": "some"}, "match must be 'all' or 'any'"),
        ({"rules": {"a": 1}}, "rules.rules must be a list"),
        ({"rules": ["x"]}, "each rule must be an object"),
        # unknown field
        (one(field="bogus", op="==", value=1), "unknown field 'bogus'"),
        (one(op="==", value=1), "unknown field None"),
        # unknown op, per field kind
        (one(field="lifetime_spend", op="has", value=1),
         "lifetime_spend needs a numeric operator (!=, <, <=, ==, >, >=, between)"),
        (one(field="total_spend", op="within_last", value=1),
         "total_spend needs a numeric operator (!=, <, <=, ==, >, >=, between)"),
        (one(field="sub_start", op=">=", value=1),
         "sub_start needs one of between, more_than, within_last"),
        (one(field="sub_start", op="within_next", value=1),
         "sub_start needs one of between, more_than, within_last"),
        (one(field="expires_at", op="==", value=1),
         "expires_at needs one of between, more_than, within_last, within_next"),
        (one(field="status", op="has", value="active"), "status needs == or !="),
        (one(field="renew", op=">", value="on"), "renew needs == or !="),
        (one(field="tag", op="==", value="vip"), "tag needs 'has' or 'not_has'"),
        # bad values
        (one(field="lifetime_spend", op=">=", value="lots"), "lifetime_spend value must be a number"),
        (one(field="lifetime_spend", op=">=", value=None), "lifetime_spend value must be a number"),
        (one(field="tips_spend", op="between", value=5), "tips_spend between needs [low, high]"),
        (one(field="tips_spend", op="between", value=[1, 2, 3]), "tips_spend between needs [low, high]"),
        (one(field="tips_spend", op="between", value=[5, 1]), "tips_spend between needs low <= high"),
        (one(field="sub_start", op="within_last", value=-1), "sub_start days cannot be negative"),
        (one(field="sub_start", op="between", value=[-1, 3]), "sub_start days cannot be negative"),
        (one(field="recent_spend", op=">=", value=1, days="x"), "recent_spend days must be an integer"),
        (one(field="status", op="==", value="paused"), "status must be one of active, expired"),
        (one(field="renew", op="==", value=None), "renew must be one of on, off"),
        (one(field="tag", op="has", value=""), "tag value cannot be blank"),
        (one(field="total_spend", op=">=", value=1, scope="team"), "scope must be one of creator, org"),
        (one(field="last_purchase_at", op="within_last", value=1, scope="team"),
         "scope must be one of creator, org"),
        (one(field="total_spend", op=">=", value=1, timeframe="1y"),
         "timeframe must be one of all, today, yesterday, this_week, 7d, 30d, 90d"),
    ]
    for rules_obj, want in rows:
        got = _err(rules_obj)
        assert got == (422, want), f"{rules_obj}: {got} != (422, {want!r})"


def case_max_rules():
    assert R._MAX_RULES == 20
    rule = {"field": "tag", "op": "has", "value": "vip"}
    ok = _validate_rules({"rules": [rule] * R._MAX_RULES})
    assert len(ok["rules"]) == R._MAX_RULES
    assert _err({"rules": [rule] * (R._MAX_RULES + 1)}) == (422, "at most 20 rules")


def case_validate_defaults():
    assert _validate_rules(None) == {"match": "all", "rules": []}
    assert _validate_rules({}) == {"match": "all", "rules": []}
    got = _validate_rules({"match": "ANY", "rules": [
        {"field": "total_spend", "op": ">=", "value": "100"},
        {"field": "last_spend_amount", "op": "<", "value": 5},
        {"field": "last_purchase_at", "op": "between", "value": [1, "2"]},
        {"field": "recent_spend", "op": ">", "value": 1},
        {"field": "recent_spend", "op": ">", "value": 1, "days": 99999},
        {"field": "status", "op": "==", "value": "ACTIVE"},
        {"field": "tag", "op": "not_has", "value": 7},
        {"field": "expires_at", "op": "within_next", "value": 3},
    ]})
    assert got == {"match": "any", "rules": [
        {"field": "total_spend", "op": ">=", "value": 100.0, "scope": "creator", "timeframe": "all"},
        {"field": "last_spend_amount", "op": "<", "value": 5.0, "scope": "creator"},
        {"field": "last_purchase_at", "op": "between", "value": [1.0, 2.0], "scope": "creator"},
        {"field": "recent_spend", "op": ">", "value": 1.0, "days": 30},
        {"field": "recent_spend", "op": ">", "value": 1.0, "days": 3650},
        {"field": "status", "op": "==", "value": "active"},
        {"field": "tag", "op": "not_has", "value": "7"},
        {"field": "expires_at", "op": "within_next", "value": 3.0},
    ]}, got
    assert R.fact_key({"field": "tips_spend", "scope": "org", "timeframe": "7d"}) == "tips_spend:org:7d"
    assert R.fact_key({"field": "last_spend_amount"}) == "last_spend_amount:creator"
    assert R.fact_key({"field": "sub_start", "scope": "org"}) == "sub_start"


def case_rule_readers():
    rs = lambda **kw: {"field": "recent_spend", "op": ">", "value": 1, **kw}  # noqa: E731
    assert R._windows_in_rules({"rules": [rs(), rs(days=-5), rs(days=99999), rs(days="x"),
                                          rs(days=7), {"field": "tag", "days": 5}]}) == {30, 1, 3650, 7}
    assert R._windows_in_rules({}) == set()
    assert R.uses_subscription_facts({"rules": [{"field": "idle_days"}]})
    assert not R.uses_subscription_facts({"rules": [{"field": "total_spend"}]})


def case_reexported():
    import smart_lists_api as api
    names = ("resolve", "_validate_rules", "uses_subscription_facts",   # imported from api elsewhere
             "_SUM_FIELDS", "_LEDGER_MONEY", "_windows_in_rules")           # the api's own body
    for n in names:
        assert getattr(api, n) is getattr(R, n), n


_harness.run()
