"""service/automations/priority_mass.py — Smart Messages' Priority mass message.

Infloww's "Priority mass message" (`/message/smart-message/priority-mass-messages`,
06-growth-automations M4) sends ONE DIRECT MESSAGE PER FAN instead of OF's mass
message, so it lands in each fan's priority inbox: "about 300–700 fans per hour,
max 5,000 fans". Here it is a run (`priority_mass_runs`, made by
priority_mass_api) whose job legs walk its frozen recipient rows
(`priority_mass_recipients`) through the per-fan chat send.

  1. The first leg FREEZES the audience (claim-first). The posted OF lists are
     read off OF's own rosters (`audiences.resolve_recipients_blocking`, which
     fails closed: a truncated or unknown list stops the run, nothing is sent),
     the exclusions below drop fans, the first `MAX_RECIPIENTS` by fan id are
     inserted `pending` and the run turns `running`, in one transaction. A run
     cancelled while it resolved never turns running.
  2. Every leg sends to at most `_LEG` pending fans and queues the next leg, so
     a 5,000-fan run is a chain of short jobs that survives a restart: the
     executor requeues an interrupted job (boot reconcile, retry on failure)
     and the next leg picks up the rows still `pending`. A row is CLAIMED
     (`claimed`, committed) before its send; a leg that finds a claimed row left
     by a crash marks it `unknown` and never sends it again, because whether OF
     created that message cannot be known. A `sent` row is never touched again.

Exclusions, at the freeze and again for each fan right before his claim, under
his lease (a long run honours exclusions made after it started): the include-only audience (`filter_candidates`), the
hard skip list, the global blacklist, the contact guard (`contact_guard_excludes`:
messaged by us or nudged in the last 6h, or messaging us in the last 2h, the
mass default), the MASSdmEXCLUDE list, fans a queued
send is about to reach, and, priced, fans who already own the media
(`ownership.owners_of_media`). At send time: a muted creator, a fan paused longer
than `_PAUSED_SKIP` (quarantined), and the fan lease; a fan resting a shorter
while or leased by another automation waits for a later leg.

Pacing: every send is `of_write_paced(..., send_purpose="gated", tries=1)`, the
per-Creator 11 s OF write gap shared with every other automation, so a run
sends at most ~300 fans an hour (Infloww's upper 700/h is not reachable without
a shorter gap; owner question). OF's rate-limit refusal puts the fan back to
pending and the next leg waits `_DEFER_S`. The text gets the account's banned
words (block stops the run, mask masks), `{name}`, and the OF word restriction.
A vault id OF refuses stops the run (`error`): every later fan would fail too.
Another 4xx marks the fan `failed`; a timeout, dropped connection or 5xx may
have sent, so the fan turns `unknown`. A leg past `_LEG_BUDGET_S` stops early
and chains, so it never holds a bulk slot long. Each send writes the outbound
`messages` row (automation_kind "priority_mass", the launching Employee) and
rests the fan `_REST_S` (`start_fan_cooldown`, which creates a missing row).

  job payload: {"run_id": N}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

import automation_executor as ax        # _make_client / of_write_paced / lease seams
from attribution import write_outbound_attribution
from automation_registry import register
from automations._common import (
    apply_word_restriction, is_media_rejected_error, load_hard_skip_ids,
    quarantine_if_undeliverable, should_skip_muted_creator, skip_unreachable_fan,
    substitute_placeholders, template_fan_name,
)
from automations._wordfilter import banned_hit_summary, filter_banned, load_banned_words
from db.engine import get_session
from db.models import Blacklist, Fan, PriorityMassRecipient, PriorityMassRun, ScheduledJob

log = logging.getLogger("of-relay.automation.priority_mass")

KIND = "priority_mass"
MAX_RECIPIENTS = 5_000       # Infloww's cap
HOURLY_RATE = 300            # what the 11 s per-Creator write gap allows, rounded down
_SEND_PURPOSE = "gated"
_LEG = 10                    # fans per leg: ~2 min of paced sends, then the next job
_LEG_BUDGET_S = 180          # a leg slowed by the shared write gap stops here and chains
_DEFER_S = 60                # the next leg's wait after a rate limit or an all-deferred leg
_REST_S = 45                 # as lifecycle_messages: a short rest after a send
_PAUSED_SKIP = timedelta(minutes=15)   # paused longer than this = quarantined, skipped

# Run statuses.
RESOLVING, RUNNING, DONE, CANCELLED, ERROR = "resolving", "running", "done", "cancelled", "error"
LIVE = (RESOLVING, RUNNING)
# Recipient statuses.
PENDING, CLAIMED, SENT, SKIPPED, FAILED, UNKNOWN = (
    "pending", "claimed", "sent", "skipped", "failed", "unknown")


def leg_payload(run_id: int) -> str:
    """The leg job's payload as stored — one spelling, so a queued leg is found."""
    return json.dumps({"run_id": int(run_id)})


async def ensure_leg(account_id: str, run_id: int, *, delay_s: float = 0,
                     include_running: bool = False) -> bool:
    """Queue the run's next leg unless one is already queued (or, with
    `include_running`, running). True when one was queued."""
    statuses = ["pending", "running"] if include_running else ["pending"]
    async with get_session() as s:
        queued = (await s.execute(select(ScheduledJob.id).where(
            ScheduledJob.account_id == str(account_id), ScheduledJob.kind == KIND,
            ScheduledJob.status.in_(statuses),
            ScheduledJob.payload_json == leg_payload(run_id)).limit(1))).first()
        if queued is not None:
            return False
        # An operator started the run: every leg is the operator's (the
        # supervisor's operator tier, ADR 0025).
        run = await s.get(PriorityMassRun, int(run_id))
        await ax.enqueue_job(
            str(account_id), KIND, payload={"run_id": int(run_id)},
            run_at=datetime.utcnow() + timedelta(seconds=delay_s), session=s,
            created_by_employee_id=run.created_by_employee_id if run is not None else None)
    return True


def _ids(raw: str | None) -> list[int]:
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    out: list[int] = []
    for x in v if isinstance(v, list) else []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


async def _set_status(run_id: int, status: str, *, error: str | None = None,
                      only_from: tuple[str, ...] = LIVE) -> bool:
    """Move a live run to `status`; never overwrites a cancelled/finished one."""
    values: dict = {"status": status}
    if status not in LIVE:
        values["completed_at"] = datetime.utcnow()
    if error is not None:
        values["last_error"] = error[:500]
    async with get_session() as s:
        res = await s.execute(update(PriorityMassRun).where(
            PriorityMassRun.id == int(run_id),
            PriorityMassRun.status.in_(only_from)).values(**values))
    return bool(res.rowcount)


async def _status(run_id: int) -> str | None:
    async with get_session() as s:
        return (await s.execute(select(PriorityMassRun.status).where(
            PriorityMassRun.id == int(run_id)))).scalar_one_or_none()


async def _set_recipient(run_id: int, fan_id: int, status: str, *,
                         reason: str | None = None, message_id: int | None = None,
                         only_from: str | None = None) -> bool:
    q = update(PriorityMassRecipient).where(
        PriorityMassRecipient.run_id == int(run_id),
        PriorityMassRecipient.fan_id == int(fan_id))
    if only_from is not None:
        q = q.where(PriorityMassRecipient.status == only_from)
    async with get_session() as s:
        res = await s.execute(q.values(status=status, reason=reason, message_id=message_id,
                                       updated_at=datetime.utcnow()))
    return bool(res.rowcount)


# ── Exclusions ────────────────────────────────────────────────────────

async def exclusions(account_id: str, fan_ids: list[int], *, priced: bool,
                     media: list[int]) -> dict[int, str]:
    """{fan_id: reason} for the fans of `fan_ids` this run must not message now."""
    import audience_include as _audiences
    from audiences import (
        BROADCAST_DEFAULT_INBOUND_H, BROADCAST_DEFAULT_OUTBOUND_H, MASSDMEXCLUDE_LIST,
        contact_guard_excludes, exclude_list_fan_ids, pending_send_fan_ids,
    )
    from ownership import owners_of_media
    if not fan_ids:
        return {}
    kept = set(await _audiences.filter_candidates(account_id, fan_ids, kind=KIND))
    hard = await load_hard_skip_ids(account_id)
    async with get_session() as s:
        black = {int(x) for x in (await s.execute(
            select(Blacklist.fan_id).where(Blacklist.fan_id.in_(fan_ids)))).scalars()}
    opted_out = await exclude_list_fan_ids(account_id, MASSDMEXCLUDE_LIST)
    contacted = await contact_guard_excludes(
        account_id, outbound_hours=BROADCAST_DEFAULT_OUTBOUND_H,
        inbound_hours=BROADCAST_DEFAULT_INBOUND_H)
    queued = await pending_send_fan_ids(account_id)
    owners = await owners_of_media(account_id, media) if priced and media else set()
    out: dict[int, str] = {}
    for fid in fan_ids:
        reason = ("outside_audience" if fid not in kept
                  else "skip_list" if fid in hard
                  else "blacklisted" if fid in black
                  else "do_not_mass" if fid in opted_out
                  else "recently_contacted" if fid in contacted
                  else "queued_send" if fid in queued
                  else "owns_media" if fid in owners
                  else None)
        if reason:
            out[fid] = reason
    return out


# ── Leg 0: freeze the audience ────────────────────────────────────────

async def _freeze(run: PriorityMassRun) -> dict:
    from audiences import resolve_recipients_blocking
    aud = json.loads(run.audience_json or "{}")
    client = await asyncio.to_thread(ax._make_client, run.account_id)
    ids = await asyncio.to_thread(
        resolve_recipients_blocking, client,
        user_lists=list(aud.get("user_lists") or []),
        excluded_user_lists=list(aud.get("excluded_user_lists") or []))
    if ids is None:
        await _set_status(run.id, ERROR, error=(
            "the audience could not be read in full from OnlyFans; nothing was sent"))
        return {"status": "error", "reason": "audience_unresolved"}
    excl = await exclusions(run.account_id, ids, priced=run.price_cents > 0,
                            media=_ids(run.media_json))
    eligible = sorted(f for f in ids if f not in excl)
    claimed = eligible[:MAX_RECIPIENTS]
    now = datetime.utcnow()
    async with get_session() as s:
        res = await s.execute(update(PriorityMassRun).where(
            PriorityMassRun.id == run.id, PriorityMassRun.status == RESOLVING).values(
            status=RUNNING, resolved_count=len(ids), excluded_count=len(excl),
            capped_count=len(eligible) - len(claimed)))
        if not res.rowcount:        # cancelled while the rosters were read
            return {"status": "skipped", "reason": "not_resolving"}
        if claimed:
            await s.execute(PriorityMassRecipient.__table__.insert(), [
                {"run_id": run.id, "fan_id": f, "status": PENDING, "updated_at": now}
                for f in claimed])
    log.info("priority_mass froze run=%s account=%s resolved=%d excluded=%d claimed=%d",
             run.id, run.account_id, len(ids), len(excl), len(claimed))
    return {"resolved": len(ids), "excluded": len(excl), "claimed": len(claimed),
            "capped": len(eligible) - len(claimed)}


# ── A leg: send to the next pending fans ──────────────────────────────

def _refused(exc: Exception) -> bool:
    """OF answered with a 4xx: it refused, so it created nothing. Anything else
    (a timeout, a dropped connection, a 5xx) may have sent the message."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and 400 <= status < 500


async def _paused_until(account_id: str, fan_id: int) -> datetime | None:
    async with get_session() as s:
        return (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).scalar_one_or_none()


async def _defer(run_id: int, fan_id: int) -> None:
    """Leave the fan pending, at the back of the queue."""
    await _set_recipient(run_id, fan_id, PENDING, only_from=PENDING)


async def _leg(run: PriorityMassRun) -> dict:
    aid, rid = run.account_id, run.id
    async with get_session() as s:
        # A claim this leg did not make was left by a crash mid-send: unknown, never resent.
        stale = await s.execute(update(PriorityMassRecipient).where(
            PriorityMassRecipient.run_id == rid, PriorityMassRecipient.status == CLAIMED,
        ).values(status=UNKNOWN, reason="interrupted", updated_at=datetime.utcnow()))
        batch = list((await s.execute(select(PriorityMassRecipient.fan_id).where(
            PriorityMassRecipient.run_id == rid, PriorityMassRecipient.status == PENDING,
        ).order_by(PriorityMassRecipient.updated_at, PriorityMassRecipient.fan_id)
            .limit(_LEG))).scalars())
        fans = {int(f.fan_id): f for f in (await s.execute(select(Fan).where(
            Fan.account_id == aid, Fan.fan_id.in_(batch or [-1])))).scalars()}
        s.expunge_all()
    stats = {"interrupted": int(stale.rowcount or 0), "sent": 0, "skipped": 0,
             "failed": 0, "unknown": 0, "deferred": 0}
    if not batch:
        await _set_status(rid, DONE, only_from=(RUNNING,))
        return {**stats, "status": "ok", "done": True}

    words, mode = await load_banned_words(aid)
    scanned, hits = filter_banned([run.text], words, mode)
    if scanned is None:
        await _set_status(rid, ERROR, error=(
            f"the text holds a banned word ({', '.join(banned_hit_summary(hits))}); stopped"))
        return {**stats, "status": "error", "reason": "banned_words"}
    template = scanned[0]
    price = run.price_cents / 100 if run.price_cents > 0 else 0
    media, previews = _ids(run.media_json), _ids(run.previews_json)
    client = await asyncio.to_thread(ax._make_client, aid)
    delay_s = 0.0
    started = time.monotonic()

    for fid in batch:
        if time.monotonic() - started > _LEG_BUDGET_S:
            break       # a slow leg yields its bulk slot; the rest stay pending
        if fans.get(fid) is not None and should_skip_muted_creator(fans[fid]):
            await _set_recipient(rid, fid, SKIPPED, reason="muted_creator", only_from=PENDING)
            stats["skipped"] += 1
            continue
        if await _status(rid) != RUNNING:       # cancelled mid-leg
            return {**stats, "status": "ok", "stopped": True}
        if not await ax.acquire_fan_lease(aid, fid, KIND):
            await _defer(rid, fid)
            stats["deferred"] += 1
            continue
        try:
            now = datetime.utcnow()
            until = await _paused_until(aid, fid)
            if until is not None and until > now + _PAUSED_SKIP:
                await _set_recipient(rid, fid, SKIPPED, reason="paused", only_from=PENDING)
                stats["skipped"] += 1
                continue
            if until is not None and until > now:
                await _defer(rid, fid)
                stats["deferred"] += 1
                continue
            # Exclusions as of now, under the lease: a fan who wrote in or was
            # messaged since this leg began is skipped.
            reason = (await exclusions(aid, [fid], priced=price > 0, media=media)).get(fid)
            if reason:
                await _set_recipient(rid, fid, SKIPPED, reason=reason, only_from=PENDING)
                stats["skipped"] += 1
                continue
            if not await _set_recipient(rid, fid, CLAIMED, only_from=PENDING):
                continue
            text = apply_word_restriction(
                substitute_placeholders(template, fans.get(fid), name=template_fan_name(fans.get(fid))))
            try:
                result = await ax.of_write_paced(
                    aid,
                    lambda f=int(fid), t=text: client.send_message(
                        f, t, price=price, locked_text=bool(run.locked_text and price),
                        media_files=media, previews=previews or None),
                    send_purpose=_SEND_PURPOSE, tries=1, dm=True)
            except Exception as exc:  # noqa: BLE001
                if await skip_unreachable_fan(aid, fid, exc, log=log):
                    await _set_recipient(rid, fid, SKIPPED, reason="unreachable")
                    stats["skipped"] += 1
                    continue
                if ax.is_rate_limited(exc):
                    # OF created nothing: the fan goes back, the next leg waits.
                    await _set_recipient(rid, fid, PENDING)
                    delay_s = _DEFER_S
                    break
                if media and is_media_rejected_error(exc):
                    await _set_recipient(rid, fid, PENDING)
                    await _set_status(rid, ERROR, error=(
                        "OnlyFans refused the attached media; stopped"))
                    return {**stats, "status": "error", "reason": "media_rejected"}
                if _refused(exc):
                    await _set_recipient(rid, fid, FAILED, reason="error")
                    stats["failed"] += 1
                else:       # OF may have sent it: never resent
                    await _set_recipient(rid, fid, UNKNOWN, reason="transport")
                    stats["unknown"] += 1
                log.warning("priority_mass send failed run=%s account=%s fan=%s",
                            rid, aid, fid, exc_info=True)
                continue
            msg_id = result.get("id") if isinstance(result, dict) else None
            if not msg_id:
                await _set_recipient(rid, fid, FAILED, reason="no_id")
                stats["failed"] += 1
                await quarantine_if_undeliverable(client, aid, fid, log=log)
                continue
            await _set_recipient(rid, fid, SENT, message_id=int(msg_id))
            stats["sent"] += 1
            # An UPSERT: a fan read off OF's roster may have no `fans` row yet.
            await ax.start_fan_cooldown(aid, fid, cooldown_s=_REST_S)
            await write_outbound_attribution(
                account_id=aid, fan_id=int(fid), message_id=int(msg_id),
                sent_by_employee_id=run.created_by_employee_id, automation_kind=KIND,
                body=str(result.get("text") or text), price_cents=int(run.price_cents),
                created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                emit_live=True)
        finally:
            await ax.release_fan_lease(aid, fid, holder=KIND)

    if stats["deferred"] and not (stats["sent"] or stats["skipped"] or stats["failed"]
                                  or stats["unknown"]):
        delay_s = _DEFER_S          # every fan was busy: give them a minute
    if await _status(rid) == RUNNING:
        await ensure_leg(aid, rid, delay_s=delay_s)
    return {**stats, "status": "ok"}


@register(KIND)
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    try:
        rid = int((payload or {}).get("run_id"))
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "no_run_id"}
    async with get_session() as s:
        row = await s.get(PriorityMassRun, rid)
        if row is not None:
            s.expunge(row)
    if row is None or row.account_id != str(account_id):
        return {"status": "skipped", "reason": "no_run"}
    stats: dict = {"run_id": rid}
    if row.status == RESOLVING:
        stats.update(await _freeze(row))
        if await _status(rid) != RUNNING:
            return stats
        row.status = RUNNING
    if row.status != RUNNING:
        return {**stats, "status": "skipped", "reason": row.status}
    return {**stats, **await _leg(row)}


async def counts(run_ids: list[int]) -> dict[int, dict[str, int]]:
    """{run_id: {status: n}} over the runs' recipients."""
    out: dict[int, dict[str, int]] = {int(r): {} for r in run_ids}
    if not run_ids:
        return out
    async with get_session() as s:
        for rid, status, n in (await s.execute(
                select(PriorityMassRecipient.run_id, PriorityMassRecipient.status, func.count())
                .where(PriorityMassRecipient.run_id.in_(run_ids))
                .group_by(PriorityMassRecipient.run_id, PriorityMassRecipient.status))).all():
            out[int(rid)][str(status)] = int(n)
    return out
