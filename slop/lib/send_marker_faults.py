from __future__ import annotations

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

    rmf._send_step = _send_step


def _funnel_noid_not_counted() -> None:
    rmf = _rmf()
    real = rmf._send_step

    async def _send_step(*a, attempt, **kw):
        try:
            return await real(*a, attempt=attempt, **kw)
        finally:
            attempt.returned = 0

    rmf._send_step = _send_step


def _funnel_marker_sets_status() -> None:
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
    from datetime import datetime

    from db.models import FunnelState
    st = _store()
    real = st.mark

    async def mark(model, keys, ctx):
        return datetime.utcnow() if model is FunnelState else await real(model, keys, ctx)

    st.mark = mark


def _funnel_settle_skips_lookup() -> None:
    st = _store()
    real = st.landed

    async def landed(account_id, fan_id, since, kind, **tags) -> bool:
        return False if kind == "reply_mass_funnel" else await real(account_id, fan_id, since, kind, **tags)

    st.landed = landed


def _followup_sending_marker_ignored() -> None:
    from automations import send_followup_decide as sfd

    sfd.Entry.marked = property(lambda self: False)


def register(Fault) -> dict:
    return {
        "funnel-partial-requeued": Fault(_funnel_partial_requeued, (FUNNEL_ONCE, FUNNEL_PARTIAL, FUNNEL_PARTIAL_NOID)),
        "funnel-noid-not-counted": Fault(_funnel_noid_not_counted, (FUNNEL_ONCE, FUNNEL_PARTIAL_NOID)),
        "funnel-marker-sets-status": Fault(_funnel_marker_sets_status, (FUNNEL_PARKED_QUIET,)),
        "funnel-sending-marker-ignored": Fault(_funnel_sending_marker_ignored, (
            FUNNEL_ONCE, FUNNEL_MARKED, FUNNEL_SETTLED, FUNNEL_RETRY, FUNNEL_PARTIAL_NOID)),
        "funnel-settle-skips-lookup": Fault(_funnel_settle_skips_lookup, (FUNNEL_SETTLED,)),
        "followup-sending-marker-ignored": Fault(_followup_sending_marker_ignored, (
            DRIP_ONCE, DRIP_MARKED, DRIP_RETRY)),
    }
