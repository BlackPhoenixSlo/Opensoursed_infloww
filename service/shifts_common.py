"""service/shifts_common.py — what the two `/admin/shifts` routers share.

The Shift schedule (service/shifts_api.py) and the Clock endpoints
(service/clock_api.py) both start from the owner's Agency context, read the
same `from`/`to` range and JSON body, and look rows up by path id the same
way; those helpers live here so neither router imports the other's
privates.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy import select

from agency_scope import agency_account_ids  # noqa: F401 — shifts_api / clock_api import it from here
from db.models import ClockEvent, Employee, Shift
from employees import AgencyContext, json_object, owner_context
from route_wire import own_row_or_404, parse_utc

MAX_RANGE = timedelta(days=42)

OWNER_ONLY = "only the agency owner manages the Shift schedule"


async def shift_owner_context(account_id: str | None = None) -> AgencyContext:
    return await owner_context(account_id, OWNER_ONLY)


async def agency_employee_ids(s, agency_user_id: str, ids: list[int]) -> set[int]:
    rows = (await s.execute(
        select(Employee.id).where(Employee.id.in_(ids), Employee.user_id == agency_user_id)
    )).scalars().all()
    return set(rows)


def parse_range(from_: str | None, to: str | None) -> tuple[datetime, datetime]:
    """`from` and `to` → naive UTC, 422 unless from < to within 42 days."""
    start = parse_utc(from_, "from")
    end = parse_utc(to, "to")
    if end <= start:
        raise HTTPException(status_code=422, detail="to must be after from")
    if end - start > MAX_RANGE:
        raise HTTPException(status_code=422, detail="the range is at most 42 days")
    return start, end


async def json_body(request: Request) -> dict[str, Any]:
    return await json_object(request, 422)


# The Agency-owned rows `own_agency_row` looks up by path id.
_Owned = TypeVar("_Owned", Shift, ClockEvent)


async def own_agency_row(s, ctx: AgencyContext, model: type[_Owned], raw_id: str, what: str) -> _Owned:
    """This Agency's `model` row (a Shift or a Clock event) by its path id,
    or 404 "<what> not found" (another Agency's, missing, or not an id)."""
    return await own_row_or_404(s, model, raw_id, what, "agency_user_id", ctx.agency_user_id)
