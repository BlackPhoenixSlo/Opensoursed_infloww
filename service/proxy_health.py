"""
Proxy health (roadmap 2.14; failover and recheck: docs/adr/0030): is each
Creator's proxy up, how slow is it, and what to do when it is not.

Two signals, one state per proxy label (in memory; a restart starts clean):

  * Passive, free: OF calls through a proxy report here. A call under the
    full retry policy (`of_client.FULL_RETRY`: background work, every write,
    no-request jobs) that ends in a ProxyError, or in curl's "couldn't
    connect" (with a proxy set, the only host curl connects to is the
    proxy), after `_proxy_retry`'s own 5 tries, counts one error. A read
    someone waits on (`INTERACTIVE_RETRY`, 2 tries in ~1 s) never counts:
    three of those fit inside any CONNECT-403 blip. Any call that gets an
    answer resets the count. A timeout is not counted: it can't be told
    apart from a slow OF.
  * The probe (`proxies.probe`): one GET of Cloudflare's
    `https://1.1.1.1/cdn-cgi/trace` through the proxy, which answers the
    egress ip, its country (`loc`) and the Cloudflare colo, and gives the
    time to first byte. No OnlyFans call, no third-party key. It runs from
    the Test button (`/admin/proxies/{label}/test`), as the confirm and
    recheck below, before a new binding or a move (`verify_pick`), and
    periodically only when PROXY_HEALTH_INTERVAL_S is set (opt-in, off by
    default). It only ever goes through proxies in the registry: never an
    ad-hoc URL, never the relay's own connection. A failed probe counts one
    error too.

The states (`snapshot()["state"]`):

  healthy     no consecutive errors.
  suspect     1..DOWN_AFTER-1 consecutive errors, or DOWN_AFTER reached and the
              confirm probe not yet run. Nothing happens.
  bad         DOWN_AFTER consecutive errors AND a failed confirm probe
              (`down`). Announced; `assign_pool` no longer picks it; a watcher
              thread rechecks it with one probe after RECHECK_S, then twice
              that, and so on up to RECHECK_MAX_S.
  rechecking  bad, a recheck probe in flight.

The confirm waits out a blip: it probes no sooner than CONFIRM_GAP_S after
the streak's first counted error, and not at all if an answer through the
proxy reset the count meanwhile. After FAILOVER_AFTER_RECHECKS failed
rechecks (`failover_due`), and again after every later failed recheck until
nobody is left on it, the Creators on a bad INFLOWWW POOL proxy are moved to
pool proxies that answer a probe right then (`_failover`:
`proxies.failover_pool`, one registry write, so the relay's `on_switch`
evicts their clients and reconnects their chat sockets together). A custom
proxy's Creators are never moved: the user chose it. A recheck that passes,
or any answer through the proxy, brings it back up (announced); its Creators
are NOT moved back: a second IP change for them is a second OnlyFans
security risk, so the recovered proxy becomes the standby.

Prod timeline for a pool proxy that dies, from these constants and the
measured ~0.33 s per refused try (slop/evidence/
20261028T111800Z-scale-vs-load-7cc9bbd67): the first full-policy call fails
~7.7 s in (5 tries, 0.4+0.8+1.6+3.2 s of pauses); with traffic DOWN_AFTER of
them land about together; the confirm runs CONFIRM_GAP_S (30 s) after the
first, ~38 s: bad, announced; rechecks at +20 s (~58 s) and +40 s (~98 s);
the second failed one moves its Creators: about 100 s after the death (98 s
plus ~1 s of probes). Prod's CONNECT-403 blips (0-32 s, both pool proxies,
every chain ending in a success) end before the confirm (>= 7.7 + 30 s after
a blip starts), so they mark nothing bad. PROXY_RECHECK_S scales the whole
cadence (the confirm wait with it): at 2 s, ~7.7 + 3 + 2 + 4 = ~17 s.

When a proxy goes down or comes back, each Creator on it gets the
`proxy_switched` account-state event with `down`, so open tabs refetch the
proxies and accounts lists, which carry `health` / `proxy_down`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
from typing import Any, Callable

import proxies

log = logging.getLogger("of-relay.proxy-health")

DOWN_AFTER = 3          # consecutive counted errors that start the confirm
INTERVAL_ENV = "PROXY_HEALTH_INTERVAL_S"
_MIN_INTERVAL_S = 600   # a periodic probe never runs more often than this
RECHECK_ENV = "PROXY_RECHECK_S"
RECHECK_S = 20.0        # first recheck of a bad proxy after this; doubled each time
RECHECK_MAX_S = 600.0   # ... up to this (6 probes an hour for a proxy that stays dead)
_MIN_RECHECK_S = 1.0
FAILOVER_AFTER_RECHECKS = 2   # failed rechecks in a row before a pool proxy's Creators move
CONFIRM_GAP_S = 30.0    # the confirm probes no sooner than this after a streak's first error
                        # (> prod's longest blip, 32 s, minus a full chain's ~7.7 s)

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}
_watchers: set[str] = set()   # labels with a watcher (claimed before its thread starts)


def _spawn_thread(fn: Callable[[], None], name: str) -> None:
    threading.Thread(target=fn, name=name, daemon=True).start()


# How a watcher is started; tests replace it to run the watcher inline.
_spawn: Callable[[Callable[[], None], str], None] = _spawn_thread
# How a watcher waits (the confirm's wait, between rechecks); tests replace it to skip the wait.
_sleep: Callable[[float], None] = time.sleep


def _now() -> float:
    return time.time()


def _blank() -> dict[str, Any]:
    return {"errors": 0, "first_error_at": None, "down": False, "last_error": None,
            "last_error_at": None}


def recheck_s() -> float:
    """The first recheck's delay (PROXY_RECHECK_S, default RECHECK_S, floored at 1 s)."""
    try:
        v = float(os.environ.get(RECHECK_ENV) or 0)
    except ValueError:
        return RECHECK_S
    return RECHECK_S if v <= 0 else max(v, _MIN_RECHECK_S)


def confirm_gap_s() -> float:
    """CONFIRM_GAP_S, scaled with PROXY_RECHECK_S (one knob for the whole cadence)."""
    return CONFIRM_GAP_S * recheck_s() / RECHECK_S


def record(label: str | None, ok: bool, error: str | None = None) -> None:
    """One outcome through `label`. Cheap on the success path (called on
    every proxied OF call); announces an up change, starts the watcher when
    DOWN_AFTER errors are in a row."""
    if not label:
        return
    st = _state.get(label)
    if ok and (st is None or (st["errors"] == 0 and not st["down"])):
        return  # healthy and staying healthy: nothing to write
    watch = False
    with _lock:
        st = _state.setdefault(label, _blank())
        was_down = st["down"]
        if ok:
            _up(st)
        else:
            if not st["errors"]:
                st["first_error_at"] = _now()
            st["errors"] += 1
            st.update(last_error=(error or "error")[:200], last_error_at=_now())
            if st["errors"] >= DOWN_AFTER and not st["down"] and label not in _watchers:
                watch = True
                _watchers.add(label)
        changed = st["down"] != was_down
    if changed:
        log.warning("proxy %s is back up", label)
        _announce(label, False)
    if watch:
        _spawn(lambda: _watch(label), f"proxy-watch-{label}")


def last_geo(p: dict[str, Any]) -> str | None:
    """A proxy's country as its last answering probe saw it (None: never seen)."""
    with _lock:
        return (_state.get(p.get("label") or "") or {}).get("geo")


def verify_pick(p: dict[str, Any], timeout_s: int = 15) -> bool:
    """The destination check before a NEW binding (a login's attach step,
    Browserbase's bind) or a move (`_failover`, a held Creator re-picked):
    one probe through the pick, counted like the Test button's. False = pass
    it over: nobody is moved onto a proxy that does not answer right now."""
    label = p.get("label") or ""
    result = proxies.probe(p, timeout_s=timeout_s)
    if label:
        record_probe(label, result)
    return bool(result.get("ok"))


def failover_due(label: str) -> bool:
    """Bad, and FAILOVER_AFTER_RECHECKS rechecks in a row failed: its pool
    Creators are to move. The one predicate `_failover` and `assign_pool` share."""
    with _lock:
        st = _state.get(label)
        return bool(st and st["down"] and st.get("rechecks_failed", 0) >= FAILOVER_AFTER_RECHECKS)


def _due_labels() -> set[str]:
    return {label for label in list(_state) if failover_due(label)}


# The attach request (a login's last step) waits on its probes: a short
# timeout each, at most proxies.ATTACH_PROBES of them.
ATTACH_PROBE_TIMEOUT_S = 5


def assign_pool(account_id: str, rng: random.Random | None = None) -> tuple[dict[str, Any], bool]:
    """`proxies.assign_pool` with this module's view: bad proxies skipped, a
    Creator moved off its proxy only when `failover_due` and onto a pick that
    answers (`verify_pick`, ATTACH_PROBE_TIMEOUT_S each), the region from the
    last probes. A Creator on no pool proxy is bound even when no pick
    answers (least-used not bad) or every pool proxy is bad (least-used).
    LookupError: the pool is empty."""
    return proxies.assign_pool(account_id, bad=down_labels(), due=_due_labels(), geo=last_geo,
                               verify=lambda p: verify_pick(p, timeout_s=ATTACH_PROBE_TIMEOUT_S),
                               rng=rng)


def record_probe(label: str, result: dict[str, Any]) -> None:
    """Keep a probe's trace fields; count its outcome (the Test button, the
    periodic probe, `verify_pick`). A watcher's own probes go through `_probe` instead."""
    _keep_probe(label, result)
    record(label, bool(result.get("ok")), result.get("error"))


def _keep_probe(label: str, result: dict[str, Any]) -> None:
    with _lock:
        st = _state.setdefault(label, _blank())
        st["probe"] = {k: result.get(k) for k in ("ok", "ip", "geo", "colo", "ttfb_ms", "error")}
        st["probed_at"] = _now()
        if result.get("ok") and result.get("geo"):
            st["geo"] = result["geo"]   # the last country seen: kept through a failed probe (failover's region)


def _probe(label: str) -> bool | None:
    """One probe through `label`, kept in the state. None when the proxy is
    gone from the registry (its state is dropped; the watcher ends)."""
    p = proxies.get_by_label(label)
    if p is None:
        with _lock:
            _state.pop(label, None)
        log.info("proxy %s is gone from the registry; its watcher ends", label)
        return None
    result = proxies.probe(p)
    _keep_probe(label, result)
    return bool(result.get("ok"))


def _watch(label: str) -> None:
    """The watcher: confirm, then recheck with backoff until the proxy answers.
    One per label at a time; never raises."""
    try:
        _watch_inner(label)
    except Exception:
        log.warning("proxy watcher for %s failed", label, exc_info=True)
    finally:
        with _lock:
            _watchers.discard(label)


def _watch_inner(label: str) -> None:
    # Wait out CONFIRM_GAP_S from the streak's first error; a blip ends
    # meanwhile (an answer resets the count). A new streak that started
    # during the sleep moved first_error_at: wait again from it.
    while True:
        with _lock:
            st = _state.get(label)
            if not st or st["down"] or st["errors"] < DOWN_AFTER:
                return
            wait = st["first_error_at"] + confirm_gap_s() - _now()
        if wait <= 0:
            break
        _sleep(wait)
    if _confirm(label):
        _recheck_loop(label)


def _up(st: dict[str, Any]) -> None:
    st.update(errors=0, first_error_at=None, down=False, rechecks_failed=0, next_recheck_at=None,
              rechecking=False)


def _confirm(label: str) -> bool:
    """DOWN_AFTER errors in a row, past the confirm's wait: one probe decides.
    Answers → a blip, the count restarts (True = now bad, announced)."""
    ok = _probe(label)
    if ok is None:
        return False
    if ok:
        with _lock:
            _state[label].update(errors=0, first_error_at=None)
        log.info("proxy %s: %d errors in a row but the probe answers; not marked bad", label, DOWN_AFTER)
        return False
    with _lock:
        _state[label].update(down=True, bad_since=_now(), rechecks_failed=0)
    log.warning("proxy %s is DOWN (confirmed by probe)", label)
    _announce(label, True)
    return True


def _recheck_loop(label: str) -> None:
    """Recheck a bad proxy after RECHECK_S, doubling up to RECHECK_MAX_S, until
    it answers (or an answer through it brought it back meanwhile), or it is
    gone from the registry. Its pool Creators move once `failover_due`, and
    again after each later failed recheck (a move that found no answering
    destination is retried)."""
    delay = recheck_s()
    while True:
        with _lock:
            st = _state.get(label) or _blank()
            if not st["down"]:
                return
            st["next_recheck_at"] = _now() + delay
        _sleep(delay)
        with _lock:
            st = _state.get(label) or _blank()
            if not st["down"]:
                return
            st.update(rechecking=True, next_recheck_at=None)
        ok = _probe(label)
        if ok is None:
            return
        with _lock:
            st = _state.get(label) or _blank()
            st["rechecking"] = False
            if ok:
                _up(st)
            else:
                st["rechecks_failed"] = st.get("rechecks_failed", 0) + 1
        if ok:
            log.warning("proxy %s is back up (recheck)", label)
            _announce(label, False)
            return
        if failover_due(label):
            _failover(label)
        delay = min(delay * 2, RECHECK_MAX_S)


def _failover(label: str) -> list[str]:
    """Move the Creators on a bad pool proxy to pool proxies that answer
    (`proxies.failover_pool`: each destination probed by `verify_pick` before
    anyone is put on it; a provider-wide outage would otherwise herd everyone
    onto the last proxy not yet confirmed bad). Nothing is probed, stamped
    or logged when the proxy is not a pool proxy or nobody is on it
    (failover_pool returns None). Logged; [] when nobody moved (they stay,
    surfaced)."""
    moved = proxies.failover_pool(label, bad=down_labels(), geo=last_geo, verify=verify_pick)
    if moved is None:
        return []
    with _lock:
        st = _state.setdefault(label, _blank())
        st.update(failed_over_at=_now(), failed_over=st.get("failed_over", 0) + len(moved))
    if moved:
        log.warning("proxy %s: %d Creator(s) moved to healthy pool proxies: %s", label, len(moved), moved)
    else:
        log.warning("proxy %s: nobody moved (no pool proxy answers); retried at the next failed recheck", label)
    return moved


def snapshot(label: str) -> dict[str, Any]:
    """`health` for one proxy: {state, down, errors, last_error, last_error_at,
    probe?, probed_at?, bad_since?, next_recheck_at?, failed_over?...}. A
    proxy never seen reads as healthy."""
    with _lock:
        st = dict(_state.get(label) or {})
    st.setdefault("down", False)
    st.setdefault("errors", 0)
    st.pop("first_error_at", None)
    if st["down"]:
        st["state"] = "rechecking" if st.pop("rechecking", False) else "bad"
    else:
        st.pop("rechecking", None)
        st["state"] = "suspect" if st["errors"] else "healthy"
    return st


def down_labels() -> set[str]:
    with _lock:
        return {label for label, st in _state.items() if st["down"]}


def _announce(label: str, down: bool) -> None:
    try:
        import events
        p = proxies.get_by_label(label)
        for aid in (proxies._ids_on(p) if p else []):
            events.publish_state("proxy_switched", account_id=aid, proxied=True, down=down)
    except Exception:
        log.warning("proxy health announce failed for %s", label, exc_info=True)


def probe_targets() -> list[dict[str, Any]]:
    """Registry proxies with at least one Creator on them."""
    return [p for p in proxies.list_proxies() if p.get("label") and proxies._ids_on(p)]


def probe_all() -> int:
    """Probe every proxy a Creator is on, one at a time. Returns how many."""
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
