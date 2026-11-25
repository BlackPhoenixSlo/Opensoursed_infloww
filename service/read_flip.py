from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import relay_cache

log = logging.getLogger("relay.read_flip")


def landed(result: Any) -> bool:
    return not (isinstance(result, dict) and result.get("success") is False)


def acked_fans(result: Any) -> list[int] | None:
    if not (isinstance(result, dict) and result.get("partial")):
        return None
    return [int(f) for f in result.get("acked_fan_ids") or [] if str(f).lstrip("-").isdigit()]


async def set_local_unread(account_id: str, *, fan_id: int | None, value: int, at: int | None = None) -> None:
    try:
        from datetime import datetime
        from db.engine import get_session as _gs
        from db.models import Chat as _Chat, Fan as _Fan
        from sqlalchemy import exists as _exists, update as _update
        async with _gs() as s:
            stmt = _update(_Chat).where(_Chat.account_id == account_id).values(unread_count=value)
            if fan_id is not None:
                stmt = stmt.where(_Chat.fan_id == fan_id)
            if value == 0 and at is not None:
                cut = datetime.utcfromtimestamp(at / 1000)
                stmt = stmt.where(~_exists().where(
                    _Fan.account_id == _Chat.account_id, _Fan.fan_id == _Chat.fan_id,
                    _Fan.last_message_received_at > cut))
            await s.execute(stmt)
            await s.commit()
    except Exception:
        log.warning("set_local_unread(%s, fan=%s) failed — best-effort", account_id, fan_id,
                    exc_info=True)


def bust_chat_list_and_badges(aid: str, chat_id: int | None = None) -> None:
    # A WS-driven bust may lag or never come: bust here so TTL'd caches do not serve the pre-write snapshot.
    try:
        relay_cache.invalidate("list_chats", aid)
        relay_cache.invalidate("roster_count", aid)
        match = None if chat_id is None else (lambda ex, c=int(chat_id): ex == (c,))
        relay_cache.invalidate("get_chat", aid, match=match)
    except Exception:  # noqa: BLE001
        log.warning("chat list bust failed (account=%s chat=%s)", aid, chat_id, exc_info=True)


def now_ms() -> int:
    return int(time.time() * 1000)


async def write(aid: str, fan_id: int | None, call: Callable[[], Any], *,
                only_if_unread: bool = False) -> tuple[Any, int]:
    import badge_reads  # noqa: PLC0415 — deferred: badge_reads imports this module
    at = now_ms()
    intent = badge_reads.record_intent(aid, fan_id, at=at, only_if_unread=only_if_unread)
    try:
        result = await asyncio.to_thread(call)
    except BaseException:
        badge_reads.retire(intent)
        raise
    (badge_reads.landed if landed(result) else badge_reads.retire)(intent)
    return result, at


def publish(aid: str, fan_id: int | None, unread: int, at: int | None = None) -> None:
    try:
        import events  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
        fid = "all" if fan_id is None else events.js_safe_id(int(fan_id))
        events.publish({"chat_read_changed": {"fan_id": fid, "unread": unread,
                                              "at": at if at is not None else now_ms()},
                        "__account_id": str(aid)})
    except Exception:  # noqa: BLE001
        log.warning("chat_read_changed publish failed (account=%s fan=%s)", aid, fan_id, exc_info=True)


def after_reply(aid: str, fan_id: int, at: int) -> None:
    import badge_reads
    import unread_total

    unread_total.on_reply(aid, fan_id, at)
    badge_reads.on_reply(aid, fan_id, at)
    if not unread_total.ENABLED:
        return
    import accounts_admin_api
    import unread_total_decide as utd

    me = accounts_admin_api.amber_creator_id(aid)
    _apply_amber_arrival(aid, fan_id, utd.ECHO, at,
                         None if me is None else lambda row: utd.reply_row(row, me, at))


def _apply_amber_arrival(aid: str, fan: int, kind: str, at: int,
                         row_change: Callable[[dict], dict] | None) -> None:
    try:
        import accounts_admin_api
        import badge_reads
        import unread_total_decide as utd

        badge_reads.note_arrival(aid, fan, kind, at)
        if row_change is None:
            return
        arrivals = badge_reads.arrivals(aid).get(fan, {})
        if max(arrivals.items(), key=utd.arrival_order, default=None) == (kind, at):
            accounts_admin_api.patch_window(aid, {fan: row_change})
        accounts_admin_api.amber_refresh(aid)
    except Exception:
        log.warning("amber move failed account=%s fan=%s kind=%s", aid, fan, kind, exc_info=True)


def _move_unread_total(aid: str, fan_id: int | None, unread: int, at: int | None) -> None:
    import unread_total  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
    unread_total.on_read_flip(aid, fan_id, unread, at)


def _move_amber(aid: str, fan_id: int | None, unread: int, at: int | None) -> None:
    import unread_total  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
    if not unread_total.ENABLED or fan_id is None:
        return
    import unread_total_decide as utd

    flip_at = at if at is not None else unread_total._clock()
    kind = utd.UNREAD if unread else utd.READ
    _apply_amber_arrival(aid, fan_id, kind, flip_at, lambda row: utd.unread_row(row, unread))


async def after_write(aid: str, fan_id: int | None, unread: int, result: Any, *, at: int | None = None) -> bool:
    import badge_reads  # noqa: PLC0415 — deferred: badge_reads imports this module
    if not landed(result):
        log.info("read flip not landed account=%s fan=%s unread=%s result=%r", aid, fan_id, unread, result)
        return False
    acked = acked_fans(result) if fan_id is None else None
    for fid in ([fan_id] if acked is None else acked):
        await set_local_unread(aid, fan_id=fid, value=unread, at=at)
        # Before the bust: unread_total and Amber read/patch the cached window it drops.
        _move_unread_total(aid, fid, unread, at)
        badge_reads.on_read_flip(aid, fid, unread, at)
        _move_amber(aid, fid, unread, at)
        bust_chat_list_and_badges(aid, fid)
        publish(aid, fid, unread, at)
    if acked is not None:
        log.info("read flip partial account=%s acked=%d result=%r", aid, len(acked), result)
    return acked is None
