from __future__ import annotations

import re
from datetime import datetime, timezone

_STEP = re.compile(r"^\s*(\d+)(?:\.(\d+))?\s*$")


def parse_step(v: str | int | float) -> tuple[int, int] | None:
    m = _STEP.match(str(v))
    if not m or int(m.group(1)) < 1:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


# Infloww's day-only "Oct 13, 2026" is kept at 12:00 UTC so the day reads the same in any browser zone.
def parse_when(v: str | int | float | None) -> datetime | None:
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
    created = parse_when(created_on) or now
    return created, parse_when(modified_on) or created
