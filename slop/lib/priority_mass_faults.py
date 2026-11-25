from __future__ import annotations

FROZEN = "frozen recipients == oracle (OF lists minus exclusions, first 5000 by fan id), every run"
ONCE = "each fan got at most one message per Creator (OF's record)"
ROWS = ("sent rows == OF sends, by fan: each sent row names an OF message to its fan, every fan OF "
        "got one from has a sent or unknown row, and carries its run's price")
CRASH = "the send in flight at the SIGKILL: its claimed row turns unknown and the fan is never sent again"
SETTLED = "the uncancelled runs finish done after the crash, no row left pending or claimed"
CANCEL = "cancel: every pending fan turns skipped, at most 1 send lands after it"
REFUSE = "a Sensitive word (added, imported) is refused 4xx and leaves no run row"
REPEAT = "the same message to the same Creator again inside 120 s is refused 409, no second row"
RESUME = "resume: a live run keeps one leg queued (never two); a cancelled run is 409"
LEG_SCAN = ("a run created clean stops at its first leg (error, banned_words) once a Sensitive word its text "
            "holds across odd whitespace is listed before that leg; OF gets nothing from it")
UI_CREATOR = ("UI: Smart Messages' OF mass and Message online fans composers open on the column's picked "
              "Creator ('Post as'; the OF one's Broadcast sends as it), not the first one")
UI_SEED = ("UI: the composer pre-ticks the Creator's OF MASSDMEXCLUDE list in Exclude; the POST and its run row "
           "exclude it and none of its fans is frozen or got an OF send")


def _claimed_row_resent_after_crash() -> None:
    # a crash claim returns to pending instead of unknown: OF may already have taken the send
    from sqlalchemy import update

    from automations import priority_mass as pm
    from db.engine import get_session
    from db.models import PriorityMassRecipient

    real = pm._leg

    async def _leg(run):
        async with get_session() as s:
            await s.execute(update(PriorityMassRecipient).where(
                PriorityMassRecipient.run_id == run.id, PriorityMassRecipient.status == pm.CLAIMED,
            ).values(status=pm.PENDING, reason="requeued"))
        return await real(run)

    pm._leg = _leg


def _cancel_keeps_pending() -> None:
    from fastapi import HTTPException
    from fastapi.routing import APIRoute

    import priority_mass_api as api
    import server
    from automations import priority_mass as pm

    async def cancel_run(run_id: int) -> dict:
        row = await api._get_run(run_id)
        if not await pm._set_status(row.id, pm.CANCELLED):
            raise HTTPException(409, f"the run is {row.status}")
        return (await api._public([await api._get_run(run_id)]))[0]

    path = "/admin/priority-mass/runs/{run_id}/cancel"
    routes = server.app.router.routes
    hit = [i for i, r in enumerate(routes) if isinstance(r, APIRoute) and r.path == path]
    assert len(hit) == 1, f"{path}: {len(hit)} routes (the fault would patch nothing)"
    old = routes[hit[0]]
    routes[hit[0]] = APIRoute(path, cancel_run, methods=sorted(old.methods), dependencies=old.dependencies)


def _sensitive_word_ignored() -> None:
    import priority_mass_api as api

    async def _sensitive_words(account_id: str) -> list[str]:
        return []

    api._sensitive_words = _sensitive_words


def _leg_exact_scan_only() -> None:
    from automations import priority_mass as pm

    pm.sensitive_hits = lambda text, words: []


def register(Fault) -> dict:
    return {
        "pm-claimed-row-resent-after-crash": Fault(_claimed_row_resent_after_crash, (ONCE, CRASH)),
        "pm-cancel-keeps-pending": Fault(_cancel_keeps_pending, (CANCEL,)),
        "pm-sensitive-word-ignored": Fault(_sensitive_word_ignored, (REFUSE,)),
        "pm-leg-exact-scan-only": Fault(_leg_exact_scan_only, (LEG_SCAN,)),
        "sm-mass-composer-first-creator": Fault(None, (UI_CREATOR,), browser=(
            (r"forcedAccountId:(?:\s|\\n)*accountId \?\? undefined", "forcedAccountId: undefined"),
        )),
        "pm-ui-no-massdm-seed": Fault(None, (UI_SEED,), browser=(
            (r"if \(!accountId \|\| !lists \|\| isFetching\) return;", "return;"),
            (r"disabled: send\.isPending \|\| !seeded", "disabled: send.isPending"),
        )),
    }
