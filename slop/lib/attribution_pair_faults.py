from __future__ import annotations

PH_ONCE = ("every mass placeholder adopted exactly once by its own OF echo (a 2-day-old same-caption stub adopts "
           "nothing), no duplicate bubble, none left past the echo")


def _ignores_window() -> None:
    import attribution

    attribution._MAX_ADOPT_SECONDS = 10 * 365 * 86400.0


def register(Fault) -> dict:
    return {
        "placeholder-pair-ignores-window": Fault(_ignores_window, (PH_ONCE,)),
    }
