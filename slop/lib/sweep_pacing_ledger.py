"""sweep-pacing's ledger vocabulary (scenarios/2026-11-05-sweep-pacing.py, its docstring): OF's
ledger row shape, the ledger-only Creators' sizes and provider id bases, the product's page caps.
The scenario seeds with it, lib/sweep_pacing_backfill.py and lib/sweep_pacing_proxy.py judge and
seed with the same names."""
from __future__ import annotations

TX_PAGE = 100                # transaction_ingest._PAGE_LIMIT (OF's max a page)
TICK_PAGES, FRESH_PAGES = 40, 6   # transaction_ingest_decide's _BACKFILL_TICK_PAGES / _BACKFILL_FRESH_PAGES
TX_CYCLES = 4                # backfill, the full 7-day walk, two recent ones (the first after NEW_ROW_AGO)
DEEP_ROWS, DEEP_BELOW, DEEP_FAIL_AFTER = 6_000, 30, 5   # 61 pages: 5 + 429 / the cap / the rest, the 3 passes
DEEP_WALK_PAGE = 97          # DEEP's walk pages bound: DEEP_ROWS // DEEP_WALK_PAGE + 1 a pass
REACT_ROWS, REACT_HELD, REACT_BELOW, REACT_FLIPS, REACT_BLANK_AFTER, REACT_GAP_D = 1_500, 700, 20, 50, 8, 30
REACT_FLIP_FROM = 200        # REACT's held rows REACT_FLIP_FROM .. + REACT_FLIPS seeded pending (old flips)
REACT_DISPUTED = 650   # below the full walk's 600 rows, above REACT's blank page, held
CROWD_N, CROWD_ROWS = 8, 2_500
# OF provider id bases, one per seeded ledger (distinct: a provider id names one row).
LEDGER_ID = {"new": 9_000_000_000, "deep": 30_000_000_000, "deep_below": 31_000_000_000,
             "react": 32_000_000_000, "react_below": 33_000_000_000, "blank": 34_000_000_000,
             "blank_old": 35_000_000_000, "gap": 36_000_000_000, "crowd": 37_000_000_000,
             "px": 38_000_000_000, "fresh": 39_000_000_000}
LEDGER_ID_STRIDE = 100_000   # CROWD's / PX's Creators, each its own range
# Every write path a walk takes: PPV (_link_ppv_message, try_stamp_message), first charge, renewal, tip.
DESCRIPTIONS = ("Tip from u{}", "Payment for message from u{}", "Subscription from u{}", "Recurring subscription from u{}")
SALES = {"Tip": ("tip", "tips"), "Payment": ("ppv_message", "chat_messages"), "Subscription": ("subscription", "subscribes"),
         "Recurring": ("rebill", "subscribes")}


def iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")   # OF's timestamps


def tx_row(pid: int, fan: int, cents: int, at, status: str = "done", *, description: str | None = None) -> dict:
    """One OF ledger row; its description by default the write path `pid` picks."""
    return {"id": pid, "user": {"id": fan}, "amount": cents / 100, "currency": "USD", "createdAt": iso(at),
            "status": status, "net": cents * 0.8 / 100, "fee": cents * 0.2 / 100, "vatAmount": 0,
            "description": description if description is not None else DESCRIPTIONS[pid % len(DESCRIPTIONS)].format(fan)}


def sale(row: dict) -> tuple[str, str]:
    """The row's kind as the product writes it, and its dispute's paymentType."""
    return next(v for k, v in SALES.items() if row["description"].startswith(k))


def pages(n: int) -> int:
    return -(-n // TX_PAGE)
