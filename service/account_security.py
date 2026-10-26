"""service/account_security.py — password sign-in, personal 2FA and session
revoke for both principals (roadmap S14, 6.2; 07 M3/M4/M5). The routes are
account_security_api.py; this module imports neither auth nor chatters, so
both import it.

Both principals, owners (`users`, kind "user") and employees (`chatters`, kind
"chatter"), carry the same columns (db.models._LoginSecurity).

2FA is TOTP (RFC 6238: SHA-1, 30 s, 6 digits, the authenticator apps'
defaults; stdlib hmac, no new dependency) plus 10 backup codes stored as
sha256 (random codes, not passwords). A code is accepted one step either side
of now and never twice (`totp_last_step`, a backup code is spent); both are
consumed with a conditional UPDATE so two racing requests cannot share one.

Sign-in. `password_sign_in` takes one sign-in throttle token (login_throttle)
per submit, checks the password, then `challenge_for`: a principal with 2FA on
gets `{two_factor: "verify", ticket}` and no cookie; an employee without it
whose Agency requires it (the `security` Settings blob's `require_2fa`) gets
`{two_factor: "setup", ticket}`. The ticket is signed, names the principal and
its purpose, lives TICKET_TTL_SECONDS and dies with a session revoke; it
travels in the JSON body, never a cookie.

ASSUMPTION: Organization enforcement applies to employees only, as Infloww's
copy ("All employees will be required to set up and use two-factor
authentication"), so the owner is never forced. Rung 4. Overturned if the owner
wants their own account held to it too.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from datetime import datetime
from typing import Any, Literal, NamedTuple
from urllib.parse import quote

from fastapi import HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import events
import login_throttle
from db.engine import get_session
from db.models import Chatter, ChatterUser, User
from brand import BRAND_NAME
from session_stamps import now_ms, sign

ISSUER = BRAND_NAME
TICKET_TTL_SECONDS = 5 * 60
ENROL_TTL_SECONDS = 10 * 60
RECOVERY_CODE_COUNT = 10
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6

Kind = Literal["user", "chatter"]
MODELS: dict[Kind, type[User] | type[Chatter]] = {"user": User, "chatter": Chatter}

# Sign-in refused because the login is switched off or no Agency has it any more
# (Deactivate unlinks it, employees.delete_employee). Typed, so the sign-in page
# shows the reason banner (roadmap 6.14); the words are Infloww's
# account_deactivated_contact_admin.
ACCOUNT_DEACTIVATED = {
    "code": "account_deactivated",
    "message": "Your account has been deactivated. Contact your organization's administrator for assistance.",
}
INVALID_LOGIN = "invalid username or password"


# ── TOTP ──────────────────────────────────────────────────────────────

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp(secret: str, step: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** TOTP_DIGITS).zfill(TOTP_DIGITS)


def current_step() -> int:
    return int(time.time() // TOTP_STEP_SECONDS)


def match_step(secret: str, code: str, last_step: int | None) -> int | None:
    """The step `code` is valid for (now, or one either side), skipping any step
    already used; None when it matches none."""
    code = "".join(code.split())
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    now = current_step()
    for step in (now - 1, now, now + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def otpauth_uri(username: str, secret: str) -> str:
    label = quote(f"{ISSUER}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"


# ── Backup codes ──────────────────────────────────────────────────────

def _hash_code(code: str) -> str:
    return hashlib.sha256("".join(code.lower().replace("-", "").split()).encode("utf-8")).hexdigest()


def new_recovery_codes() -> tuple[list[str], str]:
    """(the codes to show once, their hashes as stored). 64 random bits each,
    shown as four groups of four hex digits."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(8)
        codes.append("-".join(raw[i:i + 4] for i in range(0, 16, 4)))
    return codes, json.dumps([_hash_code(c) for c in codes])


def stored_codes(stored: str | None) -> list[str]:
    try:
        loaded = json.loads(stored) if stored else []
    except ValueError:
        return []
    return [h for h in loaded if isinstance(h, str)] if isinstance(loaded, list) else []


def remaining_after(stored: str | None, code: str) -> str | None:
    """The stored list without `code`'s hash, or None when it is not one of them."""
    wanted = _hash_code(code)
    hashes = stored_codes(stored)
    for i, h in enumerate(hashes):
        if hmac.compare_digest(h, wanted):
            return json.dumps(hashes[:i] + hashes[i + 1:])
    return None


# ── Signed tokens ─────────────────────────────────────────────────────
# The 2FA sign-in tickets ("verify", "setup") and the setup's enrol token
# ("enrol", carrying the new secret). Signed with the owner session secret under
# their own scope, stamped on the sessions' clock (session_stamps), so a revoke
# ends a ticket as it does a cookie. Format: `purpose.kind.id.value.issued_ms.sig`.

Purpose = Literal["verify", "setup", "enrol"]
_TTL_SECONDS: dict[Purpose, int] = {"verify": TICKET_TTL_SECONDS, "setup": TICKET_TTL_SECONDS,
                                    "enrol": ENROL_TTL_SECONDS}
_KINDS: dict[str, Kind] = {"user": "user", "chatter": "chatter"}
_SCOPE = "account-security"


class Signed(NamedTuple):
    kind: Kind
    principal_id: str
    value: str  # the enrol token's secret; empty on a ticket
    issued: int  # ms, session_stamps.now_ms


def make_signed(purpose: Purpose, kind: Kind, principal_id: str, value: str = "") -> str:
    payload = f"{purpose}.{kind}.{principal_id}.{value}.{now_ms()}"
    return f"{payload}.{sign(payload, _SCOPE)}"


def parse_signed(token: str, purpose: Purpose) -> Signed | None:
    """The token's fields when it is a `purpose` token signed here and within
    its TTL; None otherwise."""
    parts = (token or "").split(".")
    if len(parts) != 6 or parts[0] != purpose:
        return None
    kind = _KINDS.get(parts[1])
    if kind is None or not hmac.compare_digest(parts[5], sign(".".join(parts[:5]), _SCOPE)):
        return None
    try:
        issued = int(parts[4])
    except ValueError:
        return None
    if now_ms() - issued > _TTL_SECONDS[purpose] * 1000:
        return None
    return Signed(kind, parts[2], parts[3], issued)


# ── 2FA policy ────────────────────────────────────────────────────────

class TwoFactorChallenge(BaseModel):
    two_factor: Literal["verify", "setup"]
    ticket: str
    username: str


async def owner_requires_2fa(s, owner_user_id: str) -> bool:
    # Lazy: settings_api imports employees, which imports this module.
    from settings_api import applied_blob
    return (await applied_blob(s, owner_user_id, "security")).get("require_2fa") is True


async def required_for_chatter(s, chatter_id: str) -> bool:
    """Whether any Agency this employee is linked to requires 2FA."""
    owners = (await s.execute(
        select(ChatterUser.user_id).where(ChatterUser.chatter_id == chatter_id)
    )).scalars().all()
    for owner_id in owners:
        if await owner_requires_2fa(s, owner_id):
            return True
    return False


async def challenge_for(s, kind: Kind, row) -> TwoFactorChallenge | None:
    """The 2FA step a right password leads to, or None to sign in at once."""
    if row.totp_secret:
        return TwoFactorChallenge(two_factor="verify", ticket=make_signed("verify", kind, row.id),
                                  username=row.username)
    if kind == "chatter" and await required_for_chatter(s, row.id):
        return TwoFactorChallenge(two_factor="setup", ticket=make_signed("setup", kind, row.id),
                                  username=row.username)
    return None


# ── Password sign-in ──────────────────────────────────────────────────

async def password_sign_in(
    request: Request, username: str, password: str, kinds: tuple[Kind, ...],
) -> tuple[Kind, Any] | TwoFactorChallenge:
    """Check `username`/`password` against each principal table in `kinds`, in
    order; the first whose password matches signs in. One sign-in throttle
    token per call whatever the tables hold, so a 401 or a 429 says nothing
    about which usernames exist where. Returns `(kind, row)` for the caller to
    set its cookie, or the 2FA step. 401 on a wrong password; 403
    `ACCOUNT_DEACTIVATED` for a switched-off employee login or one no Agency
    has, told only after the right password. A right password gives the token
    back unless it signs in (a challenge or a deactivated refusal)."""
    attempt = login_throttle.take(request, username)
    async with get_session() as s:
        for kind in kinds:
            model = MODELS[kind]
            row = (await s.execute(select(model).where(model.username == username))).scalar_one_or_none()
            if row is not None and row.password == password:
                break
        else:
            raise HTTPException(status_code=401, detail=INVALID_LOGIN)
        if kind == "chatter":
            linked = (await s.execute(
                select(ChatterUser.user_id).where(ChatterUser.chatter_id == row.id).limit(1)
            )).first()
            if not row.is_active or linked is None:
                attempt.refund()
                raise HTTPException(status_code=403, detail=ACCOUNT_DEACTIVATED)
        challenge = await challenge_for(s, kind, row)
        if challenge is not None:
            attempt.refund()
            return challenge
        # Bump last_seen_at so the inactivity window restarts.
        await s.execute(update(model).where(model.id == row.id).values(last_seen_at=datetime.utcnow()))
    attempt.succeeded()
    return kind, row


# ── Links and revokes ─────────────────────────────────────────────────

async def revoke_sessions(s, kind: Kind, principal_id: str) -> None:
    """Sign every session of this principal out (its cookies issued before
    now), and once `s` commits end its open event streams: a stream makes no
    further request to be refused, its reconnect does (events.sse_stream)."""
    model = MODELS[kind]
    await s.execute(update(model).where(model.id == principal_id).values(
        sessions_valid_after=datetime.utcnow()))
    events.on_commit(s, "sessions_revoked", agency=events.sessions_audience(kind, principal_id))


async def link_login(s, chatter: Chatter, owner_id: str) -> bool:
    """Link an employee login to an Agency; False when it already was. A login
    without 2FA joining an Agency that requires it is signed out everywhere, so
    its next sign-in sets 2FA up before it reaches this Agency."""
    result = await s.execute(
        sqlite_insert(ChatterUser)
        .values(chatter_id=chatter.id, user_id=owner_id, created_at=datetime.utcnow())
        .on_conflict_do_nothing(index_elements=["chatter_id", "user_id"])
    )
    if (result.rowcount or 0) != 1:
        return False
    events.on_commit(s, "assignment_changed", agency=owner_id)
    if not chatter.totp_secret and await owner_requires_2fa(s, owner_id):
        await revoke_sessions(s, "chatter", chatter.id)
    return True


async def revoke_if_unlinked(s, chatter_id: str) -> None:
    """A login left with no Agency is deactivated: sign it out everywhere."""
    linked = (await s.execute(
        select(ChatterUser.user_id).where(ChatterUser.chatter_id == chatter_id).limit(1)
    )).first()
    if linked is None:
        await revoke_sessions(s, "chatter", chatter_id)


async def revoke_unenrolled_employees(s, owner_user_id: str) -> None:
    """The Agency just started requiring 2FA: its employees without 2FA are
    signed out, so their next sign-in sets it up."""
    unenrolled = (await s.execute(select(Chatter.id).where(
        Chatter.id.in_(select(ChatterUser.chatter_id).where(ChatterUser.user_id == owner_user_id)),
        Chatter.totp_secret.is_(None),
    ))).scalars().all()
    for chatter_id in unenrolled:
        await revoke_sessions(s, "chatter", chatter_id)


def clear_two_factor_values() -> dict[str, Any]:
    return {"totp_secret": None, "totp_enabled_at": None, "totp_recovery": None, "totp_last_step": None}
