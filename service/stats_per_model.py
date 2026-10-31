"""
stats_per_model.py — Per-model KPIs, split out of stats.py.

  GET /admin/stats/per-model        → one row per Creator in the window:
                                       revenue by kind, net, pending, refunds,
                                       subs, messages, spenders, OF's Statistics

`per_model` does the reads; `pivot_models` (pure: no DB, no awaits) turns
their rows into the per-Creator rows, each started as `empty_model_row`;
`pick_active_subs_source` (pure) picks the active-subs read.

stats.py includes this router where the route stood (route order). The report
zone and OF's top-ups are read as `stats._report_zone` / `stats._of_top_ups`
at call time (imported in the route, no import-time cycle), so a patch on
`stats` (slop fault of-zero-erases-db-sale) reaches this route as before the
split.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, text

import msg_stats
import of_stats_daily
import tx_rollup
from attribution_backfill import PPV_KINDS, REVENUE_KINDS, REVERSED_STATUSES, TRACKED_STATUSES
from auth import clamp_account_filter
from db.engine import get_session
from db.models import Account, Fan, Message, Transaction
from stats_fans import new_subs_q
from stats_window import parse_date as _parse_date, stats_guard

log = logging.getLogger("of-relay.stats")

router = APIRouter(dependencies=[Depends(stats_guard)])


# ── Per-model KPIs ───────────────────────────────────────────────


def _kind_bucket(kind: str | None) -> str:
    """Collapse Phase F's rich kind vocabulary to the chip buckets the
    per-model card knows about. Without this, `ppv_message`/`ppv_post`/
    `tip_post`/etc. silently fall into `custom` because the response dict
    has no key for them — they go to `custom` in the chips and the PPV
    chip shows $0 even when there is real PPV revenue.

    Feed-post sales (`ppv_post`, `tip_post`) get their own `post` bucket so
    the card can show post revenue separately — these MUST be checked before
    the generic `ppv`/`tip` prefix rules below or they'd fold into those."""
    if not kind:
        return "custom"
    if kind in ("ppv_post", "tip_post"):
        return "post"
    if kind.startswith("ppv"):
        return "ppv"
    if kind.startswith("tip"):
        return "tip"
    if kind == "subscription":
        return "subscription"
    if kind == "rebill":
        return "rebill"
    return "custom"


def _safe_div(num: int, den: int) -> int | None:
    """Integer division returning None when the denominator is 0 — the UI
    distinguishes "no data" from a real zero (a model with no new subs has
    no LTV, not LTV=0)."""
    if den <= 0:
        return None
    return int(num // den)


def empty_model_row(aid: str, *, engagement: bool, active_subs_known: bool) -> dict[str, Any]:
    """A Creator's per-model row before any read lands on it: every money and
    count field zero, the derived ones null; `active_subs_count` null when no
    active-subs source has a signal; the engagement fields only with
    `engagement`."""
    row: dict[str, Any] = {
        "account_id": aid,
        "display_name": None,
        "revenue_by_kind": {
            "ppv": 0,
            "post": 0,
            "tip": 0,
            "subscription": 0,
            "rebill": 0,
            "custom": 0,
        },
        "pending_by_kind": {
            "ppv": 0,
            "post": 0,
            "tip": 0,
            "subscription": 0,
            "rebill": 0,
            "custom": 0,
        },
        "total_revenue_cents": 0,
        # OF's own post-fee figure, summed from transactions.net_cents.
        # `net_missing_count` > 0 means some rows have no net yet (a
        # WS-pumped sale the ledger has not backfilled) — the UI must
        # disclose that rather than treat the sum as complete.
        "total_net_revenue_cents": 0,
        "net_missing_count": 0,
        "messages_sent": 0,
        "ppv_conversions": 0,
        "new_subs_count": 0,
        "active_subs_count": 0 if active_subs_known else None,
        "ltv_cents": None,
        "arpu_cents": None,
        "pending_revenue_cents": 0,
        "pending_clears_by": None,
        "refunded_cents": 0,
        "refunded_net_cents": 0,
        "spenders_count": 0,
        "avg_spend_per_spender_cents": None,
        "avg_spend_per_transaction_cents": None,
        "of_visitors": None,
        "of_renewals": None,
        "of_new_sub_conversion_pct": None,
        "of_renew_on": None,
        "of_renew_on_pct": None,
    }
    if engagement:
        row.update(ppvs_sent=0, fans_chatted=0, avg_reply_seconds=None)
    return row


ActiveSubsSource = Literal["subscription_expires_at", "transactions_31d", "unavailable"]


def pick_active_subs_source(r_act: list[Any], r_act_tx: list[Any]) -> ActiveSubsSource:
    """The best active-subs source, pure: Fan.subscription_expires_at (a real
    expiry) when any of its rows counts a subscriber, else the 31-day
    transactions heuristic (Q3b) when any of its rows does, else "unavailable"
    so the UI renders "—" instead of a misleading 0."""
    if any(int(r.active_subs or 0) > 0 for r in r_act):
        return "subscription_expires_at"
    if any(int(r.active_subs or 0) > 0 for r in r_act_tx):
        return "transactions_31d"
    return "unavailable"


def pivot_models(*, acct_rows: list[Any], r_sums: list[Any], top: list[dict[str, Any]], r_new: list[Any],
                 r_act: list[Any], r_msg: list[Any], r_reply: list[Any], r_pending: list[Any],
                 r_spend: list[Any], r_of: dict[str, dict[str, Any]], active_subs_source: str,
                 engagement: bool) -> list[dict[str, Any]]:
    """per_model's rows from its reads, pure (no DB, no awaits): every Creator in
    `acct_rows` (id, nickname) and every one a read names, sorted by total
    revenue descending. `r_sums` the rollup by (account_id, kind, status), `top`
    OF's top-ups by account_id (`_of_top_ups`), `r_act` the chosen active-subs
    source's rows, `r_of` OF's Statistics per Creator; the others as
    per_model reads them."""
    by_acct: dict[str, dict[str, Any]] = {}

    def _ensure(aid: str) -> dict[str, Any]:
        if aid in by_acct:
            return by_acct[aid]
        row = empty_model_row(aid, engagement=engagement,
                              active_subs_known=active_subs_source != "unavailable")
        by_acct[aid] = row
        return row

    # Seed with every known account so models with zero traffic still show.
    nickname_by_id: dict[str, str | None] = {aid: nick for aid, nick in acct_rows}
    for aid in nickname_by_id:
        row = _ensure(aid)
        row["display_name"] = nickname_by_id[aid]

    for r in r_sums:
        row = _ensure(r.account_id)
        bucket = _kind_bucket(r.kind)
        amount = int(r.gross_cents or 0)
        if r.status in TRACKED_STATUSES:
            row["revenue_by_kind"][bucket] += amount
            row["total_revenue_cents"] += amount
            row["total_net_revenue_cents"] += int(r.net_cents or 0)
            row["net_missing_count"] += int(r.net_missing or 0)
            # PPV conversions: every tracked PPV sale in the window (a
            # re-purchase is a separate sale), the attribution view's rows.
            if r.kind in PPV_KINDS:
                row["ppv_conversions"] += int(r.sales or 0)
        # Pending is a subset of the revenue above: a reversal never clears.
        if r.status == "pending":
            row["pending_revenue_cents"] += amount
            row["pending_by_kind"][bucket] += amount
        if r.status in REVERSED_STATUSES:
            row["refunded_cents"] += amount
            row["refunded_net_cents"] += int(r.net_cents or 0)

    # OnlyFans' own figure where it is over the ledger's (`_of_top_ups`, as
    # /admin/stats/revenue reads it). Pending, refunds and PPV conversions stay
    # the ledger's (OF charts none of them).
    for c in top:
        row = _ensure(c["account_id"])
        row["revenue_by_kind"][_kind_bucket(c["kind"])] += c["gross_cents"]
        row["total_revenue_cents"] += c["gross_cents"]
        row["total_net_revenue_cents"] += c["net_cents"]

    for r in r_new:
        row = _ensure(r.account_id)
        row["new_subs_count"] = int(r.new_subs or 0)

    if active_subs_source != "unavailable":
        for r in r_act:
            row = _ensure(r.account_id)
            row["active_subs_count"] = int(r.active_subs or 0)

    for r in r_msg:
        if engagement:
            _ensure(r.account_id).update(messages_sent=int(r.messages), ppvs_sent=int(r.ppvs or 0),
                                         fans_chatted=int(r.fans))
        else:
            _ensure(r.account_id)["messages_sent"] = int(r.messages_sent or 0)

    replies: dict[str, list[float]] = {}
    for r in r_reply:
        acc = replies.setdefault(r.account_id, [0, 0.0])
        acc[0] += int(r.replies)
        acc[1] += float(r.reply_seconds or 0)
    for aid, (n, seconds) in replies.items():
        if n:
            _ensure(aid)["avg_reply_seconds"] = round(seconds / n)

    for r in r_pending:
        if r.clears is not None:
            _ensure(r.account_id)["pending_clears_by"] = r.clears[:10]

    for r in r_spend:
        row = _ensure(r.account_id)
        row["spenders_count"] = int(r.spenders)
        row["avg_spend_per_spender_cents"] = _safe_div(int(r.cents or 0), int(r.spenders))
        row["avg_spend_per_transaction_cents"] = _safe_div(int(r.cents or 0), int(r.sales))

    for aid, figures in r_of.items():
        _ensure(aid).update(figures)

    for row in by_acct.values():
        row["ltv_cents"] = _safe_div(row["total_revenue_cents"], row["new_subs_count"])
        active = row["active_subs_count"]
        row["arpu_cents"] = (
            _safe_div(row["total_revenue_cents"], active)
            if isinstance(active, int) else None
        )

    return sorted(
        by_acct.values(),
        key=lambda x: x["total_revenue_cents"],
        reverse=True,
    )


@router.get("/admin/stats/per-model")
async def per_model(
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    account_id: str | None = Query(None),
    engagement: bool = Query(False),
) -> dict[str, Any]:
    """Per-OF-model KPIs for the stats dashboard. Returns one row per
    account in the window (defaults: last 30 days UTC), sorted by total
    revenue descending.

    Per-model fields:
      • account_id / display_name
      • revenue_by_kind   — {ppv, tip, subscription, rebill, custom}
      • total_revenue_cents
      • messages_sent     — an Employee's own sends, no mass or automated ones
                             (`msg_stats.chatter_sends`)
      • ppvs_sent, fans_chatted — with ``engagement=true`` only (Creator
                             reports): the priced ones among them, and the
                             fans they went to, each once
                             (`msg_stats.creator_sends`)
      • avg_reply_seconds — with ``engagement=true`` only: the Employees'
                             replies' average wait, null with none
                             (`msg_stats.reply_stats`)
      • ppv_conversions
      • new_subs_count    — DISTINCT fans whose subscription began in window,
                             free and trial ones included (see _new_subs_q)
      • active_subs_count — subscribers as of the window's end via
                             subscription_expires_at (see top-level
                             `active_subs_source`)
      • ltv_cents         — total / new_subs OR null
      • arpu_cents        — total / active OR null
      • refunded_cents    — gross of the window's reversals (REVERSED_STATUSES),
                             dated by their sale, as `status=reversed` on the
                             revenue read dates them; refunded_net_cents their
                             OF net
      • spenders_count, avg_spend_per_spender_cents,
        avg_spend_per_transaction_cents — see spenders_q
      • of_visitors, of_renewals, of_new_sub_conversion_pct, of_renew_on,
        of_renew_on_pct   — OnlyFans' Statistics over the window's UTC days
                             (`of_stats_daily.window_figures`), null unless
                             every day is stored

    The heavy sub-queries (money, new-subs, active-subs, messages) run
    concurrently via asyncio.gather to keep p95 latency under 500ms with 30+
    accounts.

    Caveat: `fans.subscription_status` is currently never populated, so we
    fall back to `subscription_expires_at > end`. If THAT column is also
    empty (nothing writes it today), the 31-day transactions fallback
    applies, else `active_subs_count` and `arpu_cents` are null for every
    model and the top-level `active_subs_source` is "unavailable"."""
    import stats
    account_ids = clamp_account_filter(account_id)
    zone = await stats._report_zone(account_id)
    if from_:
        start = _parse_date(from_, field="from", zone=zone)
    else:
        start = datetime.utcnow() - timedelta(days=30)
    if to:
        end = _parse_date(to, field="to", zone=zone)
    else:
        end = datetime.utcnow()

    # ── Build the queries ──────────────────────────────────────────────
    # Revenue, pending and PPV conversions by (account, kind, status), one
    # read of the hourly rollup (tx_rollup.window_sums). Revenue reads every
    # kind (the attribution view drops subscription/rebill/custom), counts
    # both cleared and pending (TRACKED_STATUSES); pending is surfaced
    # separately as pending_by_kind (subset, not additional) so the UI can
    # flag what's not yet bank-cleared.
    # `net_cents` rides along with gross so the creators table can reconcile
    # against a Net-basis KPI card. Purely ADDITIVE: it adds top-level keys and
    # moves no money between the existing `revenue_by_kind` buckets — that dict
    # is a closed 6-key TypeScript interface (app/hooks/useStats.ts) consumed by
    # PerModelKpiGrid / PerEmployeeTable / CompetitorReports, and adding a key to
    # IT would silently reroute revenue into a bucket those surfaces never render.
    async def _sums() -> list[Any]:
        async with get_session() as ss:
            return await tx_rollup.window_sums(ss, ("account_id", "kind", "status"), account_ids=account_ids,
                                               start=start, end=end)

    # New subs in window, each fan once (`stats_fans.new_subs_q`).
    new_fans = new_subs_q(account_ids, start, end).subquery()
    new_subs_by_acct = (select(new_fans.c.account_id, func.count().label("new_subs"))
                  .group_by(new_fans.c.account_id))
    window = tx_rollup.Binds()
    acct_in = "" if account_ids is None else " AND " + window.in_("account_id", account_ids)
    s_, e_ = window.bind(start.strftime(tx_rollup.TS_FORMAT)), window.bind(end.strftime(tx_rollup.TS_FORMAT))

    # Pending revenue's latest projected clearance per account:
    # max(occurred_at + payout_pending_days) over the pending rows.
    pending_q = text(
        "SELECT account_id, MAX(datetime(occurred_at, printf('%+d days', COALESCE(payout_pending_days, 0)))) "
        f"AS clears FROM transactions WHERE status = 'pending' AND occurred_at >= {s_} AND occurred_at <= {e_}{acct_in} "
        "GROUP BY account_id").bindparams(**window)

    # Q3: active subs snapshot — best available signal.
    # Per DA: `subscription_status` is never written. Use the fallback
    # path on `subscription_expires_at` unconditionally; the response
    # surfaces which source produced the count (or marks it
    # unavailable if expires_at is also empty).
    # Counted as of the window's end, not now, so a past window shows the
    # subscribers it ended with (roadmap S5).
    active_subs_q = select(
        Fan.account_id.label("account_id"),
        func.count().label("active_subs"),
    ).where(
        Fan.subscription_expires_at.is_not(None),
        Fan.subscription_expires_at > end,
        or_(Fan.subscribed_at.is_(None), Fan.subscribed_at <= end),
    )
    if account_ids is not None:
        active_subs_q = active_subs_q.where(Fan.account_id.in_(account_ids))
    active_subs_q = active_subs_q.group_by(Fan.account_id)

    # Q3b: transactions-based active-subs fallback. When
    # fans.subscription_expires_at is empty for every fan (most installs
    # today), derive "active" as DISTINCT fan_id with a cleared
    # subscription / rebill within 31 days of `end` — the period a
    # standard monthly OF sub covers. Multi-month subscribers leak out
    # of this window, so the count slightly under-reports yearly
    # subscribers. Acceptable until the WS pump populates expires_at
    # directly.
    tx_active_subs_q = select(
        Transaction.account_id.label("account_id"),
        func.count(func.distinct(Transaction.fan_id)).label("active_subs"),
    ).where(
        Transaction.kind.in_(("subscription", "rebill")),
        Transaction.status.in_(TRACKED_STATUSES),
        Transaction.fan_id.is_not(None),
        Transaction.occurred_at >= end - timedelta(days=31),
        Transaction.occurred_at <= end,
    )
    if account_ids is not None:
        tx_active_subs_q = tx_active_subs_q.where(Transaction.account_id.in_(account_ids))
    tx_active_subs_q = tx_active_subs_q.group_by(Transaction.account_id)

    # Q4: messages_sent per account: an Employee's own sends (`msg_stats.chatter_sends`).
    messages_q = select(
        Message.account_id.label("account_id"),
        func.count().label("messages_sent"),
    ).where(
        *await msg_stats.chatter_sends(),
        Message.created_at >= start,
        Message.created_at <= end,
    )
    if account_ids is not None:
        messages_q = messages_q.where(Message.account_id.in_(account_ids))
    messages_q = messages_q.group_by(Message.account_id)

    # Q4b, with `engagement` only (Creator reports, roadmap W5 5.3): the same
    # sends' PPVs and fans chatted (each fan once per Creator,
    # `msg_stats.creator_sends`, which counts the messages too), and the
    # replies' count and summed seconds (`msg_stats.reply_stats`).
    async def _messages() -> list[Any]:
        if not engagement:
            return await _run(messages_q)
        async with get_session() as ss:
            return await msg_stats.creator_sends(ss, account_ids=account_ids, start=start, end=end)

    async def _replies() -> list[Any]:
        if not engagement:
            return []
        async with get_session() as ss:
            return await msg_stats.reply_stats(ss, account_ids=account_ids, start=start, end=end)

    # Infloww's spender columns, from the ledger rows (a distinct fan count no
    # rollup keeps): the fans who bought content or tipped (REVENUE_KINDS, so a
    # subscription-only fan is no spender) and their spend on it, over them and
    # over their sales ("Average amount spent by each fan that purchased
    # content or gave tips", "... each time by fans on content or tips").
    spenders_q = select(
        Transaction.account_id.label("account_id"),
        func.count(func.distinct(Transaction.fan_id)).label("spenders"),
        func.sum(Transaction.amount_cents).label("cents"),
        func.count().label("sales"),
    ).where(
        Transaction.kind.in_(REVENUE_KINDS),
        Transaction.status.in_(TRACKED_STATUSES),
        Transaction.fan_id.is_not(None),
        Transaction.occurred_at >= start,
        Transaction.occurred_at <= end,
    )
    if account_ids is not None:
        spenders_q = spenders_q.where(Transaction.account_id.in_(account_ids))
    spenders_q = spenders_q.group_by(Transaction.account_id)

    # Run the heavy queries concurrently. AsyncSession is NOT safe to
    # share across `await` points (sa.exc.IllegalStateChangeError), so
    # each task opens its OWN session — the engine's connection pool
    # hands out one connection per task. SQLite WAL handles the parallel
    # readers fine and we keep the latency win.
    async def _run(stmt: Any) -> list[Any]:
        async with get_session() as ss:
            return (await ss.execute(stmt)).all()

    # pending_q failing must NOT 500 the dashboard — fall back to empty.
    async def _run_pending(stmt: Any) -> list[Any]:
        try:
            return await _run(stmt)
        except Exception:
            log.warning("per-model pending_q failed; reporting 0 pending", exc_info=True)
            return []

    r_sums, r_new, r_act, r_act_tx, r_msg, r_reply, r_pending, r_spend, r_of, (of_cells, _) = await asyncio.gather(
        _sums(),
        _run(new_subs_by_acct),
        _run(active_subs_q),
        _run(tx_active_subs_q),
        _messages(),
        _replies(),
        _run_pending(pending_q),
        _run(spenders_q),
        of_stats_daily.window_figures(account_ids, start, end),
        of_stats_daily.earnings_window(account_ids, start, end),
    )

    # Account labels — single query, separate from the heavy aggregates.
    # Clamp by `account_ids` (not the bare query-param `account_id`) so the
    # seed loop below only materializes cards the principal is allowed to
    # see. Without this, a chatter/owner with 15 accounts would still get
    # a card for every account in the DB (most all-zeros).
    async with get_session() as s:
        acct_q = select(Account.id, Account.nickname)
        if account_ids is not None:
            acct_q = acct_q.where(Account.id.in_(account_ids))
        acct_rows = (await s.execute(acct_q)).all()

    # The best active-subs source (`pick_active_subs_source`); the fallback reads its own rows.
    active_subs_source = pick_active_subs_source(r_act, r_act_tx)
    if active_subs_source == "transactions_31d":
        r_act = r_act_tx

    # ── Pivot rows by account_id (`pivot_models`) ─────────────────────
    # OnlyFans' top-ups read as `stats._of_top_ups` (the slop fault patches it there).
    top: list[dict[str, Any]] = []
    if of_cells:
        async with get_session() as ss:
            top = await stats._of_top_ups(ss, of_cells, ("account_id",))
    per_model_rows = pivot_models(acct_rows=acct_rows, r_sums=r_sums, top=top, r_new=r_new, r_act=r_act,
                                  r_msg=r_msg, r_reply=r_reply, r_pending=r_pending, r_spend=r_spend, r_of=r_of,
                                  active_subs_source=active_subs_source, engagement=engagement)

    return {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "active_subs_source": active_subs_source,
        "per_model": per_model_rows,
    }
