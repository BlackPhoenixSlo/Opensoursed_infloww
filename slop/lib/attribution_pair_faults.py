"""Mass placeholder pairing's break-it-once fault (service/attribution_pair.py
`pair_placeholders`, fed by `attribution.adopt_thread_placeholders`): lib/faults.py merges
`register(Fault)` into FAULTS. The check name lives here and
scenarios/2026-10-31-mass-placeholder-echo.py imports it, so a target can never name a check
that does not exist.
"""
from __future__ import annotations

PH_ONCE = ("every mass placeholder adopted exactly once by its own OF echo (a 2-day-old same-caption stub adopts "
           "nothing), no duplicate bubble, none left past the echo")


def _ignores_window() -> None:
    """The pre-bound lane: placeholder pairing distance-ORDERED but not distance-LIMITED.
    `attribution._MAX_ADOPT_SECONDS` (read at call time both by the loader's per-stub read
    ranges and as `pair_placeholders`' `max_s`) becomes 10 years, so a stub whose own echo
    never came claims the same caption sent days later, stamps it with its old run and is
    deleted. Nearest-first still holds, so a fresh stub keeps its own echo; only a send with
    no fresh stub of its own is mis-adopted."""
    import attribution

    attribution._MAX_ADOPT_SECONDS = 10 * 365 * 86400.0


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-31-mass-placeholder-echo --break --no-ui
        "placeholder-pair-ignores-window": Fault(_ignores_window, (PH_ONCE,)),
    }
