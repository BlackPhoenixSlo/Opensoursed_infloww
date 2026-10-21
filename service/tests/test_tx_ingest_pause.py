#!/usr/bin/env python3
"""
transaction_ingest's failure backoff: what counts toward the auto-pause.

    case_proxy_refusal_is_not_counted   a proxy CONNECT 403 (curl 56, the
        transient IPRoyal DC refusal) never reached OF: the streak stays where
        it was and the account is not paused
    case_three_real_failures_pause_10_min
    case_success_resets_the_streak

Run: ./venv/bin/python service/tests/test_tx_ingest_pause.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import asyncio  # noqa: E402
import logging  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from curl_cffi.requests.exceptions import ProxyError  # noqa: E402

import transaction_ingest as ti  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, TransactionScanHistory  # noqa: E402

ACCT = "80000112"
REFUSAL = ProxyError(
    "Failed to perform, curl: (56) CONNECT tunnel failed, response 403. "
    "See https://curl.se/libcurl/c/libcurl-errors.html first for more details.")

logging.getLogger("of-relay.ingest_tx").setLevel(logging.WARNING)


async def _reset(failures: int = 0) -> None:
    async with get_session() as s:
        if await s.get(Account, ACCT) is None:
            s.add(Account(id=ACCT, nickname="founder"))
    async with get_session() as s:
        row = await s.get(TransactionScanHistory, ACCT)
        if row is None:
            row = TransactionScanHistory(account_id=ACCT)
            s.add(row)
        row.consecutive_failures = failures
        row.paused_until = None
        row.current_status = "refreshing"


async def _row() -> TransactionScanHistory:
    async with get_session() as s:
        return await s.get(TransactionScanHistory, ACCT)


def case_proxy_refusal_is_not_counted():
    async def go():
        await _reset(failures=2)
        for _ in range(5):
            await ti._record_failure(ACCT, REFUSAL)
        row = await _row()
        assert row.consecutive_failures == 2, row.consecutive_failures
        assert row.paused_until is None, row.paused_until
        assert not await ti._is_paused(ACCT)
        assert row.current_status != "refreshing", "the start-of-tick stamp was left in place"
        assert "CONNECT tunnel failed" in (row.last_error or "")
    asyncio.run(go())


def case_three_real_failures_pause_10_min():
    async def go():
        await _reset()
        for _ in range(3):
            await ti._record_failure(ACCT, RuntimeError("OF 500"))
        row = await _row()
        assert row.consecutive_failures == 3, row.consecutive_failures
        assert row.current_status == "paused", row.current_status
        left = (row.paused_until - datetime.utcnow()).total_seconds()
        assert 590 < left <= 600, f"paused for {left:.0f}s, want 10 min"
        assert await ti._is_paused(ACCT)
    asyncio.run(go())


def case_success_resets_the_streak():
    async def go():
        await _reset()
        await ti._record_failure(ACCT, RuntimeError("OF 500"))
        await ti._record_failure(ACCT, RuntimeError("OF 500"))
        await ti._mark_success(
            ACCT, mode="refresh", inserted=0, patched=0, last_marker=None, pages=1,
            page_rows_min_occurred_at=None, page_rows_max_occurred_at=None,
            floor_reached=True)
        assert (await _row()).consecutive_failures == 0
        await ti._record_failure(ACCT, RuntimeError("OF 500"))
        await ti._record_failure(ACCT, RuntimeError("OF 500"))
        row = await _row()
        assert row.consecutive_failures == 2, row.consecutive_failures
        assert row.paused_until is None or row.paused_until < datetime.utcnow() + timedelta(seconds=1), \
            "two failures after a success paused the account"
        assert not await ti._is_paused(ACCT)
    asyncio.run(go())


_harness.run()
