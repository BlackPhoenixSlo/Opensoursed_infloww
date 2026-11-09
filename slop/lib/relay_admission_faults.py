"""The relay-admission flow's break-it-once faults (scenarios/2026-11-05-relay-admission.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.

  admission-in-thread         server._bg_admission a no-op: a background read takes its worker thread first
                              and waits for its Creator's background lane there (before 2026-11-05)
  coalesce-ignores-priority   relay_coalesce.priority_class always "user": a user read joins a background-led
                              flight (and relay_cache's background lock), inheriting its lane wait
  pool-spills-unbounded       db/engine.py's spill cap off (max_overflow -1): one connection + thread per
                              checkout that waited SPILL_AFTER_S (before 2026-11-09)
"""
from __future__ import annotations

C_TAP_P95 = "taps during the background flood meet the per-kind and overall p95 budget"
C_NO_THREAD_WAIT = "every lane-stats sample during the flood: threads_waiting_background == 0 (fleet and per Creator)"
C_BG_CAP = "bg_in_flight_peak stays within the background lane cap for every Creator"
C_TAPS = "every tap answered 200 in both legs (chatters x Creators x 3 each), users/me answers the asked Creator"
C_PROBE = "a user read of a held background list_chats key answers within the probe budget"
C_POOL = ("relay DB connections out stay within its pool's bound (pool_size + max spill, bounded) and relay "
          "threads under the scenario's THREADS_MAX, every 1 s sample ramp to drain")


def _pool_spills_unbounded() -> None:
    """The spill cap reverted (bug class: the DB pool's overflow unbounded again, before 2026-11-09): every
    checkout that waits SPILL_AFTER_S opens one more connection, one aiosqlite thread each."""
    import db.engine  # noqa: F401 — the package re-exports `engine` over the module name
    import sys

    sys.modules["db.engine"].engine.sync_engine.pool._max_overflow = -1


def _admission_in_thread() -> None:
    """Admission back in the worker thread (bug class: the loop-side wait dropped or bypassed): every
    background read takes a thread and blocks on its Creator's lane there, so a flood of them fills the
    default executor and a user tap's to_thread queues behind it."""
    import contextlib

    import server

    server._bg_admission = lambda *a, **k: contextlib.nullcontext()


def _coalesce_ignores_priority() -> None:
    """One flight class again (bug class: the coalesce / single-flight key loses the priority): a user read
    joins whatever background read of that key is in flight and waits for it."""
    import relay_coalesce

    relay_coalesce.priority_class = lambda: "user"


def register(Fault) -> dict:
    return {
        # slop/run relay-admission --break (the scenario's FAULT)
        # Taps slow to ~10 s under it (measured, 012c); they pass the 30 s client timeout only on a loaded
        # host (6df7, load 122), so C_TAPS / no-5xx are not targets.
        "admission-in-thread": Fault(_admission_in_thread, (C_TAP_P95, C_NO_THREAD_WAIT)),
        # slop/run relay-admission --break --fault=coalesce-ignores-priority
        "coalesce-ignores-priority": Fault(_coalesce_ignores_priority, (C_PROBE,)),
        # CHATTERLY_DB_SPILL_AFTER_S=0.05 slop/run relay-admission --scale=medium --users=30 --no-ui --break
        # --fault=pool-spills-unbounded (baseline with the same env): 50 ms spills make 30 users press the pool
        # (capped: dbPeak 32, 148 threads, a638; uncapped: 478, 971 threads, CAUGHT dd46). Users 30/100 never spill
        # at 2 s, and 200 uncapped hits the gate's 3000-thread guard first (INFRA, 3146 threads, 6750).
        "pool-spills-unbounded": Fault(_pool_spills_unbounded, (C_POOL,)),
    }
