"""service/route_wire.py — wire-time and path-id helpers any router may share.

`parse_utc` reads an ISO-8601 time with a zone into naive UTC (how times are
stored), `wire` writes one back as an ISO string ending in Z, and
`own_row_or_404` reads a row by its path id for its owner only. First used by
the `/admin/shifts` routers (service/shifts_api.py, service/clock_api.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypeVar, overload

from fastapi import HTTPException


def parse_utc(value: Any, field: str, status: int = 422) -> datetime:
    """An ISO-8601 time with a zone (Z or an offset) → naive UTC; `status`
    (422 by default) when it is missing, not ISO-8601 or has no zone.

    ASSUMPTION: any explicit offset is accepted and converted, not only a
    literal Z; a time with no zone is refused. Rung 4: stricter later is a
    narrowing the app never trips (it always sends toISOString()).
    Overturned if the owner wants non-Z input refused.
    """
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=status, detail=f"{field}: an ISO-8601 UTC time is required")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=status, detail=f"{field}: not an ISO-8601 time") from None
    if dt.tzinfo is None:
        raise HTTPException(status_code=status, detail=f"{field}: the time needs a zone (end it with Z)")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@overload
def wire(dt: datetime) -> str: ...
@overload
def wire(dt: None) -> None: ...
def wire(dt: datetime | None) -> str | None:
    """A stored naive-UTC time as the wire's ISO string ending in Z; None stays None."""
    return None if dt is None else dt.isoformat() + "Z"


_Row = TypeVar("_Row")


async def own_row_or_404(s, model: type[_Row], raw_id: str, what: str, owner_attr: str, owner_val: Any) -> _Row:
    """The `model` row with path id `raw_id` whose `owner_attr` is `owner_val`,
    or 404 "<what> not found" (another owner's, missing, or not an id)."""
    try:
        row_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found") from None
    row = await s.get(model, row_id)
    if row is None or getattr(row, owner_attr) != owner_val:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row
