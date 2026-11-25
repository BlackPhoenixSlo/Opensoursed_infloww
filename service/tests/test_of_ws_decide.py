from __future__ import annotations

import _harness  # MUST be first: binds temp DB

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
    for b, wait, nxt in [(1, 1, 2), (2, 2, 4), (15, 15, 30), (16, 16, 30), (29, 29, 30), (30, 30, 30)]:
        assert decide(Pump(b), Failed(None)) == (Pump(nxt), Wait(wait)), b


def case_uptime_resets_the_backoff() -> None:
    assert RESET_AFTER_S == 60
    for b, up, wait, nxt in [
        (8, None, 8, 16),
        (8, 0.05, 8, 16),
        (8, 59.9, 8, 16),
        (8, 60, 1, 2),
        (30, 3600, 1, 2),
        (1, 120, 1, 2),
        (16, 30, 16, 30),
    ]:
        assert decide(Pump(b), Failed(None, up)) == (Pump(nxt), Wait(wait)), (b, up)
    st, waits = Pump(), []
    for _ in range(4):
        st, eff = decide(st, Failed(None, 0.05))
        waits.append(eff.s)
    assert waits == [1, 2, 4, 8], waits
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
    assert decide(st, dead) == (st, GiveUp("otp_required"))
    for b in (1, 2, 8, 30):
        for reason in ("otp_required", "wrong_user", "no_session"):
            assert decide(Pump(b, DEAD_RETRIES), Failed(reason)) == (Pump(b, DEAD_RETRIES), GiveUp(reason))
            assert decide(Pump(b, 2), Failed(reason)) == (Pump(min(b * 2, 30), 3), Wait(b, 3)), (b, reason)
    assert decide(Pump(2, 1), Failed("")) == (Pump(4, 1), Wait(2, 0))


def case_dead_count_resets_only_with_the_backoff() -> None:
    dead = "otp_required"
    for evs, want in [
        ([Failed(dead, 5)] * 4, [Wait(1, 1), Wait(2, 2), Wait(4, 3), GiveUp(dead)]),
        ([Failed(dead), Failed(None)] * 3 + [Failed(dead)],
         [Wait(1, 1), Wait(2), Wait(4, 2), Wait(8), Wait(16, 3), Wait(30), GiveUp(dead)]),
        ([Failed(dead), Failed(None, 5)] * 3 + [Failed(dead)],
         [Wait(1, 1), Wait(2), Wait(4, 2), Wait(8), Wait(16, 3), Wait(30), GiveUp(dead)]),
        ([Failed(None, 0.05)] + [Failed(dead)] * 4, [Wait(1), Wait(2, 1), Wait(4, 2), Wait(8, 3), GiveUp(dead)]),
        ([Failed(dead)] * 3 + [Failed(None, RESET_AFTER_S)] + [Failed(dead)] * 4,
         [Wait(1, 1), Wait(2, 2), Wait(4, 3), Wait(1), Wait(2, 1), Wait(4, 2), Wait(8, 3), GiveUp(dead)]),
        ([Failed(dead)] * 3 + [Failed(dead, RESET_AFTER_S)] + [Failed(dead)] * 3,
         [Wait(1, 1), Wait(2, 2), Wait(4, 3), Wait(1, 1), Wait(2, 2), Wait(4, 3), GiveUp(dead)]),
    ]:
        assert _run(Pump(), evs)[1] == want, (evs, _run(Pump(), evs)[1])
    assert decide(Pump(8, 3), Failed(dead, 59.9)) == (Pump(8, 3), GiveUp(dead))


class _Logs(logging.Handler):

    def __enter__(self):
        self.lines: list[str] = []
        logging.getLogger("of-ws").addHandler(self)
        return self

    def __exit__(self, *_a):
        logging.getLogger("of-ws").removeHandler(self)

    def emit(self, record) -> None:
        self.lines.append(record.getMessage())


class _Spy:

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
    recon: list = []

    def on_reconnect():
        recon.append(len(hellos))
        raise RuntimeError("a hook that raises never costs the socket")
    ws = of_ws.OFWebSocket(lambda: c, session_dead=account_health.is_session_dead_error, on_reconnect=on_reconnect)
    try:
        with _Spy() as spy:
            task = asyncio.create_task(_drain(ws))
            await _until(lambda: len(spy.steps) == 3, 15)
            ws.stop()
            frames = await asyncio.wait_for(task, 2)
    finally:
        srv.close()
        await srv.wait_closed()
    assert len(hellos) == 3 and frames == [{"connected": True, "v": "5.4.0"}] * 3, (hellos, frames)
    assert len(recon) == 2, recon
    assert [h for _, h in hellos] == [{"act": "connect", "token": t} for _, t in c.issued], (hellos, c.issued)
    for (t_me, _), (t_hello, _) in zip(c.issued, hellos):
        assert t_me <= t_hello, (c.issued, hellos)
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
    ws = of_ws.OFWebSocket(lambda: c, session_dead=account_health.is_session_dead_error)
    try:
        with _Spy() as spy, _Logs() as logs:
            try:
                await asyncio.wait_for(_drain(ws), 20)
                raise AssertionError("events() ended without raising")
            except of_ws.SessionDead as e:
                assert e.reason == "otp_required", e.reason
                assert isinstance(e.__cause__, OFAPIError), repr(e.__cause__)
                assert e.__context__ is e.__cause__, "raised outside the handler: no __context__"
    finally:
        srv.close()
        await srv.wait_closed()
    assert len(hellos) == 1 and len(c.issued) == 5, (hellos, c.issued)
    (ev1, eff1), *deads = spy.steps
    assert ev1.dead_reason is None and 0 <= ev1.up_s < 1 and eff1 == Wait(1), spy.steps
    assert all(ev == Failed("otp_required") for ev, _ in deads), spy.steps
    assert [eff for _, eff in deads] == [Wait(2, 1), Wait(4, 2), Wait(8, 3), GiveUp("otp_required")], spy.steps
    gaps = [round(b[0] - a[0], 1) for a, b in zip(c.issued, c.issued[1:])]
    assert all(w - 0.1 <= g < w + 0.5 for g, w in zip(gaps, [1, 2, 4, 8])), gaps
    dead_lines = [ln for ln in logs.lines if "session dead" in ln]
    assert [ln.split("— ")[1] for ln in dead_lines] == [
        "retry 1/3 in 2s", "retry 2/3 in 4s", "retry 3/3 in 8s", "not reconnecting"], logs.lines


async def case_shell_without_classifier_never_gives_up() -> None:
    otp = OFAPIError(f"400 for {ME}\n{OTP_BODY}")
    c = _Client(9, answers=[otp, otp, otp])
    ws = of_ws.OFWebSocket(lambda: c)
    with _Spy() as spy:
        task = asyncio.create_task(_drain(ws))
        await _until(lambda: len(c.issued) == 2, 5)
        ws.stop()
        assert await asyncio.wait_for(task, 3) == []
    assert spy.steps[:2] == [(Failed(None), Wait(1)), (Failed(None), Wait(2))], spy.steps


async def case_shell_logs_a_retry_only_when_decide_retries() -> None:
    otp = OFAPIError(f"400 for {ME}\n{OTP_BODY}")
    c = _Client(9, answers=[otp, otp, otp])
    ws = of_ws.OFWebSocket(lambda: c, session_dead=account_health.is_session_dead_error)
    real = d.decide
    d.decide = lambda state, ev: real(state, Failed(None))
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
