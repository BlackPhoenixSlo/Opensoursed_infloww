"""service/s4s_common.py — the owner-only check, JSON body reader and
Discovery listing rule every Share for Share router uses (`s4s_api`,
`s4s_media`, `s4s_requests_api`, `s4s_schedule_api`). A leaf: it imports no
S4S module, so the routers form a plain chain (s4s_api → s4s_schedule_api →
s4s_requests_api) with no cycle.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy import select

from db.models import S4SBlock, S4SProfile, UserAccount
from employees import AgencyContext, json_object, owner_context


_OWNER_ONLY = "only the agency owner manages Share for Share"


async def _owner_context(account_id: str | None = None) -> AgencyContext:
    return await owner_context(account_id, _OWNER_ONLY)


async def _json_object(request: Request) -> dict[str, Any]:
    return await json_object(request, 400)


def listed_to(agency_user_id: str) -> tuple:
    """The conditions on `S4SProfile` for a Creator Discovery lists to this
    Agency (ADR-0011): opted in, visible, still linked to an Agency, and not
    blocked by this Agency. The Primary-post join is the caller's."""
    in_agency = select(UserAccount.account_id).where(UserAccount.account_id == S4SProfile.account_id).exists()
    blocked = select(S4SBlock.account_id).where(S4SBlock.agency_user_id == agency_user_id)
    return (S4SProfile.opted_in.is_(True), S4SProfile.discovery_visible.is_(True), in_agency,
            S4SProfile.account_id.not_in(blocked))
