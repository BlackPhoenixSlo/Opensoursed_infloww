"""The full chat sweep cadence's break-it-once faults (service/sweep_cadence.py, whose `tick`
looks `plan` up in its module): lib/faults.py merges `register(Fault)` into FAULTS. The check names
live here and scenarios/2026-11-07-chat-sweep-cadence.py imports them.
"""
from __future__ import annotations

ONE_OPEN = "at most one open full sweep per live Creator after every relay restart and cadence pass"
COLLAPSE = ("a seeded backlog of duplicate full sweeps collapses to its oldest job (the rest cancelled "
            "'duplicate full sweep'); fan_ids jobs untouched")
ANCHOR = ("a new full sweep only once the last one finished >= SWEEP_EVERY_S ago (none while one is recent, "
          "one once it is older); a deactivated or session-dead Creator gets none")


def _sweep_every_pass() -> None:
    """The pre-fix shape in the new loop: every pass enqueues a sweep for every live Creator,
    open job or recent sweep or not (the boot seed ran once per restart, with no dedupe).
    The collapse is unchanged, so only the open-count and cadence checks can see it."""
    import sweep_cadence as sc

    real = sc.plan

    def every_pass(live, open_jobs, swept_recently):
        live = list(live)
        p = real(live, {}, set())
        return sc.Plan(enqueue=p.enqueue, cancel=real(live, open_jobs, swept_recently).cancel)

    sc.plan = every_pass


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-07-chat-sweep-cadence --break (the scenario's FAULT)
        "sweep-enqueued-every-pass": Fault(_sweep_every_pass, (ONE_OPEN, ANCHOR)),
    }
