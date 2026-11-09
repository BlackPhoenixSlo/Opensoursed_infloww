"""The slow-connections flow's break-it-once fault (scenarios/2026-11-05-slow-connections.py): lib/faults.py merges
`register(Fault)` into FAULTS. Check names carry no number: the budgets live in the scenario's BUDGET_MS (the ms in
each check's detail and the table); both sides build the name with `budget_check`.
"""
from __future__ import annotations

SI_FORCED = "net-si-budget-forced"
LOSSY_SI_FORCED = "net-lossy-si-budget-forced"  # --net=jp-lossy --break --fault=net-lossy-si-budget-forced


def budget_check(profile: str, flow: str) -> str:
    return f"{profile}: {flow} within budget"


# Far-profile flows measured at least twice si's budget in the 345a baseline; other flows are not targets.
TARGETS: tuple[str, ...] = (
    budget_check("jp-mobile", "dashboard"),
    budget_check("jp-mobile", "fan-list"),
    budget_check("jp-mobile", "vault"),
    budget_check("jp-bad", "dashboard"),
    budget_check("jp-bad", "fan-list"),
    budget_check("jp-bad", "vault"),
)


# jp-lossy flows measured at least twice si's budget in baselines b548 and aa1e; other flows are not targets.
LOSSY_TARGETS: tuple[str, ...] = tuple(budget_check("jp-lossy", f) for f in ("dashboard", "creators", "fan-list", "vault"))


def register(Fault) -> dict:
    # slop/run slow-connections --break: Harness side (no relay or app change): the scenario judges every profile's
    # ready times against si's budgets, i.e. "the code is as fast as on the owner's line" is false over 250 ms RTT.
    # The wire twin: si's budgets on jp-lossy ("loss costs nothing" is false); harness side as well.
    return {SI_FORCED: Fault(None, TARGETS), LOSSY_SI_FORCED: Fault(None, LOSSY_TARGETS)}
