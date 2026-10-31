"""
One proxy's down / confirm / recheck / failover rules as a pure transition
(docs/reducer-scan.md "Non-React" 2; the states and timeline: proxy_health.py,
docs/adr/0030):

    decide(state, event) -> (state', effects, next)

`state` is the label's entry in `proxy_health._state` (None: no entry) and is
never mutated; `state'` replaces it (None: no entry). No clock, no lock, no
I/O, no logging here: the shell in proxy_health.py builds each event under its
lock (the time in it read there), calls decide, writes state', and after the
lock performs the effects in order, then the watcher's next move. Each event
is one of the shell's lock sections:

  CallOk / CallErr   record(): an OF call or a probe through the proxy answered / failed
  ConfirmDue         the confirm's wait is over (owns every confirm wait: the gap from the streak's first error)
  ConfirmResult      the confirm probe's answer, for the streak its Confirm named
  RecheckWait        arm the next recheck (stamp next_recheck_at; base = recheck_s(), read at each arm)
  RecheckDue         the recheck's wait is over
  RecheckResult      the recheck probe's answer
  Gone               the label left the registry (the probe found no proxy)
  FailedOver         proxies.failover_pool answered (moved: who; () = nobody)

Effects: Watch (claim the label, then spawn its watcher thread), Unwatch
(release the claim), Announce(down) (`proxy_switched` to each Creator on it),
Failover (`_failover`), Log. The shell applies Watch's claim and Unwatch's
release in the same lock section as the state write.
`next`, the watcher's next move, names the event it sends next: Wait(s, then)
(sleep s, then send `then`: ConfirmDue or RecheckDue), Confirm(streak) (probe
now; ConfirmResult(streak)), Recheck (probe now; RecheckResult), ArmRecheck
(send RecheckWait now), or None: the watcher ends. Steps outside the watcher
(CallOk, CallErr, FailedOver: the last runs inside the Failover effect,
mid-recheck) return None and never Unwatch.

The claim's contract: a watcher step with nothing of its own left to do goes
through one exit, `_resume(state')`, the only place Unwatch is emitted. Bad:
keep rechecking (ArmRecheck). Not bad but at DOWN_AFTER errors (a call brought
it back mid-recheck, then a streak landed while this watcher held the claim, so
it started none): back to the confirm phase (Wait(0, ConfirmDue)), same
watcher. Otherwise: Unwatch and next None, in the same decide as the
watcher's last step, so a CallErr right after reads `watching` False (built
under the same lock) and gets its Watch. So the watcher goes on exactly while
its state warrants one: no proxy is left bad or at DOWN_AFTER errors with
nobody watching it.

Importable without side effects (stdlib only).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Union

DOWN_AFTER = 3                # consecutive counted errors that start the confirm
FAILOVER_AFTER_RECHECKS = 2   # failed rechecks in a row before a pool proxy's Creators move
RECHECK_MAX_S = 600.0         # the recheck's doubling stops here (6 probes an hour for a proxy that stays dead)

State = Optional[dict[str, Any]]


# ── events ──
@dataclass(frozen=True)
class CallOk:
    now: float


@dataclass(frozen=True)
class CallErr:
    now: float
    error: Optional[str]
    watching: bool            # the label already has a watcher (`proxy_health._watchers`)


@dataclass(frozen=True)
class ConfirmDue:
    now: float
    gap: float                # confirm_gap_s(): no confirm sooner than this after the streak's first error


@dataclass(frozen=True)
class ConfirmResult:
    now: float
    ok: bool
    streak: int               # Confirm(streak): the streak this probe confirms


@dataclass(frozen=True)
class RecheckWait:
    now: float
    base: float               # recheck_s(), read at each arm: the first recheck's delay


@dataclass(frozen=True)
class RecheckDue:
    pass


@dataclass(frozen=True)
class RecheckResult:
    ok: bool


@dataclass(frozen=True)
class Gone:
    pass


@dataclass(frozen=True)
class FailedOver:
    now: float
    moved: tuple[str, ...]


Event = Union[CallOk, CallErr, ConfirmDue, ConfirmResult, RecheckWait, RecheckDue, RecheckResult, Gone,
              FailedOver]


# ── effects ──
@dataclass(frozen=True)
class Watch:
    pass


@dataclass(frozen=True)
class Unwatch:
    pass


@dataclass(frozen=True)
class Announce:
    down: bool


@dataclass(frozen=True)
class Failover:
    pass


@dataclass(frozen=True)
class Log:
    level: int
    msg: str                  # %-format; the shell passes the label first, then args
    args: tuple = ()


Effect = Union[Watch, Unwatch, Announce, Failover, Log]


# ── the watcher's next move: each names the event the watcher sends next ──
@dataclass(frozen=True)
class Wait:
    s: float
    then: type                # ConfirmDue or RecheckDue: sent once the wait is over


@dataclass(frozen=True)
class Confirm:
    streak: int               # probe now; its ConfirmResult names this streak


@dataclass(frozen=True)
class Recheck:
    pass                      # probe now; its RecheckResult follows


@dataclass(frozen=True)
class ArmRecheck:
    pass                      # send RecheckWait now


Next = Optional[Union[Wait, Confirm, Recheck, ArmRecheck]]


def blank() -> dict[str, Any]:
    # streak: bumped at each streak's first error; a confirm is for one streak (ConfirmResult.streak)
    return {"errors": 0, "first_error_at": None, "streak": 0, "down": False, "last_error": None,
            "last_error_at": None}


_UP = {"errors": 0, "first_error_at": None, "down": False, "rechecks_failed": 0, "next_recheck_at": None,
       "rechecking": False}


def failover_due(st: State) -> bool:
    """Bad, and FAILOVER_AFTER_RECHECKS rechecks in a row failed: its pool Creators are to move."""
    return bool(st and st["down"] and st.get("rechecks_failed", 0) >= FAILOVER_AFTER_RECHECKS)


def recheck_delay(base: float, failed: int) -> float:
    """The wait before the next recheck: base, then doubled per failed recheck up to RECHECK_MAX_S
    (the first one is never capped: a PROXY_RECHECK_S over the cap is honoured once)."""
    return base if failed <= 0 else min(base * 2 ** min(failed, 64), RECHECK_MAX_S)


def _resume(st: State) -> tuple[list[Effect], Next]:
    """Where the watcher goes when its step has nothing of its own left to do: the one place it ends.
    Bad: it keeps rechecking. Not bad but at DOWN_AFTER errors (a call brought it back, then a new
    streak landed while this watcher still held the claim, so that streak started none): back to the
    confirm phase. Otherwise (no entry, or below the bar) nothing warrants a watcher: Unwatch, the
    claim released in this same decide, so the next DOWN_AFTER-th error reads watching=False."""
    if st is not None and st["down"]:
        return [], ArmRecheck()
    if st is not None and st["errors"] >= DOWN_AFTER:
        return [], Wait(0.0, ConfirmDue)
    return [Unwatch()], None


def decide(st: State, ev: Event) -> tuple[State, list[Effect], Next]:
    if isinstance(ev, CallOk):
        cur = st if st is not None else blank()
        if cur["down"]:
            return {**cur, **_UP}, [Log(logging.WARNING, "proxy %s is back up"), Announce(False)], None
        return {**cur, **_UP}, [], None

    if isinstance(ev, CallErr):
        cur = st if st is not None else blank()
        nxt = {**cur, "errors": cur["errors"] + 1, "last_error": (ev.error or "error")[:200],
               "last_error_at": ev.now}
        if not cur["errors"]:
            nxt.update(first_error_at=ev.now, streak=cur["streak"] + 1)
        if nxt["errors"] >= DOWN_AFTER and not nxt["down"] and not ev.watching:
            return nxt, [Watch()], None
        return nxt, [], None

    if isinstance(ev, ConfirmDue):
        # The gap from the streak's first error, then Confirm(it). An answer reset the count (a blip): no
        # confirm. A new streak since moved first_error_at: waited out from it.
        if not st or st["down"] or st["errors"] < DOWN_AFTER:
            return (st, *_resume(st))
        wait = st["first_error_at"] + ev.gap - ev.now
        return st, [], Confirm(st["streak"]) if wait <= 0 else Wait(wait, ConfirmDue)

    if isinstance(ev, ConfirmResult):
        if st is None:
            return (None, *_resume(None))
        if ev.ok:
            nxt = {**st, "errors": 0, "first_error_at": None}
            effects, then = _resume(nxt)
            return nxt, [Log(logging.INFO, "proxy %s: %d errors in a row but the probe answers; not marked bad",
                             (DOWN_AFTER,)), *effects], then
        if not st["errors"] or st["streak"] != ev.streak:
            # A call got through during the probe (it reset the streak this confirm was for): not bad
            # (ADR 0030). A new streak at DOWN_AFTER since: the same watcher waits it out and confirms it.
            effects, then = _resume(st)
            return st, [Log(logging.INFO, "proxy %s: a call got through during the confirm probe; not marked bad"),
                        *effects], then
        nxt = {**st, "down": True, "bad_since": ev.now, "rechecks_failed": 0}
        effects, then = _resume(nxt)
        return nxt, [Log(logging.WARNING, "proxy %s is DOWN (confirmed by probe)"), Announce(True), *effects], then

    # The recheck steps read a missing entry as a blank one and never create it.
    if isinstance(ev, RecheckWait):
        if not (st or blank())["down"]:
            return (st, *_resume(st))
        delay = recheck_delay(ev.base, st.get("rechecks_failed", 0))
        return {**st, "next_recheck_at": ev.now + delay}, [], Wait(delay, RecheckDue)

    if isinstance(ev, RecheckDue):
        if not (st or blank())["down"]:
            return (st, *_resume(st))
        return {**st, "rechecking": True, "next_recheck_at": None}, [], Recheck()

    if isinstance(ev, RecheckResult):
        # Written whatever happened during the probe (as before): an answer brings it up and is announced
        # even when a call already did; a failure counts even when a call brought it back meanwhile.
        cur = {**(st or blank()), "rechecking": False}
        if ev.ok:
            nxt: State = {**cur, **_UP} if st is not None else None
            effects, then = _resume(nxt)
            return nxt, [Log(logging.WARNING, "proxy %s is back up (recheck)"), Announce(False), *effects], then
        nxt = {**cur, "rechecks_failed": cur.get("rechecks_failed", 0) + 1} if st is not None else None
        effects, then = _resume(nxt)
        return nxt, ([Failover()] if failover_due(nxt) else []) + effects, then

    if isinstance(ev, Gone):
        effects, then = _resume(None)
        return None, [Log(logging.INFO, "proxy %s is gone from the registry; its watcher ends"), *effects], then

    if isinstance(ev, FailedOver):
        cur = st if st is not None else blank()
        nxt = {**cur, "failed_over_at": ev.now, "failed_over": cur.get("failed_over", 0) + len(ev.moved)}
        if ev.moved:
            return nxt, [Log(logging.WARNING, "proxy %s: %d Creator(s) moved to healthy pool proxies: %s",
                             (len(ev.moved), list(ev.moved)))], None
        return nxt, [Log(logging.WARNING,
                         "proxy %s: nobody moved (no pool proxy answers); retried at the next failed recheck")], None

    raise TypeError(f"unknown proxy health event {ev!r}")
