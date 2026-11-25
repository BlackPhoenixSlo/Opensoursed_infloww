from __future__ import annotations

RESET_AFTER_S = 60
WS_GAP_MAX_S = 2.0
TORN_DIRECT = ("torn proxies.json: no OF client of a proxied Creator is built direct while the registry "
               "file is rewritten in place in a loop (each build names the proxy)")
WS_GAP = (f"WS pump: after a socket up >= {RESET_AFTER_S} s, OF ending it is followed by a reconnect "
          f"within {WS_GAP_MAX_S:.0f} s (the backoff earlier drops grew starts over)")


def _proxies_torn_read_goes_direct() -> None:
    import json

    import proxies

    def registry():
        if not proxies.REGISTRY_PATH.exists():
            return proxies.Ok(proxies._empty())
        try:
            data = json.loads(proxies.REGISTRY_PATH.read_text())
        except (OSError, ValueError):
            return proxies.Ok(proxies._empty())
        if not isinstance(data, dict) or "proxies" not in data:
            return proxies.Ok(proxies._empty())
        return proxies.Ok(data)

    proxies.registry = registry


def _of_ws_backoff_never_resets() -> None:
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return real(state, of_ws_decide.Failed(ev.dead_reason))

    of_ws_decide.decide = decide


def register(Fault) -> dict:
    return {
        "proxies-torn-read-goes-direct": Fault(_proxies_torn_read_goes_direct, (TORN_DIRECT,)),
        "of-ws-backoff-never-resets": Fault(_of_ws_backoff_never_resets, (WS_GAP,)),
    }
