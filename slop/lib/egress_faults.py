"""A Creator's egress faults (lib/faults.py merges `register(Fault)` into FAULTS): which way its
OnlyFans traffic leaves, the proxy registry (`service/proxies.py`) and the WS pump's reconnect rules
(`service/of_ws_decide.py`), each patched inside the relay. The check names live here and the
scenarios import them, so a target can never name a check that does not exist.

  proxies-torn-read-goes-direct    scenarios/2026-10-28-dead-proxy-interactive-reads.py, TORN_DIRECT
  of-ws-backoff-never-resets       scenarios/2026-10-25-session-health-otp.py, WS_GAP
"""
from __future__ import annotations

RESET_AFTER_S = 60  # = service/of_ws_decide.RESET_AFTER_S: a socket up this long starts the backoff over
WS_GAP_MAX_S = 2.0  # the reset backoff's 1 s wait, plus /users/me and the socket's open on a loaded relay
TORN_DIRECT = ("torn proxies.json: no OF client of a proxied Creator is built direct while the registry "
               "file is rewritten in place in a loop (each build names the proxy)")
WS_GAP = (f"WS pump: after a socket up >= {RESET_AFTER_S} s, OF ending it is followed by a reconnect "
          f"within {WS_GAP_MAX_S:.0f} s (the backoff earlier drops grew starts over)")


def _proxies_torn_read_goes_direct() -> None:
    """The registry read before the fix: a proxies.json read mid-write (empty or half-written) is an
    empty registry, so a client built in that instant finds no proxy for its Creator and goes direct.
    `load` and the writers call `registry` at call time, so they see it too: sync_pool would take a
    torn file for an empty registry (startup only; harmless for the run)."""
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
    """decide() deaf to Failed.up_s: a pump's backoff only grows while it lives, so a socket up for
    hours that OF ends waits the backoff of the drops before it (1, 2, 4, 8 ... 30 s)."""
    import of_ws_decide
    real = of_ws_decide.decide

    def decide(state, ev):
        return real(state, of_ws_decide.Failed(ev.dead_reason))

    of_ws_decide.decide = decide


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-28-dead-proxy-interactive-reads --break --fault=proxies-torn-read-goes-direct
        "proxies-torn-read-goes-direct": Fault(_proxies_torn_read_goes_direct, (TORN_DIRECT,)),
        # slop/run 2026-10-25-session-health-otp --break --fault=of-ws-backoff-never-resets
        "of-ws-backoff-never-resets": Fault(_of_ws_backoff_never_resets, (WS_GAP,)),
    }
