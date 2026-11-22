"""service/automations/promo_reactivate.py — Automation: promo_reactivate.

Keep a profile discount permanently on offer. OnlyFans promos END on their own —
the clock runs out or the claim cap fills, and OF flips the promo to
`isFinished`. This automation notices that and re-creates the SAME campaign
(same discount %, claim cap, duration, message), then repoints the mirror row at
the fresh OF promo. Net effect: an always-on offer that renews itself instead of
quietly lapsing.

Opt-in PER CAMPAIGN — only `promo_campaigns.auto_reactivate = 1` rows are
touched, so a one-off promo is never resurrected behind your back. Ticking
"Keep running" (promotions_api) also ensures this kind's rule (hourly,
dry_run false, cooldown 2); unticking the last armed campaign switches it off.

steps_json (per-run knobs):
  max_reactivations  cycle cap per campaign (0 = unlimited)
  cooldown_minutes   min gap between re-arms of the same campaign (default 2)
  dry_run            plan only, hit no OF endpoint (DEFAULT TRUE when omitted —
                     safe; only the rule the Keep running tick makes sets false)

Event-driven, not a faster poll. A run fires on the hourly backstop, on a
subscribe toast (event_transcoder pokes this kind; a poke under the floor is
deferred, not dropped), and on the bounded re-checks a run queues for itself
(`_recheck` follow-ups; one Re-check slot per Creator, `promo_keep_state.recheck_at` +
`recheck_job_id`, claimed by compare-and-set while no owning job is pending or running,
freed only by its own job, so never two pending; a pending owner due later than a new
look is moved earlier, never later):
  near_cap  the live kept promo is one claim from its cap: look again in 90 s
            (OF may count the claim after the toast). Not from a re-check run.
  expiry    the live kept promo's expires_at falls before the next backstop:
            look at expires_at + 30 s. OF still saying it is on offer past that
            wins (no create): look again in 60 s, at most 3 times.
  cooldown  a campaign is held by the cooldown and nothing was re-armed: look
            at last_reactivated_at + cooldown + 5 s.
  timed     Pre-emption applies and the live kept promo ends before the next
            backstop: look just inside TIMED_LEAD_S of OF's read finishedAt, on OF's
            clock (needs the skew known); a guessed expires_at only gets its expiry
            check. One-shot: never from a timed re-check.
  recovery  a sent Pre-emption failed (OF may have ended the live promo): look when
            its back-off ends, so After-end recovers before the backstop.
  first_read  a Kept create landed (automatic, or a Growth create with Keep running
            ticked): look FIRST_READ_S later, so the claim memo's first count of the new
            promo is taken before its claims arrive (a Trusted count needs a first read at
            0). One per create, never from its own run's plan.
None in dry run (it never acts, so nothing is owed a timely look).

Pre-emption (Slice B; PROMO_PREEMPT_ENABLED, the server's kill switch, and the campaign's
`preempt` tick; cap >= 10 only): while the Kept promo is live, re-create it at a Trusted
count of ceil(0.9 x cap) (Fill) or within TIMED_LEAD_S of OF's own end time read twice
unchanged, with our clock within 30 s of OF's (Timed), so the next promo is up before the
old one ends. Same reservation, guards, budget, cycle cap and Cooldown as After-end, plus a
recovery create left in both budget windows; a failed one warns "no promo may be live" and
After-end recovers after the back-off (an OF refusal also unticks `preempt`; only a captcha,
a deactivated Creator or a free page turn Keep running off). Why it waits instead is the
card's waiting line (wait_reason).

Toast gate (`should_poke`): a subscribe toast pokes this kind only when a run could be owed
(no fresh read of the live Kept promo, its count plus the toasts since near the threshold,
or its end near), so a busy Creator's toasts cost no list reads far from the threshold.
A read refused with an unclassified OF 401 backs the toasts off for GATE_STALE_S (`_hold_gate`).

Safety — every unknown is read as "leave it alone", never as "re-create it":
  • Fails CLOSED when OF is unreachable — a failed fetch must never be read as
    "the promo is gone", which would create a duplicate live promo every tick.
  • Fails CLOSED on a campaign with no `of_promo_id` — without it we can't look
    the promo up, so we can't tell "finished" from "still live".
  • A campaign with no usable discount (1-100) is skipped: OF rejects the create
    and we'd burn a call per tick.
  • Deleting a campaign in the UI removes its mirror row, so it stops re-arming.
  • A filled claim cap is ended (of_promos.normalise_of_promo), so the next
    promo goes up as the last claim lands; 0 = unlimited, never filled. While OF's
    own flags still say live, only for the Kept promo first read at 0 Claims whose
    count never went down (the claim memo, promo_keep_state); else wait. An earlier
    promo of the same campaign in that state is ended (Inflowwww replaced it); one OF
    still lists live is a second live promo: stand down.
  • Every create is a Create reservation (promo_create_guard, ADR-0040): reserved,
    flipped to sending right before the POST, settled after; an answer with no id is
    unknown, adopted only when a later read shows a unique matching promo. While a
    create is open no other starts; one never seen within UNKNOWN_OFF_S turns Keep
    running off (create_unknown).
  • Zero-claim breaker (promo_keep_decide): after a create, no next one until its
    promo is seen live or NOT_LISTED_S passes; 3 in a row with no new Claims or
    never live turn Keep running off (breaker). Each create and stop notifies the
    owners (promo_keep_running).
  • Create budget and back-off: at most 3 automatic creates per rolling hour, 8 per
    day; a failed one holds the next (doubling from 120 s, OF's Retry-After in full).
    A captcha, a free page, another 4xx or a second 403/429 in a row turn Keep running
    off; a dead session flags the account (run_once then skips it).
  • Host fence (ADR-0041): only the box whose PROMO_CREATE_HOST_ID is stamped on the
    campaign (at tick) re-creates it; a fenced campaign costs no OF read, so a DB copy or
    a box with the env unset never creates.
  • A Kept Free trial with no Offer limit (unlimited claims, trial_unlimited) costs no OF
    read either: the run turns it off once (limit_needed), with a notice. The Re-create
    limit is optional: none = re-created indefinitely (owner 2026-11-21).
  • An operator stop wins: the decision read's start, the claimed rule and the campaign's
    tick ride on the reservation; a create sent or settled after the read (Growth, the OF
    mirror), a fresh manual promo missing from the read, the rule gone/off/dry run, a new
    tick or a read over 90 s old refuse this one, at reserve and at the sending CAS.
  • Dry run never writes: no reconcile, no turn-off, no create.

Self-registers via @register("promo_reactivate"); scheduled by an
automation_rules row (kind="promo_reactivate", trigger_json={"every_seconds": N}).
"""
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
_DEFAULT_INTERVAL_S = 3600          # the backstop cadence when the run has no rule
RECHECK = "_recheck"                # payload key on this kind's own re-check jobs
_RETRIES = "_expiry_retries"
NEAR_CAP_S = 90                     # near_cap: look again after OF counts the claim
EXPIRY_GRACE_S = 30                 # expiry: look this long after expires_at
EXPIRY_RETRY_S = 60                 # ... and again while OF still says on offer
EXPIRY_MAX_RETRIES = 3
COOLDOWN_GRACE_S = 5
TIMED_GRACE_S = 5                   # timed: land inside the lead, not on its edge
GATE_STALE_S = 600                  # toast gate: an older read, or an end this near, pokes
FIRST_READ_S = 10                   # first_read: the new Kept promo's first count, before claims
MOVE_MIN_S = 30                     # a held Re-check slot's job moves earlier only by more than this


def _preempts(r: PromoCampaign | None, cap: int) -> bool:
    """Pre-emption applies to this Kept campaign's promo of this cap."""
    return r is not None and preempt_applies(runtime_switches.on(PREEMPT_SWITCH), bool(r.preempt), cap)


@dataclass(frozen=True)
class _Gate:
    """The toast gate's copy of the last read of the live Kept promo."""
    claims: int
    trigger: int | None     # Claims at which a run is owed (threshold, else cap); None: never
    read_mono: float        # monotonic, at the read's start: later toasts are not in `claims`
    ends_at: datetime | None


# In-process on purpose: a restart empties both, and no entry means every toast pokes.
_gate: dict[str, _Gate] = {}
_toasts: dict[str, list[float]] = {}


def _set_gate(account_id: str, p: dict | None, r: PromoCampaign | None, read_mono: float) -> None:
    """After a read (or a create's answer): `p` the live Kept promo, None when not known live."""
    aid = str(account_id)
    if p is None or not p.get("claims_present"):
        _gate.pop(aid, None)
        return
    cap = int(p.get("subscribe_counts") or 0)
    trigger = threshold(cap) if _preempts(r, cap) else (cap or None)
    _gate[aid] = _Gate(int(p.get("subscriber_count") or 0), trigger, read_mono,
                       parse_iso(p.get("finished_at")))


def _hold_gate(account_id: str, read_mono: float) -> None:
    """The read met an OF 401 the strict dead-session classifier does not name: backed off,
    never parked, as the purchase poll treats it (purchase_notifications.feed_outcome
    `unauthorized`). Toasts poke nothing for GATE_STALE_S; the backstop and Re-checks still
    run (W30 F27)."""
    _gate[str(account_id)] = _Gate(0, None, read_mono, None)


def should_poke(account_id: str, n_toasts: int) -> bool:
    """Do `n_toasts` subscribe toasts owe this kind a run? Sync and in-memory (the
    transcoder's hot path). Yes with no fresh read of the live Kept promo, when its end is
    near, or when its last Claims plus the toasts since that read reach one short of the
    trigger (OF may count a claim after its toast, like near_cap). With no fresh read the
    Creator's toasts are dropped, not kept: only toasts after the next read count, so the
    history never grows while the gate is stale (rule off, fenced)."""
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


def _kept(value: int | None, default: int) -> int:
    """The campaign's own number, defaulting ONLY when it was never recorded.

    Both count knobs have a meaningful ZERO, so `int(value or default)` is
    wrong on each: `subscribe_counts=0` is OF's UNLIMITED claims (promotions_api
    dropped a max(1,...) floor precisely to make that reachable), and
    `subscribe_days=0` is what OF itself stores for a percent discount. Reading
    either 0 as "unset" re-arms an always-on offer as a one-shot — a different
    campaign than the one the operator ticked "keep running".
    """
    return default if value is None else int(value)


async def _queue_recheck(account_id: str, payload: dict, reason: str, at: datetime,
                         retries: int = 0, *, rule_id: int | None = None) -> dict | None:
    """Queue ONE re-check run at `at`, unless the Creator's Re-check slot is taken.

    The slot is `promo_keep_state.recheck_at` + `recheck_job_id`, claimed by a
    compare-and-set (racing runs: one wins) while its owning job is not pending or running
    (a done, failed or cancelled owner frees it at once; boot heals orphaned running jobs).
    The job is inserted in the same transaction, rule-bound like enqueue_followup: a rule
    turned off mid-run rolls the claim back. The run's own knobs ride along. `rule_id`: the
    rule to bind when queued outside a run (a manual create); else the run's own.
    A slot whose owner is pending but due over MOVE_MIN_S after `at` is moved, not skipped: that same job
    (its rule and knobs) runs at `at` for `reason` instead, so a far Timed/expiry look never
    delays a recovery or first read. Still one job; never moved later. The run it makes
    plans the next look again."""
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
    """`_queue_recheck`'s taken slot, in its transaction (the write lock held): the owner job
    still pending and due over MOVE_MIN_S after `at` becomes this re-check at `at` (racing
    runs planning the same look a moment apart leave it alone). `at` is in the future, so
    the job is not due and no worker holds it; the CAS on status/run_at settles any race."""
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
    """A Kept create landed: one first_read Re-check FIRST_READ_S out. `payload` None (a
    Growth create, outside any run): the Creator's enabled rule's knobs and id; none, or a
    dry run, queues nothing (a dry run never writes the memo)."""
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
    """Fold this read into the Creator's claim memo (promo_keep_state) and persist it, so
    a restart keeps the history an inferred cap and Pre-emption need (not in dry run: it
    writes nothing). Returns the committed memo before and after this read, and skew_s.
    One transaction, the write first: it holds SQLite's write lock before the read, so a
    racing fold waits and folds onto this one (a drop it saw is never written over)."""
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
    """The card's waiting line (keep_wait): why the live Kept promo is not pre-empted."""
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
    """The Kept campaigns this box may re-create (Host fence; a Free trial with no Offer
    limit never is)."""
    return [r for r in managed if not promo_create_guard.fenced(r.keep_host_id)
            and not promo_create_guard.trial_unlimited(r)]


async def _limit_needed(account_id: str, managed: list[PromoCampaign]) -> list[int]:
    """Turn off, once, this box's Kept Free trials with no Offer limit (unlimited claims):
    they would idle silently. Returns the campaign ids."""
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
    """Earlier OF promos of the Kept campaigns (their past ids, the ids their reservations
    replaced): one still listed full by count only is ended, never a reason to wait. Read
    only when the list holds such a promo."""
    if not live or not any(p.get("cap_inferred") for p in live):
        return frozenset()
    mine = {r.id for r in managed}
    past = await link_metrics.past_promo_ids(account_id)
    ids = {o for cid in mine for o in past.get(cid, ())}
    ids |= await promo_create_guard.replaced_ids(account_id, mine)
    return frozenset(ids)


async def _interval_s() -> float:
    """The run's rule cadence (seconds), else the hourly default."""
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
    """A sent Pre-emption failed: OF may have ended the live promo. Forget the toast gate's
    copy of it (toasts poke again) and, while Keep running is on, look once the back-off
    ends through the Re-check slot, so After-end recovers before the backstop."""
    _gate.pop(str(account_id), None)
    async with get_session() as s:
        c = await s.get(PromoCampaign, campaign_id)
    if c is None or not c.auto_reactivate:
        return None
    now = datetime.utcnow()
    nb = (await promo_create_guard.budget_state(account_id, now)).not_before
    at = max(nb or now, now) + timedelta(seconds=COOLDOWN_GRACE_S)
    if at >= now + timedelta(seconds=await _interval_s()):
        return None                 # the backstop's
    return await _queue_recheck(account_id, payload, "recovery", at)


async def _live_followup(account_id: str, payload: dict, kept: PromoCampaign | None,
                         live: dict, now: datetime, skew: int | None) -> dict | None:
    """The stand-down's re-check, when the live promo is a kept campaign's own (`kept`):
    the earliest of near_cap / timed / expiry. None when nothing is owed or one is pending."""
    if kept is None:
        return None
    again = payload.get(RECHECK)
    plans: list[tuple[datetime, str, int]] = []
    cap, claims = int(live.get("subscribe_counts") or 0), int(live.get("subscriber_count") or 0)
    if not again and cap > 0 and claims >= cap - 1:
        plans.append((now + timedelta(seconds=NEAR_CAP_S), "near_cap", 0))
    exp = kept.expires_at
    # Only OF's own end time on a known clock can make a Timed create: a guessed expiry
    # keeps its one expiry check. OF's end reaches our clock at end + skew.
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
            # The expiry re-check found it still on offer past our expires_at (often
            # only our created + finish_days guess): OF wins, no create. Look again
            # in 60 s, at most EXPIRY_MAX_RETRIES times; then the backstop has it.
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
    # SAFE by default INCLUDING for a stored `null` — see _common.bool_knob.
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
            # The slot's own job running frees it so this run may plan the next; another
            # job's slot (claimed after this one's owner died) is not ours to clear.
            await s.execute(update(PromoKeepState)
                            .where(PromoKeepState.account_id == str(account_id),
                                   PromoKeepState.recheck_job_id == job_queue.current_job_id())
                            .values(recheck_at=None, recheck_job_id=None))
    async def stood_down(out: dict) -> dict:
        """A return before any verdict: the card's waiting line no longer holds (dry run: no write)."""
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
        # Before any OF read: a fenced box spends nothing on Keep running.
        log.info("promo_reactivate fenced account=%s campaigns=%s", account_id, [r.id for r in managed])
        return await stood_down({"managed": len(managed), "reactivated": 0, "skipped": "fence",
                                 "dry_run": dry_run})
    managed = _here(managed)

    # Pass the ids we manage so paging stops as soon as they're all located:
    # /promotions holds the creator's whole promo history (230+ on a real
    # account) and page 1 alone would show an older-but-LIVE promo as absent,
    # i.e. "expired", i.e. re-create it.
    managed_ids = {int(r.of_promo_id) for r in managed if r.of_promo_id is not None}
    # Before the read: any create sent or settled after this instant (a manual one
    # mid-walk) beats this run's (newer_create).
    read_at, read_mono = datetime.utcnow(), time.monotonic()
    # A background walk (of_pacing): paging to an older managed promo can take pages. A dead
    # session raises: run_once marks the account and skips it until the session is back.
    failed: list[Exception] = []
    live = await of_pacing.walk(account_id, "promo_reactivate",
                                lambda: fetch_of_promos(account_id, need_ids=managed_ids,
                                                        raise_dead=True, on_error=failed.append))
    # Every read first settles an open create; one settled may have repointed a campaign.
    # Dry run writes nothing (a lost row would turn Keep running off).
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
    if await promo_create_guard.has_open(account_id):
        # Still open (no unique candidate yet): a second create could duplicate it. Natural
        # reads settle it; UNKNOWN_OFF_S after its send it is lost and Keep running stops.
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
        # OF may list the promo our newest create replaced as live for a while after it:
        # not alerted until NOT_LISTED_S past that settle (it still blocks any create).
        top = creates[0] if creates else None
        lag = (top.replaced_of_promo_id if top is not None
               and now < top.settled_at + timedelta(seconds=NOT_LISTED_S) else None)
        foreign = [p.get("of_promo_id") for p in live if not p.get("is_finished")
                   and p.get("of_promo_id") not in managed_ids and p.get("of_promo_id") != lag]
        if verdict.kept is not None and foreign:
            # OF should run one promo at a time: another live beside the Kept one is the
            # 4 h sweep's alert (promo_keep_creates), a replaced one of ours too.
            log.warning("promo_keep_second_live account=%s campaign=%s live=%s",
                        account_id, verdict.kept, [verdict.live.get("of_promo_id"), *foreign])
        if not dry_run:
            kept = next((r for r in managed if r.id == verdict.kept), None)
            recheck = await _live_followup(account_id, payload, kept, verdict.live, now, skew)
            if recheck:
                out["recheck"] = recheck
        return out
    if isinstance(verdict, Wait) and verdict.reason == "inferred_cap_untrusted":
        # Full only by our count while OF still offers it, and no clean history: OF
        # flipping a flag, or the backstop, decides; a create could end a live promo.
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
            # Held by the cooldown, the breaker hold, the back-off or the budget: look again
            # just past it, not at the backstop; a hold past the backstop is the backstop's.
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
             # "all,expired" (both audiences) goes back as OF's list.
             "type": promo_type_body(r.promo_type)}
    if r.finish_days is not None:
        # The offer expiration goes back too (sent only when one was: None = never sent).
        terms["finish_days"] = int(r.finish_days)
    # The replaced promo's Claims while Kept: the Zero-claim breaker's "gained" input.
    old = next((p for p in live if p.get("of_promo_id") == r.of_promo_id), None)
    same = memo.kept_of_promo_id == r.of_promo_id
    claims = (int(old["subscriber_count"]) if old is not None and old.get("claims_present")
              else memo.last_claims if same else None)
    still = {"auto_reactivate": True, "of_promo_id": r.of_promo_id}
    if pre:
        still["preempt"] = True     # the second tick, unticked since the read: no POST
    # Timed: OF's end on our clock, so the window is re-checked right before the POST.
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
        # Keep running stays on: run_once skips the account until the session is back.
        await account_health.mark_session_dead(account_id, account_health.is_session_dead_error(sent.error))
    if outcome.state != "created":
        # unknown: the next reads adopt it or, UNKNOWN_OFF_S on, call it lost.
        out = {**done, "errors": int(outcome.state == "failed"), "create": outcome.state,
               "error_class": outcome.error_class}
        if pre and outcome.error_class != "not_sent":
            out["warning"] = "no_promo_may_be_live"     # OF may have ended the old one anyway
            # The notice's own rule (recover never depends on the previous class).
            if outcome.state == "failed" and preempt_failure(outcome.error_class, None)[2]:
                recheck = await _recovery(account_id, payload, r.id)
                if recheck:
                    out["recheck"] = recheck
        return out
    log.info("promo_reactivate re-armed account=%s campaign=%s new_of_id=%s cycle=%s source=%s",
             account_id, r.id, outcome.item.get("of_promo_id"), int(r.reactivate_count or 0) + 1, source)
    # The new promo is the live Kept one: its answer seeds the toast gate until the next read.
    _set_gate(account_id, None if outcome.item.get("is_finished") else outcome.item, r,
              time.monotonic())
    out = {**done, "reactivated": 1}
    recheck = await queue_first_read(account_id, payload)
    if recheck:
        out["recheck"] = recheck
    return out
