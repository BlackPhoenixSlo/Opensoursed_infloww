"""The OnlyFans WebSocket pump's break-it-once faults (scenarios/2026-10-25-session-health-otp.py,
the one scenario whose Creators run the REAL of_ws pump, against lib/of_wire.py's socket): lib/faults.py
merges `register(Fault)` into FAULTS. Each patches `service/of_ws_decide.decide`, the pure reconnect rules
of_ws.OFWebSocket.events() performs, inside the relay. WS_PARKED and WS_RETRIES, the scenario's WS pump
checks, are owned by lib/pump_faults.py.
"""
from __future__ import annotations

try:
    from .pump_faults import WS_PARKED, WS_RETRIES
except ImportError:  # loaded as a top-level module (lib/ on sys.path, inside the relay)
    from pump_faults import WS_PARKED, WS_RETRIES


def _of_ws_dead_session_keeps_reconnecting() -> None:
    """decide() blind to the classifier's answer: a session OF rejected (101 otpState, "Wrong user.")
    is treated as a transient failure, so the pump never raises SessionDead and keeps re-reading
    /users/me on its 1, 2, 4, 8, 16 s backoff into OF's 2FA demand, and never exits. The account is
    still flagged by its inbox reads (via=proxy), and its first retries look like the real ones, so
    only WS_PARKED (the pump never exits) can see it. PROBE_RESTART goes red with it (noise): a pump
    that never exits is never restarted."""
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return real(state, of_ws_decide.Failed(None, ev.up_s))  # up_s kept: the 60 s reset (WS_GAP) intact

    of_ws_decide.decide = decide


def _of_ws_dead_gives_up_first() -> None:
    """The pre-Q2 rule: decide() gives up on the first dead answer, no retry, so a session OF asks
    for a code for a moment (or a /users/me it answers wrongly once) parks the pump at once. The pump
    still exits and parks, so only WS_RETRIES can see it."""
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return (state, of_ws_decide.GiveUp(ev.dead_reason)) if ev.dead_reason else real(state, ev)

    of_ws_decide.decide = decide


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-25-session-health-otp --break --fault=of-ws-dead-session-keeps-reconnecting
        "of-ws-dead-session-keeps-reconnecting": Fault(_of_ws_dead_session_keeps_reconnecting, (WS_PARKED,)),
        # slop/run 2026-10-25-session-health-otp --break --fault=of-ws-dead-gives-up-first
        "of-ws-dead-gives-up-first": Fault(_of_ws_dead_gives_up_first, (WS_RETRIES,)),
    }
