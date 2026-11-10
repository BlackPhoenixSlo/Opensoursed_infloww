"""OnlyFans WebSocket pump faults for session-health-otp and ws-pump-evict.

lib/faults.py merges register(Fault) into FAULTS. Session-health faults patch
of_ws_decide.decide; the eviction fault pins OFWebSocket's client source. WS_PARKED
and WS_RETRIES are owned by lib/pump_faults.py.
"""
from __future__ import annotations

try:
    from .pump_faults import WS_PARKED, WS_RETRIES
except ImportError:  # loaded as a top-level module (lib/ on sys.path, inside the relay)
    from pump_faults import WS_PARKED, WS_RETRIES


WS_EVICT_RECONNECT = ("after the evict and OF dropping every socket, every Creator's pump reconnected within "
                      "RECONNECT_S on a fresh pooled client: /users/me 200, then a socket with OF's token")
WS_EVICT_NO_RETIRED = "relay.log has no 'signed session retired' after the evict"


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


def _ws_pump_keeps_evicted_client() -> None:
    """Pin the first pooled client; after eviction its signed sessions stay retired."""
    import of_ws
    real = of_ws.OFWebSocket.__init__

    def init(self, client_source, *args, **kwargs):
        first = []

        def pinned_source():
            if not first:
                first.append(client_source())
            return first[0]

        real(self, pinned_source, *args, **kwargs)

    of_ws.OFWebSocket.__init__ = init


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-25-session-health-otp --break --fault=of-ws-dead-session-keeps-reconnecting
        "of-ws-dead-session-keeps-reconnecting": Fault(_of_ws_dead_session_keeps_reconnecting, (WS_PARKED,)),
        # slop/run 2026-10-25-session-health-otp --break --fault=of-ws-dead-gives-up-first
        "of-ws-dead-gives-up-first": Fault(_of_ws_dead_gives_up_first, (WS_RETRIES,)),
        # slop/run 2026-11-10-ws-pump-evict --break
        "ws-pump-keeps-evicted-client": Fault(_ws_pump_keeps_evicted_client,
                                              (WS_EVICT_RECONNECT, WS_EVICT_NO_RETIRED)),
    }
