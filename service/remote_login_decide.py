"""
Browserbase login's wait-for-login rules as ONE pure transition:

    login_step(state, event) -> (state', effect)

No I/O, no clock, no logging, stdlib only. remote_login._drive_until_logged_in is
the shell: once per poll it reads the page (Poll), performs the one effect, and
after typing a code reports how it went (Typed).

Events:
  Poll(now, cancel, expired, uid, otp, code, challenge, shown)
                        one look at the job and the page. cancel: the operator
                        cancelled; expired: past expires_at - CAPTURE_RESERVE_S;
                        uid: OnlyFans' auth_id cookie (logged in); otp: a visible
                        2FA field; code: the operator's pending code, taken from
                        the job (only while otp); challenge: a captcha on screen;
                        shown: the job's state as the operator sees it. A signal
                        the shell had no need to read (an earlier one decided) is
                        False / None.
  Typed(ok, at)         the code was typed and sent (ok) or not, at `at`

Effects (exactly one):
  Cancel                raise _Cancelled
  Expire                raise TimeoutError (the Browserbase session window)
  LoggedIn(uid)         return uid: the capture runs next
  TypeCode(code)        type `code` into the 2FA field, then send Typed
  Show(state, message)  job.set_state(state, message)
  AskAgain(message)     job.otp_retry(message): still on the prompt, a new code
  Idle                  nothing to do; wait POLL_S

A code is judged by a timer, not by OnlyFans: still on the prompt OTP_VERIFY_S
after it was sent, or the prompt shown again (the job had left STATE_OTP) sooner,
means rejected. A visible 2FA field wins over a captcha beside it; a captcha keeps
the sent-at stamp (a captcha between a code and the prompt again).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# remote_login imports these (its job states and the operator's wording).
STATE_TYPING = "typing"
STATE_CHALLENGE = "challenge"
STATE_OTP = "otp"
OTP_VERIFY_S = 15
OTP_ASK = "OnlyFans asks for the 2FA code — enter it here or in the live view"
OTP_REJECTED = "OnlyFans didn't accept that code (or hasn't answered yet) — try again"
OTP_NOT_TYPED = "couldn't type the 2FA code — try again or type it in the live view"
CHALLENGE_MSG = "human verification required — solve it in the live view"
TYPING_MSG = "waiting for OnlyFans"


@dataclass(frozen=True)
class Drive:
    otp_sent_at: Optional[float] = None  # when the last code went in; None: none pending


@dataclass(frozen=True)
class Poll:
    now: float
    cancel: bool = False
    expired: bool = False
    uid: Optional[str] = None
    otp: bool = False
    code: Optional[str] = None
    challenge: bool = False
    shown: str = ""


@dataclass(frozen=True)
class Typed:
    ok: bool
    at: float


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class Expire:
    pass


@dataclass(frozen=True)
class LoggedIn:
    uid: str


@dataclass(frozen=True)
class TypeCode:
    code: str


@dataclass(frozen=True)
class Show:
    state: str
    message: str


@dataclass(frozen=True)
class AskAgain:
    message: str


@dataclass(frozen=True)
class Idle:
    pass


Event = Union[Poll, Typed]
Effect = Union[Cancel, Expire, LoggedIn, TypeCode, Show, AskAgain, Idle]


def login_step(state: Drive, ev: Event, verify_s: float = OTP_VERIFY_S) -> tuple[Drive, Effect]:
    if isinstance(ev, Typed):
        return (Drive(ev.at), Idle()) if ev.ok else (Drive(None), AskAgain(OTP_NOT_TYPED))
    if ev.cancel:
        return state, Cancel()
    if ev.expired:
        return state, Expire()
    if ev.uid:
        return state, LoggedIn(ev.uid)
    sent = state.otp_sent_at
    if ev.otp:
        if ev.code is not None:
            return state, TypeCode(ev.code)
        if ev.shown != STATE_OTP:  # the prompt is (back) on screen
            lately = sent is not None and ev.now - sent < verify_s
            return Drive(None), Show(STATE_OTP, OTP_REJECTED if lately else OTP_ASK)
        if sent is not None and ev.now - sent >= verify_s:
            return Drive(None), AskAgain(OTP_REJECTED)
        return state, Idle()
    if ev.challenge:
        return state, Show(STATE_CHALLENGE, CHALLENGE_MSG)
    if ev.shown != STATE_TYPING:
        return state, Show(STATE_TYPING, TYPING_MSG)
    return state, Idle()
