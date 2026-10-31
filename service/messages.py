"""
messages.py — server-side endpoints for the per-chat message timeline.

Endpoints, all keyed on (account_id, fan_id):

  GET    /admin/messages/{account_id}/{fan_id}?limit=&before_id=
                                          → paginated history (newest first)
  POST   /admin/messages/{account_id}/{fan_id}/mark-read
                                          → zero out chats.unread_count
                                            (LOCAL only — the OF call lives
                                            in the existing relay endpoint)

Re-exports the mirror writes (`mark_unsent` and friends, messages_unsent.py):
the local half of an unsend, called by the relay's OF routes and by the
unsend_messages automation once OF confirms. The paid-messages read model
(query builder, CSV row, mass summaries) lives in messages_query.py.

This file owns NONE of the OF-network logic — every row served comes from
the local `messages` / `message_flags` / `chats` tables that the WS
transcoder populates. Outbound sends + OF-side read receipts live in
of_client.py and the relay endpoints in server.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

import csv_export
from db.engine import get_session
from db.models import Account, Chat, Employee, Message, MessageMedia, Transaction
from attribution_backfill import TRACKED_STATUSES
from stats import _parse_date
from auth import assert_account_owned, assert_employee_filter_owned, clamp_account_filter
from of_shapes import DIM_KEYS, media_urls   # shared OF payload-shape readers
from messages_query import (  # noqa: F401 — some re-exported (tests: messages._collapsed_mass_rows)
    _CSV_HEADER, _apply_dashboard_filters, _build_messages_query, _collapsed_mass_rows,
    _csv_row, _keyset_where, _page, _paid_row,
)
from messages_unsent import (  # noqa: F401 — re-exported (server, automations, tests import from here)
    _queue_body_and_stamp, _queue_id_of, mark_mass_runs_unsent,
    mark_queue_copies_unsent, mark_queue_unsent, mark_unsent,
)


log = logging.getLogger("of-relay.messages")
router = APIRouter()


def _row_to_dict(
    m: Message, media: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "account_id": m.account_id,
        "fan_id": m.fan_id,
        "message_id": m.message_id,
        "direction": m.direction,
        "sender_name": m.sender_name,
        "body": m.body,
        "media_ids": _safe_load_list(m.media_ids),
        # Per-item media with NULLABLE width/height — the render-stability
        # cache (18_chat_render_stability §1.1). `media_ids` (id-only, legacy)
        # is kept for back-compat; `media` carries the dims the skeleton/grid
        # need. Empty until a live OF fetch / client PATCH fills message_media.
        "media": media or [],
        "media_count": m.media_count,
        "price_cents": m.price_cents,
        "is_paid": m.is_paid,
        "is_tip": m.is_tip,
        "is_unsent": m.is_unsent,
        "unsent_by_employee_id": m.unsent_by_employee_id,
        "unsent_reason": m.unsent_reason,
        "unsent_at": m.unsent_at.isoformat() if m.unsent_at else None,
        "is_promise": m.is_promise,
        "promise_due_date": (
            m.promise_due_date.isoformat() if m.promise_due_date else None
        ),
        "purchased_at": m.purchased_at.isoformat() if m.purchased_at else None,
        "sent_by_employee_id": m.sent_by_employee_id,
        "temp_id": m.temp_id,
        "mass_run_id": m.mass_run_id,
        "funnel_step": m.funnel_step,
        "automation_kind": m.automation_kind,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "ingested_at": m.ingested_at.isoformat() if m.ingested_at else None,
    }


def _safe_load_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


# ── media dimensions (18_chat_render_stability §1.1) ────────────────────
#
# message_media is the render-stability cache: one row per media item, with
# NULLABLE width/height. Dims are NEVER read from a Message.raw_json — the WS
# event carries only the media id (DA bug 1). They come from two lazy sources:
#   1. the live OF REST /chats/{id}/messages media objects, whose
#      `files`/`info` blocks carry source/full/preview width+height
#      (verified against real OF payloads — see reconcile_rest_media);
#   2. a client onload→PATCH for items OF never sized.
# Every consumer tolerates null dims (neutral skeleton box).

def _as_pos_int(v: Any) -> int | None:
    """Coerce an OF width/height to a positive int, else None."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def extract_media_dims(media: dict) -> tuple[int | None, int | None]:
    """Pull natural (width, height) from one OF REST media object.

    Reads files.{full,source,preview}, then the same under `info`, then a
    top-level width/height. Returns (None, None) for a WS-shaped media item
    (id only) — which is exactly why raw_json can't be the dims source."""
    if not isinstance(media, dict):
        return (None, None)
    for container_key in ("files", "info"):
        container = media.get(container_key)
        if not isinstance(container, dict):
            continue
        for k in DIM_KEYS:
            sub = container.get(k)
            if isinstance(sub, dict):
                w = _as_pos_int(sub.get("width"))
                h = _as_pos_int(sub.get("height"))
                if w and h:
                    return (w, h)
    # Some payloads put width/height directly on the media object.
    return (_as_pos_int(media.get("width")), _as_pos_int(media.get("height")))


def _media_duration_ms(media: dict) -> int | None:
    """Video/audio length in ms if OF provided it (seconds upstream)."""
    if not isinstance(media, dict):
        return None
    dur = media.get("duration")
    if dur is None:
        files = media.get("files")
        if isinstance(files, dict) and isinstance(files.get("full"), dict):
            dur = files["full"].get("duration")
    try:
        secs = float(dur)
    except (TypeError, ValueError):
        return None
    return int(secs * 1000) if secs > 0 else None


def _media_to_dict(mm: MessageMedia) -> dict[str, Any]:
    """message_media row → the OFMedia-ish shape the seed payload returns.
    width/height stay nullable; the UI tolerates null (neutral skeleton box)."""
    return {
        "id": mm.media_id,
        "type": mm.type,
        "width": mm.width,
        "height": mm.height,
        "thumb_url": mm.thumb_url,
        "source_url": mm.source_url,
        "duration_ms": mm.duration_ms,
    }


async def _load_media_for_messages(
    s: AsyncSession, account_id: str, fan_id: int, message_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """message_id → its message_media rows (as dicts), for a page of messages."""
    if not message_ids:
        return {}
    rows = (
        await s.execute(
            select(MessageMedia).where(
                MessageMedia.account_id == account_id,
                MessageMedia.fan_id == fan_id,
                MessageMedia.message_id.in_(message_ids),
            )
        )
    ).scalars().all()
    out: dict[int, list[dict[str, Any]]] = {}
    for mm in rows:
        out.setdefault(mm.message_id, []).append(_media_to_dict(mm))
    return out


async def reconcile_rest_media(
    s: AsyncSession, account_id: str, fan_id: int, of_messages: list[dict],
) -> None:
    """Upsert message_media rows from OF REST messages — the PRIMARY dims
    source. One row per media item, dims from files/info when present.

    FK-safe: message_media is a CASCADE child of `messages`, so we only write
    rows whose parent message already exists (the WS pump / outbound
    attribution own message persistence — T-API does not take that over;
    cold-start rows still get dims inline on the live payload). Existing dims
    survive on conflict via COALESCE, so a client onload→PATCH is never
    clobbered by a later REST refresh that happens to lack dims."""
    by_msg: dict[int, list[dict]] = {}
    for m in of_messages or []:
        if not isinstance(m, dict):
            continue
        mid = m.get("id")
        media = m.get("media")
        if isinstance(mid, int) and isinstance(media, list) and media:
            by_msg[mid] = media
    if not by_msg:
        return
    existing = set(
        (
            await s.execute(
                select(Message.message_id).where(
                    Message.account_id == account_id,
                    Message.fan_id == fan_id,
                    Message.message_id.in_(list(by_msg.keys())),
                )
            )
        ).scalars()
    )
    if not existing:
        return
    now = datetime.utcnow()
    wrote = False
    for mid, media in by_msg.items():
        if mid not in existing:
            continue
        for item in media:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            w, h = extract_media_dims(item)
            thumb_url, source_url = media_urls(item)
            ins = sqlite_insert(MessageMedia).values(
                account_id=account_id,
                fan_id=fan_id,
                message_id=mid,
                media_id=item["id"],
                type=item.get("type"),
                width=w,
                height=h,
                thumb_url=thumb_url,
                source_url=source_url,
                duration_ms=_media_duration_ms(item),
                updated_at=now,
            )
            stmt = ins.on_conflict_do_update(
                index_elements=["account_id", "fan_id", "message_id", "media_id"],
                set_={
                    # COALESCE(excluded, existing): a fresh REST refresh updates
                    # fields it actually has, but never overwrites a stored value
                    # (e.g. a client onload→PATCHed dim) with a null.
                    "type": func.coalesce(ins.excluded.type, MessageMedia.type),
                    "width": func.coalesce(ins.excluded.width, MessageMedia.width),
                    "height": func.coalesce(ins.excluded.height, MessageMedia.height),
                    "thumb_url": func.coalesce(
                        ins.excluded.thumb_url, MessageMedia.thumb_url
                    ),
                    "source_url": func.coalesce(
                        ins.excluded.source_url, MessageMedia.source_url
                    ),
                    "duration_ms": func.coalesce(
                        ins.excluded.duration_ms, MessageMedia.duration_ms
                    ),
                    "updated_at": now,
                },
            )
            await s.execute(stmt)
            wrote = True
    if wrote:
        await s.commit()


async def stamp_rest_media_dims(
    account_id: str, fan_id: int, of_messages: list[dict],
) -> None:
    """Mutate each media item in `of_messages` to carry top-level width/height
    (so the client gets dims without parsing OF's nested files/info).

    Source order per item: OF inline dims first; then a stored message_media
    row (e.g. a prior client onload→PATCH) for items OF never sized. Leaves
    dims null when neither source has them.

    READ-ONLY by design. `sync_rest_media_dims` used to do this AND the write
    in one await; it is gone, split into this half — the part the HTTP
    response actually needs, so it stays on the request path — and
    `persist_rest_media_dims`, which the caller fires and forgets. That split
    took a write transaction on the single shared SQLite writer off every chat
    open and every 30s/2min poll.

    Best-effort — callers wrap in try/except so a media hiccup never breaks
    chat load."""
    if not of_messages:
        return
    need_db: dict[int, list[dict]] = {}
    for m in of_messages:
        if not isinstance(m, dict):
            continue
        media = m.get("media")
        if not isinstance(media, list):
            continue
        for item in media:
            if not isinstance(item, dict):
                continue
            w, h = extract_media_dims(item)
            if w and h:
                item["width"], item["height"] = w, h
            else:
                item.setdefault("width", None)
                item.setdefault("height", None)
                mid = item.get("id")
                if isinstance(mid, int):
                    need_db.setdefault(mid, []).append(item)
    if not need_db:
        return
    async with get_session() as s:
        rows = (
            await s.execute(
                select(
                    MessageMedia.media_id,
                    MessageMedia.width,
                    MessageMedia.height,
                ).where(
                    MessageMedia.account_id == account_id,
                    MessageMedia.media_id.in_(list(need_db.keys())),
                )
            )
        ).all()
        for media_id, w, h in rows:
            if w and h:
                for item in need_db.get(media_id, []):
                    item["width"], item["height"] = w, h


async def persist_rest_media_dims(
    account_id: str, fan_id: int, of_messages: list[dict],
) -> None:
    """Persist OF REST dims into message_media. The WRITE half of what used to
    be `sync_rest_media_dims`, meant to be fired and forgotten by the route.

    Nothing in the HTTP response depends on it: `stamp_rest_media_dims` has
    already put every dim the client needs on the payload, and this only
    populates the store that a LATER request reads from. Running it off the
    request path means a chat open no longer waits on the shared SQLite writer.

    Swallows its own exceptions rather than relying on the caller: it runs in a
    bare `create_task`, where an escaping error would only surface as an
    unretrieved-task warning."""
    if not of_messages:
        return
    try:
        async with get_session() as s:
            await reconcile_rest_media(s, account_id, fan_id, of_messages)
    except Exception:  # noqa: BLE001
        log.debug(
            "persist_rest_media_dims failed account=%s fan=%s",
            account_id, fan_id, exc_info=True,
        )


# ── routes ─────────────────────────────────────────────────────────────
#
# NOTE: route order matters in FastAPI. The literal-third-segment route
# (`mark-read`) is declared BEFORE the int-parameter route `/{message_id}`
# so "mark-read" doesn't try to parse as an int and 422. The PPV-list
# route at /admin/paid-messages lives at a different prefix, but is
# declared first here as a defensive measure — if anyone ever moves it
# under /admin/messages/* the parametric `{account_id}/{fan_id}` below
# would shadow it.


@router.get("/admin/paid-messages")
async def list_paid_messages(
    request: Request,
    from_: str = Query(..., alias="from", description="ISO date or datetime; required"),
    to: str = Query(..., description="ISO date or datetime; required"),
    account_id: str | None = Query(None),
    employee_id: int | None = Query(None, description="Filters on sent_by_employee_id"),
    status: str = Query("all", pattern="^(paid|unpaid|all)$"),
    type_: str = Query("paid", alias="type", pattern="^(paid|free|all)$"),
    direction: str = Query("out", pattern="^(out|in|any)$"),
    fan_id: int | None = Query(None, description="Exact filter on Message.fan_id"),
    fan_query: str | None = Query(None, description="Substring match on fan username/display name; ≥2 chars"),
    collapse_mass: bool = Query(
        True,
        description="Collapse each mass broadcast's per-fan rows into one "
        "'sent to N fans' summary row (JSON only). Auto-disabled when a single "
        "fan or a fan_query is in scope.",
    ),
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(50, ge=1, le=100),
    # The Message dashboard's filters (plain defaults, so the tests' direct
    # calls see None/False, not a Query sentinel). Validated below.
    q: str | None = None,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    unsent_only: bool = False,
    sender_type: str = "any",
    kind: str = "all",
    before_sent_at: str | None = Query(
        None,
        description="Keyset cursor (primary): ISO send-time of the last row on "
        "the previous page. Paired with before_id as the tiebreaker.",
    ),
    before_id: int | None = Query(
        None,
        description="Keyset cursor (tiebreaker): message_id of the last row on "
        "the previous page. With before_sent_at, paginates by (sent_at, "
        "message_id) DESC; alone, falls back to legacy message_id-only paging.",
    ),
) -> Any:
    """Paginated message list — newest first by send TIME.

    Ordered/paginated on a `(sent_at, message_id)` DESC keyset (message_id
    is the tiebreaker), so collapsed mass-broadcast summaries — which carry a
    synthetic 5e15-band message_id — interleave with normal rows by their real
    send time instead of pinning to page 1.

    Defaults preserve the original PPV-tab semantics: `type=paid`,
    `direction=out`. The All-Messages tab drops both filters by passing
    `type=all&direction=any`; the per-fan deep link adds `fan_id=<id>`.

    Reads `messages` directly. JSON path joins `fans` for display
    name/avatar and `employees` for the sender label. No `transactions`
    join — this endpoint is messages-only by design (see Phase E
    synthesis §3, T-PAIDMSG).

    `purchased_at` may be NULL even when `is_paid=true` — the WS pump
    sometimes lags writing the timestamp. We forward the NULL as-is so
    the UI can render "just paid" without lying with a fabricated time.

    Message dashboard filters (Infloww's): `q` searches the message text,
    `min_price_cents`/`max_price_cents` bound the price, `unsent_only` keeps
    the unsent, `sender_type=employee|automation` splits hand-sent from
    automation-sent, `kind=direct|mass` is the Direct vs mass tab (mass =
    rows on a `mass_run`; an OF-native blast only counts once
    POST /admin/messages/detect-mass has tagged it). JSON rows carry
    `reply_seconds` (see `_build_messages_query`) and the unsent fields; mass
    summaries carry their local `purchased_count` / `earnings_cents`.

    `format=csv` returns a streaming `text/csv` download (50k row cap,
    truncation sentinel + `X-Row-Count` header). `limit`/`before_id` are
    ignored in CSV mode — the export reflects the filter set, not the
    current page.
    """
    if fan_query is not None and len(fan_query) < 2:
        raise HTTPException(status_code=400, detail="fan_query must be 2+ chars")
    if q is not None and not 2 <= len(q) <= 200:
        raise HTTPException(status_code=400, detail="q must be 2-200 chars")
    if (min_price_cents or 0) < 0 or (max_price_cents or 0) < 0:
        raise HTTPException(status_code=400, detail="prices must be >= 0")
    if sender_type not in ("any", "employee", "automation"):
        raise HTTPException(status_code=400, detail="sender_type must be any|employee|automation")
    if kind not in ("all", "direct", "mass"):
        raise HTTPException(status_code=400, detail="kind must be all|direct|mass")
    filters = dict(
        text_query=q, min_price_cents=min_price_cents, max_price_cents=max_price_cents,
        unsent_only=unsent_only, sender_type=sender_type,
    )
    account_ids = clamp_account_filter(account_id)
    # Gate the second axis. Without this, a chatter with access to
    # account_X could ask `?employee_id=<arbitrary id>` and read every
    # message attributed to that random employee on account_X — see the
    # audit notes for the bypass this closed.
    await assert_employee_filter_owned(employee_id)
    start = _parse_date(from_, field="from", request=request)
    end = _parse_date(to, field="to", request=request)

    if format == "csv":
        # Pulling the account-nickname map up front keeps the row loop
        # join-free; the rows stream in the download's own session.
        nick_map: dict[str, str] = {}
        async with get_session() as s:
            nick_rows = (await s.execute(select(Account.id, Account.nickname))).all()
            for ar in nick_rows:
                nick_map[ar.id] = ar.nickname or ""

        q = _build_messages_query(
            start=start, end=end,
            account_ids=account_ids, employee_id=employee_id,
            status=status, type_=type_, direction=direction,
            fan_query=fan_query, fan_id=fan_id,
            for_csv=True, kind=kind, **filters,
        ).order_by(Message.created_at.desc(), Message.message_id.desc())
        # Filename uses raw inputs so the user sees the date range they
        # typed (not the parsed naive-UTC version we computed for SQL).
        filename = (f"messages_{csv_export.safe_filename_part(from_)}"
                    f"_to_{csv_export.safe_filename_part(to)}.csv")
        # The sentinel line has always been 16 cells against the
        # 17-column header; kept so existing exports stay byte-identical.
        return csv_export.download(
            filename, lambda s2: csv_export.query_rows(s2, q), _CSV_HEADER,
            lambda row: _csv_row(row, nick_map), truncated_width=16,
        )

    # Collapse mass broadcasts into one summary row per run, EXCEPT when the
    # view is already narrow (a single fan or a fan search) — there the raw
    # per-fan rows are what the operator wants. Inbound has no mass rows.
    do_collapse = (collapse_mass and fan_id is None and not fan_query and direction != "in"
                   and kind != "direct")

    # Composite keyset cursor: (sent_at, message_id) DESC. before_sent_at is
    # the previous page's last send time; before_id breaks ties within the
    # same timestamp. before_dt is naive UTC to match the column convention
    # (these isoformat strings always carry a "T", so no end-of-day shift).
    before_dt: datetime | None = None
    if before_sent_at:
        try:
            before_dt = datetime.fromisoformat(before_sent_at)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"invalid before_sent_at: {e}"
            ) from e
    before: tuple[datetime, int] | None = (
        (before_dt, before_id) if before_dt is not None and before_id is not None else None
    )

    async with get_session() as s:
        mq = _build_messages_query(
            start=start, end=end,
            account_ids=account_ids, employee_id=employee_id,
            status=status, type_=type_, direction=direction,
            fan_query=fan_query, fan_id=fan_id,
            for_csv=False, kind=kind, **filters,
        )
        if do_collapse:
            # Per-fan mass rows are replaced by the summary rows below.
            mq = mq.where(Message.mass_run_id.is_(None))
        mq = _keyset_where(mq, before=before, before_id=before_id)
        mq = mq.order_by(Message.created_at.desc(), Message.message_id.desc()).limit(limit)

        rows = (await s.execute(mq)).all()

        mass_rows: list[dict[str, Any]] = []
        if do_collapse:
            mass_rows = await _collapsed_mass_rows(
                s=s, start=start, end=end, account_ids=account_ids,
                employee_id=employee_id, type_=type_,
                before=before, limit=limit, **filters,
            )

    # 200-char body truncation kept for paid-only (default) so PPV-tab
    # payloads stay small; expanded to 2000 once the All-Messages tab
    # asks for inbound or free bodies (rendered with line-clamp client-side).
    body_cap = 200 if type_ == "paid" else 2000
    return _page([_paid_row(r, body_cap) for r in rows], mass_rows, limit)


@router.get("/admin/messages/{account_id}/{fan_id}")
async def list_messages(
    account_id: str,
    fan_id: int,
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, description="Return messages with message_id < this"),
) -> dict[str, Any]:
    """Paginated timeline — newest first.

    Cursor is the last seen `message_id`. Ordering by message_id DESC
    means the PK (account_id, fan_id, message_id) covers both the filter
    and the sort, no separate sort step needed.

    Mass-send optimistic placeholders (`attribution._MASS_PLACEHOLDER_BASE`
    band) are served only while fresh (≤1h): they exist to bridge the
    send→delivery window, but a placeholder that was never reconciled — or
    whose broadcast was auto-unsent on OF — would otherwise seed the chat
    pane forever, since its synthetic id sits above every real OF id and the
    client's fresh-page merge can't retire it. The chat UI is this endpoint's
    only consumer, and the OF fetch is the truth for anything older."""
    assert_account_owned(account_id)
    from attribution import _MASS_PLACEHOLDER_BASE  # local: matches _collapsed_mass_rows
    from transaction_ingest import _TIP_MSG_ID_BASE  # band END — tips start here
    placeholder_floor = datetime.utcnow() - timedelta(hours=1)
    async with get_session() as s:
        q = (
            select(Message)
            .where(Message.account_id == account_id, Message.fan_id == fan_id)
            # The age cutoff applies ONLY to the mass-placeholder band
            # [5e15, 6e15). At 6e15 the ledger-synthesized TIP rows begin
            # (transaction_ingest._TIP_MSG_ID_BASE) — those are permanent
            # synthetic history the WS pump never saw, and this seed is their
            # ONLY render path, so they must never age out.
            .where(or_(
                Message.message_id < _MASS_PLACEHOLDER_BASE,
                Message.message_id >= _TIP_MSG_ID_BASE,
                Message.created_at >= placeholder_floor,
            ))
            # An unsent bubble is gone from OF, so it must not seed the pane:
            # the seed carries no media, so it would repaint as an empty
            # locked shell on every reload. The client drops these too, but
            # filtering here is what makes the mirror flip (mark_unsent, in
            # messages_unsent.py) effective for a browser still running an
            # older bundle.
            .where(Message.is_unsent.is_(False))
            .order_by(Message.message_id.desc())
            .limit(limit)
        )
        if before_id is not None:
            q = q.where(Message.message_id < before_id)
        rows = (await s.execute(q)).scalars().all()
        media_by_msg = await _load_media_for_messages(
            s, account_id, fan_id, [m.message_id for m in rows]
        )
        items = [_row_to_dict(m, media_by_msg.get(m.message_id, [])) for m in rows]
        # next_before_id: cursor the client passes next call. Null means
        # this page was shorter than `limit`, so there's nothing more.
        next_before = items[-1]["message_id"] if len(items) == limit else None
        return {
            "messages": items,
            "limit": limit,
            "next_before_id": next_before,
        }


@router.get("/admin/messages/{account_id}/{fan_id}/attribution")
async def list_message_attribution(
    account_id: str,
    fan_id: int,
    since_id: int | None = Query(None, description="Only return rows with message_id >= this"),
    limit: int = Query(200, ge=1, le=200),
) -> dict[str, Any]:
    """Map message_id → sender employee for outbound bubbles.

    LEFT JOIN messages.sent_by_employee_id → employees.id. Deleted
    employees (ON DELETE SET NULL on sent_by_employee_id, or rows that
    never had an employee captured) produce NULL display_name; we emit
    `display_name=null` so the UI's "render only if truthy" guard skips
    them — never the literal string "null"."""
    assert_account_owned(account_id)
    async with get_session() as s:
        q = (
            select(
                Message.message_id,
                Message.sent_by_employee_id,
                Message.automation_kind,
                Message.sender_name,
                Employee.display_name,
                Employee.color,
                Message.unsent_at,
                Message.unsent_reason,
                Message.created_at,
            )
            .select_from(Message)
            .outerjoin(Employee, Employee.id == Message.sent_by_employee_id)
            .where(
                Message.account_id == account_id,
                Message.fan_id == fan_id,
                Message.direction == "out",
            )
        )
        if since_id is not None:
            q = q.where(Message.message_id >= since_id)
        q = q.order_by(Message.message_id.desc()).limit(limit)
        rows = (await s.execute(q)).all()

    by_msg_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_msg_id[str(r.message_id)] = {
            "employee_id": r.sent_by_employee_id,
            "display_name": r.display_name,
            # Which automation sent it ("welcome_chatter_for_info", "autoreply", …). When set,
            # the bubble shows the specific automation name instead of the flat
            # "Automation" sentinel that every bot send's display_name resolves to.
            "automation_kind": r.automation_kind,
            # Denormalized mass sender tag ("mass-kingsley1") for HUMAN broadcast
            # rows; "" for 1:1 sends and automation-fired mass (the Automation
            # sentinel is excluded in attribution.mass_sender_tag). The bubble
            # prefers this over the automation label / employee name.
            "sender_name": r.sender_name,
            "color": r.color,
            # Set once WE unsent it (mark_unsent / the mass-unsend flips). The
            # bubble is gone from OF, so the thread draws a "Message withdrawn"
            # line in its place; `unsent_reason` tells a manual unsend from an
            # automatic one ("automation:…").
            "unsent_at": r.unsent_at.isoformat() if r.unsent_at else None,
            "unsent_reason": r.unsent_reason,
            # When it was sent: the withdrawn line's Date divider.
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
    return {"by_msg_id": by_msg_id}


def _iso(v: Any) -> datetime | None:
    """Parse an OF ISO timestamp ('...Z' or '+00:00'); None on anything odd."""
    if not isinstance(v, str) or not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def reconcile_chats_from_of(account_id: str, of_chats: list[dict]) -> int:
    """Reconcile local `chats` from a fresh OF /chats payload — read state +
    last-message direction. Returns the number of chats touched.

    Why this exists: OF's `unreadMessagesCount` is the SOURCE OF TRUTH for read
    state (cleared when a chat is read on OF web OR via our mark-as-read), but
    nothing local mirrored it. `chats.unread_count` is WS-incremented and only
    zeroed by an app-side outbound send, so it drifted toward "every chat that
    ever got a DM" — which is why the roster blue badge read as a *total* instead
    of the real unread backlog. We piggy-back on the inbox's existing /chats fetch
    (NO new OF calls) to pull OF's truth into the tables the roster aggregate reads.

    Per chat we:
      • set `unread_count` = OF's count (unconditional — OF is authoritative), and
      • advance the last message + persist its direction MONOTONICALLY, so an
        OF-web reply (which the WS pump skips) flips the chat off the owe-reply
        badge without waiting for the next scrape.

    Monotonic-on-message_id makes the last-message advance safe against a
    concurrent WS write landing a newer inbound mid-reconcile; unread_count is set
    every time because read state isn't monotonic. Best-effort: own session,
    swallows errors — a sync hiccup must never break the inbox response it rides on.
    """
    from attribution import adopt_thread_placeholders  # local: circular import

    own = str(account_id)
    touched = 0
    try:
        async with get_session() as s:
            for c in of_chats:
                wu = c.get("withUser") or {}
                fan_id = wu.get("id")
                if fan_id is None:
                    continue
                unread = int(c.get("unreadMessagesCount") or 0)
                lm = c.get("lastMessage") or {}
                lm_id = lm.get("id")
                from_id = (lm.get("fromUser") or {}).get("id")

                # (a) Ensure the last message exists locally WITH its direction so
                #     the roster's last_message_id→direction join can classify it.
                #     do_nothing: never clobber a fuller row the WS/scrape wrote.
                if lm_id is not None and from_id is not None:
                    direction = "out" if str(from_id) == own else "in"
                    await s.execute(
                        sqlite_insert(Message)
                        .values(account_id=own, fan_id=int(fan_id),
                                message_id=int(lm_id), direction=direction,
                                body=(lm.get("text") or ""),
                                created_at=_iso(lm.get("createdAt")) or datetime.utcnow())
                        .on_conflict_do_nothing(
                            index_elements=["account_id", "fan_id", "message_id"])
                    )
                    # Fastest place we ever see OF's real id for an un-echoed
                    # optimistic send: this rides the inbox poll (60-90s) where
                    # the scrape is hours behind. Folding the stub in here keeps
                    # the thread from showing the PPV twice for a whole afternoon,
                    # and keeps the real row from reading as a human send. Gated
                    # on an OUTBOUND last message so an all-inbound inbox page
                    # doesn't pay a lookup per chat for something that can only
                    # ever pair with an outbound row.
                    if direction == "out":
                        await adopt_thread_placeholders(
                            s, account_id=own, fan_id=int(fan_id))

                # (b) unread_count = OF truth, unconditionally (create row if new).
                await s.execute(
                    sqlite_insert(Chat)
                    .values(account_id=own, fan_id=int(fan_id), unread_count=unread)
                    .on_conflict_do_update(
                        index_elements=["account_id", "fan_id"],
                        set_={"unread_count": unread})
                )

                # (c) Advance the chat's last message forward-only.
                if lm_id is not None:
                    preview = (lm.get("text") or "")[:120]
                    await s.execute(
                        sqlite_insert(Chat)
                        .values(account_id=own, fan_id=int(fan_id),
                                last_message_id=int(lm_id),
                                last_message_at=_iso(lm.get("createdAt")),
                                last_message_preview=preview)
                        .on_conflict_do_update(
                            index_elements=["account_id", "fan_id"],
                            set_={"last_message_id": int(lm_id),
                                  "last_message_at": _iso(lm.get("createdAt")),
                                  "last_message_preview": preview},
                            where=(Chat.last_message_id.is_(None))
                                  | (Chat.last_message_id < int(lm_id)),
                        )
                    )
                touched += 1
            await s.commit()
    except Exception:
        log.warning("reconcile_chats_from_of(%s) failed — best-effort", account_id,
                    exc_info=True)
    return touched


@router.post("/admin/messages/{account_id}/{fan_id}/mark-read")
async def mark_chat_read(account_id: str, fan_id: int) -> dict[str, Any]:
    """LOCAL read-marker — zeroes `chats.unread_count` for this pair.

    Does NOT call OF. The relay endpoint that POSTs to OF's chat read
    endpoint is responsible for the upstream side; this just keeps our
    inbox badge from lying after the user has clearly seen the messages.
    The inbox calls this on EVERY chat open (no OF round-trip) so a chat the
    chatter reads but doesn't reply to flips from the roster's blue (unread)
    count to orange (owe reply) immediately, even when OF already considered
    it read (so our `reconcile_chats_from_of` left nothing to clear).

    The WHERE guards on `unread_count > 0` so the rowcount tells the caller
    whether anything ACTUALLY changed — a chat opened with nothing locally
    unread returns `cleared=false`, letting the UI skip a needless roster
    refetch."""
    assert_account_owned(account_id)
    # Read state mirrors OF's, so it goes through the OF-cache writer — in
    # order with the DMs of this chat queued before it, and in their commit.
    from db import of_writer  # noqa: PLC0415
    cleared = await of_writer.write(_clear_unread, (account_id, int(fan_id)),
                                    key=(account_id, int(fan_id)))
    # cleared=False → no chats row yet (WS hasn't transcoded one) OR it was
    # already read. Not an error — 200 with cleared=false.
    if cleared:
        # Reading a chat moves it off the roster's blue (unread) count. That
        # badge is served from a 5-min OF cache that ONLY the WS pump busts
        # (on messages) — a read isn't a message, so without this the poll
        # would keep serving the pre-read count for up to the full TTL. Bust
        # it so the next roster poll re-reads OF and the badge drop sticks.
        import relay_cache  # noqa: PLC0415 — defer; avoids an import cycle at module load
        relay_cache.invalidate("roster_count", account_id)
    return {"account_id": account_id, "fan_id": fan_id, "cleared": cleared}


async def _clear_unread(conn, items: list) -> list:
    """of_writer op: zero one chat's unread. The WHERE guards on
    `unread_count > 0`, so each read reports whether it ACTUALLY changed."""
    out = []
    for account_id, fan_id in items:
        res = await conn.execute(
            update(Chat)
            .where(Chat.account_id == account_id, Chat.fan_id == fan_id, Chat.unread_count > 0)
            .values(unread_count=0)
        )
        out.append((res.rowcount or 0) > 0)
    return out


@router.post("/admin/messages/{account_id}/{fan_id}/rescrape-now")
async def rescrape_chat_now(account_id: str, fan_id: int) -> dict[str, Any]:
    """Synchronously re-scrape ONE fan's chat from OF into the local DB and
    return when done — the chat ↻ refresh's "instant re-cache".

    Runs INLINE, NOT via the automation queue, on purpose. The queued
    scrape_chats path dispatches per (account, kind) behind a per-(account, kind)
    in-flight guard, so an interactive single-fan refresh would otherwise wait
    for a whole multi-minute account-wide scrape sweep that shares the same
    (account, 'scrape_chats') pair to finish first. Calling _scrape_one_chat
    directly sidesteps the queue, both bulk-lane slots, and that guard, so the
    re-cache lands in ~1-2s regardless of background sweeps. Recent-end fast-skip
    makes repeat clicks cheap. Best-effort: returns ok=false on failure — the UI
    already shows live OF data (messages/profile/PPV) regardless of this call."""
    assert_account_owned(account_id)
    try:
        # Local import: the executor pulls in the whole automation graph; defer
        # it to request time (it's already loaded in-process) to avoid a cycle.
        from automation_executor import (  # noqa: PLC0415
            _make_client, _scrape_one_chat,
            _SCRAPE_PAGE_SIZE, _SCRAPE_MAX_PAGES,
        )
        client = await asyncio.to_thread(_make_client, account_id)
        inserted, seen = await _scrape_one_chat(
            account_id, client.user_id, client, int(fan_id), None,
            page_size=_SCRAPE_PAGE_SIZE, max_pages=_SCRAPE_MAX_PAGES,
        )
        return {"account_id": account_id, "fan_id": fan_id,
                "ok": True, "inserted": inserted, "seen": seen}
    except Exception as exc:  # best-effort — never 500 a UI refresh
        log.warning("rescrape_chat_now(%s,%s) failed — best-effort",
                    account_id, fan_id, exc_info=True)
        return {"account_id": account_id, "fan_id": fan_id, "ok": False, "error": str(exc)}


@router.post("/admin/messages/detect-mass")
async def detect_mass(
    account_id: str | None = Query(
        None, description="Scope to one account; omit for every account the principal owns"
    ),
    gap_seconds: int = Query(180, ge=10, le=3600, description="Max gap between consecutive sends in one burst"),
    min_recipients: int = Query(5, ge=2, le=10000, description="Min distinct fans for a burst to count as mass"),
    dry_run: bool = Query(False, description="Report what would be tagged without writing"),
) -> dict[str, Any]:
    """Retro-tag OF-native mass blasts the WS pump stored as per-fan rows.

    Sessionizes untagged outbound rows (`mass_run_id IS NULL` AND
    `automation_kind IS NULL`) into bursts and stamps a synthetic MassRun on
    each, so the Messages list collapses them into one "MASS · sent to N" row.
    Idempotent — only touches rows not already tied to a run. See
    mass_detect.py for the burst rule."""
    from mass_detect import detect_mass_bursts

    account_ids = clamp_account_filter(account_id)
    return await detect_mass_bursts(
        account_ids=account_ids,
        gap_seconds=gap_seconds,
        min_recipients=min_recipients,
        dry_run=dry_run,
    )


async def local_mass_sales(
    s: AsyncSession,
    account_id: str,
    *,
    runs: dict[int, int],
    queues: dict[int, int],
    since: datetime | None,
) -> dict[int, tuple[int, int]]:
    """`{broadcast: (buyers, earnings_cents)}` from OUR rows — no OF call. The one
    count behind both the Message dashboard's mass summaries and the sent list's
    Purchased / Earnings.

    A broadcast is the caller's key: `runs` maps a `mass_run_id`, and `queues` an
    OF queue id, to it (the dashboard keys on the run, the sent list on the
    queue). A fan's copy is recognised the two ways `mark_queue_copies_unsent`
    recognises one by id: the run we recorded (placeholder included), or OF's own
    `queueId` on a scraped frame — read structurally, `LIKE` is the prefilter.

    A copy counts when the ledger link marked it bought (`is_paid` /
    `purchased_at` on that row), at the copy's price, and its linked transaction, if any, is not a refund, chargeback
    or failure (pending counts, like every earnings read). A funnel follow-up
    (`funnel_step`) carries the run's id but is its own sale, so it stays out.
    One sale per fan per broadcast, so a placeholder still standing beside its
    real twin counts once.

    A floor, not OF's figure: a list-audience blast has no row for a buyer
    whose copy we never scraped or polled. Earnings are gross (the offer price)."""
    if not runs and not queues:
        return {}
    refunded = (
        select(Transaction.id)
        .where(
            Transaction.account_id == Message.account_id,
            Transaction.fan_id == Message.fan_id,
            Transaction.message_id == Message.message_id,
            Transaction.status.notin_(TRACKED_STATUSES),
        )
        .exists()
    )
    which = [Message.mass_run_id.in_(list(runs))] if runs else []
    if queues:
        which.append(and_(Message.mass_run_id.is_(None), Message.raw_json.like("%queueId%")))
    stmt = select(
        Message.fan_id, Message.price_cents, Message.mass_run_id, Message.raw_json,
    ).where(
        Message.account_id == account_id,
        Message.direction == "out",
        Message.funnel_step.is_(None),
        or_(Message.is_paid.is_(True), Message.purchased_at.is_not(None)),
        or_(*which),
        ~refunded,
    )
    if since is not None:
        stmt = stmt.where(Message.created_at >= since)

    per: dict[int, dict[int, int]] = {}
    for fan_id, price_cents, mass_run_id, raw_json in (await s.execute(stmt)).all():
        if mass_run_id is not None:
            key = runs.get(int(mass_run_id))
        else:
            qid = _queue_id_of(raw_json)
            key = queues.get(qid) if qid is not None else None
        if key is None:
            continue
        fans = per.setdefault(key, {})
        fans[int(fan_id)] = max(fans.get(int(fan_id), 0), int(price_cents or 0))
    return {key: (len(fans), sum(fans.values())) for key, fans in per.items()}
