from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Literal, NamedTuple

from curl_cffi import requests as _cc
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax
import fansly_backend  # noqa: F401
import platforms
from automations.scrape_chats_decide import history_plan, hold_ascending, inbound_since, new_unread_marker
from automation_executor import _media_ids, _parse_iso, _strip_html, _to_cents
from automation_registry import register
from db import of_writer
from db.engine import get_session
from db.models import Chat, Fan, Message, ScrapeHistory, SkipList, Transaction, is_paid_ratchet
from jsonsafe import dump_capped
import of_call_counter
import of_pacing
from of_client import OFAPIError, OFClient, proxy_refused

log = logging.getLogger("of-relay.automation")

# OF ignores `limit` and returns fewer than asked: bound loops by message count and stop on hasMore=False.
_SCRAPE_PAGE_SIZE = 50
_SCRAPE_MAX_PAGES = 40
_SCRAPE_RECENT_CAP = 100
_SCRAPE_OLDEST_CAP = 100
_SCRAPE_CHAT_LIMIT = 100
_PAGE_SLEEP_S = 0.3


def _sweep_fail_fast() -> int:
    try:
        n = int(os.environ.get("SCRAPE_SWEEP_FAIL_FAST", "5"))
    except ValueError:
        return 5
    return n if n > 0 else 5


def _sweep_budget_s() -> float:
    try:
        return float(os.environ.get("SCRAPE_SWEEP_BUDGET_S", "900"))
    except ValueError:
        return 900.0


_KEEP_GAP = object()


def _gap_cols(gap: tuple[int, int] | None) -> dict[str, int | None]:
    return {"gap_after_id": gap[0] if gap else None, "gap_before_id": gap[1] if gap else None}


_clock = time.monotonic

_attempted_at: dict[tuple[str, int], datetime] = {}


def _eager_history() -> bool:
    return os.environ.get("SCRAPE_EAGER_HISTORY", "").strip().lower() in ("1", "true", "yes", "on")


def _silent_mass_page(rows: list[dict], own_user_id: str) -> bool:
    return bool(rows) and all(
        str((m.get("fromUser") or {}).get("id")) == str(own_user_id) and bool(m.get("isFromQueue"))
        for m in rows)


async def local_unread_count(account_id: str, fan_id: int) -> int | None:
    async with get_session() as s:
        return (await s.execute(select(Chat.unread_count).where(
            Chat.account_id == str(account_id), Chat.fan_id == int(fan_id))
        )).scalar_one_or_none()


def _systemic_failure(e: BaseException) -> bool:
    status = of_pacing.upstream(e)[0]
    if isinstance(status, int):
        return status == 429 or 500 <= status < 600
    return proxy_refused(e) or isinstance(e, (_cc.exceptions.ConnectionError,
                                              _cc.exceptions.Timeout))




async def _upsert_message(
    s, account_id: str, fan_id: int, own_user_id: str, m: dict, *, peek_head: bool = False,
) -> None:
    message_id = m.get("id")
    if message_id is None:
        return
    from_user = m.get("fromUser") or {}
    from_id = from_user.get("id")
    direction = "out" if str(from_id) == str(own_user_id) else "in"

    created_at = _parse_iso(m.get("createdAt")) or datetime.utcnow()
    price_cents = _to_cents(m.get("price"))
    media_ids = _media_ids(m.get("media"))
    is_paid = m.get("isOpened") if price_cents > 0 else None
    sender_name = (from_user.get("name") or from_user.get("username") or "")[:255]
    body = m.get("text") or ""
    raw = dump_capped(m)

    updates = {
        "body": body,
        # True never reverts: writing is_paid straight through erased real sales once a purchase aged off the feed.
        "is_paid": is_paid_ratchet(is_paid),
        "is_tip": bool(m.get("isTip")),
        "is_unsent": Message.is_unsent | bool(m.get("isUnsent")),
        "media_count": int(m.get("mediaCount") or 0),
        "price_cents": case((func.coalesce(Message.price_cents, 0) == 0, price_cents),
                            else_=Message.price_cents),
        "media_ids": case((Message.media_ids == "[]", json.dumps(media_ids)),
                          else_=Message.media_ids),
        "raw_json": raw,
    }
    if peek_head and direction == "in":
        await s.execute(update(Message).where(
            Message.account_id == str(account_id), Message.fan_id == int(fan_id),
            Message.message_id == int(message_id),
        ).values(**updates))
        return

    stmt = (
        sqlite_insert(Message)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            message_id=int(message_id),
            direction=direction,
            sender_name=sender_name,
            body=body,
            media_ids=json.dumps(media_ids),
            media_count=int(m.get("mediaCount") or 0),
            price_cents=price_cents,
            is_paid=is_paid,
            is_tip=bool(m.get("isTip")),
            purchased_at=_parse_iso(m.get("openedAt")) if is_paid else None,
            is_unsent=bool(m.get("isUnsent")),
            raw_json=raw,
            created_at=created_at,
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id", "message_id"],
            set_=updates,
        )
    )
    await s.execute(stmt)


async def _upsert_page(conn, items: list) -> list:
    for account_id, fan_id, own_user_id, rows, peek_head in items:
        for m in rows:
            await _upsert_message(conn, account_id, fan_id, own_user_id, m,
                                  peek_head=peek_head)
    return [None] * len(items)


async def save_thread_page(
    account_id: str, fan_id: int, own_user_id: str, rows: list[dict], *, peek_head: bool = False,
) -> None:
    try:
        await of_writer.write(_upsert_page, (str(account_id), int(fan_id), str(own_user_id), rows, peek_head),
                              key=(str(account_id), int(fan_id)))
    except Exception:  # noqa: BLE001
        log.warning("chat_history_save_failed account=%s chat=%s", account_id, fan_id, exc_info=True)


async def upsert_message(account_id: str, fan_id: int, own_user_id: str, m: dict) -> None:
    async with get_session() as s:
        await _upsert_message(s, account_id, fan_id, own_user_id, m)


async def _upsert_fan_identity(
    s,
    account_id: str,
    fan_id: int,
    own_user_id: str,
    with_user: dict | None,
    collected: list[dict],
    *,
    last_in_at: datetime | None,
    last_out_at: datetime | None,
    is_muted: bool | None = None,
) -> None:
    info: dict = {}
    if with_user and with_user.get("id"):
        info = with_user
    else:
        for m in collected:
            fu = m.get("fromUser") or {}
            if fu.get("id") and str(fu.get("id")) != str(own_user_id):
                info = fu
                break

    insert_extra: dict[str, Any] = {}
    if last_in_at is not None:
        insert_extra["last_message_received_at"] = last_in_at
    if last_out_at is not None:
        insert_extra["last_message_sent_at"] = last_out_at

    update_set: dict[str, Any] = {"updated_at": datetime.utcnow()}
    for col, val in (
        ("of_username", info.get("username")),
        ("of_display_name", info.get("name")),
        ("avatar_url", info.get("avatar")),
    ):
        if val is not None:
            update_set[col] = val
    if last_in_at is not None:
        update_set["last_message_received_at"] = case(
            (Fan.last_message_received_at.is_(None) | (Fan.last_message_received_at < last_in_at), last_in_at),
            else_=Fan.last_message_received_at,
        )
    if last_out_at is not None:
        update_set["last_message_sent_at"] = case(
            (Fan.last_message_sent_at.is_(None) | (Fan.last_message_sent_at < last_out_at), last_out_at),
            else_=Fan.last_message_sent_at,
        )
    if is_muted is not None:
        insert_extra["is_muted"] = bool(is_muted)
        update_set["is_muted"] = bool(is_muted)
    from automations._common import source_self_heal_set
    update_set.update(source_self_heal_set(
        info.get("subscribedOn"), info.get("subscribedBy")))

    stmt = (
        sqlite_insert(Fan)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            of_username=info.get("username"),
            of_display_name=info.get("name"),
            avatar_url=info.get("avatar"),
            source=(
                "fan" if info.get("subscribedOn") else
                "creator_we_follow" if info.get("subscribedBy") else
                "onlyfans"
            ),
            **insert_extra,
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_=update_set,
        )
    )
    await s.execute(stmt)

    if is_muted is not None:
        await _reconcile_muted_skip(s, account_id, fan_id, bool(is_muted))


async def _reconcile_muted_skip(s, account_id: str, fan_id: int, is_muted: bool) -> None:
    from automations._common import MUTED_CREATOR_REASON
    source = (await s.execute(
        select(Fan.source).where(
            Fan.account_id == str(account_id), Fan.fan_id == int(fan_id))
    )).scalar_one_or_none()
    if is_muted and (source or "") == "creator_we_follow":
        await s.execute(
            sqlite_insert(SkipList)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    reason=MUTED_CREATOR_REASON, added_at=datetime.utcnow())
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"reason": MUTED_CREATOR_REASON, "added_at": datetime.utcnow()},
            )
        )
    elif not is_muted:
        await s.execute(
            delete(SkipList).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id == int(fan_id),
                SkipList.reason == MUTED_CREATOR_REASON,
            )
        )


def _history_matches(snapshot: tuple[int | None, tuple[int, int] | None]):
    cursor, gap = snapshot
    return (
        ScrapeHistory.last_message_id.is_(cursor)
        & ScrapeHistory.gap_after_id.is_(gap[0] if gap else None)
        & ScrapeHistory.gap_before_id.is_(gap[1] if gap else None)
    )


async def _upsert_chat_and_history(
    s,
    account_id: str,
    fan_id: int,
    *,
    snapshot: tuple[int | None, tuple[int, int] | None],
    newest_id: int | None,
    newest_text: str | None,
    newest_at: datetime | None,
    deferred: bool = False,
    new_unread: bool = False,
    gap: tuple[int, int] | None = None,
) -> bool | None:
    if newest_id and newest_id != snapshot[0]:
        chat_stmt = (
            sqlite_insert(Chat)
            .values(
                account_id=str(account_id),
                fan_id=int(fan_id),
                last_message_id=newest_id,
                last_message_at=newest_at,
                last_message_preview=newest_text,
                **({"unread_count": 1} if new_unread else {}),
            )
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={
                    "last_message_id": newest_id,
                    "last_message_at": newest_at,
                    "last_message_preview": newest_text,
                },
                where=(
                    (Chat.last_message_id.is_(None))
                    | (Chat.last_message_id < newest_id)
                ),
            )
        )
        await s.execute(chat_stmt)

    now = datetime.utcnow()
    if deferred:
        hist_stmt = (
            sqlite_insert(ScrapeHistory)
            .values(account_id=str(account_id), fan_id=int(fan_id),
                    last_scrape_at=now, history_deferred_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"last_scrape_at": now, "history_deferred_at": now},
                where=_history_matches(snapshot),
            )
        )
        return (await s.execute(hist_stmt.returning(ScrapeHistory.gap_before_id.is_not(None)))).scalar_one_or_none()

    hist_stmt = (
        sqlite_insert(ScrapeHistory)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            last_message_id=newest_id,
            last_message_text=newest_text,
            last_scrape_at=now,
            history_deferred_at=None,
            **_gap_cols(gap),
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_={
                "last_message_id": newest_id,
                **({"last_message_text": newest_text} if newest_text is not None else {}),
                "last_scrape_at": now,
                "history_deferred_at": None,
                **_gap_cols(gap),
            },
            where=_history_matches(snapshot),
        )
    )
    return (await s.execute(hist_stmt.returning(ScrapeHistory.gap_before_id.is_not(None)))).scalar_one_or_none()


class _RecentEnd(NamedTuple):
    rows: list[dict]
    deferred: bool
    reached: bool
    rate_limited: bool


async def _fetch_recent_end(
    client: OFClient, chat_id: int, *,
    last_seen_id: int | None, page_size: int, cap: int, max_pages: int,
    defer_if: Callable[[list[dict]], bool] | None = None,
    before_id: int | None = None, stop_on_429: bool = False,
    deadline: float | None = None,
) -> _RecentEnd:
    collected: list[dict] = []
    cursor: int | None = before_id
    pages = 0
    deferred = reached = False
    while pages < max_pages and len(collected) < cap:
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            break
        timer = asyncio.timeout_at(deadline)
        try:
            async with timer:
                resp = await asyncio.to_thread(
                    client.get_messages, chat_id,
                    limit=page_size, order="desc", before_id=cursor, peek=True,
                )
        except Exception as e:
            if timer.expired():
                break
            if not stop_on_429 or (not collected and before_id is None) or of_pacing.upstream(e)[0] != 429:
                raise
            return _RecentEnd(collected, deferred, False, True)
        rows = resp.get("list") or []
        if not rows:
            reached = True
            break
        has_more = bool(resp.get("hasMore"))
        if pages == 0:
            deferred = has_more and defer_if is not None and defer_if(rows)
        pages += 1
        stop = full = False
        for i, m in enumerate(rows):
            mid = m.get("id")
            if mid is None:
                continue
            if last_seen_id is not None and int(mid) <= int(last_seen_id):
                stop = True
                break
            collected.append(m)
            if len(collected) >= cap:
                full = i < len(rows) - 1
                break
        if stop or (not has_more and not full):
            reached = True
            break
        if deferred or not has_more:
            break
        cursor = rows[-1].get("id")
        if cursor is None:
            break
        await asyncio.sleep(_PAGE_SLEEP_S)
    return _RecentEnd(collected, deferred, reached, False)


async def _fetch_oldest_end(
    client: OFClient, chat_id: int, *,
    page_size: int, cap: int, max_pages: int,
) -> list[dict]:
    collected: list[dict] = []
    offset = 0
    pages = 0
    while pages < max_pages and len(collected) < cap:
        resp = await asyncio.to_thread(
            client.get_messages, chat_id,
            limit=page_size, order="asc", offset=offset,
        )
        rows = resp.get("list") or []
        if not rows:
            break
        pages += 1
        for m in rows:
            if m.get("id") is None:
                continue
            collected.append(m)
            if len(collected) >= cap:
                break
        if not resp.get("hasMore"):
            break
        offset += len(rows)
        await asyncio.sleep(_PAGE_SLEEP_S)
    return collected


async def _stamp_scrape_history(account_id: str, fan_id: int, *, gone: bool = False,
                                clear_deferred: bool = False, gap: Any = _KEEP_GAP,
                                snapshot: tuple[int | None, tuple[int, int] | None] | None = None) -> bool | None:
    now = datetime.utcnow()
    set_ = ({"last_scrape_at": now, "history_deferred_at": None} if gone or clear_deferred
            else {"last_scrape_at": now})
    gap_cols = {} if gap is _KEEP_GAP else _gap_cols(gap)
    set_.update(gap_cols)
    async with get_session() as s:
        result = await s.execute(
            sqlite_insert(ScrapeHistory)
            .values(account_id=str(account_id), fan_id=int(fan_id), last_scrape_at=now, **gap_cols)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_=set_,
                where=_history_matches(snapshot) if snapshot is not None else None,
            )
            .returning(ScrapeHistory.gap_before_id.is_not(None))
        )
        return result.scalar_one_or_none()


class ScrapeChunk(NamedTuple):
    inserted: int
    seen: int
    rate_limited: bool
    gap_left: bool
    history_saved: bool


def _scrape_chunk_result(inserted: int, seen: int, rate_limited: bool,
                         saved_gap_left: bool | None) -> ScrapeChunk:
    return ScrapeChunk(inserted, seen, rate_limited, saved_gap_left is not False, saved_gap_left is not None)


async def _scrape_one_chat(
    account_id: str,
    own_user_id: str,
    client: OFClient,
    chat_id: int,
    with_user: dict | None,
    *,
    page_size: int,
    max_pages: int,
    recent_cap: int = _SCRAPE_RECENT_CAP,
    oldest_cap: int = _SCRAPE_OLDEST_CAP,
    is_muted: bool | None = None,
    may_defer: bool = False,
    of_unread: bool | None = None,
    mode: Literal["sweep", "peek", "pull"] = "sweep",
    after_click_at: datetime | None = None,
    deadline: float | None = None,
) -> ScrapeChunk:
    fan_id = int(chat_id)
    unread_gate = mode == "sweep" and platforms.Lack.HISTORY_UNREAD_GATE not in platforms.for_account(account_id).lacks

    async with get_session() as s:
        hist = await s.get(ScrapeHistory, (account_id, fan_id))
        last_seen_id = hist.last_message_id if hist else None
        was_deferred = hist is not None and hist.history_deferred_at is not None
        gap = ((hist.gap_after_id, hist.gap_before_id)
               if hist is not None and hist.gap_before_id is not None
               and hist.gap_after_id is not None else None)

    snapshot = last_seen_id, gap
    first_scrape = last_seen_id is None
    defer_if: Callable[[list[dict]], bool] | None = None
    n_start = await local_unread_count(account_id, fan_id) if first_scrape and unread_gate else None
    plan = history_plan(first_scrape=first_scrape, unread_gate=unread_gate, was_deferred=was_deferred,
                        local_unread=n_start, of_unread=of_unread, after_click=after_click_at is not None)
    n_now = n_start
    if may_defer and first_scrape:
        async with get_session() as s:
            engaged = (await s.execute(
                select(Message.message_id).where(
                    Message.account_id == str(account_id), Message.fan_id == fan_id,
                    Message.direction == "in").limit(1)
            )).first() is not None
            engaged = engaged or (await s.execute(
                select(Transaction.id).where(
                    Transaction.account_id == str(account_id), Transaction.fan_id == fan_id,
                    Transaction.amount_cents > 0).limit(1)
            )).first() is not None
        if not engaged:
            defer_if = lambda rows: _silent_mass_page(rows, own_user_id)  # noqa: E731
    if plan == "page1":
        defer_if = lambda rows: True  # noqa: E731
    walk = await _fetch_recent_end(
        client, chat_id,
        last_seen_id=last_seen_id, page_size=page_size,
        cap=recent_cap, max_pages=max_pages, defer_if=defer_if,
        stop_on_429=mode == "pull", deadline=deadline,
    )
    collected, deferred = walk.rows, walk.deferred
    rate_limited = walk.rate_limited

    if first_scrape:
        if mode != "sweep" and not walk.reached and not deferred and collected:
            gap = (0, min(int(m["id"]) for m in collected))
    elif not walk.reached and collected:
        gap = (gap[0] if gap else last_seen_id, min(int(m["id"]) for m in collected))
    elif gap and not rate_limited:
        filled = await _fetch_recent_end(
            client, chat_id, last_seen_id=gap[0], before_id=gap[1], page_size=page_size,
            cap=recent_cap, max_pages=max_pages, stop_on_429=mode == "pull", deadline=deadline,
        )
        rate_limited = filled.rate_limited
        have = {int(m["id"]) for m in collected}
        collected = collected + [m for m in filled.rows if int(m["id"]) not in have]
        if filled.reached:
            gap = None
        elif filled.rows:
            gap = (gap[0], min(int(m["id"]) for m in filled.rows))

    needs_oldest = first_scrape and not walk.reached and not deferred and mode == "sweep"
    if needs_oldest:
        deferred = plan != "both_ends"
        if not deferred:
            newer_inbound = inbound_since(collected, fan_id, after_click_at)
            await asyncio.sleep(_PAGE_SLEEP_S)
            n_now = await local_unread_count(account_id, fan_id) if unread_gate else None
            deferred = hold_ascending(unread_gate=unread_gate, local_unread=n_now, initial_unread=n_start,
                                      of_unread=of_unread, after_click=after_click_at is not None,
                                      newer_inbound=newer_inbound)

    if needs_oldest and not deferred:
        oldest = await _fetch_oldest_end(
            client, chat_id,
            page_size=page_size, cap=oldest_cap, max_pages=max_pages,
        )
        if collected:
            after_id = max((int(m["id"]) for m in oldest), default=0)
            before_id = min(int(m["id"]) for m in collected)
            if after_id + 1 < before_id:
                gap = (after_id, before_id)
        seen_ids = {int(m["id"]) for m in collected if m.get("id") is not None}
        for m in oldest:
            mid = m.get("id")
            if mid is not None and int(mid) not in seen_ids:
                seen_ids.add(int(mid))
                collected.append(m)

    if not collected:
        saved_gap_left = await _stamp_scrape_history(account_id, fan_id, clear_deferred=not may_defer,
                                                     gap=gap, snapshot=snapshot)
        if is_muted is not None:
            async with get_session() as s:
                await s.execute(
                    update(Fan)
                    .where(Fan.account_id == str(account_id), Fan.fan_id == fan_id)
                    .values(is_muted=bool(is_muted))
                )
                await _reconcile_muted_skip(s, account_id, fan_id, bool(is_muted))
        return _scrape_chunk_result(0, 0, rate_limited, saved_gap_left)

    ids = [int(m["id"]) for m in collected if m.get("id") is not None]
    newest_id = last_seen_id or 0
    newest_at: datetime | None = None
    newest_text: str | None = None
    last_in_at: datetime | None = None
    last_out_at: datetime | None = None
    for m in collected:
        mid = int(m["id"]) if m.get("id") is not None else 0
        at = _parse_iso(m.get("createdAt"))
        from_id = (m.get("fromUser") or {}).get("id")
        is_out = str(from_id) == str(own_user_id)
        if mid > newest_id:
            newest_id = mid
            newest_at = at
            newest_text = _strip_html(m.get("text") or "")[:200]
        if at is not None:
            if is_out:
                last_out_at = at if last_out_at is None else max(last_out_at, at)
            else:
                last_in_at = at if last_in_at is None else max(last_in_at, at)

    async with get_session() as s:
        existing = set()
        if ids:
            res = await s.execute(
                select(Message.message_id).where(
                    Message.account_id == account_id,
                    Message.fan_id == fan_id,
                    Message.message_id.in_(ids),
                )
            )
            existing = {r[0] for r in res}
        inserted = sum(1 for i in ids if i not in existing)

        await _upsert_fan_identity(
            s, account_id, fan_id, own_user_id, with_user, collected if first_scrape else walk.rows,
            last_in_at=last_in_at, last_out_at=last_out_at,
            is_muted=is_muted,
        )
        for m in collected:
            await _upsert_message(s, account_id, fan_id, own_user_id, m)
        from attribution import adopt_thread_placeholders
        await adopt_thread_placeholders(s, account_id=str(account_id),
                                        fan_id=int(fan_id))
        saved_gap_left = await _upsert_chat_and_history(
            s, account_id, fan_id,
            snapshot=snapshot, newest_id=newest_id, newest_text=newest_text, newest_at=newest_at,
            deferred=deferred, gap=gap,
            new_unread=new_unread_marker(deferred=deferred, unread_gate=unread_gate,
                                         local_unread=n_now, of_unread=of_unread),
        )

    return _scrape_chunk_result(inserted, len(collected), rate_limited, saved_gap_left)


DEFERRED_HISTORY_CALLER = "auto:scrape_chats:deferred_history"


@register("scrape_chats")
async def _automation_scrape_chats(
    account_id: str, payload: dict, *, run_id: int
) -> dict:
    client = await asyncio.to_thread(ax._make_client, account_id)
    own_user_id = client.user_id

    def _limit(name: str, default: int) -> int:
        v = int(payload.get(name) or 0)
        return v if v > 0 else default
    page_size = _limit("page_size", _SCRAPE_PAGE_SIZE)
    max_pages = _limit("max_pages", _SCRAPE_MAX_PAGES)
    recent_cap = _limit("recent_cap", _SCRAPE_RECENT_CAP)
    oldest_cap = _limit("oldest_cap", _SCRAPE_OLDEST_CAP)

    explicit = payload.get("chat_ids") or payload.get("fan_ids")
    after_click_at = _parse_iso(payload.get("after_click_at")) if explicit else None
    if "after_click_at" in payload and after_click_at is None:
        raise ValueError("after_click_at requires an explicit scrape and an ISO timestamp")
    targets: list[tuple[int, dict | None, bool | None, bool | None]] = []
    if explicit:
        targets = [(int(c), None, None, None) for c in explicit]
    else:
        # OF /chats returns ~10 per page regardless of limit: paginate by offset until limit or hasMore is false.
        limit = int(payload.get("limit") or _SCRAPE_CHAT_LIMIT)
        seen_chat_ids: set[int] = set()
        offset = 0
        for _ in range(_SCRAPE_MAX_PAGES):
            if len(targets) >= limit:
                break
            page = await asyncio.to_thread(
                client.list_chats, limit=_SCRAPE_PAGE_SIZE, offset=offset,
                order="recent",
                # Full withUser incl. subscribedOn/subscribedBy so the fan source can be classified and self-healed.
                skip_users=None,
            )
            rows = page.get("list") or []
            if not rows:
                break
            for ch in rows:
                wu = ch.get("withUser") or {}
                cid = wu.get("id") or ch.get("id")
                if cid is None or int(cid) in seen_chat_ids:
                    continue
                seen_chat_ids.add(int(cid))
                # isMutedNotifications is on the top-level chat object, not withUser.
                targets.append((int(cid), wu, bool(ch.get("isMutedNotifications")),
                                bool(ch.get("hasUnread"))
                                or int(ch.get("unreadMessagesCount") or 0) > 0))
            offset += len(rows)
            if page.get("hasMore") is False:
                break
        targets = targets[:limit]

    chats_scanned = 0
    chats_failed = 0
    chats_broken = 0
    broken_err: Exception | None = None
    systemic_run = 0
    fail_fast = _sweep_fail_fast()
    may_defer = not payload and not _eager_history()
    mode = "peek" if payload.get("peek_only") else "sweep"
    messages_inserted = 0
    messages_seen = 0
    deferred_ids: set[int] = set()
    budget_s = 0.0 if explicit else _sweep_budget_s()
    started = _clock()
    chats_left = 0
    if budget_s > 0 and targets:
        async with get_session() as s:
            last = dict((await s.execute(select(ScrapeHistory.fan_id, ScrapeHistory.last_scrape_at).where(
                ScrapeHistory.account_id == account_id,
                ScrapeHistory.fan_id.in_([c for c, *_ in targets]),
            ))).all())
        for c, *_ in targets:
            tried = _attempted_at.get((account_id, c))
            if tried is not None and (last.get(c) is None or tried > last[c]):
                last[c] = tried
        targets.sort(key=lambda t: (t[0] in last, last.get(t[0]) or datetime.min))
    if explicit and targets:
        async with get_session() as s:
            deferred_ids = set((await s.execute(select(ScrapeHistory.fan_id).where(
                ScrapeHistory.account_id == account_id,
                ScrapeHistory.fan_id.in_([c for c, *_ in targets]),
                ScrapeHistory.history_deferred_at.is_not(None),
            ))).scalars().all())
    for n, (chat_id, with_user, is_muted, of_unread) in enumerate(targets):
        if budget_s > 0 and n and _clock() - started >= budget_s:
            chats_left = len(targets) - n
            log.info("scrape_sweep_budget account=%s stopped after %ds: %d of %d chats left",
                     account_id, int(budget_s), chats_left, len(targets))
            break
        try:
            with (of_call_counter.caller(DEFERRED_HISTORY_CALLER) if chat_id in deferred_ids
                  else contextlib.nullcontext()):
                chunk = await _scrape_one_chat(
                    account_id, own_user_id, client, chat_id, with_user,
                    page_size=page_size, max_pages=max_pages,
                    recent_cap=recent_cap, oldest_cap=oldest_cap,
                    is_muted=is_muted, may_defer=may_defer, of_unread=of_unread,
                    mode=mode, after_click_at=after_click_at,
                )
            ins, seen = chunk[:2]
            messages_inserted += ins
            messages_seen += seen
            chats_scanned += 1
            systemic_run = 0
            _attempted_at.pop((account_id, chat_id), None)
        except Exception as e:
            chats_failed += 1
            status = getattr(getattr(e, "response", None), "status_code", None)
            # 404 = fan gone, not transient: stamp scrape_history so autoscrape stops re-enqueueing the chat every pass.
            if isinstance(e, OFAPIError) and status == 404:
                log.info("scrape_chat_gone account=%s chat=%s (404 — fan gone; "
                         "stamping scrape_history)", account_id, chat_id)
                _attempted_at.pop((account_id, chat_id), None)
                try:
                    await _stamp_scrape_history(account_id, int(chat_id), gone=True)
                except Exception:
                    log.warning("stamp_scrape_history failed account=%s chat=%s",
                                account_id, chat_id, exc_info=True)
            else:
                chats_broken += 1
                broken_err = e
                _attempted_at[(account_id, chat_id)] = datetime.utcnow()
                systemic_run = systemic_run + 1 if _systemic_failure(e) else 0
                log.warning(
                    "scrape_chat_failed account=%s chat=%s",
                    account_id, chat_id, exc_info=True,
                )
                if not payload and ((not chats_scanned and chats_broken >= fail_fast)
                                    or systemic_run >= fail_fast):
                    break
        await asyncio.sleep(_PAGE_SLEEP_S)

    out = {
        "targets": len(targets),
        "chats_scanned": chats_scanned,
        "chats_failed": chats_failed,
        "messages_inserted": messages_inserted,
        "messages_seen": messages_seen,
    }
    if chats_left:
        out["budget_stopped"] = True
        out["chats_left"] = chats_left
    if chats_broken and not chats_scanned:
        if payload and len(targets) == 1 and broken_err is not None:
            raise broken_err
        raise RuntimeError(f"{'full sweep' if not payload else 'scrape'} scraped 0 of {len(targets)} chats: "
                           f"{chats_broken} failed of the first {chats_failed} of {len(targets)}")
    if not payload:
        if systemic_run >= fail_fast:
            raise RuntimeError(f"full sweep stopped after {systemic_run} systemic failures in a row: "
                               f"scraped {chats_scanned} of {len(targets)}")
        out["full_sweep"] = True
    return out


@register("scrape_fan")
async def _automation_scrape_fan(
    account_id: str, payload: dict, *, run_id: int
) -> dict:
    if not (payload.get("chat_ids") or payload.get("fan_ids")):
        return {"skipped": "no_fan_ids"}
    return await _automation_scrape_chats(account_id, payload, run_id=run_id)
