"""The slow-connections flow's break-it-once fault (scenarios/2026-11-05-slow-connections.py): lib/faults.py merges
`register(Fault)` into FAULTS. Check names carry no number: the budgets live in the scenario's BUDGET_MS (the ms in
each check's detail and the table); both sides build the name with `budget_check`.
"""
from __future__ import annotations

SI_FORCED = "net-si-budget-forced"
LOSSY_SI_FORCED = "net-lossy-si-budget-forced"  # --net=jp-lossy --break --fault=net-lossy-si-budget-forced


def budget_check(profile: str, flow: str) -> str:
    return f"{profile}: {flow} within budget"


# The far-profile budgets whose measured ready (min over 345a) is >= 2x si's budget, so si's budget fails them for
# the network alone: jp-mobile dashboard (4651 vs 1550), jp-mobile fan-list (2033 vs 950), jp-mobile vault (6055 vs
# 1900), jp-bad dashboard (9973 vs 1550), jp-bad fan-list (4292 vs 950), jp-bad vault (9429 vs 1900). Not targets (<
# 2x, could pass under si's budget on a quiet run): jp dashboard (2246 vs 1550), jp creators (935 vs 1000), jp
# fan-list (1101 vs 950), jp thread (834 vs 1200), jp vault (1285 vs 1900), jp send (878 vs 950), jp-mobile creators
# (1114 vs 1000), jp-mobile thread (1064 vs 1200), jp-mobile send (950 vs 950), jp-bad creators (1699 vs 1000),
# jp-bad thread (1330 vs 1200), jp-bad send (1280 vs 950); and receive (one budget for every profile).
TARGETS: tuple[str, ...] = (
    budget_check("jp-mobile", "dashboard"),
    budget_check("jp-mobile", "fan-list"),
    budget_check("jp-mobile", "vault"),
    budget_check("jp-bad", "dashboard"),
    budget_check("jp-bad", "fan-list"),
    budget_check("jp-bad", "vault"),
)


# jp-lossy (dummynet, 2 % loss) under si's budgets: its flows measured >= 2x si's in both baselines (b548, aa1e):
# dashboard (16207 vs 1550), creators (2469 vs 1000), fan-list (3982 vs 950), vault (14171 vs 1900). Not targets:
# thread (1651 vs 1200), send (1137 vs 950), receive (255-305 vs si's 800).
LOSSY_TARGETS: tuple[str, ...] = tuple(budget_check("jp-lossy", f) for f in ("dashboard", "creators", "fan-list", "vault"))


def register(Fault) -> dict:
    # slop/run slow-connections --break: Harness side (no relay or app change): the scenario judges every profile's
    # ready times against si's budgets, i.e. "the code is as fast as on the owner's line" is false over 250 ms RTT.
    # The wire twin: si's budgets on jp-lossy ("loss costs nothing" is false); harness side as well.
    return {SI_FORCED: Fault(None, TARGETS), LOSSY_SI_FORCED: Fault(None, LOSSY_TARGETS)}
