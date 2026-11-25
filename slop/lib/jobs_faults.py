from __future__ import annotations

RULE_OFF = "rule switched off mid-run: its retry is cancelled, nothing sent after"
RULE_OFF_ERROR_PREFIX = "rule switched off ("


def _park_ignores_rule_off() -> None:
    import run_decide as rd

    real = rd.park

    def parking(attempts, rule_live, max_attempts):
        return real(attempts, None, max_attempts)

    rd.park = parking


def register(Fault) -> dict:
    return {
        "job-park-ignores-rule-off": Fault(_park_ignores_rule_off, (RULE_OFF,)),
    }
