#!/usr/bin/env python3
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from brand import BRAND_NAME
import remote_login_decide as decide
from relay_host import live_server
from remote_login_decide import (OTP_ASK, OTP_NOT_TYPED, OTP_REJECTED, OTP_VERIFY_S,  # noqa: F401
                                 STATE_CHALLENGE, STATE_OTP, STATE_TYPING)

log = logging.getLogger("of-relay.remote-login")

HERE = Path(__file__).resolve().parent
INTERCEPTOR_PATH = HERE.parent / "loginExtensionMulti" / "interceptor.js"

BACKEND_LOCAL = "local"
BACKEND_BROWSERBASE = "browserbase"
BACKENDS = (BACKEND_LOCAL, BACKEND_BROWSERBASE)

PROXY_INFLOWWW = "infloww"
PROXY_NONE = "none"
PROXY_CUSTOM = "custom"
PROXY_CHOICES = (PROXY_INFLOWWW, PROXY_NONE, PROXY_CUSTOM)

BROWSERBASE_API = "https://api.browserbase.com/v1"
BB_HTTP_TIMEOUT_S = 30
BB_VIEWPORT = {"width": 1280, "height": 800}


OF_HOME = "https://onlyfans.com/"
OF_CHATS = "https://onlyfans.com/my/chats/"
NAV_TIMEOUT_MS = 45_000

# Browserbase sessions last 300 s: stop short so the job ends with our own error, not a dropped CDP socket.
JOB_WINDOW_S = 285
CAPTURE_WAIT_S = 25
CAPTURE_RESERVE_S = 60
POLL_S = 1.0
JOB_TTL_S = 600
TIMED_OUT = "login did not complete in time (the Browserbase session window)"

STATE_STARTING = "starting"
STATE_CAPTURING = "capturing"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_CANCELLED = "cancelled"
_TERMINAL = {STATE_DONE, STATE_ERROR, STATE_CANCELLED}

# OF renders the login form via JS after domcontentloaded (often late on BB proxies): wait for the fields, never look up once.
FORM_WAIT_S = 30
FIELD_TIMEOUT_MS = 5_000
FILL_ATTEMPTS = 3
_EMAIL_FIELD = 'input[name="email"], input[type="email"], input[autocomplete="username"]'
_PASSWORD_FIELD = 'input[name="password"], input[type="password"]'
_SUBMIT_BUTTON = 'button[type="submit"]'
_OTP_SUBMIT_BUTTON = f"{_SUBMIT_BUTTON}:visible"
_COOKIE_ONLY_NECESSARY = 'button:has-text("Only necessary cookies")'
_OTP_SELECTORS = (
    'input[name="code"]', 'input[autocomplete="one-time-code"]',
    'input[name="otp"]',
)
_OTP_FIELD = ", ".join(f"{s}:visible" for s in _OTP_SELECTORS)
OTP_CODE_RE = re.compile(r"\d{6,8}")
OTP_STEP_TIMEOUT_MS = 2_000
OTP_CHECKING = "checking the 2FA code"

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
    pass


class RemoteLoginConflict(RuntimeError):
    pass


class RemoteLoginExpired(LookupError):
    pass


class _Cancelled(Exception):
    pass


def scrub(text: Any, *secrets: str | None) -> str:
    s = "" if text is None else str(text)
    for secret in sorted({x for x in secrets if x}, key=len, reverse=True):
        s = s.replace(secret, "***")
    return s



@dataclass
class RemoteLoginJob:
    id: str
    email: str
    principal: str | None
    created_at: float
    expires_at: float
    proxy: str = PROXY_INFLOWWW
    proxy_label: str = ""
    proxy_defaulted: bool = False
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
    # Request threads only write the code (submit_otp); only the worker touches the page.
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
        with self._lock:
            if self.state in _TERMINAL:
                return
            self.state, self.message = STATE_OTP, message
            self._otp_code, self._otp_busy = None, False

    def otp_codes(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._otp_seen)

    def forget_otp(self) -> None:
        with self._lock:
            self._otp_code, self._otp_busy = None, False
            self._otp_seen.clear()

    def take_otp(self) -> str | None:
        with self._lock:
            code, self._otp_code = self._otp_code, None
            return code

    def public(self) -> dict[str, Any]:
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



def start_login(*, email: str, password: str, principal: str | None,
                proxy: str = PROXY_INFLOWWW, proxy_label: str = "",
                proxy_defaulted: bool = False,
                nickname: str | None = None, make_active: bool = True,
                backend: str = BACKEND_LOCAL) -> RemoteLoginJob:
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
    bb_env()
    now = time.time()
    job = RemoteLoginJob(
        id=uuid.uuid4().hex, email=email, principal=principal,
        proxy=proxy, proxy_label=proxy_label if proxy == PROXY_CUSTOM else "",
        proxy_defaulted=proxy_defaulted,
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



def _run_login(job: RemoteLoginJob, password: str) -> None:
    def _body(page, context) -> None:
        job.set_state(STATE_TYPING, "entering credentials")
        _type_credentials(page, job.email, password)
        _drive_until_logged_in(job, page, context)
        _capture_and_persist(job, page, context)

    _serve(job, secrets=(password,), body=_body)


def _serve(job: RemoteLoginJob, *, secrets: tuple[str | None, ...],
           body: Callable[[Any, Any], None]) -> None:
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
        if not job.is_terminal():
            job.fail("login ended without capturing a session")
        job.forget_otp()


@contextmanager
def _browserbase_backend(job: RemoteLoginJob):
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
    try:
        page.goto(OF_HOME, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        return (str(e).splitlines() or [type(e).__name__])[0]
    return None



def bb_env() -> tuple[str, str]:
    api_key = os.environ.get("BROWSERBASE_API_KEY")
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID")
    if not api_key:
        raise RuntimeError("BROWSERBASE_API_KEY is not set — cannot start a Browserbase login")
    if not project_id:
        raise RuntimeError("BROWSERBASE_PROJECT_ID is not set — cannot start a Browserbase login")
    return api_key, project_id


def _bb_session_payload(project_id: str) -> dict[str, Any]:
    # Browserbase managed proxies (ours is never sent, bound to the account afterwards); captcha solving OFF (defaults on); laptop viewport so the live view reads on a phone.
    return {
        "projectId": project_id,
        "proxies": True,
        "browserSettings": {"solveCaptchas": False, "viewport": dict(BB_VIEWPORT)},
    }


def _bb_request(path: str, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    api_key, _ = bb_env()
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
    _, project_id = bb_env()
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
        _, project_id = bb_env()
        _bb_request(f"/sessions/{session_id}", "POST",
                    {"projectId": project_id, "status": "REQUEST_RELEASE"})
    except Exception as e:  # noqa: BLE001 — the session times out on its own
        log.info("browserbase release of %s failed: %s", session_id, e)



def _goto(page, url: str, wait_until: str = "domcontentloaded") -> None:
    try:
        page.goto(url, wait_until=wait_until, timeout=NAV_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001 — a slow load; inspect the page anyway
        log.info("navigation to %s did not settle: %s", url, type(e).__name__)


class LoginFormError(RuntimeError):
    pass


def _type_credentials(page, email: str, password: str) -> None:
    fill_login_form(page, email, password)
    submit_login_form(page)


def fill_login_form(page, email: str, password: str, *, wait_s: float = FORM_WAIT_S) -> None:
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
            else:
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
    try:
        while frame.parent_frame is not None:
            el = frame.frame_element()
            try:
                if not el.is_visible():
                    return False
            finally:
                try:
                    el.dispose()
                except Exception:  # noqa: BLE001
                    pass
            frame = frame.parent_frame
    except Exception:  # noqa: BLE001
        return False
    return True


def _detect_otp(page) -> bool:
    try:
        return bool(page.locator(_OTP_FIELD).first.is_visible())
    except Exception:  # noqa: BLE001
        return False


def _auth_id(context) -> str | None:
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
        raise TimeoutError(TIMED_OUT)


def _wait(page, seconds: float) -> None:
    try:
        page.wait_for_timeout(int(seconds * 1000))
    except Exception:  # noqa: BLE001
        time.sleep(seconds)


def _enter_otp(job: RemoteLoginJob, page, code: str) -> bool:
    field = page.locator(_OTP_FIELD).first
    try:
        field.fill(code, timeout=OTP_STEP_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001 — Playwright's message echoes the value
        log.info("filling OnlyFans' 2FA field failed: %s", type(e).__name__)
        return False
    if not _detect_otp(page):
        return True
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
        return True
    _check(job, CAPTURE_RESERVE_S)
    try:
        field.press("Enter", timeout=OTP_STEP_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        log.info("sending OnlyFans' 2FA code failed: %s", type(e).__name__)
        return False
    return True


def _drive_until_logged_in(job: RemoteLoginJob, page, context) -> str:
    state = decide.Drive()
    while True:
        state, eff = decide.login_step(state, _poll(job, page, context), OTP_VERIFY_S)
        if isinstance(eff, decide.TypeCode):
            state, eff = decide.login_step(
                state, decide.Typed(_enter_otp(job, page, eff.code), time.time()), OTP_VERIFY_S)
        if isinstance(eff, decide.Cancel):
            raise _Cancelled()
        if isinstance(eff, decide.Expire):
            raise TimeoutError(TIMED_OUT)
        if isinstance(eff, decide.LoggedIn):
            return eff.uid
        if isinstance(eff, decide.Show):
            job.set_state(eff.state, eff.message)
        elif isinstance(eff, decide.AskAgain):
            job.otp_retry(eff.message)
        _wait(page, POLL_S)


def _poll(job: RemoteLoginJob, page, context) -> decide.Poll:
    now = time.time()
    if job._cancel.is_set():
        return decide.Poll(now, cancel=True)
    if now > job.expires_at - CAPTURE_RESERVE_S:
        return decide.Poll(now, expired=True)
    uid = _auth_id(context)
    if uid:
        return decide.Poll(now, uid=uid)
    if _detect_otp(page):
        return decide.Poll(now, otp=True, code=job.take_otp(), shown=job.state)
    return decide.Poll(now, challenge=_detect_challenge(page), shown=job.state)


def _read_capture(page) -> dict[str, Any] | None:
    try:
        return page.evaluate("() => window.__relayCapture || null")
    except Exception:  # noqa: BLE001
        return None


def _wait_for_capture(job: RemoteLoginJob, page) -> dict[str, Any]:
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
    return cap


def _request_from_capture(cap: dict[str, Any], cookies: list[dict], user_agent: str) -> dict[str, Any]:
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
    import proxies as proxy_registry
    import proxy_health

    if job.proxy_defaulted and job.proxy in (PROXY_INFLOWWW, PROXY_NONE):
        bound = proxy_registry.get_for_account(account_id)
        if bound is not None and not proxy_registry.is_pool(bound):
            with job._lock:
                job.proxy, job.proxy_label = PROXY_CUSTOM, str(bound.get("label") or "")
            return
    if job.proxy == PROXY_INFLOWWW:
        proxy_health.assign_pool(account_id)
    elif job.proxy == PROXY_CUSTOM:
        proxy_registry.assign_account(job.proxy_label, account_id)


def proxy_text(job: RemoteLoginJob) -> str:
    if job.proxy == PROXY_INFLOWWW:
        return f"the {BRAND_NAME} proxy"
    if job.proxy == PROXY_CUSTOM:
        return f"proxy {job.proxy_label}"
    return "no proxy (server IP)"


def _capture_and_persist(job: RemoteLoginJob, page, context) -> None:
    import accounts as account_registry
    import platforms
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

    account_registry.ensure_platform(uid, platforms.ONLYFANS.key)
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
