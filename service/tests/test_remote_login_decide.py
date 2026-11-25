from __future__ import annotations

import _harness

_harness.bootstrap()

import remote_login  # noqa: E402
from remote_login_decide import (CHALLENGE_MSG, OTP_ASK, OTP_NOT_TYPED, OTP_REJECTED, OTP_VERIFY_S,  # noqa: E402
                                 STATE_CHALLENGE, STATE_OTP, STATE_TYPING, TYPING_MSG, AskAgain, Cancel,
                                 Drive, Expire, Idle, LoggedIn, Poll, Show, Typed, TypeCode, login_step)

T = 1000.0


def case_terminal_signals_win() -> None:
    for st in (Drive(), Drive(T - 3)):
        for ev, eff in [
            (Poll(T, cancel=True, expired=True, uid="7"), Cancel()),
            (Poll(T, expired=True, uid="7", otp=True, code="123456"), Expire()),
            (Poll(T, uid="7", otp=True, code="123456", challenge=True), LoggedIn("7")),
        ]:
            assert login_step(st, ev) == (st, eff), (st, ev)


def case_otp_prompt() -> None:
    v = OTP_VERIFY_S
    assert v == remote_login.OTP_VERIFY_S == 15
    for sent, code, shown, now, after, eff in [
        (None, "123456", STATE_OTP, T, None, TypeCode("123456")),
        (T - 1, "654321", STATE_TYPING, T, T - 1, TypeCode("654321")),
        (None, None, STATE_TYPING, T, None, Show(STATE_OTP, OTP_ASK)),
        (None, None, STATE_CHALLENGE, T, None, Show(STATE_OTP, OTP_ASK)),
        (T - 3, None, STATE_TYPING, T, None, Show(STATE_OTP, OTP_REJECTED)),
        (T - v, None, STATE_TYPING, T, None, Show(STATE_OTP, OTP_ASK)),
        (T - v, None, STATE_OTP, T, None, AskAgain(OTP_REJECTED)),
        (T - v + 0.1, None, STATE_OTP, T, T - v + 0.1, Idle()),
        (None, None, STATE_OTP, T, None, Idle()),
    ]:
        got = login_step(Drive(sent), Poll(T if now is None else now, otp=True, code=code, shown=shown))
        assert got == (Drive(after), eff), (sent, code, shown, got)
    assert login_step(Drive(), Poll(T, otp=True, challenge=True, shown=STATE_TYPING)) == \
        (Drive(), Show(STATE_OTP, OTP_ASK))
    assert login_step(Drive(T - 0.5), Poll(T, otp=True, shown=STATE_OTP), 0.3) == (Drive(), AskAgain(OTP_REJECTED))


def case_typed() -> None:
    for st in (Drive(), Drive(T - 20)):
        assert login_step(st, Typed(True, T)) == (Drive(T), Idle())
        assert login_step(st, Typed(False, T)) == (Drive(), AskAgain(OTP_NOT_TYPED))


def case_challenge_and_typing() -> None:
    for st in (Drive(), Drive(T - 2)):
        for shown in (STATE_TYPING, STATE_CHALLENGE, STATE_OTP):
            assert login_step(st, Poll(T, challenge=True, shown=shown)) == (st, Show(STATE_CHALLENGE, CHALLENGE_MSG))
        for shown, eff in [(STATE_TYPING, Idle()), (STATE_CHALLENGE, Show(STATE_TYPING, TYPING_MSG)),
                           (STATE_OTP, Show(STATE_TYPING, TYPING_MSG)), ("starting", Show(STATE_TYPING, TYPING_MSG))]:
            assert login_step(st, Poll(T, shown=shown)) == (st, eff), (st, shown)


def _run(polls: list) -> list:
    st, out = Drive(), []
    for ev in polls:
        st, eff = login_step(st, ev)
        if isinstance(eff, TypeCode):
            out.append(eff)
            st, eff = login_step(st, Typed(True, ev.now))
        out.append(eff)
    return out


def case_wrong_code_then_right_code() -> None:
    effs = _run([
        Poll(T, shown="starting"),
        Poll(T + 1, otp=True, shown=STATE_TYPING),
        Poll(T + 2, otp=True, shown=STATE_OTP),
        Poll(T + 3, otp=True, code="111111", shown=STATE_OTP),
        Poll(T + 4, otp=True, shown=STATE_OTP),
        Poll(T + 3 + OTP_VERIFY_S, otp=True, shown=STATE_OTP),
        Poll(T + 20, otp=True, code="222222", shown=STATE_OTP),
        Poll(T + 21, shown=STATE_OTP),
        Poll(T + 22, uid="42", shown=STATE_TYPING),
    ])
    assert effs == [Show(STATE_TYPING, TYPING_MSG), Show(STATE_OTP, OTP_ASK), Idle(), TypeCode("111111"), Idle(),
                    Idle(), AskAgain(OTP_REJECTED), TypeCode("222222"), Idle(), Show(STATE_TYPING, TYPING_MSG),
                    LoggedIn("42")], effs


def case_cancel_while_checking_a_code() -> None:
    effs = _run([Poll(T, otp=True, shown=STATE_OTP), Poll(T + 1, otp=True, code="123456", shown=STATE_OTP),
                 Poll(T + 2, otp=True, shown=STATE_OTP), Poll(T + 3, cancel=True, otp=True, shown=STATE_OTP)])
    assert effs == [Idle(), TypeCode("123456"), Idle(), Idle(), Cancel()], effs
    assert _run([Poll(T, otp=True, code="1234567", shown=STATE_OTP), Poll(T + 1, expired=True)])[-1] == Expire()


_harness.run()
