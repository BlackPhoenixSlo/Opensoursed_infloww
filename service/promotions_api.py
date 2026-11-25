from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

import automation_executor as ax
import link_metrics
import notifications_api
from api_errors import raise_if_free_page_denied
from auth import assert_account_owned
from automation_rules_api import ensure_kind_rule
from db.engine import get_session
from db.models import PromoCampaign, PromoCreateReservation, PromoKeepState
from isotime import iso_plain
import of_pacing
import promo_create_guard
import runtime_switches
from of_mirror import delete_mirrored, merge_mirrors
from of_promos import fetch_of_promos, promo_type_body, promo_type_store
from permissions import require_opt_in_kind
from promo_create_guard import NO_EXPECT, PREEMPT_SWITCH, Reservation
from promo_keep_decide import BUDGET_DAY, BUDGET_HOUR, create_hold, preempt_applies

log = logging.getLogger("of-relay.promotions_api")

router = APIRouter()

KEEP_RUNNING_KIND = "promo_reactivate"
KEEP_RUNNING_EVERY_S = 3600
KEEP_RUNNING_STEPS = {"dry_run": False, "cooldown_minutes": 2, "max_reactivations": 0}


async def _keep_running_rule(s, account_id: str, *, on: bool) -> str:
    await require_opt_in_kind(KEEP_RUNNING_KIND, account_id)
    if on:
        return await ensure_kind_rule(s, account_id, KEEP_RUNNING_KIND, enable=True,
                                      every_seconds=KEEP_RUNNING_EVERY_S,
                                      steps=dict(KEEP_RUNNING_STEPS))
    return await ensure_kind_rule(s, account_id, KEEP_RUNNING_KIND, enable=False)


def _unarmable(discount: int | None, of_promo_id: int | None) -> str | None:
    if not (1 <= int(discount or 0) <= 100):
        return "this campaign has no saved discount, so it can't be re-created"
    if of_promo_id is None:
        return ("this campaign isn't linked to an OnlyFans promo, so its state "
                "can't be checked — re-create it to enable Keep running")
    return None


IN_FLIGHT = ("A promotion create for this Creator is still waiting on OnlyFans — "
             "give it a minute, then try again.")
UNRESOLVED_TICK = "It shows here once OnlyFans lists it; tick Keep running then"
UNRESOLVED_UNLINKED = ("It shows here once OnlyFans lists it, as an OnlyFans-only promo "
                       "Keep running can't be ticked on")


TRIAL_UNLIMITED_TEXT = "A free trial with unlimited claims can't keep running — set an Offer limit first."
RECREATE_MAX = 10


def _trial_refusal(discount: int | None, cap: int | None) -> dict | None:
    # A Free trial with unlimited claims could hand out free subs without end.
    if not promo_create_guard.unlimited_trial(discount, cap):
        return None
    return {"error": "trial_unlimited", "message": TRIAL_UNLIMITED_TEXT}


_HELD_TEXT = {
    "unknown": "waiting for OnlyFans to show the last re-create — Inflowwww checks on its next look, "
               "nothing to do",
    "backoff": "the last re-create failed, so Inflowwww waits before trying again — nothing to do",
    "budget": f"{BUDGET_HOUR} re-creates this hour (or {BUDGET_DAY} today) is the most Inflowwww "
              f"makes — nothing to do",
}
_WAIT_TEXT = {
    "count_untrusted": "the claim count isn't reliable yet",
    "end_unconfirmed": "OnlyFans' end time isn't confirmed yet",
    "clock": "OnlyFans' clock doesn't match ours",
    "second_live": "another promo is live too",
    "breaker_hold": "the last re-create hasn't shown up on OnlyFans yet",
    "backoff": "the last re-create failed",
    "budget": f"{BUDGET_HOUR} re-creates this hour (or {BUDGET_DAY} today) reached",
    "no_recovery_slot": "keeping a re-create spare in case one fails",
    "cooldown": "the last re-create was moments ago",
}
_SWITCH_TEXT = "Re-create at 90% filled is off on this server — ask the owner"


def _line(text: str, off: bool, lead: str | None = None, until: datetime | None = None) -> dict:
    return {"lead": lead, "text": text, "off": off, "until": iso_plain(until)}


def keep_lines(m: PromoCampaign, blocked: str | None, until: datetime | None,
               wait: str | None) -> list[dict]:
    lines: list[dict] = []
    if m.keep_warning:
        lines.append(_line(promo_create_guard.OFF_TEXT.get(m.keep_warning, "tick Keep running again"),
                           True, "Keep running is off"))
    act = {"fence": promo_create_guard.FENCE_TEXT, "retick": promo_create_guard.RETICK_TEXT,
           "limit_needed": promo_create_guard.OFF_TEXT["limit_needed"]}
    if blocked in act:
        lines.append(_line(act[blocked], True, "Not re-creating"))
    elif blocked == "switch":
        lines.append(_line(_SWITCH_TEXT, False))
    elif blocked and blocked != "clock":
        lines.append(_line(_HELD_TEXT.get(blocked, blocked), False, "Paused", until))
    if wait:
        lines.append(_line(f"will re-create after it ends ({_WAIT_TEXT.get(wait, wait)})", False, "Waiting"))
    if m.auto_reactivate and m.recreates_left is not None:
        n = m.recreates_left
        lines.append(_line(f"{n} re-create{'' if n == 1 else 's'} left, then Keep running turns off", False))
    return lines


async def _kept_now(s, account_id: str) -> PromoCampaign | None:
    return (await s.execute(select(PromoCampaign).where(
        PromoCampaign.account_id == account_id,
        PromoCampaign.auto_reactivate.is_(True)).order_by(PromoCampaign.id).limit(1))).scalar_one_or_none()


def _moved(now: PromoCampaign | None, after_create: bool = False) -> HTTPException:
    if after_create:
        msg = (f"it's now on “{now.name}” — tick Keep running on this row if you want it here instead"
               if now else "it was turned off meanwhile — tick Keep running on this row to keep it running")
    else:
        msg = f"Keep running {f'is now on “{now.name}”' if now else 'is now off'} — check the form and create again."
    return HTTPException(409, {
        "reason": "keep_running_moved",
        "taken_from": {"id": now.id, "name": now.name} if now else None,
        "message": msg})


def _terms_line(t: dict) -> str:
    cap = int(t.get("subscribe_counts") or 0)
    return f"{t.get('discount')}% off, {cap or 'unlimited'} claims"


async def _moved_now(account_id: str) -> HTTPException:
    async with get_session() as s:
        return _moved(await _kept_now(s, account_id))


async def _landed(account_id: str, rid: int) -> HTTPException:
    # That create is on OF already; sending again would double it.
    async with get_session() as s:
        r = await s.get(PromoCreateReservation, rid)
    t = {} if r is None else promo_create_guard.reservation_of(r).terms
    return HTTPException(409, {
        "reason": "create_landed", "id": rid, "of_promo_id": None if r is None else r.of_promo_id,
        "message": f"The earlier create ({_terms_line(t)}) did go through on OnlyFans — it's on "
                   f"the list now, so nothing new was sent."})


async def reserve_manual(account_id: str, source: str, terms: dict, resolve_open: int | None,
                         expect_kept: Any = NO_EXPECT, pre_ids: list[int] | None = None) -> Reservation:
    got = await promo_create_guard.reserve(account_id, None, source, terms, {}, pre_ids, None,
                                           expect_kept=expect_kept, unless_landed=resolve_open)
    if isinstance(got, Reservation):
        return got
    await _refused(account_id, got)
    blocking = got.blocking
    items = await fetch_of_promos(account_id, need_ids=set(), max_pages=1)
    await promo_create_guard.reconcile(account_id, items)
    row = await _reservation(blocking)
    if row is not None and row.state == "created":
        raise await _landed(account_id, row.id)
    if row is not None and row.state in promo_create_guard.OPEN:
        # A sent row's sender may still be in its POST: its age runs from the send.
        since = row.sent_at if row.state != "pending" and row.sent_at else row.created_at
        if (datetime.utcnow() - since).total_seconds() <= promo_create_guard.SETTLE_GRACE_S:
            raise HTTPException(409, {"reason": "create_in_flight", "message": IN_FLIGHT})
        if resolve_open != row.id:
            t = promo_create_guard.reservation_of(row).terms
            raise HTTPException(409, {
                "reason": "create_unresolved", "id": row.id, "terms": t,
                "message": f"An earlier create ({_terms_line(t)}) got no answer from OnlyFans and "
                           f"isn't on its list. If it did not go through, create anyway."})
        if not await promo_create_guard.clear(row):
            row = await _reservation(blocking)
            if row is not None and row.state == "created":
                raise await _landed(account_id, row.id)
            if row is not None and row.state in promo_create_guard.OPEN:
                raise HTTPException(409, {"reason": "create_in_flight", "message": IN_FLIGHT})
    pre = None if items is None else [p["of_promo_id"] for p in items if p.get("of_promo_id") is not None]
    got = await promo_create_guard.reserve(account_id, None, source, terms, {}, pre, None,
                                           expect_kept=expect_kept, unless_landed=blocking)
    if isinstance(got, Reservation):
        return got
    await _refused(account_id, got)
    raise HTTPException(409, {"reason": "create_in_flight", "message": IN_FLIGHT})


async def _reservation(rid: int | None) -> PromoCreateReservation | None:
    if rid is None:
        return None
    async with get_session() as s:
        return await s.get(PromoCreateReservation, rid)


async def _refused(account_id: str, got: promo_create_guard.Refused) -> None:
    if got.reason == "keep_running_moved":
        raise await _moved_now(account_id)
    if got.reason == "create_landed":
        raise await _landed(account_id, got.blocking)
    if got.reason != "create_open" or got.blocking is None:
        raise HTTPException(409, {"reason": "create_in_flight", "message": IN_FLIGHT})


@router.get("/admin/promotions")
async def list_promotions(account_id: str = Query(...)) -> dict[str, Any]:
    assert_account_owned(account_id)
    of_pacing.note_user(account_id)
    fetched = await fetch_of_promos(account_id)
    await promo_create_guard.reconcile(account_id, fetched)
    now = datetime.utcnow()
    budget = await promo_create_guard.budget_state(account_id, now)
    hold = create_hold(budget.auto_times, budget.not_before, now)
    async with get_session() as s:
        mirrors = (await s.execute(
            select(PromoCampaign).where(PromoCampaign.account_id == account_id)
            .order_by(PromoCampaign.created_at.desc())
        )).scalars().all()
        unresolved = set((await s.execute(select(PromoCreateReservation.campaign_id).where(
            PromoCreateReservation.account_id == account_id,
            PromoCreateReservation.state.in_(("sending", "unknown"))))).scalars().all())
        keep = await s.get(PromoKeepState, account_id)
    wait_reason = keep.wait_reason if keep else None
    preempt_on = runtime_switches.on(PREEMPT_SWITCH)

    def _cap(m: PromoCampaign, live: dict | None) -> int | None:
        # OF's cap: 0 is unlimited, not unset.
        got = (live or {}).get("subscribe_counts")
        return m.subscribe_counts if got is None else got

    def _waits(m: PromoCampaign, cap: int | None) -> bool:
        return bool(m.auto_reactivate) and preempt_applies(preempt_on, bool(m.preempt), cap)

    def _blocked(m: PromoCampaign, cap: int | None) -> tuple[str | None, datetime | None]:
        if m.id in unresolved:
            return "unknown", None
        if m.auto_reactivate and promo_create_guard.fenced(m.keep_host_id):
            return promo_create_guard.fenced(m.keep_host_id), None
        if m.auto_reactivate and promo_create_guard.trial_unlimited(m):
            return "limit_needed", None
        if m.auto_reactivate and hold:
            return hold
        if m.auto_reactivate and not preempt_on and preempt_applies(True, bool(m.preempt), cap):
            return "switch", None
        if _waits(m, cap) and wait_reason == "clock":
            return "clock", None
        return None, None

    def _from_mirror(m: PromoCampaign, live: dict | None) -> dict:
        cap = _cap(m, live)
        blocked, until = _blocked(m, cap)
        wait = wait_reason if _waits(m, cap) else None
        return {
            "id": m.id,
            "of_promo_id": m.of_promo_id,
            "name": m.name,
            # OF never echoes the discount on list: the mirror is the record.
            "discount_percent": m.discount_percent,
            "price_cents": (live or {}).get("price_cents", m.price_cents),
            "subscribe_counts": cap,
            # `or` hid the truth: OF stores subscribeDays=0 for a percent discount and 0 is falsy.
            "subscribe_days": live["subscribe_days"] if live else m.subscribe_days,
            "message": (live or {}).get("message") or m.message,
            "promo_type": (live or {}).get("promo_type") or m.promo_type,
            "status": (live or {}).get("status") or m.status,
            "subscriber_count": (live or {}).get("subscriber_count", m.subscriber_count),
            "auto_reactivate": bool(m.auto_reactivate),
            "reactivate_count": int(m.reactivate_count or 0),
            "last_reactivated_at": iso_plain(m.last_reactivated_at),
            "recreates_left": m.recreates_left,
            "keep_warning": m.keep_warning,
            "keep_blocked": blocked,
            "preempt": bool(m.preempt and m.auto_reactivate),
            "keep_wait": wait,
            "keep_lines": keep_lines(m, blocked, until, wait),
            "created_at": iso_plain(m.created_at),
            "source": "mirror",
        }

    def _from_live(p: dict) -> dict:
        return {
            "id": None,
            "of_promo_id": p["of_promo_id"],
            "name": p.get("message") or f"Promo #{p['of_promo_id']}",
            "discount_percent": None,
            "price_cents": p["price_cents"],
            "subscribe_counts": p["subscribe_counts"],
            "subscribe_days": p["subscribe_days"],
            "message": p["message"],
            "promo_type": p["promo_type"],
            "status": p["status"],
            "subscriber_count": p["subscriber_count"],
            "auto_reactivate": False,
            "reactivate_count": 0,
            "last_reactivated_at": None,
            "recreates_left": None,
            "keep_warning": None,
            "keep_blocked": None,
            "preempt": False,
            "keep_wait": None,
            "keep_lines": [],
            "created_at": p.get("created_at"),
            "source": "onlyfans",
        }

    out = merge_mirrors(mirrors, fetched, of_id_attr="of_promo_id",
                        live_id_key="of_promo_id",
                        from_mirror=_from_mirror, from_live=_from_live)
    past = await link_metrics.past_promo_ids(account_id)
    folded = {o for m in mirrors for o in past.get(m.id, []) if o != m.of_promo_id}
    out = [r for r in out if r["id"] is not None or r["of_promo_id"] not in folded]
    groups = {r["of_promo_id"]: list(dict.fromkeys([r["of_promo_id"], *(past.get(r["id"], []) if r["id"] else [])]))
              for r in out if r.get("of_promo_id")}
    figures = await link_metrics.for_list(
        account_id, "promo", groups,
        None if fetched is None else link_metrics.links_of_promos(fetched, mirrors, past))
    for r in out:
        r["metrics"] = figures["by"].get(r.get("of_promo_id"), dict(link_metrics._UNWALKED))
    return {"campaigns": out, "of_available": fetched is not None,
            "metrics_updated_at": figures["updated_at"], "metrics_refreshing": figures["refreshing"]}


class _CreateBody(BaseModel):
    account_id: str
    name: str
    discount: int = Field(50, ge=1, le=100)
    subscribe_counts: int = 10
    subscribe_days: int = 30
    message: str = Field("", max_length=500)
    promo_type: str | list[str] = "all"
    finish_days: int | None = Field(None, ge=0, le=30)
    auto_reactivate: bool = False
    recreate_limit: int | None = Field(None, ge=1, le=RECREATE_MAX)
    preempt: bool = True
    expect_taken_from: int | None = None
    resolve_open: int | None = None


@router.post("/admin/promotions")
async def create_promotion(body: _CreateBody = Body(...)) -> dict[str, Any]:
    assert_account_owned(body.account_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    try:
        promo_type = promo_type_store(body.promo_type)
    except ValueError as e:
        raise HTTPException(422, str(e))
    discount = max(1, min(int(body.discount), 100))
    # 0 = UNLIMITED: OF accepts subscribeCounts=0 and echoes null (verified live); a max(1,...) floor hid it.
    counts = max(0, min(int(body.subscribe_counts), 100000))
    days = max(0, min(int(body.subscribe_days), 3650))
    # 100%-off IS a free trial: OF sets price=0 and honours subscribeDays but rejects < 1, so it needs a real duration.
    if discount >= 100:
        days = max(1, days)
    # Checked at reserve and again at the sending CAS: a Takeover the operator did not see never happens.
    expect = (body.expect_taken_from if body.auto_reactivate
              and "expect_taken_from" in body.model_fields_set else NO_EXPECT)
    if body.auto_reactivate:
        why = _trial_refusal(discount, counts)
        if why:
            raise HTTPException(422, why)

    terms = {"discount": discount, "subscribe_counts": counts, "subscribe_days": days,
             "message": body.message or "", "type": promo_type_body(promo_type),
             **({} if body.finish_days is None else {"finish_days": int(body.finish_days)}),
             "mirror": {"name": name, "promo_type": promo_type}}
    pre = None
    if body.auto_reactivate:
        items = await fetch_of_promos(body.account_id, need_ids=set(), max_pages=1)
        pre = None if items is None else [p["of_promo_id"] for p in items if p.get("of_promo_id") is not None]
    res = await reserve_manual(body.account_id, "manual", terms, body.resolve_open, expect, pre)
    sent = await promo_create_guard.send(res, {}, lambda: ax._make_client(body.account_id), terms)
    if sent.refused == "keep_running_moved":
        raise await _moved_now(body.account_id)
    if sent.outcome is None:
        raise HTTPException(409, {"reason": "create_in_flight", "message": IN_FLIGHT})
    if sent.error is not None:
        raise_if_free_page_denied(sent.error, "promotions")
        maybe = (" — it may still have gone through: it shows here once OnlyFans lists it"
                 if sent.outcome.state == "unknown" else "")
        raise HTTPException(502, f"OnlyFans promotion create failed (session/API){maybe}: "
                                 f"{repr(sent.error)[:200]}")
    def unresolved(adoptable: bool) -> dict:
        out = {"id": None, "of_promo_id": None, "name": name, "create": "unknown",
               "auto_reactivate": False}
        if body.auto_reactivate:
            out["auto_reactivate_refused"] = UNRESOLVED_TICK if adoptable else UNRESOLVED_UNLINKED
        return out
    if sent.outcome.state != "created":
        return unresolved(res.pre_ids is not None)
    async with get_session() as s:
        mirror_id = (await s.get(PromoCreateReservation, res.id)).campaign_id
        row = None if mirror_id is None else await s.get(PromoCampaign, mirror_id)
        if row is None:
            return {**unresolved(False), "of_promo_id": (sent.outcome.item or {}).get("of_promo_id")}
        of_id, effective_days, subs = row.of_promo_id, row.subscribe_days, row.subscriber_count
    log.info("promo_created id=%s account=%s of_id=%s discount=%s%%",
             mirror_id, body.account_id, of_id, discount)
    # The mirror row is committed above on its own: the promo is live on OF, so a failed arm must never lose it.
    armed, refused, taken = False, None, None
    if body.auto_reactivate:
        refused = _unarmable(discount, of_id)
        if refused is None:
            try:
                taken = await _arm(body.account_id, mirror_id, body.recreate_limit,
                                   _ANY if expect is NO_EXPECT else expect, preempt=body.preempt,
                                   after_create=True)
                armed = True
            except HTTPException as e:
                d = e.detail if isinstance(e.detail, dict) else {}
                refused = d.get("message") or str(e.detail)
        if refused:
            log.info("promo_created_unarmed id=%s reason=%s", mirror_id, refused)
    if armed:
        try:
            from automations import promo_reactivate
            async with get_session() as s:
                await promo_create_guard.seed_memo(s, body.account_id, sent.outcome.item or {})
            await promo_reactivate.queue_first_read(body.account_id)
        except Exception:
            log.warning("promo_first_read_failed account=%s campaign=%s", body.account_id, mirror_id,
                        exc_info=True)
    out = {"id": mirror_id, "of_promo_id": of_id, "name": name,
           "discount_percent": discount, "price_cents": 0, "subscribe_counts": counts,
           "subscribe_days": effective_days, "message": body.message or "",
           "promo_type": promo_type, "status": "active",
           "subscriber_count": subs,
           "auto_reactivate": armed, "preempt": body.preempt if armed else None,
           "reactivate_count": 0,
           "last_reactivated_at": None, "source": "mirror",
           "keep_running_taken_from": taken}
    if refused:
        out["auto_reactivate_refused"] = refused
    return out


def _tick(row: PromoCampaign, recreate_limit: int | None, preempt: bool | None,
          *, limit_sent: bool = True) -> None:
    restamp = not row.auto_reactivate or row.keep_warning is not None
    row.auto_reactivate = True
    if preempt is not None:
        row.preempt = preempt
    row.keep_host_id = promo_create_guard.host_id()
    if restamp:
        row.keep_warning = None
        row.keep_ticked_at = datetime.utcnow()
    if restamp or limit_sent:
        row.recreates_left = recreate_limit if int(row.discount_percent or 0) == 100 else None


_ANY = object()


async def _arm(account_id: str, mirror_id: int, recreate_limit: int | None,
               expect_taken_from: Any = _ANY, *, refuse_others: bool = False,
               preempt: bool | None = None, limit_sent: bool = True,
               after_create: bool = False) -> dict | None:
    try:
        async with get_session() as s:
            # A write first: SQLite's write lock, so the read below is the one the tick acts on.
            await s.execute(update(PromoCampaign).where(PromoCampaign.id == mirror_id)
                            .values(auto_reactivate=PromoCampaign.auto_reactivate))
            row = await s.get(PromoCampaign, mirror_id)
            if row is None:
                raise HTTPException(404, "promotion not found")
            others = (await s.execute(select(PromoCampaign).where(
                PromoCampaign.account_id == account_id,
                PromoCampaign.auto_reactivate.is_(True),
                PromoCampaign.id != mirror_id).order_by(PromoCampaign.id))).scalars().all()
            if refuse_others and others:
                raise HTTPException(
                    409, f"“{others[0].name}” is already set to keep running. OnlyFans only runs "
                         f"one promotion at a time, so turn that one off first.")
            if expect_taken_from is not _ANY and (others[0].id if others else None) != expect_taken_from:
                raise _moved(others[0] if others else None, after_create)
            for o in others:
                o.auto_reactivate = False
            await s.flush()
            _tick(row, recreate_limit, preempt, limit_sent=limit_sent)
            await _keep_running_rule(s, account_id, on=True)
            filed: list[str] = []
            if others:
                prev = others[0]
                filed = await notifications_api.file_for_creator_owners(
                    s, account_id, lambda nick: notifications_api.Notice(
                        promo_create_guard.NOTICE_KIND,
                        f"{nick}: Keep running moved from “{prev.name}” to “{row.name}”.",
                        account_id=account_id, data={"campaign_id": mirror_id, "taken_from": prev.id},
                        dedupe=f"promo_keep_taken:{mirror_id}"))
    except IntegrityError:
        async with get_session() as s:
            raise _moved(await _kept_now(s, account_id), after_create)
    await notifications_api.push_unread(filed)
    log.info("promo_keep_running_moved id=%s unarmed=%s", mirror_id, [o.id for o in others])
    return {"id": others[0].id, "name": others[0].name} if others else None


class _PatchBody(BaseModel):
    """The operator-toggleable fields: keep this promo permanently on offer, a Free
    trial's optional Re-create limit (omitted = no limit on an off→on tick; unchanged on a
    campaign already Kept), and Re-create at 90% filled. Omitted = unchanged; at least one of
    the two ticks."""
    auto_reactivate: bool | None = None
    recreate_limit: int | None = Field(None, ge=1, le=RECREATE_MAX)
    preempt: bool | None = None


@router.patch("/admin/promotions/{mirror_id}")
async def update_promotion(mirror_id: int, body: _PatchBody = Body(...)) -> dict[str, Any]:
    """Turn Keep running on/off for one campaign. When on, the `promo_reactivate`
    automation re-creates it on OF each time it finishes; the rule is ensured
    (on) or, with no armed campaign left, switched off, in the same transaction.
    A second campaign is REFUSED (409), not moved onto: unlike the create form,
    this tick does not make a new promo, so taking the flag from a running one
    is an operator's explicit untick first."""
    if body.auto_reactivate is None and body.preempt is None:
        raise HTTPException(422, "send auto_reactivate or preempt")
    async with get_session() as s:
        row = await s.get(PromoCampaign, mirror_id)
        if row is None:
            raise HTTPException(404, "promotion not found")
        assert_account_owned(row.account_id)
        # The automation fails closed on these (can't tell finished from live), so arming one would silently do nothing.
        if body.auto_reactivate and not (1 <= int(row.discount_percent or 0) <= 100):
            raise HTTPException(422, _unarmable(row.discount_percent, row.of_promo_id))
        if body.auto_reactivate and row.of_promo_id is None:
            raise HTTPException(422, _unarmable(row.discount_percent, row.of_promo_id))
        why = body.auto_reactivate and _trial_refusal(row.discount_percent, row.subscribe_counts)
        if why:
            raise HTTPException(422, why)
        account_id = row.account_id
        if body.auto_reactivate is False:
            await _untick(s, row)
        elif body.preempt is not None and body.auto_reactivate is None:
            done = (await s.execute(update(PromoCampaign).where(
                PromoCampaign.id == mirror_id, PromoCampaign.auto_reactivate.is_(True))
                .values(preempt=body.preempt))).rowcount
            if not done:
                raise HTTPException(422, "tick Keep running first")
    if body.auto_reactivate:
        await _arm(account_id, mirror_id, body.recreate_limit, refuse_others=True,
                   preempt=body.preempt, limit_sent="recreate_limit" in body.model_fields_set)
    async with get_session() as s:
        row = await s.get(PromoCampaign, mirror_id)
        out = {"id": row.id, "auto_reactivate": row.auto_reactivate,
               "preempt": bool(row.preempt and row.auto_reactivate),
               "recreates_left": row.recreates_left,
               "reactivate_count": int(row.reactivate_count or 0),
               "last_reactivated_at": iso_plain(row.last_reactivated_at)}
    log.info("promo_auto_reactivate id=%s -> %s preempt=%s", mirror_id, body.auto_reactivate,
             body.preempt)
    return out


async def _untick(s, row: PromoCampaign) -> None:
    await s.execute(update(PromoCampaign).where(PromoCampaign.id == row.id)
                    .values(auto_reactivate=False))
    still = (await s.execute(select(PromoCampaign.id).where(
        PromoCampaign.account_id == row.account_id,
        PromoCampaign.auto_reactivate.is_(True),
        PromoCampaign.id != row.id).limit(1))).scalar_one_or_none()
    if still is None:
        await _keep_running_rule(s, row.account_id, on=False)


async def untick_kept_promo(account_id: str, of_promo_id: int) -> None:
    async with get_session() as s:
        row = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.account_id == str(account_id),
            PromoCampaign.of_promo_id == int(of_promo_id),
            PromoCampaign.auto_reactivate.is_(True)).limit(1))).scalar_one_or_none()
        if row is not None:
            await _untick(s, row)
            log.info("promo_keep_unticked_by_raw_stop id=%s of_id=%s", row.id, of_promo_id)


@router.delete("/admin/promotions/{mirror_id}")
async def delete_promotion(mirror_id: int) -> dict[str, Any]:
    async with get_session() as s:
        await s.execute(update(PromoCampaign).where(PromoCampaign.id == mirror_id)
                        .values(auto_reactivate=PromoCampaign.auto_reactivate))
        row = await s.get(PromoCampaign, mirror_id)
        if row is None:
            raise HTTPException(404, "promotion not found")
        assert_account_owned(row.account_id)
        if row.auto_reactivate:
            if (await s.execute(select(PromoCreateReservation.id).where(
                    PromoCreateReservation.account_id == row.account_id,
                    PromoCreateReservation.state.in_(promo_create_guard.OPEN)).limit(1))).first():
                raise HTTPException(409, {"reason": "create_in_flight", "message": IN_FLIGHT})
            await _untick(s, row)
    return await delete_mirrored(
        PromoCampaign, mirror_id, of_id_attr="of_promo_id",
        of_delete=lambda c, oid: c.delete_promo(oid),
        not_found="promotion not found", label="promo")
