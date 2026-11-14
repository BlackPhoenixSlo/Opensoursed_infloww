"""service/ultra_api.py — the owner's Ultra plan page (app/app/ultra/plans/[id]): plan, read, OK, cancel.

  POST /admin/ultra/plans              {request} → a `planning` plan (ultra_plan: the model reads, then
                                       submits → `awaiting_ok`); 429 when today's AI budget is spent; 400
                                       "paste logins in the Connect card" when it holds an OnlyFans login
                                       (login_paste.holds_login), before any model call, nothing stored;
                                       its only 400 (the panel reads a 400 as this refusal)
  GET  /admin/ultra/plans/{id}         → the plan (ultra_run.view): card, step states
  POST /admin/ultra/plans/{id}/ok      {sha256} → starts the run; 409 when the hash is not the stored one,
                                       the plan expired or is no longer awaiting its OK
  POST /admin/ultra/plans/{id}/cancel  → stops it before its next step (a send in flight finishes) or
                                       its planning before the next model call; a `needs_you` run stops
  POST /admin/ultra/plans/{id}/pick    {step, ids} → a `needs_you` judge's picks: exactly its pick_n distinct
                                       ids from the candidates its state shows (422 else); the run goes on

Owner session (cookie) only: a bearer token is refused by token_auth's allowlist before it gets here, and
the OK, the pick and the new plan refuse any request without a Cookie again, because the run (and the planner's
reads) hold that cookie; a chatter session is
refused at chatters._CHATTER_BLOCKED_ADMIN_PREFIXES. Another owner's plan is a 404. The whole prefix is
audit-ineligible (audit_log._AUDIT_SKIP_PREFIXES): each step's own request carries the audit. Plans are made
by MCP `propose_plan` (mcp_api) or here (ultra_plan).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictInt

import login_paste
import toolbox
import ultra_plan
import ultra_plan_decide as upd
import ultra_judge_decide as uj
import ultra_run
from auth import require_user

router = APIRouter(prefix="/admin/ultra/plans", tags=["ultra"])

_SIGN_IN = "sign in as an account owner to see this plan"
LOGIN_REFUSED = "paste logins in the Connect card"


def _browser_creds(request: Request, detail: str) -> toolbox.Creds:
    """The caller's owner cookie; a bearer token, or no cookie, is a 403 saying `detail`."""
    creds = toolbox.Creds.from_request(request)
    if creds.authorization or not creds.cookie:
        raise HTTPException(403, detail)
    return creds


class OkBody(BaseModel):
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class PickBody(BaseModel):
    step: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,31}$")
    ids: list[StrictInt] = Field(..., min_length=1, max_length=uj.PICK_CARD)


class PlanBody(BaseModel):
    request: str = Field(..., min_length=1, max_length=upd.MAX_REQUEST)


@router.post("")
async def new_plan(body: PlanBody, request: Request) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    creds = _browser_creds(request, "start a plan in the browser, signed in as an account owner")
    if not body.request.strip():
        raise HTTPException(422, "say what the plan should do")
    if login_paste.holds_login(body.request):  # never to a model, never stored (ticket 11 credential guard)
        raise HTTPException(400, LOGIN_REFUSED)
    try:
        pid = await ultra_plan.start(body.request.strip(), user.id, user.account_ids, creds)
    except ultra_run.Refused as e:
        raise HTTPException(e.status, e.detail) from None
    return await get_plan(pid)


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
    creds = _browser_creds(request, "approve a plan in the browser, signed in as its owner")
    return await _act(plan_id, ultra_run.approve(plan_id, user.id, body.sha256, creds))


@router.post("/{plan_id}/cancel")
async def cancel_plan(plan_id: str) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    return await _act(plan_id, ultra_run.cancel(plan_id, user.id))


@router.post("/{plan_id}/pick")
async def pick_plan(plan_id: str, body: PickBody, request: Request) -> dict[str, Any]:
    user = require_user(detail=_SIGN_IN)
    _browser_creds(request, "pick in the browser, signed in as the plan's owner")
    return await _act(plan_id, ultra_run.pick(plan_id, user.id, body.step, body.ids))
