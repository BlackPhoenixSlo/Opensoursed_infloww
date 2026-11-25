from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import account_health
import automation_executor as ax
from automation_registry import register
from ._common import bool_knob
from db.engine import get_session
from db.models import AutomationRule, PromoCampaign, PromoKeepState, ScheduledJob
import job_queue
import link_metrics
import of_pacing
import promo_create_guard
import runtime_switches
from isotime import parse_iso
from notifications_api import push_unread
from of_promos import fetch_of_promos, promo_type_body
from promo_create_guard import PREEMPT_SWITCH, Refused
from promo_keep_decide import (HOLD_REASONS, NOT_LISTED_S, TIMED_LEAD_S, AfterEnd, Created, Fill,
                               Inputs, Kept, Memo, Tally, Timed, TurnOff, Wait, decide,
                               end_on_our_clock, observe, preempt_applies, preempt_failure,
                               threshold)

log = logging.getLogger("of-relay.automation.promo_reactivate")

KIND = "promo_reactivate"
_DEFAULT_COOLDOWN_MIN = 2
_DEFAULT_INTERVAL_S = 3600
RECHECK = "_recheck"
_RETRIES = "_expiry_retries"
NEAR_CAP_S = 90
EXPIRY_GRACE_S = 30
EXPIRY_RETRY_S = 60
EXPIRY_MAX_RETRIES = 3
COOLDOWN_GRACE_S = 5
TIMED_GRACE_S = 5
GATE_STALE_S = 600
FIRST_READ_S = 10
MOVE_MIN_S = 30


def _preempts(r: PromoCampaign | None, cap: int) -> bool:
    return r is not None and preempt_applies(runtime_switches.on(PREEMPT_SWITCH), bool(r.preempt), cap)


@dataclass(frozen=True)
class _Gate:
    claims: int
    trigger: int | None
    read_mono: float
    ends_at: datetime | None


_gate: dict[str, _Gate] = {}
_toasts: dict[str, list[float]] = {}


def _set_gate(account_id: str, p: dict | None, r: PromoCampaign | None, read_mono: float) -> None:
    aid = str(account_id)
    if p is None or not p.get("claims_present"):
        _gate.pop(aid, None)
        return
    cap = int(p.get("subscribe_counts") or 0)
    trigger = threshold(cap) if _preempts(r, cap) else (cap or None)
    _gate[aid] = _Gate(int(p.get("subscriber_count") or 0), trigger, read_mono,
                       parse_iso(p.get("finished_at")))


def _hold_gate(account_id: str, read_mono: float) -> None:
    _gate[str(account_id)] = _Gate(0, None, read_mono, None)


def should_poke(account_id: str, n_toasts: int) -> bool:
    aid, now = str(account_id), time.monotonic()
    g = _gate.get(aid)
    if g is None or now - g.read_mono > GATE_STALE_S:
        _toasts.pop(aid, None)
        return True
    seen = [t for t in _toasts.get(aid, ()) if t >= g.read_mono] + [now] * max(int(n_toasts), 0)
    _toasts[aid] = seen
    if g.ends_at is not None and g.ends_at - datetime.utcnow() <= timedelta(seconds=GATE_STALE_S):
        return True
    return g.trigger is not None and g.claims + len(seen) >= g.trigger - 1


# 0 is meaningful to OF (subscribe_counts: unlimited claims; subscribe_days: a percent discount), so only None takes the default.
def _kept(value: int | None, default: int) -> int:
    return default if value is None else int(value)


async def _queue_recheck(account_id: str, payload: dict, reason: str, at: datetime,
                         retries: int = 0, *, rule_id: int | None = None) -> dict | None:
    knobs = {k: v for k, v in payload.items()
             if k not in (RECHECK, _RETRIES, job_queue.FOLLOWUP_MARK)}
    body = {**knobs, RECHECK: reason, _RETRIES: retries}
    rid = job_queue.current_rule_id() if rule_id is None else rule_id
    aid = str(account_id)
    async with get_session() as s:
        # Writes first: the transaction holds SQLite's write lock before it reads.
        await s.execute(sqlite_insert(PromoKeepState).values(account_id=aid)
                        .on_conflict_do_nothing(index_elements=["account_id"]))
        owner_live = exists().where(ScheduledJob.id == PromoKeepState.recheck_job_id,
                                    ScheduledJob.status.in_(("pending", "running")))
        claimed = (await s.execute(
            update(PromoKeepState)
            .where(PromoKeepState.account_id == aid,
                   or_(PromoKeepState.recheck_at.is_(None), ~owner_live))
            .values(recheck_at=at, recheck_job_id=None))).rowcount == 1
        if not claimed:
            return await _move_earlier(s, aid, reason, at, retries)
        if rid is not None:
            if not await job_queue.rule_is_live(s, rid):
                await s.rollback()
                log.info("promo_reactivate re-check dropped, rule off account=%s rule=%s", aid, rid)
                return None
            body[job_queue.FOLLOWUP_MARK] = True
        jid = await job_queue.enqueue_job(aid, KIND, payload=body, run_at=at, rule_id=rid, session=s)
        await s.execute(update(PromoKeepState).where(PromoKeepState.account_id == aid)
                        .values(recheck_job_id=jid))
    log.info("promo_reactivate re-check queued account=%s reason=%s at=%s retries=%s",
             account_id, reason, at.isoformat(), retries)
    return {"reason": reason, "at": at.isoformat(), "retries": retries}


async def _move_earlier(s, aid: str, reason: str, at: datetime, retries: int) -> dict | None:
    st = await s.get(PromoKeepState, aid)
    job = None if st is None or st.recheck_job_id is None else await s.get(ScheduledJob, st.recheck_job_id)
    if (job is None or job.status != "pending" or job.run_at is None
            or job.run_at <= at + timedelta(seconds=MOVE_MIN_S)):
        return None
    try:
        old = json.loads(job.payload_json or "{}")
    except (TypeError, ValueError):
        old = None
    if not isinstance(old, dict):
        return None
    body = json.dumps({**old, RECHECK: reason, _RETRIES: retries}, default=str)
    moved = (await s.execute(update(ScheduledJob)
                             .where(ScheduledJob.id == job.id, ScheduledJob.status == "pending",
                                    ScheduledJob.run_at == job.run_at)
                             .values(run_at=at, payload_json=body))).rowcount == 1
    if not moved:
        return None
    await s.execute(update(PromoKeepState).where(PromoKeepState.account_id == aid,
                                                PromoKeepState.recheck_job_id == job.id)
                    .values(recheck_at=at))
    log.info("promo_reactivate re-check moved earlier account=%s job=%s reason=%s at=%s",
             aid, job.id, reason, at.isoformat())
    return {"reason": reason, "at": at.isoformat(), "retries": retries}


async def queue_first_read(account_id: str, payload: dict | None = None) -> dict | None:
    rid = None
    if payload is None:
        async with get_session() as s:
            rule = (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id == str(account_id), AutomationRule.kind == KIND,
                AutomationRule.is_enabled.is_(True)).order_by(AutomationRule.id).limit(1))).scalar_one_or_none()
        if rule is None:
            return None
        try:
            payload = json.loads(rule.steps_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        payload, rid = payload if isinstance(payload, dict) else {}, rule.id
    if bool_knob(payload, "dry_run", True):
        return None
    return await _queue_recheck(account_id, payload, "first_read",
                                datetime.utcnow() + timedelta(seconds=FIRST_READ_S), rule_id=rid)


async def _observe(account_id: str, live: list[dict] | None, kept_ids: set[int],
                   now: datetime, *, persist: bool = True) -> tuple[Memo, Memo, int | None]:
    aid = str(account_id)
    async with get_session() as s:
        if persist:
            await s.execute(sqlite_insert(PromoKeepState).values(account_id=aid)
                            .on_conflict_do_nothing(index_elements=["account_id"]))
        st = await s.get(PromoKeepState, aid)
        memo = Memo() if st is None else Memo(st.kept_of_promo_id, st.first_claims,
                                              st.last_claims, st.read_at, st.finished_at)
        skew = None if st is None else st.skew_s
        new = observe(memo, live, kept_ids, now)
        if persist and new != memo:
            await s.execute(update(PromoKeepState).where(PromoKeepState.account_id == aid).values(
                kept_of_promo_id=new.kept_of_promo_id, first_claims=new.first_claims,
                last_claims=new.last_claims, read_at=new.read_at, finished_at=new.finished_at))
    return memo, new, skew


async def _note_wait(account_id: str, why: str | None) -> None:
    async with get_session() as s:
        await s.execute(update(PromoKeepState).where(
            PromoKeepState.account_id == str(account_id),
            PromoKeepState.wait_reason.is_distinct_from(why)).values(wait_reason=why))


async def _managed(account_id: str) -> list[PromoCampaign]:
    async with get_session() as s:
        return list((await s.execute(select(PromoCampaign).where(
            PromoCampaign.account_id == str(account_id),
            PromoCampaign.auto_reactivate.is_(True)))).scalars())


def _here(managed: list[PromoCampaign]) -> list[PromoCampaign]:
    return [r for r in managed if not promo_create_guard.fenced(r.keep_host_id)
            and not promo_create_guard.trial_unlimited(r)]


async def _limit_needed(account_id: str, managed: list[PromoCampaign]) -> list[int]:
    bad = [r.id for r in managed if not promo_create_guard.fenced(r.keep_host_id)
           and promo_create_guard.trial_unlimited(r)]
    if bad:
        now = datetime.utcnow()
        filed: list[str] = []
        async with get_session() as s:
            for cid in bad:
                filed += await promo_create_guard.turn_off(s, account_id, cid, "limit_needed", now)
        await push_unread(filed)
    return bad


async def _owned_ids(account_id: str, managed: list[PromoCampaign], live: list[dict] | None) -> frozenset[int]:
    if not live or not any(p.get("cap_inferred") for p in live):
        return frozenset()
    mine = {r.id for r in managed}
    past = await link_metrics.past_promo_ids(account_id)
    ids = {o for cid in mine for o in past.get(cid, ())}
    ids |= await promo_create_guard.replaced_ids(account_id, mine)
    return frozenset(ids)


async def _interval_s() -> float:
    rid = job_queue.current_rule_id()
    if rid is None:
        return _DEFAULT_INTERVAL_S
    async with get_session() as s:
        rule = await s.get(AutomationRule, rid)
    try:
        every = json.loads(rule.trigger_json or "{}").get("every_seconds") if rule else None
    except (TypeError, ValueError):
        every = None
    if isinstance(every, (int, float)) and not isinstance(every, bool) and every > 0:
        return float(every)
    return _DEFAULT_INTERVAL_S


async def _recovery(account_id: str, payload: dict, campaign_id: int) -> dict | None:
    _gate.pop(str(account_id), None)
    async with get_session() as s:
        c = await s.get(PromoCampaign, campaign_id)
    if c is None or not c.auto_reactivate:
        return None
    now = datetime.utcnow()
    nb = (await promo_create_guard.budget_state(account_id, now)).not_before
    at = max(nb or now, now) + timedelta(seconds=COOLDOWN_GRACE_S)
    if at >= now + timedelta(seconds=await _interval_s()):
        return None
    return await _queue_recheck(account_id, payload, "recovery", at)


async def _live_followup(account_id: str, payload: dict, kept: PromoCampaign | None,
                         live: dict, now: datetime, skew: int | None) -> dict | None:
    if kept is None:
        return None
    again = payload.get(RECHECK)
    plans: list[tuple[datetime, str, int]] = []
    cap, claims = int(live.get("subscribe_counts") or 0), int(live.get("subscriber_count") or 0)
    if not again and cap > 0 and claims >= cap - 1:
        plans.append((now + timedelta(seconds=NEAR_CAP_S), "near_cap", 0))
    exp = kept.expires_at
    # Only OF's own end time on a known clock can make a Timed create; a guessed expiry keeps its one expiry check.
    ours = end_on_our_clock(parse_iso(live.get("finished_at")), skew)
    if again != "timed" and ours is not None and _preempts(kept, cap):
        at = ours - timedelta(seconds=TIMED_LEAD_S - TIMED_GRACE_S)
        if now < at < now + timedelta(seconds=await _interval_s()):
            plans.append((at, "timed", 0))
    if exp is not None:
        if exp > now:
            if exp < now + timedelta(seconds=await _interval_s()):
                plans.append((exp + timedelta(seconds=EXPIRY_GRACE_S), "expiry", 0))
        elif again == "expiry":
            try:
                done = int(payload.get(_RETRIES) or 0)
            except (TypeError, ValueError):
                done = EXPIRY_MAX_RETRIES
            if done < EXPIRY_MAX_RETRIES:
                plans.append((now + timedelta(seconds=EXPIRY_RETRY_S), "expiry", done + 1))
    if not plans:
        return None
    at, reason, retries = min(plans, key=lambda p: p[0])
    return await _queue_recheck(account_id, payload, reason, at, retries)


@register("promo_reactivate")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    payload = payload or {}
    dry_run = bool_knob(payload, "dry_run", True)
    try:
        max_reactivations = int(payload.get("max_reactivations") or 0)
    except (TypeError, ValueError):
        max_reactivations = 0
    try:
        cooldown_min = int(payload.get("cooldown_minutes") or _DEFAULT_COOLDOWN_MIN)
    except (TypeError, ValueError):
        cooldown_min = _DEFAULT_COOLDOWN_MIN

    if payload.get(RECHECK):
        async with get_session() as s:
            # The slot's own job running frees it; another job's slot (claimed after its owner died) is not ours to clear.
            await s.execute(update(PromoKeepState)
                            .where(PromoKeepState.account_id == str(account_id),
                                   PromoKeepState.recheck_job_id == job_queue.current_job_id())
                            .values(recheck_at=None, recheck_job_id=None))
    async def stood_down(out: dict) -> dict:
        if not dry_run:
            await _note_wait(account_id, None)
        return out

    managed = await _managed(account_id)
    if not managed:
        return await stood_down({"managed": 0, "reactivated": 0, "dry_run": dry_run})
    off = [] if dry_run else await _limit_needed(account_id, managed)
    if off:
        managed = [r for r in managed if r.id not in off]
        if not managed:
            return await stood_down({"managed": 0, "reactivated": 0, "skipped": "limit_needed",
                                     "dry_run": dry_run})
    if not _here(managed):
        log.info("promo_reactivate fenced account=%s campaigns=%s", account_id, [r.id for r in managed])
        return await stood_down({"managed": len(managed), "reactivated": 0, "skipped": "fence",
                                 "dry_run": dry_run})
    managed = _here(managed)

    managed_ids = {int(r.of_promo_id) for r in managed if r.of_promo_id is not None}
    read_at, read_mono = datetime.utcnow(), time.monotonic()
    failed: list[Exception] = []
    # Pass managed ids so paging stops once located: /promotions holds the whole history (230+) and page 1 alone would read a live older promo as expired and re-create it.
    live = await of_pacing.walk(account_id, "promo_reactivate",
                                lambda: fetch_of_promos(account_id, need_ids=managed_ids,
                                                        raise_dead=True, on_error=failed.append))
    if not dry_run and await promo_create_guard.reconcile(account_id, live):
        managed = _here(await _managed(account_id))
        managed_ids = {int(r.of_promo_id) for r in managed if r.of_promo_id is not None}
        if not managed:
            return await stood_down({"managed": 0, "reactivated": 0, "dry_run": dry_run})
    shown = next((p for p in live or () if p.get("of_promo_id") in managed_ids and not p.get("is_finished")), None)
    _set_gate(account_id, shown, next((r for r in managed if shown and r.of_promo_id == shown["of_promo_id"]), None),
              read_mono)
    if live is None and failed and of_pacing.upstream(failed[-1])[0] == 401:
        _hold_gate(account_id, read_mono)
    # Still open (no unique candidate yet): a second create could duplicate it.
    if await promo_create_guard.has_open(account_id):
        return await stood_down({"managed": len(managed), "reactivated": 0, "skipped": "create_open",
                                 "dry_run": dry_run})
    now = datetime.utcnow()
    prior, memo, skew = await _observe(account_id, live, managed_ids, now, persist=not dry_run)
    budget = await promo_create_guard.budget_state(account_id, now)
    owned = await _owned_ids(account_id, managed, live)
    creates = await promo_create_guard.recent_creates(account_id)
    verdict = decide(Inputs(
        campaigns=tuple(Kept(r.id, r.of_promo_id, int(r.discount_percent or 0),
                             int(r.reactivate_count or 0), r.last_reactivated_at, r.keep_ticked_at,
                             bool(r.preempt))
                        for r in managed),
        promos=live, now=now, max_reactivations=max_reactivations, cooldown_min=cooldown_min,
        memo=memo, owned_ids=owned,
        creates=tuple(Created(c.campaign_id, c.settled_at, c.listed_at, c.claims_seen, c.first_claims)
                      for c in creates),
        auto_times=budget.auto_times, not_before=budget.not_before,
        preempt_enabled=runtime_switches.on(PREEMPT_SWITCH), prior=prior, skew_s=skew))

    if isinstance(verdict, Wait) and verdict.reason == "of_unreachable":
        log.info("promo_reactivate: OF unreachable account=%s — standing down", account_id)
        return await stood_down({"managed": len(managed), "reactivated": 0,
                                 "skipped": "of_unreachable", "dry_run": dry_run})
    if not dry_run:
        await _note_wait(account_id, verdict.wait_reason if isinstance(verdict, Wait) else None)
    if isinstance(verdict, Wait) and verdict.reason == "promo_already_live":
        out = {"managed": len(managed), "reactivated": 0,
               "skipped": "promo_already_live",
               "live_of_promo_id": verdict.live.get("of_promo_id"),
               "dry_run": dry_run}
        if verdict.wait_reason:
            out["wait_reason"] = verdict.wait_reason
        top = creates[0] if creates else None
        lag = (top.replaced_of_promo_id if top is not None
               and now < top.settled_at + timedelta(seconds=NOT_LISTED_S) else None)
        foreign = [p.get("of_promo_id") for p in live if not p.get("is_finished")
                   and p.get("of_promo_id") not in managed_ids and p.get("of_promo_id") != lag]
        if verdict.kept is not None and foreign:
            log.warning("promo_keep_second_live account=%s campaign=%s live=%s",
                        account_id, verdict.kept, [verdict.live.get("of_promo_id"), *foreign])
        if not dry_run:
            kept = next((r for r in managed if r.id == verdict.kept), None)
            recheck = await _live_followup(account_id, payload, kept, verdict.live, now, skew)
            if recheck:
                out["recheck"] = recheck
        return out
    if isinstance(verdict, Wait) and verdict.reason == "inferred_cap_untrusted":
        log.info("promo_reactivate: account=%s promo=%s full by count only, no trusted "
                 "claim history — waiting", account_id, verdict.live.get("of_promo_id"))
        return {"managed": len(managed), "reactivated": 0, "skipped": "inferred_cap_untrusted",
                "live_of_promo_id": verdict.live.get("of_promo_id"), "dry_run": dry_run}

    if isinstance(verdict, TurnOff):
        out = {"managed": len(managed), "reactivated": 0, "skipped": verdict.reason, "dry_run": dry_run}
        if not dry_run:
            async with get_session() as s:
                filed = await promo_create_guard.turn_off(s, account_id, verdict.campaign_id,
                                                          verdict.reason, now)
            await push_unread(filed)
            out["turned_off"] = verdict.campaign_id
        return out

    pre = isinstance(verdict, (Fill, Timed))
    tally = Tally() if pre else verdict.tally
    if tally.skipped_unverifiable:
        log.info("promo_reactivate: account=%s %s campaign(s) with no of_promo_id — cannot verify, "
                 "skipping", account_id, tally.skipped_unverifiable)
    base = {"managed": len(managed), **asdict(tally)}

    if isinstance(verdict, Wait):
        out = {**base, "reactivated": 0, "dry_run": dry_run}
        held = verdict.reason in HOLD_REASONS
        if held:
            out["skipped"] = verdict.reason
        if verdict.cooldown_ends and not dry_run:
            at = verdict.cooldown_ends + timedelta(seconds=COOLDOWN_GRACE_S)
            if at < now + timedelta(seconds=await _interval_s()):
                recheck = await _queue_recheck(account_id, payload,
                                               verdict.reason if held else "cooldown", at)
                if recheck:
                    out["recheck"] = recheck
        return out
    source = "auto_fill" if isinstance(verdict, Fill) else "auto_timed" if pre else "auto_ended"
    due = verdict.due if isinstance(verdict, AfterEnd) else (verdict.campaign_id,)
    if dry_run:
        rows = {r.id: r for r in managed}
        return {**base, "reactivated": 0, "dry_run": True,
                "would_reactivate": [{"id": rows[c].id, "name": rows[c].name,
                                      "discount": int(rows[c].discount_percent or 0)}
                                     for c in due],
                **({"source": source} if pre else {})}

    r = next(r for r in managed if r.id == verdict.campaign_id)
    done = {**base, "reactivated": 0, "errors": 0, "deferred": len(due) - 1, "dry_run": False}
    if pre:
        done["source"] = source
    client = await asyncio.to_thread(ax._make_client, account_id)
    terms = {"discount": int(r.discount_percent),
             "subscribe_counts": _kept(r.subscribe_counts, 1),
             "subscribe_days": _kept(r.subscribe_days, 30),
             "message": r.message or "",
             "type": promo_type_body(r.promo_type)}
    if r.finish_days is not None:
        terms["finish_days"] = int(r.finish_days)
    old = next((p for p in live if p.get("of_promo_id") == r.of_promo_id), None)
    same = memo.kept_of_promo_id == r.of_promo_id
    claims = (int(old["subscriber_count"]) if old is not None and old.get("claims_present")
              else memo.last_claims if same else None)
    still = {"auto_reactivate": True, "of_promo_id": r.of_promo_id}
    if pre:
        still["preempt"] = True
    timed_end = (end_on_our_clock(parse_iso(verdict.live.get("finished_at")), skew)
                 if isinstance(verdict, Timed) else None)
    res = await promo_create_guard.reserve(
        account_id, r.id, source, terms, still,
        [p["of_promo_id"] for p in live if p.get("of_promo_id") is not None], read_at,
        replaced_of_promo_id=r.of_promo_id, claims_seen=claims,
        first_claims=memo.first_claims if same else None,
        rule_id=job_queue.current_rule_id(), ticked_at=r.keep_ticked_at, timed_end=timed_end)
    if isinstance(res, Refused):
        log.info("promo_reactivate create refused account=%s campaign=%s reason=%s",
                 account_id, r.id, res.reason)
        return {**done, "skipped": res.reason}
    sent = await promo_create_guard.send(res, still, lambda: client, terms)
    outcome = sent.outcome
    if outcome is None:
        return {**done, "skipped": "not_sent"}
    if outcome.error_class == "session_dead":
        await account_health.mark_session_dead(account_id, account_health.is_session_dead_error(sent.error))
    if outcome.state != "created":
        out = {**done, "errors": int(outcome.state == "failed"), "create": outcome.state,
               "error_class": outcome.error_class}
        if pre and outcome.error_class != "not_sent":
            out["warning"] = "no_promo_may_be_live"
            if outcome.state == "failed" and preempt_failure(outcome.error_class, None)[2]:
                recheck = await _recovery(account_id, payload, r.id)
                if recheck:
                    out["recheck"] = recheck
        return out
    log.info("promo_reactivate re-armed account=%s campaign=%s new_of_id=%s cycle=%s source=%s",
             account_id, r.id, outcome.item.get("of_promo_id"), int(r.reactivate_count or 0) + 1, source)
    _set_gate(account_id, None if outcome.item.get("is_finished") else outcome.item, r,
              time.monotonic())
    out = {**done, "reactivated": 1}
    recheck = await queue_first_read(account_id, payload)
    if recheck:
        out["recheck"] = recheck
    return out
