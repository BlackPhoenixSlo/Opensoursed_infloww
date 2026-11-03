"""Send once for the drip senders (service/automations/send_marker_decide.py: a funnel /
follow-up step killed mid-send is never auto-resent, it is listed "may not have sent" and the
user retries it): the KILL phases' check names and their break-it-once faults. lib/faults.py
merges `register(Fault)` into FAULTS. Each fault patches a name the product looks up at call
time inside the throwaway relay (reply_mass_funnel's `_send_step`, send_marker_store's `mark` /
`landed`, send_followup_decide.Entry), so every shell around it is the product's.

  funnel-partial-requeued        scenarios/2026-10-30-house-funnel-walk
  funnel-noid-not-counted        scenarios/2026-10-30-house-funnel-walk
  funnel-marker-sets-status      scenarios/2026-10-30-house-funnel-walk
  funnel-sending-marker-ignored  scenarios/2026-10-30-house-funnel-walk
  funnel-settle-skips-lookup     scenarios/2026-10-30-house-funnel-walk
  followup-sending-marker-ignored  scenarios/2026-10-30-followup-drip

The check names live here and both scenarios import them, so a target can never name a
check that does not exist. FUNNEL_ONCE is a target of both partial faults too: the requeued
step re-sends the PPV, which is the double send ONCE exists for.
"""
from __future__ import annotations

# ── house funnel KILL phase (scenarios/2026-10-30-house-funnel-walk.py) ──
FUNNEL_ONCE = ("house funnel kill: OF took each KILL fan's text at most once up to the Retry (PPV never "
               "twice); after it only the retried fan's hung text twice")
FUNNEL_MARKED = ("house funnel kill: each hung fan is listed may-not-have-sent (UNCONFIRMED) with its step "
                 "after the restart")
FUNNEL_SETTLED = ("house funnel kill: a step killed after its PPV bubble landed is settled by the first tick "
                  "(advanced at the mark time, not listed, one PPV)")
FUNNEL_RETRY = ("house funnel kill: each Retry answers retried and the next tick sends the hung step once "
                "more, the walk advanced")
FUNNEL_PARTIAL = ("house funnel kill: bubble 1 refused 400 after the PPV bubble landed: one PPV over every "
                  "tick, the walk advanced")
FUNNEL_PARTIAL_NOID = ("house funnel kill: PPV bubble taken without an id, bubble 1 refused 400: one PPV, "
                       "left unconfirmed and listed")
FUNNEL_PARKED_QUIET = ("house funnel kill: the welcome chatter answers no parked KILL fan after the kill, but "
                       "answers each control fan")

# ── follow-up drip KILL phase (scenarios/2026-10-30-followup-drip.py) ──
DRIP_ONCE = ("follow-up kill: OF took each KILL fan's nudge at most once up to the Retry; after it "
             "exactly twice")
DRIP_MARKED = "follow-up kill: each hung fan is listed may-not-have-sent (UNCONFIRMED) with step 1 after the restart"
DRIP_RETRY = ("follow-up kill: each Retry answers retried and the next tick nudges once more, "
              "step 1 recorded")


def _rmf():
    from automations import reply_mass_funnel
    return reply_mass_funnel


def _store():
    from automations import send_marker_store
    return send_marker_store


def _funnel_partial_requeued() -> None:
    """The pre-fix requeue: a step that raised after a bubble landed reports nothing
    landed (the attempt's `sent` / `returned` zeroed on every raise but a lost slot),
    so the marker is cleared and the step retried when due."""
    import run_slot
    rmf = _rmf()
    real = rmf._send_step

    async def _send_step(*a, attempt, **kw):
        try:
            return await real(*a, attempt=attempt, **kw)
        except run_slot.SlotLost:
            raise
        except Exception:
            attempt.sent = attempt.returned = 0
            raise

    rmf._send_step = _send_step   # run() looks it up per call


def _funnel_noid_not_counted() -> None:
    """An id-less OF answer is not counted (the attempt's `returned` zeroed): a step
    whose only landing came back without an id reads as surely not sent."""
    rmf = _rmf()
    real = rmf._send_step

    async def _send_step(*a, attempt, **kw):
        try:
            return await real(*a, attempt=attempt, **kw)
        finally:
            attempt.returned = 0

    rmf._send_step = _send_step


def _funnel_marker_sets_status() -> None:
    """The funnel's mark also writes status 'sending' (the Retry writes 'pending'
    back): every pending reader (welcome chatter's mid-funnel guard) loses the fan."""
    from sqlalchemy import update

    from db.engine import get_session
    from db.models import FunnelState
    st = _store()
    real = st.mark

    async def mark(model, keys, ctx):
        at = await real(model, keys, ctx)
        if model is FunnelState:
            async with get_session() as s:
                await s.execute(update(FunnelState).where(
                    *(getattr(FunnelState, k) == v for k, v in keys.items())).values(status="sending"))
        return at

    st.mark = mark


def _funnel_sending_marker_ignored() -> None:
    """The funnel's mark writes nothing (the attempt still counts as entered): a killed
    step leaves no marker, so the next tick sends it again."""
    from datetime import datetime

    from db.models import FunnelState
    st = _store()
    real = st.mark

    async def mark(model, keys, ctx):
        return datetime.utcnow() if model is FunnelState else await real(model, keys, ctx)

    st.mark = mark


def _funnel_settle_skips_lookup() -> None:
    """The funnel settle never finds a landed step (every lookup a miss)."""
    st = _store()
    real = st.landed

    async def landed(account_id, fan_id, since, kind, **tags) -> bool:
        return False if kind == "reply_mass_funnel" else await real(account_id, fan_id, since, kind, **tags)

    st.landed = landed


def _followup_sending_marker_ignored() -> None:
    """decide() never sees a marker (`Entry.marked` always False): a killed nudge is
    sent again by the next tick, whose Sent save clears the marker."""
    from automations import send_followup_decide as sfd

    sfd.Entry.marked = property(lambda self: False)


def register(Fault) -> dict:
    return {
        "funnel-partial-requeued": Fault(_funnel_partial_requeued, (FUNNEL_ONCE, FUNNEL_PARTIAL, FUNNEL_PARTIAL_NOID)),
        "funnel-noid-not-counted": Fault(_funnel_noid_not_counted, (FUNNEL_ONCE, FUNNEL_PARTIAL_NOID)),
        "funnel-marker-sets-status": Fault(_funnel_marker_sets_status, (FUNNEL_PARKED_QUIET,)),
        "funnel-sending-marker-ignored": Fault(_funnel_sending_marker_ignored, (   # no mark: the
            FUNNEL_ONCE, FUNNEL_MARKED, FUNNEL_SETTLED, FUNNEL_RETRY, FUNNEL_PARTIAL_NOID)),   # unconfirm matches none
        "funnel-settle-skips-lookup": Fault(_funnel_settle_skips_lookup, (FUNNEL_SETTLED,)),
        "followup-sending-marker-ignored": Fault(_followup_sending_marker_ignored, (
            DRIP_ONCE, DRIP_MARKED, DRIP_RETRY)),
    }
