#!/usr/bin/env python3
"""The MCP sign-in builtins `register_account` / `login` (mcp_api; ultra-mode ticket 05 owner amendment):
called with no bearer, they run /auth/register or /auth/sign-in (+ /auth/2fa/login) in-process, then mint an
owner token with that fresh session. Two-Agency bench, real app, no network.

Cases:
  case_anonymous_list        — no credential: tools/list = connect_account, register_account, login; a token
                               caller lists none of them (register_account is Unknown tool for it).
  case_register              — a new owner + agency_name → a working token, the name saved, open_url on the
                               Access tokens card; a taken username 409; a bad username / short password 400.
  case_register_closed_shard — MCP_SIGNUP_URL set and OI_ORIGIN unset / another origin → 403 + the open
                               shard's register_url, whatever X-Forwarded-Host says (forged → still
                               closed); no user made. OI_ORIGIN equal to it: allowed.
  case_register_name_unsaved — the Agency-name save refused: the account and token stand, agency_name_saved
                               false, next_step names the Account settings page.
  case_login                 — an owner → a token; a wrong password 401; an employee → refused, no token row.
  case_login_throttled       — the app's sign-in throttle holds through MCP: NAME_CAPACITY wrong passwords for
                               one username from one address → the next call 429, even with the right password.
  case_login_2fa             — 2FA on: no code → asks for it; a bad code → refused; the right code → a token.
  case_secret_never_echoed   — passwords and codes appear in no result, no log record and no audit row;
                               a 422 names fields only.

Run: ./venv/bin/python service/tests/test_mcp_auth.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import account_security as sec  # noqa: E402
import login_throttle  # noqa: E402
import mcp_api  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action, OwnerToken, User  # noqa: E402
from settings_api import applied_blob  # noqa: E402

IDS = fx.seed_two_agencies()
ANON = _harness.make_client()
FWD = {"X-Forwarded-Host": "app.example.com", "X-Forwarded-Proto": "https"}
_ids = iter(range(1, 10_000))
SECRETS: list[str] = []  # every password / code sent: never seen again anywhere


def _rpc(method, params=None, headers=None):
    msg = {"jsonrpc": "2.0", "id": next(_ids), "method": method, **({"params": params} if params is not None else {})}
    r = ANON.post(mcp_api.PATH, content=json.dumps(msg).encode(),
                  headers={"Content-Type": "application/json", **(headers or {})})
    assert r.status_code == 200, (method, r.status_code, r.text)
    for s in SECRETS:
        assert s not in r.text, (method, r.text)
    return r.json()


def _tool(name, args, headers=FWD):
    for k in ("password", "code"):
        if args.get(k):
            SECRETS.append(args[k])
    res = _rpc("tools/call", {"name": name, "arguments": args}, headers)["result"]
    assert json.loads(res["content"][0]["text"]) == res["structuredContent"], res
    return res["isError"], res["structuredContent"]


async def _count(model, *where) -> int:
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def _user_id(username: str) -> str | None:
    async with get_session() as s:
        return (await s.execute(select(User.id).where(User.username == username))).scalar_one_or_none()


def _works(token: str) -> None:
    j = _rpc("tools/call", {"name": "creators_list", "arguments": {}}, {"Authorization": f"Bearer {token}"})
    assert j["result"]["isError"] is False, j


def case_anonymous_list() -> None:
    names = [t["name"] for t in _rpc("tools/list")["result"]["tools"]]
    assert names == ["connect_account", "register_account", "login"], names
    tok = fx.mint_token(fx.login_owner("agency_a_owner"))
    bearer = {"Authorization": f"Bearer {tok}"}
    listed = {t["name"] for t in _rpc("tools/list", headers=bearer)["result"]["tools"]}
    assert not {"connect_account", "register_account", "login"} & listed, listed
    assert _rpc("tools/call", {"name": "register_account", "arguments": {}}, bearer)["error"]["code"] == -32602
    init = _rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
    assert "register_account" in init and "login" in init and "logins_url" in init, init


def case_register() -> None:
    err, out = _tool("register_account", {"username": "mcp_new", "password": "pw-reg-1", "agency_name": "New Agency"})
    assert err is False and out["token"].startswith("ifw_") and out["username"] == "mcp_new", out
    assert out["open_url"] == "https://app.example.com/settings/ai-keys", out
    assert out["logins_url"] == "https://app.example.com" + mcp_api.LOGINS_PAGE, out
    _works(out["token"])
    uid = asyncio.run(_user_id("mcp_new"))

    async def _name():
        async with get_session() as s:
            return (await applied_blob(s, uid, "account")).get("agency_name")
    assert asyncio.run(_name()) == "New Agency"
    assert asyncio.run(_count(OwnerToken, OwnerToken.user_id == uid)) == 1
    err, out = _tool("register_account", {"username": "mcp_new", "password": "pw-reg-2"})
    assert err is True and out["error"]["status"] == 409 and "taken" in out["error"]["detail"], out
    err, out = _tool("register_account", {"username": "a@b.example", "password": "pw-reg-3"})
    assert err is True and out["error"]["status"] == 400 and "token" not in out, out
    err, out = _tool("register_account", {"username": "mcp_short", "password": "pw4"})
    assert err is True and out["error"]["status"] == 400 and asyncio.run(_user_id("mcp_short")) is None, out


def case_register_closed_shard() -> None:
    os.environ["MCP_SIGNUP_URL"] = "https://open.example.net/"
    forged = {"X-Forwarded-Host": "open.example.net", "X-Forwarded-Proto": "https"}
    try:
        for origin in (None, "https://app.example.com"):  # this shard's origin unknown; another origin
            if origin:
                os.environ["OI_ORIGIN"] = origin
            for headers in (FWD, {}, forged):  # a forged X-Forwarded-Host naming the open shard opens nothing
                err, out = _tool("register_account", {"username": "mcp_closed", "password": "pw-closed-1"}, headers)
                assert err is True and out["error"]["status"] == 403, (origin, headers, out)
                assert out["register_url"].startswith("https://open.example.net/login?mode=register"), out
                assert out["open_url"] == out["register_url"] and "token" not in out, out
        assert asyncio.run(_user_id("mcp_closed")) is None
        os.environ["OI_ORIGIN"] = "https://OPEN.example.net"  # the open shard itself (config, not the header)
        err, out = _tool("register_account", {"username": "mcp_open", "password": "pw-open-1"})
        assert err is False and out["token"].startswith("ifw_"), out
    finally:
        os.environ.pop("MCP_SIGNUP_URL")
        os.environ.pop("OI_ORIGIN", None)


def case_register_name_unsaved() -> None:
    real = mcp_api._inner

    async def refuse_name(creds, method, path, body, cookie=None):
        if path == "/admin/settings/account":
            return 500, {"detail": "boom"}, None
        return await real(creds, method, path, body, cookie)
    mcp_api._inner = refuse_name
    try:
        err, out = _tool("register_account", {"username": "mcp_noname", "password": "pw-noname-1",
                                              "agency_name": "Lost Name"})
    finally:
        mcp_api._inner = real
    assert err is False and out["token"].startswith("ifw_") and out["agency_name_saved"] is False, out
    assert "https://app.example.com/settings/account" in out["next_step"], out
    _works(out["token"])
    err, out = _tool("register_account", {"username": "mcp_named", "password": "pw-named-1", "agency_name": "Kept"})
    assert err is False and "agency_name_saved" not in out, out


def case_login_throttled() -> None:
    login_throttle.reset()
    try:
        for _ in range(login_throttle.NAME_CAPACITY):
            err, out = _tool("login", {"username": "agency_a_owner", "password": "wrong-pw-throttle"})
            assert err is True and out["error"]["status"] == 401, out
        for pw in ("wrong-pw-throttle", fx.PASSWORD):
            err, out = _tool("login", {"username": "agency_a_owner", "password": pw})
            assert err is True and out["error"]["status"] == 429 and "token" not in out, out
    finally:
        login_throttle.reset()


def case_login() -> None:
    uid = IDS["agency_b_owner"]
    before = asyncio.run(_count(OwnerToken, OwnerToken.user_id == uid))
    err, out = _tool("login", {"username": "agency_b_owner", "password": fx.PASSWORD})
    SECRETS.remove(fx.PASSWORD)  # the fixtures' shared password: other clients' cookies carry nothing of it
    assert err is False and out["token"].startswith("ifw_") and out["username"] == "agency_b_owner", out
    _works(out["token"])
    assert asyncio.run(_count(OwnerToken, OwnerToken.user_id == uid)) == before + 1
    err, out = _tool("login", {"username": "agency_b_owner", "password": "wrong-pw-9"})
    assert err is True and out["error"]["status"] == 401 and "token" not in out, out
    total = asyncio.run(_count(OwnerToken))
    err, out = _tool("login", {"username": "chatter_a", "password": fx.PASSWORD})
    SECRETS.remove(fx.PASSWORD)
    assert err is True and out["error"]["status"] == 403 and "employee" in out["error"]["detail"], out
    assert "token" not in out and asyncio.run(_count(OwnerToken)) == total, out


async def _two_factor_owner(name: str) -> str:
    secret = sec.new_secret()
    async with get_session() as s:
        s.add(User(id=uuid.uuid4().hex, username=name, password="pw-2fa-1", totp_secret=secret))
    return secret


def case_login_2fa() -> None:
    secret = asyncio.run(_two_factor_owner("mcp_2fa"))
    err, out = _tool("login", {"username": "mcp_2fa", "password": "pw-2fa-1"})
    assert err is True and out["two_factor"] is True and "code" in out["error"]["detail"], out
    bad = "000000" if sec.totp(secret, sec.current_step()) != "000000" else "111111"
    err, out = _tool("login", {"username": "mcp_2fa", "password": "pw-2fa-1", "code": bad})
    assert err is True and out["error"]["status"] == 400 and "not right" in out["error"]["detail"], out
    SECRETS.remove(bad)  # a digit string that may well appear in an id: checked by the case above
    code = sec.totp(secret, sec.current_step())
    err, out = _tool("login", {"username": "mcp_2fa", "password": "pw-2fa-1", "code": code})
    SECRETS.remove(code)
    assert err is False and out["token"].startswith("ifw_"), out


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        # The DB driver's own DEBUG trace prints the users INSERT (the password column is plaintext by the owner's
        # decision, as for the browser's register); it is off outside a debug run. Every other logger counts.
        if not record.name.startswith(("aiosqlite", "sqlalchemy")):
            self.lines.append(record.getMessage() + repr(record.args))


async def _audit_rows() -> list[str]:
    async with get_session() as s:
        return [f"{a} {p}" for a, p in (await s.execute(select(Action.action, Action.payload_json))).all()]


def case_secret_never_echoed() -> None:
    grab, root = _Grab(), logging.getLogger()
    saved = root.level
    root.addHandler(grab)
    root.setLevel(logging.DEBUG)
    try:
        _tool("register_account", {"username": "mcp_logs", "password": "pw-logged-7"})
        _tool("login", {"username": "mcp_logs", "password": "pw-logged-7"})
        _tool("login", {"username": "mcp_logs", "password": "pw-wrong-7"})
        err, out = _tool("login", {"username": "mcp_logs", "password": "pw-422-77" * 40})  # over max_length
        assert err is True and out["error"]["status"] == 422, out
    finally:
        root.removeHandler(grab)
        root.setLevel(saved)
    secrets = [s for s in SECRETS if len(s) >= 6 and not s.isdigit()]
    assert secrets, SECRETS
    for s in secrets:
        assert not any(s in line for line in grab.lines), s
        assert not any(s in row for row in asyncio.run(_audit_rows())), s
    assert not any("/admin/mcp" in row for row in asyncio.run(_audit_rows()))


_harness.run()
