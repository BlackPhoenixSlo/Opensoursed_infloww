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
    deactivated, parked = set(deactivated), set(parked)
    eligible = {a for a in with_session if a not in deactivated}
    actions: list[Action] = [Start(a) for a in sorted(eligible - parked) if a not in pump_done]
    for aid, done in pump_done.items():
        if aid not in eligible:
            actions.append(Stop(aid))
        elif done and aid not in parked:
            actions.append(Restart(aid))
    return actions


# A pump that exits without parking would otherwise be restarted every pass, forever.
BACKOFF_BASE_S = 15.0
BACKOFF_CAP_S = 300.0
HEALTHY_RUN_S = 60.0


def restart_backoff(attempts: int, ran_s: float) -> tuple[int, float]:
    n = 0 if ran_s >= HEALTHY_RUN_S else attempts
    return n, 0.0 if n == 0 else min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (n - 1))


def restart_due(attempts: int, started: float, exited: float, parked: bool) -> tuple[int, float]:
    n, delay = restart_backoff(0 if parked else attempts, exited - started)
    return n, exited + delay
