"""
stats_ops.py — Operations reads, split out of stats.py.

  GET /admin/stats/grok-cost        → grok_daily_cost rollup rows
  GET /admin/stats/grok-calls       → grok_calls grouped by purpose / model / day
  GET /admin/stats/per-automation   → sends, revenue and LLM spend per automation
  GET /admin/stats/automation-runs  → recent automation_runs (most recent first)
  GET /admin/stats/attribution-coverage(/recent)
                                    → % of outbound messages with an Employee,
                                       and the latest ones without

All read rows already written: the Grok runners' cost tables, the automation
scheduler's runs, the ingest path's messages and transactions.

The routes stood at three spots of stats.py, so there are three routers
(`router`, `runs_router`, `coverage_router`); stats.py includes each where its
routes stood (route order). The report zone is read as `stats._report_zone` at
call time (imported in the route, no import-time cycle), so a patch on `stats`
reaches these routes as before the split.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select

import tx_rollup
from attribution_backfill import REVENUE_KINDS, TRACKED_STATUSES
from auth import clamp_account_filter
from db.engine import get_session
from db.models import Account, AutomationRun, Employee, GrokCall, GrokDailyCost, Message
from stats_window import parse_date as _parse_date, stats_guard

router = APIRouter(dependencies=[Depends(stats_guard)])
runs_router = APIRouter(dependencies=[Depends(stats_guard)])
coverage_router = APIRouter(dependencies=[Depends(stats_guard)])


# ── Grok daily cost ──────────────────────────────────────────────

@router.get("/admin/stats/grok-cost")
async def grok_cost(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
) -> dict[str, Any]:
    """Daily Grok spend rollup. Reads grok_daily_cost directly (no aggregation
    over grok_calls). When `account_id` is omitted, returns ALL rows in the
    range — including the global rollup row (account_id=NULL) and every
    per-account row; the caller can filter client-side."""
    account_ids = clamp_account_filter(account_id)
    start = _parse_date(from_, field="from")
    end = _parse_date(to, field="to")

    async with get_session() as s:
        q = select(
            GrokDailyCost.day,
            GrokDailyCost.account_id,
            GrokDailyCost.cost_cents,
            GrokDailyCost.call_count,
            GrokDailyCost.is_capped,
            GrokDailyCost.updated_at,
        )
        if account_ids is not None:
            q = q.where(GrokDailyCost.account_id.in_(account_ids))
        # `day` is a TEXT 'YYYY-MM-DD' so lexical compare equals chronological.
        if start:
            q = q.where(GrokDailyCost.day >= start.strftime("%Y-%m-%d"))
        if end:
            q = q.where(GrokDailyCost.day <= end.strftime("%Y-%m-%d"))
        q = q.order_by(GrokDailyCost.day.desc(), GrokDailyCost.account_id)
        rows = (await s.execute(q)).all()

    return {
        "rows": [
            {
                "day": r.day,
                "account_id": r.account_id,
                "cost_cents": int(r.cost_cents or 0),
                "call_count": int(r.call_count or 0),
                "is_capped": bool(r.is_capped),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


# ── Grok per-call breakdown (the cost ruler) ────────────────────

@router.get("/admin/stats/grok-calls")
async def grok_calls(
    account_id: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    status: str = Query("done", pattern="^(done|error|pending|all)$"),
    by: str = Query("purpose_model", pattern="^(purpose_model|purpose|model|day)$"),
) -> dict[str, Any]:
    """Aggregate `grok_calls` so you can SEE which automation costs what — the
    detail the daily rollup (`/admin/stats/grok-cost`) can't give you.

    Unlike grok_cost (which reads the pre-summed grok_daily_cost), this groups
    the raw call rows by purpose × model (default) and sums tokens, cost, and
    DeepSeek cache-hit tokens — so you can compare a window's cost before/after
    a prompt change and watch the cache-hit ratio climb.

    `cost_millicents` is the internal unit (cents×100 — sub-cent DeepSeek calls
    don't floor to 0); `cost_cents` is the human dollars figure. `cache_hit_ratio`
    is cached-input ÷ total-input over the bucket (0 when the provider — e.g.
    Grok — doesn't report cache hits). `status` defaults to 'done' so partial /
    failed calls (which carry no real cost) don't skew the numbers; pass
    status=all to include them. The time filter is on `called_at`."""
    account_ids = clamp_account_filter(account_id)
    start = _parse_date(from_, field="from")
    end = _parse_date(to, field="to")

    day_expr = func.strftime("%Y-%m-%d", GrokCall.called_at).label("day")
    # Group key columns vary by `by`; everything else is summed the same way.
    keys: dict[str, Any] = {
        "purpose_model": [GrokCall.purpose.label("purpose"),
                          GrokCall.model.label("model"),
                          GrokCall.provider.label("provider")],
        "purpose": [GrokCall.purpose.label("purpose")],
        "model": [GrokCall.model.label("model"),
                  GrokCall.provider.label("provider")],
        "day": [day_expr, GrokCall.purpose.label("purpose")],
    }[by]

    metrics = [
        func.count(GrokCall.id).label("calls"),
        func.coalesce(func.sum(GrokCall.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(GrokCall.tokens_out), 0).label("tokens_out"),
        func.coalesce(func.sum(GrokCall.cache_hit_tokens), 0).label("cache_hit_tokens"),
        func.coalesce(func.sum(GrokCall.cost_cents), 0).label("cost_millicents"),
        func.coalesce(func.avg(GrokCall.latency_ms), 0).label("avg_latency_ms"),
    ]

    async with get_session() as s:
        q = select(*keys, *metrics)
        if account_ids is not None:
            q = q.where(GrokCall.account_id.in_(account_ids))
        if status != "all":
            q = q.where(GrokCall.status == status)
        if start:
            q = q.where(GrokCall.called_at >= start)
        if end:
            q = q.where(GrokCall.called_at <= end)
        q = q.group_by(*keys).order_by(func.sum(GrokCall.cost_cents).desc())
        rows = (await s.execute(q)).all()

    out = []
    for r in rows:
        m = r._mapping
        t_in = int(m["tokens_in"] or 0)
        cache = int(m["cache_hit_tokens"] or 0)
        millicents = int(m["cost_millicents"] or 0)
        out.append({
            "day": m.get("day"),
            "purpose": m.get("purpose"),
            "model": m.get("model"),
            "provider": m.get("provider"),
            "calls": int(m["calls"] or 0),
            "tokens_in": t_in,
            "tokens_out": int(m["tokens_out"] or 0),
            "cache_hit_tokens": cache,
            "cache_hit_ratio": round(cache / t_in, 3) if t_in else 0.0,
            "cost_millicents": millicents,
            "cost_cents": round(millicents / 100, 4),
            "avg_latency_ms": int(m["avg_latency_ms"] or 0),
        })
    total_mc = sum(r["cost_millicents"] for r in out)
    total_calls = sum(r["calls"] for r in out)
    # Audit rows whose prompt redaction failed and fell back to a stub. The
    # audit write is deliberately swallowed so it can never take down a live LLM
    # call — which means a degraded audit is otherwise INVISIBLE. Non-zero here
    # is the only signal that grok_calls has stopped recording what we sent.
    from llm_client import audit_degraded_count
    return {
        "rows": out,
        "totals": {
            "calls": total_calls,
            "cost_millicents": total_mc,
            "cost_cents": round(total_mc / 100, 4),
        },
        "audit_degraded": audit_degraded_count(),
    }


@router.get("/admin/stats/per-automation")
async def per_automation(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
) -> dict[str, Any]:
    """Per-automation rollup — the "which automations earn and which cost"
    panel. Answers all four at once, per automation:

      • messages_sent  — outbound rows stamped with this automation (per-chat
                         AND mass), from `messages.automation_kind`
      • revenue_cents  — earnings attributed to this automation's messages,
                         the attribution view's answer, materialised as
                         `transactions.credit_automation_kind` (rollups)
      • llm_calls / tokens_in / tokens_out / cost — LLM spend, from
                         `grok_calls.purpose`

    The three scans key on the SAME automation token (e.g. `welcome_chatter_for_info`,
    `welcome`, `send_mass_message`) — `messages.automation_kind` and
    `grok_calls.purpose` share a vocabulary by design (see the senders). So a
    mass broadcaster shows sends + revenue with $0 LLM spend, while `gen_info`
    (an LLM-only profiler that sends nothing) shows spend with 0 sends. NULL
    (human / relay sends) is excluded — that revenue lives in /per-employee.

    LLM spend counts status='done' calls only (pending/error carry no real
    cost). `cost_millicents` is the internal unit (cents×100); `cost_cents` is
    the human dollars figure. Time filter is `created_at` / `occurred_at` /
    `called_at` respectively."""
    import stats
    account_ids = clamp_account_filter(account_id)
    zone = await stats._report_zone(account_id)
    start = _parse_date(from_, field="from", zone=zone)
    end = _parse_date(to, field="to", zone=zone)

    agg: dict[str, dict[str, Any]] = {}

    def _bucket(kind: str) -> dict[str, Any]:
        if kind not in agg:
            agg[kind] = {
                "automation": kind,
                "messages_sent": 0,
                "revenue_cents": 0,
                "llm_calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_millicents": 0,
            }
        return agg[kind]

    async with get_session() as s:
        # ── messages_sent by automation_kind ───────────────────────────
        mq = (
            select(
                Message.automation_kind.label("kind"),
                func.count().label("n"),
            )
            .where(Message.automation_kind.is_not(None))
            .where(Message.direction == "out")
        )
        if account_ids is not None:
            mq = mq.where(Message.account_id.in_(account_ids))
        if start:
            mq = mq.where(Message.created_at >= start)
        if end:
            mq = mq.where(Message.created_at <= end)
        mq = mq.group_by(Message.automation_kind)
        for r in (await s.execute(mq)).all():
            _bucket(r.kind)["messages_sent"] = int(r.n or 0)

        # ── revenue by automation_kind (the view's rows, from the rollup) ─
        for r in await tx_rollup.window_sums(
                s, ("automation_kind",), account_ids=account_ids, start=start, end=end,
                where={"status": TRACKED_STATUSES, "kind": REVENUE_KINDS}):
            if r.automation_kind is not None:
                _bucket(r.automation_kind)["revenue_cents"] = int(r.gross_cents or 0)

        # ── LLM spend by purpose ───────────────────────────────────────
        gq = (
            select(
                GrokCall.purpose.label("kind"),
                func.count(GrokCall.id).label("calls"),
                func.coalesce(func.sum(GrokCall.tokens_in), 0).label("tin"),
                func.coalesce(func.sum(GrokCall.tokens_out), 0).label("tout"),
                func.coalesce(func.sum(GrokCall.cost_cents), 0).label("mc"),
            )
            .where(GrokCall.status == "done")
        )
        if account_ids is not None:
            gq = gq.where(GrokCall.account_id.in_(account_ids))
        if start:
            gq = gq.where(GrokCall.called_at >= start)
        if end:
            gq = gq.where(GrokCall.called_at <= end)
        gq = gq.group_by(GrokCall.purpose)
        for r in (await s.execute(gq)).all():
            b = _bucket(r.kind)
            b["llm_calls"] = int(r.calls or 0)
            b["tokens_in"] = int(r.tin or 0)
            b["tokens_out"] = int(r.tout or 0)
            b["cost_millicents"] = int(r.mc or 0)

    rows = [
        {**b, "cost_cents": round(b["cost_millicents"] / 100, 4)}
        for b in agg.values()
    ]
    # Highest earner first; ties broken by send volume.
    rows.sort(key=lambda r: (r["revenue_cents"], r["messages_sent"]), reverse=True)
    total_mc = sum(r["cost_millicents"] for r in rows)
    return {
        "rows": rows,
        "totals": {
            "messages_sent": sum(r["messages_sent"] for r in rows),
            "revenue_cents": sum(r["revenue_cents"] for r in rows),
            "llm_calls": sum(r["llm_calls"] for r in rows),
            "cost_millicents": total_mc,
            "cost_cents": round(total_mc / 100, 4),
        },
    }


# ── Automation runs ──────────────────────────────────────────────

@runs_router.get("/admin/stats/automation-runs")
async def automation_runs(
    kind: str | None = Query(None),
    account_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Most-recent automation runs first. `stats_json` is returned verbatim
    (TEXT, already JSON-serialized by the runner)."""
    account_ids = clamp_account_filter(account_id)
    async with get_session() as s:
        q = select(AutomationRun)
        if kind:
            # Deliberately raw: the param filters rows displayed VERBATIM, so a
            # caller matching a legacy token sees exactly the rows carrying it.
            q = q.where(AutomationRun.kind == kind)
        if account_ids is not None:
            q = q.where(AutomationRun.account_id.in_(account_ids))
        q = q.order_by(AutomationRun.started_at.desc()).limit(limit)
        rows = (await s.execute(q)).scalars().all()

    return {
        "runs": [
            {
                "id": r.id,
                "account_id": r.account_id,
                "kind": r.kind,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "status": r.status,
                "stats_json": r.stats_json,
                "error_text": r.error_text,
            }
            for r in rows
        ]
    }


# ── Attribution coverage ─────────────────────────────────────────

def _coverage_pct(attributed: int, total: int) -> float:
    """Percentage with 1-decimal rounding. 0/0 returns 0.0 — the caller
    decides whether 'no traffic' should be surfaced differently."""
    if total <= 0:
        return 0.0
    return round((attributed / total) * 100.0, 1)


@coverage_router.get("/admin/stats/attribution-coverage")
async def attribution_coverage(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
) -> dict[str, Any]:
    """% of outbound messages with `sent_by_employee_id` filled, per account.
    Window defaults to the last 7 days (UTC). Buckets, per §1.3 of the
    attribution plan:

      attributed_to_human       — employees.is_active = 1
      attributed_to_automation  — employees.display_name = 'Automation'
      unattributed_count        — messages.sent_by_employee_id IS NULL

    If migration 0011 (system Automation employee) hasn't run yet the
    automation bucket is forced to 0 and `automation_employee_present`
    is `false` — never crashes."""
    import stats
    account_ids = clamp_account_filter(account_id)
    zone = await stats._report_zone(account_id)
    if from_:
        start = _parse_date(from_, field="from", zone=zone)
    else:
        start = datetime.utcnow() - timedelta(days=7)
    if to:
        end = _parse_date(to, field="to", zone=zone)
    else:
        end = datetime.utcnow()

    async with get_session() as s:
        # Tolerant fallback probe — done before the aggregate so we can
        # zero the automation bucket if the seed row is missing.
        auto_present_row = (await s.execute(
            select(Employee.id).where(Employee.display_name == "Automation").limit(1)
        )).first()
        automation_employee_present = auto_present_row is not None

        # LEFT JOIN messages → employees so we can bucket on employee
        # attributes (is_active, display_name) while still counting rows
        # whose sent_by_employee_id is NULL or points at a deleted employee.
        attributed_expr = case((Message.sent_by_employee_id.is_not(None), 1), else_=0)
        human_expr = case(
            (and_(Message.sent_by_employee_id.is_not(None), Employee.is_active == True), 1),  # noqa: E712
            else_=0,
        )
        automation_expr = case((Employee.display_name == "Automation", 1), else_=0)
        unattributed_expr = case((Message.sent_by_employee_id.is_(None), 1), else_=0)

        q = (
            select(
                Message.account_id.label("account_id"),
                func.count().label("outbound_total"),
                func.coalesce(func.sum(attributed_expr), 0).label("attributed_count"),
                func.coalesce(func.sum(human_expr), 0).label("attributed_to_human"),
                func.coalesce(func.sum(automation_expr), 0).label("attributed_to_automation"),
                func.coalesce(func.sum(unattributed_expr), 0).label("unattributed_count"),
            )
            .select_from(Message)
            .outerjoin(Employee, Message.sent_by_employee_id == Employee.id)
            .where(Message.direction == "out")
        )
        if start:
            q = q.where(Message.created_at >= start)
        if end:
            q = q.where(Message.created_at <= end)
        if account_ids is not None:
            q = q.where(Message.account_id.in_(account_ids))
        q = q.group_by(Message.account_id).order_by(Message.account_id)

        rows = (await s.execute(q)).all()

        # Resolve nicknames for the accounts that showed up. Separate
        # lookup keeps the aggregate query unchanged and lets accounts
        # without a row in `accounts` still render (display_name=None).
        acct_ids = [r.account_id for r in rows if r.account_id]
        nickname_by_id: dict[str, str | None] = {}
        if acct_ids:
            nick_rows = (await s.execute(
                select(Account.id, Account.nickname).where(Account.id.in_(acct_ids))
            )).all()
            nickname_by_id = {aid: nick for aid, nick in nick_rows}

    per_account = []
    totals_outbound = 0
    totals_attributed = 0
    for r in rows:
        outbound_total = int(r.outbound_total or 0)
        attributed_count = int(r.attributed_count or 0)
        attributed_to_human = int(r.attributed_to_human or 0)
        attributed_to_automation = (
            int(r.attributed_to_automation or 0) if automation_employee_present else 0
        )
        unattributed_count = int(r.unattributed_count or 0)
        per_account.append({
            "account_id": r.account_id,
            "display_name": nickname_by_id.get(r.account_id),
            "outbound_total": outbound_total,
            "attributed_count": attributed_count,
            "attributed_to_human": attributed_to_human,
            "attributed_to_automation": attributed_to_automation,
            "unattributed_count": unattributed_count,
            "coverage_pct": _coverage_pct(attributed_count, outbound_total),
        })
        totals_outbound += outbound_total
        totals_attributed += attributed_count

    return {
        "from": start.strftime("%Y-%m-%d") if start else None,
        "to": end.strftime("%Y-%m-%d") if end else None,
        "automation_employee_present": automation_employee_present,
        "per_account": per_account,
        "totals": {
            "outbound_total": totals_outbound,
            "coverage_pct": _coverage_pct(totals_attributed, totals_outbound),
        },
    }


@coverage_router.get("/admin/stats/attribution-coverage/recent")
async def attribution_coverage_recent(
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    """Debugging hook for the coverage endpoint: most-recent outbound
    messages whose `sent_by_employee_id` is NULL. Used to identify which
    code paths are still leaking attribution when coverage_pct drops."""
    account_ids = clamp_account_filter(None)
    async with get_session() as s:
        q = (
            select(
                Message.account_id,
                Message.fan_id,
                Message.message_id,
                Message.created_at,
                Message.body,
                Message.media_count,
            )
            .where(Message.direction == "out", Message.sent_by_employee_id.is_(None))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        if account_ids is not None:
            q = q.where(Message.account_id.in_(account_ids))
        rows = (await s.execute(q)).all()

    return {
        "messages": [
            {
                "account_id": r.account_id,
                "fan_id": int(r.fan_id) if r.fan_id is not None else None,
                "message_id": int(r.message_id) if r.message_id is not None else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "body": (r.body or "")[:80],
                "media_count": int(r.media_count or 0),
            }
            for r in rows
        ]
    }
