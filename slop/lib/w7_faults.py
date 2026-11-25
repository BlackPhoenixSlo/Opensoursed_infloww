from __future__ import annotations

BURST = "W7 same-fan burst: exactly one dispatch job per fan"
HOLD_S = 0.05


def _unserialized() -> None:
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
    import webhook_dispatch_decide as decide

    real = decide.plan

    def no_dup(kind, rule_id, fan_id, paused_until, delay_s, dup, now):
        return real(kind, rule_id, fan_id, paused_until, delay_s, False, now)

    decide.plan = no_dup


def register(Fault) -> dict:
    return {
        "w7-dispatch-unserialized": Fault(_unserialized, (BURST,)),
        "w7-dedup-ignored": Fault(_dedup_ignored, (BURST,)),
    }
