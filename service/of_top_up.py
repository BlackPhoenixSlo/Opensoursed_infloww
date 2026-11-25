from __future__ import annotations

from typing import Any

from sqlalchemy import text

import of_stats_daily
import tx_rollup
from attribution_backfill import TRACKED_STATUSES

# Measured against two live Creators: ppv_message matches OF to the cent per UTC day; tips/subscriptions matched 144 of 150 cells.
CATEGORY = {"subscription": "subscribes", "rebill": "subscribes", "ppv_message": "messages", "ppv": "messages",
            "tip": "tips", "tip_post": "tips", "tip_message": "tips", "ppv_post": "post", "ppv_stream": "stream"}


def rows_sql(params: tx_rollup.Binds, of_cells: dict[tuple[str, str], list[dict[str, Any]]]) -> str:
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
    # max(OF, ledger): OF never takes away a sale the ledger holds.
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
    out: dict[tuple, dict[str, Any]] = {}
    for c in (*cells, *more):
        key = tuple(c[d] for d in dims)
        acc = out.setdefault(key, {**dict(zip(dims, key)), **{m: 0 for m in tx_rollup.MEASURES}})
        for m in tx_rollup.MEASURES:
            acc[m] += int(c[m] or 0)
    return list(out.values())
