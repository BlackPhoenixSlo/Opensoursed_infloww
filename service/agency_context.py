from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from auth import assert_account_owned, get_request_user
from db.engine import get_session


@dataclass(frozen=True)
class AgencyContext:
    agency_user_id: str
    employee_id: int | None
    is_owner: bool
    is_master: bool


# Owner session wins over a chatter cookie; a named Creator never moves it into another Agency (Master included).
async def agency_context(*, account_id: str | None = None, db_session=None) -> AgencyContext:
    user = get_request_user()
    from chatters import get_request_chatter as _grc
    chatter = _grc() if user is None else None
    if user is None and chatter is None:
        raise HTTPException(status_code=401, detail="sign in required")
    assert_account_owned(account_id)
    if user is not None:
        return AgencyContext(
            agency_user_id=user.id,
            employee_id=None,
            is_owner=True,
            is_master=bool(user.is_admin),
        )
    if not chatter.owner_user_ids:
        raise HTTPException(status_code=403, detail="chatter is not linked to an agency")
    employee_id = None
    if account_id and db_session is None:
        agency_user_id, employee_id = await _chatter_agency_and_mirror(
            chatter.id, chatter.owner_user_ids, account_id,
        )
    elif account_id:
        agency_user_id = await _chatter_agency_for_creator(
            chatter.id, chatter.owner_user_ids, account_id, db_session=db_session,
        )
    elif len(chatter.owner_user_ids) == 1:
        (agency_user_id,) = chatter.owner_user_ids
    else:
        raise HTTPException(status_code=400, detail="name a creator to choose the agency")
    return await _chatter_context(chatter, agency_user_id, employee_id, db_session=db_session)


async def _chatter_context(
    chatter, agency_user_id: str, employee_id: int | None = None, *, db_session=None,
) -> AgencyContext:
    # Lazy: employees re-exports this module; tests patch it there.
    import employees
    if employee_id is None and db_session is not None:
        employee_id = await employees.mirror_id(db_session, chatter.id, agency_user_id)
    if employee_id is None:
        employee_id = await employees.get_or_create_mirror_employee(
            chatter.id, agency_user_id,
            display_name=chatter.display_name or chatter.username,
            color=chatter.color,
        )
    if employee_id is None:
        raise HTTPException(status_code=503, detail="mirror employee unavailable")
    return AgencyContext(
        agency_user_id=agency_user_id,
        employee_id=employee_id,
        is_owner=False,
        is_master=False,
    )


# Chatter refused 403 before agency_context so no Mirror Employee is created by an endpoint it may not use.
async def owner_context(account_id: str | None, detail: str) -> AgencyContext:
    if get_request_user() is None:
        from chatters import get_request_chatter as _grc
        if _grc() is not None:
            raise HTTPException(status_code=403, detail=detail)
    return await agency_context(account_id=account_id)


async def agency_contexts(*, account_id: str | None = None, db_session=None) -> list[AgencyContext]:
    if not account_id and get_request_user() is None:
        from chatters import get_request_chatter as _grc
        chatter = _grc()
        if chatter is not None and len(chatter.owner_user_ids) > 1:
            return [await _chatter_context(chatter, agency_user_id, db_session=db_session)
                    for agency_user_id in sorted(chatter.owner_user_ids)]
    return [await agency_context(account_id=account_id, db_session=db_session)]


async def _chatter_agency_for_creator(
    chatter_id: str,
    owner_user_ids: set[str] | frozenset[str],
    account_id: str,
    db_session=None,
) -> str:
    if db_session is not None:
        return await _allowed_holder(db_session, chatter_id, owner_user_ids, account_id)
    async with get_session() as s:
        agency_user_id = await _allowed_holder(s, chatter_id, owner_user_ids, account_id)
    return agency_user_id


async def _chatter_agency_and_mirror(chatter_id, owner_user_ids, account_id):
    import employees
    agency_user_id = None
    try:
        async with get_session() as s:
            agency_user_id = await _allowed_holder(s, chatter_id, owner_user_ids, account_id)
            employee_id = await employees.mirror_id(s, chatter_id, agency_user_id)
    except Exception as exc:
        if agency_user_id is None:
            raise
        raise HTTPException(status_code=503, detail="mirror employee unavailable") from exc
    # Never expose the scalar before commit/session exit has succeeded.
    return agency_user_id, employee_id


async def _allowed_holder(s, chatter_id, owner_user_ids, account_id) -> str:
    import employees
    from chatters import _account_restrictions_for, _filter_owner_accounts
    holders = await employees._sorted_holder_owner_ids(s, account_id, owner_user_ids)
    restrictions = await _account_restrictions_for(s, chatter_id)
    allowed = [
        uid for uid in holders
        if _filter_owner_accounts([(uid, account_id)], restrictions)
    ]
    if not allowed:
        # No allowed holder despite assert_account_owned (links changed mid-request): 403, not a 5xx.
        raise HTTPException(status_code=403, detail="not your account")
    return allowed[0]
