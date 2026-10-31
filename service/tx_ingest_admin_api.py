"""service/tx_ingest_admin_api.py — the transactions-ingest admin surface
(per-account `transaction_scan_history` watermark + Unattributed-sales views)
and the on-demand subscriber-roster crawl.

  GET  /admin/ingest/transactions/health  → per-account scan tier, scoped to the caller's accounts
  POST /admin/ingest/transactions/{account_id}/run  (202) → one refresh/backfill scan now
  POST /admin/roster/{account_id}/crawl  → one subscriber-roster crawl now, past its TTL
  POST /admin/ingest/transactions/{account_id}/pause  (202) → pause the supervisor for N hours
  POST /admin/ingest/transactions/{account_id}/resume  (202) → clear `paused_until`
  GET  /admin/ingest/transactions/orphan-tips  → Unattributed tip transactions
  GET  /admin/ingest/transactions/sales-needing-attribution  → Unattributed confirmed sales

Included mid-file in server.py for route order (pinned by
service/tests/test_route_order.py).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field

from auth import assert_account_owned
from auth import get_request_user as _get_request_user
from chatters import get_request_chatter as _get_request_chatter

log = logging.getLogger("of-relay.tx_ingest_admin_api")

router = APIRouter()


# ── /admin/ingest/transactions/* — Phase F supervisor admin surface ─
# Read/write surface over `transaction_scan_history` (the per-account
# watermark for the OF payouts/transactions ingest job) plus a few
# observability queries on `transactions`. Sits next to the other
# /admin/* routes; share-token gate fires via middleware so no
# per-route auth dep is needed.

def _tx_ingest_tier(minutes_since_scan: float | None, current_status: str) -> str:
    """Health tier per synthesis §7.
    green:  scanned within 30m AND status in {idle, ok, refreshing, backfilling}
    yellow: 30 < minutes_since_scan <= 360
    red:    minutes_since_scan > 360 OR status in {paused, error, never_scanned}

    Note: 'refreshing'/'backfilling' here are the in-flight steady states
    (tick START stamps them, _mark_success then stamps 'ok'). A row
    sitting in those states still counts as green if the timestamp is
    fresh — it means a scan is actively running.
    """
    if current_status in ("paused", "error", "never_scanned"):
        return "red"
    if minutes_since_scan is None:
        return "red"
    if minutes_since_scan <= 30 and current_status in (
        "idle", "ok", "refreshing", "backfilling",
    ):
        return "green"
    if minutes_since_scan <= 360:
        return "yellow"
    return "red"


_TIER_RANK = {"green": 0, "yellow": 1, "red": 2}


@router.get("/admin/ingest/transactions/health")
async def admin_ingest_tx_health() -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    now = datetime.utcnow()
    # Scope to the signed-in principal's account_ids union (same rule as
    # /admin/accounts and the picker). Unauthed callers (internal curl /
    # cron) still see every row. Without this filter the Ingest health
    # banner would list models the chatter has no permission to act on.
    user = _get_request_user()
    chatter = _get_request_chatter() if user is None else None
    if user is not None:
        allowed_ids: frozenset[str] | None = user.account_ids
    elif chatter is not None:
        allowed_ids = chatter.account_ids
    else:
        allowed_ids = None
    async with get_session() as s:
        acct_rows = (await s.execute(select(Account.id, Account.nickname))).all()
        hist_rows = (await s.execute(select(TransactionScanHistory))).scalars().all()

    if allowed_ids is not None:
        acct_rows = [r for r in acct_rows if r[0] in allowed_ids]

    hist_by_acct = {h.account_id: h for h in hist_rows}
    accounts_out: list[dict[str, Any]] = []
    worst = "green"
    for aid, nick in acct_rows:
        h = hist_by_acct.get(aid)
        if h is None:
            entry = {
                "account_id": aid,
                "display_name": nick,
                "last_scan_at": None,
                "current_status": "never_scanned",
                "last_error": None,
                "consecutive_failures": 0,
                "paused_until": None,
                "rows_inserted_total": 0,
                "rows_patched_total": 0,
                "fully_backfilled": False,
                "minutes_since_scan": None,
                "tier": "red",
            }
        else:
            mins = (
                (now - h.last_scan_at).total_seconds() / 60.0
                if h.last_scan_at is not None else None
            )
            tier = _tx_ingest_tier(mins, h.current_status or "idle")
            entry = {
                "account_id": aid,
                "display_name": nick,
                "last_scan_at": h.last_scan_at.isoformat() if h.last_scan_at else None,
                "current_status": h.current_status,
                "last_error": h.last_error,
                "consecutive_failures": int(h.consecutive_failures or 0),
                "paused_until": h.paused_until.isoformat() if h.paused_until else None,
                "rows_inserted_total": int(h.rows_inserted_total or 0),
                "rows_patched_total": int(h.rows_patched_total or 0),
                "fully_backfilled": bool(h.fully_backfilled),
                "minutes_since_scan": round(mins, 2) if mins is not None else None,
                "tier": tier,
            }
        accounts_out.append(entry)
        if _TIER_RANK[entry["tier"]] > _TIER_RANK[worst]:
            worst = entry["tier"]

    return {
        "overall_status": worst,
        "as_of": now.isoformat(),
        "accounts": accounts_out,
    }


class _TxRunBody(BaseModel):
    mode: str = Field("refresh", pattern="^(refresh|backfill)$")


@router.post("/admin/ingest/transactions/{account_id}/run", status_code=202)
async def admin_ingest_tx_run(
    account_id: str,
    body: _TxRunBody | None = Body(None),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    mode = (body.mode if body else "refresh") or "refresh"
    async with get_session() as s:
        acct = (await s.execute(
            select(Account.id).where(Account.id == account_id)
        )).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="account not found")
        h = (await s.execute(
            select(TransactionScanHistory)
            .where(TransactionScanHistory.account_id == account_id)
        )).scalar_one_or_none()
        if h is not None and h.current_status in ("backfilling", "refreshing"):
            # Stale-age escape valve. last_scan_at is stamped at tick
            # START (transaction_ingest.run_one_tick), so its age ==
            # how long the row has been parked at this status. A real
            # in-flight tick holds an asyncio.Lock + finishes well under
            # _STALE_INFLIGHT_S; anything older is a tombstone from a
            # process restart or cancelled task that escaped both the
            # try/finally and the boot sweep — we must NOT keep locking
            # the user's manual Refresh out forever.
            from transaction_ingest import _STALE_INFLIGHT_S  # type: ignore[import-not-found]
            age_s = (
                (datetime.utcnow() - h.last_scan_at).total_seconds()
                if h.last_scan_at is not None
                else _STALE_INFLIGHT_S + 1
            )
            if age_s < _STALE_INFLIGHT_S:
                raise HTTPException(
                    status_code=409,
                    detail=f"already in-flight: {h.current_status}",
                )
            log.warning(
                "admin_ingest_tx_run_proceed_after_stale account=%s status=%s age_s=%.0f",
                account_id, h.current_status, age_s,
            )

    # Lock peek removed: run_one_tick now stamps current_status to
    # "refreshing"/"backfilling" at the START of the tick (inside the
    # session that took the lock), so the upstream current_status check
    # at line 4714 catches in-flight scans without needing to import
    # supervisor internals here. See library/db_data/17_round2_synthesis.md.
    queued_at = datetime.utcnow()

    async def _trigger() -> None:
        try:
            from transaction_ingest import run_one_tick  # type: ignore[import-not-found]
        except ImportError:
            log.info("admin_ingest_tx_run: transaction_ingest not yet available; no-op")
            return
        try:
            await run_one_tick(account_id, mode=mode)
        except Exception:
            log.warning("run_one_tick failed for %s", account_id, exc_info=True)

    asyncio.create_task(_trigger(), name=f"tx-ingest-trigger-{account_id}")

    return {"accepted": True, "mode": mode, "queued_at": queued_at.isoformat()}


@router.post("/admin/roster/{account_id}/crawl")
async def admin_roster_crawl(account_id: str) -> dict[str, Any]:
    """One subscriber-roster crawl NOW, past its 25-minute TTL
    (`lifecycle_messages._CRAWL_TTL_S`): the on-demand trigger for
    `subscriber_snapshot`, as /admin/ingest/transactions/{id}/run is for the
    ledger. Same code path as the lifecycle sweep and smart_list_sync, under
    the same per-account lock; answers that run's stats ({roster: crawled |
    truncated | empty, listed, returned}). A seam in ADR 0024."""
    from db.engine import get_session
    from db.models import Account
    from sqlalchemy import select
    assert_account_owned(account_id)
    async with get_session() as s:
        if (await s.execute(select(Account.id).where(Account.id == account_id))).first() is None:
            raise HTTPException(status_code=404, detail="account not found")
    import automation_executor as ax
    from automations.lifecycle_messages import refresh_roster
    client = await asyncio.to_thread(ax._make_client, account_id)
    return await refresh_roster(account_id, client, now=datetime.utcnow(), force=True)


class _TxPauseBody(BaseModel):
    duration_hours: int = Field(1, ge=1, le=24 * 30)


@router.post("/admin/ingest/transactions/{account_id}/pause", status_code=202)
async def admin_ingest_tx_pause(
    account_id: str,
    body: _TxPauseBody = Body(...),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    paused_until = datetime.utcnow() + timedelta(hours=body.duration_hours)
    async with get_session() as s:
        acct = (await s.execute(
            select(Account.id).where(Account.id == account_id)
        )).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="account not found")
        h = (await s.execute(
            select(TransactionScanHistory)
            .where(TransactionScanHistory.account_id == account_id)
        )).scalar_one_or_none()
        if h is None:
            h = TransactionScanHistory(account_id=account_id)
            s.add(h)
        h.paused_until = paused_until
        await s.commit()
    return {"accepted": True, "paused_until": paused_until.isoformat()}


@router.post("/admin/ingest/transactions/{account_id}/resume", status_code=202)
async def admin_ingest_tx_resume(account_id: str) -> dict[str, Any]:
    """Clear `paused_until` so the supervisor picks this account back up
    on the next tick. Idempotent — calling on an already-unpaused row
    is a no-op."""
    from db.engine import get_session
    from db.models import Account, TransactionScanHistory
    from sqlalchemy import select
    async with get_session() as s:
        acct = (await s.execute(
            select(Account.id).where(Account.id == account_id)
        )).first()
        if acct is None:
            raise HTTPException(status_code=404, detail="account not found")
        h = (await s.execute(
            select(TransactionScanHistory)
            .where(TransactionScanHistory.account_id == account_id)
        )).scalar_one_or_none()
        if h is not None:
            h.paused_until = None
            if h.current_status == "paused":
                h.current_status = "ok"
            await s.commit()
    return {"accepted": True}


@router.get("/admin/ingest/transactions/orphan-tips")
async def admin_ingest_tx_orphan_tips(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_assigned: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Tip transactions that fall into the 'Unattributed' bucket in the
    per-employee view: kind in tip family, status cleared or pending (the
    view's own statuses, so this list matches the Unattributed total), and no
    chatter-attributed outbound message within the 7-day lookback. With
    `include_assigned=true` ALSO returns tips that already have a
    manual `attributed_employee_id` set (so the UI can offer reassign
    / clear). Each row's `attributed_employee_id` is null for true
    orphans, populated for previously-assigned tips.

    Optional `from` / `to` (ISO date) scope to the dashboard's window."""
    from db.engine import get_session
    from sqlalchemy import text as sql_text
    # LEFT JOIN employees so we return the chatter's display_name with the
    # row — the UI used to look this up against the current owner's roster
    # and fell back to "Employee {id}" when the employee was scoped out
    # (e.g. transferred). The DB has the canonical name; surface it here.
    sql = """
      SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
             t.description, t.kind, t.attributed_employee_id,
             e.display_name AS attributed_employee_name
        FROM transactions t
        LEFT JOIN employees e ON e.id = t.attributed_employee_id
       WHERE t.kind IN ('tip', 'tip_post', 'tip_stream')
         AND t.status IN ('cleared', 'pending')
         AND t.message_id IS NULL
         AND NOT EXISTS (
           SELECT 1 FROM messages m
            WHERE m.account_id = t.account_id
              AND m.fan_id = t.fan_id
              AND m.direction = 'out'
              AND m.sent_by_employee_id IS NOT NULL
              AND m.created_at <= t.occurred_at
              AND m.created_at > datetime(t.occurred_at, '-7 days')
         )
    """
    params: dict[str, Any] = {"lim": limit}
    if not include_assigned:
        sql += " AND t.attributed_employee_id IS NULL"
    if account_id:
        sql += " AND t.account_id = :aid"
        params["aid"] = account_id
    if from_:
        sql += " AND t.occurred_at >= :start"
        params["start"] = from_
    if to:
        # End-of-day for bare ISO dates so "to=YYYY-MM-DD" includes that day.
        sql += " AND t.occurred_at <= :end"
        params["end"] = f"{to} 23:59:59" if len(to) == 10 else to
    sql += " ORDER BY t.occurred_at DESC LIMIT :lim"

    async with get_session() as s:
        rows = (await s.execute(sql_text(sql), params)).all()
    return {
        "rows": [
            {
                "id": int(r.id),
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "kind": r.kind,
                "amount_cents": int(r.amount_cents or 0),
                "occurred_at": r.occurred_at if isinstance(r.occurred_at, str)
                                else (r.occurred_at.isoformat() if r.occurred_at else None),
                "description": r.description,
                "attributed_employee_id": (
                    int(r.attributed_employee_id)
                    if r.attributed_employee_id is not None else None
                ),
                # "No one" (sales_attribution.NO_ONE) names no Employee row.
                "attributed_employee_name": ("No one" if r.attributed_employee_id == 0
                                             else r.attributed_employee_name),
            }
            for r in rows
        ]
    }


@router.get("/admin/ingest/transactions/sales-needing-attribution")
async def admin_sales_needing_attribution(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    include_assigned: bool = Query(False),
    lookback_days: int = Query(7, ge=1, le=90),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """Confirmed sales (`cleared`+`pending`) currently in the per-employee view's
    'Unattributed' bucket — standalone-tip orphans, message-linked orphans (a
    PPV whose scraped message carries no sender, e.g. duplicate-price PPVs the
    auto-rule leaves ambiguous), AND unlinked PPV/custom orphans (`message_id`
    NULL — the relinker found no unambiguous message; per ops' manual-only rule
    these are never auto-credited, so THIS panel is their only path to a
    chatter). Each row ships the CANDIDATE chatters (distinct NON-MASS 1:1
    senders to that fan within `lookback_days` before the sale) so the operator
    can assign the right one via
    POST /admin/ingest/transactions/{id}/attribute. `include_assigned=true` also
    returns sales that already carry a manual override (to reassign / clear).

    Mirrors attribution_backfill's orphan predicates; the 7-day NOT-EXISTS on the
    standalone-tip branch matches the live view's own lookup so the two agree.
    The unlinked-PPV branch has NO toucher exclusion — the view gives PPVs no
    lookback, so every unlinked one is an orphan regardless of recent chat."""
    from db.engine import get_session
    from sqlalchemy import text as sql_text

    orphan_cte = """
      WITH orphans AS (
        SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
               t.description, t.kind, t.status, t.attributed_employee_id
          FROM transactions t
          JOIN messages m ON m.account_id = t.account_id AND m.fan_id = t.fan_id
                         AND m.message_id = t.message_id
         WHERE t.message_id IS NOT NULL
           AND t.kind IN ('ppv','ppv_message','ppv_post','ppv_stream',
                          'tip','tip_post','tip_stream','custom')
           AND t.status IN ('cleared','pending')
           AND m.sent_by_employee_id IS NULL
        UNION ALL
        SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
               t.description, t.kind, t.status, t.attributed_employee_id
          FROM transactions t
         WHERE t.kind IN ('tip','tip_post','tip_stream')
           AND t.message_id IS NULL
           AND t.status IN ('cleared','pending')
           AND t.fan_id IS NOT NULL
           AND NOT EXISTS (
             SELECT 1 FROM messages m
              WHERE m.account_id = t.account_id AND m.fan_id = t.fan_id
                AND m.direction = 'out' AND m.sent_by_employee_id IS NOT NULL
                AND m.created_at <= t.occurred_at
                AND m.created_at > datetime(t.occurred_at, '-7 days'))
        UNION ALL
        SELECT t.id, t.account_id, t.fan_id, t.amount_cents, t.occurred_at,
               t.description, t.kind, t.status, t.attributed_employee_id
          FROM transactions t
         WHERE t.kind IN ('ppv','ppv_message','ppv_post','ppv_stream','custom')
           AND t.message_id IS NULL
           AND t.status IN ('cleared','pending')
           AND t.fan_id IS NOT NULL
      )
      SELECT o.id, o.account_id, o.fan_id, o.amount_cents, o.occurred_at,
             o.description, o.kind, o.status, o.attributed_employee_id,
             e.display_name AS attributed_employee_name
        FROM orphans o
        LEFT JOIN employees e ON e.id = o.attributed_employee_id
       WHERE 1=1
    """
    params: dict[str, Any] = {"lim": limit}
    if not include_assigned:
        orphan_cte += " AND o.attributed_employee_id IS NULL"
    if account_id:
        orphan_cte += " AND o.account_id = :aid"
        params["aid"] = account_id
    if from_:
        orphan_cte += " AND o.occurred_at >= :start"
        params["start"] = from_
    if to:
        orphan_cte += " AND o.occurred_at <= :end"
        params["end"] = f"{to} 23:59:59" if len(to) == 10 else to
    orphan_cte += " ORDER BY o.occurred_at DESC LIMIT :lim"

    # Distinct non-mass 1:1 senders to (account, fan) in the window before the
    # sale — the assignment candidates. `mass_run_id IS NULL` keeps blasts out.
    # lookback_days is a validated int (Query ge=1 le=90), safe to inline.
    cand_sql = sql_text(
        f"""
        SELECT m.sent_by_employee_id AS eid, e.display_name AS name,
               MAX(m.created_at) AS last_at
          FROM messages m
          LEFT JOIN employees e ON e.id = m.sent_by_employee_id
         WHERE m.account_id = :aid AND m.fan_id = :fid AND m.direction = 'out'
           AND m.sent_by_employee_id IS NOT NULL
           AND m.mass_run_id IS NULL
           AND m.created_at <= :occ
           AND m.created_at > datetime(:occ, '-{int(lookback_days)} days')
         GROUP BY m.sent_by_employee_id, e.display_name
         ORDER BY last_at DESC
        """
    )

    def _iso(v: Any) -> str | None:
        if v is None:
            return None
        return v if isinstance(v, str) else (v.isoformat() if hasattr(v, "isoformat") else str(v))

    async with get_session() as s:
        rows = (await s.execute(sql_text(orphan_cte), params)).all()
        out: list[dict[str, Any]] = []
        for r in rows:
            occ = _iso(r.occurred_at)
            cands: list[dict[str, Any]] = []
            if r.fan_id is not None and occ is not None:
                crows = (await s.execute(cand_sql, {
                    "aid": r.account_id, "fid": r.fan_id, "occ": occ,
                })).all()
                cands = [
                    {"employee_id": int(c.eid), "name": c.name, "last_at": _iso(c.last_at)}
                    for c in crows if c.eid is not None
                ]
            out.append({
                "id": int(r.id),
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "kind": r.kind,
                "status": r.status,
                "amount_cents": int(r.amount_cents or 0),
                "occurred_at": occ,
                "description": r.description,
                "attributed_employee_id": (
                    int(r.attributed_employee_id)
                    if r.attributed_employee_id is not None else None
                ),
                # "No one" (sales_attribution.NO_ONE) names no Employee row.
                "attributed_employee_name": ("No one" if r.attributed_employee_id == 0
                                             else r.attributed_employee_name),
                "candidate_chatters": cands,
            })
    return {"rows": out}
