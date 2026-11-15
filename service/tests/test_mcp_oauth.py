#!/usr/bin/env python3
"""The MCP client's browser sign-in (mcp_oauth): OAuth authorization code + PKCE whose access token is an
ordinary owner access token. Two-Agency bench, real app, no network.

Cases:
  case_metadata              — RFC 9728 / RFC 8414 JSON on this host's public address; no address → 503;
                               open behind SHARE_TOKEN, a neighbouring /.well-known path is not.
  case_register              — a public client: client_id signed, name cleaned and capped; javascript:, custom
                               schemes, plain http off loopback, a fragment, userinfo, too many or too long
                               addresses → invalid_redirect_uri; a non-object body → invalid_client_metadata.
  case_register_throttled    — REGISTER_CAPACITY registrations from one address, then 429.
  case_bad_client_or_redirect — a tampered or foreign client_id, an unregistered or non-exact redirect_uri →
                               an error page, never a redirect.
  case_pkce_required         — no code_challenge, `plain`, a malformed challenge, a wrong response_type, a too
                               long state → an error page, never a redirect to the client.
  case_no_redirect_before_consent — every answer before a signed-in owner's Allow / Cancel (bad request, signed
                               out, employee, impersonating, bearer token) has no Location to redirect_uri.
  case_non_ascii             — non-ASCII client_id / csrf / token-endpoint values → an error, never a 500.
  case_signed_out            — no session → /login?next=<this exact authorize URL>; no code.
  case_employee_refused      — an employee session → the refusal page; an impersonating owner too.
  case_consent_page          — the owner's page: client, Agency, username, redirect host, escaped; no-store,
                               no framing; Cancel → access_denied with state; loopback → no warning, an https://
                               destination → its host named in a warning above the buttons.
  case_csrf                  — Allow with no / a wrong / another session's CSRF value, or an Origin naming another
                               host → refused, no code; a GET carrying decision=allow approves nothing; an Origin
                               on a second hostname the app answers on is fine.
  case_bearer_mints_nothing  — an access token (no cookie, or beside one) on the authorize GET / Allow POST → no
                               consent page, no code.
  case_code_caps             — one owner flooding Allow keeps at most MAX_GRANTS_PER_OWNER codes (oldest go) and
                               never stops another owner; a full store drops its oldest instead of refusing.
  case_full_flow             — Allow → code → token; it works on tools/call, shows on GET /admin/owner-tokens as
                               `MCP <client> <time>`, expires_in = its lifetime; revoking it cuts access.
  case_code_rules            — single use (replay → invalid_grant), expires, bound to client_id and
                               redirect_uri; a wrong verifier → invalid_grant and the code is burned.
  case_secrets_never_logged  — password, code, verifier, CSRF value and token appear in no log record and no
                               audit row.

Run: ./venv/bin/python service/tests/test_mcp_oauth.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import base64  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import uuid  # noqa: E402
from urllib.parse import parse_qs, unquote, urlencode, urlsplit  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import login_throttle  # noqa: E402
import mcp_api  # noqa: E402
import mcp_oauth as mo  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action  # noqa: E402

IDS = fx.seed_two_agencies()
account_registry.save_meta(IDS["creator_a"], {"id": IDS["creator_a"], "nickname": "creator_a"})
fx.store_blob(IDS["agency_a_owner"], "account", {"agency_name": "Agency <A>"})

BASE = "https://app.example.com"
FWD = {"X-Forwarded-Host": "app.example.com", "X-Forwarded-Proto": "https"}
SAME = {**FWD, "Origin": BASE}
REDIRECT = "http://127.0.0.1:33418/callback"
ANON = _harness.make_client()
A = fx.login_owner("agency_a_owner")
B = fx.login_owner("agency_b_owner")


def _register(uris=(REDIRECT,), name="Claude Code", raw=None):
    body = raw if raw is not None else json.dumps({"client_name": name, "redirect_uris": list(uris)})
    return ANON.post(mo.REGISTER_PATH, content=body, headers={"Content-Type": "application/json", **FWD})


def _client(name="Claude Code", uris=(REDIRECT,)) -> str:
    login_throttle.reset()  # every case registers from the one test address
    r = _register(uris, name)
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _params(cid, challenge, redirect=REDIRECT, **over) -> dict:
    p = {"response_type": "code", "client_id": cid, "redirect_uri": redirect, "code_challenge": challenge,
         "code_challenge_method": "S256", "state": "st-1"}
    p.update(over)
    return {k: v for k, v in p.items() if v is not None}


def _authorize(client, params):
    return client.get(f"{mo.AUTHORIZE_PATH}?{urlencode(params)}", headers=FWD, follow_redirects=False)


def _form(page: str) -> dict:
    return {m[0]: m[1].replace("&amp;", "&").replace("&quot;", '"').replace("&#x27;", "'")
            for m in re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', page)}


def _decide(client, form, decision="allow", headers=SAME):
    return client.post(mo.AUTHORIZE_PATH, content=urlencode({**form, "decision": decision}),
                       headers={"Content-Type": "application/x-www-form-urlencoded", **headers},
                       follow_redirects=False)


def _query(location: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def _code(client, cid, challenge, redirect=REDIRECT) -> str:
    page = _authorize(client, _params(cid, challenge, redirect))
    assert page.status_code == 200, page.text
    r = _decide(client, _form(page.text))
    assert r.status_code == 303 and r.headers["location"].startswith(redirect + "?"), (r.status_code, r.headers)
    q = _query(r.headers["location"])
    assert q["state"] == "st-1", q
    return q["code"]


def _token(code, verifier, cid, redirect=REDIRECT):
    return ANON.post(mo.TOKEN_PATH, content=urlencode({"grant_type": "authorization_code", "code": code,
                                                       "code_verifier": verifier, "client_id": cid,
                                                       "redirect_uri": redirect}),
                     headers={"Content-Type": "application/x-www-form-urlencoded", **FWD})


def _grant_error(r, error="invalid_grant"):
    assert r.status_code == 400 and r.json()["error"] == error, (r.status_code, r.text)
    assert r.headers["cache-control"] == "no-store", r.headers
    assert "access_token" not in r.json(), r.text


def _call(token, name="creators_list"):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}}
    return ANON.post(mcp_api.PATH, content=json.dumps(msg).encode(),
                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}", **FWD})


def _error_page(r, status=400):
    assert r.status_code == status and "location" not in r.headers, (r.status_code, r.headers)
    assert r.headers["content-type"].startswith("text/html") and "Can&#x27;t connect" in r.text, r.text


# ── metadata ───────────────────────────────────────────────────────────────────

def case_metadata() -> None:
    for path in (mo.PRM_PATH, mo.PRM_PATH + mcp_api.PATH):
        r = ANON.get(path, headers=FWD)
        assert r.status_code == 200, r.text
        assert r.json() == {"resource": BASE + "/admin/mcp", "authorization_servers": [BASE],
                            "bearer_methods_supported": ["header"], "resource_name": r.json()["resource_name"]}
    j = ANON.get(mo.AS_PATH, headers=FWD).json()
    assert j == {"issuer": BASE, "authorization_endpoint": BASE + "/auth/oauth/authorize",
                 "token_endpoint": BASE + "/auth/oauth/token", "registration_endpoint": BASE + "/auth/oauth/register",
                 "response_types_supported": ["code"], "grant_types_supported": ["authorization_code"],
                 "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"]}, j
    assert ANON.get(mo.AS_PATH).status_code == 503  # no public address: nothing to name
    saved = server.SHARE_TOKEN
    server.SHARE_TOKEN = "share-secret"
    try:
        assert ANON.get("/admin/accounts").status_code == 401  # the gate is on
        for path in mo.PUBLIC_PATHS:
            assert ANON.get(path, headers=FWD).status_code == 200, path
        assert ANON.get("/.well-known/oauth-authorization-server/x", headers=FWD).status_code == 401
        assert ANON.get("/.well-known/other", headers=FWD).status_code == 401
    finally:
        server.SHARE_TOKEN = saved


# ── registration ───────────────────────────────────────────────────────────────

def case_register() -> None:
    login_throttle.reset()
    r = _register((REDIRECT, "https://app.example.net/cb?x=1", REDIRECT), "  Claude\x00\nCode " + "x" * 80)
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store", r.text
    j = r.json()
    assert j["redirect_uris"] == [REDIRECT, "https://app.example.net/cb?x=1"], j
    assert j["client_name"].startswith("Claude Code x") and len(j["client_name"]) == mo.MAX_NAME, j
    assert j["token_endpoint_auth_method"] == "none" and "client_secret" not in j, j
    assert mo.parse_client_id(j["client_id"]) == mo.Client(j["client_name"], tuple(j["redirect_uris"]))
    assert _register((REDIRECT,), "").json()["client_name"] == mo.NAME_FALLBACK
    for bad in ("javascript:alert(1)", "myapp://cb", "http://example.com/cb", "https://x.example/cb#f",
                "https://user@x.example/cb", "http://127.0.0.1:99999/cb", "https://x.example/c b",
                "https://x.example/" + "a" * mo.MAX_URI, "/relative", "", 7):
        login_throttle.reset()
        r = _register((bad,))
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri", (bad, r.text)
    login_throttle.reset()
    assert _register([f"http://localhost:{p}/cb" for p in range(mo.MAX_URIS + 1)]).json()["error"] == \
        "invalid_redirect_uri"
    assert _register(()).json()["error"] == "invalid_redirect_uri"
    for raw in ("[]", "not json", "{" * 5000):
        assert _register(raw=raw).json()["error"] == "invalid_client_metadata", raw
    assert _register(raw=json.dumps({"redirect_uris": [REDIRECT], "pad": "x" * mo.MAX_FORM})).status_code == 400
    login_throttle.reset()


def case_register_throttled() -> None:
    login_throttle.reset()
    try:
        for _ in range(login_throttle.REGISTER_CAPACITY):
            assert _register().status_code == 201
        r = _register()
        assert r.status_code == 429 and r.headers["retry-after"], (r.status_code, r.text)
        assert _harness.make_client().post("/auth/register", json={"username": "oauth_ok", "password": "pw-oauth-1"}).status_code \
            == 200  # its own bucket: owner sign-up is untouched
    finally:
        login_throttle.reset()


# ── authorize ──────────────────────────────────────────────────────────────────

def case_bad_client_or_redirect() -> None:
    cid = _client()
    _, ch = _pkce()
    payload, sig = cid.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data["r"] = ["https://evil.example/cb"]
    forged = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).rstrip(b"=").decode()
    for bad_cid in (f"{forged}.{sig}", cid + "x", "plain-id", "", None):
        _error_page(_authorize(A, _params(bad_cid, ch, "https://evil.example/cb")))
        _error_page(_authorize(A, _params(bad_cid, ch)))
    for bad in ("https://evil.example/cb", REDIRECT + "/", REDIRECT + "?x=1", "http://127.0.0.1:33419/callback",
                "http://localhost:33418/callback", "", None):
        _error_page(_authorize(A, _params(cid, ch, bad)))
        _error_page(_authorize(ANON, _params(cid, ch, bad)))  # before any login redirect


_BAD_REQUESTS = ({"code_challenge": None}, {"code_challenge_method": None}, {"code_challenge_method": "plain"},
                 {"code_challenge": "short"},
                 {"code_challenge": "é" * 43}, {"response_type": "token"}, {"response_type": None},
                 {"state": "s" * (mo.MAX_STATE + 1)})


def case_pkce_required() -> None:
    cid = _client()
    verifier, ch = _pkce()
    for over in (*_BAD_REQUESTS, {"code_challenge_method": "plain", "code_challenge": verifier},
                 {"code_challenge": ch[:-1]}, {"code_challenge": ch + "!"}):
        for client in (A, ANON):  # signed in or not: the page, no redirect, no login detour
            r = _authorize(client, _params(cid, ch, **over))
            _error_page(r)
            assert "incomplete or not supported" in r.text, (over, r.text)
    assert not mo._grants, mo._grants


def _no_redirect_to(r) -> None:
    """No Location, or only the app's own login page (whose next= names the authorize URL)."""
    loc = r.headers.get("location")
    assert loc is None or loc.startswith("/login?next=%2Fauth%2Foauth%2Fauthorize%3F"), (r.status_code, loc)


def case_no_redirect_before_consent() -> None:
    https = "https://attacker.example/cb"
    cid = _client("Tool", (REDIRECT, https))
    _, ch = _pkce()
    emp = fx.login_chatter("chatter_a")
    tok = _owner_token()
    bearer = _harness.make_client()
    bearer.headers["Authorization"] = f"Bearer {tok}"
    for redirect in (REDIRECT, https):
        for over in (*_BAD_REQUESTS, {}):
            for client in (A, ANON, emp, bearer):
                _no_redirect_to(_authorize(client, _params(cid, ch, redirect, **over)))
        form = _form(_authorize(A, _params(cid, ch, redirect)).text)
        for client in (ANON, emp, bearer):
            _no_redirect_to(_decide(client, form))
        _no_redirect_to(_decide(A, {**form, "csrf": "x"}))  # a bad CSRF value
        _no_redirect_to(_decide(A, form, "maybe"))  # neither button
    assert not mo._grants, mo._grants


def case_signed_out() -> None:
    cid = _client()
    _, ch = _pkce()
    params = _params(cid, ch)
    r = _authorize(ANON, params)
    assert r.status_code == 302 and r.headers["cache-control"].startswith("no-store"), (r.status_code, r.headers)
    loc = r.headers["location"]
    assert loc.startswith("/login?next=") and "code=" not in loc, loc
    back = unquote(loc.removeprefix("/login?next="))
    assert back == f"{mo.AUTHORIZE_PATH}?{urlencode(params)}", back
    assert _query(back) == params
    r = _decide(ANON, {"client_id": cid, "redirect_uri": REDIRECT, "code_challenge": ch, "state": "st-1",
                       "csrf": "x"})
    assert r.status_code == 403 and "location" not in r.headers, (r.status_code, r.headers)


def case_employee_refused() -> None:
    cid = _client()
    _, ch = _pkce()
    emp = fx.login_chatter("chatter_a")
    r = _authorize(emp, _params(cid, ch))
    assert r.status_code == 403 and "location" not in r.headers and "employee login" in r.text, r.text
    assert "Allow" not in r.text, r.text
    master = fx.login_owner("agency_master")
    r = master.post("/admin/impersonate", json={"user_id": IDS["agency_a_owner"],
                                               "admin_password": os.environ["ADMIN_PASSWORD"]})
    assert r.status_code == 200, r.text
    r = _authorize(master, _params(cid, ch))
    assert r.status_code == 403 and mo.IMPERSONATING.split(":")[0] in r.text, (r.status_code, r.text)


def case_consent_page() -> None:
    cid = _client("<b>Tool</b>")
    _, ch = _pkce()
    r = _authorize(A, _params(cid, ch))
    assert r.status_code == 200, r.text
    h = r.headers
    assert h["cache-control"].startswith("no-store") and h["x-frame-options"] == "DENY", h
    assert "frame-ancestors 'none'" in h["content-security-policy"], h
    t = r.text
    assert "Allow &lt;b&gt;Tool&lt;/b&gt; to connect to Agency &lt;A&gt;?" in t and "<b>Tool" not in t, t
    assert "agency_a_owner" in t and "127.0.0.1:33418" in t and str(90) in t, t
    assert 'name="viewport"' in t, t
    form = _form(t)
    assert set(form) == {"client_id", "redirect_uri", "code_challenge", "state", "csrf"}, form
    assert 'class="warn"' not in t, t  # loopback: the app on this computer, no warning
    r = _decide(A, form, "deny")
    assert r.status_code == 303, r.text
    assert _query(r.headers["location"]) == {"error": "access_denied", "state": "st-1"}
    https = "https://tools.example.net/cb"
    t = _authorize(A, _params(_client("Tool", (https,)), ch, https)).text
    warn = re.search(r'<p class="warn">(.*?)</p>', t)
    assert warn and "tools.example.net" in warn.group(1) and "started this yourself" in warn.group(1), t
    assert t.index('class="warn"') < t.index("<form"), t  # above the buttons


def case_csrf() -> None:
    cid = _client()
    _, ch = _pkce()
    form = _form(_authorize(A, _params(cid, ch)).text)
    other = _form(_authorize(B, _params(cid, ch)).text)
    for f, headers, client in (({k: v for k, v in form.items() if k != "csrf"}, SAME, A),
                               ({**form, "csrf": "x" + form["csrf"][1:]}, SAME, A),
                               ({**form, "csrf": other["csrf"]}, SAME, A),  # B's value on A's session
                               (form, SAME, B),  # A's value on B's session
                               ({**form, "state": "other"}, SAME, A),  # a parameter changed after signing
                               ({**form, "code_challenge": _pkce()[1]}, SAME, A),
                               (form, {**FWD, "Origin": "https://evil.example"}, A),
                               (form, {**FWD, "Origin": "https://app.example.com.evil.example"}, A),
                               (form, {**FWD, "Origin": "null"}, A)):
        r = _decide(client, f, headers=headers)
        assert r.status_code == 403 and "location" not in r.headers, (f, headers, r.status_code, r.headers)
    r = A.get(f"{mo.AUTHORIZE_PATH}?{urlencode({**_params(cid, ch), 'decision': 'allow', 'csrf': form['csrf']})}",
              headers=FWD, follow_redirects=False)
    assert r.status_code == 200 and "location" not in r.headers, r.status_code  # the page again, no code
    assert not mo._grants, mo._grants
    r = _decide(A, form, headers=FWD)  # no Origin header (an older browser): the CSRF value alone decides
    assert r.status_code == 303 and "code" in _query(r.headers["location"]), r.headers
    second = {"X-Forwarded-Host": "app2.example.org", "X-Forwarded-Proto": "https", "Origin": "https://app2.example.org"}
    saved = os.environ.get("APP_PUBLIC_URL")
    os.environ["APP_PUBLIC_URL"] = BASE  # the configured address names the other hostname
    try:
        r = _decide(A, form, headers=second)  # a second hostname the app answers on
    finally:
        os.environ.pop("APP_PUBLIC_URL") if saved is None else os.environ.update(APP_PUBLIC_URL=saved)
    assert r.status_code == 303 and "code" in _query(r.headers["location"]), (r.status_code, r.text)
    mo.reset()


def _owner_token() -> str:
    r = A.post("/admin/owner-tokens", json={"name": "oauth-bearer-test"}, headers=SAME)
    assert r.status_code == 200 and r.json()["token"], r.text
    return r.json()["token"]


def case_bearer_mints_nothing() -> None:
    cid = _client()
    _, ch = _pkce()
    form = _form(_authorize(A, _params(cid, ch)).text)
    tok = _owner_token()
    bare = _harness.make_client()
    bare.headers["Authorization"] = f"Bearer {tok}"
    beside = fx.login_owner("agency_a_owner")  # a valid owner cookie too: the token wins, never the cookie
    beside.headers["Authorization"] = f"Bearer {tok}"
    for client in (bare, beside):
        r = _authorize(client, _params(cid, ch))
        assert "location" not in r.headers and "Allow" not in r.text and "csrf" not in r.text, (r.status_code, r.text)
        for decision in ("allow", "deny"):
            r = _decide(client, form, decision)
            assert r.status_code in (401, 403) and "location" not in r.headers, (r.status_code, r.headers)
    assert not mo._grants, mo._grants


def case_code_caps() -> None:
    mo.reset()
    cid = _client()
    _, ch = _pkce()
    form_a = _form(_authorize(A, _params(cid, ch)).text)
    codes = [_query(_decide(A, form_a).headers["location"])["code"] for _ in range(50)]  # owner A floods Allow
    a_codes = [g for g in mo._grants.values() if g.owner == IDS["agency_a_owner"]]
    assert len(a_codes) == mo.MAX_GRANTS_PER_OWNER == len(mo._grants), len(mo._grants)
    assert set(mo._grants) == {mo._digest(c) for c in codes[-mo.MAX_GRANTS_PER_OWNER:]}  # the newest kept
    verifier, ch_b = _pkce()
    assert _token(_code(B, cid, ch_b), verifier, cid).status_code == 200  # owner B unaffected
    saved = mo.MAX_GRANTS
    mo.MAX_GRANTS = mo.MAX_GRANTS_PER_OWNER  # the store full of A's codes
    try:
        oldest = next(iter(mo._grants))
        code_b = _code(B, cid, ch_b)  # not refused: the oldest code goes
        assert len(mo._grants) == mo.MAX_GRANTS and oldest not in mo._grants, mo._grants
        assert _token(code_b, verifier, cid).status_code == 200
    finally:
        mo.MAX_GRANTS = saved
        mo.reset()


def case_non_ascii() -> None:
    cid = _client()
    verifier, ch = _pkce()
    for bad_cid in ("é.é", cid.split(".")[0] + ".é", "é"):
        _error_page(_authorize(A, _params(bad_cid, ch)))
        _error_page(_decide(A, {"client_id": bad_cid, "redirect_uri": REDIRECT, "code_challenge": ch,
                                "state": "st-1", "csrf": "x"}))
    form = _form(_authorize(A, _params(cid, ch)).text)
    r = _decide(A, {**form, "csrf": "é" * len(form["csrf"])})
    assert r.status_code == 403 and "location" not in r.headers, (r.status_code, r.text)
    code = _code(A, cid, ch)
    _grant_error(_token(code, "é" * 50, cid))  # verifier
    _grant_error(_token("é", verifier, cid))  # code
    _grant_error(_token(_code(A, cid, ch), verifier, "é.é"))  # client_id
    assert not mo._grants, mo._grants


# ── token ──────────────────────────────────────────────────────────────────────

def case_full_flow() -> None:
    cid = _client("Claude Code")
    verifier, ch = _pkce()
    r = _token(_code(A, cid, ch), verifier, cid)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    j = r.json()
    assert set(j) == {"access_token", "token_type", "expires_in"} and j["token_type"] == "Bearer", j
    assert j["access_token"].startswith("ifw_") and j["expires_in"] == 90 * 86400, j
    tok = j["access_token"]
    res = _call(tok).json()["result"]
    assert res["isError"] is False, res
    assert [c["id"] for c in res["structuredContent"]["accounts"]] == [IDS["creator_a"]], res
    rows = A.get("/admin/owner-tokens").json()["tokens"]
    row = rows[0]
    assert re.fullmatch(r"MCP Claude Code \d{4}-\d\d-\d\d \d\d:\d\d:\d\d", row["name"]), row
    assert tok.endswith(row["hint"][-4:]) and row["revoked_at"] is None, row
    assert A.delete(f"/admin/owner-tokens/{row['id']}").status_code == 200
    r = _call(tok)
    assert r.status_code == 401 and "resource_metadata=" in r.headers["www-authenticate"], (r.status_code, r.headers)


def case_code_rules() -> None:
    cid, cid2 = _client(), _client("Other", (REDIRECT, "http://localhost:5555/cb"))
    verifier, ch = _pkce()
    code = _code(A, cid, ch)
    assert _token(code, verifier, cid).status_code == 200
    _grant_error(_token(code, verifier, cid))  # replay
    code = _code(A, cid, ch)
    _grant_error(_token(code, _pkce()[0], cid))  # wrong verifier
    _grant_error(_token(code, verifier, cid))  # …and the code is gone
    code = _code(A, cid, ch)
    _grant_error(_token(code, verifier, cid2))  # another client
    code = _code(A, cid2, ch)
    _grant_error(_token(code, verifier, cid2, "http://localhost:5555/cb"))  # another of its redirect URIs
    _grant_error(_token(_code(A, cid, ch), verifier, cid, REDIRECT + "/"))
    _grant_error(_token("nope", verifier, cid))
    _grant_error(_token(_code(A, cid, ch), "short", cid))
    code = _code(A, cid, ch)
    real = mo._clock
    mo._clock = lambda: real() + mo.CODE_TTL_S + 1
    try:
        _grant_error(_token(code, verifier, cid))  # expired
    finally:
        mo._clock = real
    r = ANON.post(mo.TOKEN_PATH, content=urlencode({"grant_type": "refresh_token", "refresh_token": "x"}),
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    _grant_error(r, "unsupported_grant_type")
    r = ANON.post(mo.TOKEN_PATH, content="code=a&code=b&grant_type=authorization_code",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    _grant_error(r, "invalid_request")
    assert not mo._grants, mo._grants


# ── secrets ────────────────────────────────────────────────────────────────────

class _Grab(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        # The DB driver's own DEBUG trace prints the users INSERT (test_mcp_auth's note); every other logger counts.
        if not record.name.startswith(("aiosqlite", "sqlalchemy")):
            self.lines.append(record.getMessage() + repr(record.args))


async def _audit_rows() -> list[str]:
    async with get_session() as s:
        return [f"{a} {p}" for a, p in (await s.execute(select(Action.action, Action.payload_json))).all()]


def case_secrets_never_logged() -> None:
    grab, root = _Grab(), logging.getLogger()
    saved = root.level
    root.addHandler(grab)
    root.setLevel(logging.DEBUG)
    password = f"pw-oauth-{uuid.uuid4().hex[:8]}"
    try:
        c = _harness.make_client()
        assert c.post("/auth/register", json={"username": "oauth_logs", "password": password}).status_code == 200
        cid = _client()
        verifier, ch = _pkce()
        form = _form(_authorize(c, _params(cid, ch)).text)
        r = _decide(c, form)
        code = _query(r.headers["location"])["code"]
        tok = _token(code, verifier, cid).json()["access_token"]
        assert _call(tok).json()["result"]["isError"] is False
        _grant_error(_token(code, verifier, cid))
    finally:
        root.removeHandler(grab)
        root.setLevel(saved)
    session = c.cookies.get("chatterly_session")
    rows = asyncio.run(_audit_rows())
    for s in (password, code, verifier, form["csrf"], tok, session):
        assert s and not any(s in line for line in grab.lines), s
        assert not any(s in row for row in rows), s
    assert not any("/auth/oauth/" in row for row in rows), rows


_harness.run()
