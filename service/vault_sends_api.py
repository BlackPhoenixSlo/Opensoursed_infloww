"""service/vault_sends_api.py — server.py's vault-sends block, moved wholesale:
per-fan vault-send history (record + chat-open backfill + picker badges) and the
wall-media scan.

  POST /admin/vault/sends
  POST /admin/vault/sends/backfill
  GET  /admin/vault/wall-media
  GET  /admin/vault/fan-history
  POST /admin/vault/fan-history/sync

The account-wide aggregate over `vault_sends` (`/admin/vault/media-stats`) lives in vault.py.
`_load_client` is relay_host's call-time forward, never `from server import`,
so a test's `server._load_client = fake` still reaches it. Included mid-file
in server.py for route order (pinned by service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

import of_pacing
import platforms
from auth import assert_account_owned
from of_coerce import cents_or_zero
from relay_host import load_client as _load_client

log = logging.getLogger("of-relay.vault_sends")
router = APIRouter()


# ── Vault sends + per-fan history ─────────────────────────────────────
# Powers the picker's "you sent this to her 2 weeks ago / she bought it"
# badges. Frontend writes here right after a successful chat-send (better
# than wrapping the OF send proxy — keeps that path a clean mirror, and
# lets us decide per-call whether to track, e.g. don't track mass-sends).

class _VaultSendBody(BaseModel):
    account_id: str
    fan_id: int
    media_ids: list[int] = Field(default_factory=list)
    message_id: int | None = None
    price_cents: int = Field(0, ge=0, description="PPV price in cents (0 = free send)")


@router.post("/admin/vault/sends")
async def admin_vault_sends_create(body: _VaultSendBody = Body(...)) -> dict[str, Any]:
    """Record vault sends for positive media ids, merging repeats when a message id is supplied."""
    assert_account_owned(body.account_id)
    if body.message_id is not None:
        item = _VaultBackfillItem(message_id=body.message_id, media_ids=body.media_ids, price_cents=body.price_cents)
        inserted, _, _ = await _upsert_sends(body.account_id, body.fan_id, [item])
        return {"ok": True, "inserted": inserted}
    from db.engine import get_session
    from db.models import VaultSend
    real_ids = [mid for mid in body.media_ids if isinstance(mid, int) and mid > 0]
    if not real_ids:
        return {"ok": True, "inserted": 0}
    async with get_session() as s:
        for mid in real_ids:
            s.add(VaultSend(
                account_id=body.account_id,
                fan_id=body.fan_id,
                media_id=mid,
                price_cents=body.price_cents,
                # was_purchased flips later when a matching transaction
                # lands (see Transaction ingest path). Default null = unknown.
            ))
        await s.commit()
    return {"ok": True, "inserted": len(real_ids)}


class _VaultBackfillItem(BaseModel):
    message_id: int
    media_ids: list[int] = Field(default_factory=list)
    price_cents: int = Field(0, ge=0)
    # OF reports `isOpened=true` on a PPV once the fan has paid; we mirror
    # that as `was_purchased`. None for free sends — leave the column null
    # so the UI can distinguish "definitely not paid" vs "wasn't paid for".
    was_purchased: bool | None = None
    sent_at: str | None = Field(None, description="OF's createdAt (ISO); the row's sent_at when inserted.")


class _VaultBackfillBody(BaseModel):
    account_id: str
    fan_id: int
    items: list[_VaultBackfillItem] = Field(default_factory=list)


async def _upsert_sends(account_id: str, fan_id: int, items: list[_VaultBackfillItem]) -> tuple[int, int, int]:
    """(inserted, updated, skipped). A missing (media, message) row is inserted; an existing one is
    skipped, except that an item seen bought flips it to was_purchased=True (never back)."""
    from db.of_writer import immediate_session
    from db.models import VaultSend
    from sqlalchemy import select, update

    msg_ids = {it.message_id for it in items}
    inserted = updated = skipped = 0
    async with immediate_session() as s:
        existing: dict[tuple[int, int], list[tuple[int, bool | None]]] = {}
        if msg_ids:
            res = await s.execute(
                select(VaultSend.id, VaultSend.media_id, VaultSend.message_id, VaultSend.was_purchased)
                .where(
                    VaultSend.account_id == account_id,
                    VaultSend.fan_id == fan_id,
                    VaultSend.message_id.in_(msg_ids),
                ),
            )
            for row_id, mid, msg, bought in res.all():
                if msg is not None:
                    existing.setdefault((mid, msg), []).append((row_id, bought))

        flip: set[int] = set()
        pending: dict[tuple[int, int], VaultSend] = {}
        for item in items:
            real_ids = [mid for mid in item.media_ids if isinstance(mid, int) and mid > 0]
            sent_at = _parse_of_iso(item.sent_at)
            for mid in real_ids:
                key = (mid, item.message_id)
                if key in pending:
                    if item.was_purchased:
                        pending[key].was_purchased = True
                    skipped += 1
                    continue
                rows = existing.get(key)
                if rows is not None:
                    todo = {rid for rid, bought in rows if bought is not True} if item.was_purchased else set()
                    if todo - flip:
                        updated += 1
                        flip |= todo
                    else:
                        skipped += 1
                    continue
                row = VaultSend(
                    account_id=account_id,
                    fan_id=fan_id,
                    media_id=mid,
                    message_id=item.message_id,
                    price_cents=item.price_cents,
                    was_purchased=item.was_purchased,
                    **({"sent_at": sent_at} if sent_at else {}),
                )
                s.add(row)
                pending[key] = row
                inserted += 1
        if flip:
            await s.execute(update(VaultSend).where(VaultSend.id.in_(flip)).values(was_purchased=True))
    return inserted, updated, skipped


@router.post("/admin/vault/sends/backfill")
async def admin_vault_sends_backfill(body: _VaultBackfillBody = Body(...)) -> dict[str, Any]:
    """Bulk-insert vault-send rows from chat history. The frontend calls
    this whenever a chat opens — every outgoing message with media that
    DOESN'T already have a vault_send row gets one. Idempotent: existing
    rows are detected via (account_id, fan_id, media_id, message_id) and
    skipped, so it's safe to fire on every chat-open without dupes. An
    existing row the item shows bought (`was_purchased` true) flips to
    bought (`updated`); a bought row never flips back.

    This is how we cover historical sends (pre-tracking), without
    requiring a one-off backfill job."""
    assert_account_owned(body.account_id)
    if not body.items:
        return {"ok": True, "inserted": 0, "updated": 0, "skipped": 0}
    inserted, updated, skipped = await _upsert_sends(body.account_id, body.fan_id, body.items)
    out: dict[str, Any] = {"ok": True, "inserted": inserted, "updated": updated, "skipped": skipped}
    if inserted or updated:
        # The fan's new history (GET /admin/vault/fan-history's body): the chat open sets it instead of reading
        # it again (every page granting /admin/vault/sends grants fan-history: permissions._PICKER).
        out["history"] = await _fan_history(account_id=body.account_id, fan_id=body.fan_id)
    return out


def _parse_of_iso(s: Any) -> datetime | None:
    """OF's postedAt is "2026-04-12T17:33:11+00:00"-ish. Returns a naive
    UTC datetime (matches the rest of our DB convention) or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _session_user_id(account_id: str, client: Any) -> int | None:
    """The Creator's own OF id from the signed session (`OFClient.user_id`, a
    string): a positive int, or None when it is not all ASCII digits. A Fansly
    account is None: its old `/users/me` id was a string, so the scan has
    always 500'd there."""
    # ASSUMPTION: Fansly keeps today's 500 (rung 2, ticket "same 500 as today"; no Fansly wall-media path found).
    # Overturned when Fansly wall media becomes a supported path (FanslyShimClient.user_posts walks /timelinenew).
    if platforms.Lack.WALL_MEDIA in platforms.for_account(account_id).lacks:
        return None
    s = str(client.user_id)
    if not (s.isascii() and s.isdigit()):
        return None
    n = int(s)
    return n if n > 0 else None


@router.get("/admin/vault/wall-media")
async def admin_vault_wall_media(
    request: Request,
    account_id: str = Query(...),
    pages: int = Query(5, ge=1, le=20, description="Max OF /posts pages to walk per call."),
    limit: int = Query(50, ge=1, le=50, description="Posts per page."),
    force: bool = Query(False, description="Force a re-scan from the top, ignoring the cached watermarks. UI's '↻ refresh' button."),
) -> dict[str, Any]:
    """Aggregate every vault media id ever posted on this model's wall,
    backed by SQLite (`wall_media` + `wall_scan_state`) so subsequent
    calls are O(diff-since-last-scan) instead of the old 5-page
    (~250-post) re-walk every hour.

    Two operating modes (state per-account in `wall_scan_state`):
      • Backfill: walks BACKWARD from `oldest_post_published_at` using
        OF's beforePublishTime cursor. Used until we hit the bottom of
        the post feed; `pages` per call so creators with thousands of
        posts amortize the walk over several picker opens.
      • Refresh: once `fully_backfilled=True`, walks FORWARD from the
        top and stops at the post matching `newest_post_published_at`.
        Usually a single page round-trip — creators rarely post 50
        wall items between picker opens.

    Returns the UNION of every media_id we've ever recorded for this
    account plus scan status. `has_more=true` means DB coverage is
    incomplete (older history remains) — the frontend uses it to
    optionally trigger another fetch in the background.

    The Creator's own id comes from the session the Relay holds
    (`client.user_id`), never a `/users/me` call. The OF httpx calls
    (`client.user_posts(...)`) are blocking; we run each via
    `asyncio.to_thread` so the event loop stays responsive — the up-to-5 sequential page walks otherwise
    froze SSE / webhooks for the full duration (observed 13.5s in the
    wild). `request.is_disconnected()` checks between pages so a folder
    switch mid-walk frees the per-account proxy slot promptly."""
    from db.engine import get_session
    from db.models import WallMedia, WallScanState
    from sqlalchemy import func, select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    client = _load_client(account_id)
    my_id = _session_user_id(account_id, client)
    if my_id is None:
        raise HTTPException(status_code=500, detail="Could not resolve current user id from /users/me")

    # 1. Load scan state; honor `force` by wiping watermarks (rows stay —
    #    re-walking just re-confirms what we know via on_conflict_do_nothing).
    async with get_session() as s:
        state = (await s.execute(
            select(WallScanState).where(WallScanState.account_id == account_id)
        )).scalar_one_or_none()
        if force and state is not None:
            state.newest_post_published_at = None
            state.oldest_post_published_at = None
            state.fully_backfilled = False
            await s.flush()
        # Snapshot the values we need outside the session (state row is
        # detached after the `async with` exits).
        prev_newest = state.newest_post_published_at if state else None
        prev_oldest = state.oldest_post_published_at if state else None
        prev_backfilled = bool(state.fully_backfilled) if state else False
        prev_total = int(state.scanned_posts_total) if state else 0

    # 2. Pick mode + cursor. Three cases:
    #    • first   — never scanned this account before, walk forward from top.
    #    • refresh — fully covered already, walk forward and stop at watermark.
    #    • backfill — middle: walk backward from oldest known post.
    if prev_newest is None and prev_oldest is None:
        mode = "first"
        before: str | None = None
        stop_forward_at: datetime | None = None
    elif prev_backfilled:
        mode = "refresh"
        before = None
        stop_forward_at = prev_newest
    else:
        mode = "backfill"
        before = (
            f"{prev_oldest.timestamp():.6f}"
            if prev_oldest is not None else None
        )
        stop_forward_at = None

    # 3. Walk pages, accumulating new (account, media, post, published_at).
    new_rows: list[dict[str, Any]] = []
    seen_media_in_call: set[int] = set()  # dedupe within this call's batch
    scanned = 0
    page_newest_ts: datetime | None = None
    page_oldest_ts: datetime | None = None
    hit_known_top = False
    of_has_more = False
    for _ in range(pages):
        if await request.is_disconnected():
            raise HTTPException(status_code=499, detail="client disconnected")
        resp = await asyncio.to_thread(
            client.user_posts,
            my_id,
            limit=limit,
            skip_users="all",
            format="infinite",
            before_publish_time=before,
        )
        posts = resp.get("list", []) if isinstance(resp, dict) else []
        if not posts:
            break
        scanned += len(posts)
        for post in posts:
            pid = post.get("id")
            posted_at = _parse_of_iso(post.get("postedAt") or post.get("postedAtPrecise"))
            if posted_at and (page_newest_ts is None or posted_at > page_newest_ts):
                page_newest_ts = posted_at
            if posted_at and (page_oldest_ts is None or posted_at < page_oldest_ts):
                page_oldest_ts = posted_at
            # Refresh-mode stop: posts older-than-or-equal-to the watermark
            # are already in our DB. Don't enqueue their media (we have
            # them) and flag the outer loop to bail.
            if mode == "refresh" and stop_forward_at and posted_at and posted_at <= stop_forward_at:
                hit_known_top = True
                continue
            # OF posts carry a top-level `price` (dollars, float) for paid /
            # PPV wall posts; free posts omit it or send 0. Convert to cents
            # so the picker can badge "WALL $X.XX".
            try:
                post_price_cents = int(round(float(post.get("price") or 0) * 100))
            except (TypeError, ValueError):
                post_price_cents = 0
            if post_price_cents < 0:
                post_price_cents = 0
            for m in (post.get("media") or []):
                mid = m.get("id")
                if isinstance(mid, int) and mid > 0 and mid not in seen_media_in_call:
                    seen_media_in_call.add(mid)
                    new_rows.append({
                        "account_id": account_id,
                        "media_id": mid,
                        "post_id": int(pid) if isinstance(pid, int) else None,
                        "post_published_at": posted_at,
                        "price_cents": post_price_cents,
                    })
        of_has_more = bool(resp.get("hasMore"))
        if hit_known_top:
            break
        if not of_has_more:
            break
        before = resp.get("tailMarker")
        if not before:
            break

    # 4. Persist new rows + scan state, then read the full union back.
    now = datetime.utcnow()
    new_fully_backfilled = prev_backfilled
    if mode == "first":
        new_fully_backfilled = not of_has_more
    elif mode == "backfill" and not of_has_more:
        new_fully_backfilled = True
    # refresh mode never flips back to False — force=True is the only path
    # that resets the watermarks.

    # Merge watermarks: extend in whichever direction this call walked.
    new_newest = page_newest_ts
    if prev_newest is not None and (new_newest is None or prev_newest > new_newest):
        new_newest = prev_newest
    new_oldest = page_oldest_ts
    if prev_oldest is not None and (new_oldest is None or prev_oldest < new_oldest):
        new_oldest = prev_oldest

    new_total = prev_total + scanned

    async with get_session() as s:
        # Ensure the parent accounts row exists — wall_media + wall_scan_state
        # both FK to accounts.id. Without import_legacy ever running for this
        # account, the FK insert blows up. Idempotent ON CONFLICT no-op.
        from db.models import Account
        await s.execute(
            sqlite_insert(Account)
            .values(id=account_id, is_active_default=False)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        if new_rows:
            ins = sqlite_insert(WallMedia).values(new_rows)
            # Upsert price_cents to MAX(existing, incoming) so a media seen
            # in both a free and a paid wall post keeps the paid signal, and
            # already-recorded rows pick up a price on a forward/force
            # re-scan. post_id / post_published_at keep their first-seen
            # values — only the price is refined.
            await s.execute(
                ins.on_conflict_do_update(
                    index_elements=["account_id", "media_id"],
                    set_={"price_cents": func.max(WallMedia.price_cents, ins.excluded.price_cents)},
                )
            )
        await s.execute(
            sqlite_insert(WallScanState)
            .values(
                account_id=account_id,
                newest_post_published_at=new_newest,
                oldest_post_published_at=new_oldest,
                fully_backfilled=new_fully_backfilled,
                last_scan_at=now,
                scanned_posts_total=new_total,
            )
            .on_conflict_do_update(
                index_elements=["account_id"],
                set_={
                    "newest_post_published_at": new_newest,
                    "oldest_post_published_at": new_oldest,
                    "fully_backfilled": new_fully_backfilled,
                    "last_scan_at": now,
                    "scanned_posts_total": new_total,
                },
            )
        )
        all_rows = (await s.execute(
            select(WallMedia.media_id, WallMedia.price_cents)
            .where(WallMedia.account_id == account_id)
        )).all()

    # Only the priced rows go in the map — keeps the payload lean (free wall
    # posts are the common case and the frontend defaults missing ids to 0).
    media_prices = {
        str(int(mid)): int(cents)
        for mid, cents in all_rows
        if cents and int(cents) > 0
    }
    return {
        "media_ids": sorted({int(mid) for mid, _ in all_rows}),
        "media_prices": media_prices,
        "scanned_posts": scanned,
        "new_media_count": len(new_rows),
        "has_more": not new_fully_backfilled,
        "fully_backfilled": new_fully_backfilled,
        "mode": mode,
        "last_scan_at": now.isoformat() + "Z",
        "newest_post_published_at": new_newest.isoformat() + "Z" if new_newest else None,
        "oldest_post_published_at": new_oldest.isoformat() + "Z" if new_oldest else None,
    }


@router.get("/admin/vault/fan-history")
async def admin_vault_fan_history(
    account_id: str = Query(...),
    fan_id: int = Query(...),
) -> dict[str, Any]:
    """Per-media send history for ONE fan. Drives the vault-picker's
    'sent / purchased / unseen' badges with an O(1) lookup per tile.

    Returns:
      by_media: { "<media_id>": { send_count, last_sent_at,
                                  last_price_cents, was_purchased,
                                  last_purchase_at, total_paid_cents } }

    `was_purchased` mirrors the column on vault_sends — true once a
    transaction with the same message_id is observed.
    `last_purchase_at` / `total_paid_cents` come from joining the
    transactions table (kind in {message, ppv}) on message_id."""
    return await _fan_history(account_id, fan_id)


async def _fan_history(account_id: str, fan_id: int) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Transaction, VaultSend
    from sqlalchemy import select
    async with get_session() as s:
        # All sends to this fan, newest first.
        sends_res = await s.execute(
            select(VaultSend)
            .where(VaultSend.account_id == account_id, VaultSend.fan_id == fan_id)
            .order_by(VaultSend.sent_at.desc()),
        )
        sends = sends_res.scalars().all()
        if not sends:
            return {"by_media": {}}

        # Pull transactions referenced by any of our sends so we can mark
        # was_purchased + sum paid amounts. Filter to message-bearing txns
        # to skip subscription rebills + tips.
        msg_ids = {s.message_id for s in sends if s.message_id is not None}
        tx_by_msg: dict[int, list[Transaction]] = {}
        if msg_ids:
            tx_res = await s.execute(
                select(Transaction)
                .where(
                    Transaction.account_id == account_id,
                    Transaction.fan_id == fan_id,
                    Transaction.message_id.in_(msg_ids),
                ),
            )
            for t in tx_res.scalars().all():
                if t.message_id is None:
                    continue
                tx_by_msg.setdefault(t.message_id, []).append(t)

        by_media: dict[str, dict[str, Any]] = {}
        seen_messages: dict[int, set[int]] = defaultdict(set)
        seen_transactions: dict[int, set[int]] = defaultdict(set)
        for snd in sends:
            entry = by_media.setdefault(str(snd.media_id), {
                "send_count": 0,
                "last_sent_at": None,
                "last_price_cents": 0,
                "was_purchased": False,
                "last_purchase_at": None,
                "total_paid_cents": 0,
            })
            messages = seen_messages[snd.media_id]
            if snd.message_id is None:
                entry["send_count"] += 1
            elif snd.message_id not in messages:
                entry["send_count"] += 1
                messages.add(snd.message_id)
            # Sends came back newest-first, so the first one we see is
            # the most recent — only fill these when they're still empty.
            if entry["last_sent_at"] is None:
                entry["last_sent_at"] = snd.sent_at.isoformat() if snd.sent_at else None
                entry["last_price_cents"] = snd.price_cents or 0
            # was_purchased: row flag OR any matching transaction.
            if snd.was_purchased:
                entry["was_purchased"] = True
            if snd.message_id is None:
                continue
            transactions = seen_transactions[snd.media_id]
            for t in tx_by_msg.get(snd.message_id, []):
                if t.id in transactions:
                    continue
                transactions.add(t.id)
                entry["was_purchased"] = True
                entry["total_paid_cents"] += t.amount_cents or 0
                iso = t.occurred_at.isoformat() if t.occurred_at else None
                if iso and (entry["last_purchase_at"] is None or iso > entry["last_purchase_at"]):
                    entry["last_purchase_at"] = iso
        return {"by_media": by_media}


# ── Per-fan OF chat-media sync ────────────────────────────────────────
# The thread backfill only sees the pages a chatter scrolled; this walks OF's chat gallery
# (the Creator's media messages to the Fan) once per SYNC_FRESH, so a long-tenure Fan's old
# sends and buys reach the picker badges too.

SYNC_FRESH = timedelta(days=7)
SYNC_FAIL_COOLDOWN = timedelta(hours=1)
SYNC_RECENT_WINDOW_PAGES = 10
SYNC_PAGE_LIMIT = 50
SYNC_WALK_KIND = "fan_media_sync"
_SYNC_LOCKS: weakref.WeakValueDictionary[tuple[str, int], asyncio.Lock] = weakref.WeakValueDictionary()


class _FanHistorySyncBody(BaseModel):
    account_id: str
    fan_id: int


def _sync_due(synced_at: datetime | None, last_attempt_at: datetime | None, now: datetime) -> bool:
    failed = last_attempt_at is not None and (synced_at is None or last_attempt_at > synced_at)
    if failed and now - last_attempt_at < SYNC_FAIL_COOLDOWN:
        return False
    return synced_at is None or now - synced_at >= SYNC_FRESH


def _sync_item(m: Any, creator_id: str) -> _VaultBackfillItem | None:
    """One OF chat-media message as a backfill item: the Creator's own (a `fromUser` naming
    anyone else is skipped), with real media ids; None otherwise."""
    if not isinstance(m, dict):
        return None
    sender = m.get("fromUser")
    if isinstance(sender, dict) and sender.get("id") is not None and str(sender["id"]) != creator_id:
        return None
    msg_id = m.get("id")
    if isinstance(msg_id, str) and msg_id.isdigit():
        msg_id = int(msg_id)
    if not isinstance(msg_id, int) or isinstance(msg_id, bool) or msg_id <= 0:
        return None
    media_ids = [x.get("id") for x in (m.get("media") or []) if isinstance(x, dict)]
    media_ids = [i for i in media_ids if isinstance(i, int) and not isinstance(i, bool) and i > 0]
    if not media_ids:
        return None
    price = max(cents_or_zero(m.get("price")), 0)
    return _VaultBackfillItem(
        message_id=msg_id, media_ids=media_ids, price_cents=price,
        was_purchased=bool(m.get("isOpened")) if price > 0 else None,
        sent_at=m.get("createdAt") if isinstance(m.get("createdAt"), str) else None,
    )


async def _walk_fan_media(account_id: str, fan_id: int, client: Any,
                          creator_id: str) -> tuple[list[_VaultBackfillItem], int, bool]:
    """(items, pages, complete) from OF's `chats/{fan}/media`, newest first, at most SYNC_RECENT_WINDOW_PAGES pages.
    Any OF error (a 429 after the walk's one retry too) raises: a partial walk is never recorded as a sync."""
    def page(cursor: Any) -> Any:
        return client.chat_media(fan_id, limit=SYNC_PAGE_LIMIT, from_user=creator_id, skip_users="all", last_id=cursor)

    async def run() -> tuple[list[_VaultBackfillItem], int, bool]:
        items: list[_VaultBackfillItem] = []
        cursor: Any = None
        cursors: set[str] = set()
        pages = 0
        more = False
        while pages < SYNC_RECENT_WINDOW_PAGES:
            resp = await asyncio.to_thread(page, cursor)
            pages += 1
            rows = resp.get("list") if isinstance(resp, dict) else None
            if not isinstance(rows, list):
                raise ValueError(f"chat media page {pages}: no list")
            items.extend(it for it in (_sync_item(m, creator_id) for m in rows) if it is not None)
            more = bool(resp.get("hasMore"))
            cursor = resp.get("nextLastId")
            if not more:
                break
            if not isinstance(cursor, (str, int)) or isinstance(cursor, bool) or cursor == "" or str(cursor) in cursors:
                raise ValueError(f"chat media page {pages}: invalid cursor")
            cursors.add(str(cursor))
        return items, pages, not more

    return await of_pacing.walk(account_id, SYNC_WALK_KIND, run)


async def _write_sync(account_id: str, fan_id: int, now: datetime, *, pages: int | None = None,
                      complete: bool | None = None) -> None:
    """A finished walk (pages given) stamps synced_at; a failed one only last_attempt_at."""
    from db.engine import get_session
    from db.models import FanMediaSync
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    vals: dict[str, Any] = {"last_attempt_at": now}
    if pages is not None:
        vals.update(synced_at=now, pages=pages, complete=bool(complete))
    async with get_session() as s:
        await s.execute(
            sqlite_insert(FanMediaSync)
            .values(account_id=account_id, fan_id=fan_id, **vals)
            .on_conflict_do_update(index_elements=["account_id", "fan_id"], set_=vals)
        )
        await s.commit()


@router.post("/admin/vault/fan-history/sync")
async def admin_vault_fan_history_sync(body: _FanHistorySyncBody = Body(...)) -> dict[str, Any]:
    """GET /admin/vault/fan-history's body (`history`), after first filling `vault_sends` from OF's chat
    gallery when this Fan was not synced in 7 days (`synced: true`). Synced recently, or a failed walk
    within the hour: no OF call (`cached: true`). A failed walk returns the local history (`synced: false`)."""
    assert_account_owned(body.account_id)
    from db.engine import get_session
    from db.models import FanMediaSync
    from sqlalchemy import select

    key = (body.account_id, body.fan_id)
    lock = _SYNC_LOCKS.get(key)
    if lock is None:
        lock = _SYNC_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        async with get_session() as s:
            row = (await s.execute(select(FanMediaSync.synced_at, FanMediaSync.last_attempt_at).where(
                FanMediaSync.account_id == body.account_id, FanMediaSync.fan_id == body.fan_id,
            ))).first()
        now = datetime.utcnow()
        if row is not None and not _sync_due(row[0], row[1], now):
            return {"history": await _fan_history(body.account_id, body.fan_id), "synced": False, "cached": True}
        walk = None
        try:
            client = _load_client(body.account_id)
            creator_id = _session_user_id(body.account_id, client)
            if creator_id is not None:
                walk = await _walk_fan_media(body.account_id, body.fan_id, client, str(creator_id))
        except Exception as e:  # noqa: BLE001
            log.info("fan_media_sync_failed account=%s fan=%s err=%s", body.account_id, body.fan_id,
                     type(e).__name__)
            await _write_sync(body.account_id, body.fan_id, now)
        if walk is None:
            return {"history": await _fan_history(body.account_id, body.fan_id), "synced": False, "cached": False}
        items, pages, complete = walk
        inserted, updated, _ = await _upsert_sends(body.account_id, body.fan_id, items) if items else (0, 0, 0)
        await _write_sync(body.account_id, body.fan_id, now, pages=pages, complete=complete)
    return {
        "history": await _fan_history(body.account_id, body.fan_id), "synced": True, "cached": False,
        "inserted": inserted, "updated": updated, "pages": pages, "complete": complete,
    }
