"""The pump supervisor's break-it-once faults (scenarios/2026-10-25-session-health-otp.py): lib/faults.py
merges `register(Fault)` into FAULTS. Each patches `service/pump_reconcile` (`reconcile`, the pure pass
server.py's `_reconcile_pumps` performs, or `restart_backoff`, the Restart's delay) inside the relay. PROBE_RESTART lives here and the scenario
imports it, so the target can never name a check that does not exist. WS_PARKED (the scenario's WS pump
check) and the window it names live here for the same reason; lib/faults.py's otp-state-not-session-dead
still spells that name out.
"""
from __future__ import annotations

PROBE_RESTART = ("probe recovery: a 2FA Creator OnlyFans lets back in without a re-capture is unflagged by "
                 "the recovery probe, and the next supervisor pass restarts its exited pump (running, socket "
                 "reconnected)")
WS_WINDOW_S = 20  # flip -> end of phase B, at least: the old reconnect loop's 0, 1, 3, 7, 15 s
WS_PARKED = (f"the WS pump met the 2FA demand once and parked: per 2FA Creator at most 2 /users/me over "
             f">= {WS_WINDOW_S} s (the pump's reconnect, the probe's), no reconnect, the pump exited and "
             "supervisor passes left it parked")
PUMP_STOP = ("supervisor Stop: a running pump whose Creator lost its session is stopped by the next "
             "supervisor pass (no pump left) and its OF socket closed")
BACKOFF_WINDOW_S = 25  # Start, the at-once restart, the 15 s one; the 30 s one falls outside
BACKOFF_WANT_S = [0.0, 15.0]  # the restarts' delays after each exit: 0, then BACKOFF_BASE_S
BACKOFF_SLACK_S = 2.0         # 1 s passes plus a loaded relay
PUMP_BACKOFF = (f"a crash-looping pump (exits without parking) is restarted with backoff: over "
                f"{BACKOFF_WINDOW_S} s of 1 s supervisor passes, exactly 2 restarts, each "
                f"{BACKOFF_WANT_S} s (+ <= {BACKOFF_SLACK_S:.0f} s) after the last exit")


def _reconcile_never_restarts() -> None:
    """A pass that drops every Restart: an exited pump whose account is eligible again stays dead.
    Only the recovery probe leaves that restart to the supervisor (a re-capture restarts its own)."""
    import pump_reconcile
    real = pump_reconcile.reconcile

    def reconcile(*a, **k):
        return [x for x in real(*a, **k) if not isinstance(x, pump_reconcile.Restart)]

    pump_reconcile.reconcile = reconcile


def _reconcile_ignores_parked() -> None:
    """A pass blind to the dead-session flag: a parked account's exited pump is restarted every pass,
    so it reconnects into OF's 2FA demand again and again."""
    import pump_reconcile
    real = pump_reconcile.reconcile

    def reconcile(with_session, deactivated, parked, pump_done):
        return real(with_session, deactivated, (), pump_done)

    pump_reconcile.reconcile = reconcile


def _reconcile_never_stops() -> None:
    """A pass that drops every Stop: a running pump whose Creator lost its session keeps its socket."""
    import pump_reconcile
    real = pump_reconcile.reconcile

    def reconcile(*a, **k):
        return [x for x in real(*a, **k) if not isinstance(x, pump_reconcile.Stop)]

    pump_reconcile.reconcile = reconcile


def _supervisor_ignores_backoff() -> None:
    """The Restart without its backoff: every pass restarts an exited pump at once (the old
    supervisor), so a pump that exits without parking is restarted every pass, forever."""
    import pump_reconcile
    real = pump_reconcile.restart_backoff

    def restart_backoff(attempts, ran_s):
        return real(attempts, ran_s)[0], 0.0

    pump_reconcile.restart_backoff = restart_backoff


def register(Fault) -> dict:
    return {
        # slop/run session-health-otp --break --fault=reconcile-never-restarts
        "reconcile-never-restarts": Fault(_reconcile_never_restarts, (PROBE_RESTART,)),
        # slop/run session-health-otp --break --fault=reconcile-ignores-parked
        "reconcile-ignores-parked": Fault(_reconcile_ignores_parked, (WS_PARKED,)),
        # slop/run session-health-otp --break --fault=reconcile-never-stops
        "reconcile-never-stops": Fault(_reconcile_never_stops, (PUMP_STOP,)),
        # slop/run session-health-otp --break --fault=supervisor-ignores-backoff
        "supervisor-ignores-backoff": Fault(_supervisor_ignores_backoff, (PUMP_BACKOFF,)),
    }
