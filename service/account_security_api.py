"""service/account_security_api.py — the sign-in form's one endpoint, the 2FA
routes and "Log out other sessions" (/auth/sign-in, /auth/2fa/*,
/auth/sessions/*; roadmap S14, 6.2; 07 M3/M4/M5). Helpers: account_security.py.

The signed-in principal of a route here is `chatters.current_actor()`: the
owner cookie when present, else the chatter's. Under the founder's
impersonation every route here is refused, since /auth/* is exempt from its
read-only rule and these would change the friend's account.

`POST /auth/sign-in` is the sign-in form's: one password check across owners
then employees, one throttle token per submit (account_security.password_sign_in).
/auth/login and /chatter/login stay for scripts and single-principal callers.

After a challenge, `POST /auth/2fa/login {ticket, code}` (a TOTP or backup
code) sets the session cookie; a setup ticket goes through `/auth/2fa/init` and
`/auth/2fa/activate`, which sets it once 2FA is on. Code attempts share the
sign-in throttle (login_throttle) under the principal's username.

Setup is stateless until it succeeds: `init` returns the new secret (shown for
manual entry and as an otpauth:// link; the app has no QR library) with an
enrol token signing it to the principal; `activate` checks a code against it
and stores it only while the principal has no secret yet, so a stolen session
cannot swap an existing factor. Turning 2FA on or off signs every other session
out, and the caller gets a fresh cookie.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, update

import auth
import chatters
import login_throttle
from account_security import (
    ACCOUNT_DEACTIVATED,
    MODELS,
    Kind,
    TwoFactorChallenge,
    clear_two_factor_values,
    make_signed,
    match_step,
    new_recovery_codes,
    new_secret,
    otpauth_uri,
    parse_signed,
    password_sign_in,
    remaining_after,
    required_for_chatter,
    revoke_sessions,
    stored_codes,
)
from db.engine import get_session
from session_stamps import session_revoked

router = APIRouter(prefix="/auth", tags=["account-security"])

_EXPIRED = {"code": "ticket_expired", "message": "Your sign-in expired. Enter your password again."}
_BAD_CODE = {"code": "invalid_code", "message": "That code is not right. Try the newest code from your app."}
REQUIRED_MESSAGE = "Two-factor authentication required by your organization"


def set_session_cookie(kind: Kind, response: Response, principal_id: str) -> None:
    if kind == "user":
        auth._set_session_cookie(response, principal_id)
    else:
        chatters._set_session_cookie(response, principal_id)


def _principal() -> tuple[Kind, str]:
    if auth.get_impersonation() is not None:
        raise HTTPException(status_code=403, detail="exit impersonation to change this account's security")
    actor = chatters.current_actor()
    if actor is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return ("user" if actor.kind == "user" else "chatter"), actor.id


async def _ticket_principal(s, ticket: str, purpose: Literal["verify", "setup"]):
    """The row a sign-in ticket names, or 401 when it expired, was revoked or the row is gone."""
    parsed = parse_signed(ticket, purpose)
    if parsed is None:
        raise HTTPException(status_code=401, detail=_EXPIRED)
    kind = parsed.kind
    row = await s.get(MODELS[kind], parsed.principal_id)
    if row is None or session_revoked(parsed.issued, row.sessions_valid_after):
        raise HTTPException(status_code=401, detail=_EXPIRED)
    if kind == "chatter" and not row.is_active:
        raise HTTPException(status_code=403, detail=ACCOUNT_DEACTIVATED)
    return kind, row


async def _setup_principal(s, ticket: str | None):
    """Who is setting up 2FA: the setup ticket's principal at sign-in, else the session's."""
    if ticket:
        return await _ticket_principal(s, ticket, "setup")
    kind, pid = _principal()
    row = await s.get(MODELS[kind], pid)
    if row is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return kind, row


async def _consume_code(s, kind: Kind, row, code: str) -> bool:
    """Accept a TOTP or backup code for `row` once: the step or the code is
    spent by a conditional UPDATE, so a racing request with the same code fails."""
    model = MODELS[kind]
    if not row.totp_secret:
        return False
    step = match_step(row.totp_secret, code, row.totp_last_step)
    if step is not None:
        result = await s.execute(update(model).where(
            model.id == row.id,
            or_(model.totp_last_step.is_(None), model.totp_last_step < step),
        ).values(totp_last_step=step))
        return (result.rowcount or 0) == 1
    left = remaining_after(row.totp_recovery, code)
    if left is not None:
        result = await s.execute(update(model).where(
            model.id == row.id, model.totp_recovery == row.totp_recovery,
        ).values(totp_recovery=left))
        return (result.rowcount or 0) == 1
    return False


def _utc_iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt is not None else None


# ── Routes ────────────────────────────────────────────────────────────

class _SignInBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SignInResp(BaseModel):
    kind: Kind


class _TicketBody(BaseModel):
    ticket: str | None = Field(None, max_length=512)


class _ActivateBody(BaseModel):
    enrol_token: str = Field(..., min_length=1, max_length=512)
    code: str = Field(..., min_length=1, max_length=64)
    ticket: str | None = Field(None, max_length=512)


class _CodeBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


class _LoginCodeBody(BaseModel):
    ticket: str = Field(..., min_length=1, max_length=512)
    code: str = Field(..., min_length=1, max_length=64)


@router.post("/sign-in", response_model=SignInResp | TwoFactorChallenge)
async def sign_in(
    request: Request, response: Response, body: _SignInBody = Body(...),
) -> SignInResp | TwoFactorChallenge:
    """The sign-in form: an owner's or an employee's username and password.
    `{kind}` names the session it set; a `TwoFactorChallenge` sets none. 401
    wrong password, 403 `ACCOUNT_DEACTIVATED`, 429 past the throttle."""
    username = auth._normalize_username(body.username)
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    result = await password_sign_in(request, username, body.password, ("user", "chatter"))
    if isinstance(result, TwoFactorChallenge):
        return result
    kind, row = result
    set_session_cookie(kind, response, row.id)
    return SignInResp(kind=kind)


@router.get("/2fa")
async def two_factor_status() -> dict[str, Any]:
    """`{enabled, enabled_at, recovery_codes_left, required}` for the signed-in principal."""
    kind, pid = _principal()
    async with get_session() as s:
        row = await s.get(MODELS[kind], pid)
        if row is None:
            raise HTTPException(status_code=401, detail="sign in required")
        required = kind == "chatter" and await required_for_chatter(s, pid)
        return {
            "enabled": bool(row.totp_secret),
            "enabled_at": _utc_iso(row.totp_enabled_at) if row.totp_secret else None,
            "recovery_codes_left": len(stored_codes(row.totp_recovery)) if row.totp_secret else 0,
            "required": required,
        }


@router.post("/2fa/init")
async def two_factor_init(body: _TicketBody | None = Body(None)) -> dict[str, str]:
    """Start setup: a new secret for the authenticator app and the enrol token
    `activate` takes back. Nothing is stored yet. 409 when 2FA is already on."""
    async with get_session() as s:
        kind, row = await _setup_principal(s, body.ticket if body else None)
        if row.totp_secret:
            raise HTTPException(status_code=409, detail="two-factor authentication is already on")
        secret = new_secret()
        return {
            "secret": secret,
            "otpauth_uri": otpauth_uri(row.username, secret),
            "enrol_token": make_signed("enrol", kind, row.id, secret),
        }


@router.post("/2fa/activate")
async def two_factor_activate(
    request: Request, response: Response, body: _ActivateBody = Body(...),
) -> dict[str, Any]:
    """Finish setup with a code from the app: 2FA on, the 10 backup codes
    returned once, every other session signed out and this caller given a
    fresh cookie (its first one when a setup ticket carried the sign-in)."""
    async with get_session() as s:
        kind, row = await _setup_principal(s, body.ticket)
        enrol = parse_signed(body.enrol_token, "enrol")
        if enrol is None or (enrol.kind, enrol.principal_id) != (kind, row.id):
            raise HTTPException(status_code=400, detail="setup expired — start again")
        attempt = login_throttle.take(request, row.username)
        step = match_step(enrol.value, body.code, None)
        if step is None:
            raise HTTPException(status_code=400, detail=_BAD_CODE)
        codes, hashed = new_recovery_codes()
        now = datetime.utcnow()
        model = MODELS[kind]
        result = await s.execute(update(model).where(
            model.id == row.id, model.totp_secret.is_(None),
        ).values(totp_secret=enrol.value, totp_enabled_at=now, totp_recovery=hashed,
                 totp_last_step=step, last_seen_at=now))
        if (result.rowcount or 0) != 1:
            raise HTTPException(status_code=409, detail="two-factor authentication is already on")
        await revoke_sessions(s, kind, row.id)
        principal_id = row.id
    attempt.succeeded()
    set_session_cookie(kind, response, principal_id)
    return {"recovery_codes": codes, "enabled_at": _utc_iso(now), "kind": kind}


@router.post("/2fa/login")
async def two_factor_login(
    request: Request, response: Response, body: _LoginCodeBody = Body(...),
) -> SignInResp:
    """The sign-in's 2FA step: a TOTP or backup code for a verify ticket sets
    the session cookie. `{kind}` names the session."""
    async with get_session() as s:
        kind, row = await _ticket_principal(s, body.ticket, "verify")
        attempt = login_throttle.take(request, row.username)
        if not await _consume_code(s, kind, row, body.code):
            raise HTTPException(status_code=400, detail=_BAD_CODE)
        model = MODELS[kind]
        await s.execute(update(model).where(model.id == row.id).values(last_seen_at=datetime.utcnow()))
        principal_id = row.id
    attempt.succeeded()
    set_session_cookie(kind, response, principal_id)
    return SignInResp(kind=kind)


@router.post("/2fa/disable")
async def two_factor_disable(
    request: Request, response: Response, body: _CodeBody = Body(...),
) -> dict[str, bool]:
    """Turn 2FA off with a current TOTP or backup code; every other session is
    signed out and this caller gets a fresh cookie. Refused for an employee
    while one of their Agencies requires it."""
    kind, pid = _principal()
    async with get_session() as s:
        row = await s.get(MODELS[kind], pid)
        if row is None or not row.totp_secret:
            raise HTTPException(status_code=409, detail="two-factor authentication is off")
        if kind == "chatter" and await required_for_chatter(s, pid):
            raise HTTPException(status_code=409, detail=REQUIRED_MESSAGE)
        attempt = login_throttle.take(request, row.username)
        if not await _consume_code(s, kind, row, body.code):
            raise HTTPException(status_code=400, detail=_BAD_CODE)
        model = MODELS[kind]
        await s.execute(update(model).where(model.id == pid).values(**clear_two_factor_values()))
        await revoke_sessions(s, kind, pid)
    attempt.succeeded()
    set_session_cookie(kind, response, pid)
    return {"ok": True}


@router.post("/2fa/recovery-codes")
async def two_factor_new_codes(request: Request, body: _CodeBody = Body(...)) -> dict[str, Any]:
    """10 new backup codes for a current TOTP or backup code; the old ones stop working."""
    kind, pid = _principal()
    async with get_session() as s:
        row = await s.get(MODELS[kind], pid)
        if row is None or not row.totp_secret:
            raise HTTPException(status_code=409, detail="two-factor authentication is off")
        attempt = login_throttle.take(request, row.username)
        if not await _consume_code(s, kind, row, body.code):
            raise HTTPException(status_code=400, detail=_BAD_CODE)
        codes, hashed = new_recovery_codes()
        model = MODELS[kind]
        await s.execute(update(model).where(model.id == pid).values(totp_recovery=hashed))
    attempt.succeeded()
    return {"recovery_codes": codes}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(response: Response) -> dict[str, bool]:
    """Log out other sessions: every cookie this principal holds stops working,
    and this caller gets a fresh one so it stays signed in."""
    kind, pid = _principal()
    async with get_session() as s:
        await revoke_sessions(s, kind, pid)
    set_session_cookie(kind, response, pid)
    return {"ok": True}
