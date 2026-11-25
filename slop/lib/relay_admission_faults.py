from __future__ import annotations

C_TAP_P95 = "taps during the background flood meet the per-kind and overall p95 budget"
C_NO_THREAD_WAIT = "every lane-stats sample during the flood: threads_waiting_background == 0 (fleet and per Creator)"
C_BG_CAP = "bg_in_flight_peak stays within the background lane cap for every Creator"
C_TAPS = "every tap answered 200 in both legs (chatters x Creators x 3 each), users/me answers the asked Creator"
C_PROBE = "a user read of a held background list_chats key answers within the probe budget"
C_POOL = ("relay DB connections out stay within its pool's bound (pool_size + max spill, bounded) and relay "
          "threads under the scenario's THREADS_MAX, every 1 s sample ramp to drain")


def _pool_spills_unbounded() -> None:
    import db.engine  # noqa: F401 — the package re-exports `engine` over the module name
    import sys

    sys.modules["db.engine"].engine.sync_engine.pool._max_overflow = -1


def _admission_in_thread() -> None:
    import contextlib

    import server

    server._bg_admission = lambda *a, **k: contextlib.nullcontext()


def _coalesce_ignores_priority() -> None:
    import relay_coalesce

    relay_coalesce.priority_class = lambda: "user"


def register(Fault) -> dict:
    return {
        # Taps slow to ~10 s under it (measured); they pass the 30 s client timeout only on a loaded host, so C_TAPS / no-5xx are not targets.
        "admission-in-thread": Fault(_admission_in_thread, (C_TAP_P95, C_NO_THREAD_WAIT)),
        "coalesce-ignores-priority": Fault(_coalesce_ignores_priority, (C_PROBE,)),
        # Needs CHATTERLY_DB_SPILL_AFTER_S=0.05 at --scale=medium --users=30: at 2 s users 30/100 never spill, and 200 uncapped hits the gate's thread guard first (INFRA).
        "pool-spills-unbounded": Fault(_pool_spills_unbounded, (C_POOL,)),
    }
