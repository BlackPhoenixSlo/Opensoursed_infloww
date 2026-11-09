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
  * The probe (`proxy_probe.probe_of`): one GET of OnlyFans' API host (`robots.txt`)
    through the proxy, no cookies, no session, Chrome's TLS. Any HTTP answer:
    the proxy tunnels to OF. Health is judged by it alone: the confirm and
    recheck below, before a new binding or a move (`verify_pick`), and
    periodically only when PROXY_HEALTH_INTERVAL_S is set (opt-in, off by
    default). A failed probe counts one error too. Cloudflare's trace
    (`proxy_probe.probe`: egress ip, country, colo) is display and region only
    (`note_trace`: the Test button, a new binding's first region), never
    counted: a proxy can answer it yet refuse CONNECT to OF (2026-11-06).
    Probes only ever go through proxies in the registry: never an ad-hoc
    URL, never the relay's own connection.

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
proxy reset the count meanwhile; a failed probe marks nothing bad when an
answer reset that streak while the probe ran (a new streak since gets its
own wait and confirm, from the same watcher). A bad proxy that an answer
brings back while its watcher waits to recheck, and that reaches DOWN_AFTER
errors again before the recheck runs, is confirmed by that same watcher (the
errors start none while it holds the claim). After FAILOVER_AFTER_RECHECKS
failed rechecks (`failover_due`), and again after every later failed recheck until
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

Refusal telemetry: every `_proxy_retry` attempt through a labelled client
(`attempt_start`/`attempt_end`: a ProxyError = refused, an answer = ok, any
other failure is left out) and every probe lands in a per-label window of
window_s() seconds (PROXY_FLAP_WINDOW_S, default 600; at most _WINDOW_CAP
attempts), shown as `health.refusals`, with `health.inflight` (attempts in
flight now) and `inflight_peak` (since start). Calls that skip `_proxy_retry`
(the chat WebSocket, /img's and the vault's raw CDN gets) are not in it; a
streaming get leaves `inflight` when its headers arrive, not its body. A
probe counts as refused only for a refused CONNECT (ProxyError), as a call
does. Prod 2026-11 (per attempt on user requests, measured: 30 % refused on
52339bd6, 17 % on 8ce1b29a; inferred similar for background traffic): the
refusals come in provider-side bursts, each back within 1-20 s, so the
DOWN_AFTER streak never forms and nothing above fires. In-flight counts are
shown to the site owner only (the relay's whole traffic through a proxy).

The flap knob (PROXY_FLAP_BAD_PCT, default FLAP_PCT_DEFAULT = 20; 0 turns it
off: moving a Creator changes the IP OnlyFans sees, a risk the owner accepted
on 2026-11-05, so flapping proxies leave rotation on their own). Goes bad (`FlapBad`: no
confirm, as a flapping proxy answers a single probe most of the time) on a
refusal when `ph.flap_trips`: >= FLAP_MIN_CALLS attempts in the window, the
rate >= X (PROXY_FLAP_BAD_PCT), refusals in >= FLAP_BUCKETS tenths of the
window (a short full outage is not flapping: the confirm path owns it); decide
leaves a proxy down or in a DOWN_AFTER streak alone. Then the usual rechecks,
`failover_due` and no fail-back. Stays bad (an answer or a passing recheck,
its own sample counted first, does not bring it up) while `ph.flap_holds`:
>= FLAP_MIN_CALLS attempts and the rate >= X/2, no recency rule
(`still_flapping`); once its window drains the next one brings it back as
standby. The failover never moves anyone onto a proxy that is bad or
`herd_guarded` (`ph.flap_guards`: holds AND refusals in >= FLAP_BUCKETS
tenths, so a clean proxy's one blip does not), even when its probe answers
(none left: nobody moves).
`health.bad_reason` says which path made it bad: "down" or "flapping".

When a proxy goes down or comes back, each Creator on it gets the
`proxy_switched` account-state event with `down`, so open tabs refetch the
proxies and accounts lists, which carry `health` / `proxy_down`.

Every rule above is `proxy_health_decide.decide(state, event) -> (state',
effects, next)`, a pure function (tables: tests/test_proxy_health_decide.py).
This module is its shell: the lock (`_step`: one decide per lock section, the
watcher claim taken and released in it), the watcher thread (`_watch_inner`:
one flat loop running each `next` decide names), the waits, the probes, the
announce and the move.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import random
import threading
import time
from typing import Any, Callable

import proxies
import proxy_health_decide as ph
import proxy_probe

log = logging.getLogger("of-relay.proxy-health")

INTERVAL_ENV = "PROXY_HEALTH_INTERVAL_S"
_MIN_INTERVAL_S = 600   # a periodic probe never runs more often than this
RECHECK_ENV = "PROXY_RECHECK_S"
RECHECK_S = 20.0        # first recheck of a bad proxy after this; doubled each time up to ph.RECHECK_MAX_S
_MIN_RECHECK_S = 1.0
CONFIRM_GAP_S = 30.0    # the confirm probes no sooner than this after a streak's first error
                        # (> prod's longest blip, 32 s, minus a full chain's ~7.7 s)

FLAP_PCT_ENV = "PROXY_FLAP_BAD_PCT"        # the flap knob; unset = FLAP_PCT_DEFAULT, 0 = off (docs/adr/0030 Consequences)
FLAP_WINDOW_ENV = "PROXY_FLAP_WINDOW_S"    # the refusal window, shown in /admin/proxies too
WINDOW_S = 600.0
# The knob's other thresholds: ph.FLAP_MIN_CALLS, ph.FLAP_BUCKETS, ph.flap_trips / flap_holds / flap_guards.
FLAP_PCT_DEFAULT = 20.0   # refused share that marks a flapping proxy bad (prod replay 2026-11-05: flags the two bad ones, never the clean ones)
_WINDOW_CAP = 50_000      # attempts kept per label, whatever the window

_lock = threading.Lock()
_state: dict[str, dict[str, Any]] = {}
# Per-label attempt telemetry (`attempt_start`/`attempt_end`, the probes; `_tele_entry`): the window of
# (time, refused, tenth), its refused count and refusals per tenth, in-flight counts. Own lock; taken after
# _lock, never around it.
_tele_lock = threading.Lock()
_tele: dict[str, dict[str, Any]] = {}
_watchers: set[str] = set()   # labels with a watcher: claimed (Watch) before its thread starts, released
                              # (Unwatch) in the lock section of its last step


def _spawn_thread(fn: Callable[[], None], name: str) -> None:
    threading.Thread(target=fn, name=name, daemon=True).start()


# How a watcher is started; tests replace it to run the watcher inline.
_spawn: Callable[[Callable[[], None], str], None] = _spawn_thread
# How a watcher waits (the confirm's wait, between rechecks); tests replace it to skip the wait.
_sleep: Callable[[float], None] = time.sleep


def _now() -> float:
    return time.time()


def recheck_s() -> float:
    """The first recheck's delay (PROXY_RECHECK_S, default RECHECK_S, floored at 1 s)."""
    try:
        v = float(os.environ.get(RECHECK_ENV) or 0)
    except ValueError:
        return RECHECK_S
    return RECHECK_S if v <= 0 else max(v, _MIN_RECHECK_S)


def window_s() -> float:
    """The refusal window (PROXY_FLAP_WINDOW_S, default WINDOW_S)."""
    try:
        v = float(os.environ.get(FLAP_WINDOW_ENV) or 0)
    except ValueError:
        return WINDOW_S
    return WINDOW_S if v <= 0 else v


def flap_bad_pct() -> float:
    """PROXY_FLAP_BAD_PCT (unset: FLAP_PCT_DEFAULT); 0 = off: a refusal rate never marks a proxy bad."""
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
        # q: (time, refused, tenth) per attempt; tenths: refusals per tenth of the window (absolute buckets of
        # window_s()/10), so the spread is a len(), not a scan
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
    """The window as one snapshot (the caller holds _tele_lock)."""
    if not e:
        return ph.WindowStats(0, 0, 0)
    _prune(e, now)
    return ph.WindowStats(len(e["q"]), e["refused"], len(e["tenths"]))


def _window(label: str) -> ph.WindowStats:
    with _tele_lock:
        return _stats(_tele.get(label), _now())


def attempt_start(label: str | None) -> None:
    """One `_proxy_retry` attempt through `label` begins (inflight +1)."""
    if not label:
        return
    with _tele_lock:
        e = _tele_entry(label)
        e["inflight"] += 1
        e["inflight_peak"] = max(e["inflight_peak"], e["inflight"])


def attempt_end(label: str | None, refused: bool | None) -> None:
    """It ended: refused (a ProxyError), ok (an answer), or None (any other failure: not in the window)."""
    if not label:
        return
    with _tele_lock:
        _tele_entry(label)["inflight"] -= 1
    if refused is not None:
        _sample(label, refused)


def _sample(label: str, refused: bool) -> None:
    """One outcome into the window. A refusal that makes the window `ph.flap_trips` (knob on) sends FlapBad;
    decide leaves a proxy already down, or in a DOWN_AFTER streak, to the outage path."""
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
    """`health.refusals`: attempts refused / made through `label` in the last window_s() seconds."""
    w = _window(label)
    return {"window_s": window_s(), "refused": w.refused, "calls": w.calls, "pct": w.pct}


def still_flapping(label: str) -> bool:
    """`ph.flap_holds` on `label`'s window now (knob on): a flap-bad proxy stays bad while it holds."""
    return ph.flap_holds(_window(label), flap_bad_pct())


def herd_guarded(label: str) -> bool:
    """`ph.flap_guards` on `label`'s window now (knob on): no new binding or move onto it (`unusable_labels`)."""
    return ph.flap_guards(_window(label), flap_bad_pct())


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
        return  # healthy and staying healthy: nothing to write (no entry made, the lock not taken)
    _step(label, lambda: ph.CallOk(_now(), still_flapping(label)) if ok else ph.CallErr(_now(), error, label in _watchers))


def _step(label: str, event: Callable[[], ph.Event]) -> ph.Next:
    """One lock section: the event built under the lock (its time read there), `decide`, its state
    written (None: the entry dropped), and the claim: a Watch claims the label (before its thread
    starts), an Unwatch releases it (with the watcher's last step: an error right after sees no
    watcher and starts one). Then, outside the lock, a Watch's thread and the other effects in order.
    Returns the watcher's next move."""
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
    """A proxy's country as its last answering trace saw it (`note_trace`; None: never seen)."""
    with _lock:
        return ((_state.get(p.get("label") or "") or {}).get("trace") or {}).get("geo")


def verify_pick(p: dict[str, Any], timeout_s: int = 15, region: bool = True) -> bool:
    """The destination check before a NEW binding (a login's attach step,
    Browserbase's bind) or a move (`_failover`, a held Creator re-picked):
    one probe through the pick, counted (unlike the Test button's). False = pass
    it over: nobody is moved onto a proxy that does not answer right now.
    `region=False` (a login's attach, which waits on it): no region trace, at most one probe a pick."""
    label = p.get("label") or ""
    result = proxy_probe.probe_of(p, timeout_s=timeout_s)
    if label:
        record_probe(label, result)
        if region and result.get("ok") and last_geo(p) is None:   # the region (failover's `like`): one uncounted trace
            note_trace(label, proxy_probe.probe(p, timeout_s=timeout_s))
    return bool(result.get("ok"))


def failover_due(label: str) -> bool:
    """Bad, and FAILOVER_AFTER_RECHECKS rechecks in a row failed: its pool
    Creators are to move. The one predicate `_failover` and `assign_pool` share."""
    with _lock:
        return ph.failover_due(_state.get(label))


def _due_labels() -> set[str]:
    with _lock:
        return {label for label, state in _state.items() if ph.failover_due(state)}


# The attach request (a login's last step) waits on its probes: a short
# timeout each, at most proxies.ATTACH_PROBES of them.
ATTACH_PROBE_TIMEOUT_S = 5


def assign_pool(account_id: str, rng: random.Random | None = None) -> tuple[dict[str, Any], bool]:
    """`proxies.assign_pool` with this module's view: unusable proxies skipped, a
    Creator moved off its proxy only when `failover_due` and onto a pick that
    answers (`verify_pick`, ATTACH_PROBE_TIMEOUT_S each), the region from the
    last probes. A Creator on no pool proxy is bound even when no pick
    answers (least-used not bad) or every pool proxy is bad (least-used, one
    not bad for an outage first). LookupError: the pool is empty."""
    reasons = bad_reasons()   # one read: `bad` and `dead` agree
    return proxies.assign_pool(account_id, bad=unusable_labels(reasons),
                               dead={lb for lb, why in reasons.items() if why == "down"}, due=_due_labels(),
                               geo=last_geo,
                               verify=lambda p: verify_pick(p, timeout_s=ATTACH_PROBE_TIMEOUT_S, region=False),
                               rng=rng)


def record_probe(label: str, result: dict[str, Any]) -> None:
    """Keep a `proxy_probe.probe_of` result; count its outcome (the periodic probe,
    `verify_pick`). A watcher's own probes go through `_probe` instead."""
    _keep_probe(label, result)
    record(label, bool(result.get("ok")), result.get("error"))


def note_trace(label: str, result: dict[str, Any]) -> None:
    """Keep an answering Cloudflare trace (the Test button, a new binding's
    region) in its own slot, `trace` {ip, geo, colo}: its geo is the region
    (`last_geo`, failover's `like`), kept through a failed probe or trace.
    Display and region only, never counted: health is `probe`, `proxy_probe.probe_of`'s."""
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
    # A probe is one attempt in the refusal window: ok, or refused (a ProxyError, as `_attempt`); else neither.
    if result.get("ok") or result.get("refused"):
        _sample(label, not result.get("ok"))


def _probe(label: str) -> bool | None:
    """One probe through `label`, kept in the state. None when the proxy is
    gone from the registry (its state is dropped; the watcher ends)."""
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
    """The watcher: confirm, then recheck with backoff until the proxy answers.
    One claim per label at a time (`_step`); never raises. Its last step's
    decide releases the claim (Unwatch), never this function: a release after
    it returns would swallow the errors landing in between (no new watcher).
    A watcher that raised has not reached that step (after it only logging
    runs), so it still holds the claim and drops it here: a plain discard,
    not a decide event, as decide would know nothing more than this."""
    try:
        _watch_inner(label)
    except Exception:
        log.warning("proxy watcher for %s failed", label, exc_info=True)
        with _lock:
            _watchers.discard(label)


def _confirm_due(label: str) -> ph.Next:
    return _step(label, lambda: ph.ConfirmDue(_now(), confirm_gap_s()))


def _watch_inner(label: str) -> None:
    """One flat loop: each `next` from `decide` names the step to run (ConfirmDue first: the wait of
    CONFIRM_GAP_S from the streak's first error); None ends it. Every rule is `decide`'s; this is the
    waiting and the probing."""
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
            # still_flapping: read after the probe's own sample (_keep_probe) is in the window.
            nxt = None if ok is None else _step(label, lambda: ph.RecheckResult(ok, still_flapping(label)))
        elif isinstance(nxt, ph.ArmRecheck):
            nxt = _arm_recheck(label)
        else:
            raise TypeError(f"unknown proxy watcher step {nxt!r}")


def _arm_recheck(label: str) -> ph.Next:
    """Arm the next recheck of a bad proxy: RECHECK_S (`recheck_s()`), doubled per failed recheck up to
    RECHECK_MAX_S. The rechecks run until it answers (or an answer through it brought it back meanwhile),
    or it is gone from the registry; its pool Creators move once `failover_due`, and again after each
    later failed recheck (a move that found no answering destination is retried)."""
    return _step(label, lambda: ph.RecheckWait(_now(), recheck_s()))


def _failover(label: str) -> list[str]:
    """Move the Creators on a bad pool proxy to pool proxies that answer
    (`proxies.failover_pool`: each destination probed by `verify_pick` before
    anyone is put on it; a provider-wide outage would otherwise herd everyone
    onto the last proxy not yet confirmed bad). Nothing is probed, stamped
    or logged when the proxy is not a pool proxy or nobody is on it
    (failover_pool returns None). Logged; [] when nobody moved (they stay,
    surfaced)."""
    moved = proxies.failover_pool(label, bad=unusable_labels(bad_reasons()), geo=last_geo, verify=verify_pick)
    if moved is None:
        return []
    _step(label, lambda: ph.FailedOver(_now(), tuple(moved)))
    return moved


def snapshot(label: str) -> dict[str, Any]:
    """`health` for one proxy: {state, down, errors, last_error, last_error_at,
    probe? (the health probe), trace? (display), probed_at?, bad_since?, next_recheck_at?, failed_over?...}. A
    proxy never seen reads as healthy."""
    with _lock:
        st = dict(_state.get(label) or {})
    st.setdefault("down", False)
    st.setdefault("errors", 0)
    st.pop("first_error_at", None)
    st.pop("streak", None)
    if not st.get("bad_reason"):   # set with down only (decide)
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
    """Each bad proxy's label: why it is bad, "down" or "flapping" (one read for a whole list)."""
    with _lock:
        return {label: st["bad_reason"] for label, st in _state.items() if st["down"]}


def unusable_labels(reasons: dict[str, str]) -> set[str]:
    """Never the destination of a new binding or a move (`assign_pool`, `_failover`): bad (`reasons`,
    the caller's one `bad_reasons()` read), or `herd_guarded` (even when its one probe answers)."""
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
    """Registry proxies with at least one Creator on them."""
    return [p for p in proxies.list_proxies() if p.get("label") and proxies._ids_on(p)]


def probe_all() -> int:
    """Probe every proxy a Creator is on, one at a time. Returns how many."""
    n = 0
    for p in probe_targets():
        record_probe(p["label"], proxy_probe.probe_of(p))
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
