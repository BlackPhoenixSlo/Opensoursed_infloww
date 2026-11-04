"""The ledger reports' break-it-once faults (scenarios/2026-11-01-ledger-reports-volume.py): lib/faults.py
merges `register(Fault)` into FAULTS. Each patches a product module attribute inside the throwaway relay,
looked up at call time by the route, except loadmore-refires-on-error: a client fault (`browser=`, the app's
served JS in actors/ui.py). The check names live here and the scenario imports them, so a
target can never name a check that does not exist. Rank and CSV checks are one per route, so each
fault targets only the checks of the route it breaks.
"""
from __future__ import annotations

FAN_TOTALS = ("ledger reports: fan-report's every fan total / net (net_or_80) / tips / PPV / subs == the "
              "harness oracle (cleared + pending only), each sort key and limit, both Agencies")
FAN_RANK = "ledger reports: fan-report rank order kept and limit honoured per sort key (total|tips|ppv|subs)"
TOP_RANK = "ledger reports: top-tippers ranked by total desc, rank 1..n, limit honoured"
FAN_CSV = "ledger reports: fan-report CSV == JSON == oracle per Creator (rows, values, order, truncation)"
TIPS_CSV = "ledger reports: tips-list CSV == JSON pages == oracle per Creator (rows, amounts, order, truncation)"
TOP_CSV = "ledger reports: top-tippers CSV == JSON == oracle per Creator (rows, totals, order)"
SCOPE = ("ledger reports: no fan of another Agency in any list (fan-report, tips-list, top-tippers, "
         "paid-messages, sales-records; checks JSON and CSV, crowd JSON and CSV exports) and a foreign "
         "Creator id is refused")
TIPS = "ledger reports: tips-list rows == the oracle (tip kinds, cleared + pending), newest first"
TOP_TOTALS = "ledger reports: top-tippers totals and tip counts == the oracle (tip kinds, cleared + pending)"
TRAFFIC = ("ledger reports: fan-report traffic == the window's spend by each spender's earliest claim "
           "(link_claimers), the rest under no link")
PAID = ("ledger reports: paid-messages (kind=mass, type=paid) lists every paid broadcast once with recipients, "
        "buyers and earnings == oracle (refunded / charged-back buyers out)")
SALES = ("ledger reports: sales-records rows == oracle (each tracked credited sale once, Subscriptions "
         "unattributed by default), newest first, JSON pages == CSV")
XLSX = "ledger reports: POST /admin/stats/xlsx answers 2xx with a workbook body (PK zip magic)"
UI_TOTALS = "ledger reports UI: Fan reports' Total spend cells == the fan-report rows the page read == oracle"
UI_SIDE = "ledger reports UI side effect: Fan reports' Download report file == oracle (rows and total)"
PAGE_ERR_BOUNDED = ("ledger reports UI: the Tips tab list's next page answering 500 (browser wire) with the list's foot "
                    "in view 5 s is asked <= 2 times (retry: 1) and Load more stays offered; Load more once it "
                    "answers loads that page's rows")


def _counts_refunds() -> None:
    """Fan reports count reversed sales as spend (bug class: the status filter widened or dropped):
    `stats_fans.TRACKED_STATUSES` also holds chargedback / refunded / refund_pending."""
    import stats_fans
    stats_fans.TRACKED_STATUSES = (*stats_fans.TRACKED_STATUSES, "chargedback", "refunded", "refund_pending")


def _top_tippers_crosses_agency() -> None:
    """Top tippers loses its Agency scope (bug class: the account clamp skipped on one route):
    `transactions.clamp_account_filter` answers None (every Creator) when top_tippers calls it.
    The caller is told by its frame name: tips_list calls the same module global and no seam is
    top-tippers' own; a rename of the route function leaves the fault inert, which the --break run
    shows as NOT CAUGHT."""
    import sys

    import transactions
    real = transactions.clamp_account_filter

    def clamp(account_id=None):
        if sys._getframe(1).f_code.co_name == "top_tippers":
            return None
        return real(account_id)

    transactions.clamp_account_filter = clamp


def _csv_truncates() -> None:
    """Fan reports' CSV ends at the JSON page (bug class: the export reuses the page's limit):
    the `csv_export.download` fan_report calls streams at most 100 rows. Only stats_fans sees the
    cut: it gets a copy of the module with that one function wrapped."""
    import types

    import csv_export
    import stats_fans

    def download(filename, rows, *args, **kw):
        async def cut(s):
            k = 0
            async for r in rows(s):
                if k >= 100:
                    return
                k += 1
                yield r
        return csv_export.download(filename, cut, *args, **kw)

    shim = {k: v for k, v in vars(csv_export).items() if not k.startswith("__")}
    stats_fans.csv_export = types.SimpleNamespace(**{**shim, "download": download})


def _latest_claim() -> None:
    """Traffic credits a spender's newest claim (bug class: the earliest-claim order flipped):
    `stats_fans.first_claim_order` orders claims newest first (coalesce desc, then id desc)."""
    import stats_fans
    real = stats_fans.first_claim_order
    stats_fans.first_claim_order = lambda: tuple(c.desc() for c in real())


# app/hooks/useLoadMoreSentinel.ts's error gate, as next dev serves it (`!hasNextPage || isError)`).
# Files this scenario's UI loads that serve the hook: the Fan reports, Message dashboard and Sales records page
# chunks (3, measured: run 20261103T162315Z-2026-11-01-ledger-reports-volume-break-de25).
_LOADMORE_GATE = (r"(!hasNextPage)\s*\|\|\s*isError(\))", r"\1\2")
LOADMORE_FILES = 3


def register(Fault) -> dict:
    return {
        # slop/run ledger-reports-volume --break (the scenario's FAULT)
        # Every fan-report figure moves, so each oracle comparison of it goes red (the UI ones too, when on).
        "fan-report-counts-refunds": Fault(_counts_refunds, (FAN_TOTALS, FAN_RANK, FAN_CSV, TRAFFIC)),
        # slop/run ledger-reports-volume --break --fault=top-tippers-crosses-agency
        # Other Agencies' tippers join the board, so its totals, rank and CSV leave the oracle too.
        "top-tippers-crosses-agency": Fault(_top_tippers_crosses_agency, (SCOPE, TOP_TOTALS, TOP_RANK, TOP_CSV)),
        # slop/run ledger-reports-volume --break --fault=fan-report-csv-truncates
        # (with the UI on, the UI side-effect check, the page's Download report, goes red too)
        "fan-report-csv-truncates": Fault(_csv_truncates, (FAN_CSV,)),
        # slop/run ledger-reports-volume --break --fault=fan-report-latest-claim
        # Only spenders with two or more claims move, so only traffic leaves the oracle.
        "fan-report-latest-claim": Fault(_latest_claim, (TRAFFIC,)),
        # slop/run ledger-reports-volume --break --fault=loadmore-refires-on-error
        # Client side: the sentinel loses its error gate (the pre-fix hook), so a failed next page with the foot in
        # view is asked again on every fetch flip; only the page-error check goes red (no other check fails a page).
        "loadmore-refires-on-error": Fault(None, (PAGE_ERR_BOUNDED,), browser=(_LOADMORE_GATE,),
                                           browser_files=LOADMORE_FILES),
    }
