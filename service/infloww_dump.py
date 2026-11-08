"""An Infloww dump as the relay reads it (its step labels, its sequence dates): standard library only, so
scripts/import_infloww_scripts.py imports this same module (as it does of_rich_text) to read a dump back exactly
as `scripts_import_api.bulk_import` stored it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_STEP = re.compile(r"^\s*(\d+)(?:\.(\d+))?\s*$")


def parse_step(v: str | int | float) -> tuple[int, int] | None:
    """"3" -> (3, 0), "2.1" -> (2, 1); None below step 1 or not N / N.M."""
    m = _STEP.match(str(v))
    if not m or int(m.group(1)) < 1:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def parse_when(v: str | int | float | None) -> datetime | None:
    """Epoch seconds or ms, an ISO date-time, or Infloww's day-only "Oct 13, 2026" (kept at 12:00 UTC so the
    day reads the same in any browser zone), as naive UTC; None when absent or unreadable."""
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(str(v).strip(), "%b %d, %Y").replace(hour=12)
            except ValueError:
                return None
        return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
    try:
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def sequence_dates(created_on: str | int | float | None, modified_on: str | int | float | None,
                   now: datetime) -> tuple[datetime, datetime]:
    """A sequence's (Created on, Last modified on): an unreadable Created on is `now` (the import's), an unreadable
    Last modified on is Created on."""
    created = parse_when(created_on) or now
    return created, parse_when(modified_on) or created
