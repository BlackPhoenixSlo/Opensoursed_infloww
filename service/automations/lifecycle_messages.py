from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from random import Random

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import of_pacing
import smart_message_extras as extras
from attribution import write_outbound_attribution
from audiences import _page_all_checked
from automation_registry import register
from automations import welcome_turn
from automations._fan_notes import substitute_placeholders, template_fan_name
from automations._knobs import coerce_ids
from automations._outbound_guard import apply_word_restriction
from automations._send_failure import (
    is_unreachable_fan_error, quarantine_if_undeliverable, schedule_recheck_rejected_media,
    send_dropping_bad_media_sync, skip_unreachable_fan,
)
from automations._skiplist import (
    is_hard_skipped, load_hard_skip_ids, should_skip_muted_creator,
)
from automations.auto_follow import _NOTIFY_OUTCOMES, gated_follow, stamp_ping
from db.engine import get_session
from db.models import (
    AutomationRule, Blacklist, Fan, LifecycleMessageClaim, SubscriberSnapshot,
)
from side_effect_gate import refusal

log = logging.getLogger("of-relay.automation.lifecycle_messages")

EXPIRY = "expiry_message"
EXPIRED = "expired_message"
RESUBSCRIBE = "resubscribe_message"
BIRTHDAY = "birthday_message"
KINDS: dict[str, str] = {
    EXPIRY: "Nearing expiry", EXPIRED: "Expired",
    RESUBSCRIBE: "Resubscribe", BIRTHDAY: "Birthday",
}
PAID_ONLY = frozenset({EXPIRY, EXPIRED, RESUBSCRIBE})
FREE_PAGE_REFUSAL = "is a free subscription profile and is unable to create this message"
HOURS: dict[str, tuple[int, int]] = {EXPIRY: (1, 120), EXPIRED: (12, 120)}
DEFAULT_HOURS = 24
DEFAULT_FREQUENCY = "once"
STORED_FREQUENCY = "every"
MAX_MESSAGES = 10
MAX_VARIANTS = 10
MAX_FOLLOW_UPS = 5
TEXT_MAX = 1000
FOLLOW_UP_MINUTES = (1, 7 * 24 * 60)
DISCOUNT_PERCENT = (5, 60)
DISCOUNT_MONTHS = (1, 12)
DISCOUNT_KINDS = frozenset({EXPIRY})

_SEND_PURPOSE = "gated"
_LIMIT = 25
_COOLDOWN_S = 45
_CRAWL_TTL_S = 25 * 60
_ROSTER_PAGE = 50
_STALE_H = 24
_KNOWN_BEFORE = timedelta(days=1)
_BUSY_RETRY = timedelta(minutes=10)
_BUSY_TRIES = 3


def _parse_iso(raw) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00")) if raw else None
    except ValueError:
        return None
    if ts is not None and ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def clamp_hours(kind: str, raw) -> int | None:
    if kind not in HOURS:
        return None
    lo, hi = HOURS[kind]
    try:
        n = int(raw) if raw is not None and not isinstance(raw, bool) else DEFAULT_HOURS
    except (TypeError, ValueError):
        n = DEFAULT_HOURS
    return max(lo, min(n, hi))


async def _live_rule(account_id: str, kind: str) -> dict | None:
    async with get_session() as s:
        rule = (await s.execute(
            select(AutomationRule).where(
                AutomationRule.account_id == str(account_id),
                AutomationRule.kind == kind,
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



def _crawl_blocking(client) -> tuple[list[dict], bool]:
    return _page_all_checked(
        lambda off: client.subscribers(type="active", limit=_ROSTER_PAGE, offset=off))


def _sub_data(u: dict) -> tuple[datetime | None, datetime | None, bool | None, bool]:
    d = u.get("subscribedOnData") if isinstance(u.get("subscribedOnData"), dict) else {}
    status = d.get("status")
    renew_on = None if status is None else str(status).strip().lower() == "active"
    return (_parse_iso(d.get("subscribeAt")), _parse_iso(d.get("expiredAt")),
            renew_on, bool(d.get("renewedAt")))


async def _last_crawl(account_id: str) -> datetime | None:
    async with get_session() as s:
        return (await s.execute(
            select(func.max(SubscriberSnapshot.seen_at))
            .where(SubscriberSnapshot.account_id == str(account_id)))).scalar()


RENEW_SNAPSHOT_MAX_AGE = timedelta(days=1)


async def renew_off_fan_ids(account_id, fan_ids, now: datetime) -> set[int]:
    ids = {int(i) for i in fan_ids}
    crawl = await _last_crawl(account_id)
    if not ids or crawl is None or now - crawl > RENEW_SNAPSHOT_MAX_AGE:
        return set()
    async with get_session() as s:
        rows = (await s.execute(
            select(SubscriberSnapshot.fan_id).where(
                SubscriberSnapshot.account_id == str(account_id),
                SubscriberSnapshot.fan_id.in_(ids),
                SubscriberSnapshot.seen_at == crawl,
                SubscriberSnapshot.renew_on.is_(False),
                or_(SubscriberSnapshot.expired_at.is_(None), SubscriberSnapshot.expired_at > now),
            ))).all()
    return {int(r[0]) for r in rows}


_roster_locks: dict[str, asyncio.Lock] = {}


async def refresh_roster(account_id: str, client, *, now: datetime,
                         force: bool = False) -> dict:
    lock = _roster_locks.setdefault(str(account_id), asyncio.Lock())
    if force and lock.locked():
        return {"roster": "in_progress"}
    async with lock:
        run = lambda: _refresh_roster(account_id, client, now=now, force=force)
        return await (run() if force else of_pacing.walk(account_id, "subscribers", run))


async def _refresh_roster(account_id: str, client, *, now: datetime,
                          force: bool = False) -> dict:
    last = await _last_crawl(account_id)
    if not force and last is not None and (now - last).total_seconds() < _CRAWL_TTL_S:
        return {"roster": "fresh"}
    rows, truncated = await asyncio.to_thread(_crawl_blocking, client)
    listed: dict[int, dict] = {}
    for u in rows:
        try:
            listed[int(u["id"])] = u
        except (KeyError, TypeError, ValueError):
            continue
    # A short crawl would turn every fan past it into an expired one.
    if truncated or not listed:
        log.warning("lifecycle roster crawl unusable account=%s rows=%s truncated=%s",
                    account_id, len(listed), truncated)
        return {"roster": "truncated" if truncated else "empty"}
    async with get_session() as s:
        existing = {int(r.fan_id): r for r in (await s.execute(
            select(SubscriberSnapshot).where(
                SubscriberSnapshot.account_id == str(account_id)))).scalars()}
        new_ids = [f for f in listed if f not in existing] or [-1]
        known_at = {int(f): c for f, c in (await s.execute(
            select(Fan.fan_id, Fan.created_at).where(
                Fan.account_id == str(account_id), Fan.fan_id.in_(new_ids)))).all()}
        returned = 0
        for fid, u in listed.items():
            sub, exp, renew_on, renewed = _sub_data(u)
            row = existing.get(fid)
            if row is None:
                known = known_at.get(fid)
                back = (sub is not None and known is not None and not renewed
                        and known < sub - _KNOWN_BEFORE and sub >= now - timedelta(hours=_STALE_H))
                s.add(SubscriberSnapshot(
                    account_id=str(account_id), fan_id=fid, subscribe_at=sub,
                    expired_at=exp, renew_on=renew_on, seen_at=now,
                    resubscribed_at=sub if back else None))
                returned += int(back)
                continue
            if (last is not None and row.seen_at < last and sub is not None
                    and (row.subscribe_at is None or sub > row.subscribe_at)):
                row.resubscribed_at = sub
                returned += 1
            row.subscribe_at, row.expired_at, row.renew_on, row.seen_at = sub, exp, renew_on, now
        await s.commit()
    return {"roster": "crawled", "listed": len(listed), "returned": returned}


async def expired_fans(account_id: str, *,
                       ended_by: datetime | None = None) -> dict[int, datetime] | None:
    last = await _last_crawl(account_id)
    if last is None:
        return None
    S = SubscriberSnapshot
    q = select(S.fan_id, S.expired_at).where(
        S.account_id == str(account_id), S.seen_at < last, S.expired_at.is_not(None))
    if ended_by is not None:
        q = q.where(S.expired_at <= ended_by)
    async with get_session() as s:
        return {int(f): exp for f, exp in (await s.execute(q)).all()}


async def _roster_events(account_id: str, kind: str, *, hours: int | None,
                         since: datetime, now: datetime) -> dict[int, str]:
    if kind == EXPIRED:
        gone = await expired_fans(account_id, ended_by=now - timedelta(hours=hours)) or {}
        return {f: exp.isoformat() for f, exp in gone.items()
                if exp + timedelta(hours=hours) >= since}
    last = await _last_crawl(account_id)
    if last is None:
        return {}
    S = SubscriberSnapshot
    q = select(S.fan_id, S.expired_at, S.resubscribed_at).where(S.account_id == str(account_id))
    if kind == EXPIRY:
        q = q.where(S.seen_at == last, S.renew_on.is_(False), S.expired_at.is_not(None),
                    S.expired_at > now, S.expired_at <= now + timedelta(hours=hours))
    else:
        q = q.where(S.seen_at == last, S.resubscribed_at.is_not(None),
                    S.resubscribed_at >= since)
    async with get_session() as s:
        rows = (await s.execute(q)).all()
    out: dict[int, str] = {}
    for fid, exp, back in rows:
        if kind == EXPIRY:
            if exp - timedelta(hours=hours) < since:
                continue
            out[int(fid)] = exp.isoformat()
        else:
            out[int(fid)] = back.isoformat()
    return out


async def _birthday_events(account_id: str, now: datetime) -> dict[int, str]:
    async with get_session() as s:
        ids = (await s.execute(select(Fan.fan_id).where(
            Fan.account_id == str(account_id),
            Fan.birthday == now.strftime("%m-%d")))).scalars().all()
    return {int(f): str(now.year) for f in ids}



async def _claimed(account_id: str, kind: str, events: dict[int, str], *,
                   once: bool = False) -> set[int]:
    if not events:
        return set()
    async with get_session() as s:
        rows = (await s.execute(
            select(LifecycleMessageClaim.fan_id, LifecycleMessageClaim.event_key).where(
                LifecycleMessageClaim.account_id == str(account_id),
                LifecycleMessageClaim.kind == kind,
                LifecycleMessageClaim.fan_id.in_(list(events))))).all()
    return {int(f) for f, k in rows
            if events.get(int(f)) == k or (once and not str(k).startswith(_FORCED))}


# A force_ids run is the operator test: its claims never count toward "once".
_FORCED = "forced:"


# A step is claimed before the wire and handed back only on OF's rate-limit refusal, so a job run twice sends it once.
async def _claim(account_id: str, kind: str, fan_id: int, key: str) -> bool:
    async with get_session() as s:
        res = await s.execute(
            sqlite_insert(LifecycleMessageClaim)
            .values(account_id=str(account_id), kind=kind, fan_id=int(fan_id),
                    event_key=key, created_at=datetime.utcnow())
            .on_conflict_do_nothing(index_elements=["account_id", "kind", "fan_id", "event_key"]))
        await s.commit()
    return bool(res.rowcount)


async def _mark_sent(account_id: str, kind: str, fan_id: int, key: str, message_idx: int) -> None:
    async with get_session() as s:
        await s.execute(update(LifecycleMessageClaim).where(
            LifecycleMessageClaim.account_id == str(account_id),
            LifecycleMessageClaim.kind == kind,
            LifecycleMessageClaim.fan_id == int(fan_id),
            LifecycleMessageClaim.event_key == key).values(message_idx=int(message_idx)))
        await s.commit()


async def _release(account_id: str, kind: str, fan_id: int, key: str) -> None:
    async with get_session() as s:
        await s.execute(delete(LifecycleMessageClaim).where(
            LifecycleMessageClaim.account_id == str(account_id),
            LifecycleMessageClaim.kind == kind,
            LifecycleMessageClaim.fan_id == int(fan_id),
            LifecycleMessageClaim.event_key == key))
        await s.commit()


async def _rest(account_id: str, fan_id: int) -> None:
    now = datetime.utcnow()
    until = now + timedelta(seconds=_COOLDOWN_S)
    async with get_session() as s:
        await s.execute(update(Fan).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id),
            or_(Fan.automation_paused_until.is_(None), Fan.automation_paused_until < until),
        ).values(automation_paused_until=until, updated_at=now))
        await s.commit()


def _skip(reason: str) -> dict:
    return {"status": "skipped", "reason": reason, "sent": 0}



def pick(options, *seed):
    return options[Random(":".join(map(str, seed))).randrange(len(options))]


def follow_ups_of(raw) -> list[dict]:
    lo, hi = FOLLOW_UP_MINUTES
    out = []
    for step in raw if isinstance(raw, list) else []:
        if not isinstance(step, dict):
            continue
        text = step["text"].strip()[:TEXT_MAX] if isinstance(step.get("text"), str) else ""
        delay = step.get("delay_minutes")
        if text and isinstance(delay, int) and not isinstance(delay, bool) and lo <= delay <= hi:
            out.append({"text": text, "delay_minutes": delay})
    return out[:MAX_FOLLOW_UPS]


def discount_of(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    pct, months = raw.get("percent"), raw.get("months")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (pct, months)):
        return None
    if not (DISCOUNT_PERCENT[0] <= pct <= DISCOUNT_PERCENT[1] and pct % 5 == 0
            and DISCOUNT_MONTHS[0] <= months <= DISCOUNT_MONTHS[1]):
        return None
    return {"percent": pct, "months": months}


def discount_cap(price_cents: int) -> int:
    if price_cents <= 499:
        return 0
    return min(100 * (price_cents - 499) // price_cents, DISCOUNT_PERCENT[1])


def messages_of(steps: dict) -> list[dict]:
    raw = steps.get("messages")
    if not isinstance(raw, list):
        text = str(steps.get("text") or "").strip()[:TEXT_MAX]
        return [{"variants": [text], "follow_ups": [], "discount": None}] if text else []
    out = []
    for m in raw[:MAX_MESSAGES]:
        if not isinstance(m, dict):
            continue
        variants = m.get("variants") if isinstance(m.get("variants"), list) else []
        variants = [v.strip()[:TEXT_MAX] for v in variants if isinstance(v, str) and v.strip()][:MAX_VARIANTS]
        if variants:
            out.append({"variants": variants, "follow_ups": follow_ups_of(m.get("follow_ups")),
                        "discount": discount_of(m.get("discount"))})
    return out


def _anchor_json(anchor: tuple[datetime, int] | None) -> list | None:
    return [anchor[0].isoformat(), int(anchor[1])] if anchor is not None else None


async def schedule_follow_ups(account_id: str, kind: str, fan_id: int, steps: list[dict],
                              anchor: tuple[datetime, int] | None, *, event: str,
                              step: int = 1, tries: int = 0,
                              delay: timedelta | None = None) -> None:
    if not steps:
        return
    when = datetime.utcnow() + (delay or timedelta(minutes=steps[0]["delay_minutes"]))
    await ax.enqueue_followup(account_id, kind, run_at=when, payload={"follow_up": {
        "fan_id": int(fan_id), "steps": steps, "anchor": _anchor_json(anchor),
        "event": str(event), "step": int(step), "tries": tries}})


def _follow_up_key(event: str, step: int) -> str:
    return f"{event}|follow_up:{step}"


async def run_follow_up(account_id: str, kind: str, job: dict, *,
                        attribution_kind: str | None = None) -> dict:
    try:
        fid = int(job["fan_id"])
        step = int(job.get("step") or 1)
    except (KeyError, TypeError, ValueError):
        return _skip("bad_follow_up")
    steps = follow_ups_of(job.get("steps"))
    if not steps:
        return _skip("bad_follow_up")
    event = str(job.get("event") or "")
    raw = job.get("anchor")
    anchor = None
    if isinstance(raw, list) and len(raw) == 2:
        at = _parse_iso(raw[0])
        anchor = (at, int(raw[1])) if at is not None else None
    try:
        newest = await welcome_turn.newest_worded_inbound(account_id, fid)
    except Exception:  # noqa: BLE001 — unread is not "he said nothing"
        log.warning("%s follow-up reply check failed account=%s fan=%s — sequence stopped",
                    kind, account_id, fid, exc_info=True)
        return _skip("reply_check_failed")
    if newest is not None and (anchor is None or newest > anchor):
        return _skip("stopped_on_reply")

    import audience_include as _audiences
    async with get_session() as s:
        fan = (await s.execute(select(Fan).where(
            Fan.account_id == str(account_id), Fan.fan_id == fid))).scalar_one_or_none()
        blacklisted = (await s.execute(select(Blacklist.fan_id).where(
            Blacklist.fan_id == fid))).first() is not None
        if fan is not None:
            s.expunge(fan)
    if (blacklisted or (fan is not None and should_skip_muted_creator(fan))
            or await is_hard_skipped(account_id, fid)
            or fid not in await _audiences.filter_candidates(account_id, [fid], kind=kind)):
        return _skip("gated")

    if await ax.fan_on_cooldown(account_id, fid) or \
            not await ax.acquire_fan_lease(account_id, fid, kind):
        tries = int(job.get("tries") or 0) + 1
        if tries < _BUSY_TRIES:
            await schedule_follow_ups(account_id, kind, fid, steps, anchor, event=event,
                                      step=step, tries=tries, delay=_BUSY_RETRY)
        return _skip("busy")
    key = _follow_up_key(event, step)
    try:
        if not await _claim(account_id, kind, fid, key):
            return _skip("already_sent")
        client = await asyncio.to_thread(ax._make_client, account_id)
        text = apply_word_restriction(
            substitute_placeholders(steps[0]["text"], fan, name=template_fan_name(fan)))
        try:
            result = await ax.of_write_paced(
                account_id, lambda: client.send_message(fid, text, media_files=[]),
                send_purpose=_SEND_PURPOSE, dm=True)
        except Exception as exc:  # noqa: BLE001
            if ax.is_rate_limited(exc):
                await _release(account_id, kind, fid, key)
            if kind == EXPIRED and is_unreachable_fan_error(exc):
                return _skip("refused_expired")
            if await skip_unreachable_fan(account_id, fid, exc, log=log):
                return _skip("unreachable")
            log.warning("%s follow-up send failed account=%s fan=%s", kind, account_id, fid,
                        exc_info=True)
            return {"status": "error", "reason": "send_failed", "sent": 0}
        msg_id = result.get("id") if isinstance(result, dict) else None
        if not msg_id:
            await quarantine_if_undeliverable(client, account_id, fid, log=log)
            return {"status": "ok", "follow_up": True, "sent": 0, "no_id": 1}
        try:
            await write_outbound_attribution(
                account_id=account_id, fan_id=fid, message_id=int(msg_id),
                sent_by_employee_id=None, automation_kind=attribution_kind or kind,
                body=str(result.get("text") or text), price_cents=0,
                created_at=ax._parse_iso(result.get("createdAt")) or datetime.utcnow(),
                emit_live=True,
            )
            await _rest(account_id, fid)
            await schedule_follow_ups(account_id, kind, fid, steps[1:], anchor,
                                      event=event, step=step + 1)
        except Exception:  # noqa: BLE001 — it went out: never a reason to send it again
            log.warning("%s follow-up after-send bookkeeping failed account=%s fan=%s msg=%s",
                        kind, account_id, fid, msg_id, exc_info=True)
        log.info("%s follow-up sent account=%s fan=%s msg=%s left=%s",
                 kind, account_id, fid, msg_id, len(steps) - 1)
        return {"status": "ok", "follow_up": True, "sent": 1, "left": len(steps) - 1}
    finally:
        await ax.release_fan_lease(account_id, fid, holder=kind)


async def _follow_first(client, account_id: str, fan_id: int) -> str:
    async def _gated() -> str:
        return await gated_follow(client, int(fan_id), account_id=account_id, money_gate=True)
    outcome = await ax.of_write_paced(account_id, _gated, tries=1, send_purpose=_SEND_PURPOSE)
    if outcome in _NOTIFY_OUTCOMES:
        await stamp_ping(account_id, fan_id)
    return outcome



def pick_targets(kind: str, account_id: str, events: dict[int, str], messages: list[dict], *,
                 done: set[int], fans: dict, kept: set[int], hard_skip: set[int],
                 blacklist: set[int], now: datetime) -> tuple[list[tuple[int, str, int, str]], int]:
    plans: list[tuple[int, str, int, str]] = []
    skipped = 0
    for fid, key in events.items():
        if fid in done:
            continue
        fan = fans.get(fid)
        paused = fan is not None and fan.automation_paused_until is not None \
            and fan.automation_paused_until > now
        if (fan is None or fid not in kept or fid in hard_skip or fid in blacklist
                or paused or should_skip_muted_creator(fan)):
            skipped += 1
            continue
        idx = pick(range(len(messages)), kind, account_id, fid, key, "message")
        plans.append((fid, key, idx, pick(messages[idx]["variants"], kind, account_id, fid, key)))
    return plans, skipped


async def sweep(kind: str, account_id: str, payload: dict) -> dict:
    payload = payload or {}
    if isinstance(payload.get("follow_up"), dict):
        return await run_follow_up(account_id, kind, payload["follow_up"])
    cfg = await _live_rule(account_id, kind)
    if cfg is None or cfg.get("enabled") is not True:
        return _skip("disabled")
    messages = messages_of(cfg)
    if not messages:
        return _skip("no_text")
    enabled_at = _parse_iso(cfg.get("enabled_at"))
    if enabled_at is None:
        return _skip("no_enabled_at")
    dry_run = bool(payload.get("dry_run"))
    forced = coerce_ids(payload.get("force_ids"))
    hours = clamp_hours(kind, cfg.get("hours"))
    now = datetime.utcnow()
    outside = extras.window_skip(cfg, now)
    if outside:
        return _skip(outside)
    media, price_cents = extras.media_and_price(cfg)
    unsend_after = extras.unsend_minutes(cfg)
    once = extras.frequency(cfg, STORED_FREQUENCY) == "once" and not forced
    start = max(enabled_at, extras.window_start(cfg) or enabled_at)
    since = start if kind == EXPIRY else max(start, now - timedelta(hours=_STALE_H))
    stats: dict = {}

    client = None
    if forced:
        events = {fid: f"{_FORCED}{now.date().isoformat()}" for fid in forced}
    elif kind == BIRTHDAY:
        events = await _birthday_events(account_id, now)
    else:
        client = await asyncio.to_thread(ax._make_client, account_id)
        stats.update(await refresh_roster(account_id, client, now=now))
        events = await _roster_events(account_id, kind, hours=hours, since=since, now=now)

    import audience_include as _audiences
    audience_stats: dict = {}
    kept = set(await _audiences.filter_candidates(
        account_id, list(events), kind=kind, stats=audience_stats))
    hard_skip = await load_hard_skip_ids(account_id)
    fan_ids = list(events) or [-1]
    async with get_session() as s:
        blacklist = {int(x) for x in (await s.execute(
            select(Blacklist.fan_id).where(Blacklist.fan_id.in_(fan_ids)))).scalars().all()}
        fans = {int(f.fan_id): f for f in (await s.execute(
            select(Fan).where(Fan.account_id == str(account_id),
                              Fan.fan_id.in_(fan_ids)))).scalars().all()}
        s.expunge_all()
    done = await _claimed(account_id, kind, events, once=once)
    plans, skipped = pick_targets(kind, account_id, events, messages, done=done, fans=fans,
                                  kept=kept, hard_skip=hard_skip, blacklist=blacklist, now=now)

    if dry_run:
        return {"status": "ok", "dry_run": True, "would_send": min(len(plans), _LIMIT),
                "skipped": skipped, "capped": max(0, len(plans) - _LIMIT), "sent": 0,
                "candidates": len(events), **stats, **audience_stats}

    # A paid message never re-sells media the fan already owns: an owner gets the text alone, free.
    owned = await extras.owners(account_id, media, price_cents, [p[0] for p in plans])
    sent = no_id = errors = busy = unreachable = capped = attempted = owners_sent = 0
    refused = discounted = follow_errors = 0
    follows: Counter = Counter()
    if plans and client is None:
        client = await asyncio.to_thread(ax._make_client, account_id)
    lacks_discount = 0
    if plans and kind in DISCOUNT_KINDS and refusal(client, "set_subscription_discount"):
        plain = [p for p in plans if messages[p[2]]["discount"] is None]
        lacks_discount, plans = len(plans) - len(plain), plain
        skipped += lacks_discount
    for i, (fid, key, idx, template) in enumerate(plans):
        if attempted >= _LIMIT:
            capped = len(plans) - i
            break
        if await ax.fan_on_cooldown(account_id, fid):
            skipped += 1
            continue
        if not await ax.acquire_fan_lease(account_id, fid, kind):
            busy += 1
            continue
        try:
            if not await _claim(account_id, kind, fid, key):
                continue
            attempted += 1
            message = messages[idx]
            if kind == EXPIRED:
                try:
                    follows[await _follow_first(client, account_id, fid)] += 1
                except Exception:  # noqa: BLE001
                    follow_errors += 1
                    log.warning("%s follow-first failed account=%s fan=%s",
                                kind, account_id, fid, exc_info=True)
            # The text may promise the discount: no discount, no message.
            discount = message["discount"] if kind in DISCOUNT_KINDS else None
            if discount is not None:
                try:
                    await ax.of_write_paced(
                        account_id,
                        lambda f=int(fid), d=discount: client.set_subscription_discount(
                            f, d["percent"], d["months"]),
                        send_purpose=_SEND_PURPOSE)
                    discounted += 1
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    if ax.is_rate_limited(exc):
                        await _release(account_id, kind, fid, key)
                    log.warning("%s discount failed account=%s fan=%s event=%s",
                                kind, account_id, fid, key, exc_info=True)
                    continue
            text = apply_word_restriction(
                substitute_placeholders(template, fans[fid], name=template_fan_name(fans[fid])))
            fan_media, fan_price = ([], 0) if fid in owned else (media, price_cents)
            try:
                outcome = await ax.of_write_paced(
                    account_id,
                    lambda f=int(fid), t=text, m=fan_media, p=fan_price: send_dropping_bad_media_sync(
                        client, f, t, m, price_cents=p, log=log),
                    send_purpose=_SEND_PURPOSE, dm=True)
            except Exception as exc:  # noqa: BLE001
                if kind == EXPIRED and is_unreachable_fan_error(exc):
                    refused += 1
                    log.info("%s refused account=%s fan=%s event=%s",
                             kind, account_id, fid, key)
                    continue
                if await skip_unreachable_fan(account_id, fid, exc, log=log):
                    unreachable += 1
                    continue
                errors += 1
                if ax.is_rate_limited(exc):
                    await _release(account_id, kind, fid, key)
                log.warning("%s send failed account=%s fan=%s event=%s",
                            kind, account_id, fid, key, exc_info=True)
                continue
            result = outcome.result
            if fan_media and not outcome.media_landed:
                schedule_recheck_rejected_media(account_id, client, fan_media, log=log)
            msg_id = result.get("id") if isinstance(result, dict) else None
            if not msg_id:
                no_id += 1
                log.warning("%s no-id send account=%s fan=%s event=%s — claimed, not retried",
                            kind, account_id, fid, key)
                await quarantine_if_undeliverable(client, account_id, fid, log=log)
                continue
            landed_at = ax._parse_iso(result.get("createdAt")) or datetime.utcnow()
            await write_outbound_attribution(
                account_id=account_id, fan_id=int(fid), message_id=int(msg_id),
                sent_by_employee_id=None, automation_kind=kind,
                body=str(result.get("text") or text),
                price_cents=fan_price if outcome.media_landed else 0,
                created_at=landed_at, emit_live=True,
            )
            await extras.schedule_unsend(
                account_id, fid, int(msg_id), minutes=unsend_after,
                price_cents=fan_price if outcome.media_landed else 0)
            await _mark_sent(account_id, kind, fid, key, idx)
            await _rest(account_id, fid)
            await schedule_follow_ups(account_id, kind, fid, message["follow_ups"],
                                      (landed_at, int(msg_id)), event=key)
            sent += 1
            owners_sent += fid in owned
            log.info("%s sent account=%s fan=%s event=%s msg=%s message=%s",
                     kind, account_id, fid, key, msg_id, idx)
        finally:
            await ax.release_fan_lease(account_id, fid, holder=kind)

    out = {"status": "ok", "sent": sent, "no_id": no_id, "errors": errors,
           "unreachable": unreachable, "busy": busy, "skipped": skipped,
           "capped": capped, "candidates": len(events), "owners_sent_free": owners_sent,
           **stats, **audience_stats}
    if kind == EXPIRED:
        out.update(refused_expired=refused, follow_outcomes=dict(follows),
                   follow_errors=follow_errors)
    if kind in DISCOUNT_KINDS:
        out["discounted"] = discounted
    if lacks_discount:
        out["discount_skipped"] = "platform_lacks:set_subscription_discount"
    return out


@register("expiry_message")
async def run_expiry(account_id: str, payload: dict, *, run_id: int) -> dict:
    return await sweep(EXPIRY, account_id, payload)


@register("expired_message")
async def run_expired(account_id: str, payload: dict, *, run_id: int) -> dict:
    return await sweep(EXPIRED, account_id, payload)


@register("resubscribe_message")
async def run_resubscribe(account_id: str, payload: dict, *, run_id: int) -> dict:
    return await sweep(RESUBSCRIBE, account_id, payload)


@register("birthday_message")
async def run_birthday(account_id: str, payload: dict, *, run_id: int) -> dict:
    return await sweep(BIRTHDAY, account_id, payload)
