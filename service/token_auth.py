from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Iterable, NamedTuple

from sqlalchemy import select, update
from starlette.routing import Match

import owner_tokens
import report_files
import toolbox_decide as td
from agency_scope import agency_account_ids
from db.engine import get_session
from db.models import OwnerToken, User

log = logging.getLogger(__name__)

REFUSED = "not allowed with an access token: it reaches only the MCP tools and report downloads"
WRITE_REFUSED = "not allowed with an access token: a write must be one its MCP tool could have sent"

MCP_PATH = "/admin/mcp"
PRM_MCP_PATH = "/.well-known/oauth-protected-resource" + MCP_PATH

MCP_OTHER_METHODS = ("GET", "DELETE", "PUT")

EXTRA: frozenset[tuple[str, str]] = frozenset({
    ("GET", report_files.ROUTE),
    ("POST", MCP_PATH),
    *((m, MCP_PATH) for m in MCP_OTHER_METHODS),
})

STRIPPED = (b"cookie", b"x-employee-id")


def allowlist() -> frozenset[tuple[str, str]]:
    return frozenset((t.method, t.path) for t in td.token_tools()) | EXTRA


def matched(scope: dict[str, Any], routes: Iterable[Any]) -> tuple[str | None, dict[str, Any]]:
    for route in routes:
        match, child = route.matches(scope)
        if match is Match.FULL:
            return getattr(route, "path", None), dict(child.get("path_params") or {})
    return None, {}


def challenge_for(base: str | None) -> str:
    return f'Bearer resource_metadata="{base}{PRM_MCP_PATH}"' if base else "Bearer"


def challenge(headers: Any, scheme: str) -> str:
    return challenge_for(td.public_base(headers.get("x-forwarded-host"), headers.get("x-forwarded-proto") or scheme,
                                        os.environ.get("APP_PUBLIC_URL")))


def allowed(method: str, template: str | None) -> bool:
    return (method, template) in allowlist()


async def write_refusal(request: Any, template: str | None, params: dict[str, Any]) -> str | None:
    tool = td.write_tool(request.scope["method"], template)
    if tool is None:
        return None
    items = request.query_params.multi_items()
    accounts = request.headers.getlist("x-account-id")
    if len({k for k, _ in items}) != len(items) or len(accounts) > 1:
        return "a parameter is repeated"
    raw = await request.body()
    try:
        body = json.loads(raw) if raw.strip() else {}
    # RecursionError: a body nested past the decoder's depth is refused, not a 500.
    except (ValueError, RecursionError):
        return "the body must be a JSON object"
    return td.route_refusal(tool, request.scope["path"], params, dict(items), accounts[0] if accounts else None, body)


class StripCookieIdentities:

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = scope.get("headers") or []
            auth = next((v for k, v in headers if k.lower() == b"authorization"), None)
            if auth is not None and owner_tokens.bearer(auth.decode("latin-1")) is not None:
                scope = {**scope, "headers": [(k, v) for k, v in headers if k.lower() not in STRIPPED]}
        await self.app(scope, receive, send)


class Owner(NamedTuple):
    user_id: str
    username: str
    account_ids: frozenset[str]
    token_id: int
    token_name: str


async def _touch(token_id: int, now: datetime) -> None:
    try:
        async with get_session() as s:
            await s.execute(update(OwnerToken).where(OwnerToken.id == token_id).values(last_used_at=now))
    except Exception:
        log.debug("owner token last_used_at bump skipped (non-fatal)", exc_info=True)


async def resolve(token: str) -> Owner | None:
    async with get_session() as s:
        found = (await s.execute(
            select(OwnerToken, User).join(User, User.id == OwnerToken.user_id)
            .where(OwnerToken.token_sha256 == owner_tokens.digest(token))
        )).first()
        if found is None:
            return None
        tok, user = found
        now = datetime.utcnow()
        verdict = owner_tokens.verdict(
            created_at=tok.created_at, expires_at=tok.expires_at, revoked_at=tok.revoked_at,
            valid_after=user.sessions_valid_after, last_used_at=tok.last_used_at, now=now,
        )
        if verdict == "refuse":
            return None
        owner = Owner(user.id, user.username, frozenset(await agency_account_ids(s, user.id)), tok.id, tok.name)
    if verdict == "touch":
        await _touch(owner.token_id, now)
    return owner
