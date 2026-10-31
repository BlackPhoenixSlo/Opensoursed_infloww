"""The OnlyFans WebSocket pump's break-it-once fault (scenarios/2026-10-25-session-health-otp.py,
the one scenario whose Creators run the REAL of_ws pump, against lib/of_wire.py's socket): lib/faults.py
merges `register(Fault)` into FAULTS. It patches `service/of_ws_decide.decide`, the pure reconnect rules
of_ws.OFWebSocket.events() performs, inside the relay. WS_PARKED, the scenario's WS pump check, is
owned by lib/pump_faults.py.
"""
from __future__ import annotations

try:
    from .pump_faults import WS_PARKED
except ImportError:  # loaded as a top-level module (lib/ on sys.path, inside the relay)
    from pump_faults import WS_PARKED


def _of_ws_dead_session_keeps_reconnecting() -> None:
    """decide() blind to the classifier's answer: a session OF rejected (101 otpState, "Wrong user.")
    is treated as a transient failure, so the pump never raises SessionDead and keeps re-reading
    /users/me on its 1, 2, 4, 8 s backoff into OF's 2FA demand, and never exits. The account is still
    flagged by its inbox reads (via=proxy), so only the WS check can see it."""
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return real(state, of_ws_decide.Failed(None))

    of_ws_decide.decide = decide


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-25-session-health-otp --break --fault=of-ws-dead-session-keeps-reconnecting
        "of-ws-dead-session-keeps-reconnecting": Fault(_of_ws_dead_session_keeps_reconnecting, (WS_PARKED,)),
    }
