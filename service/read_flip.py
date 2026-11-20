"""What follows a read flip that landed on the platform (mark read / unread / mark all read), for
the relay's routes (server.of_mark_chat_read & co) and the automations that mark a chat read after
their reply (full_ai_live, welcome_chatter_for_info): the local `chats.unread_count` mirror, the
cached chat window + roster badges + chat detail dropped, and `chat_read_changed` to every tab of
the Creator. One path, so an automation's read clears the badge exactly as a chatter's does.

In-process only (relay_cache, events): the automations run on the relay's loop
(server.py starts automation_executor's supervisor as a task). Best-effort throughout: the write
already landed, nothing here may fail it."""
from __future__ import annotations

import logging
import time
from typing import Any

import relay_cache

log = logging.getLogger("relay.read_flip")


def landed(result: Any) -> bool:
    """Whether a read write's answer is a success. A non-2xx raises in the clients; the Fansly shim
    answers a rejected ack 200-style `{"success": False, "reason": "ack_rejected"}` without raising."""
    return not (isinstance(result, dict) and result.get("success") is False)


async def set_local_unread(account_id: str, *, fan_id: int | None, value: int) -> None:
    """Mirror an OF read-state change into local `chats.unread_count` so the roster
    badge (a local aggregate) updates immediately instead of waiting for the next
    /chats reconcile. fan_id=None → every chat on the account (bulk mark-all-read).
    Best-effort: own session, swallows errors."""
    try:
        from db.engine import get_session as _gs
        from db.models import Chat as _Chat
        from sqlalchemy import update as _update
        async with _gs() as s:
            stmt = _update(_Chat).where(_Chat.account_id == account_id).values(unread_count=value)
            if fan_id is not None:
                stmt = stmt.where(_Chat.fan_id == fan_id)
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


def publish(aid: str, fan_id: int | None, unread: int, at: int | None = None) -> None:
    """`chat_read_changed {fan_id | "all", unread 0/1, at epoch ms}` once a read flip landed on OF, so every tab that
    can see the Creator (any-scope) flips the row in its cached chat lists without a re-read (app
    hooks/useAccountStateEvents.ts): another chatter's open list kept the old unread flag until it refetched.
    Best-effort: the write already landed."""
    try:
        import events  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
        events.publish({"chat_read_changed": {"fan_id": "all" if fan_id is None else int(fan_id), "unread": unread,
                                              "at": at if at is not None else now_ms()},
                        "__account_id": str(aid)})
    except Exception:  # noqa: BLE001
        log.warning("chat_read_changed publish failed (account=%s fan=%s)", aid, fan_id, exc_info=True)


def _move_unread_total(aid: str, fan_id: int | None, unread: int, at: int | None) -> None:
    """unread_total.on_read_flip (Knob off: returns at once), before the bust: it peeks the held row."""
    try:
        import unread_total  # noqa: PLC0415 — deferred: keeps this module's import light for the automations
        unread_total.on_read_flip(aid, fan_id, unread, at)
    except Exception:  # noqa: BLE001
        log.warning("unread total move failed (account=%s fan=%s)", aid, fan_id, exc_info=True)


async def after_write(aid: str, fan_id: int | None, unread: int, result: Any, *, set_local: bool = True,
                      at: int | None = None) -> bool:
    """After a read write answered `result` (fan_id None: every chat): when it landed (`landed`), set the
    local unread to `unread` (unless `set_local` is False: the caller already did), move the Unread total
    (unread_total.on_read_flip, from the held row, so before the bust), drop the cached chat list / badges /
    detail, publish `chat_read_changed` stamped `at` (`now_ms()` taken before the write); True. Not landed: nothing,
    False."""
    if not landed(result):
        log.info("read flip not landed account=%s fan=%s unread=%s result=%r", aid, fan_id, unread, result)
        return False
    if set_local:
        await set_local_unread(aid, fan_id=fan_id, value=unread)
    _move_unread_total(aid, fan_id, unread, at)
    bust_chat_list_and_badges(aid, fan_id)
    publish(aid, fan_id, unread, at)
    return True
