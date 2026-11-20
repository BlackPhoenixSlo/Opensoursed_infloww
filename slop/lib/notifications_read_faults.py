"""scenarios/2026-11-20-notifications-mark-read.py's checks and fault: lib/faults.py merges `register(Fault)`.

  notif-read-not-sent  OFClient.notifications_read answers `{}` without reaching OF (the pre-fix state at the wire).
"""
from __future__ import annotations

WIRE_ONE = "opening the Notifications panel sent OF exactly one mark-read (All, no type), none for another Creator"
BADGE = "the Notifications button read OF's count before the open and no number after it"
RELAY_ZERO = "the relay's count for the scoped Creator answers OF's lowered count (all 0) after the open"
API_BUST = "the mark-read route answers OF's counters, reaches the wire once and drops the relay's cached count"


def _not_sent() -> None:
    import of_client
    of_client.OFClient.notifications_read = lambda self, type=None: {}


def register(Fault) -> dict:
    return {"notif-read-not-sent": Fault(_not_sent, (WIRE_ONE, BADGE, RELAY_ZERO, API_BUST))}
