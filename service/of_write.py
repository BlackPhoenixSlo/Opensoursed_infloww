from __future__ import annotations

import asyncio
import inspect
import logging
from contextvars import ContextVar

from curl_cffi.const import CurlECode
from curl_cffi.requests import exceptions as curl_exc

from of_client import OUTBOUND_TEXT_GUARD, OFDeniedError, proxy_refused
import dm_rate
import run_slot
from write_gate import WriteGate
import run_decide
from send_tripwire import UnclaimedSend

log = logging.getLogger("of-relay.automation")


# OF throttles consecutive POSTs with a 400 "Please allow 10 seconds"; retry after an async pause, never a blocking sleep on the loop.
_RATE_LIMIT_MARK = "allow 10 seconds"


def is_rate_limited(exc: BaseException) -> bool:
    # 5xx or no answer echoing the text is unconfirmed: OF may have created it.
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and isinstance(detail.get("upstream_status"), int):
        status, text = detail["upstream_status"], str(detail.get("upstream_body", ""))
    else:
        status, text = getattr(getattr(exc, "response", None), "status_code", None), str(exc)
    return isinstance(status, int) and 400 <= status < 500 and _RATE_LIMIT_MARK in text.lower()


async def of_write_with_retry(fn, *, tries: int = 2, pause_s: float = 11.0):
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return await (fn() if inspect.iscoroutinefunction(fn) else asyncio.to_thread(fn))
        except Exception as e:  # noqa: BLE001 — re-raised below if not retryable
            if is_rate_limited(e) and attempt < tries:
                log.info("of_write_rate_limited attempt=%d — async pause %.0fs then retry",
                         attempt, pause_s)
                await asyncio.sleep(pause_s)
                last_exc = e
                continue
            raise
    assert last_exc is not None
    raise last_exc


# Proactive per-account spacing (OF throttles per account) so writes never crowd the 10 s window; operator writes are served before automation's.
_OF_WRITE_GAP_S = 11.0
_write_gates: dict[str, WriteGate] = {}

# The current run's OF writes, read by run_once when the run fails (send once: run_decide.outcome); a child task's write still marks it.
_RUN_WRITE: ContextVar[run_decide.RunWrites | None] = ContextVar("_run_write", default=None)


def _write_gate(account_id: str) -> WriteGate:
    gate = _write_gates.get(account_id)
    if gate is None:
        gate = _write_gates[account_id] = WriteGate()
    return gate


async def of_write_paced(account_id, fn, *, min_gap_s: float = _OF_WRITE_GAP_S,
                         tries: int = 2, pause_s: float = 11.0,
                         send_purpose: str | None = None, operator: bool | None = None,
                         dm: bool = False, before_write=None):
    # send_purpose is the audience-coverage assert: an untagged write raises under tests and logs loudly in prod.
    # before_write mints the run right before the write, so a restart during the spacing wait leaves nothing minted and the send is planned again.
    import audience_include as _audiences
    import automation_executor as ax
    _audiences.audit_send_purpose(send_purpose, where="of_write_paced")
    aid = str(account_id)
    if operator is None:
        operator = run_slot.operator_run()
    # Deliberately not run_slot.released(): send_mass_message spaces its write under broadcast_lock, and giving the slot back while holding a lock can deadlock against runs waiting on it. The DM rate wait is a plain wait for the same reason.
    if dm:
        await dm_rate.turn(aid, operator=operator)
    wait = await _write_gate(aid).turn(min_gap_s, operator=operator)
    if wait > 0.001:
        log.info("of_write_paced account=%s spaced %.1fs%s (loop/threads stay free)",
                 aid, wait, " operator" if operator else "")
    if before_write is not None:
        await before_write()
        # The gap counts from the write itself, not from the grant before_write ran after.
        gate = _write_gate(aid)
        gate.next_at = max(gate.next_at, asyncio.get_running_loop().time() + min_gap_s)
    cell = _RUN_WRITE.get()
    if cell is not None:
        fn = _tracked(fn, cell)
    if send_purpose != "manual":
        return await ax.of_write_with_retry(fn, tries=tries, pause_s=pause_s)
    # send_purpose manual (a human's composer message): the composer only warns on a sensitive word, it never refuses.
    guard_token = OUTBOUND_TEXT_GUARD.set(None)
    try:
        return await ax.of_write_with_retry(fn, tries=tries, pause_s=pause_s)
    finally:
        OUTBOUND_TEXT_GUARD.reset(guard_token)


def _may_have_sent(e: BaseException) -> bool:
    # curl_cffi raises every curl 28 phase, even connect, as plain Timeout; a canceled worker call keeps running: both may have sent. Dropped connections, 5xx and unknown failures may have sent; refusals, couldn't-connect and OF 4xx did not.
    current: BaseException | None = e
    for _ in range(32):
        if current is None:
            break
        if proxy_refused(current) or isinstance(current, (OFDeniedError, UnclaimedSend)):
            return False
        if isinstance(current, curl_exc.ConnectionError) and getattr(current, "code", None) == CurlECode.COULDNT_CONNECT:
            return False
        status = getattr(getattr(current, "response", None), "status_code", None)
        if isinstance(status, int):
            return not 400 <= status < 500
        current = current.__cause__
    return True


# Accepted risk: the x-hash warm-up GET of a fresh client runs inside fn, so its read timeout counts as maybe sent (one GET per pooled client).
def _tracked(fn, cell: run_decide.RunWrites):
    async def attempt():
        # Restoring `before` is exact only because a run's writes are sequential; concurrent writes in one run could undo an "accepted" (send-once).
        before = cell.state
        if before == "none":
            cell.state = "unanswered"
        try:
            result = await (fn() if inspect.iscoroutinefunction(fn) else asyncio.to_thread(fn))
        except BaseException as e:
            if not _may_have_sent(e):
                cell.state = before
            raise
        cell.state = "accepted"
        return result
    return attempt
