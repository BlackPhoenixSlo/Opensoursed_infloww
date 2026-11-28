from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from curl_cffi.const import CurlECode
from curl_cffi.requests import exceptions as curl_exc
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

import account_health
import link_metrics
import notifications_api
import of_pacing
import platforms
import runtime_switches
from automations._knobs import bool_knob
from db.engine import get_session
from db.models import AutomationRule, PromoCampaign, PromoCreateReservation, PromoKeepState
from isotime import parse_iso
from of_client import (PRE_DISPATCH, OFAPIError, OFDeactivatedError, OFDeniedError, OFDispatchRefused,
                       proxy_refused)
from of_promos import extract_created_promo, normalise_of_promo, promo_expires_at
from promo_keep_decide import (BREAKER_N, TIMED_LEAD_S, backoff_until, create_hold,  # noqa: F401
                               failure_turns_off, in_timed_window, preempt_failure, recovery_slot)

log = logging.getLogger("of-relay.promo_create_guard")

# SETTLE_GRACE_S > slot wait + retries; CREATED_AT_SLACK_S: OF's createdAt may trail our sent_at stamp.
SETTLE_GRACE_S = 600
UNKNOWN_OFF_S = 900
CREATED_AT_SLACK_S = 5
DECISION_MAX_AGE_S = 90
OPEN = ("pending", "sending", "unknown")
REACHED = ("sending", "unknown", "created", "lost")
AUTO_SOURCES = ("auto_ended", "auto_fill", "auto_timed")
PREEMPT_SOURCES = ("auto_fill", "auto_timed")
PREEMPT_SWITCH = "PROMO_PREEMPT_ENABLED"
MANUAL_SOURCES = ("manual", "manual_raw")
NOTICE_KIND = "promo_keep_running"
_SOURCE_WORD = {"auto_ended": "ended", "auto_fill": "filled", "auto_timed": "was ending"}
OFF_TEXT = {
    "create_unknown": "a promo create got no clear answer from OnlyFans and never showed up — "
                      "check the promos on OnlyFans, then tick Keep running again",
    "breaker": "3 promos in a row got no new claims or never went live — check the offer, "
               "then tick Keep running again",
    "price_free": "OnlyFans refused the promo because the page is free — set a subscription "
                  "price on OnlyFans, then tick Keep running again",
    "captcha": "OnlyFans asked for a captcha — open the account on OnlyFans, then tick Keep "
               "running again",
    "deactivated": "this Creator is deactivated — activate it, then tick Keep running again",
    "rate_limited": "OnlyFans refused two promo creates in a row (rate limit or block) — wait a "
                    "while, then tick Keep running again",
    "create_refused": "OnlyFans refused the promo create — check the offer, then tick Keep "
                      "running again",
    "limit_reached": "the free trial used up its Re-create limit — tick Keep running again "
                     "to set a new one",
    "limit_needed": "this free trial has no Offer limit, so it can't keep running — create a "
                    "new one with an Offer limit",
    "kept_duplicate": "another campaign of this Creator was also set to keep running, and only "
                      "one can be — tick Keep running again on the one you want",
}
HOST_ENV = "PROMO_CREATE_HOST_ID"
FENCE_TEXT = "This server is not set to create promos — ask the owner to set it up"
RETICK_TEXT = "Tick Keep running again"
KEEP_KIND = "promo_reactivate"


NO_EXPECT = object()


@dataclass(frozen=True)
class Reservation:
    id: int
    account_id: str
    campaign_id: int | None
    source: str
    terms: dict = field(default_factory=dict)
    decision_read_at: datetime | None = None
    pre_ids: tuple[int, ...] | None = None
    rule_id: int | None = None
    ticked_at: datetime | None = None
    expect_kept: Any = NO_EXPECT
    timed_end: datetime | None = None


@dataclass(frozen=True)
class Refused:
    reason: str
    blocking: int | None = None


@dataclass(frozen=True)
class Outcome:
    state: str
    item: dict | None = None
    error_class: str | None = None
    retry_after_s: float | None = None


def _causes(error: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    e: BaseException | None = error
    while e is not None and all(e is not x for x in out):
        out.append(e)
        e = e.__cause__
    return out


# Fired before the request left the box (proxy refused tunnel, DNS, TCP connect): safe to treat as not_sent.
def _pre_send(e: BaseException) -> bool:
    return (proxy_refused(e) or isinstance(e, curl_exc.DNSError)
            or (isinstance(e, curl_exc.ConnectionError)
                and getattr(e, "code", None) == CurlECode.COULDNT_CONNECT))


def outcome_of(res: Any = None, error: BaseException | None = None) -> Outcome:
    if error is not None:
        chain = _causes(error)
        if any(_pre_send(e) for e in chain):
            return Outcome("failed", error_class="not_sent")
        error = next((e for e in chain if isinstance(e, OFAPIError)), error)
        if isinstance(error, OFDeactivatedError):
            return Outcome("failed", error_class="deactivated")
        if isinstance(error, OFDeniedError):
            return Outcome("failed", error_class="not_sent")
        if account_health.is_session_dead_error(error):
            return Outcome("failed", error_class="session_dead")
        status, body, header = of_pacing.upstream(error) if isinstance(error, OFAPIError) else (None, "", None)
        if isinstance(status, int) and 400 <= status < 500:
            text = f"{body} {error}"
            cls = ("price_free" if "Access denied" in text
                   else "captcha" if "captcha" in text.lower() else f"http_{status}")
            return Outcome("failed", error_class=cls,
                           retry_after_s=of_pacing.asked_wait(header, of_pacing.allow_s(body)))
        # 5xx, timeout, connection or bad body may have landed: unknown, never failed (reconcile decides).
        return Outcome("unknown")
    item = normalise_of_promo(extract_created_promo(res))
    return Outcome("created", item=item) if item.get("of_promo_id") is not None else Outcome("unknown")


def host_id() -> str:
    return os.environ.get(HOST_ENV, "").strip()


def fenced(stamp: str | None) -> str | None:
    if stamp is None:
        return "retick"
    here = host_id()
    return None if here and here == stamp else "fence"


# A Free trial with no Claim cap could hand out subs without end; the Re-create limit is optional (owner: Keep running is indefinite by default).
def unlimited_trial(discount: int | None, cap: int | None) -> bool:
    return int(discount or 0) == 100 and not cap


def trial_unlimited(c: PromoCampaign) -> bool:
    return unlimited_trial(c.discount_percent, c.subscribe_counts)


def _live_rule(steps_json: str | None) -> bool:
    try:
        steps = json.loads(steps_json or "{}")
    except (TypeError, ValueError):
        steps = {}
    return not bool_knob(steps if isinstance(steps, dict) else {}, "dry_run", True)


async def _recheck(s, res: Reservation, want: Mapping[str, Any], now: datetime) -> str | None:
    R = PromoCreateReservation
    auto = res.source in AUTO_SOURCES
    if res.campaign_id is not None:
        c = await s.get(PromoCampaign, res.campaign_id)
        if c is None or c.account_id != res.account_id:
            return "campaign_gone"
        if any(getattr(c, k) != v for k, v in want.items()):
            return "campaign_changed"
        if auto and fenced(c.keep_host_id):
            return "fence"
        if auto and c.recreates_left == 0:
            return "limit_reached"
        if auto and trial_unlimited(c):
            return "trial_unlimited"
        if auto and c.keep_ticked_at != res.ticked_at:
            return "campaign_changed"
    if res.source in PREEMPT_SOURCES and not runtime_switches.on(PREEMPT_SWITCH):
        return "switch_off"
    if res.expect_kept is not NO_EXPECT:
        kept = (await s.execute(select(PromoCampaign.id).where(
            PromoCampaign.account_id == res.account_id, PromoCampaign.auto_reactivate.is_(True))
            .order_by(PromoCampaign.id).limit(1))).scalar_one_or_none()
        if kept != res.expect_kept:
            return "keep_running_moved"
    if not auto:
        return None
    q = select(AutomationRule.steps_json).where(
        AutomationRule.account_id == res.account_id, AutomationRule.kind == KEEP_KIND,
        AutomationRule.is_enabled.is_(True))
    if res.rule_id is not None:
        q = q.where(AutomationRule.id == res.rule_id)
    if not any(_live_rule(j) for j in (await s.execute(q)).scalars().all()):
        return "rule_off"
    read = res.decision_read_at
    if read is None or now - read > timedelta(seconds=DECISION_MAX_AGE_S):
        return "decision_stale"
    # A failed send may have ended the live promo on OF all the same: the read predates it.
    failed_sent = and_(R.state == "failed", R.sent_at.is_not(None),
                       R.error_class.is_distinct_from("not_sent"))
    newer = (await s.execute(select(R.id).where(
        R.account_id == res.account_id, R.id != res.id, or_(R.state.in_(REACHED), failed_sent),
        or_(R.sent_at > read, R.settled_at > read)).limit(1))).scalar_one_or_none()
    if newer is not None:
        return "newer_create"
    if res.source == "auto_timed" and (
            res.timed_end is None or not in_timed_window((res.timed_end - now).total_seconds())):
        return "timed_window"
    times, not_before = await _budget_facts(s, res.account_id, now, exclude_id=res.id)
    hold = create_hold(times, not_before, now)
    if hold:
        return hold[0]
    if res.source in PREEMPT_SOURCES and not recovery_slot(times, now):
        return "no_recovery_slot"
    fresh = (await s.execute(select(R.of_promo_id).where(
        R.account_id == res.account_id, R.source.in_(MANUAL_SOURCES), R.state == "created",
        R.of_promo_id.is_not(None),
        R.settled_at > now - timedelta(seconds=SETTLE_GRACE_S)))).scalars().all()
    if any(int(i) not in set(res.pre_ids or ()) for i in fresh):
        return "manual_unlisted"
    return None


def promotion_type_refusal(account_id: str) -> str | None:
    return platforms.lack_refusal(str(account_id), platforms.Lack.PROMOTION_TYPE)


async def reserve(account_id: str, campaign_id: int | None, source: str, terms: dict,
                  expect: Mapping[str, Any], pre_ids: Sequence[int] | None,
                  decision_read_at: datetime | None, *, replaced_of_promo_id: int | None = None,
                  claims_seen: int | None = None, first_claims: int | None = None,
                  rule_id: int | None = None, ticked_at: datetime | None = None,
                  expect_kept: Any = NO_EXPECT, timed_end: datetime | None = None,
                  unless_landed: int | None = None) -> Reservation | Refused:
    aid = str(account_id)
    if why := promotion_type_refusal(aid):
        return Refused(why)
    ids = None if pre_ids is None else tuple(sorted({int(i) for i in pre_ids}))
    R = PromoCreateReservation
    try:
        async with get_session() as s:
            now = datetime.utcnow()
            # A write first takes SQLite's write lock, so the reads below are the ones the insert acts on.
            await s.execute(update(R).where(R.account_id == aid, R.state.in_(OPEN)).values(state=R.state))
            if unless_landed is not None and (await s.execute(select(R.id).where(
                    R.id == unless_landed, R.account_id == aid, R.state == "created"))).scalar_one_or_none():
                return Refused("create_landed", unless_landed)
            if (blocking := (await s.execute(select(R.id).where(
                    R.account_id == aid, R.state.in_(OPEN)).limit(1))).scalar_one_or_none()) is not None:
                return Refused("create_open", blocking)
            row = PromoCreateReservation(
                account_id=aid, campaign_id=campaign_id, source=source, state="pending",
                terms_json=json.dumps(terms), pre_ids_json=None if ids is None else json.dumps(ids),
                replaced_of_promo_id=replaced_of_promo_id, claims_seen=claims_seen,
                first_claims=first_claims, host_id=host_id(), created_at=now)
            s.add(row)
            await s.flush()
            res = Reservation(row.id, aid, campaign_id, source, dict(terms), decision_read_at,
                              ids, rule_id, ticked_at, expect_kept, timed_end)
            why = await _recheck(s, res, expect, now)
            if why:
                await s.rollback()
                return Refused(why)
    except IntegrityError:
        async with get_session() as s:
            gone = campaign_id is not None and await s.get(PromoCampaign, campaign_id) is None
        return Refused("campaign_gone" if gone else "create_open")
    return res


async def _guard(res: Reservation, recheck: Mapping[str, Any], frm: str) -> str | None:
    now = datetime.utcnow()
    R = PromoCreateReservation
    async with get_session() as s:
        if (await s.execute(update(R).where(R.id == res.id, R.state == frm)
                            .values(state="sending", sent_at=now))).rowcount != 1:
            return f"not_{frm}"
        why = await _recheck(s, res, recheck, now)
        if why:
            await s.execute(update(R).where(R.id == res.id)
                            .values(state="failed", error_class="not_sent", sent_at=None, settled_at=now))
            log.info("promo_create not sent account=%s reservation=%s reason=%s at=%s",
                     res.account_id, res.id, why, "cas" if frm == "pending" else "dispatch")
    return why


async def mark_sending(res: Reservation, recheck: Mapping[str, Any]) -> str | None:
    return await _guard(res, recheck, "pending")


async def _dispatch_check(res: Reservation, recheck: Mapping[str, Any]) -> str | None:
    return await _guard(res, recheck, "sending")


def _create_notice(res: Reservation, campaign: str, new_id: int | None):
    word = _SOURCE_WORD.get(res.source, "ended")
    return lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running re-created “{campaign}” after the last promo {word} — "
        f"new OnlyFans promo {new_id}.", account_id=res.account_id,
        data={"reservation_id": res.id, "of_promo_id": new_id}, dedupe=f"promo_create:{res.id}")


async def turn_off(s, account_id: str, campaign_id: int, reason: str, now: datetime) -> list[str]:
    c = await s.get(PromoCampaign, campaign_id)
    if c is None or not c.auto_reactivate:
        return []
    c.auto_reactivate = False
    c.keep_warning = reason
    c.keep_warning_at = now
    log.warning("promo_keep_off account=%s campaign=%s reason=%s", account_id, campaign_id, reason)
    return await notifications_api.file_for_creator_owners(s, account_id, lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running is off for “{c.name}” — {OFF_TEXT.get(reason, reason)}.",
        account_id=account_id, data={"campaign_id": campaign_id, "reason": reason},
        dedupe=f"promo_keep_off:{campaign_id}:{now.isoformat()}"))


async def _repoint(s, res: Reservation, item: dict, now: datetime) -> list[str]:
    row = await s.get(PromoCampaign, res.campaign_id)
    if row is None:
        return []
    new_id = item.get("of_promo_id")
    if row.of_promo_id and new_id != row.of_promo_id:
        # The finished promo stays under the campaign: its claimers' spend still counts toward Revenue.
        (await link_metrics.meta_row(s, res.account_id, "promo", int(row.of_promo_id))).campaign_id = row.id
    row.of_promo_id = new_id
    row.status = "active"
    row.subscriber_count = 0
    row.reactivate_count = int(row.reactivate_count or 0) + 1
    row.last_reactivated_at = now
    row.expires_at = promo_expires_at(item.get("finished_at"), row.finish_days, now)
    filed = await notifications_api.file_for_creator_owners(
        s, res.account_id, _create_notice(res, row.name, new_id))
    if row.recreates_left is not None:
        row.recreates_left = max(0, row.recreates_left - 1)
        if row.recreates_left == 0:
            filed += await turn_off(s, res.account_id, row.id, "limit_reached", now)
    return filed


async def seed_memo(s, account_id: str, item: dict) -> None:
    pid = item.get("of_promo_id")
    if pid is None or not item.get("claims_present") or int(item.get("subscriber_count") or 0) <= 0:
        return
    vals = {"kept_of_promo_id": pid, "first_claims": None,
            "last_claims": int(item.get("subscriber_count") or 0), "read_at": datetime.utcnow(),
            "finished_at": item.get("finished_at")}
    await s.execute(sqlite_insert(PromoKeepState).values(account_id=str(account_id), **vals)
                    .on_conflict_do_update(index_elements=["account_id"], set_=vals,
                                           where=PromoKeepState.kept_of_promo_id.is_distinct_from(pid)))


async def _stamp_skew(s, res: Reservation, item: dict, answer_at: datetime) -> None:
    at = parse_iso(item.get("created_at"))
    skew = round((answer_at - at).total_seconds()) if at is not None else None
    await s.execute(sqlite_insert(PromoKeepState).values(account_id=res.account_id, skew_s=skew)
                    .on_conflict_do_update(index_elements=["account_id"], set_={"skew_s": skew}))


async def _preempt_failed(s, res: Reservation, *, kept_off: bool, untick: bool,
                         recover: bool) -> list[str]:
    c = await s.get(PromoCampaign, res.campaign_id)
    log.warning("promo_preempt_failed account=%s campaign=%s reservation=%s",
                res.account_id, res.campaign_id, res.id)
    if untick and c is not None and c.preempt:
        c.preempt = False
        log.warning("promo_preempt_off account=%s campaign=%s reservation=%s",
                    res.account_id, res.campaign_id, res.id)
    name = c.name if c is not None else f"#{res.campaign_id}"
    tail = ("" if kept_off else
            " Re-create at 90% filled is off for it now (tick it again to retry); Keep running still "
            "re-creates it after the promo ends." if untick else
            " It re-creates after a short wait." if recover else
            " It re-creates once the Creator is logged in again.")
    return await notifications_api.file_for_creator_owners(s, res.account_id, lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running's early re-create of “{name}” failed — OnlyFans may have "
        f"ended the old promo, so no promo may be live.{tail}",
        account_id=res.account_id, data={"campaign_id": res.campaign_id, "reservation_id": res.id},
        dedupe=f"promo_preempt_failed:{res.id}"))


async def _preempt_unknown(s, res: Reservation) -> list[str]:
    c = await s.get(PromoCampaign, res.campaign_id)
    log.warning("promo_preempt_unknown account=%s campaign=%s reservation=%s",
                res.account_id, res.campaign_id, res.id)
    name = c.name if c is not None else f"#{res.campaign_id}"
    return await notifications_api.file_for_creator_owners(s, res.account_id, lambda nick: notifications_api.Notice(
        NOTICE_KIND, f"{nick}: Keep running's early re-create of “{name}” got no clear answer from "
        f"OnlyFans — no promo may be live. Check the promos on OnlyFans.",
        account_id=res.account_id, data={"campaign_id": res.campaign_id, "reservation_id": res.id},
        dedupe=f"promo_preempt_unknown:{res.id}"))


async def _adopt_manual(s, res: Reservation, item: dict, now: datetime) -> None:
    t, m = res.terms, res.terms.get("mirror") or {}
    days = item.get("subscribe_days")
    row = PromoCampaign(
        account_id=res.account_id, of_promo_id=item.get("of_promo_id"),
        name=m.get("name") or f"Promo #{item.get('of_promo_id')}",
        discount_percent=int(t.get("discount") or 0), price_cents=0,
        subscribe_counts=int(t.get("subscribe_counts") or 0),
        subscribe_days=int(t.get("subscribe_days") or 0) if days is None else days,
        message=t.get("message") or "", promo_type=m.get("promo_type") or "all", status="active",
        subscriber_count=item.get("subscriber_count") or 0, created_at=now,
        finish_days=t.get("finish_days"),
        expires_at=promo_expires_at(item.get("finished_at"), t.get("finish_days"), now))
    s.add(row)
    await s.flush()
    await s.execute(update(PromoCreateReservation).where(PromoCreateReservation.id == res.id)
                    .values(campaign_id=row.id))


async def _backoff(s, res: Reservation, outcome: Outcome, now: datetime) -> tuple[datetime, str | None]:
    R = PromoCreateReservation
    c = await s.get(PromoCampaign, res.campaign_id) if res.campaign_id is not None else None
    q = select(R.state, R.error_class, R.not_before).where(
        R.account_id == res.account_id, R.source.in_(AUTO_SOURCES), R.id != res.id,
        R.state.in_(("created", "failed", "lost")))
    if c is not None and c.keep_ticked_at is not None:
        q = q.where(R.created_at >= c.keep_ticked_at)
    k, prev = 1, None
    for state, cls, not_before in (await s.execute(q.order_by(R.id.desc()).limit(64))).all():
        if state == "created":
            break
        if not_before is None:
            continue
        if k == 1:
            prev = cls
        k += 1
    return backoff_until(now, k, outcome.retry_after_s), prev


async def settle(res: Reservation, outcome: Outcome, *, only: Sequence[str] = OPEN,
                 answer_at: datetime | None = None) -> bool:
    now = datetime.utcnow()
    R = PromoCreateReservation
    filed: list[str] = []
    async with get_session() as s:
        if outcome.state == "unknown":
            moved = (await s.execute(update(R).where(R.id == res.id, R.state == "sending")
                                     .values(state="unknown"))).rowcount == 1
            if moved and res.source in PREEMPT_SOURCES and res.campaign_id is not None:
                filed = await _preempt_unknown(s, res)
        else:
            moved = None
    if moved is not None:
        await notifications_api.push_unread(filed)
        return moved
    async with get_session() as s:
        new_id = (outcome.item or {}).get("of_promo_id")
        cols: dict[str, Any] = {}
        auto = res.source in AUTO_SOURCES
        if auto and outcome.state in ("failed", "lost"):
            cols["not_before"], prev = await _backoff(s, res, outcome, now)
            cols["retry_after_s"] = outcome.retry_after_s
        moved = (await s.execute(update(R).where(R.id == res.id, R.state.in_(tuple(only))).values(
            state=outcome.state, of_promo_id=new_id, error_class=outcome.error_class,
            settled_at=now, **cols))).rowcount
        if moved != 1:
            if outcome.state == "created" and new_id is not None:
                await s.execute(update(R).where(R.id == res.id, R.of_promo_id.is_(None))
                                .values(of_promo_id=new_id))
                log.warning("promo_create late_created account=%s reservation=%s of_promo_id=%s",
                            res.account_id, res.id, new_id)
            return False
        if outcome.state == "created" and answer_at is not None:
            await _stamp_skew(s, res, outcome.item, answer_at)
        if outcome.state == "created" and auto and res.campaign_id is not None:
            filed = await _repoint(s, res, outcome.item, now)
            await seed_memo(s, res.account_id, outcome.item)
        elif outcome.state == "created" and res.source == "manual":
            await _adopt_manual(s, res, outcome.item, now)
        elif outcome.state == "lost" and res.campaign_id is not None:
            filed = await turn_off(s, res.account_id, res.campaign_id, "create_unknown", now)
        elif outcome.state == "failed" and auto and res.campaign_id is not None:
            pre = res.source in PREEMPT_SOURCES
            off, untick, recover = preempt_failure(outcome.error_class, prev) if pre else \
                (failure_turns_off(outcome.error_class, prev), False, False)
            if off:
                filed = await turn_off(s, res.account_id, res.campaign_id, off, now)
            if pre and outcome.error_class != "not_sent":
                filed += await _preempt_failed(s, res, kept_off=bool(off), untick=untick,
                                               recover=recover)
    log.info("promo_create settled account=%s reservation=%s state=%s of_promo_id=%s",
             res.account_id, res.id, outcome.state, new_id)
    await notifications_api.push_unread(filed)
    return True


def _audience(v: Any) -> frozenset[str]:
    parts = v.split(",") if isinstance(v, str) else list(v or ())
    return frozenset(str(p).strip() for p in parts if str(p).strip()) or frozenset({"all"})


# OF echoes no discount: match a new ID by cap (null = 0), message and audience, allowing up to 5s before sent_at.
# Match subscribeDays only for discount 100 because OF stores 0 otherwise.
def _candidate(r: PromoCreateReservation, p: dict, held: set[int], now: datetime) -> bool:
    if r.pre_ids_json is None or r.sent_at is None:
        return False
    terms = json.loads(r.terms_json or "{}")
    pid = p.get("of_promo_id")
    if pid is None or pid in held or pid in set(json.loads(r.pre_ids_json)):
        return False
    at = parse_iso(p.get("created_at"))
    if at is None or not r.sent_at - timedelta(seconds=CREATED_AT_SLACK_S) <= at <= now:
        return False
    if int(p.get("subscribe_counts") or 0) != int(terms.get("subscribe_counts") or 0):
        return False
    if (p.get("message") or "") != (terms.get("message") or ""):
        return False
    if _audience(p.get("promo_type")) != _audience(terms.get("type")):
        return False
    return int(terms.get("discount") or 0) != 100 or \
        int(p.get("subscribe_days") or 0) == int(terms.get("subscribe_days") or 0)


def reservation_of(r: PromoCreateReservation) -> Reservation:
    pre = None if r.pre_ids_json is None else tuple(json.loads(r.pre_ids_json))
    return Reservation(r.id, r.account_id, r.campaign_id, r.source, json.loads(r.terms_json or "{}"),
                       pre_ids=pre)


async def reconcile(account_id: str, items: Sequence[dict] | None) -> int:
    aid, now, R = str(account_id), datetime.utcnow(), PromoCreateReservation
    grace = timedelta(seconds=SETTLE_GRACE_S)
    async with get_session() as s:
        open_rows = (await s.execute(select(R).where(R.account_id == aid, R.state.in_(OPEN)))).scalars().all()
        held = set((await s.execute(select(R.of_promo_id).where(
            R.account_id == aid, R.of_promo_id.is_not(None)))).scalars().all())
    settled = 0
    for r in open_rows:
        res = reservation_of(r)
        if r.state == "pending":
            # Never flipped to sending: no POST; the pending-only CAS loses to a sender that flips it meanwhile.
            if now - r.created_at > grace:
                settled += await settle(res, Outcome("failed", error_class="not_sent"), only=("pending",))
            continue
        if items is None or (r.state == "sending" and now - (r.sent_at or r.created_at) <= grace):
            continue
        # A negative read never settles a sent row failed: OF may list a create late.
        found = [p for p in items if _candidate(r, p, held, now)]
        if len(found) == 1:
            settled += await settle(res, Outcome("created", item=found[0]))
            continue
        async with get_session() as s:
            await s.execute(update(R).where(R.id == r.id, R.state.in_(OPEN))
                            .values(reconcile_reads=R.reconcile_reads + 1))
        if now - (r.sent_at or r.created_at) >= timedelta(seconds=UNKNOWN_OFF_S):
            settled += await settle(res, Outcome("lost"), only=(r.state,))
    if items is not None:
        await _stamp_listed(aid, items, now)
    return settled


async def _stamp_listed(aid: str, items: Sequence[dict], now: datetime) -> None:
    def went_live(p: dict) -> bool:
        return not p.get("is_finished") or (bool(p.get("claims_present"))
                                            and int(p.get("subscriber_count") or 0) > 0)
    live = {p.get("of_promo_id") for p in items if went_live(p)}
    R = PromoCreateReservation
    async with get_session() as s:
        recent = (await s.execute(select(R.id, R.of_promo_id, R.listed_at).where(
            R.account_id == aid, R.state == "created", R.source.in_(AUTO_SOURCES))
            .order_by(R.settled_at.desc()).limit(BREAKER_N))).all()
    seen = [rid for rid, pid, listed in recent if listed is None and pid in live]
    if seen:
        async with get_session() as s:
            await s.execute(update(R).where(R.id.in_(seen), R.listed_at.is_(None)).values(listed_at=now))


async def has_open(account_id: str) -> bool:
    R = PromoCreateReservation
    async with get_session() as s:
        return (await s.execute(select(R.id).where(
            R.account_id == str(account_id), R.state.in_(OPEN)).limit(1))).scalar_one_or_none() is not None


async def recent_creates(account_id: str) -> list[PromoCreateReservation]:
    R = PromoCreateReservation
    async with get_session() as s:
        return list((await s.execute(select(R).where(
            R.account_id == str(account_id), R.state == "created", R.source.in_(AUTO_SOURCES))
            .order_by(R.settled_at.desc()).limit(BREAKER_N * 3))).scalars())


async def replaced_ids(account_id: str, campaign_ids: set[int]) -> set[int]:
    R = PromoCreateReservation
    async with get_session() as s:
        rows = (await s.execute(select(R.replaced_of_promo_id, R.of_promo_id).where(
            R.account_id == str(account_id), R.campaign_id.in_(campaign_ids)))).all()
    return {int(i) for row in rows for i in row if i is not None}


async def open_row(account_id: str) -> PromoCreateReservation | None:
    R = PromoCreateReservation
    async with get_session() as s:
        return (await s.execute(select(R).where(
            R.account_id == str(account_id), R.state.in_(OPEN)).limit(1))).scalar_one_or_none()


async def clear(row: PromoCreateReservation) -> bool:
    return await settle(reservation_of(row), Outcome("cleared"), only=(row.state,))


async def fence_notices() -> int:
    here = host_id()
    filed: list[str] = []
    async with get_session() as s:
        kept = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.auto_reactivate.is_(True)))).scalars().all()
        blocked = [c for c in kept if fenced(c.keep_host_id)]
        for c in blocked:
            log.warning("promo_keep_blocked reason=fence account=%s campaign=%s", c.account_id, c.id)
            fix = RETICK_TEXT if fenced(c.keep_host_id) == "retick" else FENCE_TEXT
            filed += await notifications_api.file_for_creator_owners(
                s, c.account_id, lambda nick, c=c, fix=fix: notifications_api.Notice(
                    NOTICE_KIND, f"{nick}: Keep running can't re-create “{c.name}” on this server — {fix}.",
                    account_id=c.account_id, data={"campaign_id": c.id, "reason": "fence"},
                    dedupe=f"promo_keep_fenced:{c.id}:{here}"))
    await notifications_api.push_unread(filed)
    return len(blocked)


async def duplicate_notices() -> int:
    filed: list[str] = []
    async with get_session() as s:
        rows = (await s.execute(select(PromoCampaign).where(
            PromoCampaign.keep_warning == "kept_duplicate", PromoCampaign.auto_reactivate.is_(False),
            PromoCampaign.keep_warning_at.is_not(None)))).scalars().all()
        for c in rows:
            filed += await notifications_api.file_for_creator_owners(
                s, c.account_id, lambda nick, c=c: notifications_api.Notice(
                    NOTICE_KIND, f"{nick}: Keep running is off for “{c.name}” — "
                    f"{OFF_TEXT['kept_duplicate']}.", account_id=c.account_id,
                    data={"campaign_id": c.id, "reason": "kept_duplicate"},
                    dedupe=f"promo_keep_off:{c.id}:{c.keep_warning_at.isoformat()}"))
    await notifications_api.push_unread(filed)
    return len(rows)


@dataclass(frozen=True)
class Budget:
    auto_times: tuple[datetime, ...] = ()
    not_before: datetime | None = None


async def _budget_facts(s, account_id: str, now: datetime,
                        exclude_id: int | None = None) -> tuple[tuple[datetime, ...], datetime | None]:
    R = PromoCreateReservation
    mine = (R.account_id == str(account_id), R.source.in_(AUTO_SOURCES),
            *(() if exclude_id is None else (R.id != exclude_id,)))
    times = (await s.execute(select(R.created_at).where(
        *mine, R.created_at > now - timedelta(days=1)))).scalars().all()
    not_before = (await s.execute(select(func.max(R.not_before)).where(*mine))).scalar_one_or_none()
    return tuple(times), not_before


async def budget_state(account_id: str, now: datetime) -> Budget:
    async with get_session() as s:
        return Budget(*await _budget_facts(s, account_id, now))


@dataclass(frozen=True)
class Sent:
    outcome: Outcome | None
    result: Any = None
    error: Exception | None = None
    refused: str | None = None


async def send(res: Reservation, recheck: Mapping[str, Any], client: Callable[[], Any],
               terms: Mapping[str, Any], *, wrap: Callable[[Callable[[], Any]], Any] | None = None) -> Sent:
    loop = asyncio.get_running_loop()
    kwargs = {k: v for k, v in terms.items() if k != "mirror"}
    reached, refused, answer_at = False, None, None

    def post():
        nonlocal reached, refused, answer_at
        c = client()
        refused = asyncio.run_coroutine_threadsafe(mark_sending(res, recheck), loop).result()
        if refused:
            return None
        reached = True

        def last_check() -> str | None:
            nonlocal refused, reached
            try:
                refused = asyncio.run_coroutine_threadsafe(_dispatch_check(res, recheck), loop).result()
            except Exception as e:
                # The guard itself failed (locked DB): nothing left the box, so not_sent, never "may have reached OF".
                reached = False
                raise OFDispatchRefused("dispatch_check_failed") from e
            return refused
        token = PRE_DISPATCH.set(last_check)
        try:
            got = c.create_promo(**kwargs)
        finally:
            PRE_DISPATCH.reset(token)
        answer_at = datetime.utcnow()
        return got
    try:
        got = await asyncio.to_thread(wrap, post) if wrap else await asyncio.to_thread(post)
    except Exception as e:
        if refused:
            return Sent(None, error=e, refused=refused)
        log.warning("promo_create failed account=%s reservation=%s", res.account_id, res.id,
                    exc_info=True)
        outcome = outcome_of(error=e) if reached else Outcome("failed", error_class="not_sent")
        await settle(res, outcome)
        return Sent(outcome, error=e)
    if refused:
        return Sent(None, refused=refused)
    outcome = outcome_of(res=got)
    await settle(res, outcome, answer_at=answer_at)
    return Sent(outcome, result=got)

