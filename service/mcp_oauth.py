"""service/mcp_oauth.py — sign in to the MCP server from the MCP client's browser (OAuth 2.1
authorization code + PKCE; how to connect: docs/runbooks/mcp-connect.md).

The access token it issues IS an owner access token (owner_tokens), minted by the same inner
`POST /admin/owner-tokens` as the MCP login tool (mcp_api.mint), named
`MCP <client name> <UTC time>`. So `/admin/mcp` checks it like any other token, it shows on the
Access tokens card, revoking it there cuts it off, and it expires as cards' tokens do
(owner_tokens.DEFAULT_DAYS). No refresh token: once it expires the 401 sends the client back here.

  GET  /.well-known/oauth-protected-resource[/admin/mcp]  RFC 9728: the MCP endpoint's resource
  GET  /.well-known/oauth-authorization-server            RFC 8414: this host is the issuer
  POST /auth/oauth/register   RFC 7591, public clients only. Stateless: client_id is the client's
                              name and redirect URIs, signed (session_stamps.sign). Throttled per
                              address (login_throttle.take_client_register).
  GET  /auth/oauth/authorize  a bad client_id, redirect_uri, response_type, PKCE or state → an error
                              page, never a redirect; no session → /login?next=<this URL>; an
                              employee or an impersonating owner → a refusal page; an owner → the
                              consent page
  POST /auth/oauth/authorize  Allow / Cancel. The form carries a CSRF value signed over the
                              session cookie and every parameter; Allow stores a one-time code
                              (CODE_TTL_S) and 303s to redirect_uri?code&state. Only these two
                              buttons ever send the browser to redirect_uri.
  POST /auth/oauth/token      form body; the code is burned on first use, then client_id,
                              redirect_uri, expiry and PKCE S256 are checked; mints the token

Codes live in this process (`_grants`): the relay runs one uvicorn worker (login_throttle's buckets
rely on the same). The session cookie a code holds is kept only until the code is used or, once expired, the next
authorize / Allow / token request.
The password, code, verifier and token are never logged; the three POST paths are audit-skipped
(audit_log._AUDIT_SKIP_PATHS: the token form body would land in the audit row as plain text).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import auth
import chatters
import login_throttle
import mcp_api
import owner_tokens
import session_stamps
import settings_api
import token_auth
import toolbox
from brand import BRAND_NAME
from db.engine import get_session

router = APIRouter()

PRM_PATH = "/.well-known/oauth-protected-resource"
AS_PATH = "/.well-known/oauth-authorization-server"
# Who serves these with no principal: server.py's share gate lets exactly these paths through.
PUBLIC_PATHS = frozenset({PRM_PATH, token_auth.PRM_MCP_PATH, AS_PATH})
REGISTER_PATH = "/auth/oauth/register"
AUTHORIZE_PATH = "/auth/oauth/authorize"
TOKEN_PATH = "/auth/oauth/token"

CODE_TTL_S = 60
MAX_GRANTS = 1000  # codes waiting for their token request; past it Allow drops the oldest
MAX_GRANTS_PER_OWNER = 3  # past it Allow drops that owner's oldest
MAX_FORM = 16 * 1024
MAX_NAME = 40  # "MCP " + name + " " + 19-char time fits the token's 64-char name
MAX_URIS = 4
MAX_URI = 200
MAX_STATE = 1024
NAME_FALLBACK = "client"

_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")  # base64url(sha256), no padding
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_LOOPBACK = ("localhost", "127.0.0.1", "::1")
_RESERVED = frozenset({"code", "state", "error", "iss"})  # what the callback adds: a redirect_uri may not carry them

WHAT_IT_CAN = ("It can read this Agency's data; make OnlyFans vault folders and add media to any of them; make "
               "bio pages and change any of them (add links, set avatar and background pictures); and propose "
               "mass messages and posts that run only after you approve them in the browser. It lasts "
               f"{owner_tokens.DEFAULT_DAYS} days; revoke it any time in Settings → AI keys → Access tokens.")
BAD_CLIENT = "This app's sign-in link is broken or was changed: start again from the app."
BAD_REDIRECT = "This app asked to send you back to an address it did not register: start again from the app."
IMPERSONATING = "You are viewing another Agency: exit that view first, then connect."
SIGNED_OUT = "Your session ended: start again from the app."
STALE_FORM = "This page is out of date: start again from the app."
BAD_REQUEST = "This app's sign-in request is incomplete or not supported: start again from the app or update it."


# ── client_id: the registration, signed ────────────────────────────────────────

@dataclass(frozen=True)
class Client:
    name: str
    redirect_uris: tuple[str, ...]


def _same(a: str, b: str) -> bool:
    """Constant-time equality for any text (compare_digest refuses non-ASCII str)."""
    return hmac.compare_digest(a.encode(), b.encode())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def client_id(client: Client) -> str:
    payload = _b64(json.dumps({"n": client.name, "r": list(client.redirect_uris)}, separators=(",", ":")).encode())
    return f"{payload}.{session_stamps.sign(payload, 'mcp-oauth-client')}"


def parse_client_id(value: str | None) -> Client | None:
    """The client a client_id names, or None when it is not one this server signed."""
    if not value or len(value) > 4096 or value.count(".") != 1:
        return None
    payload, sig = value.split(".")
    if not _same(sig, session_stamps.sign(payload, "mcp-oauth-client")):
        return None
    try:
        data = json.loads(_unb64(payload))
        return Client(str(data["n"]), tuple(str(u) for u in data["r"]))
    except (ValueError, KeyError, TypeError):
        return None


def clean_name(raw: Any) -> str:
    """client_name: printable characters only, spaces collapsed, at most MAX_NAME."""
    text = raw if isinstance(raw, str) else ""
    text = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return text[:MAX_NAME].strip() or NAME_FALLBACK


def redirect_ok(uri: Any) -> bool:
    """http://localhost[:port]/…, http://127.0.0.1[:port]/…, http://[::1][:port]/… or https://…; no userinfo, no
    fragment, no spaces or control characters, no code / state / error / iss query key (the
    callback's own), at most MAX_URI characters."""
    if not isinstance(uri, str) or not uri or len(uri) > MAX_URI:
        return False
    if any(c <= " " or c in "\\\x7f" for c in uri):
        return False
    try:
        u = urlsplit(uri)
        u.port  # noqa: B018  raises on a bad port
    except ValueError:
        return False
    if u.fragment or "#" in uri or "@" in u.netloc or not u.hostname:
        return False
    if _RESERVED & parse_qs(u.query, keep_blank_values=True).keys():
        return False
    if u.scheme == "https":
        return True
    return u.scheme == "http" and u.hostname in _LOOPBACK


# ── responses ──────────────────────────────────────────────────────────────────

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_PAGE_HEADERS = {
    **_NO_STORE,
    # No form-action: Chrome applies it to the redirect after the POST (to the client's own address).
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    # same-origin, not no-referrer: under no-referrer Chrome sends the Allow POST as `Origin: null`.
    "Referrer-Policy": "same-origin",
}

_STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f4f4f5;color:#18181b;font:16px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif}main{max-width:28rem;margin:0 auto;padding:2rem 1rem}.card{background:#fff;
border:1px solid #e4e4e7;border-radius:12px;padding:1.5rem}.brand{font-weight:600;color:#71717a;margin:0 0 1rem}
h1{font-size:1.35rem;line-height:1.3;margin:0 0 1rem;overflow-wrap:anywhere}p{margin:0 0 1rem}
dl{margin:0 0 1rem;display:grid;grid-template-columns:auto 1fr;gap:.25rem .75rem}dt{color:#71717a}
dd{margin:0;overflow-wrap:anywhere;font-weight:500}.note{color:#52525b;font-size:.95rem}
.warn{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:.75rem;overflow-wrap:anywhere}
.row{display:flex;flex-direction:column;gap:.5rem}button,.btn{display:block;width:100%;padding:.75rem 1rem;
font:inherit;font-weight:600;border-radius:8px;border:1px solid #18181b;background:#18181b;color:#fff;
cursor:pointer;text-align:center;text-decoration:none}.secondary{background:#fff;color:#18181b;border-color:#d4d4d8}
@media (min-width:480px){.row{flex-direction:row-reverse}.row button{flex:1}}
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<meta name="robots" content="noindex"><title>{html.escape(title)}</title><style>{_STYLE}</style></head>'
           f'<body><main><div class="card"><p class="brand">{html.escape(BRAND_NAME)}</p>{body}</div></main></body></html>')
    return HTMLResponse(doc, status_code=status, headers=_PAGE_HEADERS)


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    return _page("Can't connect", f"<h1>Can't connect</h1><p>{html.escape(message)}</p>", status)


def _back(redirect_uri: str, **params: str | None) -> RedirectResponse:
    """303 to the client's redirect_uri with `params` (None dropped) added to its query."""
    sep = "&" if urlsplit(redirect_uri).query else ("" if redirect_uri.endswith("?") else "?")
    q = urlencode({k: v for k, v in params.items() if v is not None})
    return RedirectResponse(f"{redirect_uri}{sep}{q}", status_code=303, headers=_NO_STORE)


def _json(body: dict[str, Any], status: int = 200, cache: str = "no-store") -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": cache})


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return _json({"error": error, "error_description": description}, status)


# ── metadata ───────────────────────────────────────────────────────────────────

def _base(request: Request) -> str | None:
    return toolbox.Creds.from_request(request).public_base()


def _metadata(request: Request, build) -> JSONResponse:
    base = _base(request)
    if base is None:
        return _json({"error": "temporarily_unavailable", "error_description": "this server's address is not set"}, 503)
    resp = _json(build(base), cache="max-age=300")
    resp.headers["Vary"] = "X-Forwarded-Host"
    return resp


def _resource(base: str) -> dict[str, Any]:
    return {"resource": f"{base}{token_auth.MCP_PATH}", "authorization_servers": [base],
            "bearer_methods_supported": ["header"], "resource_name": BRAND_NAME}


@router.get(PRM_PATH, include_in_schema=False)
@router.get(token_auth.PRM_MCP_PATH, include_in_schema=False)
async def protected_resource(request: Request) -> Response:
    return _metadata(request, _resource)


@router.get(AS_PATH, include_in_schema=False)
async def authorization_server(request: Request) -> Response:
    return _metadata(request, lambda base: {
        "issuer": base,
        "authorization_endpoint": f"{base}{AUTHORIZE_PATH}",
        "token_endpoint": f"{base}{TOKEN_PATH}",
        "registration_endpoint": f"{base}{REGISTER_PATH}",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    })


# ── registration ───────────────────────────────────────────────────────────────

@router.post(REGISTER_PATH, include_in_schema=False)
async def register(request: Request) -> Response:
    login_throttle.take_client_register(request)
    raw = await mcp_api.capped_body(request, MAX_FORM)
    try:
        meta = json.loads(raw) if raw is not None else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        meta = None
    if not isinstance(meta, dict):
        return _oauth_error("invalid_client_metadata", f"a JSON object of at most {MAX_FORM // 1024} KB")
    uris = meta.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_URIS:
        return _oauth_error("invalid_redirect_uri", f"redirect_uris: 1 to {MAX_URIS} addresses")
    if not all(redirect_ok(u) for u in uris):
        return _oauth_error("invalid_redirect_uri", "each redirect URI is http://localhost, http://127.0.0.1, "
                                                    "http://[::1] or "
                                                    f"https://, at most {MAX_URI} characters, with no fragment and no "
                                                    "code / state / error / iss query key")
    client = Client(clean_name(meta.get("client_name")), tuple(dict.fromkeys(uris)))
    # A public client: whatever auth method it asked for, it gets "none" (RFC 7591 lets the server choose).
    return _json({"client_id": client_id(client), "client_id_issued_at": int(time.time()),
                  "client_name": client.name, "redirect_uris": list(client.redirect_uris),
                  "grant_types": ["authorization_code"], "response_types": ["code"],
                  "token_endpoint_auth_method": "none"}, 201)


# ── authorize ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Grant:
    client_id: str
    redirect_uri: str
    challenge: str
    session: str
    client_name: str
    expires: float
    owner: str


_grants: dict[str, _Grant] = {}  # sha256(code) → its grant
_clock = time.monotonic


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _purge(now: float) -> None:
    for key in [k for k, g in _grants.items() if g.expires <= now]:
        _grants.pop(key, None)


def _csrf(session: str, cid: str, redirect_uri: str, challenge: str, state: str) -> str:
    return session_stamps.sign(json.dumps([session, cid, redirect_uri, challenge, state]), "mcp-oauth-consent")


def _owner_session(request: Request) -> tuple[str, Any] | str:
    """(session cookie, owner) for an owner signed in as themself, else the refusal page's text
    ("" = nobody signed in)."""
    user, session = auth.get_request_user(), request.cookies.get(auth.COOKIE_NAME)
    if user is not None and session:
        return IMPERSONATING if auth.get_impersonation() is not None else (session, user)
    if chatters.get_request_chatter() is not None:
        return mcp_api.EMPLOYEE_REFUSED[0].upper() + mcp_api.EMPLOYEE_REFUSED[1:]
    return ""


def _client_and_redirect(cid: str | None, redirect_uri: str | None) -> tuple[Client, str] | HTMLResponse:
    client = parse_client_id(cid)
    if client is None:
        return _error_page(BAD_CLIENT)
    # the asked address passes redirect_ok first: a client_id signed before a rule (F9's callback keys) still obeys it
    if not redirect_ok(redirect_uri) or not any(_registered(r, redirect_uri) for r in client.redirect_uris):
        return _error_page(BAD_REDIRECT)
    return client, redirect_uri


def _registered(registered: str, asked: str) -> bool:
    """Exact match, except a loopback http address matches on any port: a native app picks a free
    port at sign-in time (RFC 8252 §7.3). `asked` already passed redirect_ok."""
    if asked == registered:
        return True
    a, r = urlsplit(asked), urlsplit(registered)
    return (a.scheme == r.scheme == "http" and r.hostname in _LOOPBACK and a.hostname == r.hostname
            and a.path == r.path and a.query == r.query)


async def _agency_name(user: Any) -> str:
    async with get_session() as s:
        name = (await settings_api.applied_blob(s, user.id, "account")).get("agency_name")
    return name.strip() if isinstance(name, str) and name.strip() else user.username


def _hidden(**fields: str) -> str:
    return "".join(f'<input type="hidden" name="{k}" value="{html.escape(v, quote=True)}">' for k, v in fields.items())


@router.get(AUTHORIZE_PATH, include_in_schema=False)
async def authorize(request: Request) -> Response:
    _purge(_clock())  # an expired code (it holds a session cookie) goes on any sign-in traffic, not only Allow
    q = request.query_params
    found = _client_and_redirect(q.get("client_id"), q.get("redirect_uri"))
    if isinstance(found, HTMLResponse):
        return found
    client, redirect_uri = found
    # Not sent back to redirect_uri: anyone can register any https:// address, so before a signed-in
    # owner presses Allow or Cancel this host never redirects there (no open redirect).
    state = q.get("state")
    challenge = q.get("code_challenge") or ""
    if (q.get("response_type") != "code" or (state is not None and len(state) > MAX_STATE)
            or q.get("code_challenge_method") != "S256" or not _CHALLENGE.fullmatch(challenge)):
        return _error_page(BAD_REQUEST)
    who = _owner_session(request)
    if who == "":
        here = f"{AUTHORIZE_PATH}?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(here, safe='')}", status_code=302, headers=_NO_STORE)
    if isinstance(who, str):
        return _error_page(who, 403)
    session, user = who
    cid = q["client_id"]
    agency = await _agency_name(user)
    form = _hidden(client_id=cid, redirect_uri=redirect_uri, code_challenge=challenge, state=state or "",
                   csrf=_csrf(session, cid, redirect_uri, challenge, state or ""))
    e = html.escape
    u = urlsplit(redirect_uri)
    host = u.netloc
    # A loopback address is the app on this computer; any other host gets the access, so say so.
    warn = "" if u.hostname in _LOOPBACK else (
        f'<p class="warn">This sends access to <strong>{e(u.hostname or host)}</strong>. '
        f"Allow only if you started this yourself.</p>")
    body = (f"<h1>Allow {e(client.name)} to connect to {e(agency)}?</h1>"
            f"<dl><dt>Agency</dt><dd>{e(agency)}</dd><dt>Signed in as</dt><dd>{e(user.username)}</dd>"
            f"<dt>Sends you back to</dt><dd>{e(host)}</dd></dl>"
            f'<p class="note">{e(WHAT_IT_CAN)}</p>{warn}'
            f'<form method="post" action="{AUTHORIZE_PATH}">{form}<div class="row">'
            f'<button type="submit" name="decision" value="allow">Allow</button>'
            f'<button type="submit" name="decision" value="deny" class="secondary">Cancel</button></div></form>')
    return _page(f"Connect {client.name}", body)


def _form(raw: bytes | None) -> dict[str, str] | None:
    """A urlencoded body as single values; None when too big, unreadable or a key repeats."""
    if raw is None:
        return None
    try:
        parsed = parse_qs(raw.decode(), keep_blank_values=True, strict_parsing=False, max_num_fields=20)
    except (UnicodeDecodeError, ValueError):
        return None
    if any(len(v) != 1 for v in parsed.values()):
        return None
    return {k: v[0] for k, v in parsed.items()}


def _origin_host(origin: str) -> str | None:
    try:
        u = urlsplit(origin.strip())
        return u.netloc.lower() if u.scheme in ("http", "https") and u.netloc else None
    except ValueError:
        return None


def _request_host(request: Request) -> str | None:
    """The host the browser addressed: X-Forwarded-Host's first hop (behind Next), else Host."""
    h = request.headers
    host = (h.get("x-forwarded-host") or "").split(",")[0].strip() or h.get("host") or ""
    return host.lower() or None


def _store(code: str, grant: _Grant, now: float) -> None:
    """Keep `code`; never refuse: past MAX_GRANTS_PER_OWNER that owner's oldest goes, past MAX_GRANTS
    the oldest of all (codes share one TTL, so insertion order is expiry order)."""
    _purge(now)
    mine = [k for k, g in _grants.items() if g.owner == grant.owner]
    for key in mine[:max(0, len(mine) - MAX_GRANTS_PER_OWNER + 1)]:
        _grants.pop(key, None)
    while len(_grants) >= MAX_GRANTS:
        _grants.pop(next(iter(_grants)))
    _grants[_digest(code)] = grant


@router.post(AUTHORIZE_PATH, include_in_schema=False)
async def authorize_decision(request: Request) -> Response:
    # The session-bound CSRF value is the check; Origin only refuses a browser that says it came from
    # another host than this request's own (any hostname this app answers on works).
    origin = request.headers.get("origin")
    if origin is not None and _origin_host(origin) != _request_host(request):
        return _error_page(STALE_FORM, 403)
    f = _form(await mcp_api.capped_body(request, MAX_FORM))
    if f is None:
        return _error_page(STALE_FORM)
    found = _client_and_redirect(f.get("client_id"), f.get("redirect_uri"))
    if isinstance(found, HTMLResponse):
        return found
    client, redirect_uri = found
    who = _owner_session(request)
    if not isinstance(who, tuple):
        return _error_page(who or SIGNED_OUT, 403)
    session, user = who
    cid, challenge, state = f["client_id"], f.get("code_challenge", ""), f.get("state", "")
    if not _same(f.get("csrf", ""), _csrf(session, cid, redirect_uri, challenge, state)):
        return _error_page(STALE_FORM, 403)
    decision = f.get("decision")
    if decision == "deny":
        return _back(redirect_uri, error="access_denied", state=state or None)
    if decision != "allow" or not _CHALLENGE.fullmatch(challenge):
        return _error_page(STALE_FORM)
    now = _clock()
    code = secrets.token_urlsafe(32)
    _store(code, _Grant(cid, redirect_uri, challenge, session, client.name, now + CODE_TTL_S, str(user.id)), now)
    return _back(redirect_uri, code=code, state=state or None)


# ── token ──────────────────────────────────────────────────────────────────────

def pkce_ok(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.fullmatch(verifier):
        return False
    return _same(_b64(hashlib.sha256(verifier.encode()).digest()), challenge)


@router.post(TOKEN_PATH, include_in_schema=False)
async def token(request: Request) -> Response:
    _purge(_clock())
    f = _form(await mcp_api.capped_body(request, MAX_FORM))
    if f is None:
        return _oauth_error("invalid_request", "a form-encoded body, each parameter once")
    if f.get("grant_type") != "authorization_code":
        return _oauth_error("unsupported_grant_type", "only authorization_code")
    code, verifier = f.get("code") or "", f.get("code_verifier") or ""
    if not code or not verifier:
        return _oauth_error("invalid_request", "code and code_verifier are required")
    grant = _grants.pop(_digest(code), None)  # burned on any attempt: a replay finds nothing
    if grant is None or grant.expires <= _clock():
        return _oauth_error("invalid_grant", "the code is unknown, used or expired")
    if not _same(f.get("client_id") or "", grant.client_id):
        return _oauth_error("invalid_grant", "the code was issued to another client")
    if f.get("redirect_uri") != grant.redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri does not match the authorization request")
    if not pkce_ok(verifier, grant.challenge):
        return _oauth_error("invalid_grant", "code_verifier does not match code_challenge")
    name = mcp_api.token_name(grant.client_name)
    status, body = await mcp_api.mint(toolbox.Creds.from_request(request), grant.session, name)
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        # The session ended between Allow and this request (sign-out everywhere, 2FA turned on).
        return _oauth_error("invalid_grant", "the sign-in that allowed this ended: sign in again")
    return _json({"access_token": body["token"], "token_type": "Bearer",
                  "expires_in": owner_tokens.DEFAULT_DAYS * 86400})


def reset() -> None:
    """Forget every waiting code (tests)."""
    _grants.clear()

