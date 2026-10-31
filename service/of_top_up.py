"""
of_top_up.py — what OnlyFans' own earnings figure adds to the ledger in the
reports: max(OF, ledger) per (Creator, UTC day, category). stats.py reads
`top_ups` through its module global `_of_top_ups` (slop's fault
`of-zero-erases-db-sale` swaps that global and calls `stats._of_top_up_rows`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

import of_stats_daily
import tx_rollup
from attribution_backfill import TRACKED_STATUSES

# The OnlyFans Statements category (of_stats_daily.EARNINGS) each ledger kind's
# sales count in; a kind OF's chart has no category we read for (stream tips:
# OF's `tips_stream`; custom) is in none. Measured 2026-10-25 against two live
# Creators: ppv_message = OF's messages to the cent per UTC day; tips and
# subscriptions with rebills matched 144 of 150 (Creator, day) cells.
CATEGORY = {"subscription": "subscribes", "rebill": "subscribes", "ppv_message": "messages", "ppv": "messages",
            "tip": "tips", "tip_post": "tips", "tip_message": "tips", "ppv_post": "post", "ppv_stream": "stream"}


def rows_sql(params: tx_rollup.Binds, of_cells: dict[tuple[str, str], list[dict[str, Any]]]) -> str:
    """SQL: per (account_id, UTC day, category) OnlyFans' stored figure for a
    day of `of_cells` (one read with OF's total: of_stats_daily._earnings_days)
    with the ledger's tracked sales of the same UTC day and category (`tx_daily`,
    whole UTC days as OF's), as columns o_* and l_*."""
    accounts, days = sorted({a for a, _d in of_cells}), sorted({d for _a, d in of_cells})
    cat = " ".join(f"WHEN {params.bind(k)} THEN {params.bind(c)}" for k, c in CATEGORY.items())
    lo, hi = params.bind(days[0]), params.bind(days[-1])
    return (
        "SELECT o.account_id AS account_id, o.day AS day, o.category AS category, o.net_cents AS o_net, "
        "o.gross_cents AS o_gross, o.sales AS o_sales, COALESCE(l.net, 0) AS l_net, "
        "COALESCE(l.gross, 0) AS l_gross, COALESCE(l.sales, 0) AS l_sales "
        "FROM of_earnings_daily o JOIN of_earnings_daily t ON t.account_id = o.account_id AND t.day = o.day "
        f"AND t.category = {params.bind(of_stats_daily.TOTAL)} "
        f"LEFT JOIN (SELECT account_id, day, CASE kind {cat} END AS category, SUM(gross_cents) AS gross, "
        "SUM(net_or_80_cents) AS net, SUM(sales) AS sales FROM tx_daily "
        f"WHERE {params.in_('account_id', accounts)} AND day >= {lo} AND day <= {hi} "
        f"AND {params.in_('status', TRACKED_STATUSES)} GROUP BY account_id, day, category) l "
        "ON l.account_id = o.account_id AND l.day = o.day AND l.category = o.category "
        f"WHERE {params.in_('o.account_id', accounts)} AND o.day >= {lo} AND o.day <= {hi} "
        f"AND {params.in_('o.category', of_stats_daily.EARNINGS)}")


async def top_ups(s, of_cells: dict[tuple[str, str], list[dict[str, Any]]],
                  dims: tuple[str, ...]) -> list[dict[str, Any]]:
    """What OnlyFans' own figure adds to the ledger, summed per `dims` (of
    "account_id", "day" = the UTC day) and kind: per (Creator, UTC day,
    category) of `of_cells` (of_stats_daily.earnings_window), max(OF, ledger),
    as the part over the ledger's tracked sales of the same UTC day (both cut
    days at UTC midnight: OF stamps its points 00:00+00:00), only where OF's
    net is the larger: the days before a Creator was connected, and sales the
    ledger missed. OF never takes away a sale the ledger holds (2026-10-25:
    OF's PPV messages were read as $0 and erased a real $14), so the reports
    read ledger + these. Cells shaped as `stats._day_sums`' (MEASURES), summed in
    SQL: a request turns a few rows, not one per Creator, day and category."""
    if not of_cells:
        return []
    params = tx_rollup.Binds()
    rows = rows_sql(params, of_cells)
    keys = ", ".join((*dims, "category"))
    sql = (f"SELECT {keys}, SUM(MAX(0, o_gross - l_gross)) AS gross_cents, SUM(o_net - l_net) AS net_cents, "
           "SUM(MAX(0, o_sales - l_sales)) AS sales, SUM(MAX(0, MAX(0, o_gross - l_gross) - (o_net - l_net))) AS fee_cents "
           f"FROM ({rows}) WHERE o_net > l_net GROUP BY {keys}")
    return [{**{d: getattr(r, d) for d in dims}, "kind": of_stats_daily.EARNINGS_KIND[r.category],
             "gross_cents": r.gross_cents, "net_cents": r.net_cents, "net_missing": 0, "net_or_80_cents": r.net_cents,
             "sales": r.sales, "fee_cents": r.fee_cents, "vat_cents": 0}
            for r in (await s.execute(text(sql), params)).all()]


def plus(cells: list[dict[str, Any]], more: list[dict[str, Any]], dims: tuple[str, ...]) -> list[dict[str, Any]]:
    """`cells` and `more` summed per `dims`."""
    out: dict[tuple, dict[str, Any]] = {}
    for c in (*cells, *more):
        key = tuple(c[d] for d in dims)
        acc = out.setdefault(key, {**dict(zip(dims, key)), **{m: 0 for m in tx_rollup.MEASURES}})
        for m in tx_rollup.MEASURES:
            acc[m] += int(c[m] or 0)
    return list(out.values())
