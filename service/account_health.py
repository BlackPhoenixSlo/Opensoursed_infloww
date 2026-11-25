from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import AccountHealth

log = logging.getLogger("of-relay.account-health")


# Strict: only wrong_user (301), otp_required (101) and no_session flag an account; transient 429/5xx must never pause a healthy one.
# 101 = OF re-inits auth and never retries; 105 is a per-request step-up, not session death.
def is_session_dead_error(exc: BaseException) -> str | None:
    from of_client import OFAPIError

    if isinstance(exc, OFAPIError) and "Wrong user" in str(exc):
        return "wrong_user"
    if isinstance(exc, OFAPIError) and _wants_otp(exc):
        return "otp_required"
    if isinstance(exc, FileNotFoundError) and "no captured session" in str(exc):
        return "no_session"
    return None


def _wants_otp(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else None
    if status is None:
        head = str(exc).split(" ", 1)[0]
        status = int(head) if head.isdigit() else None
    if status != 400:
        return False
    body = None
    try:
        body = exc.response.json() if getattr(exc, "response", None) is not None else None
    except Exception:
        body = None
    if body is None:
        message = str(exc)
        start = message.find("{")
        try:
            body, _ = json.JSONDecoder().raw_decode(message, start) if start >= 0 else (None, 0)
        except ValueError:
            return False
    err = body.get("error") if isinstance(body, dict) else None
    payload = err.get("payload") if isinstance(err, dict) else None
    return isinstance(payload, dict) and err.get("code") == 101 and "otpState" in payload


async def is_session_dead(account_id: str) -> bool:
    async with get_session() as s:
        dead_at = (await s.execute(
            select(AccountHealth.session_dead_at)
            .where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()
    return dead_at is not None


async def mark_session_dead(account_id: str, reason: str) -> bool:
    # Shielded: later callers' claims match nothing, so a cancelled winner would leave the episode untold.
    return await asyncio.shield(_claim_session_dead(account_id, reason))


# First statement is a write so the txn holds SQLite's write lock; the conditional UPDATE then matches exactly one caller.
async def _claim_session_dead(account_id: str, reason: str) -> bool:
    now = datetime.utcnow()
    async with get_session() as s:
        await s.execute(sqlite_insert(AccountHealth).values(account_id=account_id)
                        .on_conflict_do_nothing(index_elements=["account_id"]))
        # While dead, the first reason stays: it is the one the owner was told.
        newly = (await s.execute(
            update(AccountHealth)
            .where(AccountHealth.account_id == account_id, AccountHealth.session_dead_at.is_(None))
            .values(session_dead_at=now, session_dead_reason=reason, last_probe_at=None)
        )).rowcount == 1
        if newly:
            _announce(s, "session_dead", account_id, dead=True, reason=reason)
    if newly:
        from notifications_api import notify_session_dead
        await notify_session_dead(account_id, reason, now)
    return newly


async def clear_session_dead(account_id: str) -> bool:
    async with get_session() as s:
        row = (await s.execute(
            select(AccountHealth).where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()
        if row is None or row.session_dead_at is None:
            return False
        row.session_dead_at = None
        row.session_dead_reason = None
        row.last_probe_at = None
        _announce(s, "session_dead", account_id, dead=False, reason=None)
    return True


def _announce(s, event_type: str, account_id: str, **fields: object) -> None:
    import events
    events.on_commit(s, event_type, account_id=account_id, **fields)



# In-process mirror: OFClient._http_call runs in worker threads and cannot await the DB.
_writes_off: frozenset[str] = frozenset()


def refuses_writes(account_id: str) -> bool:
    return str(account_id) in _writes_off


def write_gate_snapshot() -> frozenset[str]:
    return _writes_off


async def load_write_gate() -> None:
    global _writes_off
    _writes_off = frozenset(await deactivated_ids())


async def deactivated_since(account_id: str) -> datetime | None:
    async with get_session() as s:
        return (await s.execute(
            select(AccountHealth.deactivated_at)
            .where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()


async def is_deactivated(account_id: str) -> bool:
    return await deactivated_since(account_id) is not None


async def deactivated_ids() -> set[str]:
    async with get_session() as s:
        rows = (await s.execute(
            select(AccountHealth.account_id)
            .where(AccountHealth.deactivated_at.isnot(None))
        )).all()
    return {r[0] for r in rows}


async def deactivate(account_id: str) -> bool:
    async with get_session() as s:
        row = (await s.execute(
            select(AccountHealth).where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()
        if row is not None and row.deactivated_at is not None:
            return False
        if row is None:
            s.add(AccountHealth(account_id=account_id, deactivated_at=datetime.utcnow()))
        else:
            row.deactivated_at = datetime.utcnow()
        _announce(s, "account_active", account_id, active=False)
    global _writes_off
    _writes_off = _writes_off | {account_id}
    return True


async def activate(account_id: str) -> datetime | None:
    async with get_session() as s:
        row = (await s.execute(
            select(AccountHealth).where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()
        if row is None or row.deactivated_at is None:
            return None
        since = row.deactivated_at
        row.deactivated_at = None
        _announce(s, "account_active", account_id, active=True)
    global _writes_off
    _writes_off = _writes_off - {account_id}
    return since


@dataclass(frozen=True, slots=True)
class DeadSession:

    at: str | None = None
    reason: str | None = None


# Typed row, not dict: a mistyped key would render a paused account as healthy.
NO_DEAD_SESSION = DeadSession()


async def dead_session_map() -> dict[str, DeadSession]:
    async with get_session() as s:
        rows = (await s.execute(
            select(
                AccountHealth.account_id,
                AccountHealth.session_dead_at,
                AccountHealth.session_dead_reason,
            )
            .where(AccountHealth.session_dead_at.isnot(None))
        )).all()
    return {
        aid: DeadSession(at=dead_at.isoformat() + "Z", reason=reason)
        for aid, dead_at, reason in rows
    }


# Widening ladder: probing weeks-dead sessions every base interval is pointless; a re-capture clears the flag directly.
_PROBE_BACKOFF: tuple[tuple[timedelta, int], ...] = (
    (timedelta(hours=1), 1),
    (timedelta(days=1), 3),
    (timedelta(days=7), 6),
    (timedelta.max, 36),
)


def probe_interval_s(base_interval_s: int, dead_for: timedelta) -> int:
    return base_interval_s * next(
        mult for horizon, mult in _PROBE_BACKOFF if dead_for < horizon
    )


async def due_probe_ids(base_interval_s: int) -> list[str]:
    now = datetime.utcnow()
    async with get_session() as s:
        rows = (await s.execute(
            select(
                AccountHealth.account_id,
                AccountHealth.session_dead_at,
                AccountHealth.last_probe_at,
            )
            .where(AccountHealth.session_dead_at.isnot(None))
            # A deactivated Creator gets no OF call at all, the probe included.
            .where(AccountHealth.deactivated_at.is_(None))
        )).all()
    due: list[str] = []
    for aid, dead_at, last_probe in rows:
        if last_probe is None:
            due.append(aid)
            continue
        wait_s = probe_interval_s(base_interval_s, now - dead_at)
        if (now - last_probe).total_seconds() >= wait_s:
            due.append(aid)
    return due


async def stamp_probe(account_id: str) -> None:
    async with get_session() as s:
        await s.execute(
            update(AccountHealth)
            .where(AccountHealth.account_id == account_id)
            .values(last_probe_at=datetime.utcnow())
        )
