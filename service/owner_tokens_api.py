"""service/owner_tokens_api.py — Settings → AI keys → Access tokens.

An Agency owner mints, lists and revokes their own owner access tokens
(owner_tokens): `Authorization: Bearer ifw_…` for a non-browser caller such as
an MCP client. Owner session only: the user id comes from the session, never
the request, as tenant_keys_api. A token reaches only the MCP endpoint, the
MCP tools' own routes and report-file downloads (token_auth.allowlist); every
other route, these included, answers it 403, so a leaked token cannot mint its
successor, sign in, or touch logins, keys or sharing.
The plaintext is returned once, by POST; only its sha256 and a hint are kept.
Ticket: docs/plans/ultra-mode/issues/03-owner-tokens.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

import owner_tokens
from auth import require_user
from db.engine import get_session
from db.models import OwnerToken

router = APIRouter(prefix="/admin/owner-tokens", tags=["owner-tokens"])

_SIGN_IN = "sign in as an account owner to manage access tokens"


class OwnerTokenCreateBody(BaseModel):
    name: str = Field(..., max_length=64)
    days: Literal[30, 90, 365] = owner_tokens.DEFAULT_DAYS

    @field_validator("name")
    @classmethod
    def _named(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name a token so you can tell it apart")
        return v


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def _row(t: OwnerToken) -> dict[str, Any]:
    return {
        "id": t.id, "name": t.name, "hint": t.hint, "created_at": _iso(t.created_at),
        "expires_at": _iso(t.expires_at), "last_used_at": _iso(t.last_used_at),
        "revoked_at": _iso(t.revoked_at),
    }


@router.get("")
async def list_tokens() -> dict[str, Any]:
    """The signed-in owner's tokens, newest first; never a token itself."""
    user = require_user(detail=_SIGN_IN)
    async with get_session() as s:
        rows = (await s.execute(
            select(OwnerToken).where(OwnerToken.user_id == user.id).order_by(OwnerToken.id.desc())
        )).scalars().all()
    return {"tokens": [_row(t) for t in rows]}


@router.post("")
async def create_token(body: OwnerTokenCreateBody) -> dict[str, Any]:
    """Mint a token for the signed-in owner. The response is the only place the
    plaintext `token` ever appears."""
    user = require_user(detail=_SIGN_IN)
    token = owner_tokens.mint()
    now = datetime.utcnow()
    async with get_session() as s:
        row = OwnerToken(
            user_id=user.id, name=body.name, token_sha256=owner_tokens.digest(token),
            hint=owner_tokens.hint(token), created_at=now, expires_at=now + timedelta(days=body.days),
        )
        s.add(row)
        await s.flush()
        out = _row(row)
    return {**out, "token": token}


@router.delete("/{token_id}")
async def revoke_token(token_id: int) -> dict[str, Any]:
    """Revoke one of the signed-in owner's tokens (404 for anyone else's). The
    row stays, so the list shows when it was revoked; its next request gets a 401."""
    user = require_user(detail=_SIGN_IN)
    async with get_session() as s:
        row = (await s.execute(
            select(OwnerToken).where(OwnerToken.id == token_id, OwnerToken.user_id == user.id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="no such token")
        if row.revoked_at is None:
            row.revoked_at = datetime.utcnow()
        out = _row(row)
    return out
