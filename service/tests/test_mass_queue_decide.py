#!/usr/bin/env python3
"""
mass_queue_decide — table tests over POST /api/of/v2/messages/queue's pure half.

No DB, no OF: every row is (request values) -> value.

  case_threshold_refusal_table:     schedule / save-later × thresholds × online × expired
                                    -> the two 422 texts, byte-identical, or None.
  case_threshold_count_refusal_table: 0 ids / over the cap -> 422 text; 1..cap -> None.
  case_strip_excluded_table:        order kept, strings-as-ints dropped, elements as given.
  case_strip_excluded_same_object:  either side empty -> the very same list (`is`).
  case_needs_exclude_list_table:    ids-only audience needs no list; list/online/filters do.
  case_pending_placeholders_table:  echoed fans and non-int ids excluded, order kept.
  case_echoed_of_matches_old_loop:  send_mass_decide.echoed_of == _close_mass_run's old
                                    step-1 loop on OF echo shapes (None ids, non-dicts).

Run: ./venv/bin/python service/tests/test_mass_queue_decide.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import mass_queue_decide as mqd  # noqa: E402
from automations.send_mass_decide import echoed_of  # noqa: E402

SCHED = ("Thresholds with 'Only fans online right now' resolve "
         "the online list at send time: send now, or turn "
         "off online-only to schedule.")
EXPIRED = ("OnlyFans' online list holds active subscribers only, "
           "so 'Expired over' can't combine with online-only.")
AT = "2026-11-07T10:00:00+01:00"


def _table(rows, fn) -> None:
    bad = []
    for rid, args, want in rows:
        got = fn(*args)
        if got != want:
            bad.append(f"{rid}: {got!r} != {want!r}")
    assert not bad, "\n".join(bad)


def case_threshold_refusal_table():
    # (scheduled, save_for_later, thresholds, online_now, expired_over_days)
    _table([
        ("send now, thresholds, online", (None, False, True, True, None), None),
        ("scheduled, thresholds, online", (AT, False, True, True, None), SCHED),
        ("save later, thresholds, online", (None, True, True, True, None), SCHED),
        ("scheduled + expired: schedule text wins", (AT, False, True, True, 7.0), SCHED),
        ("send now, expired, online", (None, False, True, True, 7.0), EXPIRED),
        ("scheduled, thresholds, not online", (AT, False, True, False, 7.0), None),
        ("save later, no thresholds, online", (None, True, False, True, 7.0), None),
        ("nothing set", (None, False, False, False, None), None),
        ("empty date string is not a schedule", ("", False, True, True, None), None),
    ], mqd.threshold_refusal)


def case_threshold_count_refusal_table():
    _table([
        ("nobody clears", (0, 500), "No fan clears these thresholds right now "
                                    "— nothing was sent."),
        ("one", (1, 500), None),
        ("exactly the cap", (500, 500), None),
        ("over the cap", (501, 500), "501 fans clear these thresholds; "
                                     "one send takes at most 500. Raise a "
                                     "threshold or pick a smaller list — nothing was sent."),
    ], mqd.threshold_count_refusal)


def case_strip_excluded_table():
    _table([
        ("order kept", ([5, 1, 4, 2], [4]), [5, 1, 2]),
        ("strings-as-ints dropped", ([1, 2, 3], ["2", "3"]), [1]),
        ("str user ids kept as given", (["7", "8", 9], [8]), ["7", 9]),
        ("dups kept unless excluded", ([1, 1, 2, 2], [2]), [1, 1]),
        ("nothing excluded matches", ([1, 2], [9]), [1, 2]),
        ("all excluded", ([1, 2], [1, 2]), []),
    ], mqd.strip_excluded)


def case_strip_excluded_same_object():
    ids = [1, 2]
    assert mqd.strip_excluded(ids, []) is ids
    empty: list = []
    assert mqd.strip_excluded(empty, [1]) is empty
    assert mqd.strip_excluded(ids, [9]) is not ids     # a real strip builds a new list


def case_needs_exclude_list_table():
    # (excluded, user_lists, online_only, filters)
    _table([
        ("ids-only audience", ([3], [], False, None), False),
        ("list audience", ([3], ["fans"], False, None), True),
        ("online audience", ([3], [], True, None), True),
        ("filters audience", ([3], [], False, {"online": 1}), True),
        ("empty filters dict is no audience", ([3], [], False, {}), False),
        ("nothing excluded", ([], ["fans"], True, {"online": 1}), False),
    ], mqd.needs_exclude_list)


def case_pending_placeholders_table():
    _table([
        ("none", (None, set()), []),
        ("echoed dropped, order kept", ([3, 1, 2], {1}), [3, 2]),
        ("non-int ids skipped, str ids cast", (["4", None, "x", 5], {5}), [4]),
        ("all echoed", ([1, 2], {1, 2}), []),
    ], mqd.pending_placeholders)


def _old_step1(result):
    """_close_mass_run's step-1 loop before it called echoed_of (reference copy)."""
    msgs = result.get("messages") if isinstance(result, dict) else None
    per_fan_ids: list[tuple[int, int]] = []
    if isinstance(msgs, list):
        for m in msgs:
            if not isinstance(m, dict):
                continue
            fid_raw = m.get("userId") or m.get("toUserId") or m.get("recipientId")
            mid_raw = m.get("id") or m.get("messageId")
            try:
                if fid_raw is not None and mid_raw is not None:
                    per_fan_ids.append((int(fid_raw), int(mid_raw)))
            except (TypeError, ValueError):
                continue
    return per_fan_ids


def case_echoed_of_matches_old_loop():
    shapes = [
        None, [], "x", {}, {"id": 1}, {"messages": None}, {"messages": "x"},
        {"messages": {"userId": 1, "id": 2}},
        {"messages": [{"userId": 5, "id": 50}]},
        {"messages": [{"toUserId": "6", "messageId": "60"}, {"recipientId": 7, "id": 70}]},
        {"messages": ["x", None, 3, [1, 2], {"userId": 1}, {"id": 2},
                      {"userId": None, "id": 9}, {"userId": 9, "id": None},
                      {"userId": None, "toUserId": None, "recipientId": None, "id": None},
                      {"userId": "a", "id": 2}, {"userId": 3, "id": "b"},
                      {"userId": "", "id": 4}, {"userId": 0, "toUserId": 0, "recipientId": 0, "id": 5},
                      {"userId": 0, "toUserId": 11, "id": 0, "messageId": 110},
                      {"userId": 2.0, "id": "12"}, {"userId": True, "id": 13},
                      {"userId": 8, "id": 80}]},
    ]
    bad = [f"{s!r}: {echoed_of(s)!r} != {_old_step1(s)!r}"
           for s in shapes if echoed_of(s) != _old_step1(s)]
    assert not bad, "\n".join(bad)


_harness.run()
