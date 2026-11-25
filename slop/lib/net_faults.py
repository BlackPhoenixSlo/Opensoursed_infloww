from __future__ import annotations

SI_FORCED = "net-si-budget-forced"
LOSSY_SI_FORCED = "net-lossy-si-budget-forced"


def budget_check(profile: str, flow: str) -> str:
    return f"{profile}: {flow} within budget"


# far-profile flows measured at least twice si's budget in baseline; other flows are not targets
TARGETS: tuple[str, ...] = (
    budget_check("jp-mobile", "dashboard"),
    budget_check("jp-mobile", "fan-list"),
    budget_check("jp-mobile", "vault"),
    budget_check("jp-bad", "dashboard"),
    budget_check("jp-bad", "fan-list"),
    budget_check("jp-bad", "vault"),
)


# jp-lossy flows measured at least twice si's budget in baselines; other flows are not targets
LOSSY_TARGETS: tuple[str, ...] = tuple(budget_check("jp-lossy", f) for f in ("dashboard", "creators", "fan-list", "vault"))


def register(Fault) -> dict:
    return {SI_FORCED: Fault(None, TARGETS), LOSSY_SI_FORCED: Fault(None, LOSSY_TARGETS)}
