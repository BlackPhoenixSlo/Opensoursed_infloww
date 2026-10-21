"""
transactions.py — read-only admin endpoints for the /messages > Tips tab.

Two endpoints, both backed by raw `transactions` reads (no view dependency
— per Phase E.3 v2 synthesis §2.9 the per_employee_revenue_with_attribution
CTE is ~10× more expensive than the direct table scan and we only need
chat-linked attribution here):

  GET /admin/tips-list   → keyset-paginated list of tip transactions with
                           per-row attribution + tip_note from
                           `messages.body` when the tip is chat-linked.

  GET /admin/top-tippers → leaderboard of fans by SUM(amount_cents) over
                           the window. Optional employee_id scopes to
                           tips on that op's outbound messages (inner
                           join messages).

Both take `format=csv` (roadmap 1.16): the whole filtered set streamed as
CSV through csv_export.py, the /admin/paid-messages precedent — every tip
for the list (paging ignored), every tipper for the leaderboard (`limit`
ignored), each capped at `csv_export.CSV_MAX_ROWS`.

Both count `TRACKED_STATUSES` (cleared AND pending), like every earnings
read: a tip is written pending and clears ~7 days later, so a cleared-only
filter hid every tip of the last week (owner rule: pending always counts).
Chargebacks and refunds stay out.

Read-only — no writes, no FK side-effects. The share-token gate (server.py)
fronts both routes; we don't repeat the auth check here.
"""

from __future__ import annotations

import itertools
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, select

import csv_export
from attribution_backfill import TRACKED_STATUSES
from db.engine import get_session
from db.models import Employee, Fan, Message, Transaction
from stats import _parse_date
from auth import assert_employee_filter_owned, clamp_account_filter


log = logging.getLogger("of-relay.transactions")
router = APIRouter()

# CSV export columns: the JSON rows' fields, flattened (`fan.*` → `fan_*`).
_TIPS_CSV_HEADER = (
    "transaction_id", "occurred_at", "account_id", "fan_id", "fan_username", "fan_display_name",
    "amount_cents", "message_id", "tip_note", "attributed_employee_id", "attributed_employee_name",
    "attribution_source",
)
_TOP_TIPPERS_CSV_HEADER = (
    "rank", "account_id", "fan_id", "fan_username", "fan_display_name", "total_cents", "tip_count",
    "last_tip_at",
)


def _csv_filename(name: str, from_: str, to: str) -> str:
    """The download's name, after the window as typed."""
    return f"{name}_{csv_export.safe_filename_part(from_)}_to_{csv_export.safe_filename_part(to)}.csv"


def _attribution_source(r: Any) -> str | None:
    """"tip_message" only when both the message link AND the message's
    sent_by_employee_id are present. A linked message with NULL
    attribution is still treated as unattributed for this surface."""
    return "tip_message" if r.message_id is not None and r.attributed_employee_id is not None else None


# ── /admin/tips-list ────────────────────────────────────────────────

@router.get("/admin/tips-list", response_model=None)
async def tips_list(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
    employee_id: int | None = Query(None),
    fan_query: str | None = Query(None, description="username/display substring (≥2 chars)"),
    limit: int = Query(50, ge=1, le=100),
    before_id: int | None = Query(
        None, description="Keyset cursor: return transactions with id < this"
    ),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> dict[str, Any] | StreamingResponse:
    """Paginated tips list, newest-first by transaction_id (DESC).

    Attribution is derived per-row from the linked message: if the tip
    has a `message_id` AND that message has a `sent_by_employee_id`, we
    surface the employee + tag the row "tip_message". Standalone tips
    (no `message_id`, or the linked message exists but has no
    `sent_by_employee_id`) return `attribution_source = null` — there is
    no 7-day lookback here; it ships in Phase F if needed.
    """
    if from_ is None or to is None:
        raise HTTPException(status_code=400, detail="`from` and `to` are required")
    start = _parse_date(from_, field="from")
    end = _parse_date(to, field="to")
    account_ids = clamp_account_filter(account_id)
    # Cross-employee leak guard: an arbitrary employee_id used to slip
    # past the account gate and pull tips attributed to someone the
    # caller has no business reading. See audit notes.
    await assert_employee_filter_owned(employee_id)

    fan_q_pattern: str | None = None
    if fan_query is not None:
        fq = fan_query.strip()
        if len(fq) < 2:
            raise HTTPException(
                status_code=400,
                detail="fan_query must be at least 2 characters",
            )
        # LIKE pattern — case-insensitive on SQLite (default NOCASE
        # collation for LIKE on ASCII), good enough for username search.
        fan_q_pattern = f"%{fq}%"

    q = (
        select(
            Transaction.id.label("transaction_id"),
            Transaction.account_id.label("account_id"),
            Transaction.fan_id.label("fan_id"),
            Transaction.amount_cents.label("amount_cents"),
            Transaction.occurred_at.label("occurred_at"),
            Transaction.message_id.label("message_id"),
            func.substr(Message.body, 1, 200).label("tip_note"),
            Message.sent_by_employee_id.label("attributed_employee_id"),
            Employee.display_name.label("attributed_employee_name"),
            Fan.of_username.label("fan_username"),
            Fan.of_display_name.label("fan_display_name"),
            Fan.avatar_url.label("fan_avatar_url"),
        )
        .select_from(Transaction)
        .outerjoin(
            Message,
            and_(
                Message.account_id == Transaction.account_id,
                Message.message_id == Transaction.message_id,
            ),
        )
        .outerjoin(Employee, Employee.id == Message.sent_by_employee_id)
        .outerjoin(
            Fan,
            and_(
                Fan.account_id == Transaction.account_id,
                Fan.fan_id == Transaction.fan_id,
            ),
        )
        .where(Transaction.kind.in_(("tip", "tip_post", "tip_stream")))
        .where(Transaction.status.in_(TRACKED_STATUSES))
    )
    if start:
        q = q.where(Transaction.occurred_at >= start)
    if end:
        q = q.where(Transaction.occurred_at <= end)
    if account_ids is not None:
        q = q.where(Transaction.account_id.in_(account_ids))
    if employee_id is not None:
        q = q.where(Message.sent_by_employee_id == employee_id)
    if fan_q_pattern is not None:
        q = q.where(
            (Fan.of_username.like(fan_q_pattern))
            | (Fan.of_display_name.like(fan_q_pattern))
        )
    q = q.order_by(Transaction.id.desc())

    if format == "csv":
        return csv_export.download(
            _csv_filename("tips", from_, to), lambda s: csv_export.query_rows(s, q), _TIPS_CSV_HEADER,
            lambda r: [
                r.transaction_id, r.occurred_at.isoformat() if r.occurred_at else "",
                r.account_id, r.fan_id, r.fan_username or "", r.fan_display_name or "",
                r.amount_cents or 0, r.message_id or "", r.tip_note or "",
                r.attributed_employee_id or "", r.attributed_employee_name or "",
                _attribution_source(r) or "",
            ],
        )

    if before_id is not None:
        q = q.where(Transaction.id < before_id)
    async with get_session() as s:
        rows = (await s.execute(q.limit(limit))).all()

    items: list[dict[str, Any]] = []
    for r in rows:
        emp_id = r.attributed_employee_id
        attribution_source = _attribution_source(r)
        items.append(
            {
                "transaction_id": int(r.transaction_id),
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "fan": {
                    "username": r.fan_username,
                    "display_name": r.fan_display_name,
                    "avatar_url": r.fan_avatar_url,
                },
                "amount_cents": int(r.amount_cents or 0),
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "message_id": int(r.message_id) if r.message_id is not None else None,
                "tip_note": r.tip_note,
                "attributed_employee_id": int(emp_id) if emp_id is not None else None,
                "attributed_employee_name": r.attributed_employee_name,
                "attribution_source": attribution_source,
            }
        )

    next_before_id = items[-1]["transaction_id"] if len(items) == limit else None

    return {
        "rows": items,
        "limit": limit,
        "next_before_id": next_before_id,
    }


# ── /admin/top-tippers ──────────────────────────────────────────────

@router.get("/admin/top-tippers", response_model=None)
async def top_tippers(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
    employee_id: str | None = Query(
        None,
        description=(
            "Optional employee id to scope to that op's chat-linked tips. "
            "Explicit `null`/`unattributed` rejected — see endpoint docs."
        ),
    ),
    limit: int = Query(20, ge=1, le=100),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> dict[str, Any] | StreamingResponse:
    """Top tippers leaderboard, ranked by SUM(amount_cents) DESC.

    When `employee_id` is OMITTED: aggregate every tip in window. When
    given a numeric employee id: inner-join messages so only tips tied
    to that op's outbound messages count. We reject explicit
    `null`/`unattributed` because standalone tips have no employee by
    definition — the only honest answer is "filter on a specific op or
    pass nothing."
    """
    if from_ is None or to is None:
        raise HTTPException(status_code=400, detail="`from` and `to` are required")
    start = _parse_date(from_, field="from")
    end = _parse_date(to, field="to")
    account_ids = clamp_account_filter(account_id)

    emp_filter: int | None = None
    if employee_id is not None:
        raw = employee_id.strip().lower()
        if raw in ("null", "unattributed", ""):
            raise HTTPException(
                status_code=400,
                detail=(
                    "filter on a specific employee or omit the param; "
                    "standalone tips don't have an employee"
                ),
            )
        if not raw.isdigit():
            raise HTTPException(
                status_code=400,
                detail="employee_id must be a positive integer",
            )
        emp_filter = int(raw)
        if emp_filter <= 0:
            raise HTTPException(
                status_code=400,
                detail="employee_id must be positive",
            )
        # Same cross-employee leak guard as /admin/tips-list above.
        await assert_employee_filter_owned(emp_filter)

    q = (
        select(
            Transaction.fan_id.label("fan_id"),
            Transaction.account_id.label("account_id"),
            func.sum(Transaction.amount_cents).label("total_cents"),
            func.count().label("tip_count"),
            func.max(Transaction.occurred_at).label("last_tip_at"),
        )
        .where(Transaction.kind.in_(("tip", "tip_post", "tip_stream")))
        .where(Transaction.status.in_(TRACKED_STATUSES))
        .where(Transaction.fan_id.is_not(None))
    )
    if start:
        q = q.where(Transaction.occurred_at >= start)
    if end:
        q = q.where(Transaction.occurred_at <= end)
    if account_ids is not None:
        q = q.where(Transaction.account_id.in_(account_ids))

    if emp_filter is not None:
        # Inner-join messages on (account_id, message_id). Standalone
        # tips (message_id=NULL) drop out automatically — they can't
        # have an employee.
        q = q.join(
            Message,
            and_(
                Message.account_id == Transaction.account_id,
                Message.message_id == Transaction.message_id,
            ),
        ).where(Message.sent_by_employee_id == emp_filter)

    # The fan's names ride the aggregate as an outer join: at most one Fan per
    # (account_id, fan_id), so the sums are untouched. JSON and CSV read the
    # same query; only JSON is cut to `limit`.
    q = (
        q.outerjoin(Fan, and_(Fan.account_id == Transaction.account_id, Fan.fan_id == Transaction.fan_id))
        .add_columns(
            func.max(Fan.of_username).label("fan_username"),
            func.max(Fan.of_display_name).label("fan_display_name"),
            func.max(Fan.avatar_url).label("fan_avatar_url"),
        )
        .group_by(Transaction.fan_id, Transaction.account_id)
        .order_by(func.sum(Transaction.amount_cents).desc())
    )

    if format == "csv":
        # stream_csv hands to_row one row at a time, in rank order, so the
        # rank is a running count.
        rank = itertools.count(1)
        return csv_export.download(
            _csv_filename("top-tippers", from_, to), lambda s: csv_export.query_rows(s, q),
            _TOP_TIPPERS_CSV_HEADER, lambda r: [
                next(rank), r.account_id, r.fan_id, r.fan_username or "", r.fan_display_name or "",
                r.total_cents or 0, r.tip_count, r.last_tip_at.isoformat() if r.last_tip_at else "",
            ],
        )

    async with get_session() as s:
        agg_rows = (await s.execute(q.limit(limit))).all()

    out_rows: list[dict[str, Any]] = []
    for rank, r in enumerate(agg_rows, start=1):
        out_rows.append(
            {
                "rank": rank,
                "fan_id": int(r.fan_id),
                "account_id": r.account_id,
                "fan": {
                    "username": r.fan_username,
                    "display_name": r.fan_display_name,
                    "avatar_url": r.fan_avatar_url,
                },
                "total_cents": int(r.total_cents or 0),
                "tip_count": int(r.tip_count or 0),
                "last_tip_at": r.last_tip_at.isoformat() if r.last_tip_at else None,
            }
        )

    return {"rows": out_rows}

