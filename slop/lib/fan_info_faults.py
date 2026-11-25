from __future__ import annotations

PIN = ("fan-info sweep: a language an operator pinned (language_source='manual') is never overwritten, though "
       "gen_info detected another one past the evidence floor")
KEEP = ("fan-info sweep: a stored nickname / short_bio / bullet_points / original_name is kept when the extract "
        "returns it empty")
OWN = ("fan-info sweep: facts and profile land only on their own fan (each fan's occupation / hobbies / bio carry "
       "his own marker; a non-manual fan gets his own detected language, source 'ai')")
COUNTS = ("fan-info sweep: one run per Creator, every candidate processed once (one model call per seeded fan, "
          "none for another), run stats = rows written, no failed / capped / deferred, no 5xx")


def _plan():
    from automations import gen_info_plan
    return gen_info_plan


def _manual_overwritten() -> None:
    p = _plan()
    if not hasattr(p, "MANUAL_LANGUAGE_SOURCES"):
        raise SystemExit("slop: gen-info-manual-language-overwritten: gen_info_plan.MANUAL_LANGUAGE_SOURCES is gone")
    p.MANUAL_LANGUAGE_SOURCES = ()


def _facts_cross_fan() -> None:
    import dataclasses

    p = _plan()
    real = getattr(p, "plan_persist", None)
    if real is None:
        raise SystemExit("slop: gen-info-facts-cross-fan: gen_info_plan.plan_persist is gone")
    prev: dict = {}

    def broken(*a, **kw):
        plan = real(*a, **kw)
        if not dataclasses.is_dataclass(plan) or not hasattr(plan, "facts"):
            raise SystemExit("slop: gen-info-facts-cross-fan: PersistPlan is no dataclass with `facts`")
        # one event loop: no lock needed
        last, prev["facts"] = prev.get("facts"), plan.facts
        return plan if last is None else dataclasses.replace(plan, facts=last)

    p.plan_persist = broken


def register(Fault) -> dict:
    return {
        "gen-info-manual-language-overwritten": Fault(_manual_overwritten, (PIN,)),
        "gen-info-facts-cross-fan": Fault(_facts_cross_fan, (OWN,)),
    }
