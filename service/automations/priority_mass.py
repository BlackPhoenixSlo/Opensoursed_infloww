from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

import automation_executor as ax
import media_cotag
import platforms
import send_ops
from attribution import write_outbound_attribution
from automation_registry import register
from automations._common import (
    apply_word_restriction, is_media_rejected_error, load_hard_skip_ids,
    quarantine_if_undeliverable, schedule_recheck_rejected_media, should_skip_muted_creator,
    skip_unreachable_fan, substitute_placeholders, template_fan_name,
)
from automations._wordfilter import banned_hit_summary, filter_banned, load_banned_words, sensitive_hits
from db.engine import get_session
from db.models import Blacklist, Fan, PriorityMassRecipient, PriorityMassRun, ScheduledJob
from of_client import OFSessionRetired
from side_effect_gate import (
    is_live_check_name, live_check, live_check_ungranted, send_refusal,
)

log = logging.getLogger("of-relay.automation.priority_mass")

KIND = "priority_mass"
MAX_RECIPIENTS = 5_000
HOURLY_RATE = 300
_SEND_PURPOSE = "gated"
_LEG = 10
_LEG_BUDGET_S = 180
_DEFER_S = 60
_REST_S = 45
_PAUSED_SKIP = timedelta(minutes=15)
# A guess: only a rate limit or busy pool deferring every leg goes 48 h without progress.
_STALL_DEADLINE = timedelta(hours=48)

RESOLVING, RUNNING, DONE, CANCELLED, ERROR = "resolving", "running", "done", "cancelled", "error"
LIVE = (RESOLVING, RUNNING)
PENDING, CLAIMED, SENT, SKIPPED, FAILED, UNKNOWN = (
    "pending", "claimed", "sent", "skipped", "failed", "unknown")


def leg_payload(run_id: int) -> str:
    return json.dumps({"run_id": int(run_id)})


async def ensure_leg(account_id: str, run_id: int, *, delay_s: float = 0,
                     include_running: bool = False) -> bool:
    statuses = ["pending", "running"] if include_running else ["pending"]
    async with get_session() as s:
        queued = (await s.execute(select(ScheduledJob.id).where(
            ScheduledJob.account_id == str(account_id), ScheduledJob.kind == KIND,
            ScheduledJob.status.in_(statuses),
            ScheduledJob.payload_json == leg_payload(run_id)).limit(1))).first()
        if queued is not None:
            return False
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



async def exclusions(account_id: str, fan_ids: list[int], *, priced: bool,
                     media: list[int]) -> dict[int, str]:
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



def _platform_refusal(platform: platforms.Platform, run: PriorityMassRun) -> str | None:
    from audiences import audience_refusal
    aud = json.loads(run.audience_json or "{}")
    cotag = bool(platform.backend and media_cotag.would_cotag(run.account_id, _ids(run.media_json)))
    return (audience_refusal(run.account_id, aud.get("user_lists"), aud.get("excluded_user_lists"))
            or send_refusal(platform, {"locked_text": bool(run.locked_text and run.price_cents > 0)},
                            would_cotag=cotag)
            or live_check_ungranted(run.account_id, KIND))


def _recipient_refusal(account_id: str, fan_ids: Iterable[int]) -> str | None:
    return live_check(account_id, KIND, frozenset(map(str, fan_ids)))


async def _persisted_refusal(run: PriorityMassRun) -> str | None:
    async with get_session() as s:
        persisted = (await s.execute(select(PriorityMassRecipient.fan_id).where(
            PriorityMassRecipient.run_id == run.id))).scalars().all()
    return _recipient_refusal(run.account_id, persisted)


async def refusal(run: PriorityMassRun) -> str | None:
    platform = platforms.for_account(run.account_id)
    gated = is_live_check_name(platform, KIND)
    if reason := _platform_refusal(platform, run):
        return reason
    return await _persisted_refusal(run) if gated and run.status == RUNNING else None


async def _freeze(run: PriorityMassRun, gated: bool) -> dict:
    from audiences import AudienceRefusal, roster_audience_blocking
    aud = json.loads(run.audience_json or "{}")
    client = await asyncio.to_thread(ax._make_client, run.account_id)
    try:
        ids = await asyncio.to_thread(
            roster_audience_blocking, client, account_id=run.account_id,
            user_lists=list(aud.get("user_lists") or []),
            excluded_user_lists=list(aud.get("excluded_user_lists") or []))
    except AudienceRefusal as e:
        await _set_status(run.id, ERROR, error=e.reason, only_from=(RESOLVING,))
        return {"status": "skipped", "reason": e.reason}
    if ids is None:
        await _set_status(run.id, ERROR, error=(
            "the audience could not be read in full from OnlyFans; nothing was sent"))
        return {"status": "error", "reason": "audience_unresolved"}
    excl = await exclusions(run.account_id, ids, priced=run.price_cents > 0,
                            media=_ids(run.media_json))
    eligible = sorted(f for f in ids if f not in excl)
    claimed = eligible[:MAX_RECIPIENTS]
    if gated and (reason := _recipient_refusal(run.account_id, claimed)):
        await _set_status(run.id, ERROR, error=reason, only_from=(RESOLVING,))
        return {"status": "skipped", "reason": reason}
    now = datetime.utcnow()
    async with get_session() as s:
        res = await s.execute(update(PriorityMassRun).where(
            PriorityMassRun.id == run.id, PriorityMassRun.status == RESOLVING).values(
            status=RUNNING, resolved_count=len(ids), excluded_count=len(excl),
            capped_count=len(eligible) - len(claimed)))
        if not res.rowcount:
            return {"status": "skipped", "reason": "not_resolving"}
        if claimed:
            await s.execute(PriorityMassRecipient.__table__.insert(), [
                {"run_id": run.id, "fan_id": f, "status": PENDING, "updated_at": now}
                for f in claimed])
    log.info("priority_mass froze run=%s account=%s resolved=%d excluded=%d claimed=%d",
             run.id, run.account_id, len(ids), len(excl), len(claimed))
    return {"resolved": len(ids), "excluded": len(excl), "claimed": len(claimed),
            "capped": len(eligible) - len(claimed)}



def _refused(exc: Exception) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and 400 <= status < 500


async def _paused_until(account_id: str, fan_id: int) -> datetime | None:
    async with get_session() as s:
        return (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id)))).scalar_one_or_none()


async def _defer(run_id: int, fan_id: int) -> None:
    await _set_recipient(run_id, fan_id, PENDING, only_from=PENDING)


async def _leg(run: PriorityMassRun, gated: bool) -> dict:
    aid, rid = run.account_id, run.id
    if gated and (reason := await _persisted_refusal(run)):
        await _set_status(rid, ERROR, error=reason, only_from=(RUNNING,))
        return {"status": "skipped", "reason": reason}
    async with get_session() as s:
        # A claim this leg did not make was left by a crash mid-send: unknown, never resent (OF may have created it).
        stale = await s.execute(update(PriorityMassRecipient).where(
            PriorityMassRecipient.run_id == rid, PriorityMassRecipient.status == CLAIMED,
        ).values(status=UNKNOWN, reason="interrupted"))
        moved = (await s.execute(select(func.max(PriorityMassRecipient.updated_at)).where(
            PriorityMassRecipient.run_id == rid,
            PriorityMassRecipient.status.not_in((PENDING, CLAIMED))))).scalar()
        last = max((t for t in (moved, run.created_at) if t is not None), default=None)
        late = None
        if last is not None and datetime.utcnow() - last > _STALL_DEADLINE:
            late = await s.execute(update(PriorityMassRecipient).where(
                PriorityMassRecipient.run_id == rid, PriorityMassRecipient.status == PENDING,
            ).values(status=SKIPPED, reason="deadline", updated_at=datetime.utcnow()))
            batch, fans = [], {}
        else:
            batch = list((await s.execute(select(PriorityMassRecipient.fan_id).where(
                PriorityMassRecipient.run_id == rid, PriorityMassRecipient.status == PENDING,
            ).order_by(PriorityMassRecipient.updated_at, PriorityMassRecipient.fan_id)
                .limit(_LEG))).scalars())
            fans = {int(f.fan_id): f for f in (await s.execute(select(Fan).where(
                Fan.account_id == aid, Fan.fan_id.in_(batch or [-1])))).scalars()}
        s.expunge_all()
    stats = {"interrupted": int(stale.rowcount or 0), "sent": 0, "skipped": 0,
             "failed": 0, "unknown": 0, "deferred": 0}
    if late is not None:
        log.warning("priority_mass run=%s account=%s no progress for %s: %s fan(s) skipped",
                    rid, aid, _STALL_DEADLINE, late.rowcount)
        stats["skipped"] = int(late.rowcount or 0)
    if not batch:
        await _set_status(rid, DONE, only_from=(RUNNING,))
        return {**stats, "status": "ok", "done": True}

    words, mode = await load_banned_words(aid)
    scanned, hits = filter_banned([run.text], words, mode)
    phrase_hits = sensitive_hits(run.text or "", words)
    if scanned is None or phrase_hits:
        await _set_status(rid, ERROR, error=(
            f"the text holds a banned word ({', '.join(banned_hit_summary(hits + phrase_hits))}); stopped"))
        return {**stats, "status": "error", "reason": "banned_words"}
    template = scanned[0]
    price = run.price_cents / 100 if run.price_cents > 0 else 0
    media, previews = _ids(run.media_json), _ids(run.previews_json)
    client = await asyncio.to_thread(ax._make_client, aid)
    delay_s = 0.0
    started = time.monotonic()

    for fid in batch:
        if time.monotonic() - started > _LEG_BUDGET_S:
            break
        if fans.get(fid) is not None and should_skip_muted_creator(fans[fid]):
            await _set_recipient(rid, fid, SKIPPED, reason="muted_creator", only_from=PENDING)
            stats["skipped"] += 1
            continue
        if await _status(rid) != RUNNING:
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
            # Exclusions as of now, under the lease: a long run honours ones made after it started.
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
                    lambda f=int(fid), t=text: send_ops.automated_sync(
                        aid, KIND, f, f"{rid}:{f}", lambda: client.send_message(
                            f, t, price=price, locked_text=bool(run.locked_text and price),
                            media_files=media, previews=previews or None),
                        body={"text": t, "price": price, "media": media, "previews": previews}),
                    send_purpose=_SEND_PURPOSE, tries=1, dm=True)
            except Exception as exc:  # noqa: BLE001
                if reason := send_ops.refusal_reason(exc):
                    await _set_recipient(rid, fid, PENDING)
                    stats["deferred"] += 1
                    delay_s = _DEFER_S
                    send_ops.skip_fan(exc, reason=reason)
                    continue
                if await skip_unreachable_fan(aid, fid, exc, log=log):
                    await _set_recipient(rid, fid, SKIPPED, reason="unreachable")
                    stats["skipped"] += 1
                    continue
                # nothing was created (rate limit) or the send never left the box: fan goes back, next leg waits
                if ax.is_rate_limited(exc) or isinstance(exc, OFSessionRetired):
                    await _set_recipient(rid, fid, PENDING)
                    stats["deferred"] += 1
                    delay_s = _DEFER_S
                    log.warning("priority_mass send deferred run=%s account=%s fan=%s: %s",
                                rid, aid, fid, exc)
                    break
                if media and is_media_rejected_error(exc):
                    await _set_recipient(rid, fid, PENDING)
                    await _set_status(rid, ERROR, error=(
                        "OnlyFans refused the attached media; stopped"))
                    schedule_recheck_rejected_media(aid, client, media + previews, log=log)
                    return {**stats, "status": "error", "reason": "media_rejected"}
                if _refused(exc):
                    await _set_recipient(rid, fid, FAILED, reason="error")
                    stats["failed"] += 1
                else:
                    # OF may have sent it: never resent.
                    await _set_recipient(rid, fid, UNKNOWN, reason="transport")
                    stats["unknown"] += 1
                log.warning("priority_mass send failed run=%s account=%s fan=%s",
                            rid, aid, fid, exc_info=True)
                continue
            if send_ops.is_reconciled(result):
                await _set_recipient(rid, fid, SENT)
                stats["sent"] += 1
                continue
            msg_id = result.get("id") if isinstance(result, dict) else None
            if not msg_id:
                await _set_recipient(rid, fid, FAILED, reason="no_id")
                stats["failed"] += 1
                await quarantine_if_undeliverable(client, aid, fid, log=log)
                continue
            await _set_recipient(rid, fid, SENT, message_id=int(msg_id))
            stats["sent"] += 1
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
        delay_s = _DEFER_S
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
    platform = platforms.for_account(account_id)
    gated = is_live_check_name(platform, KIND)
    if row.status in LIVE and (reason := _platform_refusal(platform, row)):
        log.info("priority_mass refused run=%s account=%s (%s)", rid, account_id, reason)
        await _set_status(rid, ERROR, error=reason, only_from=LIVE)
        return {"status": "skipped", "reason": reason}
    stats: dict = {"run_id": rid}
    if row.status == RESOLVING:
        stats.update(await _freeze(row, gated))
        if await _status(rid) != RUNNING:
            return stats
        row.status = RUNNING
    if row.status != RUNNING:
        return {**stats, "status": "skipped", "reason": row.status}
    return {**stats, **await _leg(row, gated)}


async def counts(run_ids: list[int]) -> dict[int, dict[str, int]]:
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
