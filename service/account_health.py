"""service/account_health.py — per-account OF session health.

When OF rejects an account's stored session with "Wrong user." (the creator
got logged out / the login was re-linked elsewhere), EVERY authenticated call
for that account fails until a human re-captures the session. Letting the
automations keep firing against a dead session burns run slots, OF-proxy
round-trips and LLM spend for zero delivery — so the account is paused
wholesale instead:

  • `mark_session_dead()` flags the account. Called from the executor's
    run_once failure path (an automation hit the signature) and from
    server._persist_unhandled_errors (a UI-originated OF call hit it).
  • `automation_executor.run_once` SKIPS every run for a flagged account —
    pending jobs stay parked and resume untouched once the flag clears.
  • The executor re-probes each flagged account with a fresh-from-disk
    `client.me()` on a WIDENING schedule (see `probe_interval_s`); the first
    success clears the flag.
  • A session re-capture (`POST /admin/session/bootstrap`) clears the flag
    immediately — no waiting for the next probe.
  • Newly flagging an account files one `session_dead` agency notification
    per owner of it (notifications_api.notify_session_dead).

The same row carries the owner's Creator deactivate switch (`deactivated_at`,
see "Deactivation" below), which pauses the same loops on purpose.

Kept in its own tiny module so BOTH server.py and automation_executor.py can
import it without a circular import (same reasoning as automation_registry.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update

from db.engine import get_session
from db.models import AccountHealth

log = logging.getLogger("of-relay.account-health")


def is_session_dead_error(exc: BaseException) -> str | None:
    """Classify `exc`: a short reason string when it definitely means "this
    account has no working session", else None.

    Deliberately STRICT — only two signatures flag an account:
      • OF's unlink rejection: HTTP 400 +
        `{"error":{"code":301,"message":"Wrong user."}}` → "wrong_user"
      • `OFClient.from_account`'s FileNotFoundError ("has no captured
        session") — the session dir is missing entirely, e.g. the account
        was deleted or never captured on this host → "no_session"
    Transient 429s / 5xx / signing hiccups must never pause a healthy account;
    they already have retry paths of their own."""
    from of_client import OFAPIError  # lazy — keep this module import-light

    if isinstance(exc, OFAPIError) and "Wrong user" in str(exc):
        return "wrong_user"
    if isinstance(exc, FileNotFoundError) and "no captured session" in str(exc):
        return "no_session"
    return None


async def is_session_dead(account_id: str) -> bool:
    """True while the account's session is flagged dead (automations pause)."""
    async with get_session() as s:
        dead_at = (await s.execute(
            select(AccountHealth.session_dead_at)
            .where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()
    return dead_at is not None


async def mark_session_dead(account_id: str, reason: str) -> bool:
    """Flag the account's session as dead. Returns True only when this call
    NEWLY flagged it (was healthy before) so callers can log the transition
    once instead of on every subsequent failure."""
    now = datetime.utcnow()
    async with get_session() as s:
        row = (await s.execute(
            select(AccountHealth).where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()
        newly = row is None or row.session_dead_at is None
        if row is None:
            s.add(AccountHealth(
                account_id=account_id,
                session_dead_at=now,
                session_dead_reason=reason,
            ))
        else:
            if newly:
                row.session_dead_at = now
                row.last_probe_at = None
            row.session_dead_reason = reason
        if newly:
            _announce(s, "session_dead", account_id, dead=True, reason=reason)
    if newly:
        from notifications_api import notify_session_dead  # lazy — keep this module import-light
        await notify_session_dead(account_id, reason, now)
    return newly


async def clear_session_dead(account_id: str) -> bool:
    """Unflag the account (session verified working again). Returns True if
    it was flagged."""
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
    """An account-state SSE event once `s` commits (events.STATE_TYPES), so an
    open tab badges or un-badges the account without its next poll."""
    import events  # lazy — keep this module import-light
    events.on_commit(s, event_type, account_id=account_id, **fields)


# ── Deactivation (Creators › ⋮ › Deactivate) ────────────────────────────
# The owner's switch, not a health verdict, but it gates the same loops the
# dead-session flag does and lives on the same row. Every background loop that
# walks the roster (WS pumps, ledger polls, the chat-link seed, the automation
# executor, the link-metrics prewarm, the daily OF stats, the referrals read)
# skips a deactivated Creator, and OFClient refuses any write for it (the
# mirror below); every LISTING still returns it, stamped
# `is_active=False`, so analytics, grants and history keep their rows.

# The switch's in-process mirror, for the one gate that cannot await the
# database: OFClient._http_call (it runs in worker threads) refuses every OF
# write for a Creator in it, whichever route or job asked. One process serves
# everything (scripts/start.sh): load_write_gate() fills it once at startup, and
# deactivate/activate are its only other writers.
_writes_off: frozenset[str] = frozenset()


def refuses_writes(account_id: str) -> bool:
    """True while the Creator is deactivated, as of the mirror above."""
    return str(account_id) in _writes_off


async def load_write_gate() -> None:
    """Fill the mirror from the rows, once, at startup."""
    global _writes_off
    _writes_off = frozenset(await deactivated_ids())


async def deactivated_since(account_id: str) -> datetime | None:
    """When the owner deactivated the Creator; None while it is active."""
    async with get_session() as s:
        return (await s.execute(
            select(AccountHealth.deactivated_at)
            .where(AccountHealth.account_id == account_id)
        )).scalar_one_or_none()


async def is_deactivated(account_id: str) -> bool:
    """True while the owner has the Creator deactivated."""
    return await deactivated_since(account_id) is not None


async def deactivated_ids() -> set[str]:
    """Every deactivated Creator — the set the roster loops subtract."""
    async with get_session() as s:
        rows = (await s.execute(
            select(AccountHealth.account_id)
            .where(AccountHealth.deactivated_at.isnot(None))
        )).all()
    return {r[0] for r in rows}


async def deactivate(account_id: str) -> bool:
    """Stamp the Creator deactivated. True only when it was active before."""
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
    """Clear the deactivation. Returns when it had been deactivated (the gap
    the caller may need to backfill), None when it was already active."""
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
    """Since when an account's automations have been paused, and why.

    A typed row rather than a loose dict because BOTH account-listing endpoints
    copy these two fields onto their own shape: a mistyped string key there would
    silently render a paused account as healthy, which is the exact failure this
    whole surface exists to prevent."""

    at: str | None = None       # ISO-Z instant it was flagged
    reason: str | None = None   # "wrong_user" | "no_session"


# Null object for "this account is fine" (same idiom as _daylog.NO_DAY), so a
# listing endpoint stamps its two fields unconditionally instead of branching on
# presence at every call site.
NO_DEAD_SESSION = DeadSession()


async def dead_session_map() -> dict[str, DeadSession]:
    """account_id → DeadSession, for every FLAGGED account (healthy accounts are
    absent — callers should fall back to NO_DEAD_SESSION). The account listings
    stamp this onto their rows so the UI can badge the account "unlinked", and
    say which repair it needs, instead of it merely LOOKING idle next to accounts
    that are genuinely working."""
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


# Recovery-probe backoff: (this account has been dead LESS than, probe every N
# base intervals). Expressed as MULTIPLES of the executor's base interval so
# there stays exactly one knob, and closed with an unbounded final rung so the
# lookup is total — every age hits a row.
#
# A session that died a minute ago is worth re-checking often: the creator may
# be re-linking right now. One that died three weeks ago is not — probing it
# every 10 minutes forever is ~4k pointless authenticated OF calls a month per
# account, every one of them failing.
#
# This IS a real trade: the probe's whole job is catching a session that starts
# working again on its own, and past a week this finds it up to 6h late instead
# of 10min. That is affordable only because it is not the path a human uses — a
# re-capture (`POST /admin/session/bootstrap`) calls clear_session_dead directly
# and resumes automations on the next tick, whatever this ladder says.
_PROBE_BACKOFF: tuple[tuple[timedelta, int], ...] = (
    (timedelta(hours=1), 1),   # first hour   — every base interval (10 min)
    (timedelta(days=1), 3),    # first day    — every 30 min
    (timedelta(days=7), 6),    # first week   — hourly
    (timedelta.max, 36),       # older        — every 6 hours
)


def probe_interval_s(base_interval_s: int, dead_for: timedelta) -> int:
    """Seconds to wait between recovery probes for an account flagged
    `dead_for` ago. Widens with age and never drops below `base_interval_s`
    (a negative `dead_for` from clock skew lands in the first rung)."""
    return base_interval_s * next(
        mult for horizon, mult in _PROBE_BACKOFF if dead_for < horizon
    )


async def due_probe_ids(base_interval_s: int) -> list[str]:
    """Flagged accounts due a recovery probe — never probed, or last probed
    longer ago than their backoff interval. Filtered in Python rather than SQL
    because the per-row interval depends on `session_dead_at` (a CASE over
    julianday() arithmetic would be far less readable), and the flagged set is
    inherently small — it is bounded by the number of broken accounts."""
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
    """Record that a recovery probe ran now (rate-limits the next one)."""
    async with get_session() as s:
        await s.execute(
            update(AccountHealth)
            .where(AccountHealth.account_id == account_id)
            .values(last_probe_at=datetime.utcnow())
        )
