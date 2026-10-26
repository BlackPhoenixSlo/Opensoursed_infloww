#!/usr/bin/env python3
"""
Served OnlyFans login in a remote browser, a human solving every challenge.

Built from an earlier direct-login prototype, with its two halves reshaped
for this repo:

  * The browser runs on Browserbase. The relay creates a Browserbase session,
    drives it over CDP (Playwright `connect_over_cdp`, so no Chromium on this
    host), types the creator's email + password into OnlyFans' real form, and
    hands the operator Browserbase's own LIVE VIEW (an interactive page of the
    remote browser). When OnlyFans shows Cloudflare / a captcha, a HUMAN solves
    it there. Browserbase's captcha solver is forced off. A 2FA prompt can be
    answered either in the live view or by POSTing the code
    (`RemoteLoginJob.submit_otp`); the job's own thread types it into
    OnlyFans' code field, since only that thread drives the page.
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
Browserbase. The account's proxy is the Add creator flow's Proxy selection,
bound the way the paste-curl path binds it (`bind_proxy`): the Inflowwww proxy
through `proxies.assign_pool`, a custom proxy through `proxies.assign_account`
(the registry calls behind POST /admin/proxy-pool/assign and /admin/proxies/
assign), or nothing for No proxy. It is bound BEFORE the session is saved, so
every later relay call for the account egresses through it. A session that
can't be created, or an OnlyFans page that won't load, fails loudly.

SECRETS. BROWSERBASE_API_KEY / BROWSERBASE_PROJECT_ID come from the env only.
The OnlyFans password lives as a local of the worker thread, is never stored
on the job, and `scrub()` strips it from every job message, error and log line.
A submitted 2FA code waits in the job's private slot until the worker takes it
(then only the worker's local holds it); it is never logged and never in the
status. Every code taken is scrubbed from the job's error, and the job forgets
them all when it ends.

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
import re
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

# The Add creator flow's Proxy selection (app: creatorFlow.ProxyChoice).
PROXY_INFLOWWW = "infloww"   # the relay's env pool (never named to the client)
PROXY_NONE = "none"          # the relay's own server IP; nothing is bound
PROXY_CUSTOM = "custom"      # one of the user's proxies, by label
PROXY_CHOICES = (PROXY_INFLOWWW, PROXY_NONE, PROXY_CUSTOM)

BROWSERBASE_API = "https://api.browserbase.com/v1"
BB_HTTP_TIMEOUT_S = 30
BB_VIEWPORT = {"width": 1280, "height": 800}


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

# OnlyFans login DOM. The form is rendered by OnlyFans' JS AFTER
# domcontentloaded (on Browserbase's managed proxies it is often not there yet),
# so the fields are waited for, never looked up once. The email input is
# type="text", name="email".
FORM_WAIT_S = 30          # the login form must show within this
FIELD_TIMEOUT_MS = 5_000  # one fill / read / click attempt
FILL_ATTEMPTS = 3         # fill, then retype key by key, verifying each time
_EMAIL_FIELD = 'input[name="email"], input[type="email"], input[autocomplete="username"]'
_PASSWORD_FIELD = 'input[name="password"], input[type="password"]'
_SUBMIT_BUTTON = 'button[type="submit"]'
# The 2FA form's own submit button, when it shows one.
_OTP_SUBMIT_BUTTON = f"{_SUBMIT_BUTTON}:visible"
# The cookie banner OnlyFans shows some egresses (EU): decline the optional ones.
_COOKIE_ONLY_NECESSARY = 'button:has-text("Only necessary cookies")'
_OTP_SELECTORS = (
    'input[name="code"]', 'input[autocomplete="one-time-code"]',
    'input[name="otp"]',
)
# The visible one: a stale hidden code input left in the DOM is neither a
# prompt nor where the code is typed.
_OTP_FIELD = ", ".join(f"{s}:visible" for s in _OTP_SELECTORS)
OTP_CODE_RE = re.compile(r"\d{6,8}")
# After a submitted code: still on the 2FA prompt this long (no auth_id), the
# operator is asked again. A timer, not an OnlyFans answer, hence the wording.
OTP_VERIFY_S = 15
OTP_STEP_TIMEOUT_MS = 2_000  # one fill / read / press on the 2FA field: short, so cancel is seen
OTP_ASK = "OnlyFans asks for the 2FA code — enter it here or in the live view"
OTP_CHECKING = "checking the 2FA code"
OTP_REJECTED = "OnlyFans didn't accept that code (or hasn't answered yet) — try again"
OTP_NOT_TYPED = "couldn't type the 2FA code — try again or type it in the live view"

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


class RemoteLoginExpired(LookupError):
    """The job is past its window: it takes no code (HTTP 404, as an expired job)."""


class _Cancelled(Exception):
    pass


def scrub(text: Any, *secrets: str | None) -> str:
    """`text` with every non-empty secret replaced by ***, longest first (a
    code inside another code or the password leaves no part of either)."""
    s = "" if text is None else str(text)
    for secret in sorted({x for x in secrets if x}, key=len, reverse=True):
        s = s.replace(secret, "***")
    return s


# ── Job ─────────────────────────────────────────────────────────────────────

@dataclass
class RemoteLoginJob:
    id: str
    email: str
    principal: str | None
    created_at: float
    expires_at: float
    proxy: str = PROXY_INFLOWWW
    proxy_label: str = ""   # PROXY_CUSTOM only
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
    # A 2FA code the operator submitted, until the worker takes it. Request
    # threads only write it (submit_otp); only the worker touches the page.
    # _otp_busy: a code is pending or being checked (cleared when the job asks
    # again or leaves the prompt); _otp_seen: every code taken, for scrub().
    _otp_code: str | None = field(default=None, repr=False)
    _otp_busy: bool = field(default=False, repr=False)
    _otp_seen: set[str] = field(default_factory=set, repr=False)

    def set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            if self.state in _TERMINAL:
                return
            self.state = state
            if message:
                self.message = message
            if state != STATE_OTP:
                self._otp_code, self._otp_busy = None, False
            if state in _TERMINAL:
                self.finished_at = time.time()

    def fail(self, message: str) -> None:
        with self._lock:
            self.state = STATE_ERROR
            self.error = message
            self.message = message
            self.finished_at = time.time()
            self._otp_code, self._otp_busy = None, False

    def is_terminal(self) -> bool:
        return self.state in _TERMINAL

    def submit_otp(self, code: str) -> None:
        """Queue a 2FA code for the worker to type; the status says it is being
        checked. Spaces and dashes ("123 456", "123-456") are dropped first.
        ValueError: not 6-8 digits; RemoteLoginConflict: the job is not on the
        2FA prompt, or a code is already pending or being checked;
        RemoteLoginExpired: past expires_at - CAPTURE_RESERVE_S (the worker types
        no code then), checked under the lock so a code is never queued late."""
        code = re.sub(r"[\s-]", "", code or "")
        if not OTP_CODE_RE.fullmatch(code):
            raise ValueError("the 2FA code is 6 to 8 digits")
        with self._lock:
            if time.time() > self.expires_at - CAPTURE_RESERVE_S:
                raise RemoteLoginExpired("no such login job (expired?)")
            if self.state != STATE_OTP:
                raise RemoteLoginConflict(f"the login is not waiting for a 2FA code (state: {self.state})")
            if self._otp_busy:
                raise RemoteLoginConflict("a code is already being checked")
            self._otp_code, self._otp_busy = code, True
            self._otp_seen.add(code)
            self.message = OTP_CHECKING

    def otp_retry(self, message: str) -> None:
        """Still on the 2FA prompt: ask for a code again (worker thread)."""
        with self._lock:
            if self.state in _TERMINAL:
                return
            self.state, self.message = STATE_OTP, message
            self._otp_code, self._otp_busy = None, False

    def otp_codes(self) -> tuple[str, ...]:
        """Every 2FA code submitted to this job, for scrub()."""
        with self._lock:
            return tuple(self._otp_seen)

    def forget_otp(self) -> None:
        """Drop every code (the job has ended; it stays readable JOB_TTL_S)."""
        with self._lock:
            self._otp_code, self._otp_busy = None, False
            self._otp_seen.clear()

    def take_otp(self) -> str | None:
        """The pending 2FA code, emptying the slot (worker thread only)."""
        with self._lock:
            code, self._otp_code = self._otp_code, None
            return code

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
                "proxy": self.proxy,
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

def start_login(*, email: str, password: str, principal: str | None,
                proxy: str = PROXY_INFLOWWW, proxy_label: str = "",
                nickname: str | None = None, make_active: bool = True,
                backend: str = BACKEND_LOCAL) -> RemoteLoginJob:
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
    if proxy not in PROXY_CHOICES:
        raise ValueError(f"unknown proxy choice {proxy!r} (expected one of {PROXY_CHOICES})")
    if proxy == PROXY_CUSTOM and not proxy_label:
        raise ValueError("a custom proxy needs its label")
    _bb_env()  # fail before a job exists when the env is not set
    now = time.time()
    job = RemoteLoginJob(
        id=uuid.uuid4().hex, email=email, principal=principal,
        proxy=proxy, proxy_label=proxy_label if proxy == PROXY_CUSTOM else "",
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
        msg = scrub(f"{type(e).__name__}: {e}", *secrets, *job.otp_codes())
        log.warning("remote login %s failed: %s", job.id, msg)
        job.fail(msg)
    finally:
        if not job.is_terminal():  # body returned without reaching a final state
            job.fail("login ended without capturing a session")
        job.forget_otp()  # the error is scrubbed: the job keeps no code once it ends


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
    never sent to Browserbase; it is bound to the account afterwards),
    automated captcha solving OFF (it defaults to on), and a common laptop
    viewport, so the live view stays readable on a phone (the default is
    2560x1440)."""
    return {
        "projectId": project_id,
        "proxies": True,
        "browserSettings": {"solveCaptchas": False, "viewport": dict(BB_VIEWPORT)},
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


class LoginFormError(RuntimeError):
    """OnlyFans' login form could not be filled. The message never carries
    the typed values."""


def _type_credentials(page, email: str, password: str) -> None:
    fill_login_form(page, email, password)
    submit_login_form(page)


def fill_login_form(page, email: str, password: str, *, wait_s: float = FORM_WAIT_S) -> None:
    """Wait for OnlyFans' login form, decline the optional cookies, type the
    email and the password, and verify each field holds exactly what was typed
    (retyping it when not). Raises LoginFormError instead of leaving the job
    sitting on a half-filled form."""
    em = page.locator(_EMAIL_FIELD).first
    pw = page.locator(_PASSWORD_FIELD).first
    try:
        em.wait_for(state="visible", timeout=int(wait_s * 1000))
    except Exception:  # noqa: BLE001
        why = " (a human-verification challenge is on screen)" if _detect_challenge(page) else ""
        raise LoginFormError(f"the OnlyFans login form did not appear within {wait_s:.0f}s{why}") from None
    _dismiss_cookie_banner(page)
    _fill_verified(em, email, "email")
    _fill_verified(pw, password, "password")


def _dismiss_cookie_banner(page) -> None:
    """Best effort: the banner does not block the form, it only crowds the
    live view."""
    try:
        btn = page.locator(_COOKIE_ONLY_NECESSARY).first
        if btn.is_visible():
            btn.click(timeout=FIELD_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass


def _fill_verified(field, value: str, what: str) -> None:
    for attempt in range(FILL_ATTEMPTS):
        try:
            if attempt == 0:
                field.fill(value, timeout=FIELD_TIMEOUT_MS)
            else:  # the page swallowed the fill: clear and type key by key
                field.click(timeout=FIELD_TIMEOUT_MS)
                field.fill("", timeout=FIELD_TIMEOUT_MS)
                field.press_sequentially(value, delay=30, timeout=FIELD_TIMEOUT_MS * 4)
            if field.input_value(timeout=FIELD_TIMEOUT_MS) == value:
                return
        except Exception as e:  # noqa: BLE001 — Playwright's message echoes the value
            log.info("filling the OnlyFans %s field, attempt %d: %s",
                     what, attempt + 1, type(e).__name__)
    raise LoginFormError(f"couldn't fill the OnlyFans {what} field — the login form did not take it")


def submit_login_form(page) -> None:
    """Click LOG IN (enabled once both fields hold a value), else press Enter
    in the password field. A failed submit is left to the human in the live
    view."""
    try:
        page.locator(_SUBMIT_BUTTON).first.click(timeout=FIELD_TIMEOUT_MS)
        return
    except Exception as e:  # noqa: BLE001
        log.info("clicking OnlyFans' LOG IN failed: %s", type(e).__name__)
    try:
        page.locator(_PASSWORD_FIELD).first.press("Enter", timeout=FIELD_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        log.info("pressing Enter in OnlyFans' password field failed: %s", type(e).__name__)


def _detect_challenge(page) -> bool:
    """A human-verification challenge is ON SCREEN: Cloudflare interstitial
    text / elements, or a Turnstile / reCAPTCHA / hCaptcha / GeeTest frame.
    Only visible ones count: a hidden widget or frame (reCAPTCHA parks its
    challenge frame hidden on the page) is nothing for the human to solve."""
    try:
        if page.evaluate(
            """() => {
                const t = (document.body && document.body.innerText || '').toLowerCase();
                if (t.includes('just a moment') || t.includes('verify you are human')
                    || t.includes('checking your browser')) return true;
                const shown = (el) => {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
                };
                return [...document.querySelectorAll(
                    '#challenge-running, #challenge-stage, #challenge-form, .cf-turnstile')].some(shown);
            }"""
        ):
            return True
    except Exception:  # noqa: BLE001
        pass
    needles = ("turnstile", "recaptcha", "hcaptcha", "geetest", "challenges.cloudflare")
    try:
        return any(any(n in (f.url or "").lower() for n in needles) and _frame_on_screen(f)
                   for f in page.frames)
    except Exception:  # noqa: BLE001
        return False


def _frame_on_screen(frame) -> bool:
    """`frame`'s own <iframe> element, and each one it sits in, is visible
    (the page's main frame always is). A detached frame is not."""
    try:
        while frame.parent_frame is not None:
            el = frame.frame_element()
            try:
                if not el.is_visible():
                    return False
            finally:  # checked every poll: release the handle
                try:
                    el.dispose()
                except Exception:  # noqa: BLE001
                    pass
            frame = frame.parent_frame
    except Exception:  # noqa: BLE001
        return False
    return True


def _detect_otp(page) -> bool:
    """A VISIBLE 2FA code field is on screen (a stale hidden input is no prompt)."""
    try:
        return bool(page.locator(_OTP_FIELD).first.is_visible())
    except Exception:  # noqa: BLE001
        return False


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


def _enter_otp(job: RemoteLoginJob, page, code: str) -> bool:
    """Type `code` into OnlyFans' 2FA field (one attempt, short timeouts, so a
    cancel is seen within seconds) and send it: click the visible submit
    button of the field's own form (never the page's first one: that could be
    the login form), or press Enter in the field when its form shows none or
    the button won't take the click (covered). A field gone after the fill
    submitted itself on the last digit: the code is in, and OTP_VERIFY_S
    decides. False when the field would not take the code, or neither the
    button nor Enter could send it."""
    field = page.locator(_OTP_FIELD).first
    try:
        field.fill(code, timeout=OTP_STEP_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001 — Playwright's message echoes the value
        log.info("filling OnlyFans' 2FA field failed: %s", type(e).__name__)
        return False
    if not _detect_otp(page):
        return True  # the form sent itself
    try:
        if field.input_value(timeout=OTP_STEP_TIMEOUT_MS) != code:
            return False
    except Exception as e:  # noqa: BLE001
        log.info("reading OnlyFans' 2FA field failed: %s", type(e).__name__)
        return not _detect_otp(page)
    _check(job, CAPTURE_RESERVE_S)
    try:
        button = field.locator("xpath=ancestor::form").locator(_OTP_SUBMIT_BUTTON).first
        if button.count():
            button.click(timeout=OTP_STEP_TIMEOUT_MS)
            return True
    except Exception as e:  # noqa: BLE001
        log.info("clicking OnlyFans' 2FA submit button failed: %s", type(e).__name__)
    if not _detect_otp(page):
        return True  # the click went through after all
    _check(job, CAPTURE_RESERVE_S)  # a cancel or the deadline during the click's wait: no Enter
    try:
        field.press("Enter", timeout=OTP_STEP_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        log.info("sending OnlyFans' 2FA code failed: %s", type(e).__name__)
        return False
    return True


def _drive_until_logged_in(job: RemoteLoginJob, page, context) -> str:
    """Poll for auth_id, surfacing challenge / 2FA to the human in the live
    view. Never touches a challenge itself. On the 2FA prompt, a code the
    operator submitted (job.submit_otp) is typed in; when OnlyFans still shows
    the prompt OTP_VERIFY_S later, or shows it again sooner, the job asks for
    the code again (OTP_REJECTED). A visible 2FA field wins over any captcha
    frame beside it."""
    otp_sent_at: float | None = None
    while True:
        _check(job, CAPTURE_RESERVE_S)
        uid = _auth_id(context)
        if uid:
            return uid
        if _detect_otp(page):
            code = job.take_otp()
            if code is not None:
                if _enter_otp(job, page, code):
                    otp_sent_at = time.time()
                else:
                    otp_sent_at = None
                    job.otp_retry(OTP_NOT_TYPED)
            elif job.state != STATE_OTP:  # the prompt is (back) on screen
                sent_lately = otp_sent_at is not None and time.time() - otp_sent_at < OTP_VERIFY_S
                otp_sent_at = None
                job.set_state(STATE_OTP, OTP_REJECTED if sent_lately else OTP_ASK)
            elif otp_sent_at is not None and time.time() - otp_sent_at >= OTP_VERIFY_S:
                otp_sent_at = None
                job.otp_retry(OTP_REJECTED)
        elif _detect_challenge(page):  # otp_sent_at kept: a captcha between a code and the prompt again
            job.set_state(STATE_CHALLENGE, "human verification required — solve it in the live view")
        else:  # otp_sent_at kept: the prompt coming back soon means the code was not taken
            if job.state != STATE_TYPING:
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


def bind_proxy(job: RemoteLoginJob, account_id: str) -> None:
    """Bind the flow's proxy choice to `account_id` with the registry calls
    the paste-curl path's attach step makes: POST /admin/proxy-pool/assign
    (`assign_pool`: kept if already on the pool, else the least-used) and
    POST /admin/proxies/assign (`assign_account`). No proxy binds nothing, so
    a re-login keeps whatever the account is on."""
    import proxies as proxy_registry

    if job.proxy == PROXY_INFLOWWW:
        proxy_registry.assign_pool(account_id)
    elif job.proxy == PROXY_CUSTOM:
        proxy_registry.assign_account(job.proxy_label, account_id)


def proxy_text(job: RemoteLoginJob) -> str:
    if job.proxy == PROXY_INFLOWWW:
        return "the Inflowwww proxy"
    if job.proxy == PROXY_CUSTOM:
        return f"proxy {job.proxy_label}"
    return "no proxy (server IP)"


def _capture_and_persist(job: RemoteLoginJob, page, context) -> None:
    """Bind the proxy, persist through paste-curl's pipeline, run the bootstrap
    endpoint's hooks. The proxy is bound BEFORE anything is persisted: when the
    bind fails nothing is written (one egress)."""
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
        bind_proxy(job, uid)
    except Exception as e:  # noqa: BLE001
        import proxies as proxy_registry
        why = proxy_registry.scrub_pool_secrets(str(e))
        raise RuntimeError(
            f"binding {proxy_text(job)} failed ({why}); nothing was saved (one egress)") from e

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
    job.set_state(STATE_DONE, (
        "session captured; no proxy attached (server IP)" if job.proxy == PROXY_NONE
        else f"session captured; {proxy_text(job)} attached for all later traffic"))
