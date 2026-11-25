from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

import tenant_keys
from audit_log import credential_write
from auth import (
    _assert_admin_password, require_master, require_user,
)

router = APIRouter(prefix="/admin/my-llm-keys", tags=["tenant-keys"])


_SIGN_IN = "sign in as an account owner to manage your API keys"


@router.get("")
async def my_llm_keys_status() -> dict[str, Any]:
    """Masked status of the signed-in agency's provider keys, plus any of their
    accounts that a second owner is also linked to. Never the raw value — the
    hint is `••••` + the last four characters.

    The shared-account list rides along here rather than getting its own
    endpoint because it answers the same question the keys do — "why did my
    models stop replying" — and the card is where someone asking it looks."""
    user = require_user(detail=_SIGN_IN)
    return {
        "providers": await tenant_keys.status(user.id),
        "shared_accounts": await tenant_keys.shared_accounts(user.account_ids),
    }


@router.put("", dependencies=[Depends(credential_write)])
async def my_llm_keys_set(request: Request) -> dict[str, Any]:
    """Set or clear this agency's keys. Body is {provider: value, …}; an empty
    string clears that provider. Send ONLY the providers you changed — an absent
    provider keeps its stored key, which is what lets the form leave untouched
    fields blank rather than round-tripping a mask back to us."""
    user = require_user(detail=_SIGN_IN)
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="expected a JSON object of provider→key")
    try:
        await tenant_keys.set_keys(user.id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"providers": await tenant_keys.status(user.id)}



admin_router = APIRouter(prefix="/admin/users", tags=["tenant-keys"],
                         dependencies=[Depends(require_master)])


class AgencyKeysBody(BaseModel):
    admin_password: str = Field(..., min_length=1)
    providers: dict[str, str] = Field(default_factory=dict)


async def _assert_agency(user_id: str) -> None:
    if not await tenant_keys.agency_exists(user_id):
        raise HTTPException(status_code=404, detail=f"unknown user {user_id!r}")


@admin_router.get("/llm-key-status")
async def agency_llm_key_status_all() -> dict[str, Any]:
    """Every agency, with how many of its models can currently TALK and which
    providers it already has a key for. Feeds the founder's Manage screen.

    Registered BEFORE `/{user_id}/llm-keys` and matched first because it is a
    literal path — but it is also a different shape (a list, no user id), so
    the two cannot be confused by a caller.

    Master only, and not merely because keys are involved: this is a roster of
    every tenant on the deployment, which is not one agency's business to read.
    Provider NAMES only — never a value or a hint.
    """
    from accounts import list_accounts
    registry = {
        str(a.get("id") or ""): bool(a.get("has_session"))
        for a in list_accounts() if a.get("id")
    }
    required = {"deepseek"}
    return {"agencies": await tenant_keys.key_overview(registry, required)}


@admin_router.get("/{user_id}/llm-keys")
async def agency_llm_keys_status(user_id: str) -> dict[str, Any]:
    """Masked status of ONE agency's provider keys, for the founder's Manage
    screen. Never the raw value."""
    await _assert_agency(user_id)
    return {"user_id": user_id, "providers": await tenant_keys.status(user_id)}


@admin_router.put("/{user_id}/llm-keys", dependencies=[Depends(credential_write)])
async def agency_llm_keys_set(
    user_id: str, body: AgencyKeysBody = Body(...),
) -> dict[str, Any]:
    """Set or clear one agency's keys on their behalf. Same rules as the
    self-serve card: "" clears, an absent provider keeps its stored value, and a
    masked placeholder is refused rather than stored."""
    _assert_admin_password(body.admin_password)
    await _assert_agency(user_id)
    try:
        await tenant_keys.set_keys(user_id, dict(body.providers))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user_id": user_id, "providers": await tenant_keys.status(user_id)}


status_router = APIRouter(tags=["tenant-keys"])

_KIND_PURPOSE = {
    "autoreply": "autoreply", "reply_mass_funnel": "reply_mass_funnel",
    "welcome_chatter_for_info": "welcome_chatter_for_info",
    "send_followup": "followup", "gen_info": "gen_info",
    "describe_media": "describe_media",
}


async def _funnel_needs_key(account_id: str) -> bool:
    from automations.reply_mass_funnel import needs_llm
    return await needs_llm(account_id)


_KIND_NEEDS_KEY = {"reply_mass_funnel": _funnel_needs_key}


async def _last_key_error(account_id: str, kind: str, owners: list[str]) -> dict | None:
    import json as _json
    from sqlalchemy import func, select
    from db.engine import get_session
    from db.models import AutomationRun, UserLlmKey
    async with get_session() as s:
        row = (await s.execute(
            select(AutomationRun.stats_json, AutomationRun.started_at)
            .where(AutomationRun.account_id == account_id,
                   AutomationRun.kind == kind,
                   AutomationRun.stats_json.isnot(None))
            .order_by(AutomationRun.started_at.desc(), AutomationRun.id.desc())
            .limit(1))).first()
        if not row:
            return None
        raw, started_at = row
        try:
            ke = _json.loads(raw) or {}
        except ValueError:
            return None
        ke = ke.get("key_error") if isinstance(ke, dict) else None
        if not (isinstance(ke, dict) and str(ke.get("error", "")).startswith("api_key_")):
            return None
        if owners and ke.get("provider") and started_at is not None:
            saved = await s.scalar(
                select(func.max(UserLlmKey.updated_at))
                .where(UserLlmKey.user_id.in_(owners),
                       UserLlmKey.provider == ke["provider"],
                       UserLlmKey.api_key != ""))
            if saved is not None and saved > started_at:
                return None
    return ke


async def _kind_provider(account_id: str, kind: str, purpose: str) -> str:
    import llm_client
    from automations._common import resolve_model
    return ("deepinfra" if kind == "describe_media" else
            llm_client.MODELS[await resolve_model(account_id, purpose)].provider)


async def require_llm_key(account_id: str, kind: str) -> None:
    import llm_client
    purpose = _KIND_PURPOSE.get(kind)
    if not purpose:
        return
    needs_key = _KIND_NEEDS_KEY.get(kind)
    if needs_key is not None and not await needs_key(account_id):
        return
    provider = await _kind_provider(account_id, kind, purpose)
    if not await llm_client.llm_key_available(account_id, provider, purpose):
        house = not await tenant_keys.owners_of(account_id)
        raise llm_client.LLMKeyError("missing", provider, purpose, house=house)


@status_router.get("/admin/ai-key-status")
async def ai_key_status(account_id: str = Query(..., min_length=1),
                        kinds: str = Query(..., min_length=1)) -> dict[str, Any]:
    """`items`: per automation kind, `{kind, provider, available, last_key_error}`.
    `notices`: what the page shows — one `key_error_payload` per (problem,
    provider), naming every kind it stops. Unknown kinds are ignored, so a page
    may ask for any rule kind and get nothing for the ones without an LLM."""
    from auth import assert_account_owned
    import llm_client
    assert_account_owned(account_id)
    owners = await tenant_keys.owners_of(account_id)
    house = not owners
    items: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[str]] = {}
    for kind in dict.fromkeys(k.strip() for k in kinds.split(",")):
        purpose = _KIND_PURPOSE.get(kind)
        if not purpose:
            continue
        provider = await _kind_provider(account_id, kind, purpose)
        available = await llm_client.llm_key_available(account_id, provider, purpose)
        last = await _last_key_error(account_id, kind, owners)
        items.append({"kind": kind, "provider": provider, "available": available,
                      "last_key_error": last})
        stored = str(last["error"])[len("api_key_"):] if last else ""
        problem = "missing" if not available else ("" if stored == "missing" else stored)
        if problem:
            prov = provider if not available else str(last.get("provider") or provider)
            groups.setdefault((problem, prov), []).append(llm_client.feature_label(purpose))
    notices = []
    for (problem, provider), features in groups.items():
        names = (features[0] if len(features) == 1
                 else ", ".join(features[:-1]) + " and " + features[-1])
        notices.append(llm_client.key_error_payload(
            llm_client.LLMKeyError(problem, provider, house=house), feature=names))
    return {"account_id": account_id, "items": items, "notices": notices}
