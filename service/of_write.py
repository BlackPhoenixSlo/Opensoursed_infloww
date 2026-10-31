"""
The paced OF write: per-account spacing (write_gate.WriteGate), the DM rate wait
(dm_rate), the async retry on OF's "Please allow 10 seconds" 400, and the per-run
write tracking run_once reads on a failed run (send once: run_decide.outcome).

Moved out of automation_executor unchanged; it re-exports every name here as the
same object (`ax._write_gates is of_write._write_gates`). Tests patch
`ax.of_write_paced` and `ax.of_write_with_retry`, so of_write_paced reaches its
retry as `ax.of_write_with_retry` (a lazy import: the executor imports this
module at load).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from contextvars import ContextVar

from curl_cffi.const import CurlECode
from curl_cffi.requests import exceptions as curl_exc

from of_client import OUTBOUND_TEXT_GUARD, OFDeniedError
import dm_rate
import run_slot
from write_gate import WriteGate
import run_decide

log = logging.getLogger("of-relay.automation")

# ── OF write helper: off-thread + async retry on rate limit ──────────

# OF throttles consecutive POSTs (create_post, /messages/queue) with a 400
# `{"message":"Please allow 10 seconds"}`. We retry once after an ASYNC pause —
# asyncio.sleep yields the event loop, so the relay keeps serving other work
# (never a blocking time.sleep on the main loop).
_RATE_LIMIT_MARK = "allow 10 seconds"


def is_rate_limited(exc: BaseException) -> bool:
    """Whether `exc` is OF's "Please allow 10 seconds" rate-limit refusal."""
    return _RATE_LIMIT_MARK in str(exc).lower()


async def of_write_with_retry(fn, *, tries: int = 2, pause_s: float = 11.0):
    """Run a blocking OF write `fn` off-thread (an `async def` `fn` is awaited
    on the loop instead); on OF's rate-limit 400, pause asynchronously and
    retry (up to `tries` total attempts). Any other error — or the final
    attempt — propagates unchanged."""
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
    assert last_exc is not None  # unreachable: loop either returns or raises
    raise last_exc


# Proactive per-account spacing so consecutive OF writes never crowd the 10s
# window in the first place: each write on an account waits at its gate
# (write_gate.WriteGate) until its turn, at least the gap after the previous
# write started, and the operator's writes are served before automation's
# (ADR 0025). The wait is an async wait — the event loop and worker threads
# stay free for everything else (other accounts, other automations, the
# relay's own traffic). Per-account because OF throttles per-account;
# different girls send concurrently.
_OF_WRITE_GAP_S = 11.0
_write_gates: dict[str, WriteGate] = {}

# The current run's OF writes, which run_once reads when the run fails (send once:
# run_decide.outcome). A mutable cell, set per run, so a write from a child task the
# automation spawned still marks it.
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
    """SPACE this OF write ≥ `min_gap_s` after the previous one for this account
    (proactive — so we rarely trip the limit at all), then run it through the
    reactive async retry as a backstop.

    `send_purpose` is the audience-coverage transport assert: every automation
    write through this seam declares gated / fenced / manual / not_fan_dm /
    exempt:<reason>. Untagged raises under the test harness and logs loudly in
    prod — a future sender that dodges the classification manifest still trips
    this wire (audience_include.audit_send_purpose).

    `send_purpose="manual"` (a human's composer message — sent now, or deferred
    through scheduled_send) stands the run's outbound word guard aside: the
    composer only warns on a sensitive word, it never refuses.

    `operator`: a write a person started in the app (the chat delete, a vault
    import) goes ahead of automation's waiting writes; None = the current
    run's tier (an operator's run, ADR 0025), else automation.

    `dm`: the write is a DM (POST chats/{id}/messages): an automation one first
    waits for a place in the account's DM window (dm_rate, OF_DM_PER_MIN); an
    operator's only counts. A plain wait like the spacing, the slot kept.

    `before_write`: an async callable run once the turn is granted, right
    before the write. send_mass_message mints its run there, so a run row means
    the write was next, never "still waiting for its turn": a restart during
    the spacing wait leaves nothing minted, and the send is planned again.

    The spacing wait yields the event loop, so during the wait the worker
    threads and the loop remain available for other work. If the account has
    been idle longer than the gap, there's no wait at all."""
    import audience_include as _audiences
    import automation_executor as ax  # lazy: tests patch ax.of_write_with_retry
    _audiences.audit_send_purpose(send_purpose, where="of_write_paced")
    aid = str(account_id)
    if operator is None:
        operator = run_slot.operator_run()
    # Deliberately NOT run_slot.released(): send_mass_message spaces its write
    # under broadcast_lock, and a run that gave its slot back while holding a
    # lock can deadlock against runs holding slots waiting for it. The DM
    # rate wait (before the gate, so the gate's spacing counts from the send)
    # is a plain wait for the same reason.
    if dm:
        await dm_rate.turn(aid, operator=operator)
    wait = await _write_gate(aid).turn(min_gap_s, operator=operator)
    if wait > 0.001:
        log.info("of_write_paced account=%s spaced %.1fs%s (loop/threads stay free)",
                 aid, wait, " operator" if operator else "")
    if before_write is not None:
        await before_write()
    cell = _RUN_WRITE.get()
    if cell is not None:
        fn = _tracked(fn, cell)
    if send_purpose != "manual":
        return await ax.of_write_with_retry(fn, tries=tries, pause_s=pause_s)
    guard_token = OUTBOUND_TEXT_GUARD.set(None)
    try:
        return await ax.of_write_with_retry(fn, tries=tries, pause_s=pause_s)
    finally:
        OUTBOUND_TEXT_GUARD.reset(guard_token)


def _may_have_sent(e: BaseException) -> bool:
    """Whether OnlyFans may have taken the write attempt that raised `e` (send once).
    Surely not: refused before it left the box (OFDeniedError, a deactivated Creator's
    too), the proxy never opened the tunnel (ProxyError), the connection never opened
    (ConnectTimeout, curl's couldn't-connect: of_client._proxy_retry's own split), or
    OF answered 4xx (its rate-limit 400 included: is_rate_limited). Anything else may
    have: a read timeout, a dropped connection, a 5xx, a cancel while the call was out
    (its worker thread runs on), anything unknown."""
    if isinstance(e, (OFDeniedError, curl_exc.ProxyError, curl_exc.ConnectTimeout)):
        return False
    if isinstance(e, curl_exc.ConnectionError) and getattr(e, "code", None) == CurlECode.COULDNT_CONNECT:
        return False
    if is_rate_limited(e):
        return False
    status = getattr(getattr(e, "response", None), "status_code", None)
    return not (isinstance(status, int) and 400 <= status < 500)


def _tracked(fn, cell: run_decide.RunWrites):
    """`fn` as one tracked attempt (of_write_with_retry calls it once per try): while
    it is out, the run counts as maybe sent ("unanswered"); OF answering OK makes it
    "accepted"; an attempt that surely did not send (not _may_have_sent) puts back
    what was before it. So a cancel in the rate-limit pause after OF's 400, or an
    unrelated raise after a refused write, finds nothing sent. The attempts of one run
    go one after another (each sender awaits its write), so "what was before" is
    exact. Accepted risk: the x-hash warm-up GET of a fresh client runs inside `fn`,
    so its read timeout counts as maybe sent (one GET per pooled client)."""
    async def attempt():
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
