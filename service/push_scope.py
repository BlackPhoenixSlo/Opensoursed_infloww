from __future__ import annotations

import asyncio
import time
from datetime import datetime

CACHE_TTL_S = 60.0

_cache: dict[tuple[str, str, int], tuple[float, frozenset | None]] = {}
_live: tuple[float, frozenset] | None = None
_gen = 0
_walk: asyncio.Task | None = None


def clear() -> None:
    global _live, _gen, _walk
    _gen += 1
    _cache.clear()
    _live = None
    _walk = None


async def live_accounts() -> frozenset:
    global _walk
    hit = _live
    if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    loop = asyncio.get_running_loop()
    if _walk is None or _walk.done() or _walk.get_loop() is not loop:
        _walk = loop.create_task(_load_live(_gen))
    return await asyncio.shield(_walk)


async def _load_live(gen: int) -> frozenset:
    global _live, _walk
    try:
        import account_health
        import accounts as registry
        now = time.monotonic()
        off = await account_health.deactivated_ids()
        rows = await asyncio.to_thread(registry.list_accounts)
        live = frozenset(str(a["id"]) for a in rows if a.get("has_session") and str(a.get("id")) not in off)
        if gen == _gen:
            _live = (now, live)
        return live
    finally:
        if _walk is asyncio.current_task():
            _walk = None


async def accounts_for(kind: str, principal_id: str, issued_ms: int) -> frozenset | None:
    key = (kind, principal_id, int(issued_ms))
    hit = _cache.get(key)
    now, gen = time.monotonic(), _gen
    if hit is not None and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    accounts = await (_owner if kind == "user" else _chatter)(principal_id, int(issued_ms))
    if accounts is not None:
        accounts = accounts & await live_accounts()
    if len(_cache) > 10_000:
        _cache.clear()
    if gen == _gen:
        # Single loop thread: no await between check and write; a clear() during the read drops this write so a racing unassign never pins the old scope.
        _cache[key] = (now, accounts)
    return accounts


def _alive(issued: int, valid_after: datetime | None, last_seen: datetime | None, max_idle_s: float) -> bool:
    from session_stamps import session_verdict
    if last_seen is None:
        return False
    return session_verdict(issued, valid_after, last_seen, datetime.utcnow(),
                           # Read-only: touch is never reached, so a push never extends a session.
                           max_idle_s=max_idle_s, touch_s=float("inf")) != "expired"


async def _owner(user_id: str, issued: int) -> frozenset | None:
    import auth
    from sqlalchemy import select
    from db.engine import get_session
    from db.models import User
    async with get_session() as s:
        row = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if row is None or not _alive(issued, row.sessions_valid_after, row.last_seen_at,
                                     auth.SESSION_INACTIVITY_SECONDS):
            return None
        return await auth.account_ids_for(s, user_id, bool(getattr(row, "is_admin", False)))


async def _chatter(chatter_id: str, issued: int) -> frozenset | None:
    import chatter_identity_cache
    import chatters
    entry = chatter_identity_cache.get(chatter_id) or await chatters.load_identity(chatter_id)
    if entry is None or not _alive(issued, entry.sessions_valid_after, entry.last_seen_at,
                                   chatters.SESSION_INACTIVITY_SECONDS):
        return None
    return entry.identity.account_ids
