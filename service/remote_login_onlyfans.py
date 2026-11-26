from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import remote_login as rl

log = logging.getLogger("of-relay.remote-login")

SITE = "OnlyFans"
HOME = "https://onlyfans.com/"
OF_CHATS = "https://onlyfans.com/my/chats/"
INTERCEPTOR_PATH = Path(__file__).resolve().parent.parent / "loginExtensionMulti" / "interceptor.js"

_EMAIL_FIELD = 'input[name="email"], input[type="email"], input[autocomplete="username"]'
_PASSWORD_FIELD = 'input[name="password"], input[type="password"]'
_SUBMIT_BUTTON = 'button[type="submit"]'
_COOKIE_ONLY_NECESSARY = 'button:has-text("Only necessary cookies")'
_OTP_SELECTORS = (
    'input[name="code"]', 'input[autocomplete="one-time-code"]',
    'input[name="otp"]',
)
OTP_FIELD = ", ".join(f"{s}:visible" for s in _OTP_SELECTORS)
OTP_SUBMIT_BUTTON = f"{_SUBMIT_BUTTON}:visible"
_SIGNED = ("user-id", "x-bc", "x-of-rev", "sign", "time")

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


def init_scripts() -> tuple[str, ...]:
    return (_CAPTURE_LISTENER_JS, INTERCEPTOR_PATH.read_text(encoding="utf-8"))


def fill_login_form(page, email: str, password: str, *, wait_s: float = rl.FORM_WAIT_S) -> None:
    em = page.locator(_EMAIL_FIELD).first
    pw = page.locator(_PASSWORD_FIELD).first
    rl.await_form(page, em, SITE, wait_s)
    _dismiss_cookie_banner(page)
    rl.fill_verified(em, email, "email", SITE)
    rl.fill_verified(pw, password, "password", SITE)


def _dismiss_cookie_banner(page) -> None:
    try:
        btn = page.locator(_COOKIE_ONLY_NECESSARY).first
        if btn.is_visible():
            btn.click(timeout=rl.FIELD_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass


def submit_login_form(page) -> None:
    try:
        page.locator(_SUBMIT_BUTTON).first.click(timeout=rl.FIELD_TIMEOUT_MS)
        return
    except Exception as e:  # noqa: BLE001
        log.info("clicking OnlyFans' LOG IN failed: %s", type(e).__name__)
    try:
        page.locator(_PASSWORD_FIELD).first.press("Enter", timeout=rl.FIELD_TIMEOUT_MS)
    except Exception as e:  # noqa: BLE001
        log.info("pressing Enter in OnlyFans' password field failed: %s", type(e).__name__)


def login_error(page) -> str | None:
    return None


def logged_in(page, context) -> str | None:
    return auth_id(context)


def auth_id(context) -> str | None:
    try:
        for c in context.cookies(["https://onlyfans.com"]):
            if c.get("name") == "auth_id" and c.get("value"):
                return c["value"]
    except Exception:  # noqa: BLE001
        pass
    return None


def _read_capture(page) -> dict[str, Any] | None:
    try:
        return page.evaluate("() => window.__relayCapture || null")
    except Exception:  # noqa: BLE001
        return None


def wait_for_capture(job: rl.RemoteLoginJob, page) -> dict[str, Any]:
    deadline = time.time() + rl.CAPTURE_WAIT_S
    cap = None
    while time.time() < deadline:
        rl.check(job)
        cap = _read_capture(page)
        hdrs = (cap or {}).get("headers") or {}
        if all(hdrs.get(k) for k in _SIGNED) and ((cap or {}).get("rules") or {}).get("static_param"):
            return cap
        rl.wait(page, rl.POLL_S)
    hdrs = (cap or {}).get("headers") or {}
    if not all(hdrs.get(k) for k in _SIGNED):
        raise RuntimeError("logged in, but the chats page never fired a signed request — try again")
    return cap


def request_from_capture(cap: dict[str, Any], cookies: list[dict], user_agent: str) -> dict[str, Any]:
    h = cap.get("headers") or {}
    rules = cap.get("rules") or {}
    headers = {k: str(h[k]) for k in _SIGNED if h.get(k)}
    headers["user-agent"] = str(h.get("user-agent") or user_agent)
    for key, hdr in (("static_param", "x-relay-static-param"), ("start", "x-relay-sign-start"),
                     ("end", "x-relay-sign-end")):
        if rules.get(key):
            headers[hdr] = str(rules[key])
    return {"url": cap.get("url") or "https://onlyfans.com/api2/v2/users/me",
            "method": "GET", "headers": headers, "cookies": cookies, "data": None}


def capture(job: rl.RemoteLoginJob, page, context) -> tuple[str, dict[str, Any]]:
    rl.goto(page, OF_CHATS)
    cap = wait_for_capture(job, page)
    cookies = context.cookies(["https://onlyfans.com"])
    try:
        ua = page.evaluate("() => navigator.userAgent")
    except Exception:  # noqa: BLE001
        ua = ""
    parsed = request_from_capture(cap, cookies, ua)
    return parsed["headers"]["user-id"], parsed


def claim(parsed: dict[str, Any]) -> dict[str, Any]:
    import accounts as account_registry
    import platforms

    account_registry.ensure_platform(parsed["headers"]["user-id"], platforms.ONLYFANS.key)
    return parsed


def save(job: rl.RemoteLoginJob, parsed: dict[str, Any]) -> Path:
    import session_bootstrap

    try:
        return session_bootstrap.from_request(parsed, nickname=job.nickname, make_active=job.make_active)
    except session_bootstrap.CurlParseError as e:
        raise RuntimeError(f"logged in, but the session could not be built: {e}") from None
