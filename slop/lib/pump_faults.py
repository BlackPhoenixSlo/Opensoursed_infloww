from __future__ import annotations

PROBE_RESTART = ("probe recovery: a 2FA Creator OnlyFans lets back in without a re-capture is unflagged by "
                 "the recovery probe, and the next supervisor pass restarts its exited pump (running, socket "
                 "reconnected)")
# 2FA Creator: OF ends the socket (a transient, 1 s), each /users/me answers 101: three retries on the doubling backoff, the 4th answer parks it.
WS_RETRY_GAPS_S = (2.0, 4.0, 8.0)
WS_RETRY_SLACK_S = 0.5
WS_EXIT_SLACK_S = 2.0
WS_ME_MAX = 2 + len(WS_RETRY_GAPS_S)
WS_WINDOW_S = 25
WS_PARKED = (f"the WS pump met the 2FA demand and parked: per 2FA Creator at most {WS_ME_MAX} /users/me over "
             f">= {WS_WINDOW_S} s (the pump's 1 + {len(WS_RETRY_GAPS_S)} retries, the probe's), all 400, no "
             f"reconnect, the pump exited within {WS_EXIT_SLACK_S:.0f} s of its last /users/me and supervisor "
             f"passes left it parked")
WS_RETRIES = (f"the WS pump retried the 2FA demand: per 2FA Creator, after its first /users/me (400), "
              f"{len(WS_RETRY_GAPS_S)} more, each >= "
              f"{', '.join(f'{g - WS_RETRY_SLACK_S:.1f}' for g in WS_RETRY_GAPS_S)} s after the last")
PUMP_STOP = ("supervisor Stop: a running pump whose Creator lost its session is stopped by the next "
             "supervisor pass (no pump left) and its OF socket closed")
BACKOFF_WINDOW_S = 25
BACKOFF_WANT_S = [0.0, 15.0]
BACKOFF_SLACK_S = 2.0
PUMP_BACKOFF = (f"a crash-looping pump (exits without parking) is restarted with backoff: over "
                f"{BACKOFF_WINDOW_S} s of 1 s supervisor passes, exactly 2 restarts, each "
                f"{BACKOFF_WANT_S} s (+ <= {BACKOFF_SLACK_S:.0f} s) after the last exit")


def _reconcile_never_restarts() -> None:
    import pump_reconcile
    real = pump_reconcile.reconcile

    def reconcile(*a, **k):
        return [x for x in real(*a, **k) if not isinstance(x, pump_reconcile.Restart)]

    pump_reconcile.reconcile = reconcile


def _reconcile_ignores_parked() -> None:
    import pump_reconcile
    real = pump_reconcile.reconcile

    def reconcile(with_session, deactivated, parked, pump_done):
        return real(with_session, deactivated, (), pump_done)

    pump_reconcile.reconcile = reconcile


def _reconcile_never_stops() -> None:
    import pump_reconcile
    real = pump_reconcile.reconcile

    def reconcile(*a, **k):
        return [x for x in real(*a, **k) if not isinstance(x, pump_reconcile.Stop)]

    pump_reconcile.reconcile = reconcile


def _supervisor_ignores_backoff() -> None:
    import pump_reconcile
    real = pump_reconcile.restart_backoff

    def restart_backoff(attempts, ran_s):
        return real(attempts, ran_s)[0], 0.0

    pump_reconcile.restart_backoff = restart_backoff


def register(Fault) -> dict:
    return {
        "reconcile-never-restarts": Fault(_reconcile_never_restarts, (PROBE_RESTART,)),
        "reconcile-ignores-parked": Fault(_reconcile_ignores_parked, (WS_PARKED,)),
        "reconcile-never-stops": Fault(_reconcile_never_stops, (PUMP_STOP,)),
        "supervisor-ignores-backoff": Fault(_supervisor_ignores_backoff, (PUMP_BACKOFF,)),
    }
