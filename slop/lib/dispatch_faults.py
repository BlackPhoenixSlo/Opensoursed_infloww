"""The automation dispatch plan's break-it-once faults (service/dispatch_plan.py, checked by
scenarios/2026-10-30-dispatch-plan.py, where follow-up rules fire through
real supervisor passes): lib/faults.py merges `register(Fault)` into FAULTS. The check names
live here and the scenario imports them, so a target can never name a check that does not
exist.

Each patches one function in the relay process: a `dispatch_plan` helper (automation_executor
calls them through the module, so the patch is what the real supervisor pass runs) or, for the
busy gate, which stays a DB read, the shell's `_pair_busy`. Everything else is as shipped.
"""
from __future__ import annotations

ONE = ("dispatch plan: one supervisor pass, with a wake landing while its runs are in flight, "
       "makes one job per Creator's send_followup (two rules or one), spawns one run per due "
       "(Creator, kind) and runs it once; a deactivated Creator's job waits, unspawned")
CADENCE = ("dispatch plan: across passes inside the rules' interval each rule makes exactly one job "
           "(a second rule of the kind is held while the first one's job is open, then fires once; "
           "the cadence anchors on each rule's own last job), a deactivated Creator's at most one")


def _two_jobs_per_kind() -> None:
    """The one-job-per-(Creator, kind) gate never sees a due pending/running job of the pair:
    every due rule enqueues, so a Creator with two rules of a kind gets two jobs in one pass
    (the bug class of a dropped dedupe). That gate is a DB read in the shell, not a pure
    helper, so this patches the shell's read (`automation_executor._pair_busy`, from here,
    never inside service/). Each rule still fires once (a second rule earlier than it
    should, not twice), so only ONE can see it."""
    import automation_executor as ax

    async def never_busy(s, rule, now):
        return None

    ax._pair_busy = never_busy


def _spawns_in_flight_pairs() -> None:
    """plan_dispatch ignores the in-flight set: a pass that lands while an earlier pass's runs
    are still queued for a run slot spawns a second run of the same (Creator, kind) (the bug
    class of a dropped no-stacking guard; run_once's own lock then turns it away, so no extra
    run row: only the pass's spawn count shows it). Jobs are untouched: only ONE can see it."""
    import dispatch_plan as dp

    real = dp.plan_dispatch

    def stacking(pairs, inflight, last_served, rank, bulk_kinds):
        return real(pairs, set(), last_served, rank, bulk_kinds)

    dp.plan_dispatch = stacking


def _ignores_cadence() -> None:
    """interval_due never looks at the rule's last job (the cadence anchor): every interval
    rule is always due, so each pass with no due job of the pair pending enqueues again (the
    bug class of a lost anchor). The first pass is unchanged (nothing fired yet) and the
    wake finds the pair busy, so only CADENCE can see it."""
    import dispatch_plan as dp

    dp.interval_due = lambda every, last_fired, now, poked: True


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-dispatch-plan --break (the scenario's FAULT)
        "dispatch-plan-two-jobs-per-kind": Fault(_two_jobs_per_kind, (ONE,)),
        # at --scale=medium (10 Creators, 4 run slots: the wake finds runs still queued, their
        # jobs still pending; at small every run claims its job at once: NOT CAUGHT there)
        "dispatch-plan-spawns-in-flight-pairs": Fault(_spawns_in_flight_pairs, (ONE,)),
        "dispatch-plan-ignores-cadence": Fault(_ignores_cadence, (CADENCE,)),
    }
