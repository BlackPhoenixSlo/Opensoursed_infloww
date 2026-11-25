from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

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
    otp_sent_at: Optional[float] = None


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
        # The prompt is (back) on screen.
        if ev.shown != STATE_OTP:
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
