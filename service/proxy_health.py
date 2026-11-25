from __future__ import annotations

import asyncio
import collections
import logging
import os
import random
import threading
import time
from typing import Any, Callable

import account_health
import proxies
import proxy_health_decide as ph
import proxy_probe

log = logging.getLogger("of-relay.proxy-health")

INTERVAL_ENV = "PROXY_HEALTH_INTERVAL_S"
_MIN_INTERVAL_S = 600
RECHECK_ENV = "PROXY_RECHECK_S"
RECHECK_S = 20.0
_MIN_RECHECK_S = 1.0
# Confirm waits past prod's longest blip (32 s) minus a full chain's ~7.7 s, so a blip is not failed over.
CONFIRM_GAP_S = 30.0

FLAP_PCT_ENV = "PROXY_FLAP_BAD_PCT"
FLAP_WINDOW_ENV = "PROXY_FLAP_WINDOW_S"
WINDOW_S = 600.0
# 20% refused flags the two bad proxies and none of the clean ones in the prod replay.
FLAP_PCT_DEFAULT = 20.0
_WINDOW_CAP = 50_000

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}
# Taken after _lock, never around it.
_tele_lock = threading.Lock()
_tele: dict[str, dict[str, Any]] = {}
# Claimed before the watcher thread starts, released in the lock section of its last step: one watcher per label.
_watchers: set[str] = set()


def _spawn_thread(fn: Callable[[], None], name: str) -> None:
    threading.Thread(target=fn, name=name, daemon=True).start()


_spawn: Callable[[Callable[[], None], str], None] = _spawn_thread
_sleep: Callable[[float], None] = time.sleep


def _now() -> float:
    return time.time()


def recheck_s() -> float:
    try:
        v = float(os.environ.get(RECHECK_ENV) or 0)
    except ValueError:
        return RECHECK_S
    return RECHECK_S if v <= 0 else max(v, _MIN_RECHECK_S)


def window_s() -> float:
    try:
        v = float(os.environ.get(FLAP_WINDOW_ENV) or 0)
    except ValueError:
        return WINDOW_S
    return WINDOW_S if v <= 0 else v


def flap_bad_pct() -> float:
    raw = os.environ.get(FLAP_PCT_ENV)
    if raw is None or not raw.strip():
        return FLAP_PCT_DEFAULT
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return FLAP_PCT_DEFAULT


def _tele_entry(label: str) -> dict[str, Any]:
    e = _tele.get(label)
    if e is None:
        e = _tele[label] = {"q": collections.deque(), "refused": 0, "tenths": collections.Counter(),
                            "inflight": 0, "inflight_peak": 0}
    return e


def _prune(e: dict[str, Any], now: float) -> None:
    q, edge = e["q"], now - window_s()
    while q and (q[0][0] < edge or len(q) > _WINDOW_CAP):
        _, refused, tenth = q.popleft()
        if refused:
            e["refused"] -= 1
            e["tenths"][tenth] -= 1
            if not e["tenths"][tenth]:
                del e["tenths"][tenth]


def _stats(e: dict[str, Any] | None, now: float) -> ph.WindowStats:
    if not e:
        return ph.WindowStats(0, 0, 0)
    _prune(e, now)
    return ph.WindowStats(len(e["q"]), e["refused"], len(e["tenths"]))


def _window(label: str) -> ph.WindowStats:
    with _tele_lock:
        return _stats(_tele.get(label), _now())


def attempt_start(label: str | None) -> None:
    if not label:
        return
    with _tele_lock:
        e = _tele_entry(label)
        e["inflight"] += 1
        e["inflight_peak"] = max(e["inflight_peak"], e["inflight"])


def attempt_end(label: str | None, refused: bool | None) -> None:
    if not label:
        return
    with _tele_lock:
        _tele_entry(label)["inflight"] -= 1
    if refused is not None:
        _sample(label, refused)


def _sample(label: str, refused: bool) -> None:
    with _tele_lock:
        e, now = _tele_entry(label), _now()
        tenth = int(now // (window_s() / 10))
        e["q"].append((now, refused, tenth))
        if refused:
            e["refused"] += 1
            e["tenths"][tenth] += 1
        w = _stats(e, now)
    if refused and ph.flap_trips(w, flap_bad_pct()):
        _step(label, lambda: ph.FlapBad(_now(), label in _watchers, w.pct, w.calls))


def refusals(label: str) -> dict[str, Any]:
    w = _window(label)
    return {"window_s": window_s(), "refused": w.refused, "calls": w.calls, "pct": w.pct}


def still_flapping(label: str) -> bool:
    return ph.flap_holds(_window(label), flap_bad_pct())


def herd_guarded(label: str) -> bool:
    return ph.flap_guards(_window(label), flap_bad_pct())


def confirm_gap_s() -> float:
    return CONFIRM_GAP_S * recheck_s() / RECHECK_S


def record(label: str | None, ok: bool, error: str | None = None) -> None:
    if not label:
        return
    st = _state.get(label)
    if ok and (st is None or (st["errors"] == 0 and not st["down"])):
        return
    _step(label, lambda: ph.CallOk(_now(), still_flapping(label)) if ok else ph.CallErr(_now(), error, label in _watchers))


def _step(label: str, event: Callable[[], ph.Event]) -> ph.Next:
    with _lock:
        st, effects, nxt = ph.decide(_state.get(label), event())
        if st is None:
            _state.pop(label, None)
        else:
            _state[label] = st
        rest = []
        for e in effects:
            if isinstance(e, ph.Watch):
                _watchers.add(label)
            elif isinstance(e, ph.Unwatch):
                _watchers.discard(label)
            else:
                rest.append(e)
    if ph.Watch() in effects:
        _spawn(lambda: _watch(label), f"proxy-watch-{label}")
    for e in rest:
        if isinstance(e, ph.Log):
            log.log(e.level, e.msg, label, *e.args)
        elif isinstance(e, ph.Announce):
            _announce(label, e.down)
        elif isinstance(e, ph.Failover):
            _failover(label)
        else:
            raise TypeError(f"unknown proxy health effect {e!r}")
    return nxt


def last_geo(p: dict[str, Any]) -> str | None:
    with _lock:
        return ((_state.get(p.get("label") or "") or {}).get("trace") or {}).get("geo")


def verify_pick(p: dict[str, Any], timeout_s: int = 15, region: bool = True) -> bool:
    label = p.get("label") or ""
    result = proxy_probe.probe_of(p, timeout_s=timeout_s)
    if label:
        record_probe(label, result)
        if region and result.get("ok") and last_geo(p) is None:
            note_trace(label, proxy_probe.probe(p, timeout_s=timeout_s))
    return bool(result.get("ok"))


def failover_due(label: str) -> bool:
    with _lock:
        return ph.failover_due(_state.get(label))


def _due_labels() -> set[str]:
    with _lock:
        return {label for label, state in _state.items() if ph.failover_due(state)}


ATTACH_PROBE_TIMEOUT_S = 5


def assign_pool(account_id: str, rng: random.Random | None = None) -> tuple[dict[str, Any], bool]:
    reasons = bad_reasons()
    return proxies.assign_pool(account_id, bad=unusable_labels(reasons),
                               dead={lb for lb, why in reasons.items() if why == "down"}, due=_due_labels(),
                               geo=last_geo,
                               verify=lambda p: verify_pick(p, timeout_s=ATTACH_PROBE_TIMEOUT_S, region=False),
                               rng=rng, deactivated=account_health.write_gate_snapshot())


def record_probe(label: str, result: dict[str, Any]) -> None:
    _keep_probe(label, result)
    record(label, bool(result.get("ok")), result.get("error"))


def note_trace(label: str, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        return
    with _lock:
        st = _state.setdefault(label, ph.blank())
        st["trace"] = {k: result.get(k) for k in ("ip", "geo", "colo")}


def _keep_probe(label: str, result: dict[str, Any]) -> None:
    with _lock:
        st = _state.setdefault(label, ph.blank())
        st["probe"] = {k: result.get(k) for k in ("ok", "ttfb_ms", "error")}
        st["probed_at"] = _now()
    if result.get("ok") or result.get("refused"):
        _sample(label, not result.get("ok"))


def _probe(label: str) -> bool | None:
    p = proxies.get_by_label(label)
    if p is None:
        _step(label, ph.Gone)
        with _tele_lock:
            if (_tele.get(label) or {}).get("inflight", 0) <= 0:
                _tele.pop(label, None)
        return None
    result = proxy_probe.probe_of(p)
    _keep_probe(label, result)
    return bool(result.get("ok"))


def _watch(label: str) -> None:
    try:
        _watch_inner(label)
    except Exception:
        log.warning("proxy watcher for %s failed", label, exc_info=True)
        with _lock:
            _watchers.discard(label)


def _confirm_due(label: str) -> ph.Next:
    return _step(label, lambda: ph.ConfirmDue(_now(), confirm_gap_s()))


def _watch_inner(label: str) -> None:
    nxt = _confirm_due(label)
    while nxt is not None:
        if isinstance(nxt, ph.Wait):
            _sleep(nxt.s)
            nxt = _confirm_due(label) if nxt.then is ph.ConfirmDue else _step(label, ph.RecheckDue)
        elif isinstance(nxt, ph.Confirm):
            streak, ok = nxt.streak, _probe(label)
            nxt = None if ok is None else _step(label, lambda: ph.ConfirmResult(_now(), ok, streak))
        elif isinstance(nxt, ph.Recheck):
            ok = _probe(label)
            nxt = None if ok is None else _step(label, lambda: ph.RecheckResult(ok, still_flapping(label)))
        elif isinstance(nxt, ph.ArmRecheck):
            nxt = _arm_recheck(label)
        else:
            raise TypeError(f"unknown proxy watcher step {nxt!r}")


def _arm_recheck(label: str) -> ph.Next:
    return _step(label, lambda: ph.RecheckWait(_now(), recheck_s()))


def _failover(label: str) -> list[str]:
    moved = proxies.failover_pool(label, bad=unusable_labels(bad_reasons()), geo=last_geo, verify=verify_pick,
                                 deactivated=account_health.write_gate_snapshot())
    if moved is None:
        return []
    _step(label, lambda: ph.FailedOver(_now(), tuple(moved)))
    return moved


def snapshot(label: str) -> dict[str, Any]:
    with _lock:
        st = dict(_state.get(label) or {})
    st.setdefault("down", False)
    st.setdefault("errors", 0)
    st.pop("first_error_at", None)
    st.pop("streak", None)
    if not st.get("bad_reason"):
        st.pop("bad_reason", None)
    st["refusals"] = refusals(label)
    with _tele_lock:
        e = _tele.get(label) or {}
        st["inflight"], st["inflight_peak"] = e.get("inflight", 0), e.get("inflight_peak", 0)
    if st["down"]:
        st["state"] = "rechecking" if st.pop("rechecking", False) else "bad"
    else:
        st.pop("rechecking", None)
        st["state"] = "suspect" if st["errors"] else "healthy"
    return st


def down_labels() -> set[str]:
    return set(bad_reasons())


def bad_reasons() -> dict[str, str]:
    with _lock:
        return {label: st["bad_reason"] for label, st in _state.items() if st["down"]}


def unusable_labels(reasons: dict[str, str]) -> set[str]:
    with _tele_lock:
        seen = list(_tele)
    return set(reasons) | {lb for lb in seen if herd_guarded(lb)}


def _announce(label: str, down: bool) -> None:
    try:
        import events
        p = proxies.get_by_label(label)
        for aid in (proxies._ids_on(p) if p else []):
            events.publish_state("proxy_switched", account_id=aid, proxied=True, down=down)
    except Exception:
        log.warning("proxy health announce failed for %s", label, exc_info=True)


def probe_targets() -> list[dict[str, Any]]:
    return [p for p in proxies.list_proxies() if p.get("label") and proxies._ids_on(p)]


def probe_all() -> int:
    n = 0
    for p in probe_targets():
        record_probe(p["label"], proxy_probe.probe_of(p))
        n += 1
    return n


def interval_s() -> float:
    try:
        v = float(os.environ.get(INTERVAL_ENV) or 0)
    except ValueError:
        return 0.0
    return 0.0 if v <= 0 else max(v, _MIN_INTERVAL_S)


async def probe_loop() -> None:
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
