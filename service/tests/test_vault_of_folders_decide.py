#!/usr/bin/env python3
"""
vault_of_folders_decide — table tests over the pure rules `vault_of_folders`
hands off. Its DB / OF side is walked by test_vault_dupes, test_vault_ai_mirror
and test_vault_foreign_media_guard.

  case_next_folder_ids_table:  read-back membership — add, drop, no-op; input
                               not mutated.
  case_parse_folder_ids_table: None / bad JSON / non-int ids → [].
  case_too_many_table:         exactly max passes, max+1 is the 400 detail.
  case_hide_selection_table:   keeper refused, not-a-dupe refused, sent copies
                               only with allow_sent, order kept, empty input.
  case_chunks_table:           100 → [100], 205 → [100, 100, 5], [] → [].

No DB, no OF. Run: venv/bin/python service/tests/test_vault_of_folders_decide.py
"""
from __future__ import annotations

import _harness  # MUST be first (binds a temp DB; this file never touches it)

import vault_of_folders_decide as d  # noqa: E402


def _table(rows, fn) -> None:
    """Run every row, collect every mismatch, fail once naming them all."""
    bad = [f"{rid}: {got!r} != {want!r}" for rid, args, want in rows if (got := fn(*args)) != want]
    assert not bad, "\n  " + "\n  ".join(bad)


def case_next_folder_ids_table():
    _table([
        ("add: live in a list it lacks", ([1], 7, {2: {7}}), [1, 2]),
        ("drop: no longer live in a list it claims", ([1, 2], 7, {2: {8}}), [1]),
        ("drop removes every copy", ([2, 1, 2], 7, {2: set()}), [1]),
        ("no-op: already agrees both ways", ([1, 2], 7, {2: {7}, 3: {8}}), [1, 2]),
        ("lists not read back are left alone", ([9], 7, {2: set()}), [9]),
        ("both directions in one pass", ([1, 2], 7, {2: set(), 3: {7}}), [1, 3]),
        ("empty read-back", ([1], 7, {}), [1]),
        ("empty stored", ([], 7, {2: {7}}), [2]),
        ("media id coerced", ([], "7", {2: {7}}), [2]),
    ], d.next_folder_ids)
    ids = [1]
    assert d.next_folder_ids(ids, 7, {2: {7}}) == [1, 2] and ids == [1], ids


def case_parse_folder_ids_table():
    _table([
        ("None", (None,), []),
        ("empty string", ("",), []),
        ("ints", ("[1, 2]",), [1, 2]),
        ("bad JSON -> []", ("{not json",), []),
        ("non-list JSON -> []", ("5",), []),
        ("non-int id -> []", ('["x"]',), []),
        ("null ids skipped, strings coerced", ('[null, "3"]',), [3]),
    ], d.parse_folder_ids)


def case_too_many_table():
    _table([
        ("empty", ([], 500), None),
        ("exactly max", (list(range(500)), 500), None),
        ("max + 1", (list(range(501)), 500), {"error": "too_many", "max": 500, "got": 501}),
    ], d.too_many)


def _cluster(original: int, *dupes: tuple[int, int]) -> dict:
    return {"original": {"media_id": original},
            "dupes": [{"media_id": m, "send_count": n} for m, n in dupes]}


_CLUSTERS = [_cluster(1, (2, 0), (3, 4)), _cluster(10, (11, 0))]
_NONE = {"is_original": [], "not_a_duplicate": [], "has_sends": []}


def case_hide_selection_table():
    _table([
        ("keeper requested -> refused", ([1, 2], _CLUSTERS, False),
         ([2], {**_NONE, "is_original": [1]})),
        ("sent dupe without allow_sent -> has_sends", ([3, 11], _CLUSTERS, False),
         ([11], {**_NONE, "has_sends": [3]})),
        ("sent dupe with allow_sent -> approved", ([3, 11], _CLUSTERS, True),
         ([3, 11], _NONE)),
        ("keeper refused even with allow_sent", ([10], _CLUSTERS, True),
         ([], {**_NONE, "is_original": [10]})),
        ("not in any set -> not_a_duplicate", ([99, 2], _CLUSTERS, False),
         ([2], {**_NONE, "not_a_duplicate": [99]})),
        ("request order kept", ([11, 2], _CLUSTERS, False), ([11, 2], _NONE)),
        ("empty request", ([], _CLUSTERS, False), ([], _NONE)),
        ("no clusters", ([2], [], False), ([], {**_NONE, "not_a_duplicate": [2]})),
    ], d.hide_selection)


def case_chunks_table():
    _table([
        ("100 -> [100]", (list(range(100)), 100), [list(range(100))]),
        ("205 -> [100, 100, 5]", (list(range(205)), 100),
         [list(range(100)), list(range(100, 200)), list(range(200, 205))]),
        ("empty", ([], 100), []),
    ], d.chunks)


_harness.run()
