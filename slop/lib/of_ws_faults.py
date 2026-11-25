from __future__ import annotations

try:
    from .pump_faults import WS_PARKED, WS_RETRIES
except ImportError:
    from pump_faults import WS_PARKED, WS_RETRIES


WS_EVICT_RECONNECT = ("after the evict and OF dropping every socket, every Creator's pump reconnected within "
                      "RECONNECT_S on a fresh pooled client: /users/me 200, then a socket with OF's token")
WS_EVICT_NO_RETIRED = "relay.log has no 'signed session retired' after the evict"


def _of_ws_dead_session_keeps_reconnecting() -> None:
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return real(state, of_ws_decide.Failed(None, ev.up_s))

    of_ws_decide.decide = decide


def _of_ws_dead_gives_up_first() -> None:
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return (state, of_ws_decide.GiveUp(ev.dead_reason)) if ev.dead_reason else real(state, ev)

    of_ws_decide.decide = decide


def _ws_pump_keeps_evicted_client() -> None:
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
        "of-ws-dead-session-keeps-reconnecting": Fault(_of_ws_dead_session_keeps_reconnecting, (WS_PARKED,)),
        "of-ws-dead-gives-up-first": Fault(_of_ws_dead_gives_up_first, (WS_RETRIES,)),
        "ws-pump-keeps-evicted-client": Fault(_ws_pump_keeps_evicted_client,
                                              (WS_EVICT_RECONNECT, WS_EVICT_NO_RETIRED)),
    }
