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
(`_recheck` follow-ups, never more than one pending per account):
  near_cap  the live kept promo is one claim from its cap: look again in 90 s
            (OF may count the claim after the toast). Not from a re-check run.
  expiry    the live kept promo's expires_at falls before the next backstop:
            look at expires_at + 30 s. OF still saying it is on offer past that
            wins (no create): look again in 60 s, at most 3 times.
  cooldown  a campaign is held by the cooldown and nothing was re-armed: look
            at last_reactivated_at + cooldown + 5 s.
None in dry run (it never acts, so nothing is owed a timely look).

Safety — every unknown is read as "leave it alone", never as "re-create it":
  • Fails CLOSED when OF is unreachable — a failed fetch must never be read as
    "the promo is gone", which would create a duplicate live promo every tick.
  • Fails CLOSED on a campaign with no `of_promo_id` — without it we can't look
    the promo up, so we can't tell "finished" from "still live".
  • A campaign with no usable discount (1-100) is skipped: OF rejects the create
    and we'd burn a call per tick.
  • Deleting a campaign in the UI removes its mirror row, so it stops re-arming.
  • A filled claim cap is ended (of_promos.normalise_of_promo), so the next
    promo goes up as the last claim lands; 0 = unlimited, never filled.

Self-registers via @register("promo_reactivate"); scheduled by an
automation_rules row (kind="promo_reactivate", trigger_json={"every_seconds": N}).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

import automation_executor as ax
from automation_registry import kind_family, register
from ._common import bool_knob
from db.engine import get_session
from db.models import AutomationRule, PromoCampaign, ScheduledJob
import job_queue
import of_pacing
from of_promos import (extract_created_promo, fetch_of_promos, normalise_of_promo,
                       promo_expires_at, promo_type_body)

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


async def _recheck_pending(account_id: str) -> bool:
    """A re-check of this account is already queued (the dedupe: never two)."""
    async with get_session() as s:
        return (await s.execute(
            select(ScheduledJob.id).where(
                ScheduledJob.account_id == str(account_id),
                ScheduledJob.kind.in_(kind_family(KIND)),
                ScheduledJob.status == "pending",
                ScheduledJob.payload_json.contains(f'"{RECHECK}"', autoescape=True),
            ).limit(1))).scalar_one_or_none() is not None


async def _queue_recheck(account_id: str, payload: dict, reason: str, at: datetime,
                         retries: int = 0) -> dict | None:
    """Queue ONE re-check run at `at` (rule-bound through enqueue_followup, so turning
    the rule off drops it), unless one is pending. The run's own knobs ride along."""
    if await _recheck_pending(account_id):
        return None
    knobs = {k: v for k, v in payload.items()
             if k not in (RECHECK, _RETRIES, job_queue.FOLLOWUP_MARK)}
    job_id = await ax.enqueue_followup(
        account_id, KIND, run_at=at,
        payload={**knobs, RECHECK: reason, _RETRIES: retries})
    if job_id is None:
        return None
    log.info("promo_reactivate re-check queued account=%s reason=%s at=%s retries=%s",
             account_id, reason, at.isoformat(), retries)
    return {"reason": reason, "at": at.isoformat(), "retries": retries}


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


async def _live_followup(account_id: str, payload: dict, kept: PromoCampaign | None,
                         live: dict, now: datetime) -> dict | None:
    """The stand-down's re-check, when the live promo is a kept campaign's own (`kept`):
    the earliest of near_cap / expiry. None when nothing is owed or one is pending."""
    if kept is None:
        return None
    again = payload.get(RECHECK)
    plans: list[tuple[datetime, str, int]] = []
    cap, claims = int(live.get("subscribe_counts") or 0), int(live.get("subscriber_count") or 0)
    if not again and cap > 0 and claims >= cap - 1:
        plans.append((now + timedelta(seconds=NEAR_CAP_S), "near_cap", 0))
    exp = kept.expires_at
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

    async with get_session() as s:
        managed = (await s.execute(
            select(PromoCampaign).where(
                PromoCampaign.account_id == str(account_id),
                PromoCampaign.auto_reactivate.is_(True),
            )
        )).scalars().all()
    if not managed:
        return {"managed": 0, "reactivated": 0, "dry_run": dry_run}

    # Fail CLOSED: if we can't read OF, we cannot tell "finished" from
    # "unreachable" — re-creating on a failed fetch would duplicate live promos.
    # Pass the ids we manage so paging stops as soon as they're all located:
    # /promotions holds the creator's whole promo history (230+ on a real
    # account) and page 1 alone would show an older-but-LIVE promo as absent,
    # i.e. "expired", i.e. re-create it.
    managed_ids = {int(r.of_promo_id) for r in managed if r.of_promo_id is not None}
    # A background walk (of_pacing): paging to an older managed promo can take pages.
    live = await of_pacing.walk(account_id, "promo_reactivate",
                                lambda: fetch_of_promos(account_id, need_ids=managed_ids))
    if live is None:
        log.info("promo_reactivate: OF unreachable account=%s — standing down", account_id)
        return {"managed": len(managed), "reactivated": 0,
                "skipped": "of_unreachable", "dry_run": dry_run}

    # OnlyFans runs ONE subscription promo at a time — creating a new one flips
    # the current one to isFinished. So a campaign can be "finished" because it
    # was SUPERSEDED by a sibling, not because it lapsed. With two armed
    # campaigns that produced a ping-pong: re-arming A finished B, so next tick
    # B looked expired and was re-armed, which finished A... a real promo minted
    # on the creator's public profile every tick, forever.
    #
    # The invariant that kills it: if any promo is live, a discount IS on offer
    # and there is nothing to restore. Stand down. (/promotions is newest-first,
    # so a live promo is always on the first page we fetch.)
    live_now = [p for p in live if not p.get("is_finished")]
    if live_now:
        by_id = {int(r.of_promo_id): r for r in managed if r.of_promo_id is not None}
        shown = next((p for p in live_now if p.get("of_promo_id") in by_id), live_now[0])
        out = {"managed": len(managed), "reactivated": 0,
               "skipped": "promo_already_live",
               "live_of_promo_id": shown.get("of_promo_id"),
               "dry_run": dry_run}
        if not dry_run:
            recheck = await _live_followup(account_id, payload, by_id.get(shown.get("of_promo_id")),
                                           shown, datetime.utcnow())
            if recheck:
                out["recheck"] = recheck
        return out

    # Past this point NOTHING is on offer — the return above is the single home of
    # the liveness question, so a campaign's own OF row can only be finished (or
    # gone from history entirely). Both mean the same thing here: re-arm it. There
    # is deliberately no per-campaign "still active?" re-check; it could only ever
    # be false, and having one invited two rival notions of "active".
    now = datetime.utcnow()
    due: list[PromoCampaign] = []
    skipped_cap = skipped_cooldown = skipped_no_discount = 0
    skipped_unverifiable = 0
    held: list[datetime] = []          # last_reactivated_at of each campaign the cooldown holds

    for r in managed:
        disc = int(r.discount_percent or 0)
        if not (1 <= disc <= 100):
            skipped_no_discount += 1
            continue
        if max_reactivations and int(r.reactivate_count or 0) >= max_reactivations:
            skipped_cap += 1
            continue
        if r.last_reactivated_at and (now - r.last_reactivated_at) < timedelta(minutes=cooldown_min):
            skipped_cooldown += 1
            held.append(r.last_reactivated_at)
            continue
        if r.of_promo_id is None:
            # No OF id → we cannot tell "finished" from "still live", so
            # re-creating would mint a DUPLICATE promo every cycle (and the new
            # id may not be captured either, so it would never converge). Same
            # fail-closed rule as an unreachable fetch.
            skipped_unverifiable += 1
            log.info("promo_reactivate: campaign=%s has no of_promo_id — cannot verify, skipping", r.id)
            continue
        due.append(r)

    base = {"managed": len(managed), "due": len(due),
            "skipped_cap": skipped_cap, "skipped_cooldown": skipped_cooldown,
            "skipped_no_discount": skipped_no_discount,
            "skipped_unverifiable": skipped_unverifiable}

    if not due:
        out = {**base, "reactivated": 0, "dry_run": dry_run}
        if held and not dry_run:
            # Held only by the cooldown: look again just past it, not at the backstop.
            at = min(held) + timedelta(minutes=cooldown_min, seconds=COOLDOWN_GRACE_S)
            recheck = await _queue_recheck(account_id, payload, "cooldown", at)
            if recheck:
                out["recheck"] = recheck
        return out
    if dry_run:
        return {**base, "reactivated": 0, "dry_run": True,
                "would_reactivate": [{"id": r.id, "name": r.name,
                                      "discount": int(r.discount_percent or 0)} for r in due]}

    client = await asyncio.to_thread(ax._make_client, account_id)
    reactivated = errors = 0
    # At most ONE re-arm per run: OF only holds one live promo, so re-arming a
    # second here would immediately finish the one we just created.
    for r in due[:1]:
        # The offer expiration goes back too (sent only when one was: None = never sent).
        extra = {} if r.finish_days is None else {"finish_days": int(r.finish_days)}
        try:
            res = await asyncio.to_thread(
                lambda rr=r: client.create_promo(
                    discount=int(rr.discount_percent),
                    subscribe_counts=_kept(rr.subscribe_counts, 1),
                    subscribe_days=_kept(rr.subscribe_days, 30),
                    message=rr.message or "",
                    # "all,expired" (both audiences) goes back as OF's list.
                    type=promo_type_body(rr.promo_type), **extra),
            )
        except Exception:
            errors += 1
            log.warning("promo_reactivate create failed account=%s campaign=%s",
                        account_id, r.id, exc_info=True)
            continue
        of = normalise_of_promo(extract_created_promo(res))
        new_id = of.get("of_promo_id")
        stamp = datetime.utcnow()
        async with get_session() as s:
            row = await s.get(PromoCampaign, r.id)
            if row is None:      # deleted mid-run → don't resurrect the mirror
                continue
            if row.of_promo_id and new_id is not None and new_id != row.of_promo_id:
                # Keep the finished OF promo under this campaign, so its claimers'
                # spend still counts toward the campaign's Revenue (link_metrics).
                from link_metrics import _meta_row
                (await _meta_row(s, account_id, "promo", int(row.of_promo_id))).campaign_id = row.id
            row.of_promo_id = new_id if new_id is not None else row.of_promo_id
            row.status = "active"
            row.subscriber_count = 0          # fresh promo, fresh claim count
            row.reactivate_count = int(row.reactivate_count or 0) + 1
            row.last_reactivated_at = stamp
            row.expires_at = promo_expires_at(of.get("finished_at"), row.finish_days, stamp)
        reactivated += 1
        log.info("promo_reactivate re-armed account=%s campaign=%s new_of_id=%s cycle=%s",
                 account_id, r.id, new_id, int(r.reactivate_count or 0) + 1)

    return {**base, "reactivated": reactivated, "errors": errors,
            "deferred": max(0, len(due) - 1), "dry_run": False}
