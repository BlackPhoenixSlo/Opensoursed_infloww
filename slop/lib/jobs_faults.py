"""The scheduled-jobs lane's break-it-once fault (service/run_decide.py `park`, which
job_queue._park_failed_job calls through the module, so the patch is what the real park
performs): lib/faults.py merges `register(Fault)` into FAULTS. The check name lives here and
scenarios/2026-10-30-dispatch-plan.py imports it, so a target can never name a check that
does not exist. Its rule-off phase switches an auto_posts rule off (the Ready-made panel's
PATCH) while the rule's job is in flight, then OnlyFans refuses the post.
"""
from __future__ import annotations

RULE_OFF = "rule switched off mid-run: its retry is cancelled, nothing sent after"
# The cancelled job's last_error prefix: job_queue.RULE_OFF_REASON + " (" (the scenario
# reads the relay's DB, it imports no service code).
RULE_OFF_ERROR_PREFIX = "rule switched off ("


def _park_ignores_rule_off() -> None:
    """park never looks at the rule's liveness: a failed job whose rule the operator
    switched off while it ran goes back to pending with the backoff (the bug class of a
    dropped liveness gate on the retry path; the rules API leaves a running job alone).
    Every live rule's retry and every out-of-attempts error is unchanged, so only RULE_OFF
    can see it."""
    import run_decide as rd

    real = rd.park

    def parking(attempts, rule_live, max_attempts):
        return real(attempts, None, max_attempts)

    rd.park = parking


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-dispatch-plan --break --fault=job-park-ignores-rule-off --no-ui
        "job-park-ignores-rule-off": Fault(_park_ignores_rule_off, (RULE_OFF,)),
    }
