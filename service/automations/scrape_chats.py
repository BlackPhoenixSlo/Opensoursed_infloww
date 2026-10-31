"""service/automations/scrape_chats.py — Automation 01: scrape_chats (the reference).

Moved out of automation_executor unchanged. The client comes from
`ax._make_client`, read at call time (tests patch it on ax). The few names still
read via the executor stay readable as `automation_executor.<name>` (its
_SCRAPE_NAMES __getattr__), but the calls in this file look them up HERE: patch
`automations.scrape_chats.<name>`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import automation_executor as ax  # _make_client seam (tests patch ax._make_client)
from automation_executor import _media_ids, _parse_iso, _strip_html, _to_cents
from automation_registry import register
from db.engine import get_session
from db.models import Chat, Fan, Message, ScrapeHistory, SkipList, is_paid_ratchet
from jsonsafe import dump_capped
from of_client import OFAPIError, OFClient

log = logging.getLogger("of-relay.automation")

# scrape_chats paging — OF's Fast Fetch defaults.
# OF ignores `limit` and returns FEWER than asked, so every loop is bounded by a
# message COUNT cap (never by an assumed page size) and stops on hasMore=False.
_SCRAPE_PAGE_SIZE = 50
_SCRAPE_MAX_PAGES = 40         # safety ceiling per end per chat (count caps bound it first)
_SCRAPE_RECENT_CAP = 100       # newest-end messages pulled each scrape (first/last-100 window)
_SCRAPE_OLDEST_CAP = 100       # convo-start messages, grabbed ONCE on the first scrape
_SCRAPE_CHAT_LIMIT = 100       # how many sidebar chats one all-chats sweep covers (paginated 10/page)
_PAGE_SLEEP_S = 0.3            # inter-page / inter-chat politeness gap (matches of_client)


# ── Automation 01: scrape_chats (the reference) ──────────────────────
#
# Spec: one_section_of_automations/01_scrape_chats.md + its network-rewrite
# mapping (DOM → signed OF REST). DOM scraping is GONE — we page
# `GET /api2/v2/chats/{id}/messages` via of_client and write
# messages/chats/fans + scrape_history. Fast-skip is by `scrape_history`
# last_message_id (OF ids are monotonic), stronger than the legacy text snapshot.


async def _upsert_message(
    s, account_id: str, fan_id: int, own_user_id: str, m: dict
) -> None:
    """Upsert one OF message row. Unlike the WS transcoder (which defers
    OUTBOUND to send-time because the event lacks a recipient), the scrape knows
    the chat partner — fan_id is the chat id — so it persists BOTH directions.
    Direction is 'out' when the sender is us, else 'in'. Idempotent via the
    composite PK; on conflict we refresh the fields OF can flip after the fact
    (body edits, is_paid after unlock)."""
    message_id = m.get("id")
    if message_id is None:
        return
    from_user = m.get("fromUser") or {}
    from_id = from_user.get("id")
    direction = "out" if str(from_id) == str(own_user_id) else "in"

    created_at = _parse_iso(m.get("createdAt")) or datetime.utcnow()
    price_cents = _to_cents(m.get("price"))
    media_ids = _media_ids(m.get("media"))
    is_paid = m.get("isOpened") if price_cents > 0 else None  # NULL = free message
    sender_name = (from_user.get("name") or from_user.get("username") or "")[:255]
    body = m.get("text") or ""
    raw = dump_capped(m)

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
            set_={
                "body": body,
                # True never reverts — see is_paid_ratchet. Writing `is_paid`
                # straight through here erased real sales once a Fansly
                # purchase aged off the notifications feed.
                "is_paid": is_paid_ratchet(is_paid),
                "is_tip": bool(m.get("isTip")),
                "is_unsent": bool(m.get("isUnsent")),
                "media_count": int(m.get("mediaCount") or 0),
                "raw_json": raw,
            },
        )
    )
    await s.execute(stmt)


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
    """Ensure the fans row exists + carry identity (username/name/avatar). Prefer
    the chat's `withUser`; else lift it from the newest INBOUND message's
    fromUser (outbound fromUser is us). AI-extracted facts are never touched
    here — only identity + last-message timestamps.

    `is_muted` is the chat-level `isMutedNotifications` (None = unknown, leave the
    column alone). When it flips we reconcile the durable 'muted_creator' skip so
    muting a peer-creator's chat silences every automation (and un-muting frees
    them) — see _common.should_skip_muted_creator."""
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
        update_set["last_message_received_at"] = last_in_at
    if last_out_at is not None:
        update_set["last_message_sent_at"] = last_out_at
    if is_muted is not None:
        insert_extra["is_muted"] = bool(is_muted)
        update_set["is_muted"] = bool(is_muted)
    # Self-heal a weak/unknown source when the chat's withUser carries OF's
    # subscribedOn/subscribedBy — upgrade-only (never downgrades a known
    # classification). The reconciliation below re-reads source, so a muted
    # creator classified for the first time here is auto-restricted same-tick.
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
    """Reconcile the durable 'muted_creator' skip as the OF mute state flips. Read
    the PERSISTED source (list_chats strips subscribedBy via skip_users=all, so
    the live `info` can't classify a creator) — same source the runtime guard
    reads. Runs on the caller's session so it commits atomically with the scrape."""
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
        # Un-muted (or no longer a creator): drop ONLY the auto skip we added.
        await s.execute(
            delete(SkipList).where(
                SkipList.account_id == str(account_id),
                SkipList.fan_id == int(fan_id),
                SkipList.reason == MUTED_CREATOR_REASON,
            )
        )


async def _upsert_chat_and_history(
    s,
    account_id: str,
    fan_id: int,
    *,
    newest_id: int | None,
    newest_text: str | None,
    newest_at: datetime | None,
) -> None:
    """Advance the inbox chat preview + the scrape_history fast-skip cursor —
    both MONOTONICALLY, so backfilling old history can't clobber a newer preview
    a WS event already wrote (guarded by a WHERE on the conflict update)."""
    if newest_id:
        chat_stmt = (
            sqlite_insert(Chat)
            .values(
                account_id=str(account_id),
                fan_id=int(fan_id),
                last_message_id=newest_id,
                last_message_at=newest_at,
                last_message_preview=newest_text,
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

    hist_stmt = (
        sqlite_insert(ScrapeHistory)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            last_message_id=newest_id,
            last_message_text=newest_text,
            last_scrape_at=datetime.utcnow(),
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_={
                "last_message_id": newest_id,
                "last_message_text": newest_text,
                "last_scrape_at": datetime.utcnow(),
            },
        )
    )
    await s.execute(hist_stmt)


async def _fetch_recent_end(
    client: OFClient, chat_id: int, *,
    last_seen_id: int | None, page_size: int, cap: int, max_pages: int,
) -> tuple[list[dict], bool]:
    """The newest-end catch-up: page `order=desc` with the `id` older-cursor,
    looping on `hasMore`. Stops at `last_seen_id` (fast skip), once `cap`
    messages are collected, or when OF runs out. Returns (messages,
    long_convo) where `long_convo` is whether page 1 reported more history
    behind it — the spec's cheap "is this a long convo" probe (no messagesCount
    exists). Never assumes the page size equals `limit`."""
    collected: list[dict] = []
    cursor: int | None = None
    pages = 0
    long_convo = False
    while pages < max_pages and len(collected) < cap:
        # Sync curl_cffi call → off-thread so the event loop never blocks
        # (same idiom as transaction_ingest's `await asyncio.to_thread`).
        resp = await asyncio.to_thread(
            client.get_messages, chat_id,
            limit=page_size, order="desc", before_id=cursor,
        )
        rows = resp.get("list") or []
        if not rows:
            break
        has_more = bool(resp.get("hasMore"))
        if pages == 0:
            long_convo = has_more  # detect "long" via hasMore on page 1
        pages += 1
        stop = False
        for m in rows:
            mid = m.get("id")
            if mid is None:
                continue
            if last_seen_id is not None and int(mid) <= int(last_seen_id):
                stop = True
                break
            collected.append(m)
            if len(collected) >= cap:
                break
        if stop or not has_more:
            break
        cursor = rows[-1].get("id")
        if cursor is None:
            break
        await asyncio.sleep(_PAGE_SLEEP_S)
    return collected, long_convo


async def _fetch_oldest_end(
    client: OFClient, chat_id: int, *,
    page_size: int, cap: int, max_pages: int,
) -> list[dict]:
    """The convo START: page `order=asc` from `offset=0` FORWARD. OF honors asc
    paging and returns the true first messages, but ignores `limit` (returns
    fewer), so loop bumping `offset` by the rows actually received until `cap`
    is met or `hasMore` is False. Bounded by `cap` so we grab "how it started",
    never the whole convo."""
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
        offset += len(rows)  # NEVER assume len(rows) == page_size
        await asyncio.sleep(_PAGE_SLEEP_S)
    return collected


async def _stamp_scrape_history(account_id: str, fan_id: int) -> None:
    """Record "we scraped this fan at T" even when the scrape yielded NOTHING —
    an empty chat, a full fast-skip, or a chat that's GONE on OF (404 from a
    deleted/deactivated fan). gen_info's autoscrape re-enqueue gate is exactly
    `ScrapeHistory.last_scrape_at` vs `_SCRAPE_REFRESH_AGE`; without this stamp a
    dead/empty-chat fan was re-deferred and re-scraped every gen_info pass forever
    (the 2026-07-04 storm: ~24 dead fans × 12 404s/hour, every day). The upsert
    leaves last_message_id/text alone so the fast-skip cursor survives."""
    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(
            sqlite_insert(ScrapeHistory)
            .values(account_id=str(account_id), fan_id=int(fan_id), last_scrape_at=now)
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"last_scrape_at": now},
            )
        )


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
) -> tuple[int, int]:
    """Page one chat and write everything in ONE fresh AsyncSession.

    Recent end always: a bounded newest-first catch-up that stops at the
    last-seen message id (fast skip). On the FIRST scrape of a LONG convo (page
    1 still had history behind it), ALSO grab the convo START via asc/offset so
    the AI gets "how it started" + "where it is now" — the bounded middle is
    intentionally skipped. Capped at ~recent_cap + oldest_cap messages/fan, so a
    long history persists oldest+newest, never thousands. Returns
    (rows_inserted, rows_seen)."""
    fan_id = int(chat_id)

    async with get_session() as s:
        hist = await s.get(ScrapeHistory, (account_id, fan_id))
        last_seen_id = hist.last_message_id if hist else None

    first_scrape = last_seen_id is None
    collected, long_convo = await _fetch_recent_end(
        client, chat_id,
        last_seen_id=last_seen_id, page_size=page_size,
        cap=recent_cap, max_pages=max_pages,
    )

    # Both-ends pull, ONCE: only on the first scrape of a long convo. Later
    # cycles fast-skip the recent end and leave the already-captured start alone.
    if first_scrape and long_convo:
        await asyncio.sleep(_PAGE_SLEEP_S)
        oldest = await _fetch_oldest_end(
            client, chat_id,
            page_size=page_size, cap=oldest_cap, max_pages=max_pages,
        )
        # The two ends can overlap on a medium convo — dedup by id.
        seen_ids = {int(m["id"]) for m in collected if m.get("id") is not None}
        for m in oldest:
            mid = m.get("id")
            if mid is not None and int(mid) not in seen_ids:
                seen_ids.add(int(mid))
                collected.append(m)

    if not collected:
        # Empty chat or complete fast-skip — still a successful "we looked at OF
        # at T" observation. Stamping keeps gen_info's autoscrape from re-deferring
        # this fan on every pass (see _stamp_scrape_history).
        await _stamp_scrape_history(account_id, fan_id)
        # The mute flag still changes without new messages (un-mute an idle
        # chat): reconcile it here too, or the skip outlives the mute. Update
        # only — an empty chat must not mint a fans row.
        if is_muted is not None:
            async with get_session() as s:
                await s.execute(
                    update(Fan)
                    .where(Fan.account_id == str(account_id), Fan.fan_id == fan_id)
                    .values(is_muted=bool(is_muted))
                )
                await _reconcile_muted_skip(s, account_id, fan_id, bool(is_muted))
        return (0, 0)

    # Precise insert count: which of the collected ids are genuinely new (a WS
    # event may already have landed some of them).
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
            s, account_id, fan_id, own_user_id, with_user, collected,
            last_in_at=last_in_at, last_out_at=last_out_at,
            is_muted=is_muted,
        )
        for m in collected:
            await _upsert_message(s, account_id, fan_id, own_user_id, m)
        # The scrape is where an un-echoed optimistic send (ppv_send, list/online
        # audiences) finally meets OF's real row — fold the stubs in now, or the
        # thread keeps BOTH rows forever and the real one reads as a human send.
        # Once per thread, after the rows land: the pairing key is body-within-
        # thread, so it was never per-message work.
        from attribution import adopt_thread_placeholders  # local: circular import
        await adopt_thread_placeholders(s, account_id=str(account_id),
                                        fan_id=int(fan_id))
        await _upsert_chat_and_history(
            s, account_id, fan_id,
            newest_id=newest_id, newest_text=newest_text, newest_at=newest_at,
        )

    return (inserted, len(collected))


@register("scrape_chats")
async def _automation_scrape_chats(
    account_id: str, payload: dict, *, run_id: int
) -> dict:
    """Reference automation. Targets come from the job payload
    (`chat_ids`/`fan_ids`) or, when absent, a sweep of the most-recent chats
    (`limit`). Each chat is scraped into its own session; one slow/broken chat
    is logged and skipped, never failing the whole run."""
    client = await asyncio.to_thread(ax._make_client, account_id)
    own_user_id = client.user_id

    page_size = int(payload.get("page_size") or _SCRAPE_PAGE_SIZE)
    max_pages = int(payload.get("max_pages") or _SCRAPE_MAX_PAGES)
    recent_cap = int(payload.get("recent_cap") or _SCRAPE_RECENT_CAP)
    oldest_cap = int(payload.get("oldest_cap") or _SCRAPE_OLDEST_CAP)

    explicit = payload.get("chat_ids") or payload.get("fan_ids")
    # (chat_id, withUser, is_muted) — is_muted is the chat-level
    # `isMutedNotifications` (creator-side mute). None when unknown (explicit-id
    # scrapes don't list the chat object) → identity upsert leaves is_muted alone.
    targets: list[tuple[int, dict | None, bool | None]] = []
    if explicit:
        targets = [(int(c), None, None) for c in explicit]
    else:
        # OF's /chats returns ~10 per page regardless of `limit`, so PAGINATE by
        # offset until we've collected `limit` chats or OF runs dry — a single call
        # would only ever cover the first 10 sidebar chats (the bug that left most
        # fans un-scraped). `_SCRAPE_CHAT_LIMIT` bounds the sweep; a page cap guards
        # against a misbehaving hasMore.
        limit = int(payload.get("limit") or _SCRAPE_CHAT_LIMIT)
        seen_chat_ids: set[int] = set()
        offset = 0
        for _ in range(_SCRAPE_MAX_PAGES):
            if len(targets) >= limit:
                break
            page = await asyncio.to_thread(
                client.list_chats, limit=_SCRAPE_PAGE_SIZE, offset=offset,
                order="recent",
                # skip_users=None → full withUser incl. subscribedOn/subscribedBy
                # so _upsert_fan_identity can classify (and self-heal) the source.
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
                # `isMutedNotifications` lives on the top-level chat object (NOT
                # on withUser — confirmed live); coerce to a definite bool.
                targets.append((int(cid), wu, bool(ch.get("isMutedNotifications"))))
            offset += len(rows)
            if page.get("hasMore") is False:
                break
        targets = targets[:limit]

    chats_scanned = 0
    chats_failed = 0
    messages_inserted = 0
    messages_seen = 0
    for chat_id, with_user, is_muted in targets:
        try:
            ins, seen = await _scrape_one_chat(
                account_id, own_user_id, client, chat_id, with_user,
                page_size=page_size, max_pages=max_pages,
                recent_cap=recent_cap, oldest_cap=oldest_cap,
                is_muted=is_muted,
            )
            messages_inserted += ins
            messages_seen += seen
            chats_scanned += 1
        except Exception as e:
            chats_failed += 1
            # 404 = the chat no longer exists on OF (fan deleted/deactivated).
            # Not transient — stamp scrape_history so gen_info's autoscrape
            # stops re-enqueueing the fan every pass, and skip the traceback
            # (one info line instead of 30 lines × 12/hour × 24 dead fans).
            status = getattr(getattr(e, "response", None), "status_code", None)
            if isinstance(e, OFAPIError) and status == 404:
                log.info("scrape_chat_gone account=%s chat=%s (404 — fan gone; "
                         "stamping scrape_history)", account_id, chat_id)
                try:
                    await _stamp_scrape_history(account_id, int(chat_id))
                except Exception:
                    log.warning("stamp_scrape_history failed account=%s chat=%s",
                                account_id, chat_id, exc_info=True)
            else:
                log.warning(
                    "scrape_chat_failed account=%s chat=%s",
                    account_id, chat_id, exc_info=True,
                )
        await asyncio.sleep(_PAGE_SLEEP_S)

    return {
        "targets": len(targets),
        "chats_scanned": chats_scanned,
        "chats_failed": chats_failed,
        "messages_inserted": messages_inserted,
        "messages_seen": messages_seen,
    }
