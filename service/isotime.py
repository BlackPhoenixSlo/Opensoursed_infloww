"""service/isotime.py — the one ISO 8601 parser the automations share. No imports
from the service, so pure modules (automations/send_followup_decide.py) can use it."""
from __future__ import annotations

from datetime import datetime, timezone


def parse_iso(s: str | None) -> datetime | None:
    """OF ISO 8601 (`+00:00`, any other offset, or trailing `Z`) → naive UTC datetime (an
    offset is converted, not dropped; a naive string is taken as UTC); None if unreadable."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)
