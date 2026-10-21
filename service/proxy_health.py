"""
Proxy health (roadmap 2.14): is each Creator's proxy up, and how slow is it.

Two signals, one state per proxy label (in memory; a restart starts clean):

  * Passive, free: every OF call through a proxy reports here
    (`of_client._http_call`). A call that ends in a ProxyError, or in curl's
    "couldn't connect" (with a proxy set, the only host curl connects to is
    the proxy), after `_proxy_retry`'s own retries, counts one error; any
    call that gets an answer resets the count. A timeout is not counted: it
    can't be told apart from a slow OF. DOWN_AFTER errors in a row mark the proxy down.
  * The probe (`proxies.probe`): one GET of Cloudflare's
    `https://1.1.1.1/cdn-cgi/trace` through the proxy, which answers the
    egress ip, its country (`loc`) and the Cloudflare colo, and gives the
    time to first byte. No OnlyFans call, no third-party key. It runs from
    the Test button (`/admin/proxies/{label}/test`), and periodically only
    when PROXY_HEALTH_INTERVAL_S is set (opt-in, off by default). It only
    ever goes through proxies in the registry that a Creator is on: never an
    ad-hoc URL, never the relay's own connection.

When a proxy goes down or comes back, each Creator on it gets the
`proxy_switched` account-state event with `down`, so open tabs refetch the
proxies and accounts lists, which carry `health` / `proxy_down`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("of-relay.proxy-health")

DOWN_AFTER = 3          # consecutive errors that mark a proxy down
INTERVAL_ENV = "PROXY_HEALTH_INTERVAL_S"
_MIN_INTERVAL_S = 600   # a periodic probe never runs more often than this

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.time()


def _blank() -> dict[str, Any]:
    return {"errors": 0, "down": False, "last_error": None, "last_error_at": None}


def record(label: str | None, ok: bool, error: str | None = None) -> None:
    """One outcome through `label`. Cheap on the success path (called on
    every proxied OF call); announces a down/up change."""
    if not label:
        return
    st = _state.get(label)
    if ok and (st is None or (st["errors"] == 0 and not st["down"])):
        return  # healthy and staying healthy: nothing to write
    with _lock:
        st = _state.setdefault(label, _blank())
        was_down = st["down"]
        if ok:
            st.update(errors=0, down=False)
        else:
            st["errors"] += 1
            st.update(last_error=(error or "error")[:200], last_error_at=_now())
            if st["errors"] >= DOWN_AFTER:
                st["down"] = True
        changed = st["down"] != was_down
        down = st["down"]
    if changed:
        log.warning("proxy %s is %s", label, "DOWN" if down else "back up")
        _announce(label, down)


def record_probe(label: str, result: dict[str, Any]) -> None:
    """Keep a probe's trace fields and count its outcome."""
    with _lock:
        st = _state.setdefault(label, _blank())
        st["probe"] = {k: result.get(k) for k in ("ok", "ip", "geo", "colo", "ttfb_ms", "error")}
        st["probed_at"] = _now()
    record(label, bool(result.get("ok")), result.get("error"))


def snapshot(label: str) -> dict[str, Any]:
    """`health` for one proxy: {down, errors, last_error, last_error_at,
    probe?, probed_at?}. A proxy never seen reads as up."""
    with _lock:
        st = dict(_state.get(label) or {})
    st.setdefault("down", False)
    st.setdefault("errors", 0)
    return st


def down_labels() -> set[str]:
    with _lock:
        return {label for label, st in _state.items() if st["down"]}


def _announce(label: str, down: bool) -> None:
    try:
        import events
        import proxies
        p = proxies.get_by_label(label)
        for aid in (proxies._ids_on(p) if p else []):
            events.publish_state("proxy_switched", account_id=aid, proxied=True, down=down)
    except Exception:
        log.warning("proxy health announce failed for %s", label, exc_info=True)


def probe_targets() -> list[dict[str, Any]]:
    """Registry proxies with at least one Creator on them."""
    import proxies
    return [p for p in proxies.list_proxies() if p.get("label") and proxies._ids_on(p)]


def probe_all() -> int:
    """Probe every proxy a Creator is on, one at a time. Returns how many."""
    import proxies
    n = 0
    for p in probe_targets():
        record_probe(p["label"], proxies.probe(p))
        n += 1
    return n


def interval_s() -> float:
    """The periodic probe's period; 0 = off (the default)."""
    try:
        v = float(os.environ.get(INTERVAL_ENV) or 0)
    except ValueError:
        return 0.0
    return 0.0 if v <= 0 else max(v, _MIN_INTERVAL_S)


async def probe_loop() -> None:
    """Opt-in periodic probe (PROXY_HEALTH_INTERVAL_S). Never raises."""
    period = interval_s()
    if not period:
        return
    log.info("proxy health probe every %.0fs", period)
    while True:
        await asyncio.sleep(period)
        try:
            n = await asyncio.to_thread(probe_all)
            log.info("proxy health: probed %d proxy(ies)", n)
        except Exception:
            log.warning("proxy health probe pass failed", exc_info=True)
