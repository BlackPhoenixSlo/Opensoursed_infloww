"""
messages_query.py — the read model behind GET /admin/paid-messages (the
Message dashboard / PPV tab): the shared SELECT builder, the dashboard's row
filters, the keyset cursor + page merge, the JSON/CSV row shapers and the
collapsed mass-broadcast summaries.

The route itself (param parsing, validation) stays in messages.py, which
re-exports these names. This module must not import messages at its top
(messages imports it); the one call back (`local_mass_sales`) is lazy.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from db.models import Employee, Fan, MassBroadcastCache, MassMessageFunnel, MassRun, Message


def _build_messages_query(
    *,
    start: datetime | None,
    end: datetime | None,
    account_ids: list[str] | None,
    employee_id: int | None,
    status: str,
    type_: str,
    direction: str,
    fan_query: str | None,
    fan_id: int | None,
    for_csv: bool,
    text_query: str | None = None,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    unsent_only: bool = False,
    sender_type: str = "any",
    kind: str = "all",
):
    """Shared SELECT builder for both JSON paginated + CSV streaming paths.

    `for_csv=True` returns full `Message` ORM rows with `Fan`/`Employee`
    eager-loaded via `selectinload` (separate IN-query, not a join) so
    the row stream stays a tight Message-only scan. The JSON path keeps
    its narrow column list to avoid pulling `raw_json`/`media_ids` text.
    """
    if for_csv:
        # No ORM relationships are declared on Message → Fan/Employee
        # (see db/models.py Message class), so we can't use selectinload.
        # Instead we explicit-join here and let `s.stream()` iterate row
        # tuples; memory stays bounded because the consumer flushes each
        # row's CSV bytes before pulling the next.
        q = (
            select(
                Message.account_id,
                Message.fan_id,
                Message.message_id,
                Message.body,
                Message.media_count,
                Message.price_cents,
                Message.is_paid,
                Message.direction,
                Message.is_tip,
                Message.created_at,
                Message.purchased_at,
                Message.sent_by_employee_id,
                Message.automation_kind,
                Message.mass_run_id,
                Fan.of_username,
                Fan.of_display_name,
                Employee.display_name.label("employee_name"),
            )
            .select_from(Message)
            .outerjoin(
                Fan,
                and_(Fan.account_id == Message.account_id, Fan.fan_id == Message.fan_id),
            )
            .outerjoin(Employee, Employee.id == Message.sent_by_employee_id)
        )
    else:
        # Reply time (Infloww's): when the message before an outbound direct row
        # in its thread is the fan's, that message's time — else NULL (a
        # follow-up to our own message, or the opener). One correlated seek per
        # row on ix_messages_chat_seq. Mass rows sit out on both sides:
        # a blast is not a reply, and one landing between the fan's message and
        # ours does not make ours any less of one.
        prev = aliased(Message)
        prev_in_at = (
            select(case((prev.direction == "in", prev.created_at)))
            .where(
                prev.account_id == Message.account_id,
                prev.fan_id == Message.fan_id,
                prev.created_at < Message.created_at,
                prev.direction.in_(("in", "out")),
                prev.mass_run_id.is_(None),
            )
            .order_by(prev.created_at.desc())
            .limit(1)
            .correlate(Message)
            .scalar_subquery()
        )
        q = (
            select(
                Message.account_id,
                Message.fan_id,
                Message.message_id,
                Message.body,
                Message.media_count,
                Message.price_cents,
                Message.is_paid,
                Message.direction,
                Message.is_tip,
                Message.created_at,
                Message.purchased_at,
                Message.sent_by_employee_id,
                Message.automation_kind,
                Message.mass_run_id,
                Message.is_unsent,
                Message.unsent_at,
                Message.unsent_reason,
                case(
                    (and_(Message.direction == "out", Message.mass_run_id.is_(None)),
                     prev_in_at),
                ).label("reply_to_at"),
                Fan.of_username,
                Fan.of_display_name,
                Fan.avatar_url,
                Employee.display_name.label("employee_name"),
            )
            .select_from(Message)
            .outerjoin(
                Fan,
                and_(Fan.account_id == Message.account_id, Fan.fan_id == Message.fan_id),
            )
            .outerjoin(Employee, Employee.id == Message.sent_by_employee_id)
        )

    if direction in ("in", "out"):
        q = q.where(Message.direction == direction)
    if type_ == "paid":
        q = q.where(Message.price_cents > 0)
    elif type_ == "free":
        q = q.where(Message.price_cents == 0)
    if start is not None:
        q = q.where(Message.created_at >= start)
    if end is not None:
        q = q.where(Message.created_at <= end)
    if account_ids is not None:
        q = q.where(Message.account_id.in_(account_ids))
    if employee_id is not None:
        q = q.where(Message.sent_by_employee_id == employee_id)
    if fan_id is not None:
        q = q.where(Message.fan_id == fan_id)
    if status == "paid" and type_ != "free":
        q = q.where(Message.is_paid.is_(True))
    elif status == "unpaid" and type_ != "free":
        # NULL is_paid coexists with price_cents>0 on legacy rows
        # (OF didn't always echo the flag) — treat NULL as unpaid.
        q = q.where(or_(Message.is_paid.is_(False), Message.is_paid.is_(None)))
    if fan_query and not for_csv:
        like = f"%{fan_query}%"
        q = q.where(or_(Fan.of_username.like(like), Fan.of_display_name.like(like)))
    elif fan_query and for_csv:
        # CSV path didn't outerjoin Fan in the base select — apply via
        # a subquery on fans to keep filter semantics identical.
        like = f"%{fan_query}%"
        fan_ids = (
            select(Fan.fan_id)
            .where(Fan.account_id == Message.account_id)
            .where(or_(Fan.of_username.like(like), Fan.of_display_name.like(like)))
            .scalar_subquery()
        )
        q = q.where(Message.fan_id.in_(fan_ids))
    if kind == "direct":
        q = q.where(Message.mass_run_id.is_(None))
    elif kind == "mass":
        q = q.where(Message.mass_run_id.is_not(None))

    return _apply_dashboard_filters(
        q, text_query=text_query, min_price_cents=min_price_cents,
        max_price_cents=max_price_cents, unsent_only=unsent_only,
        sender_type=sender_type,
    )


def _apply_dashboard_filters(
    q,
    *,
    text_query: str | None,
    min_price_cents: int | None,
    max_price_cents: int | None,
    unsent_only: bool,
    sender_type: str,
):
    """The Message dashboard's row filters (Infloww's Search message text,
    Price min/max, Status = unsent, Type = Employee / AI), shared by the
    per-row query and the collapsed mass summaries so both halves of a page
    answer the same question.

    `sender_type`: "employee" = an outbound row no automation stamped
    (`automation_kind IS NULL` — a human typed or picked it, Copilot
    suggestions included, since the chatter sends those by hand);
    "automation" = an automation sent it. Either one implies outbound."""
    if text_query:
        # autoescape: a typed `%` or `_` is a character to find, not a wildcard.
        q = q.where(Message.body.contains(text_query, autoescape=True))
    if min_price_cents is not None:
        q = q.where(Message.price_cents >= min_price_cents)
    if max_price_cents is not None:
        q = q.where(Message.price_cents <= max_price_cents)
    if unsent_only:
        q = q.where(Message.is_unsent.is_(True))
    if sender_type == "employee":
        q = q.where(Message.direction == "out", Message.automation_kind.is_(None))
    elif sender_type == "automation":
        q = q.where(Message.direction == "out", Message.automation_kind.is_not(None))
    return q


def _keyset_where(q, *, before: tuple[datetime, int] | None, before_id: int | None):
    """The page cursor on the per-row query: strictly below `before` on the
    `(sent_at, message_id)` DESC keyset, else (an old client that omitted
    before_sent_at) the legacy single-key `message_id < before_id`. The mass
    summaries apply the same `before` in Python (`_collapsed_mass_rows`)."""
    if before is not None:
        b_at, b_id = before
        return q.where(
            or_(
                Message.created_at < b_at,
                and_(Message.created_at == b_at, Message.message_id < b_id),
            )
        )
    if before_id is not None:
        # Legacy single-key cursor (old client that omitted before_sent_at).
        return q.where(Message.message_id < before_id)
    return q


def _paid_row(r: Any, body_cap: int) -> dict[str, Any]:
    """One per-row query result → its JSON row (`body` cut at `body_cap`)."""
    body = r.body or ""
    return {
        "account_id": r.account_id,
        "fan_id": r.fan_id,
        "message_id": r.message_id,
        "fan": {
            "username": r.of_username,
            "display_name": r.of_display_name,
            "avatar_url": r.avatar_url,
        },
        "body": body[:body_cap],
        "body_truncated": len(body) > body_cap,
        "media_count": r.media_count,
        "price_cents": r.price_cents,
        "is_paid": bool(r.is_paid) if r.is_paid is not None else False,
        "direction": r.direction,
        "is_tip": bool(r.is_tip),
        "sent_at": r.created_at.isoformat() if r.created_at else None,
        "purchased_at": r.purchased_at.isoformat() if r.purchased_at else None,
        "sent_by_employee_id": r.sent_by_employee_id,
        "employee_name": r.employee_name,
        "automation_kind": r.automation_kind,
        "mass_run_id": r.mass_run_id,
        "is_unsent": bool(r.is_unsent),
        "unsent_at": r.unsent_at.isoformat() if r.unsent_at else None,
        "unsent_reason": r.unsent_reason,
        "reply_seconds": (
            int((r.created_at - r.reply_to_at).total_seconds())
            if r.created_at is not None and r.reply_to_at is not None else None
        ),
        "is_mass_summary": False,
    }


def _page(
    items: list[dict[str, Any]], mass_rows: list[dict[str, Any]], limit: int,
) -> dict[str, Any]:
    """The response page: per-row items merged with the mass summaries, re-cut
    to `limit`, plus the next cursor. Consumes `items` (extended in place).

    Merges the two (sent_at, message_id)-keyset streams (both fetched with the
    same `< (before_sent_at, before_id)` cursor, both DESC) and re-cuts to the
    page size. The smallest kept (sent_at, id) becomes the next cursor; the
    rows we drop here are all below it and reappear on the next page's fetch —
    no gaps, no dupes. sent_at is an ISO string (uniform naive-UTC isoformat),
    so a lexical compare is the same as a datetime compare."""
    if mass_rows:
        items.extend(mass_rows)
        items.sort(key=lambda r: (r["sent_at"] or "", r["message_id"]), reverse=True)
        items = items[:limit]

    if len(items) == limit:
        last = items[-1]
        next_before_id = last["message_id"]
        next_before_sent_at = last["sent_at"]
    else:
        next_before_id = None
        next_before_sent_at = None
    return {
        "rows": items,
        "next_before_id": next_before_id,
        "next_before_sent_at": next_before_sent_at,
    }


# CSV export columns; the cap, streaming and TRUNCATED sentinel live in
# csv_export.py (shared with the Sales records export).
_CSV_HEADER = [
    "message_id",
    "account_id",
    "account_nickname",
    "fan_id",
    "fan_username",
    "fan_display_name",
    "direction",
    "sent_at_iso",
    "body",
    "media_count",
    "price_cents",
    "is_paid",
    "is_tip",
    "purchased_at_iso",
    "sent_by_employee_id",
    "employee_name",
    "automation_kind",
]


def _csv_row(row: Any, account_nicknames: dict[str, str]) -> list[Any]:
    """One paid-messages CSV line, in `_CSV_HEADER` order."""
    return [
        row.message_id,
        row.account_id,
        account_nicknames.get(row.account_id, ""),
        row.fan_id,
        row.of_username or "",
        row.of_display_name or "",
        row.direction,
        row.created_at.isoformat() if row.created_at else "",
        (row.body or "")[:2000],
        row.media_count,
        row.price_cents,
        "" if row.is_paid is None else ("true" if row.is_paid else "false"),
        "true" if row.is_tip else "false",
        row.purchased_at.isoformat() if row.purchased_at else "",
        row.sent_by_employee_id or "",
        row.employee_name or "",
        row.automation_kind or "",
    ]


async def _collapsed_mass_rows(
    *,
    s: AsyncSession,
    start: datetime | None,
    end: datetime | None,
    account_ids: list[str] | None,
    employee_id: int | None,
    type_: str,
    before: tuple[datetime, int] | None,
    limit: int,
    text_query: str | None = None,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    unsent_only: bool = False,
    sender_type: str = "any",
) -> list[dict[str, Any]]:
    """One summary dict per mass broadcast (mass_run) that produced outbound
    rows in the window — the collapse that replaces N per-fan rows with a
    single "sent to N fans" row in the All-Messages tab.

    Synthetic `message_id = mass_placeholder_message_id(run_id)` (5e15 + run_id)
    is the row's stable, collision-free React key / sort tiebreaker — NOT the
    sort key. Rows interleave with normal messages by send TIME (`created_at`),
    so a 6d-old broadcast sits in its true chronological slot, not pinned to the
    top. The caller paginates on a `(sent_at, message_id)` keyset; `before` is
    that composite cursor (rows must sort strictly below it).

    `recipient_count` (and `viewed_count`) come from `mass_broadcast_cache`
    (OF's `/users/me/stats/messages/group` — "126 sent · 21 viewed"), joined by
    `MassRun.queue_id`. That cache may lag a brand-new broadcast, so the count
    falls back: `cache.sent_count` → `MassRun.recipient_count` →
    COUNT(DISTINCT fan_id) placeholder. The placeholder is usually 1 for an
    explicit-userIds send (one optimistic row persisted), so the cache is the
    real fan-out.

    Direction is always "out" (a broadcast). `status` is intentionally NOT
    applied — paid/unpaid is per-recipient on a broadcast, not a property of
    the summary. `type=free|paid` filters on the broadcast's own price.

    The filters (window, sender, type and the dashboard's) only PICK the runs;
    every figure is then over all of a run's copies, so a text or unsent filter
    narrows the list without shrinking a broadcast's recipient count or sales.

    `purchased_count` / `earnings_cents` are the run's sales from LOCAL rows
    (`local_mass_sales` — the same count the sent list shows).
    """
    from attribution import mass_placeholder_message_id
    # local: messages imports this module at its top.
    from messages import local_mass_sales

    picked = (
        select(Message.mass_run_id)
        .where(Message.mass_run_id.is_not(None))
        .where(Message.direction == "out")
    )
    if start is not None:
        picked = picked.where(Message.created_at >= start)
    if end is not None:
        picked = picked.where(Message.created_at <= end)
    if account_ids is not None:
        picked = picked.where(Message.account_id.in_(account_ids))
    if employee_id is not None:
        picked = picked.where(Message.sent_by_employee_id == employee_id)
    if type_ == "paid":
        picked = picked.where(Message.price_cents > 0)
    elif type_ == "free":
        picked = picked.where(Message.price_cents == 0)
    picked = _apply_dashboard_filters(
        picked, text_query=text_query, min_price_cents=min_price_cents,
        max_price_cents=max_price_cents, unsent_only=unsent_only,
        sender_type=sender_type,
    )

    q = (
        select(
            Message.account_id.label("account_id"),
            Message.mass_run_id.label("mass_run_id"),
            func.count(func.distinct(Message.fan_id)).label("recipient_count"),
            func.max(Message.body).label("body"),
            func.max(Message.price_cents).label("price_cents"),
            func.max(Message.media_count).label("media_count"),
            # The broadcast's own copies only: a funnel follow-up rides the
            # run's id and must not move the row's send time.
            func.coalesce(
                func.max(case((Message.funnel_step.is_(None), Message.created_at))),
                func.max(Message.created_at),
            ).label("created_at"),
            func.min(Message.created_at).label("first_at"),
            func.max(Message.sent_by_employee_id).label("sent_by_employee_id"),
            func.max(Message.automation_kind).label("automation_kind"),
            func.max(Message.sender_name).label("sender_name"),
            func.max(Employee.display_name).label("employee_name"),
            func.max(MassMessageFunnel.name).label("funnel_name"),
            func.max(MassRun.recipient_count).label("run_recipient_count"),
            func.max(MassRun.queue_id).label("queue_id"),
            # Source of truth for "N sent · M viewed" — keyed on the run's OF
            # queue_id (one cache row per run, so max() just unwraps it).
            func.max(MassBroadcastCache.sent_count).label("cache_sent"),
            func.max(MassBroadcastCache.viewed_count).label("cache_viewed"),
            func.max(MassRun.unsent_at).label("run_unsent_at"),
            func.max(MassBroadcastCache.is_canceled).label("cache_canceled"),
        )
        .select_from(Message)
        .outerjoin(Employee, Employee.id == Message.sent_by_employee_id)
        .outerjoin(MassRun, MassRun.id == Message.mass_run_id)
        .outerjoin(MassMessageFunnel, MassMessageFunnel.id == MassRun.funnel_id)
        .outerjoin(
            MassBroadcastCache,
            and_(
                MassBroadcastCache.account_id == MassRun.account_id,
                MassBroadcastCache.queue_id == MassRun.queue_id,
            ),
        )
        .where(Message.mass_run_id.in_(picked))
        .where(Message.direction == "out")
        .group_by(Message.account_id, Message.mass_run_id)
    )

    grouped = (await s.execute(q)).all()

    out: list[dict[str, Any]] = []
    run_info: dict[int, Any] = {}
    for g in grouped:
        run_info[int(g.mass_run_id)] = g
        synth_id = mass_placeholder_message_id(int(g.mass_run_id))
        created_at = g.created_at
        # Keyset on (created_at, synth_id): only runs strictly below the
        # cursor belong on this page. Mirrors `_keyset_where`.
        if before is not None and created_at is not None:
            b_at, b_id = before
            if not (created_at < b_at or (created_at == b_at and synth_id < b_id)):
                continue
        body = g.body or ""
        out.append({
            "account_id": g.account_id,
            "fan_id": 0,  # no single fan — distinct (account, synth_id) keeps the React key unique
            "message_id": synth_id,
            "fan": {"username": None, "display_name": None, "avatar_url": None},
            "body": body[:2000],
            "body_truncated": len(body) > 2000,
            "media_count": int(g.media_count or 0),
            "price_cents": int(g.price_cents or 0),
            "is_paid": False,
            "direction": "out",
            "is_tip": False,
            "sent_at": created_at.isoformat() if created_at else None,
            "purchased_at": None,
            # Unsent from everyone: our own cancel stamps the run, OF's history
            # (a cancel made on OF) the cache.
            "is_unsent": g.run_unsent_at is not None or bool(g.cache_canceled),
            "sent_by_employee_id": g.sent_by_employee_id,
            "employee_name": g.employee_name,
            # Denormalized "mass-<who>" tag stamped on the rows at send time
            # (attribution.mass_sender_tag); the summary row prefers it over the
            # Employee join so it survives an employee delete.
            "sender_name": g.sender_name,
            "automation_kind": g.automation_kind,
            # Mass-summary extras — the row renderer switches on is_mass_summary.
            "is_mass_summary": True,
            "mass_run_id": int(g.mass_run_id),
            # Cache is the truth; fall back when the stats poll hasn't run yet.
            "recipient_count": int(
                g.cache_sent or g.run_recipient_count or g.recipient_count or 0
            ),
            "viewed_count": int(g.cache_viewed or 0),
            "purchased_count": 0,
            "earnings_cents": 0,
            "reply_seconds": None,
            "funnel_name": g.funnel_name,
        })
    # Newest broadcast first by send TIME (synth_id tiebreaker); cap to the
    # page size (caller merges with the non-mass page and re-cuts, so an
    # over-fetch here is harmless).
    out.sort(key=lambda r: (r["sent_at"] or "", r["message_id"]), reverse=True)
    out = out[:limit]

    # Sales for the page's runs only, one read per account on the page.
    by_account: dict[str, list[int]] = {}
    for row in out:
        by_account.setdefault(row["account_id"], []).append(row["mass_run_id"])
    for aid, run_ids in by_account.items():
        firsts = [run_info[r].first_at for r in run_ids if run_info[r].first_at is not None]
        sales = await local_mass_sales(
            s, aid,
            runs={r: r for r in run_ids},
            queues={int(run_info[r].queue_id): r for r in run_ids
                    if run_info[r].queue_id is not None},
            since=min(firsts) - timedelta(days=1) if firsts else None,
        )
        for row in out:
            if row["account_id"] == aid:
                row["purchased_count"], row["earnings_cents"] = sales.get(
                    row["mass_run_id"], (0, 0))
    return out
