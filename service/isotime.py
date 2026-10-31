"""service/isotime.py — the shared lenient ISO 8601 parser and writers. Request-side strict
parsing is route_wire.parse_utc. No imports from the service, so pure modules
(automations/send_followup_decide.py) can use it."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import overload


def parse_iso(s: object) -> datetime | None:
    """OF ISO 8601 (`+00:00`, any other offset, or trailing `Z`; outer spaces ignored) →
    naive UTC datetime (an offset is converted, not dropped; a naive string is taken as
    UTC); None if not a non-blank str or unreadable."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


@overload
def iso_z(dt: datetime) -> str: ...
@overload
def iso_z(dt: None) -> None: ...
def iso_z(dt: datetime | None) -> str | None:
    """A stored naive-UTC time as ISO ending in Z; None stays None."""
    return None if dt is None else dt.isoformat() + "Z"


@overload
def iso_plain(dt: datetime) -> str: ...
@overload
def iso_plain(dt: None) -> None: ...
def iso_plain(dt: datetime | None) -> str | None:
    """A stored naive time as bare ISO (no zone); None stays None."""
    return None if dt is None else dt.isoformat()
