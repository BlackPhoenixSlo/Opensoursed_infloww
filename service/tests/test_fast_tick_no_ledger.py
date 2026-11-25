#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from sqlalchemy import func, select  # noqa: E402

import purchase_notifications  # noqa: E402
from purchase_poll_decide import Outcome  # noqa: E402
import purchase_poll as pp  # noqa: E402
import transaction_ingest as ti  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Transaction  # noqa: E402

ACCT = "31337"


class _LedgerSpy:
    def __init__(self):
        self.ledger_reads = 0

    def transactions(self, **_kw):
        self.ledger_reads += 1
        return {"list": [{"id": "tx-1", "amount": 10, "createdAt": "2026-10-19T10:00:00+00:00"}]}


async def case_fast_tick_skips_ledger_keeps_purchases():
    spy = _LedgerSpy()
    polled = []

    async def _poll(account_id, client, *, limit, pages=1):
        polled.append((account_id, client, limit))
        return {"outcome": Outcome("ok")}

    orig_client, orig_poll = ti._client_for, purchase_notifications.poll_purchases
    ti._client_for = lambda _aid: spy
    purchase_notifications.poll_purchases = _poll
    try:
        res = await pp.run_fast_tick(ACCT)
    finally:
        ti._client_for, purchase_notifications.poll_purchases = orig_client, orig_poll

    assert polled == [(ACCT, spy, pp._FAST_PAGE_LIMIT)], polled
    assert spy.ledger_reads == 0, "the 30 s tick must not re-read the ledger"
    assert res == {"rows_inserted": 0, "rows_patched": 0, "outcome": Outcome("ok")}, res
    async with get_session() as s:
        n = (await s.execute(select(func.count()).select_from(Transaction))).scalar()
    assert n == 0, f"fast tick wrote {n} ledger rows"


_harness.run()
