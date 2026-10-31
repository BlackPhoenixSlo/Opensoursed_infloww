"""service/agency_context.py — which Agency, which Employee, Owner or Master
a request acts as (docs/spec/phase-01), from the session alone.

The Mirror Employee and holder lookups stay in employees.py and are read
through it at call time.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from auth import assert_account_owned, get_request_user
from db.engine import get_session


@dataclass(frozen=True)
class AgencyContext:
    """Which Agency, which Employee, Owner or Master — for one request,
    from the session alone (docs/spec/phase-01)."""
    agency_user_id: str        # users.id of the Agency
    employee_id: int | None    # Mirror Employee for a Chatter session; None for an Owner session
    is_owner: bool             # True for an Owner session (Master included)
    is_master: bool            # users.is_admin


async def agency_context(*, account_id: str | None = None) -> AgencyContext:
    """The Agency context of the current request, from the session cookies'
    ContextVars and the database only — never from client-supplied input.

    Await it inside a handler. A caller with a Creator in its path, query or
    body passes that id as `account_id`. Refusals, in order: 401 `sign in
    required` with no session (ALLOW_ANONYMOUS_ADMIN does not change this);
    403 `not your account` when `account_id` is not the principal's; 403
    `chatter is not linked to an agency`; 400 `name a creator to choose the
    agency` for a chatter linked to several Agencies who names no Creator.
    503 when the chatter's Mirror Employee cannot be resolved.

    An Owner session (it wins over a chatter cookie in the same browser, as
    in `_actor_account_ids`) is the Agency itself: no Employee, and a named
    Creator never moves it into another Agency — the Master included.
    Impersonation needs no case: the session middleware has already
    overlaid the impersonated owner onto `get_request_user()`.

    A Chatter session acts in one of its linked Agencies, as its own Mirror
    Employee there (created on first use): the only Agency when it has one,
    else the one `_chatter_agency_for_creator` picks for the named Creator.
    """
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
    if account_id:
        agency_user_id = await _chatter_agency_for_creator(
            chatter.id, chatter.owner_user_ids, account_id,
        )
    elif len(chatter.owner_user_ids) == 1:
        (agency_user_id,) = chatter.owner_user_ids
    else:
        raise HTTPException(status_code=400, detail="name a creator to choose the agency")
    return await _chatter_context(chatter, agency_user_id)


async def _chatter_context(chatter, agency_user_id: str) -> AgencyContext:
    """A Chatter session's context in one linked Agency, as its Mirror
    Employee there (created on first use); 503 when it cannot be resolved."""
    import employees  # lazy: employees re-exports this module; patched there by tests
    employee_id = await employees.get_or_create_mirror_employee(
        chatter.id, agency_user_id,
        display_name=chatter.display_name or chatter.username,
        color=chatter.color,
    )
    if employee_id is None:
        # ASSUMPTION: the 503 detail is `mirror employee unavailable`; the spec
        # fixes only the status. Overturned if a later Phase's UI needs
        # different wording.
        raise HTTPException(status_code=503, detail="mirror employee unavailable")
    return AgencyContext(
        agency_user_id=agency_user_id,
        employee_id=employee_id,
        is_owner=False,
        is_master=False,
    )


async def owner_context(account_id: str | None, detail: str) -> AgencyContext:
    """`agency_context` for an owner-only endpoint.

    ASSUMPTION: a Chatter session is refused 403 (`detail`) before
    `agency_context` runs, so a chatter linked to two Agencies gets 403 (not
    its 400 "name a creator") and no Mirror Employee is created by an
    endpoint it may not use. Rung 5, the spec's check order (401, then 403).
    Overturned if Phase 4's Permission roles open owner endpoints to some
    chatters.
    """
    if get_request_user() is None:
        from chatters import get_request_chatter as _grc
        if _grc() is not None:
            raise HTTPException(status_code=403, detail=detail)
    return await agency_context(account_id=account_id)


async def agency_contexts(*, account_id: str | None = None) -> list[AgencyContext]:
    """Every Agency context the current request acts in: `agency_context`'s
    one, except for a chatter linked to several Agencies that names no
    Creator, which gets one per linked Agency (in Agency id order) instead of
    the 400 — for reads that combine them (docs/spec/phase-04, the Applied
    settings read and Role enforcement). Same refusals and 503 otherwise.
    """
    if not account_id and get_request_user() is None:
        from chatters import get_request_chatter as _grc
        chatter = _grc()
        if chatter is not None and len(chatter.owner_user_ids) > 1:
            return [await _chatter_context(chatter, agency_user_id)
                    for agency_user_id in sorted(chatter.owner_user_ids)]
    return [await agency_context(account_id=account_id)]


async def _chatter_agency_for_creator(
    chatter_id: str,
    owner_user_ids: set[str] | frozenset[str],
    account_id: str,
) -> str:
    """The Agency a chatter acts in for a Creator it named (and that already
    passed `assert_account_owned`): the alphabetically first linked owner
    that holds the Creator in `user_accounts` and whose Chatter Access
    allowlist for this chatter does not exclude it.

    Unlike `resolve_chatter_employee_id`'s unfiltered tie-break, the
    allowlist applies first, so a cross-granted Creator allowed only under
    the later Agency resolves there (docs/spec/phase-01, Resolution rules).
    """
    import employees  # lazy: employees re-exports this module
    from chatters import _account_restrictions_for, _filter_owner_accounts
    async with get_session() as s:
        holders = await employees._sorted_holder_owner_ids(s, account_id, owner_user_ids)
        restrictions = await _account_restrictions_for(s, chatter_id)
    allowed = [
        uid for uid in holders
        if _filter_owner_accounts([(uid, account_id)], restrictions)
    ]
    if not allowed:
        # ASSUMPTION: no allowed holder despite `assert_account_owned`
        # passing (links or allowlist changed between the session load and
        # this read) is refused as `not your account`, not a 5xx. Overturned
        # if the owner wants such races surfaced as server errors.
        raise HTTPException(status_code=403, detail="not your account")
    return allowed[0]
