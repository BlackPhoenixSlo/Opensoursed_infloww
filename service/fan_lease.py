"""
Per-(account, fan) send lease + per-fan post-send cooldown — the two
anti-double-message primitives every sender uses (MASTER_PLAN §5.6, W3).

Moved out of automation_executor unchanged; it re-exports every name here as the
same object, and senders call them as `ax.acquire_fan_lease` / `ax.fan_on_cooldown`
/ `ax.start_fan_cooldown` (tests patch those on ax). A leaf: nothing here calls a
patched name, so it never imports the executor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import Fan, FanLease

log = logging.getLogger("of-relay.automation")

# Fan-lease TTL (W3): held for the WHOLE send, NOT released on success (let it
# expire) — only released on not-sent/error. So the TTL must clear the worst-case
# LLM-generate + OF-send latency, else a slow run's lease expires mid-send and a
# second automation could steal the fan. 900s (15 min) sits well above that.
_LEASE_TTL_S = 900
# After every CONFIRMED bot send, the fan rests: fans.automation_paused_until is
# set this far out and EVERY sender skips a paused fan BEFORE acquiring the lease.
# This is the load-bearing anti-double-message guard across overlapping ticks.
_FAN_COOLDOWN_S = 600          # 10 min — drip senders (welcome/followup) rest a fan
                              # this long after a send; chat senders use their own
                              # shorter _REPLY_COOLDOWN_S (45-90s) so convo flows.


# ── Concurrency primitive: per-(account, fan) send lease ─────────────

async def acquire_fan_lease(
    account_id: str,
    fan_id: int,
    automation_kind: str,
    *,
    ttl_s: int = _LEASE_TTL_S,
) -> bool:
    """Try to take the send-lease for one fan. Returns True iff we now hold it.

    DB-atomic: a single `INSERT … ON CONFLICT DO UPDATE … WHERE leased_until
    <= now` either inserts a fresh lease, steals an EXPIRED one, or — when a
    live lease is held — updates nothing (rowcount 0). So two automations
    racing the same fan in overlapping ticks can never both win: the first
    write commits a live lease, the second's WHERE excludes the row.

    A live lease blocks every other kind REGARDLESS of priority — priority
    (see kind_priority) only orders who *tries* first at dispatch, it never
    steals a live lease (that would risk a double-message).

    W3 lease lifecycle: the holder KEEPS the lease through the whole send and
    lets it expire by TTL on success (so a slow LLM+send can't have its lease
    stolen mid-flight); it calls `release_fan_lease()` ONLY when it did not send
    (skip/error/dry-run), to free the fan for a retry sooner. After a confirmed
    send the holder also calls `start_fan_cooldown()`, the durable cross-tick
    guard. One bot message per fan per cycle.
    """
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
            # Only an expired (or exactly-now) lease may be overwritten. A live
            # lease leaves rowcount at 0 → we did NOT acquire.
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


async def release_fan_lease(account_id: str, fan_id: int, *,
                            holder: str | None = None) -> None:
    """Drop a fan's lease early (after the send completes).

    `holder` narrows the DELETE to a lease this kind actually owns. Without it the
    delete is unconditional, and a short-lived holder whose TTL expired mid-send
    would tear down the lease a DIFFERENT automation had since acquired — it would
    then be the second sender in a fan's inbox in one beat, which is the exact
    thing the lease exists to prevent. Default None keeps every pre-existing caller
    byte-identical: they hold the 900s TTL and release inside it, so the narrowing
    would be a no-op for them and is not worth the churn of retrofitting.
    """
    async with get_session() as s:
        stmt = delete(FanLease).where(
            FanLease.account_id == str(account_id),
            FanLease.fan_id == int(fan_id),
        )
        if holder is not None:
            stmt = stmt.where(FanLease.automation_kind == str(holder))
        await s.execute(stmt)


async def _sweep_expired_leases() -> int:
    """Cheap housekeeping: drop every lease past its TTL (uses
    ix_fan_lease_expiry). Run once per supervisor tick. Returns rows removed."""
    now = datetime.utcnow()
    async with get_session() as s:
        res = await s.execute(
            delete(FanLease).where(FanLease.leased_until < now)
        )
    return res.rowcount or 0


# ── Concurrency primitive: per-fan post-send cooldown (W3) ───────────
#
# The load-bearing anti-double-message fix. After ANY automation confirms a send
# to a fan it sets `fans.automation_paused_until = now + cooldown`; EVERY sender
# calls `fan_on_cooldown()` BEFORE acquiring the lease and skips a paused fan.
# Unlike the lease (a short in-tick latch), the cooldown is the durable guard
# that holds ACROSS ticks — it survives even after the lease has expired/cleared.
# NOTE (per-fan, not per-kind): the rest is shared across automations, so whichever
# sender fired LAST sets it and the SHORTEST cooldown governs cross-automation
# re-touch (welcome_chatter_for_info's 45s can let another kind re-touch sooner than 30 min).
# Known + accepted — not a bug; WAVE 7's priority dispatch is where per-kind fan
# ownership lands.

async def start_fan_cooldown(
    account_id: str, fan_id: int, *, cooldown_s: int = _FAN_COOLDOWN_S, conn=None,
) -> datetime:
    """Rest a fan after a confirmed send: set automation_paused_until = now+cooldown.

    UPSERT, not UPDATE — many senders source candidates from the messages table,
    so an eligible fan may have no `fans` row yet; a bare UPDATE would match 0
    rows and silently fail to pause, re-opening the double-message. Returns the
    paused-until instant. `conn`: write inside the caller's transaction (the
    send's own, attribution.write_outbound_attribution) instead of a new one.
    """
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
            # updated_at = now (the row WAS touched now); NOT `until` — a
            # future updated_at leaks into User data's "last updated".
            set_={"automation_paused_until": until, "updated_at": now},
        )
    )
    if conn is not None:
        await conn.execute(stmt)
        return until
    async with get_session() as s:
        await s.execute(stmt)
    return until


async def fan_on_cooldown(account_id: str, fan_id: int) -> bool:
    """True iff `fans.automation_paused_until` is in the future. A fresh DB read
    (not the gather-time snapshot) so a fan another sender paused EARLIER IN THE
    SAME TICK is still skipped. Call this BEFORE acquire_fan_lease in every
    sender."""
    now = datetime.utcnow()
    async with get_session() as s:
        until = (
            await s.execute(
                select(Fan.automation_paused_until).where(
                    Fan.account_id == str(account_id),
                    Fan.fan_id == int(fan_id),
                )
            )
        ).scalar_one_or_none()
    return until is not None and until > now
