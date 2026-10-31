"""service/vault_sends_api.py — server.py's vault-sends block, moved wholesale:
per-fan vault-send history (record + chat-open backfill + picker badges) and the
wall-media scan.

  POST /admin/vault/sends
  POST /admin/vault/sends/backfill
  GET  /admin/vault/wall-media
  GET  /admin/vault/fan-history

The account-wide aggregate over `vault_sends` (`/admin/vault/media-stats`) lives in vault.py.
`_load_client` is relay_host's call-time forward, never `from server import`,
so a test's `server._load_client = fake` still reaches it. Included mid-file
in server.py for route order (pinned by service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel, Field

from relay_host import load_client as _load_client

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
    """Record one vault-send row per media id. Returns the inserted count.

    Skips negative ids (fresh-claim placeholders the optimistic bubble
    used before the real vault id was assigned) — those slip through if
    the caller doesn't filter, and we shouldn't pollute history with them."""
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
                message_id=body.message_id,
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


class _VaultBackfillBody(BaseModel):
    account_id: str
    fan_id: int
    items: list[_VaultBackfillItem] = Field(default_factory=list)


@router.post("/admin/vault/sends/backfill")
async def admin_vault_sends_backfill(body: _VaultBackfillBody = Body(...)) -> dict[str, Any]:
    """Bulk-insert vault-send rows from chat history. The frontend calls
    this whenever a chat opens — every outgoing message with media that
    DOESN'T already have a vault_send row gets one. Idempotent: existing
    rows are detected via (account_id, fan_id, media_id, message_id) and
    skipped, so it's safe to fire on every chat-open without dupes.

    This is how we cover historical sends (pre-tracking), without
    requiring a one-off backfill job."""
    from db.engine import get_session
    from db.models import VaultSend
    from sqlalchemy import select
    if not body.items:
        return {"ok": True, "inserted": 0, "skipped": 0}

    # Pull every existing (media_id, message_id) for this fan in one query
    # so the dupe check is O(rows) instead of O(items × DB roundtrip).
    seen_msg_ids = {it.message_id for it in body.items if it.message_id}
    inserted = 0
    skipped = 0
    async with get_session() as s:
        existing: set[tuple[int, int]] = set()
        if seen_msg_ids:
            res = await s.execute(
                select(VaultSend.media_id, VaultSend.message_id)
                .where(
                    VaultSend.account_id == body.account_id,
                    VaultSend.fan_id == body.fan_id,
                    VaultSend.message_id.in_(seen_msg_ids),
                ),
            )
            for mid, msg in res.all():
                if msg is not None:
                    existing.add((mid, msg))

        for item in body.items:
            real_ids = [mid for mid in item.media_ids if isinstance(mid, int) and mid > 0]
            for mid in real_ids:
                if (mid, item.message_id) in existing:
                    skipped += 1
                    continue
                s.add(VaultSend(
                    account_id=body.account_id,
                    fan_id=body.fan_id,
                    media_id=mid,
                    message_id=item.message_id,
                    price_cents=item.price_cents,
                    was_purchased=item.was_purchased,
                ))
                existing.add((mid, item.message_id))
                inserted += 1
        if inserted:
            await s.commit()
    return {"ok": True, "inserted": inserted, "skipped": skipped}


def _parse_of_iso(s: Any) -> datetime | None:
    """OF's postedAt is "2026-04-12T17:33:11+00:00"-ish. Returns a naive
    UTC datetime (matches the rest of our DB convention) or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


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

    The OF httpx calls (`client.me()`, `client.user_posts(...)`) are
    blocking; we run each via `asyncio.to_thread` so the event loop
    stays responsive — the up-to-5 sequential page walks otherwise
    froze SSE / webhooks for the full duration (observed 13.5s in the
    wild). `request.is_disconnected()` checks between pages so a folder
    switch mid-walk frees the per-account proxy slot promptly."""
    from db.engine import get_session
    from db.models import WallMedia, WallScanState
    from sqlalchemy import func, select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    client = _load_client(account_id)
    me_resp = await asyncio.to_thread(client.me)
    my_id = me_resp.get("id")
    if not isinstance(my_id, int):
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
        for snd in sends:
            entry = by_media.setdefault(str(snd.media_id), {
                "send_count": 0,
                "last_sent_at": None,
                "last_price_cents": 0,
                "was_purchased": False,
                "last_purchase_at": None,
                "total_paid_cents": 0,
            })
            entry["send_count"] += 1
            # Sends came back newest-first, so the first one we see is
            # the most recent — only fill these when they're still empty.
            if entry["last_sent_at"] is None:
                entry["last_sent_at"] = snd.sent_at.isoformat() if snd.sent_at else None
                entry["last_price_cents"] = snd.price_cents or 0
            # was_purchased: row flag OR any matching transaction.
            if snd.was_purchased:
                entry["was_purchased"] = True
            if snd.message_id and snd.message_id in tx_by_msg:
                for t in tx_by_msg[snd.message_id]:
                    entry["was_purchased"] = True
                    entry["total_paid_cents"] += t.amount_cents or 0
                    iso = t.occurred_at.isoformat() if t.occurred_at else None
                    if iso and (entry["last_purchase_at"] is None or iso > entry["last_purchase_at"]):
                        entry["last_purchase_at"] = iso
        return {"by_media": by_media}
