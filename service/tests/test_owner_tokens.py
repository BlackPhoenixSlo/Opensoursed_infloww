#!/usr/bin/env python3
"""Owner access tokens (docs/plans/ultra-mode/issues/03-owner-tokens.md).

Cases:
  case_pure_mint_digest_verdict — `ifw_` token, sha256 digest, hint, verdict table.
  case_allowlist                — token_auth.allowlist() = the Toolbox's non-send routes + report files
                                  + /admin/mcp, each a real (method, route template) in server.app.routes.
  case_api_create_list_revoke   — /admin/owner-tokens: plaintext once, days 30|90|365
                                  (default 90), own rows only, revoke.
  case_bearer_resolves          — a bearer alone signs the owner in (allowlisted route); last_used_at set.
  case_bearer_beats_cookie      — another owner's cookie + a valid bearer = the bearer's owner.
  case_bad_bearer_401           — unknown / revoked / expired / pre-"log out others" bearer
                                  with a valid cookie: 401, never the cookie.
  case_master_clamped           — a Master's token sees its own Agency only; master gates refuse.
  case_blocked_routes_http      — sign-in/credential/token/SSE routes 403 (JSON) with a token.
  case_revoke_escape            — a token cannot make an Employee login (it would outlive a revoke).
  case_every_route_refused      — every route in server.app.routes but the allowlist 403s with a token.
  case_admin_password_refuses_token — the founder password gate refuses token requests.
  case_chatter_cookie_suppressed — a chatter cookie beside a bearer resolves no chatter; the route sees
                                  no Cookie / X-Employee-Id header at all (stripped from the ASGI scope).
  case_employee_header_ignored  — X-Employee-Id dropped; the row lands on the owner's
                                  Employee with via="token <name>"; cookie rows keep via NULL.

No network: the account registry is stubbed.

Run: ./venv/bin/python service/tests/test_owner_tokens.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import hashlib  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import Request  # noqa: E402
from sqlalchemy import select  # noqa: E402
from starlette.routing import Mount, WebSocketRoute  # noqa: E402

import accounts as account_registry  # noqa: E402
import auth  # noqa: E402
import chatters  # noqa: E402
import owner_tokens  # noqa: E402
import server  # noqa: E402
import token_auth  # noqa: E402
import toolbox_decide as td  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Action, Chatter, ChatterUser, Employee, OwnerToken, User, UserAccount  # noqa: E402

client = _harness.make_client()

A, B = "610001", "610002"  # A: alice's Creator; B: bob's
_ACCOUNTS = (A, B)
account_registry.get_account = lambda aid: {"id": aid} if aid in _ACCOUNTS else None
account_registry.list_accounts = lambda **_: [{"id": a, "has_session": True} for a in _ACCOUNTS]
account_registry.is_account = lambda aid: aid in _ACCOUNTS
account_registry.account_ids = lambda: frozenset(_ACCOUNTS)
account_registry.get_active_account_id = lambda: A

LEAK_RE = re.compile(r"ifw_[A-Za-z0-9_-]{40,}")
ALICE, BOB, BOSS = (uuid.uuid4().hex for _ in range(3))  # BOSS: a Master linked to A only
CHATTER = uuid.uuid4().hex


async def _setup() -> None:
    async with get_session() as s:
        s.add_all([User(id=ALICE, username="alice", password="pw"),
                   User(id=BOB, username="bob", password="pw"),
                   User(id=BOSS, username="boss", password="pw", is_admin=True)])
        s.add_all([Account(id=a, nickname=a) for a in _ACCOUNTS])
        s.add(Chatter(id=CHATTER, username="chatty", password="pw"))
        await s.flush()
        s.add_all([UserAccount(user_id=ALICE, account_id=A), UserAccount(user_id=BOB, account_id=B),
                   UserAccount(user_id=BOSS, account_id=A), ChatterUser(chatter_id=CHATTER, user_id=ALICE)])


asyncio.run(_setup())


def _cookie(user_id: str) -> dict[str, str]:
    return {auth.COOKIE_NAME: auth._make_cookie(user_id)}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mint(user_id: str, name: str = "mcp", days: int | None = None) -> dict:
    body = {"name": name} if days is None else {"name": name, "days": days}
    r = client.post("/admin/owner-tokens", json=body, cookies=_cookie(user_id))
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


def _me(headers=None, cookies=None):
    r = client.get("/auth/me", headers=headers or {}, cookies=cookies or {})
    return r.status_code, (r.json() if r.status_code == 200 else r.text)


def _ids(headers=None, cookies=None):
    """The Creators GET /admin/accounts (creators_list, allowlisted) lists for this credential."""
    r = client.get("/admin/accounts", headers=headers or {}, cookies=cookies or {})
    return r.status_code, ([a["id"] for a in r.json()["accounts"]] if r.status_code == 200 else r.text)


def _set_token(token_id: int, **values) -> None:
    async def go():
        async with get_session() as s:
            row = await s.get(OwnerToken, token_id)
            for k, v in values.items():
                setattr(row, k, v)
    asyncio.run(go())


def case_pure_mint_digest_verdict() -> None:
    t = owner_tokens.mint()
    assert t.startswith("ifw_") and LEAK_RE.fullmatch(t), t
    assert owner_tokens.mint() != t
    assert owner_tokens.digest(t) == hashlib.sha256(t.encode()).hexdigest()
    assert owner_tokens.hint(t) == "ifw_…" + t[-4:]
    assert owner_tokens.bearer(f"Bearer {t}") == t
    assert owner_tokens.bearer(f"bearer {t}") == t
    assert owner_tokens.bearer(f"Bearer\t{t}") == t and owner_tokens.bearer(f"  Bearer   {t} ") == t
    for h in (None, "", "Bearer", "Bearer ", "Bearer abc", "Basic xyz", t):
        assert owner_tokens.bearer(h) is None, h
    now = datetime(2026, 11, 14, 12)
    day = timedelta(days=1)
    V = owner_tokens.verdict
    base = dict(created_at=now - day, expires_at=now + day, revoked_at=None, valid_after=None,
                last_used_at=now - timedelta(seconds=10), now=now)
    assert V(**base) == "ok"
    assert V(**{**base, "last_used_at": None}) == "touch"
    assert V(**{**base, "last_used_at": now - timedelta(seconds=301)}) == "touch"
    assert V(**{**base, "revoked_at": now - timedelta(seconds=1)}) == "refuse"
    assert V(**{**base, "expires_at": now}) == "refuse"
    assert V(**{**base, "valid_after": now - timedelta(hours=1)}) == "refuse"  # logged out others after minting
    assert V(**{**base, "valid_after": now - 2 * day}) == "ok"
    assert owner_tokens.DAYS == (30, 90, 365) and owner_tokens.DEFAULT_DAYS == 90


def case_allowlist() -> None:
    want = {(t.method, t.path) for t in td.TOOLS if t.effect != "send"} | {
        ("POST", "/admin/reports/files"), ("GET", "/admin/reports/files/{file_id}"), ("POST", "/admin/mcp")}
    assert token_auth.allowlist() == want, token_auth.allowlist() ^ want
    real = {(m, r.path) for r in server.app.routes for m in getattr(r, "methods", None) or ()}
    assert want <= real, want - real
    send = td.Tool("zz_send", "t", "POST", "/admin/zz-send", td.NoArgs, "send")
    saved = td.TOOLS
    td.TOOLS = saved + (send,)
    try:
        assert ("POST", "/admin/zz-send") not in token_auth.allowlist()  # a send tool runs from a plan only
    finally:
        td.TOOLS = saved


def case_api_create_list_revoke() -> None:
    made = _mint(ALICE, "claude desktop")
    tok = made["token"]
    assert LEAK_RE.fullmatch(tok) and made["name"] == "claude desktop"
    exp = datetime.fromisoformat(made["expires_at"].replace("Z", ""))
    assert timedelta(days=89) < exp - datetime.utcnow() <= timedelta(days=90), exp
    for days in (30, 365):
        assert _mint(ALICE, f"d{days}", days)["expires_at"]
    for bad in (0, 7, 1000):
        r = client.post("/admin/owner-tokens", json={"name": "x", "days": bad}, cookies=_cookie(ALICE))
        assert r.status_code == 422, (bad, r.status_code)
    r = client.post("/admin/owner-tokens", json={"name": "  ", "days": 30}, cookies=_cookie(ALICE))
    assert r.status_code == 422, r.status_code
    assert client.post("/admin/owner-tokens", json={"name": "x"}).status_code == 401
    listed = client.get("/admin/owner-tokens", cookies=_cookie(ALICE)).json()["tokens"]
    assert {t["name"] for t in listed} >= {"claude desktop", "d30", "d365"}, listed
    assert all("token" not in t and t["hint"].startswith("ifw_…") for t in listed), listed
    assert tok not in str(listed)
    assert client.get("/admin/owner-tokens", cookies=_cookie(BOB)).json()["tokens"] == []

    async def stored():
        async with get_session() as s:
            return (await s.execute(select(OwnerToken).where(OwnerToken.id == made["id"]))).scalar_one()
    row = asyncio.run(stored())
    assert row.token_sha256 == owner_tokens.digest(tok) and tok not in (row.hint, row.name)
    assert _ids(_bearer(tok)) == (200, [A])
    assert client.delete(f"/admin/owner-tokens/{made['id']}", cookies=_cookie(BOB)).status_code == 404
    assert client.delete(f"/admin/owner-tokens/{made['id']}", cookies=_cookie(ALICE)).status_code == 200
    assert asyncio.run(stored()).revoked_at is not None
    assert _ids(_bearer(tok))[0] == 401


def case_bearer_resolves() -> None:
    made = _mint(ALICE)
    assert _ids(_bearer(made["token"])) == (200, [A])

    async def used():
        async with get_session() as s:
            return (await s.get(OwnerToken, made["id"])).last_used_at
    assert asyncio.run(used()) is not None
    r = client.get("/admin/automation-rules", params={"account_id": A}, headers=_bearer(made["token"]))
    assert r.status_code == 200, r.text
    r = client.get("/admin/automation-rules", params={"account_id": B}, headers=_bearer(made["token"]))
    assert r.status_code == 403, r.text


def case_bearer_beats_cookie() -> None:
    tok = _mint(ALICE)["token"]
    assert _ids(None, _cookie(BOB)) == (200, [B])
    assert _ids(_bearer(tok), _cookie(BOB)) == (200, [A])


def case_bad_bearer_401() -> None:
    made = _mint(ALICE)
    expired, revoked, stale = _mint(ALICE), _mint(ALICE), _mint(ALICE)
    _set_token(expired["id"], expires_at=datetime.utcnow() - timedelta(seconds=1))
    _set_token(revoked["id"], revoked_at=datetime.utcnow())
    _set_token(stale["id"], created_at=datetime.utcnow() - timedelta(days=2))
    assert _me(None, _cookie(BOB))[1]["username"] == "bob"
    unknown = "ifw_" + "A" * 43
    for tok in (unknown, "ifw_", expired["token"], revoked["token"]):
        for probe in (_me, _ids):  # 401 before the allowlist: a bad token is a bad token anywhere
            status, body = probe(_bearer(tok), _cookie(BOB))
            assert status == 401, (tok[:8], status, body)

    async def log_out_others():
        async with get_session() as s:
            (await s.get(User, ALICE)).sessions_valid_after = datetime.utcnow() - timedelta(days=1)
    asyncio.run(log_out_others())
    try:
        assert _ids(_bearer(stale["token"]), _cookie(BOB))[0] == 401
        assert _ids(_bearer(made["token"]))[0] == 200  # minted after the revoke
    finally:
        async def undo():
            async with get_session() as s:
                (await s.get(User, ALICE)).sessions_valid_after = None
        asyncio.run(undo())


def case_master_clamped() -> None:
    tok = _mint(BOSS)["token"]
    # The Master's cookie reaches bob's Creator B; its token does not.
    assert _ids(None, _cookie(BOSS)) == (200, [A, B])
    assert _ids(_bearer(tok)) == (200, [A])
    rules = "/admin/automation-rules"
    assert client.get(rules, params={"account_id": B}, cookies=_cookie(BOSS)).status_code == 200
    assert client.get(rules, params={"account_id": B}, headers=_bearer(tok)).status_code == 403
    assert client.get(rules, params={"account_id": A}, headers=_bearer(tok)).status_code == 200
    assert client.get("/admin/secrets", cookies=_cookie(BOSS)).status_code == 200
    assert client.get("/admin/secrets", headers=_bearer(tok)).status_code == 403


def case_blocked_routes_http() -> None:
    tok = _mint(ALICE)["token"]
    for method, path, body in [
        ("POST", "/auth/logout", None), ("POST", "/auth/2fa/init", {}), ("POST", "/auth/sessions/revoke-others", {}),
        ("POST", "/chatter/logout", None),
        ("GET", "/admin/owner-tokens", None), ("POST", "/admin/owner-tokens", {"name": "x"}),
        ("DELETE", "/admin/owner-tokens/1", None),
        ("POST", "/admin/impersonate", {"user_id": BOB, "admin_password": "test-admin-password"}),
        ("DELETE", "/admin/impersonate", None),
        ("PUT", "/admin/my-llm-keys", {"deepseek": ""}), ("GET", "/admin/my-llm-keys", None),
        ("GET", "/events", None), ("GET", "/auth/me", None), ("POST", "/auth/login", {"username": "alice"}),
        ("POST", "/admin/employees/1/password", {"password": "x"}), ("POST", "/admin/employees/1/2fa/reset", {}),
        ("POST", "/admin/link-shares", {}), ("PATCH", "/api/of/v2/users/me/settings/security", {}),
        ("PUT", "/api/of/v2/users/me/settings/security", {}), ("POST", "/admin/reports/files/x", None),
        ("GET", "/admin/reports/filesx", None), ("GET", "/admin/mcp", None),
    ]:
        r = client.request(method, path, json=body, headers=_bearer(tok))
        assert r.status_code == 403 and "access token" in r.json()["detail"], (method, path, r.status_code, r.text[:120])


def case_revoke_escape() -> None:
    """Measured before the allowlist: a token minted an Employee login, which stayed signed in after the
    token was revoked. Now the route never runs."""
    tok = _mint(ALICE)["token"]
    r = client.post("/admin/employees/login", json={"username": "escapee", "password": "pw123456"},
                    headers=_bearer(tok))
    assert r.status_code == 403 and "access token" in r.json()["detail"], (r.status_code, r.text)

    async def made():
        async with get_session() as s:
            return (await s.execute(select(Chatter).where(Chatter.username == "escapee"))).scalar_one_or_none()
    assert asyncio.run(made()) is None


_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([a-z]+))?\}")
_SAMPLE = {"int": "1", "float": "1.5", "path": "x/y", "uuid": "00000000-0000-0000-0000-000000000001"}


def case_every_route_refused() -> None:
    tok = _mint(ALICE)["token"]
    allowed = token_auth.allowlist()
    checked, leaks = 0, []
    for route in server.app.routes:
        if isinstance(route, WebSocketRoute):
            continue  # no http middleware; a websocket gets no identity from a bearer
        if isinstance(route, Mount):
            pairs = [("GET", route.path + "/x")]
        else:
            path = _PARAM.sub(lambda m: _SAMPLE.get(m.group(2) or "", "x1"), route.path)
            pairs = [(m, path) for m in sorted(route.methods) if (m, route.path) not in allowed]
        for method, path in pairs:
            body = None if method in ("GET", "HEAD", "DELETE") else b"{}"  # a sized body: the batch-cap hook 411s none
            r = client.request(method, path, content=body, headers=_bearer(tok))
            checked += 1
            if r.status_code != 403 or (method != "HEAD" and "access token" not in r.text):
                leaks.append((method, getattr(route, "path", path), r.status_code))
    assert not leaks, leaks
    assert checked > 500, checked


def case_admin_password_refuses_token() -> None:
    tok = _mint(BOSS)["token"]
    body = {"account_id": "999999999", "admin_password": "test-admin-password"}
    # Founder grant gates on the password alone: an owner token with the right password is refused.
    alice_tok = _mint(ALICE)["token"]
    for t in (tok, alice_tok):
        r = client.post(f"/admin/users/{BOB}/accounts", json=body, headers=_bearer(t))
        assert r.status_code == 403, (r.status_code, r.text)
    r = client.post(f"/admin/users/{BOB}/accounts", json=body, cookies=_cookie(ALICE))
    assert r.status_code != 403, (r.status_code, r.text)  # the cookie path still reaches the handler


def case_chatter_cookie_suppressed() -> None:
    chat = {chatters.COOKIE_NAME: chatters._make_cookie(CHATTER)}
    r = client.get("/chatter/me", cookies=chat)
    assert r.status_code == 200 and r.json() and r.json()["username"] == "chatty", r.text
    tok = _mint(ALICE)["token"]
    probe = td.Tool("zz_tok_hdr", "test", "GET", "/admin/zz-tok/hdr", td.NoArgs, "read")
    saved = td.TOOLS
    td.TOOLS = saved + (probe,)  # allowlisted for this case only
    try:
        r = client.get("/admin/zz-tok/hdr", cookies={**chat, **_cookie(BOB)},
                       headers={**_bearer(tok), "X-Employee-Id": "7"})
    finally:
        td.TOOLS = saved
    assert r.status_code == 200 and r.json() == {"cookie": None, "employee": None, "chatter": None,
                                                 "user": "alice"}, r.text


async def _hdr(request: Request):
    u, c = auth.get_request_user(), chatters.get_request_chatter()
    return {"cookie": request.headers.get("cookie"), "employee": request.headers.get("x-employee-id"),
            "chatter": c.username if c else None, "user": u.username if u else None}


server.app.add_api_route("/admin/zz-tok/hdr", _hdr, methods=["GET"])


def case_employee_header_ignored() -> None:
    async def other_employee() -> int:
        async with get_session() as s:
            e = Employee(display_name="Sam", user_id=ALICE)
            s.add(e)
            await s.flush()
            return e.id
    sam = asyncio.run(other_employee())
    made = _mint(ALICE, "agent one")

    def post(**kw) -> Action:
        recipe = {"dataset": "sales", "window": {"preset": "last_7_days"}}
        r = client.post("/admin/reports/files", json={"recipe": recipe},
                        headers={"X-Employee-Id": str(sam), **kw.get("h", {})}, cookies=kw.get("c", {}))
        assert r.status_code == 200, r.text

        async def row():
            async with get_session() as s:
                return (await s.execute(select(Action).where(Action.action == "POST /admin/reports/files")
                                        .order_by(Action.id.desc()).limit(1))).scalar_one()
        return asyncio.run(row())

    via_token = post(h=_bearer(made["token"]))
    assert via_token.via == "token agent one", via_token.via
    assert via_token.employee_id not in (None, sam), via_token.employee_id

    async def owner_emp():
        async with get_session() as s:
            return (await s.get(Employee, via_token.employee_id)).user_id
    assert asyncio.run(owner_emp()) == ALICE
    via_cookie = post(c=_cookie(ALICE))
    assert via_cookie.via is None and via_cookie.employee_id == sam, (via_cookie.via, via_cookie.employee_id)
    rows = client.get("/admin/audit", params={"include_background": "true"}, cookies=_cookie(ALICE)).json()["actions"]
    assert any(a.get("via") == "token agent one" for a in rows), rows[:3]


_harness.run()
