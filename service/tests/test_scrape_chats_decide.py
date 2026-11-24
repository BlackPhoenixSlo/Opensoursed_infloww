import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automations.scrape_chats_decide import history_plan, hold_ascending, inbound_since, new_unread_marker


CASES = (
    (True, True, False, None, None, False, "defer"),
    (True, True, False, 0, True, False, "defer"),
    (True, True, False, 1, False, False, "defer"),
    (True, True, False, 0, False, False, "both_ends"),
    (True, True, True, 0, None, False, "page1"),
    (True, True, True, 1, False, False, "page1"),
    (True, True, True, 0, False, False, "both_ends"),
    (True, True, True, 1, None, True, "both_ends"),
    (False, True, False, 1, True, False, "both_ends"),
    (True, False, False, None, True, False, "both_ends"),
)


def test_history_plan():
    for first, gated, deferred, local, of, click, want in CASES:
        assert history_plan(first_scrape=first, unread_gate=gated, was_deferred=deferred,
                            local_unread=local, of_unread=of, after_click=click) == want


def test_hold_ascending():
    cases = (
        (False, 1, 0, True, True, True, False),
        (True, 1, 1, True, True, False, False),
        (True, 2, 1, None, True, False, True),
        (True, 0, 0, False, True, True, True),
        (True, None, None, None, False, False, True),
        (True, 0, 0, False, False, False, False),
    )
    for gate, local, initial, of, click, inbound, want in cases:
        assert hold_ascending(unread_gate=gate, local_unread=local, initial_unread=initial,
                              of_unread=of, after_click=click, newer_inbound=inbound) == want


def test_inbound_since():
    at = datetime(2026, 1, 1)
    cases = (
        (7, "2026-01-01T00:00:00Z", at, True),
        ("7", "2026-01-01T01:00:00+01:00", at, True),
        (8, "2026-01-01T00:00:00Z", at, False),
        (7, "2025-12-31T23:59:59Z", at, False),
        (7, "invalid", at, False),
        (7, "2026-01-01T00:00:00Z", None, False),
    )
    for sender, created, click, want in cases:
        assert inbound_since([{"fromUser": {"id": sender}, "createdAt": created}], 7, click) == want


def test_new_unread_marker():
    cases = (
        (True, True, None, None, False),
        (True, True, None, False, False),
        (True, True, None, True, True),
        (True, True, 1, False, True),
        (True, True, 0, False, False),
        (False, True, 1, True, False),
        (True, False, 1, True, False),
    )
    for deferred, gate, local, of, want in cases:
        assert new_unread_marker(deferred=deferred, unread_gate=gate, local_unread=local, of_unread=of) == want


if __name__ == "__main__":
    test_history_plan()
    test_hold_ascending()
    test_inbound_since()
    test_new_unread_marker()
