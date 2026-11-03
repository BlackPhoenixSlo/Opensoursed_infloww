"""
of_ws_decide.decide(state, Failed(dead_reason, up_s)) -> (state', Wait | GiveUp): the OnlyFans
WebSocket pump's reconnect rules (service/of_ws.py's events() is the shell) as tables.

  case_backoff_doubles_to_the_cap        transient failures wait 1, 2, 4, 8, 16, 30, 30 … s
  case_uptime_resets_the_backoff         a failed pass whose socket was up >= RESET_AFTER_S
                                         (60 s, Failed.up_s) starts the backoff over; a
                                         shorter one keeps it doubling; a dead answer
                                         after a long uptime is retry 1
  case_classifier_answer_to_effect       a real 101 otpState gives up once retried out,
                                         a socket close reconnects (the classifier's full
                                         table: test_session_health.py)
  case_dead_retries_then_gives_up        dead answers 1..3 wait 1, 2, 4 s as Wait(s, retry
                                         1..3), the 4th gives up, state kept; a transient's
                                         Wait has retry 0; "" is not a reason
  case_dead_count_resets_only_with_the_backoff
                                         a socket up >= 60 s resets the count; one up 5 s
                                         or a transient pass keeps it (and the doubling),
                                         so dead/transient alternation gives up on the 4th
  case_shell_refreshes_ticket_before_every_reconnect
                                         a real loopback socket that OF closes after each
                                         hello: /users/me, then the socket, then the hello
                                         with THAT ticket's token, every pass; decide saw a
                                         Failed per drop and the shell waited ~1 then ~2 s
  case_shell_transient_then_dead         socket drop -> Wait(1) -> /users/me answers 101
                                         -> Wait 2, 4, 8 s (retry 1..3, logged n/3) -> the
                                         4th 101 -> GiveUp: SessionDead("otp_required")
                                         (the slop path)
  case_shell_without_classifier_never_gives_up
                                         no session_dead classifier: a 101 reconnects
  case_shell_logs_a_retry_only_when_decide_retries
                                         a decide blind to the classifier (the slop fault
                                         of-ws-dead-session-keeps-reconnecting): a 101 is
                                         logged as a plain ws error, never "retry 0/3"

Run: ./venv/bin/python service/tests/test_of_ws_decide.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

import websockets  # noqa: E402
from websockets.exceptions import ConnectionClosedOK  # noqa: E402
from websockets.frames import Close  # noqa: E402

import account_health  # noqa: E402
import of_ws  # noqa: E402
import of_ws_decide as d  # noqa: E402
from of_client import OFAPIError  # noqa: E402
from of_ws_decide import (DEAD_RETRIES, RECONNECT_MAX_S, RECONNECT_MIN_S, RESET_AFTER_S,  # noqa: E402
                          Failed, GiveUp, Pump, Wait, decide)

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
    # A dead answer after a long uptime: the reset, then retry 1.
    assert decide(Pump(30, DEAD_RETRIES), Failed("otp_required", 600)) == (Pump(2, 1), Wait(1, 1))


def case_classifier_answer_to_effect() -> None:
    for err, effect in [
        (OFAPIError(f"400 for {ME}\n{OTP_BODY}"), GiveUp("otp_required")),
        (ConnectionClosedOK(Close(1000, ""), None), Wait(4)),
    ]:
        st = Pump(4, DEAD_RETRIES)
        assert decide(st, Failed(account_health.is_session_dead_error(err)))[1] == effect, err


def _run(st: Pump, evs: list[Failed]) -> tuple[Pump, list]:
    effs = []
    for ev in evs:
        st, eff = decide(st, ev)
        effs.append(eff)
    return st, effs


def case_dead_retries_then_gives_up() -> None:
    assert DEAD_RETRIES == 3
    dead = Failed("otp_required")
    st = Pump()
    for n, wait in [(1, 1), (2, 2), (3, 4)]:
        st, eff = decide(st, dead)
        assert (st, eff) == (Pump(wait * 2, n), Wait(wait, n)), (n, st, eff)
    assert decide(st, dead) == (st, GiveUp("otp_required"))  # the 4th: no wait, state kept
    # Retried out at any backoff, any reason: GiveUp; with retries left: the backoff's wait.
    for b in (1, 2, 8, 30):
        for reason in ("otp_required", "wrong_user", "no_session"):
            assert decide(Pump(b, DEAD_RETRIES), Failed(reason)) == (Pump(b, DEAD_RETRIES), GiveUp(reason))
            assert decide(Pump(b, 2), Failed(reason)) == (Pump(min(b * 2, 30), 3), Wait(b, 3)), (b, reason)
    # An empty reason is no reason (the shell's `if reason:` at HEAD): a transient (retry 0), count kept.
    assert decide(Pump(2, 1), Failed("")) == (Pump(4, 1), Wait(2, 0))


def case_dead_count_resets_only_with_the_backoff() -> None:
    dead = "otp_required"
    # (events) -> the effects; every row ends in GiveUp on its 4th dead answer unless reset.
    for evs, want in [
        # dead with a socket up 5 s (a dead session can still open it): no reset.
        ([Failed(dead, 5)] * 4, [Wait(1, 1), Wait(2, 2), Wait(4, 3), GiveUp(dead)]),
        # dead/transient alternation: the transient keeps the count and the doubling.
        ([Failed(dead), Failed(None)] * 3 + [Failed(dead)],
         [Wait(1, 1), Wait(2), Wait(4, 2), Wait(8), Wait(16, 3), Wait(30), GiveUp(dead)]),
        ([Failed(dead), Failed(None, 5)] * 3 + [Failed(dead)],
         [Wait(1, 1), Wait(2), Wait(4, 2), Wait(8), Wait(16, 3), Wait(30), GiveUp(dead)]),
        # transient first (the slop path: OF ends the socket, then /users/me answers 101).
        ([Failed(None, 0.05)] + [Failed(dead)] * 4, [Wait(1), Wait(2, 1), Wait(4, 2), Wait(8, 3), GiveUp(dead)]),
        # a socket up >= 60 s between: the count starts over, so 3 more retries.
        ([Failed(dead)] * 3 + [Failed(None, RESET_AFTER_S)] + [Failed(dead)] * 4,
         [Wait(1, 1), Wait(2, 2), Wait(4, 3), Wait(1), Wait(2, 1), Wait(4, 2), Wait(8, 3), GiveUp(dead)]),
        ([Failed(dead)] * 3 + [Failed(dead, RESET_AFTER_S)] + [Failed(dead)] * 3,
         [Wait(1, 1), Wait(2, 2), Wait(4, 3), Wait(1, 1), Wait(2, 2), Wait(4, 3), GiveUp(dead)]),
    ]:
        assert _run(Pump(), evs)[1] == want, (evs, _run(Pump(), evs)[1])
    # up_s 59.9 is no reset.
    assert decide(Pump(8, 3), Failed(dead, 59.9)) == (Pump(8, 3), GiveUp(dead))


class _Logs(logging.Handler):
    """Collects of_ws's log lines (the shell's logger) while active."""

    def __enter__(self):
        self.lines: list[str] = []
        logging.getLogger("of-ws").addHandler(self)
        return self

    def __exit__(self, *_a):
        logging.getLogger("of-ws").removeHandler(self)

    def emit(self, record) -> None:
        self.lines.append(record.getMessage())


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
    otp = OFAPIError(f"400 for {ME}\n{OTP_BODY}")
    c = _Client(port, answers=[None] + [otp] * (DEAD_RETRIES + 1))
    ws = of_ws.OFWebSocket(c, session_dead=account_health.is_session_dead_error)
    try:
        with _Spy() as spy, _Logs() as logs:
            try:
                await asyncio.wait_for(_drain(ws), 20)  # waits 1 + 2 + 4 + 8 s
                raise AssertionError("events() ended without raising")
            except of_ws.SessionDead as e:
                assert e.reason == "otp_required", e.reason
                assert isinstance(e.__cause__, OFAPIError), repr(e.__cause__)
                assert e.__context__ is e.__cause__, "raised outside the handler: no __context__"
    finally:
        srv.close()
        await srv.wait_closed()
    assert len(hellos) == 1 and len(c.issued) == 5, (hellos, c.issued)
    # The drop had a socket up ~0.05 s; each 101 came from /users/me, before any socket.
    (ev1, eff1), *deads = spy.steps
    assert ev1.dead_reason is None and 0 <= ev1.up_s < 1 and eff1 == Wait(1), spy.steps
    assert all(ev == Failed("otp_required") for ev, _ in deads), spy.steps
    assert [eff for _, eff in deads] == [Wait(2, 1), Wait(4, 2), Wait(8, 3), GiveUp("otp_required")], spy.steps
    gaps = [round(b[0] - a[0], 1) for a, b in zip(c.issued, c.issued[1:])]
    assert all(w - 0.1 <= g < w + 0.5 for g, w in zip(gaps, [1, 2, 4, 8])), gaps
    # The shell logs each retry with decide's number, then the give-up.
    dead_lines = [ln for ln in logs.lines if "session dead" in ln]
    assert [ln.split("— ")[1] for ln in dead_lines] == [
        "retry 1/3 in 2s", "retry 2/3 in 4s", "retry 3/3 in 8s", "not reconnecting"], logs.lines


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


async def case_shell_logs_a_retry_only_when_decide_retries() -> None:
    otp = OFAPIError(f"400 for {ME}\n{OTP_BODY}")
    c = _Client(9, answers=[otp, otp, otp])
    ws = of_ws.OFWebSocket(c, session_dead=account_health.is_session_dead_error)
    real = d.decide
    d.decide = lambda state, ev: real(state, Failed(None))  # the classifier's answer ignored
    try:
        with _Logs() as logs:
            task = asyncio.create_task(_drain(ws))
            await _until(lambda: len(c.issued) == 2, 5)
            ws.stop()
            assert await asyncio.wait_for(task, 3) == []
    finally:
        d.decide = real
    assert not any("session dead" in ln for ln in logs.lines), logs.lines
    assert sum(ln.startswith("ws error") for ln in logs.lines) >= 2, logs.lines


_harness.run()
