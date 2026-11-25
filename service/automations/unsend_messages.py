from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update

import automation_executor as ax
from automation_registry import register
from db.engine import get_session
from db.models import Action, MassBroadcastCache, MassRun, Message, Post
from messages import (
    _queue_body_and_stamp, mark_mass_runs_unsent, mark_queue_copies_unsent,
    mark_unsent,
)

UNSENT_REASON = "automation:unsend_messages"

log = logging.getLogger("of-relay.automation.unsend")

# Per-chat DELETE only works inside OF's ~24h edit window.
_PER_CHAT_WINDOW_H = 24
_DEFAULT_TEXT_HOURS = 9
_DEFAULT_MASS_TEXT_HOURS = 8
# A priced PPV broadcast is never auto-unsent before this: most mass-PPV revenue lands >4h after send.
_MIN_MASS_PRICE_HOURS = 24
_MAX_SWEEP = 200

_MASS_REFRESH_LOOKBACK_DAYS = 30
_MASS_REFRESH_PAGE = 100
_MASS_REFRESH_MAX_PAGES = 50
_MASS_REFRESH_WARM_LOOKBACK_H = 72
_POST_RETRY_BASE_MIN = 15
_POST_RETRY_MAX = 7


def _norm_targets(raw: object) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for t in raw:
        if not isinstance(t, dict):
            continue
        try:
            if t.get("post_id") is not None:
                out.append({
                    "kind": "post",
                    "post_id": int(t["post_id"]),
                    "local_post_id": (
                        int(t["local_post_id"]) if t.get("local_post_id") is not None else None
                    ),
                })
            elif t.get("story_id") is not None:
                out.append({
                    "kind": "story",
                    "story_id": int(t["story_id"]),
                })
            elif isinstance(t.get("hide_upload"), dict):
                hu = t["hide_upload"]
                md5 = hu.get("md5")
                size = hu.get("size")
                if md5 and size is not None:
                    out.append({
                        "kind": "hide_upload",
                        "md5": str(md5),
                        "size": int(size),
                        "exclude_ids": [int(x) for x in (hu.get("exclude_ids") or [])],
                    })
                else:
                    log.warning("unsend_target_bad_hide target=%r — skipped", t)
            elif t.get("queue_id") is not None:
                out.append({
                    "kind": "mass",
                    "queue_id": int(t["queue_id"]),
                    "mass_run_id": (
                        int(t["mass_run_id"]) if t.get("mass_run_id") is not None else None
                    ),
                })
            elif t.get("message_id") is not None and t.get("fan_id") is not None:
                out.append({
                    "kind": "chat",
                    "message_id": int(t["message_id"]),
                    "fan_id": int(t["fan_id"]),
                })
            else:
                log.warning("unsend_target_unroutable target=%r", t)
        except (TypeError, ValueError):
            log.warning("unsend_target_bad_id target=%r — skipped", t)
    return out


def _pos_hours(raw: object, default: float | None) -> float | None:
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return default


@dataclass(frozen=True)
class SweepPlan:
    per_chat: bool
    mass: bool
    text_hours: float
    media_hours: float | None
    mass_text_hours: float | None
    mass_media_hours: float | None
    mass_price_hours: float | None
    price_floored_from: float | None


def sweep_policy(policy: dict) -> SweepPlan:
    m_text = _pos_hours(policy.get("mass_text_hours"),
                        _DEFAULT_MASS_TEXT_HOURS if policy.get("mass_text") else None)
    m_media = _pos_hours(policy.get("mass_media_hours"), None)
    m_price = _pos_hours(policy.get("mass_price_hours"), None)
    floored_from = None
    if m_price is not None and m_price < _MIN_MASS_PRICE_HOURS:
        floored_from, m_price = m_price, float(_MIN_MASS_PRICE_HOURS)
    mass = any(h is not None for h in (m_text, m_media, m_price))
    return SweepPlan(
        per_chat=("text_hours" in policy or "media_hours" in policy) or not mass,
        mass=mass,
        text_hours=_pos_hours(policy.get("text_hours"), _DEFAULT_TEXT_HOURS),
        media_hours=_pos_hours(policy.get("media_hours"), None),
        mass_text_hours=m_text,
        mass_media_hours=m_media,
        mass_price_hours=m_price,
        price_floored_from=floored_from,
    )


def mass_targets(rows) -> list[dict]:
    out: list[dict] = []
    seen_q: set[int] = set()
    for qid_raw, run_id in rows:
        qid = int(qid_raw)
        if qid in seen_q:
            continue
        seen_q.add(qid)
        out.append({
            "kind": "mass", "queue_id": qid,
            "mass_run_id": int(run_id) if run_id is not None else None,
            "from_cache": True,
        })
    return out


async def _sweep_targets(account_id: str, plan: SweepPlan) -> list[dict]:
    text_hours = plan.text_hours
    media_hours = plan.media_hours
    now = datetime.utcnow()
    window_floor = now - timedelta(hours=_PER_CHAT_WINDOW_H)

    media_clause = False
    if media_hours is not None:
        media_clause = and_(
            Message.media_count > 0,
            Message.created_at <= now - timedelta(hours=media_hours),
        )
    text_clause = and_(
        Message.media_count == 0,
        Message.created_at <= now - timedelta(hours=text_hours),
    )

    async with get_session() as s:
        rows = (
            await s.execute(
                select(Message.fan_id, Message.message_id)
                .where(
                    Message.account_id == str(account_id),
                    Message.direction == "out",
                    Message.is_unsent.is_(False),
                    Message.mass_run_id.is_(None),
                    Message.created_at >= window_floor,
                    or_(text_clause, media_clause),
                )
                .order_by(Message.created_at)
                .limit(_MAX_SWEEP)
            )
        ).all()
    return [
        {"kind": "chat", "fan_id": int(r[0]), "message_id": int(r[1])}
        for r in rows
    ]


async def _sweep_mass_targets(account_id: str, plan: SweepPlan) -> list[dict]:
    text_hours = plan.mass_text_hours
    media_hours = plan.mass_media_hours
    price_hours = plan.mass_price_hours
    now = datetime.utcnow()
    classes = []
    if text_hours is not None:
        classes.append(and_(
            MassBroadcastCache.is_free.is_(True),
            MassBroadcastCache.media_count == 0,
            MassBroadcastCache.sent_at <= now - timedelta(hours=text_hours),
        ))
    if media_hours is not None:
        classes.append(and_(
            MassBroadcastCache.media_count > 0,
            MassBroadcastCache.is_free.is_(True),
            MassBroadcastCache.sent_at <= now - timedelta(hours=media_hours),
        ))
    if price_hours is not None:
        classes.append(and_(
            MassBroadcastCache.is_free.is_(False),
            MassBroadcastCache.sent_at <= now - timedelta(hours=price_hours),
        ))
    if not classes:
        return []
    async with get_session() as s:
        rows = (
            await s.execute(
                select(MassBroadcastCache.queue_id, MassRun.id)
                .select_from(MassBroadcastCache)
                .outerjoin(MassRun, and_(
                    MassRun.account_id == MassBroadcastCache.account_id,
                    MassRun.queue_id == MassBroadcastCache.queue_id,
                ))
                .where(
                    MassBroadcastCache.account_id == str(account_id),
                    MassBroadcastCache.sent_at.is_not(None),
                    MassBroadcastCache.is_tip.is_(False),
                    MassBroadcastCache.is_canceled.is_(False),
                    MassBroadcastCache.can_unsend.is_(True),
                    or_(*classes),
                )
                .order_by(MassBroadcastCache.sent_at)
                .limit(_MAX_SWEEP)
            )
        ).all()
    return mass_targets(rows)


def _parse_item_date(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if d.tzinfo is not None:
        d = (d - d.utcoffset()).replace(tzinfo=None)
    return d


@dataclass(frozen=True)
class _PageCursor:
    end_cursor: datetime
    # Advance by rows returned, not page index: OF may return a short page.
    offset: int = 0
    date_mode: bool = False
    fruitless: int = 0
    seen_qids: frozenset[int] = frozenset()


def next_history_page(cur: _PageCursor, resp: object,
                      start: datetime) -> tuple[list[dict], _PageCursor | None]:
    items = (resp.get("items") if isinstance(resp, dict) else None) or []
    seen = set(cur.seen_qids)
    fresh: list[dict] = []
    for it in items:
        try:
            qid = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if qid not in seen:
            seen.add(qid)
            fresh.append(it)
    fruitless = 0 if fresh else cur.fruitless + 1
    if fruitless >= 2:
        return fresh, None
    if not (isinstance(resp, dict) and resp.get("hasMore") and items):
        return fresh, None
    nxt = replace(cur, fruitless=fruitless, seen_qids=frozenset(seen))
    if fresh and not cur.date_mode:
        return fresh, replace(nxt, offset=cur.offset + len(items))
    oldest = None
    for it in items:
        d = _parse_item_date(it.get("date"))
        if d is not None and (oldest is None or d < oldest):
            oldest = d
    if oldest is None or oldest <= start:
        return fresh, None
    step = oldest - timedelta(seconds=1)
    if step >= cur.end_cursor:
        return fresh, None
    return fresh, replace(nxt, date_mode=True, end_cursor=step, offset=0)


async def _refresh_mass_cache(account_id: str, client) -> bool:
    import mass_broadcast_cache as cache
    fetch = getattr(client, "mass_message_history", None)
    if not callable(fetch):
        return True
    async with get_session() as s:
        cached_rows = (
            await s.execute(
                select(func.count())
                .select_from(MassBroadcastCache)
                .where(MassBroadcastCache.account_id == str(account_id))
            )
        ).scalar() or 0
    end = datetime.utcnow()
    lookback = (
        timedelta(hours=_MASS_REFRESH_WARM_LOOKBACK_H)
        if cached_rows
        else timedelta(days=_MASS_REFRESH_LOOKBACK_DAYS)
    )
    start = end - lookback
    fmt = "%Y-%m-%d %H:%M:%S"
    written = 0
    cur = _PageCursor(end_cursor=end)
    try:
        for _ in range(_MASS_REFRESH_MAX_PAGES):
            resp = await asyncio.to_thread(
                fetch, start_date=start.strftime(fmt),
                end_date=cur.end_cursor.strftime(fmt),
                limit=_MASS_REFRESH_PAGE, offset=cur.offset,
            )
            fresh, nxt = next_history_page(cur, resp, start)
            if fresh:
                written += await cache.upsert_many(str(account_id), fresh)
            if nxt is None:
                break
            cur = nxt
        else:
            log.warning(
                "mass_cache_refresh_truncated account=%s hit %d-page cap (%d rows) — "
                "older broadcasts may not be swept this run",
                account_id, _MASS_REFRESH_MAX_PAGES, written,
            )
    except Exception:
        log.error("mass_cache_refresh_failed account=%s — sweeping STALE cache",
                  account_id, exc_info=True)
        return False
    return True


async def _flip_mass_unsent(account_id: str, mass_run_id: int | None) -> int:
    if mass_run_id is None:
        return 0
    return await mark_mass_runs_unsent(account_id, [int(mass_run_id)],
                                       reason=UNSENT_REASON)


async def _flip_queue_copies(account_id: str, queue_id: int | None) -> int:
    if queue_id is None:
        return 0
    body, sent_at = await _queue_body_and_stamp(account_id, int(queue_id))
    copies, _stamped = await mark_queue_copies_unsent(
        account_id, int(queue_id), body=body, sent_at=sent_at,
        reason=UNSENT_REASON)
    return copies


# Runs even with nothing to unsend: a cancel racing an in-flight scrape can leave a copy at is_unsent=0, and a queue is a target only once.
async def _reapply_recent_unsends(account_id: str) -> int:
    since = datetime.utcnow() - timedelta(hours=24)
    async with get_session() as s:
        queues = (await s.execute(
            select(MassRun.queue_id).where(
                MassRun.account_id == str(account_id),
                MassRun.queue_id.is_not(None),
                MassRun.unsent_at.is_not(None),
                MassRun.unsent_at >= since,
            ).distinct()
        )).scalars().all()
    flipped = 0
    for qid in queues:
        try:
            flipped += await _flip_queue_copies(account_id, int(qid))
        except Exception:
            log.warning("unsend re-apply failed account=%s queue=%s",
                        account_id, qid, exc_info=True)
    return flipped


async def _flip_cache_canceled(account_id: str, queue_id: int) -> int:
    async with get_session() as s:
        res = await s.execute(
            update(MassBroadcastCache)
            .where(
                MassBroadcastCache.account_id == str(account_id),
                MassBroadcastCache.queue_id == int(queue_id),
                MassBroadcastCache.is_canceled.is_(False),
            )
            .values(is_canceled=True, can_unsend=False, unsend_seconds=0)
        )
    return res.rowcount or 0


async def _flip_post_deleted(
    account_id: str, of_post_id: int, local_post_id: int | None
) -> int:
    now = datetime.utcnow()
    if local_post_id is not None:
        where = and_(
            Post.account_id == str(account_id),
            Post.id == int(local_post_id),
        )
    else:
        where = and_(
            Post.account_id == str(account_id),
            Post.of_post_id == int(of_post_id),
        )
    async with get_session() as s:
        res = await s.execute(
            update(Post)
            .where(where, Post.status != "deleted")
            .values(status="deleted", updated_at=now)
        )
    return res.rowcount or 0


async def _write_action(account_id: str, target: dict, flipped: int) -> None:
    if target["kind"] == "mass":
        action, target_type, target_id = "unsend_mass", "queue", str(target["queue_id"])
    elif target["kind"] == "post":
        action, target_type, target_id = "delete_post", "post", str(target["post_id"])
    elif target["kind"] == "story":
        action, target_type, target_id = "delete_story", "story", str(target["story_id"])
    elif target["kind"] == "hide_upload":
        action, target_type = "hide_vault_media", "vault_media"
        target_id = str(target.get("hidden_id") or target.get("md5") or "")
    else:
        action, target_type, target_id = "unsend_message", "message", str(target["message_id"])
    async with get_session() as s:
        s.add(Action(
            employee_id=None,
            account_id=str(account_id),
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=json.dumps({**target, "rows_flipped": flipped}, default=str),
        ))


@register("unsend_messages")
async def run(account_id: str, payload: dict, *, run_id: int) -> dict:
    """Unsend targeted messages via the OF API and mirror the result locally.

    Each target is unsent through the window-appropriate endpoint, then its
    `messages.is_unsent` is flipped and an `actions` row recorded. One failing
    target is logged and skipped — it never fails the whole run; a failing
    feed-post delete is also re-queued with a backoff (`_retry_failed_posts`)."""
    payload = payload or {}
    targets = _norm_targets(payload.get("targets"))
    client = None
    mass_refresh_failed = False
    wants_mass = any(t.get("kind") == "mass" for t in targets)
    if not targets:
        policy = payload.get("policy") or {}
        plan = sweep_policy(policy)
        if plan.price_floored_from is not None:
            log.info("unsend mass_price_hours=%.1f floored to %d (a priced PPV lands 47%% "
                     "of its revenue >4h after send)", plan.price_floored_from,
                     _MIN_MASS_PRICE_HOURS)
        wants_mass = plan.mass
        if plan.per_chat:
            targets += await _sweep_targets(account_id, plan)
        if wants_mass:
            if not payload.get("dry_run"):
                client = await asyncio.to_thread(ax._make_client, account_id)
                mass_refresh_failed = not await _refresh_mass_cache(account_id, client)
            targets += await _sweep_mass_targets(account_id, plan)

    if payload.get("dry_run"):
        return {
            "dry_run": True,
            "targets": len(targets),
            "would_unsend": targets,
            "unsent": 0,
            "failed": 0,
            "rows_flipped": 0,
        }

    copies_flipped = 0
    if wants_mass:
        # Runs even with no targets: a queue is a target once, so the cancel-vs-scrape race can only be repaired on a tick with none.
        copies_flipped += await _reapply_recent_unsends(account_id)

    if not targets:
        return {"targets": 0, "unsent": 0, "failed": 0, "rows_flipped": 0,
                "copies_flipped": copies_flipped,
                "mass_refresh_failed": mass_refresh_failed}

    if client is None:
        client = await asyncio.to_thread(ax._make_client, account_id)

    unsent = 0
    failed = 0
    rows_flipped = 0
    failed_posts: list[dict] = []
    for t in targets:
        try:
            if t["kind"] == "mass":
                await asyncio.to_thread(client.cancel_scheduled, t["queue_id"])
                flipped = await _flip_mass_unsent(account_id, t.get("mass_run_id"))
                copies_flipped += await _flip_queue_copies(
                    account_id, t.get("queue_id"))
                if t.get("from_cache"):
                    flipped += await _flip_cache_canceled(account_id, t["queue_id"])
                try:
                    from audiences import close_funnel_discovery_for_queue
                    await close_funnel_discovery_for_queue(
                        account_id, queue_id=t.get("queue_id"),
                        mass_run_id=t.get("mass_run_id"))
                except Exception:
                    log.warning("close_funnel_discovery failed account=%s queue=%s",
                                account_id, t.get("queue_id"), exc_info=True)
            elif t["kind"] == "post":
                await asyncio.to_thread(client.delete_post, t["post_id"])
                flipped = await _flip_post_deleted(
                    account_id, t["post_id"], t.get("local_post_id")
                )
            elif t["kind"] == "story":
                await asyncio.to_thread(client.delete_story, t["story_id"])
                flipped = 0
            elif t["kind"] == "hide_upload":
                hit = await asyncio.to_thread(
                    client.vault_media_lookup_hash, t["md5"], t["size"]
                )
                vid = (hit or {}).get("id") or (hit or {}).get("mediaId")
                # exclude_ids (the source item) are never hidden, guarding against a hash collision.
                if vid is not None and int(vid) not in t.get("exclude_ids", []):
                    await asyncio.to_thread(client.hide_vault_media, [int(vid)])
                    t["hidden_id"] = int(vid)
                    flipped = 1
                else:
                    flipped = 0
            else:
                await asyncio.to_thread(
                    client.unsend_message, t["message_id"], t["fan_id"]
                )
                flipped = await mark_unsent(
                    account_id, t["message_id"], fan_id=t["fan_id"],
                    reason=UNSENT_REASON,
                )
            await _write_action(account_id, t, flipped)
            unsent += 1
            rows_flipped += flipped
        except Exception:
            failed += 1
            if t["kind"] == "post":
                failed_posts.append(t)
            log.warning(
                "unsend_failed account=%s target=%r", account_id, t, exc_info=True
            )

    post_retry_job_id = await _retry_failed_posts(account_id, failed_posts, payload)

    return {
        "targets": len(targets),
        "unsent": unsent,
        "failed": failed,
        "rows_flipped": rows_flipped,
        "copies_flipped": copies_flipped,
        "mass_refresh_failed": mass_refresh_failed,
        "post_retry_job_id": post_retry_job_id,
    }


async def _retry_failed_posts(account_id: str, failed: list[dict], payload: dict) -> int | None:
    if not failed:
        return None
    attempt = int(payload.get("post_retry") or 0)
    if attempt >= _POST_RETRY_MAX:
        log.error("unsend: post delete retries spent account=%s posts=%s",
                  account_id, [t["post_id"] for t in failed])
        return None
    return await ax.enqueue_job(
        account_id, "unsend_messages",
        payload={"targets": [{"post_id": t["post_id"], "local_post_id": t.get("local_post_id")} for t in failed],
                 "post_retry": attempt + 1},
        run_at=datetime.utcnow() + timedelta(minutes=_POST_RETRY_BASE_MIN * 2 ** attempt),
    )
