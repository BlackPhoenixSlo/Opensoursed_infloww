"""Ledger scan and held-row evidence shared by the pacing and watermark checks."""
from __future__ import annotations

import re
from collections import Counter

TX_START = re.compile(r"ingest_tx_scan_start account=(\S+) mode=(\w+)")
SCAN_END = re.compile(r"ingest_tx_scan_end account=(\S+) ")
IN_FLIGHT = ("refreshing", "backfilling")   # transaction_ingest_decide.IN_FLIGHT: a tick under way
_SCAN_KEYS = ("done", "cursor", "status", "failures", "last_error", "floor", "newest", "paused_until", "last_full_at",
              "full_walk_failures")


def scan_many(w, aids) -> dict[str, dict]:
    aids = list(aids)
    if not aids:
        return {}
    con = w.sql()
    rows = con.execute(
        "SELECT account_id, fully_backfilled, oldest_seen_occurred_at, current_status, consecutive_failures, "
        "last_error, backfill_floor, newest_seen_occurred_at, paused_until, last_full_at, full_walk_failures "
        f"FROM transaction_scan_history WHERE account_id IN ({','.join('?' * len(aids))})", aids).fetchall()
    con.close()
    return {r[0]: dict(zip(_SCAN_KEYS, r[1:])) for r in rows}


def scan_one(w, aid: str) -> dict:
    return scan_many(w, [aid]).get(aid, dict.fromkeys(_SCAN_KEYS))


def held(w, aid: str) -> tuple[Counter, int, int]:
    """Provider id -> rows, their amount cents, and the Creator's fan lifetime cents."""
    con = w.sql()
    ids = Counter(str(r[0]) for r in con.execute(
        "SELECT provider_transaction_id FROM transactions WHERE account_id = ? AND provider_transaction_id IS NOT NULL",
        (aid,)))
    total = con.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE account_id = ? "
                        "AND provider_transaction_id IS NOT NULL", (aid,)).fetchone()[0]
    life = con.execute("SELECT COALESCE(SUM(lifetime_spend_cents), 0) FROM fans WHERE account_id = ?", (aid,)).fetchone()[0]
    con.close()
    return ids, total, life


def held_count(w, aid: str) -> int:
    return sum(held(w, aid)[0].values())


def tx_status(w, aid: str, pid) -> str | None:
    con = w.sql()
    row = con.execute("SELECT status FROM transactions WHERE account_id = ? AND provider_transaction_id = ?",
                      (aid, str(pid))).fetchone()
    con.close()
    return row[0] if row else None
