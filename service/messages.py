from __future__ import annotations

import asyncio
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
from events import js_safe_id
from attribution_backfill import TRACKED_STATUSES
from stats import _parse_date
from auth import assert_account_owned, assert_employee_filter_owned, clamp_account_filter
from of_coerce import json_list
from of_shapes import DIM_KEYS, media_urls
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
        "fan_id": js_safe_id(m.fan_id),
        "message_id": js_safe_id(m.message_id),
        "direction": m.direction,
        "sender_name": m.sender_name,
        "body": m.body,
        "media_ids": json_list(m.media_ids),
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



def _as_pos_int(v: Any) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


# Dims never come from Message.raw_json: the WS event carries only the media id.
def extract_media_dims(media: dict) -> tuple[int | None, int | None]:
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
    return (_as_pos_int(media.get("width")), _as_pos_int(media.get("height")))


def _media_duration_ms(media: dict) -> int | None:
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
                    # A REST refresh lacking dims must not null a value a client PATCH stored.
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




# Route order matters: the literal `mark-read` segment is declared before int-param routes, and this one before the parametric `{account_id}/{fan_id}` that would shadow it.
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
    # Without this a chatter could read any employee's messages via ?employee_id=.
    await assert_employee_filter_owned(employee_id)
    start = _parse_date(from_, field="from", request=request)
    end = _parse_date(to, field="to", request=request)

    if format == "csv":
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
        filename = (f"messages_{csv_export.safe_filename_part(from_)}"
                    f"_to_{csv_export.safe_filename_part(to)}.csv")
        # Sentinel line is 16 cells vs the 17-column header; kept so exports stay byte-identical.
        return csv_export.download(
            filename, lambda s2: csv_export.query_rows(s2, q), _CSV_HEADER,
            lambda row: _csv_row(row, nick_map), truncated_width=16,
        )

    do_collapse = (collapse_mass and fan_id is None and not fan_query and direction != "in"
                   and kind != "direct")

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
    from attribution import _MASS_PLACEHOLDER_BASE
    from transaction_ingest import _TIP_MSG_ID_BASE
    placeholder_floor = datetime.utcnow() - timedelta(hours=1)
    async with get_session() as s:
        q = (
            select(Message)
            .where(Message.account_id == account_id, Message.fan_id == fan_id)
            # Age cutoff only for the mass-placeholder band [5e15, 6e15); tip rows (>=6e15) are permanent synthetic history, never age out.
            .where(or_(
                Message.message_id < _MASS_PLACEHOLDER_BASE,
                Message.message_id >= _TIP_MSG_ID_BASE,
                Message.created_at >= placeholder_floor,
            ))
            # Unsent bubble is gone from OF; the seed has no media, so it would repaint as an empty locked shell.
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
            "automation_kind": r.automation_kind,
            "sender_name": r.sender_name,
            "color": r.color,
            "unsent_at": r.unsent_at.isoformat() if r.unsent_at else None,
            "unsent_reason": r.unsent_reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
    return {"by_msg_id": by_msg_id}


def _iso(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def reconcile_chats_from_of(account_id: str, of_chats: list[dict]) -> int:
    # OF's unreadMessagesCount is the read-state truth, set unconditionally; the last message only advances forward so a concurrent WS write isn't clobbered.
    from db import of_writer  # noqa: PLC0415
    try:
        return await of_writer.write(_reconcile_chats, (str(account_id), of_chats))
    except Exception:
        log.warning("reconcile_chats_from_of(%s) failed — best-effort", account_id,
                    exc_info=True)
        return 0


async def _reconcile_chats(conn, items: list) -> list:
    from attribution import adopt_thread_placeholders

    out = []
    for own, of_chats in items:
        msgs, unread, last, outbound = [], [], [], []
        for c in of_chats:
            fan_id = (c.get("withUser") or {}).get("id")
            if fan_id is None:
                continue
            fan_id = int(fan_id)
            lm = c.get("lastMessage") or {}
            lm_id = lm.get("id")
            from_id = (lm.get("fromUser") or {}).get("id")
            # do_nothing: never clobber a fuller row the WS/scrape wrote.
            if lm_id is not None and from_id is not None:
                direction = "out" if str(from_id) == own else "in"
                msgs.append(dict(account_id=own, fan_id=fan_id, message_id=int(lm_id),
                                 direction=direction, body=(lm.get("text") or ""),
                                 created_at=_iso(lm.get("createdAt")) or datetime.utcnow()))
                # Fastest place we see OF's real id for an un-echoed optimistic send (scrape is hours behind).
                if direction == "out":
                    outbound.append(fan_id)
            # unread_count is OF truth, set unconditionally.
            unread.append(dict(account_id=own, fan_id=fan_id,
                               unread_count=int(c.get("unreadMessagesCount") or 0)))
            if lm_id is not None:
                last.append(dict(account_id=own, fan_id=fan_id, last_message_id=int(lm_id),
                                 last_message_at=_iso(lm.get("createdAt")),
                                 last_message_preview=(lm.get("text") or "")[:120]))
        if msgs:
            await conn.execute(sqlite_insert(Message).on_conflict_do_nothing(
                index_elements=["account_id", "fan_id", "message_id"]), msgs)
        if outbound:
            s = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                for fan_id in outbound:
                    await adopt_thread_placeholders(s, account_id=own, fan_id=fan_id)
                await s.flush()
            finally:
                await s.close()
        if unread:
            ins = sqlite_insert(Chat)
            await conn.execute(ins.on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"unread_count": ins.excluded.unread_count}), unread)
        if last:
            ins = sqlite_insert(Chat)
            ex = ins.excluded
            await conn.execute(ins.on_conflict_do_update(
                index_elements=["account_id", "fan_id"],
                set_={"last_message_id": ex.last_message_id, "last_message_at": ex.last_message_at,
                      "last_message_preview": ex.last_message_preview},
                where=(Chat.last_message_id.is_(None)) | (Chat.last_message_id < ex.last_message_id)), last)
        out.append(len(unread))
    return out


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
    # Read state goes through the OF-cache writer, in order with this chat's queued DMs.
    from db import of_writer  # noqa: PLC0415
    cleared = await of_writer.write(_clear_unread, (account_id, int(fan_id)),
                                    key=(account_id, int(fan_id)))
    if cleared:
        # Roster unread badge is a 5-min OF cache only the WS pump busts; a read isn't a message, so bust it.
        import relay_cache  # noqa: PLC0415 — defer; avoids an import cycle at module load
        relay_cache.invalidate("roster_count", account_id)
    return {"account_id": account_id, "fan_id": fan_id, "cleared": cleared}


async def _clear_unread(conn, items: list) -> list:
    out = []
    for account_id, fan_id in items:
        res = await conn.execute(
            update(Chat)
            .where(Chat.account_id == account_id, Chat.fan_id == fan_id, Chat.unread_count > 0)
            .values(unread_count=0)
        )
        out.append((res.rowcount or 0) > 0)
    return out


_full_pulls: dict[tuple[str, int], asyncio.Task] = {}
_PULL_WAIT_S = 8.0
_PULL_MAX_CHUNKS = 20
_PULL_BUDGET_S = 60.0


async def _pull_whole_history(account_id: str, fan_id: int) -> tuple[int, int, bool]:
    from automation_executor import _make_client, _scrape_one_chat, _SCRAPE_MAX_PAGES, _SCRAPE_PAGE_SIZE  # noqa: PLC0415
    import of_pacing  # noqa: PLC0415

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _PULL_BUDGET_S
    client = await asyncio.to_thread(_make_client, account_id)

    async def pull():
        inserted = seen = 0
        for _ in range(_PULL_MAX_CHUNKS):
            if loop.time() >= deadline:
                break
            chunk = await _scrape_one_chat(
                account_id, client.user_id, client, fan_id, None,
                page_size=_SCRAPE_PAGE_SIZE, max_pages=_SCRAPE_MAX_PAGES,
                mode="pull", deadline=deadline,
            )
            inserted += chunk.inserted
            seen += chunk.seen
            if chunk.rate_limited:
                break
            if not chunk.history_saved:
                continue
            if loop.time() < deadline and not chunk.gap_left:
                return inserted, seen, True
            if not chunk.seen:
                break
        return inserted, seen, False

    return await of_pacing.walk(account_id, "chat_refresh", pull)


def _pull_done(key: tuple[str, int], task: asyncio.Task) -> None:
    _full_pulls.pop(key, None)
    if not task.cancelled() and task.exception() is not None:
        log.warning("chat_history_pull_failed account=%s chat=%s", *key, exc_info=task.exception())


@router.post("/admin/messages/{account_id}/{fan_id}/rescrape-now")
async def rescrape_chat_now(account_id: str, fan_id: int) -> dict[str, Any]:
    """Re-scrape ONE fan's chat from OF into the local DB — the chat ↻ refresh.

    Commits bounded chunks of history. Returns `complete` when the tracked gap
    is filled, `partial` when the pull stops early, or `pending` while it is
    still running. Only `complete` returns ok=true."""
    assert_account_owned(account_id)
    key = (str(account_id), int(fan_id))
    task = _full_pulls.get(key)
    if task is None:
        task = asyncio.create_task(_pull_whole_history(*key), name=f"chat-pull-{account_id}-{fan_id}")
        _full_pulls[key] = task
        task.add_done_callback(lambda t: _pull_done(key, t))
    done, _ = await asyncio.wait({task}, timeout=_PULL_WAIT_S)
    if not done:
        return {"account_id": account_id, "fan_id": fan_id, "ok": False, "status": "pending"}
    exc = task.exception()
    if exc is not None:
        return {"account_id": account_id, "fan_id": fan_id, "ok": False, "status": "partial", "error": str(exc)}
    inserted, seen, complete = task.result()
    return {"account_id": account_id, "fan_id": fan_id, "ok": complete,
            "status": "complete" if complete else "partial", "inserted": inserted, "seen": seen}


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
