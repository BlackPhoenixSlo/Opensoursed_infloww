"""W7 webhook dispatch's break-it-once faults (service/webhook_dispatch.py, checked by
scenarios/2026-10-26-runtime-switches.py's same-fan burst phase): lib/faults.py merges
`register(Fault)` into FAULTS. The check name lives here and the scenario imports it, so
a target can never name a check that does not exist.

Each patches one module attribute in the relay process (`webhook_dispatch` looks them up
at call time); everything else is as shipped.
"""
from __future__ import annotations

BURST = "W7 same-fan burst: exactly one dispatch job per fan"
HOLD_S = 0.05   # _unserialized's read hold; the scenario gates the burst's same-fan gap under it


def _unserialized() -> None:
    """The per-(account, fan) serial is gone (the bug before it: two DMs of one fan ms
    apart each read "no pending job" before either inserts → 2 jobs). The race is made
    deterministic: the pending-job read answers HOLD_S after it was taken, so the second
    DM (a few ms behind, the pump's shape) reads before the first one's insert.
    Twin: service/tests/test_webhook_dispatch.py `_stale_dup_read` (same wrapper, unit side)."""
    import asyncio
    import contextlib

    import webhook_dispatch as wd

    real = wd._has_imminent_pending_job

    async def stale(account_id, kind, fan_id, within_s, *, s=None):
        got = await real(account_id, kind, fan_id, within_s, s=s)
        await asyncio.sleep(HOLD_S)
        return got

    wd._fan_serial = lambda account_id, fan_id: contextlib.nullcontext()
    wd._has_imminent_pending_job = stale


def _dedup_ignored() -> None:
    """The plan ignores the pending-job read (dup forced False): every DM of a fan queues
    its own job, cooldown-deferred ones included."""
    import webhook_dispatch_decide as decide

    real = decide.plan

    def no_dup(kind, rule_id, fan_id, paused_until, delay_s, dup, now):
        return real(kind, rule_id, fan_id, paused_until, delay_s, False, now)

    decide.plan = no_dup


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-26-runtime-switches --break --fault=w7-dispatch-unserialized
        "w7-dispatch-unserialized": Fault(_unserialized, (BURST,)),
        # slop/run 2026-10-26-runtime-switches --break --fault=w7-dedup-ignored
        "w7-dedup-ignored": Fault(_dedup_ignored, (BURST,)),
    }
