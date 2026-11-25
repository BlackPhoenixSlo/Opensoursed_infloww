#!/usr/bin/env python3
"""test_of_live_window.py — the desktop Go live window's session read (ticket 127, D28).

`POST /api/of/live-window/session` hands the desktop's main process a Creator's
OnlyFans cookies (never Cloudflare's) and x_bc, for a signed-in owner of that
Creator; every chatter is refused, whatever their role grants. No captured
session answers `{"session": null}` (the desktop's login-page mode); a broken
one stays a 503. Both routes are 404 while OF_LIVE_WINDOW_ENABLED is off. The
pooled client is faked (`of_live_window._client_for`): no session file is read,
no OF is called.

Run:  ./venv/bin/python service/tests/test_of_live_window.py
"""
import _harness  # noqa: F401 — MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from http.cookiejar import CookieJar  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import of_live_window  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Action  # noqa: E402
from of_cookie_events import cookie_from_row  # noqa: E402

_IDS = fx.seed_two_agencies()
A, B = _IDS["creator_a"], _IDS["creator_b"]
SWITCH = "OF_LIVE_WINDOW_ENABLED"
PATH = "/api/of/live-window/session"
SESS, XBC, CF = "sess-secret-4d2e", "xbc-secret-81aa", "cf-secret-77"
FAR = int(time.time()) + 86400

_ROWS = [
    {"name": "auth_id", "value": "1000001", "domain": ".onlyfans.com", "path": "/", "secure": True},
    {"name": "sess", "value": SESS, "domain": ".onlyfans.com", "path": "/", "secure": True,
     "httpOnly": True, "expires": FAR},
    {"name": "fp", "value": "fp-1", "domain": "onlyfans.com", "path": "/", "secure": True, "hostOnly": True},
    {"name": "__cf_bm", "value": CF, "domain": ".onlyfans.com", "path": "/", "secure": True, "httpOnly": True},
    {"name": "cf_clearance", "value": CF, "domain": ".onlyfans.com", "path": "/", "secure": True},
    {"name": "_cfuvid", "value": CF, "domain": ".onlyfans.com", "path": "/", "secure": True},
    {"name": "other", "value": "x", "domain": ".example.com", "path": "/", "secure": True},
]


# account id -> the HTTPException `_load_client` would raise for it (no session file, a broken one).
_LOAD_ERRORS: dict = {}


def _fake_client(aid: str):
    if aid in _LOAD_ERRORS:
        raise _LOAD_ERRORS[aid]
    jar = CookieJar()
    for row in _ROWS:
        jar.set_cookie(cookie_from_row(row))
    return SimpleNamespace(account_id=aid, x_bc=XBC, http=SimpleNamespace(cookies=SimpleNamespace(jar=jar)))


of_live_window._client_for = _fake_client


@contextlib.contextmanager
def _switch(value):
    old = os.environ.get(SWITCH)
    if value is None:
        os.environ.pop(SWITCH, None)
    else:
        os.environ[SWITCH] = value
    of_live_window._reads.clear()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(SWITCH, None)
        else:
            os.environ[SWITCH] = old


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage() + " " + str(record.__dict__))


def _load_error(error):
    from fastapi import HTTPException
    return HTTPException(status_code=503, detail={"error": error, "account_id": A, "message": "x"})


@contextlib.contextmanager
def _load_fails(error):
    _LOAD_ERRORS[A] = _load_error(error)
    try:
        yield
    finally:
        _LOAD_ERRORS.pop(A, None)


@contextlib.contextmanager
def _roles(blob):
    fx.store_blob(_IDS["agency_a_owner"], "roles", blob)
    try:
        yield
    finally:
        fx.store_blob(_IDS["agency_a_owner"], "roles", {})


def _post(client, aid):
    return client.post(PATH, headers={"X-Account-Id": aid})


def case_switch_defaults_off():
    import runtime_switches
    os.environ.pop(SWITCH, None)
    assert runtime_switches.BY_NAME[SWITCH].default is False
    assert runtime_switches.on(SWITCH) is False


def case_off_both_routes_404():
    owner = fx.login_owner("agency_a_owner")
    for value in (None, "0", ""):
        with _switch(value):
            assert owner.get("/api/of/live-window").status_code == 404
            assert _post(owner, A).status_code == 404


def case_on_probe_answers_enabled():
    owner = fx.login_owner("agency_a_owner")
    with _switch("1"):
        r = owner.get("/api/of/live-window")
        assert r.status_code == 200, r.text
        assert r.json() == {"enabled": True}


def case_anonymous_401():
    anon = _harness.make_client()
    with _switch("1"):
        r = _post(anon, A)
        assert r.status_code == 401, r.status_code
        assert SESS not in r.text and XBC not in r.text


def case_out_of_scope_403():
    with _switch("1"):
        for client in (fx.login_owner("agency_a_owner"), fx.login_chatter("chatter_a")):
            r = _post(client, B)
            assert r.status_code == 403, r.status_code
            assert SESS not in r.text and XBC not in r.text


def case_missing_account_400():
    owner = fx.login_owner("agency_a_owner")
    with _switch("1"):
        assert owner.post(PATH).status_code == 400
        assert owner.post(PATH, headers={"X-Account-Id": "abc"}).status_code == 400


def case_owner_access_token_refused():
    owner = fx.login_owner("agency_a_owner")
    token = fx.mint_token(owner)
    bare = _harness.make_client()
    with _switch("1"):
        r = bare.post(PATH, headers={"X-Account-Id": A, "Authorization": f"Bearer {token}"})
        assert r.status_code == 403, (r.status_code, r.text)
        assert "access token" in r.text, r.text
        assert SESS not in r.text


def case_chatter_with_go_live_page_403():
    # Enforcement off grants every chatter every page, Go live included
    # (permissions.py): the page alone never hands out a Creator's session.
    with _roles({"enforce": False}), _switch("1"):
        chatter = fx.login_chatter("chatter_a")
        # The page is granted, yet the probe refuses too: a chatter's Start stays disabled.
        assert chatter.get("/api/of/live-window").status_code == 403
        r = _post(chatter, A)
        assert r.status_code == 403, (r.status_code, r.text)
        assert "owners only" in r.text, r.text
        assert SESS not in r.text and XBC not in r.text


def case_no_session_file_answers_null():
    owner = fx.login_owner("agency_a_owner")
    with _switch("1"), _load_fails("no_session"):
        r = _post(owner, A)
        assert r.status_code == 200, (r.status_code, r.text)
        assert r.json() == {"session": None}
        assert r.headers["cache-control"] == "no-store"


def case_broken_session_stays_503():
    owner = fx.login_owner("agency_a_owner")
    for error in ("incomplete_signing_rules", "bad_session"):
        with _switch("1"), _load_fails(error):
            r = _post(owner, A)
            assert r.status_code == 503, (error, r.status_code)
            assert "session" not in r.json() or r.json().get("session") is not None


def case_in_scope_session_without_cloudflare_no_store():
    with _switch("1"):
        for client in (fx.login_owner("agency_a_owner"),):
            r = _post(client, A)
            assert r.status_code == 200, (r.status_code, r.text)
            assert r.headers["cache-control"] == "no-store"
            body = r.json()["session"]
            assert body["x_bc"] == XBC
            names = [c["name"] for c in body["cookies"]]
            assert sorted(names) == ["auth_id", "fp", "sess"], names
            assert CF not in r.text
            by = {c["name"]: c for c in body["cookies"]}
            assert by["sess"] == {"name": "sess", "value": SESS, "domain": ".onlyfans.com", "path": "/",
                                  "secure": True, "httpOnly": True, "expires": FAR}
            assert by["fp"]["domain"] == "onlyfans.com"   # host-only stays host-only
            assert by["auth_id"]["expires"] is None



@contextlib.contextmanager
def _platform(aid, key):
    import accounts
    saved = accounts.load_meta(aid)
    meta = {k: v for k, v in (saved or {"id": aid}).items() if k != "platform"}
    if key is not None:
        meta["platform"] = key
    accounts.save_meta(aid, meta)
    try:
        yield
    finally:
        if saved is None:
            (accounts.account_dir(aid) / "meta.json").unlink()
        else:
            accounts.save_meta(aid, saved)


def case_only_a_fansly_creator_is_refused_whatever_the_key():
    owner = fx.login_owner("agency_a_owner")
    for key, want in ((None, 200), ("onlyfans", 200), ("myspace", 200), ("fansly", 409)):
        with _switch("1"), _platform(A, key):
            r = _post(owner, A)
        assert r.status_code == want, (key, r.status_code, r.text)
        if want == 409:
            assert r.json()["detail"] == "Go live is for OnlyFans Creators", r.text

def case_get_is_not_the_session():
    owner = fx.login_owner("agency_a_owner")
    with _switch("1"):
        r = owner.get(PATH, headers={"X-Account-Id": A})
        assert r.status_code == 405, r.status_code


def case_rate_limited():
    owner = fx.login_owner("agency_a_owner")
    with _switch("1"):
        codes = [_post(owner, A).status_code for _ in range(of_live_window.RATE_MAX + 1)]
        assert codes[:-1] == [200] * of_live_window.RATE_MAX, codes
        assert codes[-1] == 429, codes


def case_no_secret_in_logs_or_audit():
    cap = _Capture()
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(cap)
    root.setLevel(logging.DEBUG)
    try:
        with _switch("1"):
            r = _post(fx.login_owner("agency_a_owner"), A)
            assert r.status_code == 200
    finally:
        root.removeHandler(cap)
        root.setLevel(old_level)
    joined = "\n".join(cap.lines)
    assert "live_window_session" in joined, "the read is logged (ids only)"
    for secret in (SESS, XBC, CF):
        assert secret not in joined, secret

    async def _rows():
        async with get_session() as s:
            return (await s.execute(select(Action).where(Action.action == f"POST {PATH}"))).scalars().all()
    rows = asyncio.run(_rows())
    assert rows, "the read leaves an audit row"
    for row in rows:
        blob = f"{row.payload_json} {row.target_id} {row.target_type}"
        for secret in (SESS, XBC, CF):
            assert secret not in blob, secret


if __name__ == "__main__":
    _harness.run()
