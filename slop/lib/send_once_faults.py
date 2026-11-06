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
REFUSED_DEFERRED = ("a proxy-refused broadcast (send_mass_message) waits out the burst: its job reads "
                    "'proxy_retry:1' (GET /admin/system/runs last_error), due PROXY_RETRY_MINUTES after the "
                    "refusal, then OF takes it once")
REFUSED_TERMINAL = ("a broadcast the proxy refuses every time ends error 'proxy_refused' after "
                    "PROXY_RETRIES + 1 tries (proxy_retry:1..3 between); OF never saw it")
REFUSED_RUN_CLOSED = "every mass run minted for a refused broadcast POST reads 'refused' (none left running)"
REFUSED_DM_PLAIN = "a proxy-refused composer DM (scheduled_send) keeps the plain retry: its job never reads 'proxy_retry'"


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


def _refused_job_not_deferred() -> None:
    """The pre-fix park: run_once never sees a refusal (its `proxy_refused`, a module global,
    always False), so a refused job retries after the plain 60 s backoff, `last_error` the bare
    error: the once-refused broadcast is sent ~60 s later, the always-refused one ends error after
    3 plain tries. Only REFUSED_DEFERRED and REFUSED_TERMINAL can see it (its runs still close
    'refused'; the composer DM never deferred)."""
    import automation_executor

    automation_executor.proxy_refused = lambda e: False


def _composer_send_deferred() -> None:
    """The composer's scheduled_send waits out the proxy like a broadcast (5 min): a chatter's DM
    lands behind the chat's later messages. Only REFUSED_DM_PLAIN (the scenario skips that wait too)."""
    import run_decide

    run_decide.PROXY_DEFER_KINDS = run_decide.PROXY_DEFER_KINDS | {"scheduled_send"}


def _mass_refused_run_left_running() -> None:
    """The pre-fix send_mass_message: a refused POST leaves its minted run 'running'. Only
    REFUSED_RUN_CLOSED."""
    from automations import send_mass_message

    async def keep(_mass_run_id: int) -> None:
        return None

    send_mass_message._close_refused_run = keep


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-31-scheduled-send-once --break --no-ui
        "send-once-retries-after-accept": Fault(_retries_after_accept, (ONCE, ECHO_5XX)),
        # slop/run 2026-10-31-scheduled-send-once --break --fault=rate-limit-text-sniff --no-ui
        "rate-limit-text-sniff": Fault(_rate_limit_text_sniff, (ONCE, ECHO_5XX)),
        # slop/run 2026-10-31-scheduled-send-once --break --fault=refused-job-not-deferred --no-ui
        "refused-job-not-deferred": Fault(_refused_job_not_deferred, (REFUSED_DEFERRED, REFUSED_TERMINAL)),
        # slop/run 2026-10-31-scheduled-send-once --break --fault=composer-send-deferred --no-ui
        "composer-send-deferred": Fault(_composer_send_deferred, (REFUSED_DM_PLAIN,)),
        # slop/run 2026-10-31-scheduled-send-once --break --fault=mass-refused-run-left-running --no-ui
        "mass-refused-run-left-running": Fault(_mass_refused_run_left_running, (REFUSED_RUN_CLOSED,)),
    }
