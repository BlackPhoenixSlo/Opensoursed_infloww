from __future__ import annotations

LEDGER = ("ledger: one write transaction per ledger page with news and none for a quiet re-poll (write_telemetry "
          "`ledger` label == `ingest_tx_page_written` lines < pages fetched, relay.log) and each fan's "
          "lifetime_spend_cents == its seeded spend + the sum of its revenue transactions")
CB_MONEY = ("cb_money_once: every reversed sale (ledger undo + dispute; dispute only; one of a "
            "same-fan same-amount pair 1 s apart) is chargedback and its fan's lifetime_spend_cents fell by it "
            "exactly once; the phase's revenue rows sum to the expected cents")
CB_OPEN = "cb_open_untouched: an open dispute (payment.status done) leaves its row's status and its fan's lifetime"
CB_UNMATCHED = ("cb_unmatched_no_insert: a dispute naming no ingested sale inserts nothing (transactions row count "
                "unchanged, no row for its fan)")
CB_REPOLL = ("cb_repoll_idempotent: a re-poll writes nothing (`ledger-chargebacks` write transactions and "
             "ingest_cb_applied lines unchanged, statuses and lifetimes unchanged)")
CB_CALLS = ("cb_call_budget: one OF /payouts/chargebacks call per Creator per completed refresh walk (fake-OF hits "
            "== ingest_tx_scan_end mode=refresh lines == ingest_cb_poll pages=1 lines; no ingest_cb_error)")


def _per_row_txns() -> None:
    import transaction_ingest as ti

    async def per_row(account_id, rows, *, capped=False):
        ins = pat = 0
        for raw in rows:
            i, p = await ti._write_one(account_id, raw, capped=capped)
            ins, pat = ins + i, pat + p
        return ins, pat

    ti.write_page = per_row


def _delta_separate_txn() -> None:
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
    ti.apply_lifetime_delta = drop_first(ti.apply_lifetime_delta)


def _cb_already_ignored() -> None:
    import dataclasses

    import transaction_chargebacks as cb

    real = cb.plan_chargebacks

    def plan(disputes, held):
        return real(disputes, [dataclasses.replace(h, status="cleared") for h in held])

    cb.plan_chargebacks = plan


def register(Fault) -> dict:
    return {
        "ledger-per-row-txns": Fault(_per_row_txns, (LEDGER,)),
        "ledger-delta-separate-txn": Fault(_delta_separate_txn, (LEDGER,)),
        "ledger-chargeback-already-ignored": Fault(_cb_already_ignored, (CB_MONEY, CB_REPOLL)),
    }
