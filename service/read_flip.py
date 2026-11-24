"""What follows a read flip that landed on the platform (mark read / unread / mark all read), for
the relay's routes (server.of_mark_chat_read & co) and the automations that mark a chat read after
their reply (full_ai_live, welcome_chatter_for_info): the local `chats.unread_count` mirror, the
cached chat window + roster badges + chat detail dropped, and `chat_read_changed` to every tab of
the Creator. One path, so an automation's read clears the badge exactly as a chatter's does.

In-process only (relay_cache, events): the automations run on the relay's loop
(server.py starts automation_executor's supervisor as a task). Best-effort throughout: the write
already landed, nothing here may fail it."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import relay_cache

log = logging.getLogger("relay.read_flip")


def landed(result: Any) -> bool:
    """Whether a read write's answer is a success. A non-2xx raises in the clients; the Fansly shim
    answers a write it could not complete 200-style `{"success": False, "reason": ...}` without raising."""
    return not (isinstance(result, dict) and result.get("success") is False)


def acked_fans(result: Any) -> list[int] | None:
    """The fans a partial mark-all cleared (the Fansly shim's `{"partial": True, "acked_fan_ids": [...]}`:
    capped, a failed scan, a backlog past the scan; ids as strings), or None for a whole answer."""
    if not (isinstance(result, dict) and result.get("partial")):
        return None
    return [int(f) for f in result.get("acked_fan_ids") or [] if str(f).lstrip("-").isdigit()]


async def set_local_unread(account_id: str, *, fan_id: int | None, value: int, at: int | None = None) -> None:
    """Mirror an OF read-state change into local `chats.unread_count` so the roster
    badge (a local aggregate) updates immediately instead of waiting for the next
    /chats reconcile. fan_id=None → every chat on the account (bulk mark-all-read).
    A read (value 0) stamped `at` (epoch ms, taken before the write) leaves a chat
    whose fan's last inbound message (`fans.last_message_received_at`) is newer:
    that DM committed while the write was in flight, and its unread stands.
    Best-effort: own session, swallows errors."""
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
    """Drop the account's cached chat window AND its roster badge counts, after
    any OF write that changes the cached chat window or roster-badge counts.
    A WS-driven bust may lag the response or never come, and without this
    both would serve the pre-write snapshot for their TTL. Also the chat's
    cached detail (`chat_id`; None: every chat of the account). Never raises."""
    try:
        relay_cache.invalidate("list_chats", aid)
        relay_cache.invalidate("roster_count", aid)
        match = None if chat_id is None else (lambda ex, c=int(chat_id): ex == (c,))
        relay_cache.invalidate("get_chat", aid, match=match)
    except Exception:  # noqa: BLE001
        log.warning("chat list bust failed (account=%s chat=%s)", aid, chat_id, exc_info=True)


def now_ms() -> int:
    """A read flip's `at`: taken BEFORE the platform write, so a fan message landing while the
    write is in flight is newer than the flip and keeps its unread flag in every tab."""
    return int(time.time() * 1000)


async def write(aid: str, fan_id: int | None, call: Callable[[], Any], *,
                only_if_unread: bool = False) -> tuple[Any, int]:
    """`(call()'s answer, at)` for a read-state write of ours (read, unread, mark all, mute; fan None: every chat),
    run in a thread, `at` = `now_ms()` before it. Its Write intent is recorded first (badge_reads: the counter frame
    it causes, which can beat the response, costs no read), stamped at the response when it `landed`, retired at
    once when not or when the call raises or is cancelled. `only_if_unread`: none when the held row shows him read."""
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
    """`chat_read_changed {fan_id | "all", unread 0/1, at epoch ms}` once a read flip landed on OF (a fan id past 2^53,
    a Fansly snowflake, as a string: a JSON number that big reaches the browser rounded), so every tab that
    can see the Creator (any-scope) flips the row in its cached chat lists without a re-read (app
    hooks/useAccountStateEvents.ts): another chatter's open list kept the old unread flag until it refetched.
    Best-effort: the write already landed."""
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
    """unread_total.on_read_flip (Knob off: returns at once; never raises), before the bust: it peeks the held row."""
    import unread_total  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
    unread_total.on_read_flip(aid, fan_id, unread, at)


def _move_amber(aid: str, fan_id: int | None, unread: int, at: int | None) -> None:
    """The Amber circle (creator-badges 0F) before the bust drops the window it folds: the fan's held row takes the
    flip, then `amber_refresh`. Mark all: the next window read moves it. Knob off: nothing. Never raises."""
    import unread_total  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
    if not unread_total.ENABLED or fan_id is None:
        return
    import unread_total_decide as utd

    flip_at = at if at is not None else unread_total._clock()
    kind = utd.UNREAD if unread else utd.READ
    _apply_amber_arrival(aid, fan_id, kind, flip_at, lambda row: utd.unread_row(row, unread))


async def after_write(aid: str, fan_id: int | None, unread: int, result: Any, *, at: int | None = None) -> bool:
    """After a read write answered `result` (fan_id None: every chat), never before it: when it landed
    (`landed`), set the local unread to `unread` (a read fenced by `at`: set_local_unread), move the Unread
    total (unread_total.on_read_flip, from the held row, so before the bust) and the Amber circle, drop the cached chat list /
    badges / detail, publish `chat_read_changed`
    stamped `at` (`now_ms()` taken before the write); True. A partial mark-all (`acked_fans`) does that for
    each acked fan alone, never `"all"`, and answers False. Not landed: nothing, False."""
    import badge_reads  # noqa: PLC0415 — deferred: badge_reads imports this module
    if not landed(result):
        log.info("read flip not landed account=%s fan=%s unread=%s result=%r", aid, fan_id, unread, result)
        return False
    acked = acked_fans(result) if fan_id is None else None
    for fid in ([fan_id] if acked is None else acked):
        await set_local_unread(aid, fan_id=fid, value=unread, at=at)
        _move_unread_total(aid, fid, unread, at)
        badge_reads.on_read_flip(aid, fid, unread, at)
        _move_amber(aid, fid, unread, at)
        bust_chat_list_and_badges(aid, fid)
        publish(aid, fid, unread, at)
    if acked is not None:
        log.info("read flip partial account=%s acked=%d result=%r", aid, len(acked), result)
    return acked is None
