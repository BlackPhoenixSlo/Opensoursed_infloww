"""service/ultra_api.py — the owner's Ultra plan page (app/app/ultra/plans/[id]): read, OK, cancel.

  GET  /admin/ultra/plans/{id}         → the plan (ultra_run.view): card, step states
  POST /admin/ultra/plans/{id}/ok      {sha256} → starts the run; 409 when the hash is not the stored one,
                                       the plan expired or is no longer awaiting its OK
  POST /admin/ultra/plans/{id}/cancel  → stops it before its next step (a send in flight finishes)

Owner session (cookie) only: a bearer token is refused by token_auth's allowlist before it gets here, and
the OK refuses any request without a Cookie again, because the run holds that cookie; a chatter session is
refused at chatters._CHATTER_BLOCKED_ADMIN_PREFIXES. Another owner's plan is a 404. The whole prefix is
audit-ineligible (audit_log._AUDIT_SKIP_PREFIXES): each step's own request carries the audit. Plans are made
by MCP `propose_plan` (mcp_api); in-app planning is step 5.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import toolbox
import ultra_run
from auth import require_user

router = APIRouter(prefix="/admin/ultra/plans", tags=["ultra"])

_SIGN_IN = "sign in as an account owner to see this plan"


class OkBody(BaseModel):
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


@router.get("/{plan_id}")
async def get_plan(plan_id: str) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    out = await ultra_run.view(plan_id, user.id)
    if out is None:
        raise HTTPException(404, "plan not found")
    return out


async def _act(plan_id: str, coro) -> dict[str, Any]:
    try:
        await coro
    except ultra_run.Refused as e:
        raise HTTPException(e.status, e.detail) from None
    return await get_plan(plan_id)


@router.post("/{plan_id}/ok")
async def ok_plan(plan_id: str, body: OkBody, request: Request) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    creds = toolbox.Creds.from_request(request)
    if creds.authorization or not creds.cookie:
        raise HTTPException(403, "approve a plan in the browser, signed in as its owner")
    return await _act(plan_id, ultra_run.approve(plan_id, user.id, body.sha256, creds))


@router.post("/{plan_id}/cancel")
async def cancel_plan(plan_id: str) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    return await _act(plan_id, ultra_run.cancel(plan_id, user.id))
