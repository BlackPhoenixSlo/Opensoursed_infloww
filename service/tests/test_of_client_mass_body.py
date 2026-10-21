#!/usr/bin/env python3
"""
of_client mass-send WIRE BODY — the fix that started it all.

OF's POST /messages/queue has NO per-user exclusion field: `excludedUsers` was
silently dropped (verified live 2026-06-12 — excluded fans still got the blast),
and the list-level field is `excludedLists`, not `excludeUserLists`. These tests
pin the exact body shape so a refactor can't quietly reintroduce the dead names.

  case_send_mass_body / case_schedule_mass_body:
      `excludedLists` carries the list ids; `excluded_users` is subtracted from
      `userIds` CLIENT-SIDE; the dead `excludedUsers`/`excludeUserLists` keys are
      gone entirely.

Run: ./venv/bin/python service/tests/test_of_client_mass_body.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import of_client  # noqa: E402


def _client():
    """An OFClient that skips __init__ (no session/signing needed) and captures
    the body instead of hitting the network."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.captured: list[tuple[str, dict]] = []
    c.post_json = lambda path, json_body=None: (  # type: ignore[attr-defined]
        c.captured.append((path, json_body)) or {"id": 1})
    return c


def _assert_clean(body: dict):
    assert "excludedUsers" not in body, f"dead per-user field present: {body}"
    assert "excludeUserLists" not in body, f"dead list field present: {body}"
    assert "excludedLists" in body, f"real list field missing: {body}"


def case_send_mass_body():
    c = _client()
    c.send_mass_message(
        "hi", user_lists=["fans"], included_users=[1, 2, 3],
        excluded_users=[2], excluded_user_lists=[77])
    path, body = c.captured[-1]
    assert path.endswith("/messages/queue"), path
    _assert_clean(body)
    assert body["userIds"] == [1, 3], body          # 2 subtracted client-side
    assert body["excludedLists"] == [77], body
    assert body["userLists"] == ["fans"], body


def case_schedule_mass_body():
    c = _client()
    c.schedule_mass_message(
        text="hi", scheduled_date="2026-06-20T10:00:00+00:00",
        user_ids=[5, 6], excluded_users=[6], excluded_user_lists=[88])
    path, body = c.captured[-1]
    assert path.endswith("/messages/queue"), path
    _assert_clean(body)
    assert body["userIds"] == [5], body             # 6 subtracted client-side
    assert body["excludedLists"] == [88], body


def case_no_excludes_passthrough():
    # No excludes → userIds untouched, excludedLists empty (not the dead keys).
    c = _client()
    c.send_mass_message("hi", included_users=[9, 8, 7])
    _, body = c.captured[-1]
    _assert_clean(body)
    assert body["userIds"] == [9, 8, 7], body
    assert body["excludedLists"] == [], body


_harness.run(
    case_send_mass_body,
    case_schedule_mass_body,
    case_no_excludes_passthrough,
)
