"""
of_ws_decide.decide(state, Failed(dead_reason, up_s)) -> (state', Wait | GiveUp): the OnlyFans
WebSocket pump's reconnect rules (service/of_ws.py's events() is the shell) as tables.

  case_backoff_doubles_to_the_cap        transient failures wait 1, 2, 4, 8, 16, 30, 30 … s
  case_uptime_resets_the_backoff         a failed pass whose socket was up >= RESET_AFTER_S
                                         (60 s, Failed.up_s) starts the backoff over; a
                                         shorter one keeps it doubling; a dead session
                                         after a long uptime still gives up
  case_classifier_answer_to_effect       a real 101 otpState gives up, a socket close
                                         reconnects (the classifier's full table:
                                         test_session_health.py)
  case_give_up_is_immediate_at_any_backoff
                                         the first dead answer gives up, whatever came
                                         before; no wait, state kept; "" is not a reason
  case_shell_refreshes_ticket_before_every_reconnect
                                         a real loopback socket that OF closes after each
                                         hello: /users/me, then the socket, then the hello
                                         with THAT ticket's token, every pass; decide saw a
                                         Failed per drop and the shell waited ~1 then ~2 s
  case_shell_transient_then_dead         socket drop -> Wait(1) -> /users/me answers 101 ->
                                         GiveUp: SessionDead("otp_required") (the slop path)
  case_shell_without_classifier_never_gives_up
                                         no session_dead classifier: a 101 reconnects

Run: ./venv/bin/python service/tests/test_of_ws_decide.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

import websockets  # noqa: E402
from websockets.exceptions import ConnectionClosedOK  # noqa: E402
from websockets.frames import Close  # noqa: E402

import account_health  # noqa: E402
import of_ws  # noqa: E402
import of_ws_decide as d  # noqa: E402
from of_client import OFAPIError  # noqa: E402
from of_ws_decide import (RECONNECT_MAX_S, RECONNECT_MIN_S, RESET_AFTER_S, Failed, GiveUp,  # noqa: E402
                          Pump, Wait, decide)

OTP_BODY = ('{"error":{"code":101,"message":"Confirm it is you","payload":{"otpState":'
            '{"appOtp":true},"strong":false}}}')
ME = "https://onlyfans.com/api2/v2/users/me"


async def _until(pred, timeout_s: float) -> None:
    t_end = time.monotonic() + timeout_s
    while not pred():
        assert time.monotonic() < t_end, "timed out"
        await asyncio.sleep(0.02)


def case_backoff_doubles_to_the_cap() -> None:
    assert (RECONNECT_MIN_S, RECONNECT_MAX_S) == (1, 30)
    st, waits = Pump(), []
    for _ in range(9):
        st, eff = decide(st, Failed(None))
        assert isinstance(eff, Wait), eff
        waits.append(eff.s)
    assert waits == [1, 2, 4, 8, 16, 30, 30, 30, 30], waits
    assert st == Pump(30)
    # From any backoff: (state, the wait now, the next state's backoff)
    for b, wait, nxt in [(1, 1, 2), (2, 2, 4), (15, 15, 30), (16, 16, 30), (29, 29, 30), (30, 30, 30)]:
        assert decide(Pump(b), Failed(None)) == (Pump(nxt), Wait(wait)), b


def case_uptime_resets_the_backoff() -> None:
    assert RESET_AFTER_S == 60
    # (backoff before, the failed pass's socket uptime) -> (the wait now, the next backoff)
    for b, up, wait, nxt in [
        (8, None, 8, 16),    # never opened: keeps doubling
        (8, 0.05, 8, 16),    # closed right after the hello: keeps doubling
        (8, 59.9, 8, 16),
        (8, 60, 1, 2),       # up a minute: starts over
        (30, 3600, 1, 2),
        (1, 120, 1, 2),
        (16, 30, 16, 30),
    ]:
        assert decide(Pump(b), Failed(None, up)) == (Pump(nxt), Wait(wait)), (b, up)
    # Short uptimes in a row: 1, 2, 4, 8 as before up_s existed.
    st, waits = Pump(), []
    for _ in range(4):
        st, eff = decide(st, Failed(None, 0.05))
        waits.append(eff.s)
    assert waits == [1, 2, 4, 8], waits
    # A dead session after a long uptime: GiveUp, unchanged.
    assert decide(Pump(30), Failed("otp_required", 600)) == (Pump(1), GiveUp("otp_required"))


def case_classifier_answer_to_effect() -> None:
    for err, effect in [
        (OFAPIError(f"400 for {ME}\n{OTP_BODY}"), GiveUp("otp_required")),
        (ConnectionClosedOK(Close(1000, ""), None), Wait(4)),
    ]:
        assert decide(Pump(4), Failed(account_health.is_session_dead_error(err)))[1] == effect, err


def case_give_up_is_immediate_at_any_backoff() -> None:
    for b in (1, 2, 8, 30):
        for reason in ("otp_required", "wrong_user", "no_session"):
            assert decide(Pump(b), Failed(reason)) == (Pump(b), GiveUp(reason)), (b, reason)
    # An empty reason is no reason (the shell's `if reason:` at HEAD): it reconnects.
    assert decide(Pump(2), Failed("")) == (Pump(4), Wait(2))
    # After any run of transient failures, the first dead answer ends it.
    st = Pump()
    for _ in range(5):
        st, _ = decide(st, Failed(None))
    assert decide(st, Failed("otp_required"))[1] == GiveUp("otp_required")


class _Spy:
    """Wraps of_ws_decide.decide (looked up per call by the shell) and records each step."""

    def __init__(self):
        self.steps: list[tuple] = []
        self.real = d.decide

    def __enter__(self):
        def spy(state, ev):
            out = self.real(state, ev)
            self.steps.append((ev, out[1]))
            return out
        d.decide = spy
        return self

    def __exit__(self, *_a):
        d.decide = self.real


async def _dropping_server(hellos: list):
    """A loopback 'OF' that answers the hello, then closes the socket (code 1000)."""
    async def serve(conn) -> None:
        hellos.append((time.monotonic(), json.loads(await conn.recv())))
        await conn.send('{"connected":true,"v":"5.4.0"}')
        await asyncio.sleep(0.05)
        await conn.close()
    srv = await websockets.serve(serve, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


class _Client:
    proxy_url = None
    user_agent = "ua"
    account_id = "acc_decide"

    def __init__(self, port: int, answers: list | None = None):
        self.port, self.answers, self.issued = port, list(answers or []), []

    def me(self) -> dict:
        if self.answers:
            a = self.answers.pop(0)
            if isinstance(a, Exception):
                self.issued.append((time.monotonic(), None))
                raise a
        token = f"t{len(self.issued)}"
        self.issued.append((time.monotonic(), token))
        return {"wsUrl": f"ws://127.0.0.1:{self.port}/ws3/1", "wsAuthToken": token}


async def _drain(ws) -> list:
    got = []
    async for ev in ws.events():
        got.append(ev)
    return got


async def case_shell_refreshes_ticket_before_every_reconnect() -> None:
    hellos: list = []
    srv, port = await _dropping_server(hellos)
    c = _Client(port)
    ws = of_ws.OFWebSocket(c, session_dead=account_health.is_session_dead_error)
    try:
        with _Spy() as spy:
            task = asyncio.create_task(_drain(ws))
            await _until(lambda: len(spy.steps) == 3, 15)  # passes at ~0, 1, 3 s; the third drop waits 4 s
            ws.stop()
            frames = await asyncio.wait_for(task, 2)  # a stop during the wait ends events() at once
    finally:
        srv.close()
        await srv.wait_closed()
    assert len(hellos) == 3 and frames == [{"connected": True, "v": "5.4.0"}] * 3, (hellos, frames)
    assert [h for _, h in hellos] == [{"act": "connect", "token": t} for _, t in c.issued], (hellos, c.issued)
    # Each pass: the ticket first, then the socket (its hello carries that ticket's token).
    for (t_me, _), (t_hello, _) in zip(c.issued, hellos):
        assert t_me <= t_hello, (c.issued, hellos)
    # Each drop: a Failed whose socket was up ~0.05 s (no reset).
    assert all(isinstance(ev, Failed) and ev.dead_reason is None and 0 <= ev.up_s < 1
               for ev, _ in spy.steps), spy.steps
    assert [eff for _, eff in spy.steps] == [Wait(1), Wait(2), Wait(4)], spy.steps
    g1, g2 = (b[0] - a[0] for a, b in zip(c.issued, c.issued[1:]))
    assert 0.9 <= g1 < 1.5 and 1.9 <= g2 < 2.5, (g1, g2)


async def case_shell_transient_then_dead() -> None:
    hellos: list = []
    srv, port = await _dropping_server(hellos)
    c = _Client(port, answers=[None, OFAPIError(f"400 for {ME}\n{OTP_BODY}")])
    ws = of_ws.OFWebSocket(c, session_dead=account_health.is_session_dead_error)
    try:
        with _Spy() as spy:
            try:
                await asyncio.wait_for(_drain(ws), 5)
                raise AssertionError("events() ended without raising")
            except of_ws.SessionDead as e:
                assert e.reason == "otp_required", e.reason
                assert isinstance(e.__cause__, OFAPIError), repr(e.__cause__)
                assert e.__context__ is e.__cause__, "raised outside the handler: no __context__"
    finally:
        srv.close()
        await srv.wait_closed()
    assert len(hellos) == 1 and len(c.issued) == 2, (hellos, c.issued)
    # The drop had a socket up ~0.05 s; the 101 came from /users/me, before any socket.
    (ev1, eff1), (ev2, eff2) = spy.steps
    assert ev1.dead_reason is None and 0 <= ev1.up_s < 1 and eff1 == Wait(1), spy.steps
    assert (ev2, eff2) == (Failed("otp_required"), GiveUp("otp_required")), spy.steps


async def case_shell_without_classifier_never_gives_up() -> None:
    otp = OFAPIError(f"400 for {ME}\n{OTP_BODY}")
    c = _Client(9, answers=[otp, otp, otp])
    ws = of_ws.OFWebSocket(c)  # no session_dead: the CLI tailer's shape
    with _Spy() as spy:
        task = asyncio.create_task(_drain(ws))
        await _until(lambda: len(c.issued) == 2, 5)
        ws.stop()
        assert await asyncio.wait_for(task, 3) == []  # ended by the stop, no SessionDead
    assert spy.steps[:2] == [(Failed(None), Wait(1)), (Failed(None), Wait(2))], spy.steps


_harness.run()
