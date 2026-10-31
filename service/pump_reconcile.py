"""The pump supervisor's pass, pure (docs/reducer-scan.md, Non-React #4).

`reconcile` decides, from the roster and whether each pump task is done, which
per-account WS pumps to start, stop or restart. No asyncio, no I/O, no imports from
the service: server.py's `_reconcile_pumps` gathers the inputs and performs the
actions in the order returned.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class Start:
    account_id: str


@dataclass(frozen=True)
class Stop:
    account_id: str


@dataclass(frozen=True)
class Restart:
    account_id: str


Action = Union[Start, Stop, Restart]


def reconcile(
    with_session: Iterable[str],
    deactivated: Iterable[str],
    parked: Iterable[str],
    pump_done: Mapping[str, bool],
) -> list[Action]:
    """One supervisor pass. `pump_done` maps each account with a pump task to
    whether that task is done. An account is eligible when it has a session and is not
    deactivated; a parked one (session dead) is eligible but gets no new pump, and
    its done pump is left in place until the flag clears. A session change is no
    input here: post_bootstrap_hooks restarts that pump itself (server.py
    `_restart_account_pump`).

    - eligible, not parked, no pump -> Start
    - eligible, not parked, its pump done -> Restart
    - a pump whose account is not eligible (deleted, lost its session,
      deactivated), parked or not -> Stop

    Order: the Starts by account id, then the Stops and Restarts in `pump_done`'s
    iteration order.
    """
    deactivated, parked = set(deactivated), set(parked)
    eligible = {a for a in with_session if a not in deactivated}
    actions: list[Action] = [Start(a) for a in sorted(eligible - parked) if a not in pump_done]
    for aid, done in pump_done.items():
        if aid not in eligible:
            actions.append(Stop(aid))
        elif done and aid not in parked:
            actions.append(Restart(aid))
    return actions


# A Restart's backoff. A pump that exits without parking (an error before its own
# reconnect loop) would otherwise be restarted every pass, forever.
BACKOFF_BASE_S = 15.0   # the supervisor's cadence: a shorter wait is never seen in prod
BACKOFF_CAP_S = 300.0
HEALTHY_RUN_S = 60.0    # a pump that ran this long before it exited was healthy


def restart_backoff(attempts: int, ran_s: float) -> tuple[int, float]:
    """(attempt, delay_s) for a Restart of a pump that exited after running `ran_s`
    seconds; `attempts` is the supervisor's restarts of that account since its last
    healthy run. A healthy run (>= HEALTHY_RUN_S) resets the count. Attempt 0 restarts
    at once (a one-off exit, or a pump the recovery probe unparked), then 15, 30, 60 ...
    s after the exit, capped at BACKOFF_CAP_S."""
    n = 0 if ran_s >= HEALTHY_RUN_S else attempts
    return n, 0.0 if n == 0 else min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (n - 1))


def restart_due(attempts: int, started: float, exited: float, parked: bool) -> tuple[int, float]:
    """(attempt, due): computed once when a pump exits, from its start and exit times
    (one clock). A Restart waits until `due`; the caller then stores attempt + 1. A
    parked exit (the session went dead) is no crash: it resets the count like a healthy
    run, so the restart after the recovery probe unparks it goes at once."""
    n, delay = restart_backoff(0 if parked else attempts, exited - started)
    return n, exited + delay
