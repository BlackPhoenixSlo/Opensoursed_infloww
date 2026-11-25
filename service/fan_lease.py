from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import Fan, FanLease

log = logging.getLogger("of-relay.automation")

# Held for the WHOLE send and not released on success, so the TTL must clear the worst LLM+send latency or a second automation steals the fan.
_LEASE_TTL_S = 900
# After a confirmed send every sender skips the fan BEFORE the lease: the cross-tick anti-double-message guard. Chat senders use a shorter one.
_FAN_COOLDOWN_S = 600



# A live lease blocks every kind regardless of priority; priority only orders who tries first.
async def acquire_fan_lease(
    account_id: str,
    fan_id: int,
    automation_kind: str,
    *,
    ttl_s: int = _LEASE_TTL_S,
) -> bool:
    now = datetime.utcnow()
    until = now + timedelta(seconds=ttl_s)
    stmt = (
        sqlite_insert(FanLease)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            automation_kind=automation_kind,
            leased_until=until,
            acquired_at=now,
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_={
                "automation_kind": automation_kind,
                "leased_until": until,
                "acquired_at": now,
            },
            where=FanLease.leased_until <= now,
        )
    )
    async with get_session() as s:
        res = await s.execute(stmt)
        got = (res.rowcount or 0) > 0
    if got:
        log.debug(
            "fan_lease_acquired account=%s fan=%s kind=%s ttl=%ds",
            account_id, fan_id, automation_kind, ttl_s,
        )
    else:
        log.debug(
            "fan_lease_blocked account=%s fan=%s kind=%s (live lease held)",
            account_id, fan_id, automation_kind,
        )
    return got


# `holder` narrows the DELETE: an expired holder must not tear down a lease a different automation has since acquired.
async def release_fan_lease(account_id: str, fan_id: int, *,
                            holder: str | None = None) -> None:
    async with get_session() as s:
        stmt = delete(FanLease).where(
            FanLease.account_id == str(account_id),
            FanLease.fan_id == int(fan_id),
        )
        if holder is not None:
            stmt = stmt.where(FanLease.automation_kind == str(holder))
        await s.execute(stmt)


async def _sweep_expired_leases() -> int:
    now = datetime.utcnow()
    async with get_session() as s:
        res = await s.execute(
            delete(FanLease).where(FanLease.leased_until < now)
        )
    return res.rowcount or 0



# Cooldown is per fan, not per kind: the last sender's (shortest) cooldown governs cross-automation re-touch; accepted.
# UPSERT: an eligible fan may have no fans row yet, and a bare UPDATE would silently fail to pause.
async def start_fan_cooldown(
    account_id: str, fan_id: int, *, cooldown_s: int = _FAN_COOLDOWN_S, conn=None,
) -> datetime:
    now = datetime.utcnow()
    until = now + timedelta(seconds=cooldown_s)
    stmt = (
        sqlite_insert(Fan)
        .values(
            account_id=str(account_id),
            fan_id=int(fan_id),
            automation_paused_until=until,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["account_id", "fan_id"],
            set_={"automation_paused_until": until, "updated_at": now},
        )
    )
    if conn is not None:
        await conn.execute(stmt)
        return until
    async with get_session() as s:
        await s.execute(stmt)
    return until


# Fresh read, not the gather-time snapshot: a fan paused earlier in the same tick must still be skipped.
async def fan_on_cooldown(account_id: str, fan_id: int) -> bool:
    return int(fan_id) in await fans_on_cooldown(account_id, [fan_id])


async def fans_on_cooldown(account_id: str, fan_ids) -> set[int]:
    now = datetime.utcnow()
    async with get_session() as s:
        rows = (
            await s.execute(
                select(Fan.fan_id, Fan.automation_paused_until).where(
                    Fan.account_id == str(account_id),
                    Fan.fan_id.in_([int(f) for f in fan_ids]),
                )
            )
        ).all()
    return {int(f) for f, until in rows if until is not None and until > now}
