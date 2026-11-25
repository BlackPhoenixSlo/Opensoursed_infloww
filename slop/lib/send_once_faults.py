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
    import run_decide

    run_decide.ONE_SHOT_KINDS = frozenset()


def _rate_limit_text_sniff() -> None:
    import automation_executor
    import of_write

    def sniff(exc: BaseException) -> bool:
        return of_write._RATE_LIMIT_MARK in str(exc).lower()

    of_write.is_rate_limited = automation_executor.is_rate_limited = sniff


def _refused_job_not_deferred() -> None:
    import automation_executor

    automation_executor.proxy_refused = lambda e: False


def _composer_send_deferred() -> None:
    import run_decide

    run_decide.PROXY_DEFER_KINDS = run_decide.PROXY_DEFER_KINDS | {"scheduled_send"}


def _mass_refused_run_left_running() -> None:
    from automations import send_mass_message

    async def keep(_mass_run_id: int, _e: BaseException) -> None:
        return None

    send_mass_message._close_unsent_run = keep


def register(Fault) -> dict:
    return {
        "send-once-retries-after-accept": Fault(_retries_after_accept, (ONCE, ECHO_5XX)),
        "rate-limit-text-sniff": Fault(_rate_limit_text_sniff, (ONCE, ECHO_5XX)),
        "refused-job-not-deferred": Fault(_refused_job_not_deferred, (REFUSED_DEFERRED, REFUSED_TERMINAL)),
        "composer-send-deferred": Fault(_composer_send_deferred, (REFUSED_DM_PLAIN,)),
        "mass-refused-run-left-running": Fault(_mass_refused_run_left_running, (REFUSED_RUN_CLOSED,)),
    }
