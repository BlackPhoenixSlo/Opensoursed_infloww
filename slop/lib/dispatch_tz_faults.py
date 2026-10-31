"""A rule's bad `tz_offset_minutes` in the dispatch plan (service/dispatch_plan.py
`parse_trigger`), checked by scenarios/2026-10-30-followup-drip.py: seed/followup_drip.py
writes one rule whose stored offset is "x", and one real supervisor pass must skip it while
every other rule fires. lib/faults.py merges `register(Fault)` into FAULTS. The check name
lives here and the scenario imports it, so the target can never name a check that does not
exist.
"""
from __future__ import annotations

BAD_TZ = ("dispatch plan: a rule with a bad tz_offset_minutes is skipped; every other rule still "
          "fires on time (one supervisor pass makes each good rule's job; its next_due_at was due "
          "before the pass and is the next slot after it)")


def _bad_tz_aborts_pass() -> None:
    """Restores the pre-fix raise for a non-numeric stored offset (the seeded "x"): the
    materializer's handling of a clock rule's bad offset (`dispatch_plan._bad_tz`, log once
    and skip) becomes `int(raw)`, whose return is unused, so "x" raises ValueError out of
    `_materialize_due_rules`; the supervisor pass logs `automation_rule_materialize_failed`
    and no rule makes a job (the session rolls back). An out-of-range number (9999) still
    converts, so such a rule stays skipped, not fired as pre-fix: only the raise comes back.
    `parse_trigger` looks `_bad_tz` up in its module at call time, so the executor's pass runs
    the patch. The rules API reads `trigger_of`, which never calls it, so its reads are as
    shipped and only BAD_TZ can see it. (Patching `tz_offset` would also reach that read: a 500
    on the list route, noise.)"""
    import dispatch_plan as dp

    dp._bad_tz = lambda raw: int(raw)   # the return is unused: only the raise matters


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-followup-drip --break --fault=dispatch-bad-tz-aborts-pass
        "dispatch-bad-tz-aborts-pass": Fault(_bad_tz_aborts_pass, (BAD_TZ,)),
    }
