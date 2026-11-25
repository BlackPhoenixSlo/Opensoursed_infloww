from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypeVar

from fastapi import HTTPException

from isotime import iso_z


def parse_utc(value: Any, field: str, status: int = 422) -> datetime:
    if not isinstance(value, str) or not value:
        raise HTTPException(status_code=status, detail=f"{field}: an ISO-8601 UTC time is required")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=status, detail=f"{field}: not an ISO-8601 time") from None
    if dt.tzinfo is None:
        raise HTTPException(status_code=status, detail=f"{field}: the time needs a zone (end it with Z)")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


wire = iso_z


_Row = TypeVar("_Row")


async def own_row_or_404(s, model: type[_Row], raw_id: str, what: str, owner_attr: str, owner_val: Any) -> _Row:
    try:
        row_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{what} not found") from None
    row = await s.get(model, row_id)
    if row is None or getattr(row, owner_attr) != owner_val:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row
