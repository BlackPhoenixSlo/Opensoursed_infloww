"""Send once's break-it-once faults (service/run_decide.py `ONE_SHOT_KINDS`, which
run_decide.sends_once (run_once's outcome) and one_shot_family (the boot heal) read at call
time, so the patch is what the real run and boot heal perform; of_write.is_rate_limited,
read as a module global by of_write_with_retry): lib/faults.py merges
`register(Fault)` into FAULTS. The check names live here and
scenarios/2026-10-31-scheduled-send-once.py imports them, so a target can never name a check
that does not exist.
"""
from __future__ import annotations

ONCE = "OF holds exactly 1 message per job"
SETTLED = "every job ends done or error (none pending/running)"
PARKED = "parked jobs carry 'may have sent'"
REFUSED = "a send OF never saw (proxy refused) is retried and ends done"
ECHO_5XX = "a 5xx echoing OF's rate-limit text: one OF message, job error 'may have sent', never resent"


def _retries_after_accept() -> None:
    """The pre-fix lane: no kind sends once, so every failed or orphaned job goes back to
    pending, one-shots too, and a send OF took is sent again. A not-sent failure and every
    sweep requeue exactly as with the fix, so only ONCE (and ECHO_5XX, phase C's parked
    send) can see it."""
    import run_decide

    run_decide.ONE_SHOT_KINDS = frozenset()


def _rate_limit_text_sniff() -> None:
    """The pre-fix gate: OF's rate-limit text alone is a refusal, whatever the status, so
    of_write_with_retry sends a 5xx echo again (OF has it twice). On of_write and on
    automation_executor's re-export (the senders read `ax.is_rate_limited`)."""
    import automation_executor
    import of_write

    def sniff(exc: BaseException) -> bool:
        return of_write._RATE_LIMIT_MARK in str(exc).lower()

    of_write.is_rate_limited = automation_executor.is_rate_limited = sniff


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-31-scheduled-send-once --break --no-ui
        "send-once-retries-after-accept": Fault(_retries_after_accept, (ONCE, ECHO_5XX)),
        # slop/run 2026-10-31-scheduled-send-once --break --fault=rate-limit-text-sniff --no-ui
        "rate-limit-text-sniff": Fault(_rate_limit_text_sniff, (ONCE, ECHO_5XX)),
    }
