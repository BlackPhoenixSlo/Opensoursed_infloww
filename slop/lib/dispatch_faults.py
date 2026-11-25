from __future__ import annotations

ONE = ("dispatch plan: one supervisor pass, with a wake landing while its runs are in flight, "
       "makes one job per Creator's send_followup (two rules or one), spawns one run per due "
       "(Creator, kind) and runs it once; a deactivated Creator's job waits, unspawned")
CADENCE = ("dispatch plan: across passes inside the rules' interval each rule makes exactly one job "
           "(a second rule of the kind is held while the first one's job is open, then fires once; "
           "the cadence anchors on each rule's own last job), a deactivated Creator's at most one")


def _two_jobs_per_kind() -> None:
    import automation_executor as ax

    async def never_busy(s, rule, now):
        return None

    ax._pair_busy = never_busy


def _spawns_in_flight_pairs() -> None:
    import dispatch_plan as dp

    real = dp.plan_dispatch

    def stacking(pairs, inflight, last_served, rank, bulk_kinds):
        return real(pairs, set(), last_served, rank, bulk_kinds)

    dp.plan_dispatch = stacking


def _ignores_cadence() -> None:
    import dispatch_plan as dp

    dp.interval_due = lambda every, last_fired, now, poked: True


def register(Fault) -> dict:
    return {
        "dispatch-plan-two-jobs-per-kind": Fault(_two_jobs_per_kind, (ONE,)),
        "dispatch-plan-spawns-in-flight-pairs": Fault(_spawns_in_flight_pairs, (ONE,)),
        "dispatch-plan-ignores-cadence": Fault(_ignores_cadence, (CADENCE,)),
    }
