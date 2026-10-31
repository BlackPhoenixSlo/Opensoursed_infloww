"""The house funnel's `next`-jump fault (F1): lib/faults.py merges `register(Fault)` into
FAULTS. It patches the pure `funnel_decide` inside the throwaway relay, so the bug lives
in the rules and every shell around them (reads, sends, saves) is the product's.

  house-funnel-jump-waits-prev-step   scenarios/2026-10-30-house-funnel-walk

Its check name lives here and the scenario imports it, so the target can never name a
check that does not exist (the walk's other checks: lib/funnel_faults.py).
"""
from __future__ import annotations

JUMP_WAIT = "house funnel: after a `next` jump the reply-wait follows the sent step's intervals"


def _house_funnel_jump_waits_prev_step() -> None:
    """The pre-F1 rule: a quiet check paces on step c - 1's `check_intervals_min`
    (the step BEFORE the one he is on) instead of the step last sent. Identical on a
    linear walk (the sent step is c - 1), so only a fan who jumped can show it."""
    from automations import funnel_decide as fd

    def sent_step_intervals(e, steps):
        return fd.step_intervals(steps, max(e.current_step - 1, 0))

    fd.sent_step_intervals = sent_step_intervals  # decide() looks it up per call


def register(Fault) -> dict:
    return {
        # slop/run house-funnel-walk --break --fault=house-funnel-jump-waits-prev-step
        "house-funnel-jump-waits-prev-step": Fault(_house_funnel_jump_waits_prev_step, (JUMP_WAIT,)),
    }
