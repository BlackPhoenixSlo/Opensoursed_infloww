#!/usr/bin/env python3
"""
Served OnlyFans login in a remote browser, a human solving every challenge.

Built from an earlier direct-login prototype, with its two halves reshaped
for this repo:

  * The browser runs on Browserbase. The relay creates a Browserbase session,
    drives it over CDP (Playwright `connect_over_cdp`, so no Chromium on this
    host), types the creator's email + password into OnlyFans' real form, and
    hands the operator Browserbase's own LIVE VIEW (an interactive page of the
    remote browser). When OnlyFans shows Cloudflare / a captcha / a 2FA prompt,
    a HUMAN solves it there. Browserbase's captcha solver is forced off.
  * Capture reuses the paste-curl pipeline. Before OnlyFans loads, the login
    extension's own interceptor (loginExtensionMulti/interceptor.js) is added
    as an init script, so the remote page publishes exactly what the extension
    would put in its "Copy cURL": the signed headers and `x-relay-static-param`.
    Those, plus the browser's cookies, go through
    `session_bootstrap.from_request` (paste-curl's own parser output path),
    then the proxy is bound and `server.post_bootstrap_hooks` runs, the same
    hooks POST /admin/session/bootstrap runs.

BROWSERBASE'S NETWORK, OUR PROXY AFTERWARDS (owner's call: "we can just use
their proxies and then we attach ours"). The session is created with
Browserbase's managed proxies (`proxies: true`); our proxy is never sent to
Browserbase. The proxy the operator picks is still required, and it is bound to
the account BEFORE the session is saved, so every later relay call for the
account egresses through it, as with an extension-captured login. A session
that can't be created, or an OnlyFans page that won't load, fails loudly.

SECRETS. BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID come from the env only.
The OnlyFans password lives as a local of the worker thread, is never stored
on the job, and `scrub()` strips it from every job message, error and log line.

BACKENDS. `backend` keeps the source's selector, default "local". This repo
removed the local headless-Chromium capture (cleanup 9a: capture_session_proxy,
interceptor, extract_rules), so "local" is refused up front with a clear
error; "browserbase" is the opt-in that works.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("of-relay.remote-login")

HERE = Path(__file__).resolve().parent
# The login extension's MAIN-world interceptor, injected unchanged: one source
# of truth for what a captured session carries.
INTERCEPTOR_PATH = HERE.parent / "loginExtensionMulti" / "interceptor.js"

BACKEND_LOCAL = "local"
BACKEND_BROWSERBASE = "browserbase"
BACKENDS = (BACKEND_LOCAL, BACKEND_BROWSERBASE)

BROWSERBASE_API = "https://api.browserbase.com/v1"
BB_HTTP_TIMEOUT_S = 30


def live_server():
    """The server module that is actually serving.

    uvicorn loads it as `service.server`; a bare `import server` would run a
    SECOND copy of server.py under the name `server`, with its own state
    (`_main_loop` unset, its own pump registry). Through that copy the
    post-bootstrap link to the signed-in user was silently skipped: the
    account landed on disk and in `accounts`, but owned by nobody."""
    for name in ("service.server", "server"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "post_bootstrap_hooks"):
            return mod
    import server  # lazy: server imports remote_login_api
    return server

OF_HOME = "https://onlyfans.com/"
OF_CHATS = "https://onlyfans.com/my/chats/"
NAV_TIMEOUT_MS = 45_000

# Browserbase's default session lifetime is 300 s; stop short of it so the job
# ends with our own error, not a dropped CDP socket. The login (human included)
# must land CAPTURE_RESERVE_S before that, leaving the capture its time.
JOB_WINDOW_S = 285
CAPTURE_WAIT_S = 25       # after login: wait for a signed request + static_param
CAPTURE_RESERVE_S = 60
POLL_S = 1.0
JOB_TTL_S = 600           # a finished job stays readable this long

STATE_STARTING = "starting"
STATE_TYPING = "typing"
STATE_CHALLENGE = "challenge"
STATE_OTP = "otp"
STATE_CAPTURING = "capturing"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_CANCELLED = "cancelled"
_TERMINAL = {STATE_DONE, STATE_ERROR, STATE_CANCELLED}

# OnlyFans login DOM: ordered fallbacks. A stale selector only stalls the job in
# `typing`; the human can finish the form by hand in the live view.
_EMAIL_SELECTORS = (
    'input[name="email"]', 'input[type="email"]',
    'input[inputmode="email"]', 'input#email', 'input[name="username"]',
)
_PASSWORD_SELECTORS = (
    'input[name="password"]', 'input[type="password"]', 'input#password',
)
_SUBMIT_SELECTORS = (
    'button[type="submit"]', 'button[at-attr="submit"]',
    'form button:has-text("Log")', 'button:has-text("Log in")',
)
_OTP_SELECTORS = (
    'input[name="code"]', 'input[autocomplete="one-time-code"]',
    'input[name="otp"]',
)

# Stores the interceptor's postMessage payloads on window.__relayCapture,
# merging rules the way the extension's bridge.js does (static_param arrives on
# a later publish than the headers).
_CAPTURE_LISTENER_JS = r"""
(function () {
  window.addEventListener("message", function (e) {
    try {
      if (e.source !== window || !e.data || e.data.__chatterly_capture !== true) return;
      var p = e.data.payload || {}, prev = window.__relayCapture || {};
      var pr = prev.rules || {}, nr = p.rules || {};
      window.__relayCapture = {
        url: p.url, headers: p.headers || {},
        rules: {
          static_param: nr.static_param || pr.static_param || null,
          start: nr.start || pr.start || null,
          end: nr.end || pr.end || null,
        },
      };
    } catch (_) {}
  });
})();
"""


class BackendUnavailable(RuntimeError):
    """The requested backend cannot run in this build (HTTP 501)."""


class RemoteLoginConflict(RuntimeError):
    """A live job already exists for this email (HTTP 409)."""


class _Cancelled(Exception):
    pass


def scrub(text: Any, *secrets: str | None) -> str:
    """`text` with every non-empty secret replaced by ***."""
    s = "" if text is None else str(text)
    for secret in secrets:
        if secret:
            s = s.replace(secret, "***")
    return s


# ── Job ─────────────────────────────────────────────────────────────────────

@dataclass
class RemoteLoginJob:
    id: str
    email: str
    proxy_label: str
    principal: str | None
    created_at: float
    expires_at: float
    backend: str = BACKEND_BROWSERBASE
    nickname: str | None = None
    make_active: bool = True
    state: str = STATE_STARTING
    message: str = ""
    error: str | None = None
    account_id: str | None = None
    session_file: str | None = None
    live_view_url: str | None = None
    finished_at: float | None = None
    _cancel: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            if self.state in _TERMINAL:
                return
            self.state = state
            if message:
                self.message = message
            if state in _TERMINAL:
                self.finished_at = time.time()

    def fail(self, message: str) -> None:
        with self._lock:
            self.state = STATE_ERROR
            self.error = message
            self.message = message
            self.finished_at = time.time()

    def is_terminal(self) -> bool:
        return self.state in _TERMINAL

    def public(self) -> dict[str, Any]:
        """Status safe to return to the job's own principal: no password, no
        cookies, no CDP connect URL. The live-view URL is returned only while
        the job runs (it controls the remote browser)."""
        with self._lock:
            return {
                "id": self.id,
                "backend": self.backend,
                "state": self.state,
                "message": self.message,
                "error": self.error,
                "account_id": self.account_id,
                "session_file": self.session_file,
                "proxy_label": self.proxy_label,
                "live_view_url": None if self.state in _TERMINAL else self.live_view_url,
                "expires_at": self.expires_at,
            }


_jobs: dict[str, RemoteLoginJob] = {}
_jobs_lock = threading.Lock()


def _gc_locked() -> None:
    now = time.time()
    for jid in [jid for jid, j in _jobs.items()
                if j.is_terminal() and now - (j.finished_at or now) > JOB_TTL_S]:
        _jobs.pop(jid, None)


def get_job(job_id: str) -> RemoteLoginJob | None:
    with _jobs_lock:
        _gc_locked()
        return _jobs.get(job_id)


def _register(job: RemoteLoginJob) -> None:
    key = job.email.strip().lower()
    with _jobs_lock:
        _gc_locked()
        for j in _jobs.values():
            if not j.is_terminal() and j.email.strip().lower() == key:
                raise RemoteLoginConflict(
                    "a login is already running for this OnlyFans email — cancel it first")
        _jobs[job.id] = job


# ── Entry points ────────────────────────────────────────────────────────────

def start_login(*, email: str, password: str, proxy_label: str,
                principal: str | None, nickname: str | None = None,
                make_active: bool = True, backend: str = BACKEND_LOCAL) -> RemoteLoginJob:
    """Start a served login and return its job. The password goes to the worker
    thread only. The request's context is copied into the thread so the
    post-bootstrap hooks link the new account to the signed-in user."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r} (expected one of {BACKENDS})")
    if backend == BACKEND_LOCAL:
        raise BackendUnavailable(
            "the local browser backend is not available in this build (the "
            "relay ships no Chromium) — use backend=\"browserbase\"")
    if not email or not password:
        raise ValueError("email and password are required")
    if not proxy_label:
        raise ValueError("a proxy is required (it is bound to the account for all later traffic)")
    _bb_env()  # fail before a job exists when the env is not set
    now = time.time()
    job = RemoteLoginJob(
        id=uuid.uuid4().hex, email=email, proxy_label=proxy_label, principal=principal,
        created_at=now, expires_at=now + JOB_WINDOW_S, backend=backend,
        nickname=nickname, make_active=make_active, message="starting browser",
    )
    _register(job)
    ctx = contextvars.copy_context()
    threading.Thread(
        target=ctx.run, args=(_run_login, job, password),
        name=f"remote-login-{job.id[:8]}", daemon=True,
    ).start()
    return job


def cancel(job: RemoteLoginJob) -> None:
    job._cancel.set()


# ── Worker ──────────────────────────────────────────────────────────────────

def _run_login(job: RemoteLoginJob, password: str) -> None:
    def _body(page, context) -> None:  # the backend has already loaded OF_HOME
        job.set_state(STATE_TYPING, "entering credentials")
        _type_credentials(page, job.email, password)
        _drive_until_logged_in(job, page, context)
        _capture_and_persist(job, page, context)

    _serve(job, secrets=(password,), body=_body)


def _serve(job: RemoteLoginJob, *, secrets: tuple[str | None, ...],
           body: Callable[[Any, Any], None]) -> None:
    """Open the backend, run `body(page, context)`, tear down — inside the one
    scrubbed try/except every job ends through."""
    try:
        with _browserbase_backend(job) as (context, page):
            body(page, context)
    except _Cancelled:
        job.set_state(STATE_CANCELLED, "cancelled")
    except Exception as e:  # noqa: BLE001
        msg = scrub(f"{type(e).__name__}: {e}", *secrets)
        log.warning("remote login %s failed: %s", job.id, msg)
        job.fail(msg)
    finally:
        if not job.is_terminal():  # body returned without reaching a final state
            job.fail("login ended without capturing a session")


@contextmanager
def _browserbase_backend(job: RemoteLoginJob):
    """A Browserbase Chromium on Browserbase's managed proxies, driven over
    CDP, with OnlyFans already loaded. Yields `(context, page)`; releases the
    session on the way out."""
    from playwright.sync_api import sync_playwright

    session = _bb_create_session()
    with sync_playwright() as p, _bb_connected(job, p, session) as (context, page):
        err = open_of(page)
        if err:
            raise RuntimeError(f"couldn't open OnlyFans in the remote browser: {err}")
        job.set_state(STATE_STARTING, "browser ready" if job.live_view_url else
                      "browser ready (live view unavailable — challenges cannot be solved)")
        yield context, page


@contextmanager
def _bb_connected(job: RemoteLoginJob, p, session: dict[str, Any]):
    """CDP-connect to `session` with the capture scripts in place, publish its
    live view on the job; close the browser and release the session on exit."""
    sid = session.get("id")
    try:
        lv = _bb_live_view_url(sid)
        with job._lock:
            job.live_view_url = lv
        browser = p.chromium.connect_over_cdp(session["connectUrl"])
        try:
            context = browser.contexts[0]
            context.add_init_script(_CAPTURE_LISTENER_JS)
            context.add_init_script(INTERCEPTOR_PATH.read_text(encoding="utf-8"))
            page = context.pages[0] if context.pages else context.new_page()
            yield context, page
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
    finally:
        _bb_release(sid)


def open_of(page) -> str | None:
    """Load OnlyFans' home page. None when it loaded, else the navigation
    error's first line."""
    try:
        page.goto(OF_HOME, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        return (str(e).splitlines() or [type(e).__name__])[0]
    return None


# ── Browserbase REST (stdlib; tests fake these symbols) ─────────────────────

def _bb_env() -> tuple[str, str]:
    api_key = os.environ.get("BROWSERBASE_API_KEY")
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID")
    if not api_key:
        raise RuntimeError("BROWSERBASE_API_KEY is not set — cannot start a Browserbase login")
    if not project_id:
        raise RuntimeError("BROWSERBASE_PROJECT_ID is not set — cannot start a Browserbase login")
    return api_key, project_id


def _bb_session_payload(project_id: str) -> dict[str, Any]:
    """The create-session body: Browserbase's managed proxies (our proxy is
    never sent to Browserbase; it is bound to the account afterwards), and
    automated captcha solving OFF (it defaults to on)."""
    return {
        "projectId": project_id,
        "proxies": True,
        "browserSettings": {"solveCaptchas": False},
    }


def _bb_request(path: str, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    api_key, _ = _bb_env()
    req = urllib.request.Request(
        f"{BROWSERBASE_API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"X-BB-API-Key": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=BB_HTTP_TIMEOUT_S) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Browserbase {method} {path} failed (HTTP {e.code}): {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Browserbase {method} {path} failed: {e.reason}") from None
    return json.loads(raw.decode() or "{}")


def _bb_create_session() -> dict[str, Any]:
    """Create a session on Browserbase's managed proxies. Raises on any refusal."""
    _, project_id = _bb_env()
    try:
        session = _bb_request("/sessions", "POST", _bb_session_payload(project_id))
    except RuntimeError as e:
        raise RuntimeError(f"couldn't start a Browserbase session on its managed proxies: {e}") from None
    if not session.get("connectUrl") or not session.get("id"):
        raise RuntimeError("Browserbase session-create returned no id/connectUrl")
    return session


def _bb_live_view_url(session_id: str) -> str | None:
    try:
        dbg = _bb_request(f"/sessions/{session_id}/debug")
    except Exception as e:  # noqa: BLE001
        log.warning("browserbase live view unavailable for %s: %s", session_id, e)
        return None
    url = dbg.get("debuggerFullscreenUrl") or dbg.get("debuggerUrl")
    pages = dbg.get("pages") or []
    if not url and pages:
        url = pages[0].get("debuggerFullscreenUrl") or pages[0].get("debuggerUrl")
    return url


def _bb_release(session_id: str | None) -> None:
    if not session_id:
        return
    try:
        _, project_id = _bb_env()
        _bb_request(f"/sessions/{session_id}", "POST",
                    {"projectId": project_id, "status": "REQUEST_RELEASE"})
    except Exception as e:  # noqa: BLE001 — the session times out on its own
        log.info("browserbase release of %s failed: %s", session_id, e)


# ── Page driving ────────────────────────────────────────────────────────────

def _goto(page, url: str, wait_until: str = "domcontentloaded") -> None:
    try:
        page.goto(url, wait_until=wait_until, timeout=NAV_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001 — a slow load; inspect the page anyway
        log.info("navigation to %s did not settle: %s", url, type(e).__name__)


def _find_first(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _type_credentials(page, email: str, password: str) -> None:
    em = _find_first(page, _EMAIL_SELECTORS)
    if em:
        try:
            em.fill(email)
        except Exception:  # noqa: BLE001
            pass
    pw = _find_first(page, _PASSWORD_SELECTORS)
    if pw:
        try:
            pw.fill(password)
        except Exception:  # noqa: BLE001
            pass
    submit = _find_first(page, _SUBMIT_SELECTORS)
    try:
        if submit:
            submit.click()
        elif pw:
            pw.press("Enter")
    except Exception:  # noqa: BLE001
        pass


def _detect_challenge(page) -> bool:
    """A human-verification challenge is on screen: Cloudflare interstitial
    text / elements, or a Turnstile / reCAPTCHA / hCaptcha / GeeTest frame."""
    try:
        if page.evaluate(
            """() => {
                const t = (document.body && document.body.innerText || '').toLowerCase();
                if (t.includes('just a moment') || t.includes('verify you are human')
                    || t.includes('checking your browser')) return true;
                return !!document.querySelector(
                    '#challenge-running, #challenge-stage, #challenge-form, .cf-turnstile');
            }"""
        ):
            return True
    except Exception:  # noqa: BLE001
        pass
    needles = ("turnstile", "recaptcha", "hcaptcha", "geetest", "challenges.cloudflare")
    try:
        return any(any(n in (f.url or "").lower() for n in needles) for f in page.frames)
    except Exception:  # noqa: BLE001
        return False


def _detect_otp(page) -> bool:
    return _find_first(page, _OTP_SELECTORS) is not None


def _auth_id(context) -> str | None:
    """auth_id is OnlyFans' logged-in cookie."""
    try:
        for c in context.cookies(["https://onlyfans.com"]):
            if c.get("name") == "auth_id" and c.get("value"):
                return c["value"]
    except Exception:  # noqa: BLE001
        pass
    return None


def _check(job: RemoteLoginJob, reserve_s: float = 0) -> None:
    if job._cancel.is_set():
        raise _Cancelled()
    if time.time() > job.expires_at - reserve_s:
        raise TimeoutError("login did not complete in time (the Browserbase session window)")


def _wait(page, seconds: float) -> None:
    try:
        page.wait_for_timeout(int(seconds * 1000))
    except Exception:  # noqa: BLE001
        time.sleep(seconds)


def _drive_until_logged_in(job: RemoteLoginJob, page, context) -> str:
    """Poll for auth_id, surfacing challenge / 2FA to the human in the live
    view. Never touches a challenge itself."""
    while True:
        _check(job, CAPTURE_RESERVE_S)
        uid = _auth_id(context)
        if uid:
            return uid
        if _detect_challenge(page):
            job.set_state(STATE_CHALLENGE, "human verification required — solve it in the live view")
        elif _detect_otp(page):
            job.set_state(STATE_OTP, "enter the 2FA code in the live view")
        elif job.state != STATE_TYPING:
            job.set_state(STATE_TYPING, "waiting for OnlyFans")
        _wait(page, POLL_S)


def _read_capture(page) -> dict[str, Any] | None:
    try:
        return page.evaluate("() => window.__relayCapture || null")
    except Exception:  # noqa: BLE001
        return None


def _wait_for_capture(job: RemoteLoginJob, page) -> dict[str, Any]:
    """The interceptor's latest signed-request snapshot, waiting for its
    static_param (published on the first sign() call) up to CAPTURE_WAIT_S."""
    required = ("user-id", "x-bc", "x-of-rev", "sign", "time")
    deadline = time.time() + CAPTURE_WAIT_S
    cap = None
    while time.time() < deadline:
        _check(job)
        cap = _read_capture(page)
        hdrs = (cap or {}).get("headers") or {}
        if all(hdrs.get(k) for k in required) and ((cap or {}).get("rules") or {}).get("static_param"):
            return cap
        _wait(page, POLL_S)
    hdrs = (cap or {}).get("headers") or {}
    if not all(hdrs.get(k) for k in required):
        raise RuntimeError("logged in, but the chats page never fired a signed request — try again")
    return cap  # headers only: from_request falls back to a static_param seen at this rev


def _request_from_capture(cap: dict[str, Any], cookies: list[dict], user_agent: str) -> dict[str, Any]:
    """The capture in paste-curl's parsed-request shape, the x-relay-* headers
    being what the extension's Copy cURL adds."""
    h = cap.get("headers") or {}
    rules = cap.get("rules") or {}
    headers = {k: str(h[k]) for k in ("user-id", "x-bc", "x-of-rev", "sign", "time") if h.get(k)}
    headers["user-agent"] = str(h.get("user-agent") or user_agent)
    for key, hdr in (("static_param", "x-relay-static-param"), ("start", "x-relay-sign-start"),
                     ("end", "x-relay-sign-end")):
        if rules.get(key):
            headers[hdr] = str(rules[key])
    return {"url": cap.get("url") or "https://onlyfans.com/api2/v2/users/me",
            "method": "GET", "headers": headers, "cookies": cookies, "data": None}


def _capture_and_persist(job: RemoteLoginJob, page, context) -> None:
    """Bind the proxy, persist through paste-curl's pipeline, run the bootstrap
    endpoint's hooks. The proxy is bound BEFORE anything is persisted: when the
    bind fails nothing is written (one egress)."""
    import proxies as proxy_registry
    import session_bootstrap

    job.set_state(STATE_CAPTURING, "capturing session")
    _goto(page, OF_CHATS)
    cap = _wait_for_capture(job, page)
    cookies = context.cookies(["https://onlyfans.com"])
    try:
        ua = page.evaluate("() => navigator.userAgent")
    except Exception:  # noqa: BLE001
        ua = ""
    parsed = _request_from_capture(cap, cookies, ua)
    uid = parsed["headers"]["user-id"]

    try:
        proxy_registry.assign_account(job.proxy_label, uid)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"proxy bind failed for {job.proxy_label!r}; nothing was saved (one egress)") from e

    try:
        path = session_bootstrap.from_request(
            parsed, nickname=job.nickname, make_active=job.make_active)
    except session_bootstrap.CurlParseError as e:
        raise RuntimeError(f"logged in, but the session could not be built: {e}") from None
    aid = path.parent.name
    with job._lock:
        job.account_id = aid
        job.session_file = path.name

    live_server().post_bootstrap_hooks(aid)
    job.set_state(STATE_DONE, f"session captured; proxy {job.proxy_label} attached for all later traffic")
