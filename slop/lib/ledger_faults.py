"""The ledger ingest's break-it-once faults: lib/faults.py merges `register(Fault)` into FAULTS.

Each patches a real `transaction_ingest` function inside the throwaway relay (looked up by
module attribute at call time, so the patch is seen by every tick). The check name is
defined here and imported by scenarios/2026-10-27-sales-attribution-tips-ppv.py, so a target
can never name a check that does not exist.
"""
from __future__ import annotations

LEDGER = ("ledger: one write transaction per ledger page with news and none for a quiet re-poll (write_telemetry "
          "`ledger` label == `ingest_tx_page_written` lines < pages fetched, relay.log) and each fan's "
          "lifetime_spend_cents == its seeded spend + the sum of its revenue transactions")


def _per_row_txns() -> None:
    """A ledger page is written one row per write transaction (bug class: the page batch
    undone, the pre-batch writer's shape): `transaction_ingest._write_page` writes each row
    through `_write_one`. Every row still lands right, so only the txn count sees it."""
    import transaction_ingest as ti

    async def per_row(account_id, rows):
        ins = pat = 0
        for raw in rows:
            i, p = await ti._write_one(account_id, raw)
            ins, pat = ins + i, pat + p
        return ins, pat

    ti._write_page = per_row


def _delta_separate_txn() -> None:
    """A row's lifetime change is lost while its row commits (bug class: the pre-batch
    writer's delta in a transaction of its own after the row's, failing in between — a crash
    or a lock timeout): the first non-zero `transaction_ingest._bump_lifetime` /
    `_apply_lifetime_delta` call does nothing, so that fan's lifetime_spend_cents never moves."""
    import transaction_ingest as ti

    lost = []

    def drop_first(real):
        async def run(s, account_id, fan_id, cents):
            if cents and not lost:
                lost.append((account_id, fan_id, cents))
                return
            await real(s, account_id, fan_id, cents)
        return run

    ti._bump_lifetime = drop_first(ti._bump_lifetime)
    ti._apply_lifetime_delta = drop_first(ti._apply_lifetime_delta)


def register(Fault) -> dict:
    return {
        # slop/run sales-attribution --break --fault=ledger-per-row-txns
        "ledger-per-row-txns": Fault(_per_row_txns, (LEDGER,)),
        # slop/run sales-attribution --break --fault=ledger-delta-separate-txn
        "ledger-delta-separate-txn": Fault(_delta_separate_txn, (LEDGER,)),
    }
