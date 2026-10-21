"""service/tenant_keys_api.py — Setup → Keys, THIS agency's own LLM keys.

Distinct from /admin/secrets (secrets_store) in both scope and blast radius:
those are the DEPLOYMENT's house keys, these are one owner's. An owner may only
ever read or write their own row — the user id comes from the session and is
never taken from the request, so there is no cross-tenant write to defend
against.

A signed-in User is required. A Chatter session resolves to no user here (a
different principal with a different cookie) and so gets a 401: chatters do the
messaging work, they do not hold the agency's billing credentials. Writes while
impersonating are already refused by the session middleware (impersonation is
read-only), so a founder cannot overwrite a friend's key while wearing their
identity.

The store itself is `tenant_keys`, which stays free of web imports because the
LLM money path imports it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

import tenant_keys
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


@router.put("")
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


# ── Founder: set an agency's keys FOR them ────────────────────────────
#
# The managed flow this deployment actually runs: an agency connects its OF
# model and the founder does the rest. Everything else in that flow already
# works — a master sees every account through the fat set without needing a
# link, and Admin → Manage grants and revokes them. The one thing missing was
# the credential: `/admin/my-llm-keys` writes only the SIGNED-IN owner's row,
# and impersonation is read-only, so an agency that had not pasted a key could
# not be fixed from any screen.
#
# It is also what turns the upgrade step from "sign in as each owner in turn"
# into one page.
#
# Two gates, matching the neighbouring grant/revoke endpoints and then some:
# a signed-in MASTER for both verbs (a masked hint still leaks the last four
# characters of another tenant's key, so the read is not public either), plus
# the founder password on the write, because this stores a credential someone
# else's models will spend.

# The gate is a ROUTER dependency, not a line at the top of each handler.
# 231c0ee exists precisely because a gate that had to be typed into every
# handler was not typed into two of them, and /admin/secrets sat ungated for the
# life of those routes. Declaring it once means a route added here is master-only
# by construction — forgetting is no longer possible.
admin_router = APIRouter(prefix="/admin/users", tags=["tenant-keys"],
                         dependencies=[Depends(require_master)])


class AgencyKeysBody(BaseModel):
    admin_password: str = Field(..., min_length=1)
    # {provider: value}; "" clears. Only the providers named are touched.
    providers: dict[str, str] = Field(default_factory=dict)


async def _assert_agency(user_id: str) -> None:
    """404 on an id that names no agency, before either verb answers.

    Not defensive tidying — both verbs fail badly without it. The read hands
    back every provider unset, which is indistinguishable from a real agency
    that never pasted a key, so a mistyped id looks like the problem the screen
    exists to fix. The write dies on the `user_llm_keys` foreign key as a 500.
    Same check, same wording, as the grant endpoints one file over.
    """
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
    # Local import, matching `auth.admin_list_user_accounts` — the registry
    # pulls in the account layer and this module has no business dragging it
    # into every import of the key API.
    #
    # `has_session` is the registry's own answer and the only current one: the
    # `sessions` TABLE has no live writer, so the store must not be left to
    # guess from it.
    from accounts import list_accounts
    registry = {
        str(a.get("id") or ""): bool(a.get("has_session"))
        for a in list_accounts() if a.get("id")
    }
    # What a live model needs before it can reply at all. Named HERE, at the
    # composition root, rather than inferred in the store or hardcoded in the
    # component: credentials resolve per provider, so an agency holding only a
    # DeepInfra key would otherwise read as configured while every chat reply it
    # makes fails closed. Every account on this deployment leaves
    # `model_by_purpose` unset and falls through to the house DeepSeek default;
    # when that stops being true, this set is the one line to change.
    required = {"deepseek"}
    return {"agencies": await tenant_keys.key_overview(registry, required)}


@admin_router.get("/{user_id}/llm-keys")
async def agency_llm_keys_status(user_id: str) -> dict[str, Any]:
    """Masked status of ONE agency's provider keys, for the founder's Manage
    screen. Never the raw value."""
    await _assert_agency(user_id)
    return {"user_id": user_id, "providers": await tenant_keys.status(user_id)}


@admin_router.put("/{user_id}/llm-keys")
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


# ── /admin/ai-key-status: the key notice on an automation's page ─────────────
# Background automations cannot toast, so their page asks here. Readable by
# anyone who may see the account (chatters too — they get the sentence without
# the owner-only link), which is why it is its own router and not under the
# chatter-blocked /admin/my-llm-keys prefix. Presence and a stored sentence
# only: never a key, a mask or a hint.
status_router = APIRouter(tags=["tenant-keys"])

# automation kind → the purpose its calls bill under (send_followup's differs).
_KIND_PURPOSE = {
    "autoreply": "autoreply", "reply_mass_funnel": "reply_mass_funnel",
    "welcome_chatter_for_info": "welcome_chatter_for_info",
    "send_followup": "followup", "gen_info": "gen_info",
    "describe_media": "describe_media",
}


async def _last_key_error(account_id: str, kind: str) -> dict | None:
    """The `key_error` the kind's LATEST finished run carried, or None. The
    latest only: a run after the key was fixed carries none, which clears it."""
    import json as _json
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import AutomationRun
    async with get_session() as s:
        raw = await s.scalar(
            select(AutomationRun.stats_json)
            .where(AutomationRun.account_id == account_id,
                   AutomationRun.kind == kind,
                   AutomationRun.stats_json.isnot(None))
            .order_by(AutomationRun.started_at.desc(), AutomationRun.id.desc())
            .limit(1))
    try:
        ke = (_json.loads(raw) or {}).get("key_error") if raw else None
    except ValueError:
        return None
    return ke if isinstance(ke, dict) and str(ke.get("error", "")).startswith("api_key_") else None


@status_router.get("/admin/ai-key-status")
async def ai_key_status(account_id: str = Query(..., min_length=1),
                        kinds: str = Query(..., min_length=1)) -> dict[str, Any]:
    """`items`: per automation kind, `{kind, provider, available, last_key_error}`.
    `notices`: what the page shows — one `key_error_payload` per (problem,
    provider), naming every kind it stops. Unknown kinds are ignored, so a page
    may ask for any rule kind and get nothing for the ones without an LLM."""
    from auth import assert_account_owned
    import llm_client
    from automations._common import resolve_model
    assert_account_owned(account_id)
    house = not await tenant_keys.owners_of(account_id)
    items: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[str]] = {}
    for kind in dict.fromkeys(k.strip() for k in kinds.split(",")):
        purpose = _KIND_PURPOSE.get(kind)
        if not purpose:
            continue
        provider = ("deepinfra" if kind == "describe_media" else
                    llm_client.MODELS[await resolve_model(account_id, purpose)].provider)
        available = await llm_client.llm_key_available(account_id, provider, purpose)
        last = await _last_key_error(account_id, kind)
        items.append({"kind": kind, "provider": provider, "available": available,
                      "last_key_error": last})
        # Live presence wins; a stored "missing" is stale once a key exists.
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
