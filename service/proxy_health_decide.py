# A watcher step with nothing of its own left goes through _resume, the only place Unwatch is emitted: no proxy is left bad or at DOWN_AFTER with nobody watching.
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Union

DOWN_AFTER = 3
FAILOVER_AFTER_RECHECKS = 2
RECHECK_MAX_S = 600.0  # the recheck's doubling stops here (6 probes an hour for a proxy that stays dead)
FLAP_MIN_CALLS = 20
FLAP_BUCKETS = 3  # refusals must land in this many tenths of the window, else a blip; a short full outage sits in one or two and the confirm path owns it

State = Optional[dict[str, Any]]


@dataclass(frozen=True)
class WindowStats:
    calls: int
    refused: int
    spread: int

    @property
    def pct(self) -> float:
        return round(100.0 * self.refused / self.calls, 1) if self.calls else 0.0


def flap_trips(w: WindowStats, knob: float) -> bool:
    return flap_guards(w, knob) and w.refused * 100.0 >= knob * w.calls


# Hysteresis with no recency rule: a flap-bad proxy returns only once its window drains, so a burst minutes ago cannot read clean and re-trip on the next refusal (each trip is a move).
def flap_holds(w: WindowStats, knob: float) -> bool:
    return bool(knob) and w.calls >= FLAP_MIN_CALLS and w.refused * 200.0 >= knob * w.calls


def flap_guards(w: WindowStats, knob: float) -> bool:
    # Herd guard: one blip (<= 2 tenths) never holds a clean proxy out of rotation for the whole window.
    return flap_holds(w, knob) and w.spread >= FLAP_BUCKETS


@dataclass(frozen=True)
class CallOk:
    now: float
    flapping: bool


@dataclass(frozen=True)
class FlapBad:
    now: float
    watching: bool
    pct: float
    calls: int


@dataclass(frozen=True)
class CallErr:
    now: float
    error: Optional[str]
    watching: bool


@dataclass(frozen=True)
class ConfirmDue:
    now: float
    gap: float


@dataclass(frozen=True)
class ConfirmResult:
    now: float
    ok: bool
    streak: int


@dataclass(frozen=True)
class RecheckWait:
    now: float
    base: float


@dataclass(frozen=True)
class RecheckDue:
    pass


@dataclass(frozen=True)
class RecheckResult:
    ok: bool
    flapping: bool


@dataclass(frozen=True)
class Gone:
    pass


@dataclass(frozen=True)
class FailedOver:
    now: float
    moved: tuple[str, ...]


Event = Union[CallOk, FlapBad, CallErr, ConfirmDue, ConfirmResult, RecheckWait, RecheckDue, RecheckResult, Gone,
              FailedOver]


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
    msg: str
    args: tuple = ()


Effect = Union[Watch, Unwatch, Announce, Failover, Log]


@dataclass(frozen=True)
class Wait:
    s: float
    then: type


@dataclass(frozen=True)
class Confirm:
    streak: int


@dataclass(frozen=True)
class Recheck:
    pass


@dataclass(frozen=True)
class ArmRecheck:
    pass


Next = Optional[Union[Wait, Confirm, Recheck, ArmRecheck]]


def blank() -> dict[str, Any]:
    return {"errors": 0, "first_error_at": None, "streak": 0, "down": False, "bad_reason": None, "last_error": None,
            "last_error_at": None}


_UP = {"errors": 0, "first_error_at": None, "down": False, "bad_reason": None, "rechecks_failed": 0,
       "next_recheck_at": None, "rechecking": False}


def failover_due(st: State) -> bool:
    return bool(st and st["down"] and st.get("rechecks_failed", 0) >= FAILOVER_AFTER_RECHECKS)


def recheck_delay(base: float, failed: int) -> float:
    return base if failed <= 0 else min(base * 2 ** min(failed, 64), RECHECK_MAX_S)


def _resume(st: State) -> tuple[list[Effect], Next]:
    if st is not None and st["down"]:
        return [], ArmRecheck()
    if st is not None and st["errors"] >= DOWN_AFTER:
        return [], Wait(0.0, ConfirmDue)
    return [Unwatch()], None


def decide(st: State, ev: Event) -> tuple[State, list[Effect], Next]:
    if isinstance(ev, CallOk):
        cur = st if st is not None else blank()
        if cur["bad_reason"] == "flapping" and ev.flapping:
            return {**cur, "errors": 0, "first_error_at": None}, [], None
        if cur["down"]:
            return {**cur, **_UP}, [Log(logging.WARNING, "proxy %s is back up"), Announce(False)], None
        return {**cur, **_UP}, [], None

    if isinstance(ev, FlapBad):
        cur = st if st is not None else blank()
        if cur["down"] or cur["errors"] >= DOWN_AFTER:
            return st, [], None
        nxt = {**cur, "down": True, "bad_reason": "flapping", "bad_since": ev.now, "rechecks_failed": 0}
        return nxt, [Log(logging.WARNING, "proxy %s is DOWN (refusing %.0f%% of %d calls)", (ev.pct, ev.calls)),
                     Announce(True), *([] if ev.watching else [Watch()])], None

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
        if st["down"]:
            return (st, *_resume(st))
        if not st["errors"] or st["streak"] != ev.streak:
            effects, then = _resume(st)
            return st, [Log(logging.INFO, "proxy %s: a call got through during the confirm probe; not marked bad"),
                        *effects], then
        nxt = {**st, "down": True, "bad_reason": "down", "bad_since": ev.now, "rechecks_failed": 0}
        effects, then = _resume(nxt)
        return nxt, [Log(logging.WARNING, "proxy %s is DOWN (confirmed by probe)"), Announce(True), *effects], then

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
        # Written whatever happened during the probe: an answer brings it up and is announced even when a call already did.
        cur = {**(st or blank()), "rechecking": False}
        if ev.ok and not (cur["bad_reason"] == "flapping" and ev.flapping):
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
