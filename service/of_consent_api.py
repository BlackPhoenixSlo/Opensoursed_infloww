from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from sqlalchemy import select

import consent_notices
import of_consent
from auth import assert_account_owned, get_request_user
from chatters import get_request_chatter
from db.engine import get_session
from db.models import AgencyNotification
from isotime import iso_z

router = APIRouter()


async def _view(s: Any, account_id: str) -> dict[str, Any]:
    row = await of_consent.current(s, account_id)
    required = (await s.execute(
        select(AgencyNotification.id).where(AgencyNotification.kind == consent_notices.KIND,
                                            AgencyNotification.account_id == account_id).limit(1))
                ).first() is not None
    return {"account_id": account_id, "auto_accept": bool(row and row.enabled), "required": required,
            "changed": None if row is None else {
                "enabled": bool(row.enabled), "user_id": row.user_id, "username": row.username,
                "employee_id": row.employee_id, "at": iso_z(row.at)}}


@router.get("/admin/of-consent/{account_id}")
async def get_of_consent(account_id: str) -> dict[str, Any]:
    """The Creator's switch, whether OF wants the consent form, and who changed it last."""
    assert_account_owned(account_id)
    async with get_session() as s:
        return await _view(s, account_id)


@router.put("/admin/of-consent/{account_id}")
async def put_of_consent(account_id: str, body: dict = Body(...)) -> dict[str, Any]:
    """Turn the switch on or off (`{"auto_accept": bool}`); one history row per change."""
    assert_account_owned(account_id)
    if get_request_user() is None and get_request_chatter() is not None:
        raise HTTPException(403, "owners only")
    want = body.get("auto_accept") if isinstance(body, dict) else None
    if not isinstance(want, bool):
        raise HTTPException(422, "auto_accept must be true or false")
    import employees
    user = get_request_user()
    emp = await employees.get_owner_employee_id(user) if user is not None else None
    async with get_session() as s:
        row = await of_consent.current(s, account_id)
        if bool(row and row.enabled) != want:
            await of_consent.record(s, account_id, want, user_id=user and user.id,
                                    username=user and user.username, employee_id=emp,
                                    at=datetime.utcnow())
        return await _view(s, account_id)
