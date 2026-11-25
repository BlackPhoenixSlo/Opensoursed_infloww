from __future__ import annotations

from datetime import datetime, timezone
from typing import overload


def parse_iso(s: object) -> datetime | None:
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
    return None if dt is None else dt.isoformat() + "Z"


@overload
def iso_plain(dt: datetime) -> str: ...
@overload
def iso_plain(dt: None) -> None: ...
def iso_plain(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat()
