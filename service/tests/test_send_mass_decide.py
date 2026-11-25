#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import json  # noqa: E402
from dataclasses import replace  # noqa: E402

from automations import send_mass_decide as smd  # noqa: E402
from automations.send_mass_decide import Funnel, Plan, Skip  # noqa: E402

F = Funnel(id=3, opening_message="How many strokes? 😈")
NO_OPENER = Funnel(id=4, opening_message=None)


def plan(payload, *, funnel=F, resolved, opener=()):
    return smd.plan(payload, funnel=funnel, resolved=resolved,
                    list_ids=smd.list_ids_of(payload)[0], opener_media=list(opener))


def R(included, excluded=(), answered=None) -> dict:
    out = {"included_users": list(included), "excluded_users": list(excluded)}
    if answered is not None:
        out["skipped_funnel_responders"] = answered
    return out


def _table(rows, fn) -> None:
    bad = []
    for rid, args, want in rows:
        got = fn(*args)
        if got != want:
            bad.append(f"{rid}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_seed_table():
    _table([
        ("list ∪ explicit, explicit first",
         ({"included_users": [1, 2]}, [3, 4], []), ([1, 2, 3, 4], [])),
        ("dups kept for plan to drop",
         ({"included_users": [1, 2]}, [2, 3], []), ([1, 2, 2, 3], [])),
        ("fan_ids alias", ({"fan_ids": ["5"]}, [], []), ([5], [])),
        ("excludes + exclude-list members",
         ({"excluded_users": [9]}, [], [8, 9]), ([], [9, 8, 9])),
        ("empty", ({}, [], []), ([], [])),
    ], smd.seed)
    assert smd.list_ids_of({"list_ids": [7, "x"], "exclude_list_ids": ["4"]}) == ([7], [4])


def case_plan_audience_table():
    def go(payload, resolved):
        p = plan(payload, resolved=resolved)
        return p if isinstance(p, Skip) else p.recipients
    _table([
        ("dedupe keeps first-seen order", ({}, R([3, 1, 3, 2, 1])), [3, 1, 2]),
        ("exclusions win", ({}, R([1, 2, 3], [2])), [1, 3]),
        ("all excluded -> empty audience", ({}, R([1, 2], [1, 2])), Skip("empty_audience")),
        ("empty audience -> no send", ({}, R([])), Skip("empty_audience")),
        ("OF list names are an audience", ({"user_lists": ["fans"]}, R([])), []),
        ("online_only is an audience", ({"online_only": 1}, R([])), []),
        ("filters dict is an audience", ({"filters": {"online": 1}}, R([])), []),
        ("filters non-dict is not", ({"filters": "online"}, R([])), Skip("empty_audience")),
    ], go)
    p = plan({"excluded_user_lists": ["Mass_Exclude"]},
             resolved=R([1, 2], [2, 9], answered=[7]))
    assert p.excl_set == frozenset({2, 9}) and p.skipped_answered == [7], p
    assert p.excluded_user_lists == ["Mass_Exclude"] and not p.is_list_audience, p


def case_plan_text_table():
    def go(payload, funnel, resolved):
        p = plan(payload, funnel=funnel, resolved=resolved)
        return p if isinstance(p, Skip) else (p.text, p.funnel_id)
    _table([
        ("funnel opener", ({}, F, R([1])), ("How many strokes? 😈", 3)),
        ("payload text beats the opener", ({"text": "hi"}, F, R([1])), ("hi", 3)),
        ("text without a funnel", ({"text": "hi"}, None, R([1])), ("hi", None)),
        ("no text at all", ({}, None, R([1])), Skip("no_text")),
        ("funnel with no opener text", ({}, NO_OPENER, R([1])), Skip("no_text")),
        ("no_text checked before the audience", ({}, None, R([])), Skip("no_text")),
    ], go)


def case_opener_table():
    def go(payload, funnel, opener):
        p = plan(payload, funnel=funnel, resolved=R([1]), opener=opener)
        return (p.media_files, p.previews, p.price)
    _table([
        ("funnel send, opener mapped", ({}, F, [11, 12]), ([11, 12], [], 0)),
        ("funnel without opener media sends none", ({}, F, []), ([], [], 0)),
        ("payload previews kept with opener media", ({"previews": [5]}, F, [11]), ([11], [5], 0)),
        ("explicit media beats the opener",
         ({"media_files": ["7"], "price": 5}, F, [11]), ([7], [], 5)),
        ("no funnel: no opener media", ({"text": "hi"}, None, [11]), ([], [], 0)),
    ], go)


def case_opener_media_of():
    _table([
        ("ids", ("[1, \"2\"]",), [1, 2]),
        ("None", (None,), []),
        ("bad json", ("{nope",), []),
        ("not a list", ("{\"a\": 1}",), []),
    ], smd.opener_media_of)


def case_audience_filter_shape():
    p = plan({"user_lists": ["fans"], "list_ids": [7]}, resolved=R([1, 2], [9, 3]))
    assert isinstance(p, Plan), p
    p = replace(p, recipients=[1], excluded_user_lists=["x", 5])
    raw = smd.audience_filter(p, ref=41, fence=True)
    assert list(json.loads(raw)) == ["user_lists", "included_users", "excluded_users",
                                     "list_ids", "ref", "excluded_user_lists", "fence",
                                     "online", "filters", "auto_exclude_list",
                                     "unresolved_exclude_lists"], raw
    assert json.loads(raw) == {"user_lists": ["fans"], "included_users": [1],
                               "excluded_users": [3, 9], "list_ids": [7], "ref": "41",
                               "excluded_user_lists": ["x", 5], "fence": True,
                               "online": False, "filters": False,
                               "auto_exclude_list": None,
                               "unresolved_exclude_lists": ["x", 5]}, raw
    af = json.loads(smd.audience_filter(p, ref=None, fence=False, auto_exclude=5))
    assert (af["auto_exclude_list"], af["unresolved_exclude_lists"]) == (5, ["x"]), af
    assert json.loads(smd.audience_filter(p, ref=None, fence=False))["ref"] is None
    af = json.loads(smd.audience_filter(replace(p, online_only=True), ref=None, fence=False))
    assert (af["online"], af["filters"]) == (True, False), af
    af = json.loads(smd.audience_filter(replace(p, filters={"online": 1}), ref=None, fence=False))
    assert (af["online"], af["filters"]) == (False, True), af


def case_echoed_of_table():
    _table([
        ("queue object, no messages", ({"id": 1},), []),
        ("not a dict", (None,), []),
        ("userId/id", ({"messages": [{"userId": 5, "id": 50}]},), [(5, 50)]),
        ("aliases", ({"messages": [{"toUserId": "6", "messageId": "60"},
                                   {"recipientId": 7, "id": 70}]},), [(6, 60), (7, 70)]),
        ("malformed dropped, order kept",
         ({"messages": ["x", {"userId": 1}, {"userId": "a", "id": 2}, {"userId": 8, "id": 80}]},),
         [(8, 80)]),
    ], smd.echoed_of)


def case_dry_run_table():
    _table([
        ("flag", ({"dry_run": True},), True),
        ("truthy", ({"dry_run": 1},), True),
        ("absent", ({},), False),
        ("false", ({"dry_run": False},), False),
    ], smd.is_dry_run)
    lst = plan({"text": "hi", "user_lists": ["7"]}, resolved=R([], [9, 3]))
    exp = plan({"text": "hi"}, resolved=R([1, 2, 3], [3]))
    exl = plan({"text": "hi", "excluded_user_lists": [5]}, resolved=R([1, 2]))
    onl = plan({"text": "hi", "online_only": True}, resolved=R([]))
    flt = plan({"text": "hi", "filters": {"online": 1}}, resolved=R([]))
    ok = {"status": "ok", "dry_run": True, "sent": 0}
    _table([
        ("explicit = recipients", (exp,),
         {**ok, "would_send": [1, 2], "would_send_count": 2, "audience": "explicit"}),
        ("explicit + OF exclude lists refuses", (exl,),
         {**ok, "would_send": None, "would_send_count": None, "audience": "explicit",
          "reason": "excluded_lists_unresolved"}),
        ("online refuses", (onl,),
         {**ok, "would_send": None, "would_send_count": None, "audience": "list",
          "reason": "online_or_filtered"}),
        ("filters refuse", (flt,),
         {**ok, "would_send": None, "would_send_count": None, "audience": "list",
          "reason": "online_or_filtered"}),
        ("list never read", (lst,),
         {**ok, "would_send": None, "would_send_count": None, "audience": "list",
          "reason": "list_audience"}),
    ], smd.dry_run_result)


_harness.run()
