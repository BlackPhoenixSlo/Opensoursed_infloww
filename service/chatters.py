from __future__ import annotations

import json
import logging
import secrets
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger("of-relay.chatters")

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

import account_health
import accounts as account_registry
import cell_mode
import chatter_identity_cache as identity_cache
import events
import platforms
import shared_refresher
from account_security import (
    TwoFactorChallenge,
    challenge_for,
    link_login,
    password_sign_in,
)
from db.engine import get_session
from db.models import (
    Account,
    Chatter,
    ChatterAccountAccess,
    ChatterFolderAccess,
    ChatterInvite,
    ChatterUser,
    User,
    UserAccount,
)
from auth import (
    USERNAME_RE,
    RESERVED_USERNAMES,
    cookie_secure,
    _normalize_username,
    _validate_password,
)
import signed_cookie
from session_secret import load_secret
from session_stamps import now_ms, session_verdict



COOKIE_NAME = "chatterly_chatter_session"
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 3600
SESSION_INACTIVITY_SECONDS = 30 * 24 * 3600
INVITE_TTL_SECONDS = 24 * 3600

# Distinct from the User session secret: cross-principal forgery must need both files.
_SECRET_FILE = Path(__file__).resolve().parent / ".chatter_secret"


_SESSION_SECRET = load_secret("CHATTER_SESSION_SECRET", _SECRET_FILE)



class ChatterIdentity:

    __slots__ = ("id", "username", "display_name", "color",
                 "owner_user_ids", "account_ids")

    def __init__(
        self,
        id_: str,
        username: str,
        display_name: str | None,
        color: str | None,
        owner_user_ids: frozenset[str],
        account_ids: frozenset[str],
    ):
        self.id = id_
        self.username = username
        self.display_name = display_name
        self.color = color
        self.owner_user_ids = owner_user_ids
        self.account_ids = cell_mode.clamp(account_ids)


_request_chatter: ContextVar["ChatterIdentity | None"] = ContextVar(
    "chatterly_request_chatter", default=None,
)


def get_request_chatter() -> "ChatterIdentity | None":
    return _request_chatter.get()



def _sign(payload: str) -> str:
    return signed_cookie.sign(_SESSION_SECRET, payload)


def _make_cookie(chatter_id: str) -> str:
    return signed_cookie.make(_SESSION_SECRET, chatter_id, str(now_ms()))


def _parse_cookie(value: str) -> str | None:
    parsed = parse_cookie_issued(value)
    return parsed[0] if parsed else None


def parse_cookie_issued(value: str) -> tuple[str, int] | None:
    return signed_cookie.parse_issued(_SESSION_SECRET, value)


def _set_session_cookie(response: Response, chatter_id: str) -> None:
    from auth import _ACTOR
    response.set_cookie(
        COOKIE_NAME,
        _make_cookie(chatter_id),
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
    )
    if _ACTOR is not None:
        _ACTOR.clear(response)


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, samesite="lax")



def _validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="username must be 3-32 chars, lowercase a-z 0-9 . _ -",
        )
    if username in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail=f"username {username!r} is reserved")


async def _account_restrictions_for(s, chatter_id: str) -> dict[str, frozenset[str]]:
    rows = (await s.execute(
        select(
            ChatterAccountAccess.user_id,
            ChatterAccountAccess.account_id,
        ).where(ChatterAccountAccess.chatter_id == chatter_id)
    )).all()
    out: dict[str, set[str]] = {}
    for uid, aid in rows:
        out.setdefault(uid, set()).add(aid)
    return {uid: frozenset(aids) for uid, aids in out.items()}


def _filter_owner_accounts(
    pairs: "list[tuple[str, str]]",
    restrictions: dict[str, frozenset[str]],
) -> set[str]:
    allowed: set[str] = set()
    for uid, aid in pairs:
        if _allowed(restrictions, uid, aid):
            allowed.add(aid)
    return allowed


async def allowed_folder_ids_for_chatter(account_id: str) -> "frozenset[int] | None":
    actor = current_actor()
    if actor is None or actor.kind != "chatter":
        return None
    async with get_session() as s:
        rows = (await s.execute(
            select(ChatterFolderAccess.folder_id).where(
                ChatterFolderAccess.chatter_id == actor.id,
                ChatterFolderAccess.account_id == account_id,
            )
        )).all()
    if not rows:
        return None
    return frozenset(r[0] for r in rows)


async def load_identity(chatter_id: str) -> "identity_cache.CachedIdentity | None":
    async with get_session() as s:
        row = (await s.execute(
            select(Chatter).where(Chatter.id == chatter_id)
        )).scalar_one_or_none()
        if row is None or not row.is_active:
            return None

        owner_rows = (await s.execute(
            select(ChatterUser.user_id).where(ChatterUser.chatter_id == chatter_id)
        )).all()
        owner_ids = {r[0] for r in owner_rows}

        if owner_ids:
            acct_rows = (await s.execute(
                select(
                    UserAccount.user_id,
                    UserAccount.account_id,
                ).where(UserAccount.user_id.in_(list(owner_ids)))
            )).all()
            restrictions = await _account_restrictions_for(s, chatter_id)
            account_ids: set[str] = _filter_owner_accounts(
                [(uid, aid) for uid, aid in acct_rows], restrictions
            )
        else:
            account_ids = set()

        identity = ChatterIdentity(
            id_=row.id,
            username=row.username,
            display_name=row.display_name,
            color=row.color,
            owner_user_ids=frozenset(owner_ids),
            account_ids=frozenset(account_ids),
        )
        return identity_cache.CachedIdentity(identity, row.sessions_valid_after, row.last_seen_at)


LAST_SEEN_TOUCH_S = 300


async def _session_identity(chatter_id: str, issued: int) -> tuple[ChatterIdentity | None, bool]:
    entry = identity_cache.get(chatter_id)
    if entry is None:
        gen = identity_cache.generation()
        entry = await load_identity(chatter_id)
        if entry is None:
            return None, False
        identity_cache.store(chatter_id, entry, gen)
    now = datetime.utcnow()
    verdict = session_verdict(issued, entry.sessions_valid_after, entry.last_seen_at, now,
                              max_idle_s=SESSION_INACTIVITY_SECONDS, touch_s=LAST_SEEN_TOUCH_S)
    if verdict == "expired":
        return None, True
    if verdict == "touch":
        async with get_session() as s:
            res = await s.execute(update(Chatter).where(
                Chatter.id == chatter_id,
                Chatter.last_seen_at < now - timedelta(seconds=LAST_SEEN_TOUCH_S),
            ).values(last_seen_at=now))
        if res.rowcount:
            entry.last_seen_at = now
        else:
            # A sign-in or concurrent request bumped last_seen_at since the read: next request re-reads the row.
            identity_cache.drop(chatter_id)
    return entry.identity, False



router = APIRouter(prefix="/chatter", tags=["chatter-auth"])


class _LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class _RegisterBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)
    display_name: str | None = Field(None, max_length=64)


class OwnerAccountDTO(BaseModel):
    account_id: str
    nickname: str | None = None
    color: str | None = None


class OwnerDTO(BaseModel):
    user_id: str
    username: str
    accounts: list[OwnerAccountDTO]


class FlatAccountDTO(BaseModel):
    account_id: str
    nickname: str | None = None
    color: str | None = None
    owner_id: str
    owner_username: str
    session_dead_at: str | None = None
    session_dead_reason: str | None = None
    is_active: bool = True
    role: Literal["watcher"] | None = None
    platform: str = "onlyfans"
    freshness: dict[str, Any] | None = Field(default=None, exclude_if=lambda v: v is None)


class ChatterMeResp(BaseModel):
    chatter_id: str
    username: str
    display_name: str | None = None
    color: str | None = None
    owners: list[OwnerDTO]
    created_at: datetime | None = None


class InvitePreviewResp(BaseModel):
    """Pre-register peek at an invite token. The chatter-login UI fetches
    this to show 'invited by @alice — expires in N hours' so the new
    chatter knows what they're accepting before they create an account.

    Read-only: does NOT consume the invite. Only the actual POST
    /chatter/register call marks it used."""
    username: str = Field(..., description="username of the issuing owner")
    expires_at: datetime
    used: bool


@router.get("/invite/{token}", response_model=InvitePreviewResp)
async def invite_preview(token: str) -> InvitePreviewResp:
    """Return the issuing owner + status for an invite token. Surfaced on
    the /chatter-login form so the new chatter sees which owner is
    inviting them. 404 if the token doesn't exist (typo / forged URL);
    we DON'T 410 on used/expired here — the form needs to render an
    explanatory message rather than a blank rejection."""
    async with get_session() as s:
        row = (await s.execute(
            select(ChatterInvite, User.username)
            .join(User, User.id == ChatterInvite.user_id)
            .where(ChatterInvite.token == token)
        )).first()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown invite token")
        invite, username = row.ChatterInvite, row.username
    return InvitePreviewResp(
        username=username,
        expires_at=invite.expires_at,
        used=invite.used_at is not None or invite.expires_at < datetime.utcnow(),
    )


@router.post("/register", response_model=ChatterMeResp | TwoFactorChallenge)
async def register(
    response: Response,
    body: _RegisterBody = Body(...),
    token: str = Query(..., description="invite token from /admin/chatters/invite"),
) -> ChatterMeResp | TwoFactorChallenge:
    """Register a new chatter. Gated by an owner-issued invite token —
    we never accept random self-signups. On success the issuing owner is
    auto-linked so the chatter sees that owner's accounts on first login.

    The invite is consumed on success (used_at set, used_by_chatter_id
    stamped); subsequent attempts with the same token 410 Gone.

    When the issuing Agency requires 2FA the answer is a setup
    `TwoFactorChallenge` and no cookie: the new login sets 2FA up first.
    """
    username = _normalize_username(body.username)
    _validate_username(username)
    _validate_password(body.password)

    now = datetime.utcnow()
    new_id = uuid.uuid4().hex

    async with get_session() as s:
        invite = (await s.execute(
            select(ChatterInvite).where(ChatterInvite.token == token)
        )).scalar_one_or_none()
        if invite is None:
            raise HTTPException(status_code=404, detail="unknown invite token")
        if invite.used_at is not None:
            raise HTTPException(status_code=410, detail="invite already used")
        if invite.expires_at < now:
            raise HTTPException(status_code=410, detail="invite expired")
        owner_exists = (await s.execute(
            select(User.id).where(User.id == invite.user_id)
        )).scalar_one_or_none()
        if owner_exists is None:
            raise HTTPException(status_code=410, detail="issuing owner no longer exists")

        s.add(Chatter(
            id=new_id,
            username=username,
            password=body.password,
            display_name=(body.display_name or "").strip() or None,
            created_at=now,
            last_seen_at=now,
        ))
        try:
            await s.flush()
        except IntegrityError:
            raise HTTPException(status_code=409, detail="username already taken")

        s.add(ChatterUser(
            chatter_id=new_id, user_id=invite.user_id, created_at=now,
        ))
        invite.used_at = now
        invite.used_by_chatter_id = new_id
        await s.flush()
        owner_id, setup_json = invite.user_id, invite.setup_json

    try:
        from employees import setup_login_employee, validate_employee_setup
        setup = json.loads(setup_json) if setup_json else {}
        try:
            setup = await validate_employee_setup(owner_id, setup)
        except HTTPException:
            log.warning("invite setup no longer valid for chatter=%s; applying none", new_id)
            setup = {}
        await setup_login_employee(owner_id, new_id, setup)
    except Exception:
        log.exception("invite setup failed (chatter=%s)", new_id)

    async with get_session() as s:
        row = await s.get(Chatter, new_id)
        challenge = await challenge_for(s, "chatter", row)
    if challenge is not None:
        return challenge
    _set_session_cookie(response, new_id)
    entry = await load_identity(new_id)
    return await _me_response(entry.identity if entry else None)


@router.post("/login", response_model=ChatterMeResp | TwoFactorChallenge)
async def login(
    request: Request, response: Response, body: _LoginBody = Body(...),
) -> ChatterMeResp | TwoFactorChallenge:
    """Employee sign-in (account_security.password_sign_in); the sign-in form
    uses `POST /auth/sign-in`. 401 wrong password, 429 past the sign-in
    throttle, 403 `ACCOUNT_DEACTIVATED` for a switched-off login or one no
    Agency has, told only after the right password. With 2FA on, or required by
    an Agency, the answer is a `TwoFactorChallenge` and no cookie."""
    username = _normalize_username(body.username)
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    result = await password_sign_in(request, username, body.password, ("chatter",))
    if isinstance(result, TwoFactorChallenge):
        return result
    _, row = result
    _set_session_cookie(response, row.id)
    entry = await load_identity(row.id)
    return await _me_response(entry.identity if entry else None)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    import push_api
    # Before the cookies go: their sessions' push subs.
    await push_api.forget_cookies(request)
    from auth import clear_all_principal_cookies
    clear_all_principal_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=ChatterMeResp | None)
async def me() -> ChatterMeResp | None:
    """Who is signed in on this request (or None). Used by the Next app
    shell to choose between the chatter dashboard and a redirect to
    /chatter-login."""
    c = get_request_chatter()
    if c is None:
        return None
    return await _me_response(c)


@router.get("/me/accounts", response_model=list[FlatAccountDTO])
async def me_accounts() -> list[FlatAccountDTO]:
    """Flat list — every account the chatter can see, with owner_id and
    owner_username denormalised so the picker can render owner-group
    headers in O(owners + accounts) without a client-side join."""
    c = _require_chatter()
    return await _flat_accounts_for(c)


class FolderAccessDTO(BaseModel):
    folder_id: int
    folder_name: str | None = None


class FolderAccessResp(BaseModel):
    account_id: str
    restricted: bool
    folders: list[FolderAccessDTO]


@router.get("/me/folder-access", response_model=FolderAccessResp)
async def me_folder_access(account_id: str = Query(..., min_length=1)) -> FolderAccessResp:
    """The chatter's AUTHORITATIVE folder menu for one account (DA-3).

    `restricted=False` ⇒ no folder limits for this account; the picker
    shows OF's full folder list as usual. `restricted=True` ⇒ the chatter
    may ONLY see `folders` (names from the denormalised column, not from
    paginated vault/lists). Order is deterministic (folder_name, folder_id)
    so the picker's "first allowed folder" default is stable across loads.

    The chatter must be linked to an owner that granted this account — we
    don't leak grants for accounts outside the chatter's union."""
    c = _require_chatter()
    if account_id not in c.account_ids:
        raise HTTPException(
            status_code=403,
            detail="account not available to you",
        )
    async with get_session() as s:
        rows = (await s.execute(
            select(
                ChatterFolderAccess.folder_id,
                ChatterFolderAccess.folder_name,
            ).where(
                ChatterFolderAccess.chatter_id == c.id,
                ChatterFolderAccess.account_id == account_id,
            )
        )).all()
    folders = sorted(
        (FolderAccessDTO(folder_id=fid, folder_name=fname) for fid, fname in rows),
        key=lambda f: ((f.folder_name or "").lower(), f.folder_id),
    )
    return FolderAccessResp(
        account_id=account_id,
        restricted=bool(folders),
        folders=folders,
    )



def _require_chatter() -> "ChatterIdentity":
    c = get_request_chatter()
    if c is None:
        raise HTTPException(status_code=401, detail="chatter sign-in required")
    return c


async def _me_response(c: "ChatterIdentity | None") -> ChatterMeResp:
    if c is None:
        raise HTTPException(status_code=500, detail="chatter identity unavailable")
    owners = await _owners_for(c)
    async with get_session() as s:
        created = (await s.execute(
            select(Chatter.created_at).where(Chatter.id == c.id)
        )).scalar_one_or_none()
    return ChatterMeResp(
        chatter_id=c.id,
        username=c.username,
        display_name=c.display_name,
        color=c.color,
        owners=owners,
        created_at=created.replace(tzinfo=timezone.utc) if created is not None else None,
    )


def _allowed(restrictions: dict[str, frozenset[str]], user_id: str, account_id: str) -> bool:
    limit = restrictions.get(user_id)
    return limit is None or account_id in limit


async def _owners_for(c: "ChatterIdentity") -> list[OwnerDTO]:
    if not c.owner_user_ids:
        return []
    async with get_session() as s:
        user_rows = (await s.execute(
            select(User.id, User.username).where(
                User.id.in_(list(c.owner_user_ids))
            )
        )).all()
        usernames = {r.id: r.username for r in user_rows}

        acct_rows = (await s.execute(
            select(
                UserAccount.user_id,
                UserAccount.account_id,
                Account.nickname,
                Account.color,
            ).join(Account, Account.id == UserAccount.account_id, isouter=True)
            .where(UserAccount.user_id.in_(list(c.owner_user_ids)))
        )).all()
        restrictions = await _account_restrictions_for(s, c.id)

    grouped: dict[str, list[OwnerAccountDTO]] = {uid: [] for uid in c.owner_user_ids}
    for r in acct_rows:
        if not _allowed(restrictions, r.user_id, r.account_id):
            continue
        grouped[r.user_id].append(OwnerAccountDTO(
            account_id=r.account_id,
            nickname=r.nickname,
            color=r.color,
        ))
    out: list[OwnerDTO] = []
    for uid in sorted(c.owner_user_ids, key=lambda u: usernames.get(u, "").lower()):
        accs = sorted(grouped.get(uid, []), key=lambda a: (a.nickname or a.account_id).lower())
        out.append(OwnerDTO(
            user_id=uid, username=usernames.get(uid, uid), accounts=accs,
        ))
    return out


async def _flat_accounts_for(c: "ChatterIdentity") -> list[FlatAccountDTO]:
    if not c.owner_user_ids:
        return []
    async with get_session() as s:
        rows = (await s.execute(
            select(
                UserAccount.user_id,
                UserAccount.account_id,
                Account.nickname,
                Account.color,
                User.username,
            )
            .join(User, User.id == UserAccount.user_id)
            .join(Account, Account.id == UserAccount.account_id, isouter=True)
            .where(UserAccount.user_id.in_(list(c.owner_user_ids)))
        )).all()
        restrictions = await _account_restrictions_for(s, c.id)
    dead = await account_health.dead_session_map()
    off = await account_health.deactivated_ids()
    seen: dict[str, FlatAccountDTO] = {}
    for r in rows:
        if not _allowed(restrictions, r.user_id, r.account_id):
            continue
        existing = seen.get(r.account_id)
        if existing is None or (r.username or "").lower() < existing.owner_username.lower():
            health = dead.get(r.account_id, account_health.NO_DEAD_SESSION)
            role = account_registry.get_role(r.account_id)
            seen[r.account_id] = FlatAccountDTO(
                account_id=r.account_id,
                nickname=r.nickname,
                color=r.color,
                owner_id=r.user_id,
                owner_username=r.username or r.user_id,
                session_dead_at=health.at,
                session_dead_reason=health.reason,
                is_active=r.account_id not in off,
                role=role,
                platform=platforms.for_account(r.account_id).key,
                freshness=shared_refresher.snapshot(r.account_id) if shared_refresher.ENABLED and role is None
                else None,
            )
    import split_inbox
    await split_inbox.warm(seen)
    for a in seen.values():
        if a.freshness is not None and split_inbox.bound_cached(c.id, a.account_id):
            a.freshness = split_inbox.without_unread_total(a.freshness)
    return sorted(
        seen.values(),
        key=lambda a: (a.owner_username.lower(), (a.nickname or a.account_id).lower()),
    )



# Owner-only /admin/* prefixes; everything else falls through to its per-account ownership gate.
_CHATTER_BLOCKED_ADMIN_PREFIXES: tuple[str, ...] = (
    "/admin/users",
    "/admin/impersonate",
    "/admin/chatters",
    "/admin/proxies",
    "/admin/proxy-pool",
    "/admin/session",
    "/admin/login",
    "/admin/rev",
    "/admin/audit",
    "/admin/secrets",
    "/admin/system",
    "/admin/my-llm-keys",
    "/admin/owner-tokens",
    "/admin/ultra",
    "/admin/employees",
    "/admin/employee-groups",
    "/admin/link-shares",
    "/admin/agency-notifications",
    # Managing the list is owner-only; the bare GET /admin/sensitive-words stays open, every composer reads it.
    "/admin/sensitive-words/",
    "/admin/roster",
    "/admin/bio-pages",
    "/admin/full-ai/prepare-content",
)


def _chatter_allowed_admin(path: str, method: str) -> bool:
    if any(path.startswith(p) for p in _CHATTER_BLOCKED_ADMIN_PREFIXES):
        return False
    if path == "/admin/accounts" or path.startswith("/admin/accounts/"):
        if method == "GET" and path == "/admin/accounts/roster-counts":
            return True
        # PATCH recolors a model (the handler nulls every other field for a chatter); /active is a POST so never reaches here.
        if method == "PATCH" and path != "/admin/accounts/active":
            return True
        return False
    return True


async def chatter_session_middleware(request: Request, call_next):
    _request_chatter.set(None)
    from auth import _ACTOR
    cookie = None if _ACTOR is not None and _ACTOR.DATA else request.cookies.get(COOKIE_NAME)
    expired = False
    if cookie:
        parsed = parse_cookie_issued(cookie)
        if parsed:
            identity, expired = await _session_identity(*parsed)
            if identity is not None:
                _request_chatter.set(identity)
    claims = getattr(request.state, "oi_actor", None) if _ACTOR is not None else None
    if claims is not None and claims.kind == "chatter" and _request_chatter.get() is None:
        identity = await _ACTOR.chatter_identity(claims)
        if identity is None and (refused := _ACTOR.refused(request.url.path, "actor_revoked")):
            return refused
        _request_chatter.set(identity)

    # User cookie wins for /admin/*: the gate only applies when no owner is signed in.
    from auth import get_request_user as _get_user_local
    chatter_active = _request_chatter.get() is not None
    if chatter_active and _get_user_local() is None:
        path = request.url.path
        if path.startswith("/admin/") and not _chatter_allowed_admin(
            path, request.method,
        ):
            return Response(
                "owner-only endpoint — chatter sessions cannot access this admin surface",
                status_code=403,
            )

    response = await call_next(request)
    if expired:
        _clear_session_cookie(response)
    return response



class CurrentActor:
    __slots__ = ("kind", "id", "username", "account_ids")

    def __init__(self, kind: str, id_: str, username: str, account_ids: frozenset[str]):
        self.kind = kind
        self.id = id_
        self.username = username
        self.account_ids = account_ids


def current_actor() -> "CurrentActor | None":
    from auth import get_request_user

    u = get_request_user()
    if u is not None:
        return CurrentActor(
            kind="user", id_=u.id, username=u.username, account_ids=u.account_ids,
        )
    c = _request_chatter.get()
    if c is not None:
        return CurrentActor(
            kind="chatter", id_=c.id, username=c.username, account_ids=c.account_ids,
        )
    return None


def assert_owner() -> "CurrentActor":
    actor = current_actor()
    if actor is None:
        raise HTTPException(status_code=401, detail="sign in required")
    if actor.kind != "user":
        raise HTTPException(
            status_code=403,
            detail="owner-only endpoint — chatter sessions cannot perform this action",
        )
    return actor



admin_router = APIRouter(prefix="/admin/chatters", tags=["admin-chatters"])


class _LinkBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    display_name: str | None = Field(None, max_length=64)
    role_id: str | None = Field(None, max_length=64)
    account_ids: list[str] | None = None
    group_id: int | None = None


def _setup_from(body: BaseModel) -> dict:
    from employees import SETUP_KEYS
    return {k: getattr(body, k) for k in SETUP_KEYS if k in body.model_fields_set}


class AdminInviteResp(BaseModel):
    token: str
    expires_at: datetime
    accept_path: str


@admin_router.post("/link")
async def link_chatter(body: _LinkBody = Body(...)) -> dict:
    """Link an existing chatter to the current owner by username.
    Idempotent — second call with the same username returns 200 with
    `already_linked: true`. We never create the Chatter row here —
    chatters self-register via an invite token (POST /admin/chatters/invite)
    so an owner can't squat on someone else's username."""
    actor = assert_owner()
    target_username = _normalize_username(body.username)
    if not target_username:
        raise HTTPException(status_code=400, detail="username required")
    from employees import setup_login_employee, validate_employee_setup
    setup = await validate_employee_setup(actor.id, _setup_from(body))

    async with get_session() as s:
        chatter = (await s.execute(
            select(Chatter).where(Chatter.username == target_username)
        )).scalar_one_or_none()
        if chatter is None:
            raise HTTPException(
                status_code=404,
                detail=f"no chatter named {target_username!r} — send them an invite link instead",
            )
        if body.display_name and not chatter.display_name:
            chatter.display_name = body.display_name.strip()

        already_linked = not await link_login(s, chatter, actor.id)

    employee_id = await setup_login_employee(actor.id, chatter.id, setup)
    return {
        "ok": True,
        "chatter_id": chatter.id,
        "username": chatter.username,
        "already_linked": already_linked,
        "employee_id": employee_id,
    }


class _InviteBody(BaseModel):
    display_name: str | None = Field(None, max_length=64)
    role_id: str | None = Field(None, max_length=64)
    account_ids: list[str] | None = None
    group_id: int | None = None


async def _mint_invite(s, owner_id: str, setup_json: str | None) -> AdminInviteResp:
    token = secrets.token_urlsafe(24)
    now = datetime.utcnow()
    expires = now + timedelta(seconds=INVITE_TTL_SECONDS)
    s.add(ChatterInvite(token=token, user_id=owner_id, created_at=now, expires_at=expires,
                        setup_json=setup_json))
    await s.flush()
    return AdminInviteResp(token=token, expires_at=expires, accept_path=f"/chatter-login?token={token}")


@admin_router.post("/invite", response_model=AdminInviteResp)
async def invite_chatter(body: _InviteBody | None = Body(None)) -> AdminInviteResp:
    """Mint a single-use signup token good for 24h. The owner copies the
    `<dashboard>/chatter-login?token=…` URL and shares it with the new
    chatter; first login through that URL auto-links them to this owner.
    An optional body is the Employee setup (role, Creators, group, name),
    checked now and applied when the invite is accepted."""
    actor = assert_owner()
    setup: dict = {}
    if body is not None:
        from employees import validate_employee_setup
        setup = await validate_employee_setup(actor.id, _setup_from(body))
    async with get_session() as s:
        return await _mint_invite(s, actor.id, json.dumps(setup) if setup else None)



class PendingInviteRow(AdminInviteResp):
    created_at: datetime
    display_name: str | None = None
    role_id: str | None = None
    account_ids: list[str] | None = None
    group_id: int | None = None


async def _own_pending_invite(s, owner_id: str, token: str) -> ChatterInvite:
    invite = await s.get(ChatterInvite, token)
    if invite is None or invite.user_id != owner_id or invite.used_at is not None:
        raise HTTPException(status_code=404, detail="no such pending invite")
    return invite


@admin_router.get("/invites", response_model=list[PendingInviteRow])
async def list_pending_invites() -> list[PendingInviteRow]:
    """The caller's unused, unexpired invites, newest first, with their setup."""
    actor = assert_owner()
    async with get_session() as s:
        invites = (await s.execute(
            select(ChatterInvite)
            .where(ChatterInvite.user_id == actor.id, ChatterInvite.used_at.is_(None),
                   ChatterInvite.expires_at > datetime.utcnow())
            .order_by(ChatterInvite.created_at.desc())
        )).scalars().all()
    rows = []
    for inv in invites:
        try:
            setup = json.loads(inv.setup_json) if inv.setup_json else {}
        except ValueError:
            setup = {}
        rows.append(PendingInviteRow(
            token=inv.token, expires_at=inv.expires_at, created_at=inv.created_at,
            accept_path=f"/chatter-login?token={inv.token}",
            display_name=setup.get("display_name"), role_id=setup.get("role_id"),
            account_ids=setup.get("account_ids"), group_id=setup.get("group_id"),
        ))
    return rows


@admin_router.delete("/invites/{token}")
async def revoke_invite(token: str) -> dict:
    """Delete an unused invite of the caller's, so its link stops working."""
    actor = assert_owner()
    async with get_session() as s:
        await s.delete(await _own_pending_invite(s, actor.id, token))
    return {"ok": True}


@admin_router.post("/invites/{token}/resend", response_model=AdminInviteResp)
async def resend_invite(token: str) -> AdminInviteResp:
    """Replace an unused invite with a fresh link good for another 24h, keeping
    its setup; the old link stops working."""
    actor = assert_owner()
    async with get_session() as s:
        old = await _own_pending_invite(s, actor.id, token)
        setup_json = old.setup_json
        await s.delete(old)
        return await _mint_invite(s, actor.id, setup_json)



class FolderGrant(BaseModel):
    folder_id: int
    folder_name: str | None = None


class AccessResp(BaseModel):
    account_ids: list[str]
    folder_access: dict[str, list[int]]


class _AccountAccessBody(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


class _FolderAccessBody(BaseModel):
    account_id: str = Field(..., min_length=1)
    folders: list[FolderGrant] = Field(default_factory=list)


def _assert_owns(actor: "CurrentActor", account_id: str) -> None:
    if account_id not in actor.account_ids:
        raise HTTPException(
            status_code=403,
            detail=f"account {account_id!r} is not one of yours",
        )


async def _assert_linked(s, chatter_id: str, owner_id: str) -> None:
    linked = (await s.execute(
        select(ChatterUser.chatter_id).where(
            ChatterUser.chatter_id == chatter_id,
            ChatterUser.user_id == owner_id,
        )
    )).first()
    if linked is None:
        raise HTTPException(
            status_code=404,
            detail=f"chatter {chatter_id!r} is not linked to you",
        )


@admin_router.get("/{chatter_id}/access", response_model=AccessResp)
async def get_chatter_access(chatter_id: str) -> AccessResp:
    """This owner's visibility grants for one linked chatter — the account
    allowlist (empty = all of this owner's models) plus the per-account
    folder allowlists (only for accounts this owner owns)."""
    actor = assert_owner()
    async with get_session() as s:
        await _assert_linked(s, chatter_id, actor.id)
        acct_rows = (await s.execute(
            select(ChatterAccountAccess.account_id).where(
                ChatterAccountAccess.chatter_id == chatter_id,
                ChatterAccountAccess.user_id == actor.id,
            )
        )).all()
        fa_rows = []
        if actor.account_ids:
            fa_rows = (await s.execute(
                select(
                    ChatterFolderAccess.account_id,
                    ChatterFolderAccess.folder_id,
                ).where(
                    ChatterFolderAccess.chatter_id == chatter_id,
                    ChatterFolderAccess.account_id.in_(list(actor.account_ids)),
                )
            )).all()
    folder_access: dict[str, list[int]] = {}
    for aid, fid in fa_rows:
        folder_access.setdefault(aid, []).append(fid)
    return AccessResp(
        account_ids=[r[0] for r in acct_rows if r[0] in actor.account_ids],
        folder_access=folder_access,
    )


@admin_router.put("/{chatter_id}/account-access")
async def put_chatter_account_access(
    chatter_id: str, body: _AccountAccessBody = Body(...),
) -> dict:
    """Replace THIS owner's account allowlist for the chatter atomically.
    Empty list = remove the restriction (chatter sees all of this owner's
    models again). Rejects any account id the owner doesn't own."""
    from employees import _replace_login_access
    actor = assert_owner()
    for aid in body.account_ids:
        _assert_owns(actor, aid)
    deduped = sorted(set(body.account_ids))
    async with get_session() as s:
        await _assert_linked(s, chatter_id, actor.id)
        await _replace_login_access(s, chatter_id, actor.id, deduped)
        events.on_commit(s, "assignment_changed", agency=actor.id)
    return {"ok": True, "chatter_id": chatter_id, "account_ids": deduped}


@admin_router.put("/{chatter_id}/folder-access")
async def put_chatter_folder_access(
    chatter_id: str, body: _FolderAccessBody = Body(...),
) -> dict:
    """Replace the folder allowlist for (chatter, account) atomically.
    Empty list = remove the restriction (chatter sees all folders for that
    account). The owner must own the account. folder_name is denormalised
    at write time (DA-3)."""
    actor = assert_owner()
    _assert_owns(actor, body.account_id)
    by_id: dict[int, str | None] = {}
    for g in body.folders:
        by_id[g.folder_id] = g.folder_name
    async with get_session() as s:
        await _assert_linked(s, chatter_id, actor.id)
        await s.execute(
            delete(ChatterFolderAccess).where(
                ChatterFolderAccess.chatter_id == chatter_id,
                ChatterFolderAccess.account_id == body.account_id,
            )
        )
        for fid, fname in by_id.items():
            s.add(ChatterFolderAccess(
                chatter_id=chatter_id,
                account_id=body.account_id,
                folder_id=fid,
                folder_name=fname,
                created_at=datetime.utcnow(),
            ))
    return {
        "ok": True,
        "chatter_id": chatter_id,
        "account_id": body.account_id,
        "folder_ids": sorted(by_id.keys()),
    }
