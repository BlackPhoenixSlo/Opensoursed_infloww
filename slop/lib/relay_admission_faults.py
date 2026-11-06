"""The relay-admission flow's break-it-once faults (scenarios/2026-11-05-relay-admission.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.

  admission-in-thread         server._bg_admission a no-op: a background read takes its worker thread first
                              and waits for its Creator's background lane there (before 2026-11-05)
  coalesce-ignores-priority   relay_coalesce.priority_class always "user": a user read joins a background-led
                              flight (and relay_cache's background lock), inheriting its lane wait
"""
from __future__ import annotations

BG_CAP = 2  # service/server.py _ACCOUNT_LANE_BACKGROUND (default)
# Catches blocking (a fault puts tap p95 at 10-30 s), not jitter: on the shared machine (gate: up to 6
# runs) the no-fault flood p95 spread over runs was 85-140 ms all, 120-189 ms send (measured: 7b84, 09ae,
# dd50, f09a), so 1.25x + 50 ms flipped on host noise.
P95_RATIO, P95_SLACK_MS = 2.0, 100
PROBE_HOLD_S, PROBE_MAX_S = 3.0, 1.0

C_TAP_P95 = (f"taps during the background flood: p95 <= {P95_RATIO} x the no-flood p95 + {P95_SLACK_MS} ms, "
             "per tap kind (open fan, send, users/me) and overall")
C_NO_THREAD_WAIT = "every lane-stats sample during the flood: threads_waiting_background == 0 (fleet and per Creator)"
C_BG_CAP = f"bg_in_flight_peak <= {BG_CAP} for every Creator (the background lane cap holds)"
C_TAPS = "every tap answered 200 in both legs (chatters x Creators x 3 each), users/me answers the asked Creator"
C_PROBE = (f"a user read of the same list_chats key as an in-flight background read (OF holds that one "
           f"{PROBE_HOLD_S:.0f} s) answers in < {PROBE_MAX_S:.0f} s, every probe")


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
    }
