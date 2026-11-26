from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

import fansly_backend
import remote_login as rl

log = logging.getLogger("of-relay.remote-login")

SITE = "Fansly"
HOME = "https://fansly.com/"

_GATES = (re.compile(r"^\s*enter\s*$", re.I), re.compile(r"^\s*essential only\s*$", re.I))
_LOGIN_TAB = re.compile(r"^\s*log\s*in\s*$", re.I)
_SIGN_IN = re.compile(r"^\s*sign\s*in\s*$", re.I)
_USER_LABEL = re.compile(r"username or e-?mail", re.I)
_USER_CSS = ", ".join(f"{s}:visible" for s in (
    'input[autocomplete="username"]', 'input[type="email"]', 'input[name*="user" i]',
    'input[name*="email" i]',
))
_PASSWORD_FIELD = 'input[type="password"]:visible'
_OTP_SELECTORS = (
    'input[autocomplete="one-time-code"]', 'input[name="code"]', 'input[name="otp"]',
    'input[name*="twofa" i]', 'input[name*="2fa" i]',
)
OTP_FIELD = ", ".join(f"{s}:visible" for s in _OTP_SELECTORS)
OTP_SUBMIT_BUTTON = 'button[type="submit"]:visible'
_REFUSED = re.compile(r"(invalid|incorrect|wrong)[^.\n]{0,40}(password|username|credentials|login)", re.I)

_READ_JS = r"""
() => {
  const parseQuotingSnowflakeIds = (raw) =>
    JSON.parse(String(raw).replace(/:(\s*)(-?\d{16,})(\s*[,}\]])/g, ':$1"$2"$3'));
  let session = null, device = null;
  try {
    const s = parseQuotingSnowflakeIds(localStorage.getItem("session_active_session"));
    if (s && typeof s === "object") session = s;
  } catch (_) {}
  try {
    const raw = localStorage.getItem("device_device_id");
    if (raw != null) device = String(raw).trim().replace(/^"+|"+$/g, "") || null;
  } catch (_) {}
  return { session, device_id: device, user_agent: navigator.userAgent || "" };
}
"""


def init_scripts() -> tuple[str, ...]:
    return ()


def _sign_in(page):
    return page.get_by_text(_SIGN_IN).filter(visible=True)


def _pass_gates(page) -> None:
    for gate in _GATES:
        try:
            button = page.get_by_text(gate).filter(visible=True)
            if button.count():
                button.first.click(timeout=rl.FIELD_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            log.info("passing a Fansly gate failed: %s", type(e).__name__)


def _open_login(page, wait_s: float) -> None:
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        _pass_gates(page)
        if any(rl.visible(page, lambda p: p.get_by_text(gate).filter(visible=True)) for gate in _GATES):
            rl.wait(page, rl.POLL_S)
            continue
        if rl.visible(page, _sign_in):
            return
        try:
            tabs = page.get_by_text(_LOGIN_TAB).filter(visible=True)
            if tabs.count():
                tabs.last.click(timeout=rl.FIELD_TIMEOUT_MS)
        except Exception as e:  # noqa: BLE001
            log.info("opening Fansly's Login tab failed: %s", type(e).__name__)
        rl.wait(page, rl.POLL_S)
    raise rl.form_missing(page, SITE, wait_s)


def _user_field(page):
    return (page.get_by_label(_USER_LABEL).or_(page.get_by_placeholder(_USER_LABEL))
            .filter(visible=True).or_(page.locator(_USER_CSS)).first)


def fill_login_form(page, email: str, password: str, *, wait_s: float = rl.FORM_WAIT_S) -> None:
    _open_login(page, wait_s)
    user = _user_field(page)
    rl.await_form(page, user, SITE, rl.FIELD_TIMEOUT_MS / 1000)
    rl.fill_verified(user, email, "username or email", SITE)
    rl.fill_verified(page.locator(_PASSWORD_FIELD).first, password, "password", SITE)


def submit_login_form(page) -> None:
    try:
        _sign_in(page).first.click(timeout=rl.FIELD_TIMEOUT_MS)
        return
    except Exception as e:  # noqa: BLE001
        log.info("clicking Fansly's Sign In failed: %s", type(e).__name__)
    try:
        page.locator(_PASSWORD_FIELD).first.press("Enter", timeout=rl.FIELD_TIMEOUT_MS)
    except Exception:
        raise rl.LoginFormError("Couldn't submit Fansly's sign-in form; try again") from None


def login_error(page) -> str | None:
    if not rl.visible(page, _sign_in):
        return None
    try:
        text = page.evaluate("() => (document.body && document.body.innerText) || ''")
    except Exception:  # noqa: BLE001
        return None
    return next((line.strip()[:120] for line in (text or "").splitlines() if _REFUSED.search(line)), None)


def _read(page) -> dict[str, Any]:
    try:
        got = page.evaluate(_READ_JS)
    except Exception:  # noqa: BLE001
        return {}
    return got if isinstance(got, dict) else {}


def _text(v: Any) -> str:
    return "" if v is None else str(v)


def logged_in(page, context) -> str | None:
    s = _read(page).get("session") or {}
    if not s.get("token") or rl.visible(page, OTP_FIELD) or rl.visible(page, _sign_in):
        return None
    return _text(s.get("accountId") or s.get("account_id")) or None


def session_from(read: dict[str, Any]) -> dict[str, Any]:
    s = read.get("session") or {}
    token = _text(s.get("token"))
    account_id = _text(s.get("accountId") or s.get("account_id"))
    user_agent = _text(read.get("user_agent"))
    if not token:
        raise RuntimeError("logged in, but Fansly's session holds no token — try again")
    if not account_id:
        raise RuntimeError("logged in, but Fansly's session holds no account id — try again")
    if not user_agent:
        raise RuntimeError("logged in, but the browser reported no user agent — try again")
    return fansly_backend.session_blob(
        token=token, session_id=_text(s.get("id")) or None, account_id=account_id,
        device_id=_text(s.get("deviceId") or s.get("device_id") or read.get("device_id")) or None,
        user_agent=user_agent,
    )


def capture(job: rl.RemoteLoginJob, page, context) -> tuple[str, dict[str, Any]]:
    read = _read(page)
    job.hide(_text((read.get("session") or {}).get("token")))
    session = session_from(read)
    return session["accountId"], session


def claim(session: dict[str, Any]) -> tuple[dict, dict]:
    return fansly_backend.prove(session)


def save(job: rl.RemoteLoginJob, claimed: tuple[dict, dict]) -> Path:
    me, session = claimed
    return fansly_backend.save(session, me, nickname=job.nickname, make_active=job.make_active)
