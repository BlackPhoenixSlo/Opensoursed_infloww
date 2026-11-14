"""service/token_auth.py — an owner access token's request (`Authorization: Bearer ifw_…`,
owner_tokens; docs/plans/ultra-mode/issues/03-owner-tokens.md, build-log F3).

A token is for an MCP client, not a browser, so it reaches an ALLOWLIST and nothing else:
the routes of the Toolbox's non-send tools (`toolbox_decide.TOOLS`; send tools run only from
an owner-approved plan), the report-file download pair and `POST /admin/mcp`. Matched on
(method, route template) of the route Starlette dispatches the request to (`matched`, the
same first-FULL-match walk over `app.routes` as Starlette's router; auth walks it once and
hands template + path params to both checks), never on a path prefix: a new route is closed
to tokens until it is listed here.

  StripCookieIdentities  pure ASGI, outside every hook: a bearer request loses its Cookie and
                         X-Employee-Id headers before any Request object exists, so no later
                         reader (chatter middleware, share gate, audit, attribution) sees them
  allowed                the allowlist check (auth.session_middleware answers 403 otherwise)
  write_refusal          a write tool's route takes an untyped body wider than the tool's
                         schema: a bearer's raw request must equal the one the tool builds from
                         the same args (`toolbox_decide.route_refusal`), else 403 (build-log
                         step 3 MUST)
  resolve                token → its owner, or None (unknown, revoked, expired, minted before
                         "Log out other sessions"); last_used_at bumped at most every 5 min

auth.session_middleware owns the ContextVars and calls these; this module never imports auth.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterable, NamedTuple

from sqlalchemy import select, update
from starlette.routing import Match

import owner_tokens
import toolbox_decide as td
from agency_scope import agency_account_ids
from db.engine import get_session
from db.models import OwnerToken, User

log = logging.getLogger(__name__)

REFUSED = "not allowed with an access token: it reaches only the MCP tools and report downloads"
WRITE_REFUSED = "not allowed with an access token: a write must be one its MCP tool could have sent"

MCP_PATH = "/admin/mcp"

# Besides the tools' own routes: the report_file download, and the MCP endpoint itself.
EXTRA: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/admin/reports/files/{file_id}"),
    ("POST", MCP_PATH),
})

# Headers a bearer request must not carry past this layer: every cookie identity (owner
# session, impersonation, chatter, share) and the acting-employee pick.
STRIPPED = (b"cookie", b"x-employee-id")


def allowlist() -> frozenset[tuple[str, str]]:
    """(method, route template) pairs a token may call. Read per request from `td.token_tools()`
    (a few dozen tuples), so the list cannot drift from the Toolbox: each tool's route, nothing else."""
    return frozenset((t.method, t.path) for t in td.token_tools()) | EXTRA


def matched(scope: dict[str, Any], routes: Iterable[Any]) -> tuple[str | None, dict[str, Any]]:
    """(template, path params) of the route Starlette's router dispatches `scope` to: the first
    FULL match (path and method), as Router.app walks them. (None, {}) when only a 405/404
    would answer."""
    for route in routes:
        match, child = route.matches(scope)
        if match is Match.FULL:
            return getattr(route, "path", None), dict(child.get("path_params") or {})
    return None, {}


def allowed(method: str, template: str | None) -> bool:
    return (method, template) in allowlist()


async def write_refusal(request: Any, template: str | None, params: dict[str, Any]) -> str | None:
    """Why a bearer's request to a write tool's route (`matched`'s template + path params) is
    wider than the tool, or None (also for every non-write route). Reads the body: the hook
    chain's Request caches it for the app."""
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
    except (ValueError, RecursionError):  # RecursionError: nested past the decoder's depth → refused, not a 500
        return "the body must be a JSON object"
    return td.route_refusal(tool, request.scope["path"], params, dict(items), accounts[0] if accounts else None, body)


class StripCookieIdentities:
    """Pure ASGI, registered outside the hook chain (server.py): an `ifw_` bearer request's
    scope loses `STRIPPED` headers, so a token never mixes with a cookie identity."""

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
    """Bump owner_tokens.last_used_at: own session, swallowed, as auth._touch_last_seen."""
    try:
        async with get_session() as s:
            await s.execute(update(OwnerToken).where(OwnerToken.id == token_id).values(last_used_at=now))
    except Exception:
        log.debug("owner token last_used_at bump skipped (non-fatal)", exc_info=True)


async def resolve(token: str) -> Owner | None:
    """The token's owner, or None when it is unknown, revoked, expired or minted before "Log
    out other sessions". `account_ids` = the Creators the owner's Agency owns: a Master's
    token is clamped to its own Agency (the caller signs it in with is_admin False)."""
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
