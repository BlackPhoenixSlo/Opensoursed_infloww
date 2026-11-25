from __future__ import annotations

JUMP_WAIT = "house funnel: after a `next` jump the reply-wait follows the sent step's intervals"


def _house_funnel_jump_waits_prev_step() -> None:
    from automations import funnel_decide as fd

    def sent_step_intervals(e, steps):
        return fd.step_intervals(steps, max(e.current_step - 1, 0))

    fd.sent_step_intervals = sent_step_intervals


def register(Fault) -> dict:
    return {
        "house-funnel-jump-waits-prev-step": Fault(_house_funnel_jump_waits_prev_step, (JUMP_WAIT,)),
    }
