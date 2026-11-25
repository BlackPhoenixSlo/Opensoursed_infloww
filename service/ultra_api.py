# Owner session (cookie) only: the run and planner reads hold that cookie, so a bearer token is refused.
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
    if login_paste.holds_login(body.request):
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
