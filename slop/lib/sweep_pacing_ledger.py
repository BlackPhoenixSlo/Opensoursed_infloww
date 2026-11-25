from __future__ import annotations

TX_PAGE = 100  # OF's max a page  # OF's max a page
TICK_PAGES, FRESH_PAGES = 40, 6
TX_CYCLES = 4
DEEP_ROWS, DEEP_BELOW, DEEP_FAIL_AFTER = 6_000, 30, 5
DEEP_WALK_PAGE = 97
REACT_ROWS, REACT_HELD, REACT_BELOW, REACT_FLIPS, REACT_BLANK_AFTER, REACT_GAP_D = 1_500, 700, 20, 50, 8, 30
REACT_FLIP_FROM = 200
REACT_DISPUTED = 650
CROWD_N, CROWD_ROWS = 8, 2_500
LEDGER_ID = {"new": 9_000_000_000, "deep": 30_000_000_000, "deep_below": 31_000_000_000,
             "react": 32_000_000_000, "react_below": 33_000_000_000, "blank": 34_000_000_000,
             "blank_old": 35_000_000_000, "gap": 36_000_000_000, "crowd": 37_000_000_000,
             "px": 38_000_000_000, "fresh": 39_000_000_000}
LEDGER_ID_STRIDE = 100_000
DESCRIPTIONS = ("Tip from u{}", "Payment for message from u{}", "Subscription from u{}", "Recurring subscription from u{}")
SALES = {"Tip": ("tip", "tips"), "Payment": ("ppv_message", "chat_messages"), "Subscription": ("subscription", "subscribes"),
         "Recurring": ("rebill", "subscribes")}


def iso(dt) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def tx_row(pid: int, fan: int, cents: int, at, status: str = "done", *, description: str | None = None) -> dict:
    return {"id": pid, "user": {"id": fan}, "amount": cents / 100, "currency": "USD", "createdAt": iso(at),
            "status": status, "net": cents * 0.8 / 100, "fee": cents * 0.2 / 100, "vatAmount": 0,
            "description": description if description is not None else DESCRIPTIONS[pid % len(DESCRIPTIONS)].format(fan)}


def sale(row: dict) -> tuple[str, str]:
    return next(v for k, v in SALES.items() if row["description"].startswith(k))


def pages(n: int) -> int:
    return -(-n // TX_PAGE)
