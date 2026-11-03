"""Priority mass message's break-it-once faults (scenarios/2026-11-01-priority-mass-5k.py):
lib/faults.py merges `register(Fault)` into FAULTS. Each patches the product function whose
bug class it names, inside the throwaway relay. The check names live here and the scenario
imports them, so a target can never name a check that does not exist.
"""
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
UI_SEED = ("UI: the composer pre-ticks the Creator's OF MASSDMEXCLUDE list in Exclude; the POST and its run row "
           "exclude it and none of its fans is frozen or got an OF send")


def _claimed_row_resent_after_crash() -> None:
    """automations/priority_mass.py `_leg`: a claim left by a crash goes back to `pending` (a
    "requeue the interrupted" heal) instead of `unknown`, so the fan whose send OF may already
    have taken is sent again. Every other leg step is the product's."""
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
    """priority_mass_api.py `cancel_run` without its sweep: the run turns cancelled, its pending
    fans stay pending. The body mirrors the product's `cancel_run` lines 234-236 and 243, without
    its pending -> skipped UPDATE (237-241); swapped in on the app's router (FastAPI calls the
    route's endpoint, not the module attribute)."""
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
    """priority_mass_api.py `_sensitive_words`: the Agency's list never read (as if keyed by
    another scope), so the route's matcher finds nothing to refuse. The route's second reader of
    the same list (`load_banned_words`, whole-word `filter_banned`) still refuses the single
    words; the phrases with odd case / whitespace ("Cash\\napp", "Telegram   me") are what go
    through (measured: 2 of 4 refusal posts 200)."""
    import priority_mass_api as api

    async def _sensitive_words(account_id: str) -> list[str]:
        return []

    api._sensitive_words = _sensitive_words


def register(Fault) -> dict:
    return {
        # slop/run priority-mass-5k --break (the scenario's FAULT)
        "pm-claimed-row-resent-after-crash": Fault(_claimed_row_resent_after_crash, (ONCE, CRASH)),
        # slop/run priority-mass-5k --break --fault=pm-cancel-keeps-pending --baseline=...
        "pm-cancel-keeps-pending": Fault(_cancel_keeps_pending, (CANCEL,)),
        # slop/run priority-mass-5k --break --fault=pm-sensitive-word-ignored --baseline=...
        "pm-sensitive-word-ignored": Fault(_sensitive_word_ignored, (REFUSE,)),
        # slop/run priority-mass-5k --break --fault=pm-ui-no-massdm-seed --baseline=... (not --no-ui)
        # app/components/growth/PriorityMass.tsx as before the seed: its seedExclude effect returns before
        # dispatching and Send no longer waits for the seed (the fix reverted). Only the composer's chunk
        # holds `!lists || isFetching` / `!seeded` on the pages this scenario opens (FunnelLaunchPanel's
        # twin is in growth/auto-funnel's, Mass's composer reads `listsQ`).
        "pm-ui-no-massdm-seed": Fault(None, (UI_SEED,), browser=(
            (r"if \(!accountId \|\| !lists \|\| isFetching\) return;", "return;"),
            (r"disabled: send\.isPending \|\| !seeded", "disabled: send.isPending"),
        )),
    }
