from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import smart_message_extras as extras
from attribution import _MASS_PLACEHOLDER_BASE, write_outbound_attribution
from automation_registry import register
from automations._common import (
    apply_word_restriction, load_hard_skip_ids, quarantine_if_undeliverable,
    schedule_recheck_rejected_media, send_dropping_bad_media_sync, should_skip_muted_creator,
    skip_unreachable_fan, substitute_placeholders, template_fan_name,
)
from db.engine import get_session
from db.models import (
    AutomationRule, Blacklist, Fan, Message, PurchaseFollowupClaim, PurchaseNotice,
    Transaction,
)

log = logging.getLogger("of-relay.automation.purchase_followup")

KIND = "purchase_followup"
_SEND_PURPOSE = "gated"
# A day-old thank-you reads as a bot catching up, even though the ledger linker can land a purchase hours late.
_MAX_AGE_HOURS = 24
_LIMIT = 25
# Infloww's own default for the Trigger: at most one thank-you per fan per 2h.
_EVERY_FLOOR_H = 2
_LEGACY_FLOOR_H = 24
DEFAULT_DELAY = [1, 3]
DEFAULT_FREQUENCY = "every"
STORED_FREQUENCY = "every"
_LEGACY_DELAY_MAX_MIN = 24 * 60
# Short so the AI seller's post-buy follow-up (90-240s after unlock) still goes out; the rest only lengthens a pause.
_COOLDOWN_S = 45
# A refund or chargeback is not proof of a purchase.
_PROOF_STATUSES = ("cleared", "pending")


def delay_of(steps: dict) -> list[int] | None:
    if "delay_range" in steps:
        return extras.delay_range(steps)
    d = steps.get("delay_minutes")
    if isinstance(d, bool) or not isinstance(d, int) or d <= 0:
        return None
    d = min(d, _LEGACY_DELAY_MAX_MIN)
    return [d, d]


def floor_hours(steps: dict) -> int:
    return _EVERY_FLOOR_H if steps.get("frequency") in extras.FREQUENCIES else _LEGACY_FLOOR_H


def _parse_iso(raw) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
    if ts is not None and ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


async def _live_rule(account_id: str) -> dict | None:
    async with get_session() as s:
        rule = (await s.execute(
            select(AutomationRule).where(
                AutomationRule.account_id == str(account_id),
                AutomationRule.kind == KIND,
                AutomationRule.is_enabled.is_(True),
            ).order_by(AutomationRule.id).limit(1)
        )).scalar_one_or_none()
    if rule is None:
        return None
    try:
        steps = json.loads(rule.steps_json or "{}")
    except (TypeError, ValueError):
        return {}
    return steps if isinstance(steps, dict) else {}


async def _purchases(account_id: str, *, now: datetime, start: datetime,
                     delay: list[int] | None) -> dict[int, list[int]]:
    aid = str(account_id)
    lo_s, hi_s = (delay[0] * 60, delay[1] * 60) if delay else (0, 0)
    ready_before = now - timedelta(seconds=lo_s)
    fresh_after = max(start, now - timedelta(seconds=hi_s, hours=_MAX_AGE_HOURS))
    bought = (
        Message.account_id == aid,
        Message.direction == "out",
        Message.message_id < _MASS_PLACEHOLDER_BASE,
        Message.price_cents > 0,
        Message.is_paid.is_(True),
        or_(Message.automation_kind.is_(None), Message.automation_kind != KIND),
        Message.purchased_at.is_not(None),
        Message.purchased_at <= ready_before,
        Message.purchased_at >= fresh_after,
    )
    cols = (Message.fan_id, Message.message_id, Message.purchased_at)
    reads = [
        select(*cols).where(*bought, Message.created_at >= fresh_after),
        select(*cols).select_from(Transaction).join(Message, and_(
            Message.account_id == Transaction.account_id,
            Message.fan_id == Transaction.fan_id,
            Message.message_id == Transaction.message_id,
        )).where(
            Transaction.account_id == aid,
            Transaction.occurred_at >= fresh_after,
            Transaction.occurred_at <= ready_before,
            Transaction.status.in_(_PROOF_STATUSES),
            *bought,
        ),
        select(*cols).select_from(PurchaseNotice).join(Message, and_(
            Message.account_id == PurchaseNotice.account_id,
            Message.fan_id == PurchaseNotice.fan_id,
            Message.message_id == PurchaseNotice.message_id,
        )).where(
            PurchaseNotice.account_id == aid,
            PurchaseNotice.notified_at >= fresh_after,
            PurchaseNotice.notified_at <= ready_before,
            *bought,
        ),
    ]
    found: dict[tuple[int, int], datetime] = {}
    async with get_session() as s:
        for q in reads:
            for fid, mid, at in (await s.execute(q)).all():
                if fid is not None and mid is not None:
                    found[(int(fid), int(mid))] = at
    out: dict[int, list[int]] = {}
    for (fid, mid), at in sorted(found.items(), key=lambda kv: (kv[1], kv[0])):
        due = at + timedelta(seconds=extras.delay_seconds(delay, aid, fid, mid))
        if due <= now and due >= now - timedelta(hours=_MAX_AGE_HOURS):
            out.setdefault(fid, []).append(mid)
    return out


async def _thanked_recently(account_id: str, fan_ids: list[int],
                            since: datetime | None) -> set[int]:
    if not fan_ids:
        return set()
    when = () if since is None else (PurchaseFollowupClaim.created_at >= since,)
    async with get_session() as s:
        return {int(f) for f in (await s.execute(
            select(PurchaseFollowupClaim.fan_id).where(
                PurchaseFollowupClaim.account_id == str(account_id),
                PurchaseFollowupClaim.fan_id.in_(fan_ids),
                PurchaseFollowupClaim.silent.is_(False),
                *when,
            ).distinct())).scalars().all()}


async def _claimed(account_id: str, msg_ids: list[int]) -> set[tuple[int, int]]:
    if not msg_ids:
        return set()
    async with get_session() as s:
        return {(int(f), int(m)) for f, m in (await s.execute(
            select(PurchaseFollowupClaim.fan_id, PurchaseFollowupClaim.purchased_message_id)
            .where(PurchaseFollowupClaim.account_id == str(account_id),
                   PurchaseFollowupClaim.purchased_message_id.in_(msg_ids)))).all()}


# Claimed before the wire, ON CONFLICT DO NOTHING: two racing sweeps cannot both win one purchase.
async def _claim(account_id: str, fan_id: int, msg_ids: list[int], *,
                 silent: bool = False) -> list[int]:
    won: list[int] = []
    async with get_session() as s:
        for mid in msg_ids:
            res = await s.execute(
                sqlite_insert(PurchaseFollowupClaim)
                .values(account_id=str(account_id), fan_id=int(fan_id),
                        purchased_message_id=int(mid), silent=bool(silent),
                        created_at=datetime.utcnow())
                .on_conflict_do_nothing(
                    index_elements=["account_id", "fan_id", "purchased_message_id"]))
            if res.rowcount:
                won.append(int(mid))
        await s.commit()
    return won


async def _release(account_id: str, fan_id: int, msg_ids: list[int]) -> None:
    async with get_session() as s:
        await s.execute(delete(PurchaseFollowupClaim).where(
            PurchaseFollowupClaim.account_id == str(account_id),
            PurchaseFollowupClaim.fan_id == int(fan_id),
            PurchaseFollowupClaim.purchased_message_id.in_(msg_ids)))
        await s.commit()


# Only ever lengthens a pause: a longer one (a decline's 72h) stays.
async def _rest(account_id: str, fan_id: int) -> None:
    now = datetime.utcnow()
    until = now + timedelta(seconds=_COOLDOWN_S)
    async with get_session() as s:
        await s.execute(update(Fan).where(
            Fan.account_id == str(account_id),
            Fan.fan_id == int(fan_id),
            or_(Fan.automation_paused_until.is_(None),
                Fan.automation_paused_until < until),
        ).values(automation_paused_until=until, updated_at=now))
        await s.commit()


def _skip(reason: str) -> dict:
    return {"status": "skipped", "reason": reason, "sent": 0}


@register(KIND)
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    cfg = await _live_rule(account_id)
    if cfg is None:
        return _skip("disabled")
    if cfg.get("enabled") is not True:
        return _skip("disabled")
    template = str(cfg.get("text") or "").strip()
    if not template:
        return _skip("no_text")
    enabled_at = _parse_iso(cfg.get("enabled_at"))
    if enabled_at is None:
        return _skip("no_enabled_at")
    dry_run = bool((payload or {}).get("dry_run"))
    now = datetime.utcnow()
    outside = extras.window_skip(cfg, now)
    if outside:
        return _skip(outside)
    media, price_cents = extras.media_and_price(cfg)
    unsend_after = extras.unsend_minutes(cfg)
    once = extras.frequency(cfg, STORED_FREQUENCY) == "once"

    start = max(enabled_at, extras.window_start(cfg) or enabled_at)
    bought = await _purchases(account_id, now=now, start=start, delay=delay_of(cfg))

    import audience_include as _audiences
    audience_stats: dict = {}
    kept = set(await _audiences.filter_candidates(
        account_id, list(bought), kind=KIND, stats=audience_stats))

    hard_skip = await load_hard_skip_ids(account_id)
    fan_ids = list(bought) or [-1]
    async with get_session() as s:
        blacklist = {int(x) for x in (await s.execute(
            select(Blacklist.fan_id).where(Blacklist.fan_id.in_(fan_ids)))).scalars().all()}
        fans = {int(f.fan_id): f for f in (await s.execute(
            select(Fan).where(Fan.account_id == str(account_id),
                              Fan.fan_id.in_(fan_ids)))).scalars().all()}
        s.expunge_all()
    done = await _claimed(account_id, [m for mids in bought.values() for m in mids])
    thanked = await _thanked_recently(
        account_id, list(bought), None if once else now - timedelta(hours=floor_hours(cfg)))

    plans: list[tuple[int, list[int]]] = []
    folds: list[tuple[int, list[int]]] = []
    skipped = 0
    for fid, mids in bought.items():
        pending = [m for m in mids if (fid, m) not in done]
        if not pending:
            continue
        if fid in thanked:
            folds.append((fid, pending))
            continue
        fan = fans.get(fid)
        paused = fan is not None and fan.automation_paused_until is not None \
            and fan.automation_paused_until > now
        if (fan is None or fid not in kept or fid in hard_skip or fid in blacklist
                or paused or should_skip_muted_creator(fan)):
            skipped += 1
            continue
        plans.append((fid, pending))

    if dry_run:
        return {"status": "ok", "dry_run": True, "would_send": min(len(plans), _LIMIT),
                "would_fold": len(folds), "skipped": skipped,
                "capped": max(0, len(plans) - _LIMIT), "sent": 0, **audience_stats}

    owned = await extras.owners(account_id, media, price_cents, [f for f, _ in plans])
    folded = owners_sent = 0
    for fid, pending in folds:
        if await _claim(account_id, fid, pending, silent=True):
            folded += 1
    sent = no_id = errors = busy = unreachable = capped = attempted = 0
    # Before any claim: a client that cannot be built leaves every purchase for the next sweep.
    client = await asyncio.to_thread(ax._make_client, account_id) if plans else None
    for i, (fid, pending) in enumerate(plans):
        if attempted >= _LIMIT:
            capped = len(plans) - i
            break
        if await ax.fan_on_cooldown(account_id, fid):
            skipped += 1
            continue
        if not await ax.acquire_fan_lease(account_id, fid, KIND):
            busy += 1
            continue
        try:
            claimed = await _claim(account_id, fid, pending)
            if not claimed:
                continue
            attempted += 1
            text = apply_word_restriction(
                substitute_placeholders(template, fans[fid], name=template_fan_name(fans[fid])))
            # A fan who already owns the media gets the text alone, free (no re-selling).
            fan_media, fan_price = ([], 0) if fid in owned else (media, price_cents)
            try:
                outcome = await ax.of_write_paced(
                    account_id,
                    lambda f=int(fid), t=text, m=fan_media, p=fan_price: send_dropping_bad_media_sync(
                        client, f, t, m, price_cents=p, log=log),
                    send_purpose=_SEND_PURPOSE, dm=True)
            except Exception as exc:  # noqa: BLE001
                if await skip_unreachable_fan(account_id, fid, exc, log=log):
                    unreachable += 1
                    continue
                errors += 1
                # Only a throttle refusal created nothing, so only it gives the claim back; any other failure keeps it (never twice).
                if ax.is_rate_limited(exc):
                    await _release(account_id, fid, claimed)
                log.warning("purchase_followup send failed account=%s fan=%s purchases=%s",
                            account_id, fid, claimed, exc_info=True)
                continue
            result = outcome.result
            if fan_media and not outcome.media_landed:
                schedule_recheck_rejected_media(account_id, client, fan_media, log=log)
            msg_id = result.get("id") if isinstance(result, dict) else None
            if not msg_id:
                no_id += 1
                log.warning("purchase_followup no-id send account=%s fan=%s purchases=%s "
                            "— claimed, not retried", account_id, fid, claimed)
                await quarantine_if_undeliverable(client, account_id, fid, log=log)
                continue
            await write_outbound_attribution(
                account_id=account_id, fan_id=int(fid), message_id=int(msg_id),
                sent_by_employee_id=None, automation_kind=KIND,
                body=str(result.get("text") or text),
                price_cents=fan_price if outcome.media_landed else 0,
                created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                emit_live=True,
            )
            await extras.schedule_unsend(
                account_id, fid, int(msg_id), minutes=unsend_after,
                price_cents=fan_price if outcome.media_landed else 0)
            await _rest(account_id, fid)
            sent += 1
            owners_sent += fid in owned
            log.info("purchase_followup sent account=%s fan=%s purchases=%s msg=%s",
                     account_id, fid, claimed, msg_id)
        finally:
            await ax.release_fan_lease(account_id, fid, holder=KIND)

    return {"status": "ok", "sent": sent, "no_id": no_id, "errors": errors,
            "unreachable": unreachable, "busy": busy, "skipped": skipped,
            "capped": capped, "folded": folded, "candidates": len(bought),
            "owners_sent_free": owners_sent, **audience_stats}
