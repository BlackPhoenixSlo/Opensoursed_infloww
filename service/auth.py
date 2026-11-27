from __future__ import annotations

import hmac
import logging
import os

import secrets_store
from dotenv import dotenv_values
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("of-relay.auth")

from fastapi import APIRouter, Body, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

import cell_mode
import events
import login_throttle
import owner_tokens
import token_auth
from account_security import TwoFactorChallenge, password_sign_in
from agency_scope import agency_account_ids
from db.engine import get_session
import session_stamps
import signed_cookie
import split_inbox
from session_stamps import now_ms, session_verdict
from db.models import (
    User,
    UserAccount,
)



COOKIE_NAME = "chatterly_session"
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 3600
SESSION_INACTIVITY_SECONDS = 30 * 24 * 3600
LAST_SEEN_TOUCH_S = 300

# Short-lived so a forgotten "view as" session can't persist; 1h is plenty for a support call.
IMPERSONATE_COOKIE_NAME = "chatterly_impersonate"
IMPERSONATE_TTL_SECONDS = 60 * 60

_ACTOR = None
if os.environ.get("OI_CELL_MAP"):
    import actor_token as _ACTOR

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
RESERVED_USERNAMES = frozenset({"admin", "root", "system", "chatterly", "founder"})


_request_user: ContextVar["AuthedUser | None"] = ContextVar(
    "chatterly_request_user", default=None
)


class AuthedUser:

    __slots__ = ("id", "username", "account_ids", "is_admin")

    def __init__(
        self, id_: str, username: str, account_ids: frozenset[str],
        is_admin: bool = False,
    ):
        self.id = id_
        self.username = username
        self.account_ids = cell_mode.clamp(account_ids)
        self.is_admin = is_admin


_request_token: ContextVar["tuple[int, str] | None"] = ContextVar(
    "chatterly_request_token", default=None
)


def get_request_token() -> "tuple[int, str] | None":
    return _request_token.get()


def request_via() -> str | None:
    tok = _request_token.get()
    return f"token {tok[1]}" if tok else None


def get_request_user() -> AuthedUser | None:
    return _request_user.get()


def require_user(*, detail: str) -> AuthedUser:
    user = _request_user.get()
    if user is None:
        raise HTTPException(status_code=401, detail=detail)
    return user



class Impersonation:
    __slots__ = ("real_user_id", "real_username",
                 "impersonated_user_id", "impersonated_username")

    def __init__(
        self,
        real_user_id: str, real_username: str,
        impersonated_user_id: str, impersonated_username: str,
    ):
        self.real_user_id = real_user_id
        self.real_username = real_username
        self.impersonated_user_id = impersonated_user_id
        self.impersonated_username = impersonated_username


_impersonation: ContextVar["Impersonation | None"] = ContextVar(
    "chatterly_impersonation", default=None,
)


def get_impersonation() -> "Impersonation | None":
    return _impersonation.get()


def _actor_account_ids() -> frozenset[str] | None:
    user = _request_user.get()
    if user is not None:
        return user.account_ids
    try:
        from chatters import get_request_chatter
    except ImportError:
        return None
    chatter = get_request_chatter()
    if chatter is not None:
        return chatter.account_ids
    return None


async def assert_employee_filter_owned(employee_id: int | None) -> None:
    if employee_id is None:
        return
    from db.engine import get_session
    from db.models import Employee
    async with get_session() as s:
        row = await s.get(Employee, employee_id)
    if row is None:
        raise HTTPException(status_code=403, detail="not your employee")
    user = _request_user.get()
    if user is not None:
        if user.is_admin:
            return
        if row.user_id != user.id:
            raise HTTPException(status_code=403, detail="not your employee")
        return
    try:
        from chatters import get_request_chatter
    except ImportError:
        return
    chatter = get_request_chatter()
    if chatter is not None:
        if row.user_id in chatter.owner_user_ids:
            return
        if row.chatter_id == chatter.id:
            return
        raise HTTPException(status_code=403, detail="not your employee")


def allow_anonymous_account_access() -> bool:
    # Escape hatch: a lockout from the fail-closed gate is a one-line revert plus restart, never a redeploy.
    return os.environ.get("ALLOW_ANONYMOUS_ADMIN", "0").strip().lower() \
        in ("1", "true", "yes", "on")


def require_actor_account_ids() -> frozenset[str] | None:
    ids = _actor_account_ids()
    if ids is None and not allow_anonymous_account_access():
        raise HTTPException(status_code=401, detail="sign in required")
    return ids


def assert_account_owned(account_id: str | None) -> None:
    # Fail closed: abstaining for anonymous callers once let unauthenticated requests through every account gate.
    if not account_id:
        return
    ids = require_actor_account_ids()
    if ids is None:
        return
    if account_id not in ids:
        raise HTTPException(status_code=403, detail="not your account")


def clamp_account_filter(account_id: str | None) -> list[str] | None:
    ids = _actor_account_ids()
    if account_id:
        if ids is not None and account_id not in ids:
            raise HTTPException(status_code=403, detail="not your account")
        return [account_id]
    ids = cell_mode.read_scope(ids)
    if ids is None:
        return None
    return list(ids)


def split_account_ids(*raw: str | None) -> list[str]:
    return list(dict.fromkeys(a.strip() for one in raw for a in (one or "").split(",") if a.strip()))



def _make_cookie(user_id: str) -> str:
    return signed_cookie.make(session_stamps.SESSION_SECRET, user_id, str(now_ms()))


def _parse_cookie(value: str) -> str | None:
    parsed = parse_cookie_issued(value)
    return parsed[0] if parsed else None


def parse_cookie_issued(value: str) -> tuple[str, int] | None:
    """`(user_id, issued_ms)` if the cookie's HMAC verifies, else None."""
    return signed_cookie.parse_issued(session_stamps.SESSION_SECRET, value)


def _make_impersonate_cookie(impersonated_user_id: str, founder_user_id: str) -> str:
    # Bound to the founder id: a leaked impersonate cookie alone is useless.
    issued = str(int(datetime.utcnow().timestamp()))
    return signed_cookie.make(
        session_stamps.SESSION_SECRET, impersonated_user_id, founder_user_id, issued,
    )


def _parse_impersonate_cookie(value: str) -> tuple[str, str, int] | None:
    fields = signed_cookie.parse(session_stamps.SESSION_SECRET, value, 3)
    if fields is None:
        return None
    imp, founder, issued = fields
    try:
        issued_int = int(issued)
    except ValueError:
        return None
    return imp, founder, issued_int



def _normalize_username(raw: str) -> str:
    return (raw or "").strip().lower()


def _validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="username must be 3-32 chars, lowercase a-z 0-9 . _ -",
        )
    if username in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail=f"username {username!r} is reserved")


def _validate_password(password: str) -> None:
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="password must be at least 6 chars")
    if len(password) > 256:
        raise HTTPException(status_code=400, detail="password too long")


def cookie_secure() -> bool:
    return os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _make_cookie(user_id),
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
    )
    if _ACTOR is not None:
        _ACTOR.clear(response)


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, samesite="lax")


def _set_impersonate_cookie(
    response: Response, impersonated_user_id: str, founder_user_id: str,
) -> None:
    response.set_cookie(
        IMPERSONATE_COOKIE_NAME,
        _make_impersonate_cookie(impersonated_user_id, founder_user_id),
        max_age=IMPERSONATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
    )
    if _ACTOR is not None:
        _ACTOR.clear(response)


def _clear_impersonate_cookie(response: Response) -> None:
    response.delete_cookie(IMPERSONATE_COOKIE_NAME, samesite="lax")
    if _ACTOR is not None:
        _ACTOR.clear(response)


def clear_all_principal_cookies(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, samesite="lax")
    response.delete_cookie(IMPERSONATE_COOKIE_NAME, samesite="lax")
    if _ACTOR is not None:
        _ACTOR.clear(response)
    try:
        from chatters import COOKIE_NAME as _CHATTER_COOKIE_NAME
        response.delete_cookie(_CHATTER_COOKIE_NAME, samesite="lax")
    except ImportError:
        pass



router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class ImpersonatingResp(BaseModel):
    real_user_id: str
    real_username: str


class AuthResp(BaseModel):
    user_id: str
    username: str
    impersonating: ImpersonatingResp | None = None
    is_admin: bool = False
    # When this user registered (UTC). The UI counts the 7-day free trial
    # from it. While impersonating, the impersonated user's.
    created_at: datetime | None = None


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


@router.post("/register", response_model=AuthResp)
async def register(request: Request, response: Response, body: RegisterBody = Body(...)) -> AuthResp:
    username = _normalize_username(body.username)
    _validate_username(username)
    _validate_password(body.password)
    login_throttle.take_register(request)

    new_id = uuid.uuid4().hex
    async with get_session() as s:
        s.add(User(
            id=new_id,
            username=username,
            # plaintext per owner decision
            password=body.password,
        ))
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="username already taken")
    if cell_mode.is_control():
        from employees import seed_agency_rows
        try:
            await seed_agency_rows(new_id, username)
        except Exception:
            log.exception("Cells: owner %s has no Mirror Employee or role presets until the next start", new_id)

    _set_session_cookie(response, new_id)
    return AuthResp(user_id=new_id, username=username, created_at=_utc(datetime.utcnow()))


@router.post("/login", response_model=AuthResp | TwoFactorChallenge)
async def login(
    request: Request, response: Response, body: LoginBody = Body(...),
) -> AuthResp | TwoFactorChallenge:
    """Owner sign-in, for scripts; the sign-in form uses `POST /auth/sign-in`
    (account_security_api), which also signs employees in. 401 wrong password,
    429 past the sign-in throttle. With 2FA on the answer is a
    `TwoFactorChallenge` and no cookie: the code goes to `POST /auth/2fa/login`."""
    username = _normalize_username(body.username)
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    result = await password_sign_in(request, username, body.password, ("user",))
    if isinstance(result, TwoFactorChallenge):
        return result
    _, row = result
    _set_session_cookie(response, row.id)
    return AuthResp(user_id=row.id, username=row.username, is_admin=bool(row.is_admin),
                    created_at=_utc(row.created_at))


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    import push_api
    await push_api.forget_cookies(request)
    clear_all_principal_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=AuthResp | None)
async def me() -> AuthResp | None:
    """Who is signed in on this request (or None). Used by the Next app
    shell to decide between rendering the app or redirecting to /login.

    When impersonating, `user_id`/`username` reflect the IMPERSONATED user
    (matches the rest of the app's view) and `impersonating` carries the
    founder's real identity for the banner."""
    u = get_request_user()
    if u is None:
        return None
    imp = get_impersonation()
    async with get_session() as s:
        created = (await s.execute(
            select(User.created_at).where(User.id == u.id)
        )).scalar_one_or_none()
    return AuthResp(
        user_id=u.id,
        username=u.username,
        is_admin=bool(u.is_admin),
        created_at=_utc(created) if created is not None else None,
        impersonating=ImpersonatingResp(
            real_user_id=imp.real_user_id,
            real_username=imp.real_username,
        ) if imp is not None else None,
    )



async def _master_account_ids(s) -> frozenset[str]:
    # Union registry + user_accounts: each holds accounts the other lacks; registry alone made master weaker than an owner.
    # account_ids(), not list_accounts(): the listing reads a meta.json per account on every master request.
    import accounts as _registry
    rows = (await s.execute(select(UserAccount.account_id).distinct())).all()
    return _registry.account_ids() | frozenset(str(r[0]) for r in rows)


async def account_ids_for(s, user_id: str, is_admin: bool) -> frozenset[str]:
    if is_admin:
        return await _master_account_ids(s)
    return frozenset(await agency_account_ids(s, user_id))


async def _touch_last_seen(user_id: str, now: datetime) -> None:
    # Own session and swallowed: a failed cosmetic stamp must never fail the request (a lock timeout once 500'd real API calls).
    try:
        async with get_session() as s:
            await s.execute(update(User).where(User.id == user_id).values(last_seen_at=now))
    except Exception:
        log.debug("last_seen_at bump skipped (non-fatal)", exc_info=True)


from typing import NamedTuple  # noqa: E402  (used by this region only)


class _CookieClears(NamedTuple):
    session: bool = False
    impersonate: bool = False


async def _resolve_session(request: Request) -> _CookieClears:
    cookie = request.cookies.get(COOKIE_NAME)
    parsed = parse_cookie_issued(cookie) if cookie else None
    if not parsed:
        return _CookieClears()
    user_id, issued = parsed
    async with get_session() as s:
        row = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if row is None:
            return _CookieClears()
        now = datetime.utcnow()
        verdict = session_verdict(
            issued, row.sessions_valid_after, row.last_seen_at, now,
            max_idle_s=SESSION_INACTIVITY_SECONDS, touch_s=LAST_SEEN_TOUCH_S,
        )
        if verdict == "expired":
            return _CookieClears(session=True)
        is_admin = bool(getattr(row, "is_admin", False))
        account_ids = await account_ids_for(s, user_id, is_admin)
        if verdict == "touch":
            await _touch_last_seen(user_id, now)
        _request_user.set(AuthedUser(row.id, row.username, account_ids, is_admin))
        imp_cookie = request.cookies.get(IMPERSONATE_COOKIE_NAME)
        return _CookieClears(impersonate=await _apply_impersonation(imp_cookie, s, row, now))


async def _apply_impersonation(imp_cookie: str | None, s, row: User, now: datetime) -> bool:
    if not imp_cookie:
        return False
    parsed = _parse_impersonate_cookie(imp_cookie)
    verdict = session_stamps.impersonation_verdict(
        parsed, now, row.id, ttl=IMPERSONATE_TTL_SECONDS,
    )
    if verdict == "clear" or parsed is None:
        return True
    imp_uid = parsed[0]
    imp_row = (await s.execute(select(User).where(User.id == imp_uid))).scalar_one_or_none()
    if imp_row is None:
        return True
    imp_is_admin = bool(getattr(imp_row, "is_admin", False))
    imp_account_ids = await account_ids_for(s, imp_uid, imp_is_admin)
    _request_user.set(AuthedUser(imp_row.id, imp_row.username, imp_account_ids, imp_is_admin))
    _impersonation.set(Impersonation(
        real_user_id=row.id,
        real_username=row.username,
        impersonated_user_id=imp_row.id,
        impersonated_username=imp_row.username,
    ))
    return False


async def apply_actor(s, claims) -> bool:
    rows = {r.id: r for r in (await s.execute(select(User).where(User.id.in_({claims.id, claims.eff_id})))).scalars()}
    real, eff = rows.get(claims.id), rows.get(claims.eff_id)
    if real is None or eff is None or session_stamps.session_revoked(claims.iat * 1000, real.sessions_valid_after):
        return False
    import agency_copy
    if await agency_copy.owner_missing(s, {real.id, eff.id}):
        return False
    is_admin = bool(getattr(eff, "is_admin", False))
    _request_user.set(AuthedUser(eff.id, eff.username, await account_ids_for(s, eff.id, is_admin), is_admin))
    if claims.ro:
        _impersonation.set(Impersonation(real.id, real.username, eff.id, eff.username))
    return True


def impersonation_expires(request: Request) -> int | None:
    parsed = _parse_impersonate_cookie(request.cookies.get(IMPERSONATE_COOKIE_NAME) or "")
    if not parsed:
        return None
    # The cookie's clock is naive utcnow().timestamp(); carry only the time left onto the epoch clock.
    left = parsed[2] + IMPERSONATE_TTL_SECONDS - int(datetime.utcnow().timestamp())
    return int(datetime.now(timezone.utc).timestamp()) + left


async def _token_request(request: Request, call_next, token: str):
    if any(h.decode() in request.headers for h in token_auth.STRIPPED):
        raise RuntimeError("bearer request still carries a cookie: token_auth.StripCookieIdentities missing")
    owner = await token_auth.resolve(token)
    if owner is None:
        return Response(
            "invalid, expired or revoked access token", status_code=401,
            headers={"Cache-Control": "no-store",
                     "WWW-Authenticate": token_auth.challenge(request.headers, request.url.scheme)},
        )
    template, params = token_auth.matched(request.scope, request.app.routes)
    if not token_auth.allowed(request.method, template):
        return JSONResponse({"detail": token_auth.REFUSED}, status_code=403,
                            headers={"Cache-Control": "no-store"})
    if why := await token_auth.write_refusal(request, template, params):
        return JSONResponse({"detail": f"{token_auth.WRITE_REFUSED}: {why}"}, status_code=403,
                            headers={"Cache-Control": "no-store"})
    _request_user.set(AuthedUser(owner.user_id, owner.username, owner.account_ids, is_admin=False))
    _request_token.set((owner.token_id, owner.token_name))
    return await call_next(request)


async def session_middleware(request: Request, call_next):
    _request_user.set(None)
    _impersonation.set(None)
    _request_token.set(None)
    if _ACTOR is not None and (aged := _ACTOR.aged_refusal(request)):
        return aged
    token = owner_tokens.bearer(request.headers.get("authorization"))
    if token is not None:
        return await _token_request(request, call_next, token)
    clears = _CookieClears() if _ACTOR is not None and _ACTOR.DATA else await _resolve_session(request)
    if _ACTOR is not None and _request_user.get() is None and (refused := await _ACTOR.resolve(request)):
        return refused

    if session_stamps.blocks_write(
        request.method, request.url.path, _impersonation.get() is not None,
    ):
        return Response(
            "read-only while impersonating — exit impersonation to mutate",
            status_code=403,
        )

    response = await call_next(request)
    if clears.session:
        _clear_session_cookie(response)
    if clears.impersonate:
        _clear_impersonate_cookie(response)
    return response



admin_router = APIRouter(prefix="/admin/users", tags=["admin-users"])

ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"
_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _read_admin_password() -> str:
    env = (os.environ.get(ADMIN_PASSWORD_ENV) or "").strip()
    if not env:
        # service/.env directly, not just os.environ, for a NATIVE run
        # (scripts/start.sh), where the process reads that file and this must
        # not depend on which other module happened to call load_dotenv first.
        #
        # In the CONTAINER this file does not exist — the Dockerfile COPY is a
        # .py allow-list and nothing mounts it — so the container path is the
        # `environment:` entry in docker-compose.yml, fed from the compose-level
        # the compose-level .env. Both are covered here, which is the point: getting it
        # wrong reads as an empty password, i.e. a 503 on all five founder
        # writes that looks like a relay fault rather than a config gap.
        env = (dotenv_values(_ENV_FILE).get(ADMIN_PASSWORD_ENV) or "").strip()
    return env or secrets_store.stored(ADMIN_PASSWORD_ENV)


class AdminUserRow(BaseModel):
    id: str
    username: str
    created_at: datetime
    last_seen_at: datetime
    account_count: int


@admin_router.get("", response_model=list[AdminUserRow])
async def admin_list_users() -> list[AdminUserRow]:
    """Every user on the deployment (every Agency's username and model count):
    a roster of other tenants, so master-only like llm-key-status beside it."""
    require_master()
    async with get_session() as s:
        rows = (await s.execute(
            select(
                User.id, User.username, User.created_at, User.last_seen_at,
                func.count(UserAccount.account_id).label("account_count"),
            )
            .join(UserAccount, UserAccount.user_id == User.id, isouter=True)
            .group_by(User.id)
            .order_by(User.created_at.desc())
        )).all()
    return [
        AdminUserRow(
            id=r.id, username=r.username,
            created_at=r.created_at, last_seen_at=r.last_seen_at,
            account_count=r.account_count or 0,
        )
        for r in rows
    ]


class DeleteUserBody(BaseModel):
    confirm: str = Field(..., description="must equal the literal string 'delete'")
    admin_password: str = Field(..., min_length=1, max_length=512)


def require_master() -> AuthedUser:
    user = get_request_user()
    if user is None:
        raise HTTPException(
            status_code=401, detail="sign in as the master account")
    if not user.is_admin:
        raise HTTPException(
            status_code=403, detail="master account required")
    return user


def _assert_admin_password(supplied: str) -> None:
    if _request_token.get() is not None:
        raise HTTPException(status_code=403, detail="not allowed with an access token")
    expected = _read_admin_password()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{ADMIN_PASSWORD_ENV} is not configured on this relay — set it "
                f"in the relay's environment (the compose-level .env, beside "
                f"docker-compose.yml) and restart, or once from Setup → Server keys"
            ),
        )
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="wrong admin password")


@admin_router.delete("/{user_id}")
async def admin_delete_user(user_id: str, body: DeleteUserBody = Body(...)) -> dict:
    if body.confirm != "delete":
        raise HTTPException(status_code=400, detail="confirm must equal 'delete'")
    _assert_admin_password(body.admin_password)
    import leak_tracker
    await leak_tracker.before_user_delete(user_id)
    async with get_session() as s:
        row = (await s.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown user {user_id!r}")
        events.on_commit(s, "assignment_changed", agency=user_id)
        await s.execute(delete(User).where(User.id == user_id))
    return {"ok": True, "deleted_user_id": user_id}



class GrantAccountBody(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    admin_password: str = Field(..., min_length=1, max_length=512)


class RevokeAccountBody(BaseModel):
    admin_password: str = Field(..., min_length=1, max_length=512)


class GrantedAccount(BaseModel):
    account_id: str
    nickname: str | None = None
    color: str | None = None


class GrantOverview(BaseModel):
    granted: list[GrantedAccount]
    available: list[GrantedAccount]


@admin_router.get("/{user_id}/accounts", response_model=GrantOverview)
async def admin_list_user_accounts(user_id: str) -> GrantOverview:
    """Founder UI populates its grant picker from this. `granted` is the
    friend's current set; `available` is every other OF account on the
    relay (so the founder can click one to grant). Master-only, as the
    /admin/users list: it names every OF account on the relay. The POST/DELETE
    mutators carry the admin_password gate on top."""
    require_master()
    from accounts import list_accounts

    async with get_session() as s:
        u = (await s.execute(
            select(User.id).where(User.id == user_id)
        )).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail=f"unknown user {user_id!r}")
        granted_ids = await agency_account_ids(s, user_id)

    all_accounts = list_accounts()
    granted: list[GrantedAccount] = []
    available: list[GrantedAccount] = []
    for a in all_accounts:
        aid = str(a.get("id") or "")
        if not aid:
            continue
        item = GrantedAccount(
            account_id=aid,
            nickname=a.get("nickname"),
            color=a.get("color"),
        )
        (granted if aid in granted_ids else available).append(item)
    granted.sort(key=lambda x: (x.nickname or x.account_id).lower())
    available.sort(key=lambda x: (x.nickname or x.account_id).lower())
    return GrantOverview(granted=granted, available=available)


@admin_router.post("/{user_id}/accounts")
async def admin_grant_user_account(
    user_id: str, body: GrantAccountBody = Body(...),
) -> dict:
    _assert_admin_password(body.admin_password)
    from accounts import get_account as _get_account
    if _get_account(body.account_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown account {body.account_id!r}")
    async with get_session() as s:
        u = (await s.execute(
            select(User.id).where(User.id == user_id)
        )).scalar_one_or_none()
        if u is None:
            raise HTTPException(status_code=404, detail=f"unknown user {user_id!r}")
        try:
            s.add(UserAccount(user_id=user_id, account_id=body.account_id))
            await s.flush()
            events.on_commit(s, "assignment_changed", agency=user_id)
        except IntegrityError:
            await s.rollback()
    await split_inbox.owner_link_changed(body.account_id)
    return {"ok": True, "user_id": user_id, "account_id": body.account_id}


@admin_router.delete("/{user_id}/accounts/{account_id}")
async def admin_revoke_user_account(
    user_id: str, account_id: str, body: RevokeAccountBody = Body(...),
) -> dict:
    _assert_admin_password(body.admin_password)
    import leak_tracker  # lazy: both import this module
    import notifications_api
    await leak_tracker.drop_watches(account_id=account_id, agency_user_id=user_id)
    # Both drops run before the link goes; each is safe to retry after a 500.
    await notifications_api.drop_pinned(account_id, [user_id])
    async with get_session() as s:
        result = await s.execute(
            delete(UserAccount).where(
                UserAccount.user_id == user_id,
                UserAccount.account_id == account_id,
            )
        )
        if (result.rowcount or 0) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"user {user_id!r} does not hold account {account_id!r}",
            )
        events.on_commit(s, "assignment_changed", agency=user_id)
    await split_inbox.owner_link_changed(account_id)
    return {"ok": True, "user_id": user_id, "account_id": account_id}



impersonate_router = APIRouter(prefix="/admin/impersonate", tags=["admin-impersonate"])


class ImpersonateStartBody(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    admin_password: str = Field(..., min_length=1, max_length=512)


@impersonate_router.post("")
async def admin_start_impersonate(
    response: Response, body: ImpersonateStartBody = Body(...),
) -> dict:
    _assert_admin_password(body.admin_password)
    me = _request_user.get()
    if me is None:
        raise HTTPException(
            status_code=401, detail="sign in as the founder before impersonating",
        )
    if body.user_id == me.id:
        raise HTTPException(status_code=400, detail="cannot impersonate yourself")
    async with get_session() as s:
        target = (await s.execute(
            select(User).where(User.id == body.user_id)
        )).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail=f"unknown user {body.user_id!r}")
        target_username = target.username
    _set_impersonate_cookie(response, body.user_id, me.id)
    log.warning(
        "impersonate START: founder=%s (id=%s) -> user=%s (id=%s)",
        me.username, me.id, target_username, body.user_id,
    )
    return {
        "ok": True,
        "impersonating": {"user_id": body.user_id, "username": target_username},
        "ttl_seconds": IMPERSONATE_TTL_SECONDS,
    }


@impersonate_router.delete("")
async def admin_stop_impersonate(response: Response) -> dict:
    imp = _impersonation.get()
    if imp is not None:
        log.warning(
            "impersonate STOP: founder=%s (id=%s) -> user=%s (id=%s)",
            imp.real_username, imp.real_user_id,
            imp.impersonated_username, imp.impersonated_user_id,
        )
    _clear_impersonate_cookie(response)
    return {"ok": True}
