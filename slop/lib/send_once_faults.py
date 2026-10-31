"""Send once's break-it-once fault (service/run_decide.py `ONE_SHOT_KINDS`, which
run_decide.sends_once (run_once's outcome) and one_shot_family (the boot heal) read at call
time, so the patch is what the real run and boot heal perform): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and
scenarios/2026-10-31-scheduled-send-once.py imports them, so a target can never name a check
that does not exist.
"""
from __future__ import annotations

ONCE = "OF holds exactly 1 message per job"
SETTLED = "every job ends done or error (none pending/running)"
PARKED = "parked jobs carry 'may have sent'"
REFUSED = "a send OF never saw (proxy refused) is retried and ends done"


def _retries_after_accept() -> None:
    """The pre-fix lane: no kind sends once, so every failed or orphaned job goes back to
    pending, one-shots too, and a send OF took is sent again. A not-sent failure and every
    sweep requeue exactly as with the fix, so only ONCE can see it."""
    import run_decide

    run_decide.ONE_SHOT_KINDS = frozenset()


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-31-scheduled-send-once --break --no-ui
        "send-once-retries-after-accept": Fault(_retries_after_accept, (ONCE,)),
    }
