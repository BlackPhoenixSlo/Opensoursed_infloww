#!/usr/bin/env python3
"""
Served Browserbase login (service/remote_login.py, remote_login_api.py).

No browser and NO network: `_bb_request` / `urlopen` / the page are faked.

  case_backend_selector:
      start_login defaults to "local", which is refused up front
      (BackendUnavailable); an unknown backend is a ValueError.
  case_env_and_proxy_fail_loud:
      missing BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID, an unknown proxy
      choice or a custom proxy without a label raise before any session exists.
  case_session_payload_shape:
      the create body asks for Browserbase's managed proxies (`proxies: true`),
      projectId from env, solveCaptchas False, a 1280x800 viewport (readable
      live view on a phone); our proxy is never in it.
  case_form_waited_filled_verified:
      the typing waits for OnlyFans' late-rendered form (it is not there at
      domcontentloaded: the live bug left the email empty), declines the
      optional cookies, fills email then password, verifies both, then clicks
      LOG IN.
  case_swallowed_fill_is_retyped:
      a fill the page swallows (the field still reads empty) is retyped key by
      key and verified.
  case_form_never_appears_fails_fast:
      no login form: the job fails with a clear error well inside the window,
      instead of sitting on "entering credentials" until the session expires;
      nothing is typed and the password is never in the error.
  case_field_never_takes_value_fails:
      a field that never holds what was typed fails with which field; the
      password field is not touched after the email failed.
  case_managed_login_binds_proxy:
      a served job on a managed-proxy session: ONE create, the live view is
      that session's, OnlyFans loads, the chosen proxy is bound before the
      session is persisted, the message says the proxy is attached, and the
      session is released.
  case_create_refused_fails_loud:
      any refused create (402/400/401/429/5xx) fails the job after ONE create
      call with a clear "couldn't start a Browserbase session" error; no retry.
  case_nav_error_fails_fast:
      a failed load of OnlyFans fails the job at once with "couldn't open
      OnlyFans", the body never runs, and the session is released.
  case_live_server_is_the_serving_module:
      uvicorn serves `service.server`; the capture's post-bootstrap hooks (the
      link to the signed-in user) must run on THAT module, not on a second copy
      a bare `import server` would execute.
  case_backend_error_scrubbed:
      any backend error reaches the job with the OF password scrubbed.
  case_public_hides_secrets:
      the status never carries email/password; the live view only while live.
  case_request_from_capture:
      the interceptor snapshot becomes paste-curl's parsed shape with the
      x-relay-* headers the extension adds.
  case_capture_binds_before_persist:
      the flow's proxy is bound to the captured user-id with the paste path's
      registry calls (Inflowwww proxy: assign_pool; custom: assign_account;
      No proxy: nothing), then from_request persists, then the bootstrap hooks
      run; a failed bind persists nothing.
  case_api_proxy_choice:
      no proxy given: the Inflowwww proxy when the relay has a pool, else none;
      "infloww" without a pool 409s; a custom label is checked for visibility
      (another user's or a pool label 404s); unknown choice / custom without a
      label 400.
  case_api_gates:
      400 missing password (never a 422 echoing it), 400 unknown backend, 501 local, 404 unknown proxy, 503 env missing,
      404 unknown job, 403 another principal's job; /admin/login is audit-
      skipped and chatter-blocked.
  case_otp_code_signs_in:
      start over HTTP → login form typed → OnlyFans' 2FA prompt puts the job
      in "otp" → POST /otp with the code → the job's own thread types it into
      the 2FA field and presses Enter → auth_id → capture → done. The code is
      in no status, response or log line.
  case_otp_wrong_code_retries:
      a code OnlyFans does not take leaves the job in "otp" with OTP_REJECTED
      after OTP_VERIFY_S; while it is checked, another code is 409; a second
      code is typed over it and signs in.
  case_otp_prompt_back_within_verify_window:
      the 2FA prompt goes away and comes back before OTP_VERIFY_S: the job is
      back in "otp" asking for the code (not stuck in "typing").
  case_enter_otp_one_attempt_cancel_and_form_scope:
      _enter_otp: one fill with short timeouts (a swallowed fill is "couldn't
      type", no retyping); a cancel between fill and submit is seen before the
      submit; the fallback submit is the 2FA field's own form's button, never
      the page's first submit button (the login form's).
  case_otp_only_a_visible_field:
      a stale hidden 2FA input is no prompt (_detect_otp False) and never the
      field the code is typed into: every _OTP_FIELD selector is `:visible`.
  case_otp_code_spaces_and_dashes:
      "123 456" / "123-456" / " 1234-5678 " are accepted as their digits;
      anything else with them (letters, dots, too few digits) is 400, never
      echoed.
  case_otp_scrubbed_from_job_error:
      an exception whose message carries the submitted code (Playwright echoes
      filled values) reaches the job error and the log as ***.
  case_api_otp_gates:
      POST /otp: 404 unknown job, 403 another principal's job, 409 a job not on
      the 2FA prompt, 400 a code that is not 6-8 digits or a body that is not
      {"code": "<string>"} (never echoed, nor on malformed JSON); a good code
      lands in the job's slot, the status says it is being checked, a second
      code is 409 until the job asks again; leaving the prompt or failing
      empties the slot.

Run: ./venv/bin/python service/tests/test_remote_login_browserbase.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"
_harness.bootstrap()
client = _harness.make_client()

import auth  # noqa: E402
import chatters  # noqa: E402
import employees  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import remote_login as rl  # noqa: E402

_TMP = Path(tempfile.gettempdir()) / f"bb_login_test_{uuid.uuid4().hex}"
_TMP.mkdir(parents=True, exist_ok=True)
proxy_registry.REGISTRY_PATH = _TMP / "proxies.json"
proxy_registry.REGISTRY_PATH.write_text(json.dumps({"proxies": []}))

PROXY_PW = "pr0xyPW"
OF_PW = "hunter2-of"
_ENV = ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID")


def _set_env(key="bb_test_key", project="proj-xyz"):
    for k, v in zip(_ENV, (key, project)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _job(**kw):
    now = time.time()
    base = dict(id=uuid.uuid4().hex, email="e@x.com", principal=None,
                created_at=now, expires_at=now + 30)
    base.update(kw)
    return rl.RemoteLoginJob(**base)


def _raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc as e:
        return e
    raise AssertionError(f"expected {exc.__name__}")


def case_backend_selector():
    import inspect
    assert inspect.signature(rl.start_login).parameters["backend"].default == rl.BACKEND_LOCAL
    _set_env()
    kw = dict(email="a@b", password="p", principal=None)
    _raises(rl.BackendUnavailable, rl.start_login, **kw)
    _raises(ValueError, rl.start_login, **kw, backend="nope")


def case_env_and_proxy_fail_loud():
    _set_env(key=None, project=None)
    assert "BROWSERBASE_API_KEY" in str(_raises(RuntimeError, rl._bb_create_session))
    _set_env(project=None)
    assert "BROWSERBASE_PROJECT_ID" in str(_raises(RuntimeError, rl._bb_create_session))
    _set_env()
    _raises(ValueError, rl.start_login, email="a@b", password="p", proxy=rl.PROXY_CUSTOM,
            proxy_label="", principal=None, backend=rl.BACKEND_BROWSERBASE)
    _raises(ValueError, rl.start_login, email="a@b", password="p", proxy="bogus",
            principal=None, backend=rl.BACKEND_BROWSERBASE)
    assert not rl._jobs, "no job may be registered by a refused start"


def case_session_payload_shape():
    _set_env()
    seen = {}
    orig = rl._bb_request

    def _fake(path, method="GET", body=None):
        seen.update(path=path, method=method, body=body)
        return {"id": "s1", "connectUrl": "wss://connect.browserbase.com/x"}

    rl._bb_request = _fake
    try:
        session = rl._bb_create_session()
    finally:
        rl._bb_request = orig
    assert session["id"] == "s1"
    assert (seen["path"], seen["method"]) == ("/sessions", "POST")
    assert seen["body"] == {"projectId": "proj-xyz", "proxies": True,
                            "browserSettings": {"solveCaptchas": False,
                                                 "viewport": {"width": 1280, "height": 800}}}, seen["body"]


_BB = "https://api.browserbase.com/v1"


class _Resp:
    def __init__(self, obj):
        self._raw = json.dumps(obj).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _fake_browserbase(create_status=None, create_body=b"{}"):
    """A fake urlopen. A session create answers `create_status` (None:
    accepted, session s1); the live view and the release succeed. Records
    every call."""
    calls = []

    def _urlopen(req, timeout=None):
        body = json.loads(req.data.decode()) if req.data else None
        calls.append((req.get_method(), req.full_url, body))
        if req.full_url == f"{_BB}/sessions":
            if create_status is None:
                return _Resp({"id": "s1", "connectUrl": "wss://connect.browserbase.com/s1"})
            raise urllib.error.HTTPError(req.full_url, create_status, "refused", {},
                                         io.BytesIO(create_body))
        if req.full_url.endswith("/debug"):
            sid = req.full_url.split("/")[-2]
            return _Resp({"debuggerFullscreenUrl": f"https://www.browserbase.com/devtools-fullscreen/{sid}"})
        return _Resp({})

    return calls, _urlopen


# connectUrl → the error its first page.goto raises (None: it loads).
_NAV_ERRORS: dict[str, str | None] = {}
_GOTOS: list[str] = []


class _FakePage:
    def __init__(self, cdp_url):
        self.cdp_url = cdp_url

    def goto(self, url, **_k):
        _GOTOS.append(f"{self.cdp_url.rsplit('/', 1)[-1]} {url}")
        err = _NAV_ERRORS.get(self.cdp_url)
        if err:
            raise Exception(f"Page.goto: {err} at {url}\nCall log: ...")


class _FakeBrowserCtx:
    def __init__(self, cdp_url):
        self.pages = [_FakePage(cdp_url)]

    def add_init_script(self, _js):
        return None


class _FakeBrowser:
    def __init__(self, cdp_url):
        self.contexts = [_FakeBrowserCtx(cdp_url)]

    def close(self):
        return None


class _FakePlaywright:
    class chromium:  # noqa: N801 — mirrors playwright's attribute
        @staticmethod
        def connect_over_cdp(url):
            return _FakeBrowser(url)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _with_fakes(urlopen, fn):
    """Run fn() with urlopen and playwright.sync_api faked (no network, no browser)."""
    import importlib.machinery
    import sys
    import types
    fake_mod = types.ModuleType("playwright.sync_api")
    fake_mod.sync_playwright = _FakePlaywright
    saved = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}
    sys.modules["playwright"] = types.ModuleType("playwright")
    # a spec, so the start route's find_spec("playwright") sees it installed
    sys.modules["playwright"].__spec__ = importlib.machinery.ModuleSpec("playwright", None)
    sys.modules["playwright.sync_api"] = fake_mod
    orig = rl.urllib.request.urlopen
    rl.urllib.request.urlopen = urlopen
    try:
        return fn()
    finally:
        rl.urllib.request.urlopen = orig
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _persist_fakes(order):
    import server
    import session_bootstrap
    orig = (proxy_registry.assign_account, proxy_registry.assign_pool,
            session_bootstrap.from_request, server.post_bootstrap_hooks)
    proxy_registry.assign_account = lambda label, aid: order.append(("bind", label, aid))
    proxy_registry.assign_pool = lambda aid: order.append(("pool", aid)) or ({}, False)
    session_bootstrap.from_request = lambda parsed, **kw: (
        order.append(("persist", parsed["headers"]["user-id"], kw.get("nickname")))
        or Path("/x/accounts/777/session_T.json"))
    server.post_bootstrap_hooks = lambda aid: order.append(("hooks", aid))

    def restore():
        (proxy_registry.assign_account, proxy_registry.assign_pool,
         session_bootstrap.from_request, server.post_bootstrap_hooks) = orig
    return restore


def case_managed_login_binds_proxy():
    _set_env()
    _NAV_ERRORS.clear()
    _GOTOS.clear()
    order, seen = [], {}
    restore = _persist_fakes(order)
    calls, urlopen = _fake_browserbase()
    job = _job(proxy=rl.PROXY_CUSTOM, proxy_label="hu-1")

    def _body(page, ctx):
        seen["live"] = job.public()  # mid-job status, as the card polls it
        rl._capture_and_persist(job, _Page(), _Ctx())

    try:
        _with_fakes(urlopen, lambda: rl._serve(job, secrets=(OF_PW,), body=_body))
    finally:
        restore()

    assert job.state == rl.STATE_DONE, (job.state, job.error)
    assert seen["live"]["live_view_url"].endswith("/s1"), seen["live"]
    assert seen["live"]["message"] == "browser ready", seen["live"]
    assert "proxy_fallback" not in seen["live"]
    assert job.message == "session captured; proxy hu-1 attached for all later traffic", job.message
    assert order == [("bind", "hu-1", "777"), ("persist", "777", None), ("hooks", "777")], order
    assert _GOTOS == [f"s1 {rl.OF_HOME}"], _GOTOS
    creates = [b for m, u, b in calls if (m, u) == ("POST", f"{_BB}/sessions")]
    assert creates == [{"projectId": "proj-xyz", "proxies": True,
                        "browserSettings": {"solveCaptchas": False,
                                                 "viewport": {"width": 1280, "height": 800}}}], creates
    assert ("POST", f"{_BB}/sessions/s1", {"projectId": "proj-xyz", "status": "REQUEST_RELEASE"}) in calls


def case_create_refused_fails_loud():
    _set_env()
    for status, body in ((402, b'{"message":"Proxies are not included in your plan"}'),
                         (400, b'{"message":"projectId is invalid"}'),
                         (401, b'{"message":"Invalid API key"}'),
                         (429, b'{"message":"too many sessions"}'),
                         (500, b'{"message":"internal error"}')):
        calls, urlopen = _fake_browserbase(create_status=status, create_body=body)
        job, ran = _job(), []
        _with_fakes(urlopen, lambda: rl._serve(job, secrets=(OF_PW,), body=lambda p, c: ran.append(1)))
        assert job.state == rl.STATE_ERROR, (status, job.state)
        assert "couldn't start a Browserbase session on its managed proxies" in job.error, job.error
        assert f"HTTP {status}" in job.error, (status, job.error)
        assert not ran and len(calls) == 1, (status, calls)  # one create, no retry


def case_nav_error_fails_fast():
    _set_env()
    for err in ("net::ERR_NAME_NOT_RESOLVED", "net::ERR_TUNNEL_CONNECTION_FAILED",
                "Timeout 45000ms exceeded."):
        _NAV_ERRORS.clear()
        _NAV_ERRORS["wss://connect.browserbase.com/s1"] = err
        calls, urlopen = _fake_browserbase()
        job, ran = _job(), []
        t0 = time.monotonic()
        try:
            _with_fakes(urlopen, lambda: rl._serve(job, secrets=(OF_PW,), body=lambda p, c: ran.append(1)))
        finally:
            _NAV_ERRORS.clear()
        assert time.monotonic() - t0 < 5, "must fail fast, not wait out the job window"
        assert job.state == rl.STATE_ERROR and "couldn't open OnlyFans" in job.error, (err, job.error)
        assert not ran
        creates = [u for m, u, _b in calls if (m, u) == ("POST", f"{_BB}/sessions")]
        released = [u for m, u, b in calls if b and b.get("status") == "REQUEST_RELEASE"]
        assert len(creates) == 1 and released == [f"{_BB}/sessions/s1"], (err, calls)


def case_backend_error_scrubbed():
    orig = rl._bb_create_session

    def _boom():
        raise RuntimeError(f"session could not start (pw={OF_PW})")

    rl._bb_create_session = _boom
    try:
        job = _job()
        rl._serve(job, secrets=(OF_PW,), body=lambda p, c: None)
    finally:
        rl._bb_create_session = orig
    assert job.is_terminal() and job.state == rl.STATE_ERROR
    assert "could not start" in job.message
    assert OF_PW not in job.message and "***" in job.message


def case_public_hides_secrets():
    j = _job(principal="u1")
    j.live_view_url = "https://www.browserbase.com/devtools-fullscreen/x"
    pub = j.public()
    assert "password" not in pub and "email" not in pub and "connectUrl" not in json.dumps(pub)
    assert pub["live_view_url"] and pub["state"] == rl.STATE_STARTING
    j.fail("boom")
    assert j.public()["live_view_url"] is None
    j.set_state(rl.STATE_DONE)  # a terminal job stays terminal
    assert j.state == rl.STATE_ERROR


def case_request_from_capture():
    cap = {"url": "https://onlyfans.com/api2/v2/chats?limit=10",
           "headers": {"user-id": "123", "x-bc": "bc", "x-of-rev": "rev1", "sign": "1:a:b:2",
                       "time": "1700000000000", "user-agent": None},
           "rules": {"static_param": "SP", "start": "1", "end": None}}
    cookies = [{"name": "auth_id", "value": "123", "domain": ".onlyfans.com", "path": "/"}]
    parsed = rl._request_from_capture(cap, cookies, "UA/1")
    h = parsed["headers"]
    assert h["user-id"] == "123" and h["user-agent"] == "UA/1"
    assert h["x-relay-static-param"] == "SP" and h["x-relay-sign-start"] == "1"
    assert "x-relay-sign-end" not in h
    assert parsed["url"] == cap["url"] and parsed["cookies"] is cookies


class _Ctx:
    def cookies(self, _urls=None):
        return [{"name": "auth_id", "value": "777", "domain": ".onlyfans.com", "path": "/"}]


class _Page:
    def goto(self, *_a, **_k):
        return None

    def evaluate(self, script, *_a):
        if "__relayCapture" in script:
            return {"url": "https://onlyfans.com/api2/v2/users/me",
                    "headers": {"user-id": "777", "x-bc": "bc", "x-of-rev": "r",
                                "sign": "1:a:b:2", "time": "1"},
                    "rules": {"static_param": "SP"}}
        return "UA/2"

    def wait_for_timeout(self, _ms):
        return None


def case_capture_binds_before_persist():
    order = []
    restore = _persist_fakes(order)
    try:
        job = _job(proxy=rl.PROXY_CUSTOM, proxy_label="hu-1", nickname="Bella")
        rl._capture_and_persist(job, _Page(), _Ctx())
        assert order == [("bind", "hu-1", "777"), ("persist", "777", "Bella"), ("hooks", "777")], order
        assert job.state == rl.STATE_DONE and job.account_id == "777"
        assert job.session_file == "session_T.json"

        # The Inflowwww proxy (the default): assign_pool, as POST /admin/proxy-pool/assign does.
        order.clear()
        job = _job()
        assert job.proxy == rl.PROXY_INFLOWWW
        rl._capture_and_persist(job, _Page(), _Ctx())
        assert order == [("pool", "777"), ("persist", "777", None), ("hooks", "777")], order
        assert job.message == "session captured; the Inflowwww proxy attached for all later traffic", job.message
        assert job.public()["proxy"] == rl.PROXY_INFLOWWW and job.public()["proxy_label"] == ""

        # No proxy: nothing is bound, so a re-login keeps the account's binding.
        order.clear()
        job = _job(proxy=rl.PROXY_NONE)
        rl._capture_and_persist(job, _Page(), _Ctx())
        assert order == [("persist", "777", None), ("hooks", "777")], order
        assert job.message == "session captured; no proxy attached (server IP)", job.message

        order.clear()

        def _bad_bind(label, aid):
            raise KeyError(label)

        proxy_registry.assign_account = _bad_bind
        job = _job(proxy=rl.PROXY_CUSTOM, proxy_label="gone")
        e = _raises(RuntimeError, rl._capture_and_persist, job, _Page(), _Ctx())
        assert "one egress" in str(e)

        def _no_pool(aid):
            raise LookupError("no Inflowwww proxies are set up on this relay")

        proxy_registry.assign_pool = _no_pool
        e = _raises(RuntimeError, rl._capture_and_persist, _job(), _Page(), _Ctx())
        assert "Inflowwww proxy" in str(e) and "one egress" in str(e), e
        assert order == [], "nothing may be persisted when the bind fails"
    finally:
        restore()


# ── Typing into OnlyFans' login form ─────────────────────────────────────────

class _Field:
    """A fake Playwright locator for one input / button. `swallow` fills are
    dropped (the field keeps reading empty)."""

    def __init__(self, log, name, *, visible=True, appears=True, swallow=0):
        self.log, self.name, self.visible, self.appears = log, name, visible, appears
        self.swallow, self.value = swallow, ""

    @property
    def first(self):
        return self

    def wait_for(self, state="visible", timeout=None):
        self.log.append(("wait", self.name, timeout))
        if not self.appears:
            raise Exception(f"Timeout {timeout}ms exceeded waiting for {self.name}")

    def is_visible(self):
        return self.visible

    def click(self, timeout=None):
        self.log.append(("click", self.name))

    def fill(self, value, timeout=None):
        if value:
            self.log.append(("fill", self.name))
        if self.swallow > 0 and value:
            self.swallow -= 1
            return
        self.value = value

    def press_sequentially(self, value, delay=None, timeout=None):
        self.log.append(("type", self.name))
        if self.swallow > 0:
            self.swallow -= 1
            return
        self.value = value

    def input_value(self, timeout=None):
        return self.value

    def press(self, key, timeout=None):
        self.log.append(("press", self.name, key))


class _FormPage:
    def __init__(self, **email_kw):
        self.log = []
        self.fields = {
            rl._EMAIL_FIELD: _Field(self.log, "email", **email_kw),
            rl._PASSWORD_FIELD: _Field(self.log, "password"),
            rl._SUBMIT_BUTTON: _Field(self.log, "submit"),
            rl._COOKIE_ONLY_NECESSARY: _Field(self.log, "only-necessary-cookies"),
        }

    def locator(self, sel):
        return self.fields[sel]

    def goto(self, *_a, **_k):
        return None

    def evaluate(self, *_a):
        return False

    @property
    def frames(self):
        return []


def case_form_waited_filled_verified():
    page = _FormPage()
    rl._type_credentials(page, "a@b.com", OF_PW)
    assert page.log == [
        ("wait", "email", rl.FORM_WAIT_S * 1000),
        ("click", "only-necessary-cookies"),
        ("fill", "email"), ("fill", "password"),
        ("click", "submit"),
    ], page.log
    assert page.fields[rl._EMAIL_FIELD].value == "a@b.com"
    assert page.fields[rl._PASSWORD_FIELD].value == OF_PW
    # No banner on screen: nothing to decline.
    page = _FormPage()
    page.fields[rl._COOKIE_ONLY_NECESSARY].visible = False
    rl.fill_login_form(page, "a@b.com", OF_PW)
    assert ("click", "only-necessary-cookies") not in page.log, page.log


def case_swallowed_fill_is_retyped():
    page = _FormPage(swallow=1)
    rl.fill_login_form(page, "a@b.com", OF_PW)
    assert page.fields[rl._EMAIL_FIELD].value == "a@b.com"
    assert [e for e in page.log if e[1] == "email"][-1] == ("type", "email"), page.log


def case_form_never_appears_fails_fast():
    _set_env()
    _NAV_ERRORS.clear()
    calls, urlopen = _fake_browserbase()
    page = _FormPage(appears=False)
    orig = _FakeBrowserCtx.__init__

    def _ctx_init(self, cdp_url):
        self.pages = [page]

    _FakeBrowserCtx.__init__ = _ctx_init
    job = _job()
    t0 = time.monotonic()
    try:
        _with_fakes(urlopen, lambda: rl._run_login(job, OF_PW))
    finally:
        _FakeBrowserCtx.__init__ = orig
    assert time.monotonic() - t0 < 5, "must fail fast, not wait out the job window"
    assert job.state == rl.STATE_ERROR, (job.state, job.error)
    assert "the OnlyFans login form did not appear" in job.error, job.error
    assert OF_PW not in job.error
    assert not [e for e in page.log if e[0] in ("fill", "type", "click")], page.log
    assert any(b and b.get("status") == "REQUEST_RELEASE" for _m, _u, b in calls)


def case_field_never_takes_value_fails():
    page = _FormPage(swallow=99)
    e = _raises(rl.LoginFormError, rl.fill_login_form, page, "a@b.com", OF_PW)
    assert "email field" in str(e) and "a@b.com" not in str(e), e
    attempts = [x for x in page.log if x[1] == "email" and x[0] in ("fill", "type")]
    assert len(attempts) == rl.FILL_ATTEMPTS, page.log  # one fill, then key-by-key retypes
    assert not [x for x in page.log if x[1] in ("password", "submit")], page.log


def case_live_server_is_the_serving_module():
    import sys
    import types
    import server
    assert rl.live_server() is server
    served = types.ModuleType("service.server")
    served.post_bootstrap_hooks = lambda aid: None
    sys.modules["service.server"] = served
    try:
        assert rl.live_server() is served
    finally:
        sys.modules.pop("service.server", None)


def case_api_proxy_choice():
    import remote_login_api
    proxy_registry.upsert({"label": "mine-1", "host": "203.0.113.11", "port": 12323})
    proxy_registry.upsert({"label": "theirs-1", "host": "203.0.113.12", "port": 12323, "user_id": "u-other"})
    seen = []
    orig = (rl.start_login, proxy_registry.pool_entries)
    rl.start_login = lambda **kw: seen.append(kw) or _job(proxy=kw["proxy"], proxy_label=kw["proxy_label"])
    base = {"email": "a@b.c", "password": OF_PW, "backend": "browserbase"}
    start = lambda **kw: client.post("/admin/login/remote/start", json={**base, **kw})
    try:
        proxy_registry.pool_entries = lambda: [{"label": "infloww-0000aaaa", "pool": True}]
        r = start()
        assert r.status_code == 200, r.text
        assert seen[-1]["proxy"] == rl.PROXY_INFLOWWW and seen[-1]["proxy_label"] == "", seen[-1]
        assert r.json()["proxy"] == rl.PROXY_INFLOWWW and r.json()["proxy_label"] == ""
        assert start(proxy="none").status_code == 200 and seen[-1]["proxy"] == rl.PROXY_NONE
        r = start(proxy_label="mine-1")  # a label alone means custom
        assert r.status_code == 200 and seen[-1]["proxy"] == rl.PROXY_CUSTOM, r.text
        assert seen[-1]["proxy_label"] == "mine-1"

        proxy_registry.pool_entries = lambda: []
        assert start().status_code == 200 and seen[-1]["proxy"] == rl.PROXY_NONE, "no pool: the flow's default is none"
        r = start(proxy="infloww")
        assert r.status_code == 409 and "Inflowwww" in r.text, r.text
        n = len(seen)
        assert start(proxy="custom").status_code == 400
        assert start(proxy="bogus").status_code == 400
        assert start(proxy="custom", proxy_label="missing").status_code == 404
        # Visibility: another user's proxy is invisible to a signed-in user.
        real_user = remote_login_api.remote_login.live_server()._get_request_user
        remote_login_api.remote_login.live_server()._get_request_user = lambda: type("U", (), {"id": "u-me", "account_ids": frozenset()})()
        try:
            assert start(proxy="custom", proxy_label="theirs-1").status_code == 404
        finally:
            remote_login_api.remote_login.live_server()._get_request_user = real_user
        assert len(seen) == n, "no job may start on a refused proxy"
    finally:
        rl.start_login, proxy_registry.pool_entries = orig
        rl._jobs.clear()


def case_api_gates():
    proxy_registry.upsert({"label": "hu-1", "host": "203.0.113.10", "port": 12323,
                           "username": "puser", "password": PROXY_PW})
    base = {"email": "a@b.c", "password": OF_PW, "proxy_label": "hu-1"}
    r = client.post("/admin/login/remote/start", json={"email": "a@b.c", "proxy_label": 7})
    assert r.status_code in (400, 422) and OF_PW not in r.text, r.text
    r = client.post("/admin/login/remote/start", json={"email": "a@b.c", "password": ""})
    assert r.status_code == 400, r.text  # never a 422 echoing the body
    r = client.post("/admin/login/remote/start", json={**base, "backend": "nope"})
    assert r.status_code == 400, r.text
    r = client.post("/admin/login/remote/start", json=base)  # default: local
    assert r.status_code == 501, r.text
    r = client.post("/admin/login/remote/start", json={**base, "proxy_label": "missing",
                                                       "backend": "browserbase"})
    assert r.status_code == 404, r.text
    _set_env(key=None, project=None)
    r = client.post("/admin/login/remote/start", json={**base, "backend": "browserbase"})
    assert r.status_code == 503 and "BROWSERBASE_API_KEY" in r.text, r.text
    assert OF_PW not in r.text and PROXY_PW not in r.text

    assert client.get("/admin/login/remote/nope").status_code == 404
    j = _job(principal="someone-else")
    rl._jobs[j.id] = j
    try:
        assert client.get(f"/admin/login/remote/{j.id}").status_code == 403
        assert client.post(f"/admin/login/remote/{j.id}/cancel").status_code == 403
        mine = _job(principal=None)
        rl._jobs[mine.id] = mine
        r = client.get(f"/admin/login/remote/{mine.id}")
        assert r.status_code == 200 and r.json()["id"] == mine.id
        assert client.post(f"/admin/login/remote/{mine.id}/cancel").status_code == 200
        assert mine._cancel.is_set()
    finally:
        rl._jobs.clear()

    assert any("/admin/login/remote/start".startswith(p) for p in employees._AUDIT_SKIP_PREFIXES)
    assert any("/admin/login/remote/start".startswith(p) for p in chatters._CHATTER_BLOCKED_ADMIN_PREFIXES)
    assert auth.get_request_user() is None


# ── 2FA: the code typed in by the job's own thread ──────────────────────────

GOOD_OTP = "246810"


class _OtpField(_Field):
    """OnlyFans' 2FA field: Enter with the right code signs the page in."""

    def __init__(self, page):
        super().__init__(page.log, "otp")
        self.page = page

    def is_visible(self):
        return self.page.on_prompt()

    def press(self, key, timeout=None):
        super().press(key, timeout)
        self.page.otp_tries.append(self.value)
        if key == "Enter" and self.value == GOOD_OTP:
            self.page.signed_in = True


class _OtpPage(_FormPage):
    """OnlyFans' login form; once LOG IN is clicked, its 2FA prompt
    (input[name="code"]) until the right code is entered; then the chats
    page's signed request."""

    def __init__(self):
        super().__init__()
        self.signed_in = False
        self.otp_tries = []
        self.fields[rl._OTP_FIELD] = _OtpField(self)

    hide_prompt = False

    def on_prompt(self):
        return ("click", "submit") in self.log and not self.signed_in and not self.hide_prompt

    def cookies(self, _urls=None):
        return [{"name": "auth_id", "value": "777", "domain": ".onlyfans.com", "path": "/"}] if self.signed_in else []

    def evaluate(self, script, *_a):
        if "__relayCapture" in script:
            return _Page().evaluate(script)
        return "UA/2" if "userAgent" in script else False

    def wait_for_timeout(self, _ms):
        time.sleep(0.01)


class _LogTap(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _otp_login(steps):
    """Start a served login over HTTP on an _OtpPage (fake Browserbase,
    fake persist), run `steps(job_id, page)` once the job asks for the code,
    and wait for the job to end. Returns (job, page, log lines, statuses)."""
    _set_env()
    _NAV_ERRORS.clear()
    calls, urlopen = _fake_browserbase()
    page, order, statuses = _OtpPage(), [], []
    restore = _persist_fakes(order)
    orig_init = _FakeBrowserCtx.__init__

    def _ctx_init(self, cdp_url):
        self.pages = [page]
        self.cookies = page.cookies

    tap = _LogTap()
    logging.getLogger().addHandler(tap)
    _FakeBrowserCtx.__init__ = _ctx_init

    def _run():
        r = client.post("/admin/login/remote/start", json={
            "email": "otp@x.com", "password": OF_PW, "backend": "browserbase", "proxy": "none"})
        assert r.status_code == 200, r.text
        job = rl.get_job(r.json()["id"])
        try:
            _until(lambda: job.state == rl.STATE_OTP)
            statuses.append(client.get(f"/admin/login/remote/{job.id}").json())
            steps(job.id, page, statuses)
            _until(job.is_terminal)
        finally:  # a failed case must not leave its job running for the next one
            if not job.is_terminal():
                rl.cancel(job)
                _until(job.is_terminal)
        statuses.append(job.public())
        return job

    try:
        job = _with_fakes(urlopen, _run)
    finally:
        _FakeBrowserCtx.__init__ = orig_init
        logging.getLogger().removeHandler(tap)
        restore()
    return job, page, tap.lines, statuses


def _until(cond, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def case_otp_code_signs_in():
    def _steps(jid, page, statuses):
        assert statuses[-1]["state"] == rl.STATE_OTP and statuses[-1]["message"] == rl.OTP_ASK, statuses[-1]
        r = client.post(f"/admin/login/remote/{jid}/otp", json={"code": f" {GOOD_OTP[:3]} {GOOD_OTP[3:]} "})
        assert r.status_code == 200, r.text
        statuses.append(r.json())

    job, page, lines, statuses = _otp_login(_steps)
    assert job.state == rl.STATE_DONE, (job.state, job.error)
    assert job.account_id == "777"
    otp = [e for e in page.log if e[1] == "otp"]
    assert otp == [("fill", "otp"), ("press", "otp", "Enter")], page.log
    assert page.otp_tries == [GOOD_OTP]
    blob = json.dumps(statuses) + "\n".join(lines)
    assert GOOD_OTP not in blob and OF_PW not in blob, "the code / password leaked into a status or log line"
    assert job._otp_code is None


def case_otp_wrong_code_retries():
    orig = rl.OTP_VERIFY_S
    rl.OTP_VERIFY_S = 0.3

    def _steps(jid, page, statuses):
        job = rl.get_job(jid)
        r = client.post(f"/admin/login/remote/{jid}/otp", json={"code": "000000"})
        assert r.status_code == 200 and r.json()["message"] == rl.OTP_CHECKING, r.text
        r = client.post(f"/admin/login/remote/{jid}/otp", json={"code": "111111"})
        assert r.status_code == 409 and "already being checked" in r.text and "111111" not in r.text, r.text
        _until(lambda: job.message == rl.OTP_REJECTED)
        statuses.append(client.get(f"/admin/login/remote/{jid}").json())
        assert statuses[-1]["state"] == rl.STATE_OTP, statuses[-1]
        assert not page.signed_in
        r = client.post(f"/admin/login/remote/{jid}/otp", json={"code": GOOD_OTP})
        assert r.status_code == 200, r.text

    try:
        job, page, lines, statuses = _otp_login(_steps)
    finally:
        rl.OTP_VERIFY_S = orig
    assert job.state == rl.STATE_DONE, (job.state, job.error)
    assert page.otp_tries == ["000000", GOOD_OTP], page.otp_tries
    assert any(s["message"] == rl.OTP_REJECTED and s["state"] == rl.STATE_OTP for s in statuses), statuses
    blob = json.dumps(statuses) + "\n".join(lines)
    assert "000000" not in blob and GOOD_OTP not in blob


def case_otp_prompt_back_within_verify_window():
    seen = []

    def _steps(jid, page, statuses):
        job = rl.get_job(jid)
        assert client.post(f"/admin/login/remote/{jid}/otp", json={"code": "000000"}).status_code == 200
        _until(lambda: page.otp_tries == ["000000"])
        page.hide_prompt = True  # OnlyFans navigates away from the prompt...
        _until(lambda: job.state == rl.STATE_TYPING)
        seen.append(job.public())
        page.hide_prompt = False  # ...and shows it again, well inside OTP_VERIFY_S (15 s)
        _until(lambda: job.state == rl.STATE_OTP, timeout=3)
        seen.append(job.public())
        assert client.post(f"/admin/login/remote/{jid}/otp", json={"code": GOOD_OTP}).status_code == 200

    job, page, lines, statuses = _otp_login(_steps)
    assert seen[0]["state"] == rl.STATE_TYPING, seen
    assert seen[1]["state"] == rl.STATE_OTP and seen[1]["message"] == rl.OTP_ASK, seen
    assert job.state == rl.STATE_DONE and page.otp_tries == ["000000", GOOD_OTP], (job.state, page.otp_tries)


class _OtpFormField(_Field):
    """A 2FA field for _enter_otp alone: records timeouts; `press_fails`
    makes Enter raise; `on_fill` runs after a fill; `locator()` reaches the
    field's own form's submit button."""

    def __init__(self, log, *, swallow=0, press_fails=False, on_fill=None):
        super().__init__(log, "otp", swallow=swallow)
        self.press_fails, self.on_fill, self.timeouts = press_fails, on_fill, []

    def fill(self, value, timeout=None):
        self.timeouts.append(timeout)
        super().fill(value, timeout)
        if self.on_fill:
            self.on_fill()

    def input_value(self, timeout=None):
        self.timeouts.append(timeout)
        return self.value

    def press(self, key, timeout=None):
        self.timeouts.append(timeout)
        super().press(key, timeout)
        if self.press_fails:
            raise Exception("Timeout exceeded")

    def locator(self, sel):
        self.log.append(("locator", sel))
        return self if sel.startswith("xpath=") else _Field(self.log, "otp-form-submit")


def case_enter_otp_one_attempt_cancel_and_form_scope():
    def page_with(field):
        page = _FormPage()
        field.log = page.log
        page.fields[rl._OTP_FIELD] = field
        return page

    job = _job(state=rl.STATE_OTP, expires_at=time.time() + 600)  # past _check's CAPTURE_RESERVE_S
    # one fill attempt, short timeouts: a swallowed fill is not retyped
    field = _OtpFormField([], swallow=1)
    page = page_with(field)
    assert rl._enter_otp(job, page, GOOD_OTP) is False
    assert page.log == [("fill", "otp")], page.log
    assert set(field.timeouts) == {rl.OTP_STEP_TIMEOUT_MS}, field.timeouts
    # Enter fails: the fallback is the 2FA form's own submit, not the page's first one
    field = _OtpFormField([], press_fails=True)
    page = page_with(field)
    assert rl._enter_otp(job, page, GOOD_OTP) is True
    assert page.log == [("fill", "otp"), ("press", "otp", "Enter"),
                        ("locator", "xpath=ancestor::form"), ("locator", rl._SUBMIT_BUTTON),
                        ("click", "otp-form-submit")], page.log
    assert ("click", "submit") not in page.log
    # a cancel that lands while the code is typed: no submit
    field = _OtpFormField([], on_fill=job._cancel.set)
    page = page_with(field)
    assert isinstance(_raises(rl._Cancelled, rl._enter_otp, job, page, GOOD_OTP), rl._Cancelled)
    assert page.log == [("fill", "otp")], page.log


def case_otp_only_a_visible_field():
    page = _FormPage()
    page.fields[rl._OTP_FIELD] = _Field(page.log, "otp", visible=False)  # stale, hidden
    page.query_selector = lambda sel: page.fields[rl._OTP_FIELD]  # present in the DOM all the same
    assert rl._detect_otp(page) is False, "a hidden code input is no 2FA prompt"
    page.fields[rl._OTP_FIELD].visible = True
    assert rl._detect_otp(page) is True
    del page.fields[rl._OTP_FIELD]  # locator() raising: no prompt, no crash
    assert rl._detect_otp(page) is False
    # the fill target is the same visible-only selector, so .first skips a hidden input
    parts = rl._OTP_FIELD.split(", ")
    assert len(parts) == len(rl._OTP_SELECTORS) and all(p.endswith(":visible") for p in parts), rl._OTP_FIELD


def case_otp_code_spaces_and_dashes():
    for typed, code in (("123 456", "123456"), ("123-456", "123456"), (" 1234-5678 ", "12345678"),
                        ("12\t34 56", "123456")):
        job = _job(state=rl.STATE_OTP)
        job.submit_otp(typed)
        assert job.take_otp() == code, typed
    mine = _job(principal=None, state=rl.STATE_OTP)
    rl._jobs[mine.id] = mine
    try:
        r = client.post(f"/admin/login/remote/{mine.id}/otp", json={"code": "246-810"})
        assert r.status_code == 200 and mine.take_otp() == GOOD_OTP, r.text
        for bad in ("123.456", "12a-456", "12-34-5", "123_456", "--"):
            fresh = _job(principal=None, state=rl.STATE_OTP)
            rl._jobs[fresh.id] = fresh
            r = client.post(f"/admin/login/remote/{fresh.id}/otp", json={"code": bad})
            assert r.status_code == 400 and bad not in r.text and fresh._otp_code is None, (bad, r.text)
    finally:
        rl._jobs.clear()


def case_otp_scrubbed_from_job_error():
    from contextlib import contextmanager

    @contextmanager
    def _backend(_job):
        yield None, None

    def _body(_page, _ctx):
        raise RuntimeError(f'Locator.fill: Timeout 2000ms exceeded: fill("{GOOD_OTP}")')

    job = _job(state=rl.STATE_OTP)
    job.submit_otp(GOOD_OTP)
    assert job.take_otp() == GOOD_OTP
    tap = _LogTap()
    logging.getLogger().addHandler(tap)
    orig = rl._browserbase_backend
    rl._browserbase_backend = _backend
    try:
        rl._serve(job, secrets=(OF_PW,), body=_body)
    finally:
        rl._browserbase_backend = orig
        logging.getLogger().removeHandler(tap)
    assert job.state == rl.STATE_ERROR and "***" in job.error, job.error
    blob = json.dumps(job.public()) + "\n".join(tap.lines)
    assert GOOD_OTP not in blob, "the code reached the job error or a log line"


def case_api_otp_gates():
    otp = lambda jid, code: client.post(f"/admin/login/remote/{jid}/otp", json={"code": code})
    assert otp("nope", GOOD_OTP).status_code == 404
    theirs = _job(principal="someone-else", state=rl.STATE_OTP)
    typing = _job(principal=None, state=rl.STATE_TYPING)
    mine = _job(principal=None, state=rl.STATE_OTP)
    for j in (theirs, typing, mine):
        rl._jobs[j.id] = j
    try:
        r = otp(theirs.id, GOOD_OTP)
        assert r.status_code == 403 and theirs._otp_code is None, r.text
        r = otp(typing.id, GOOD_OTP)
        assert r.status_code == 409 and typing._otp_code is None, r.text
        for bad in ("", "12345", "123456789", "12a456"):
            r = otp(mine.id, bad)
            assert r.status_code == 400, (bad, r.text)
            assert not bad or bad not in r.text
        assert client.post(f"/admin/login/remote/{mine.id}/otp", json={}).status_code == 400
        # a body that is not {"code": "<string>"}: 400, never a pydantic 422 echoing it
        for body in ({"code": 123456}, 123456, "123456", ["123456"], {"code": ["123456"]}):
            r = client.post(f"/admin/login/remote/{mine.id}/otp", json=body)
            assert r.status_code == 400 and "123456" not in r.text, (body, r.status_code, r.text)
        r = client.post(f"/admin/login/remote/{mine.id}/otp", content=b'{"code": 123456',
                        headers={"content-type": "application/json"})
        assert r.status_code in (400, 422) and "123456" not in r.text, (r.status_code, r.text)
        assert mine._otp_code is None
        r = otp(mine.id, GOOD_OTP)
        assert r.status_code == 200 and r.json()["state"] == rl.STATE_OTP, r.text
        assert r.json()["message"] == rl.OTP_CHECKING, r.text
        assert GOOD_OTP not in r.text and GOOD_OTP not in client.get(f"/admin/login/remote/{mine.id}").text
        assert GOOD_OTP not in repr(mine)
        r = otp(mine.id, "135791")  # one code at a time
        assert r.status_code == 409 and "already being checked" in r.text and "135791" not in r.text, r.text
        assert mine.take_otp() == GOOD_OTP and mine.take_otp() is None
        assert otp(mine.id, "135791").status_code == 409, "still being checked after the worker took it"
        mine.otp_retry(rl.OTP_REJECTED)  # the job asks again
        assert otp(mine.id, "135791").status_code == 200
        mine.set_state(rl.STATE_TYPING)  # leaving the prompt empties the slot
        assert mine._otp_code is None and not mine._otp_busy
        mine.set_state(rl.STATE_OTP, rl.OTP_ASK)
        assert otp(mine.id, GOOD_OTP).status_code == 200
        mine.fail("boom")  # so does failing
        assert mine._otp_code is None and not mine._otp_busy
        assert otp(mine.id, GOOD_OTP).status_code == 409, "a failed job takes no code"
        mine = _job(principal=None, state=rl.STATE_OTP)
        rl._jobs[mine.id] = mine
        mine.set_state(rl.STATE_DONE)
        assert otp(mine.id, GOOD_OTP).status_code == 409, "a finished job takes no code"
    finally:
        rl._jobs.clear()
    assert any("/admin/login/remote/x/otp".startswith(p) for p in employees._AUDIT_SKIP_PREFIXES)


_harness.run()
