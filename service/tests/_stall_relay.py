from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from fastapi import Query  # noqa: E402

import server  # noqa: E402
import split_inbox  # noqa: E402
from auth import clamp_account_filter  # noqa: E402
from events import js_safe_id  # noqa: E402


async def _pre_fix_chats_recent(
    limit: int = Query(25, ge=1, le=100),
    account_id: str | None = Query(None),
) -> dict[str, Any]:
    from db.engine import get_session
    from db.models import Chat as _Chat, Fan as _Fan
    from sqlalchemy import select
    account_ids = clamp_account_filter(account_id)
    async with get_session() as s:
        stmt = (
            select(_Chat, _Fan)
            .join(_Fan, (_Fan.account_id == _Chat.account_id) & (_Fan.fan_id == _Chat.fan_id), isouter=True)
            .where(_Chat.hidden_locally == False)  # noqa: E712
            .order_by(_Chat.last_message_at.desc().nullslast())
            .limit(limit)
        )
        if account_ids is not None:
            if not account_ids:
                return {"list": [], "source": "local-db"}
            stmt = stmt.where(_Chat.account_id.in_(account_ids))
        rows = (await s.execute(stmt)).all()
        out: list[dict[str, Any]] = []
        for chat, fan in rows:
            out.append({
                "__accountId": chat.account_id,
                "withUser": {
                    "id": js_safe_id(chat.fan_id),
                    "name": fan.of_display_name if fan else None,
                    "username": fan.of_username if fan else None,
                    "avatar": fan.avatar_url if fan else None,
                },
                "lastMessage": {
                    "id": js_safe_id(chat.last_message_id),
                    "text": chat.last_message_preview or "",
                    "createdAt": chat.last_message_at.isoformat() + "Z" if chat.last_message_at else None,
                } if chat.last_message_id else None,
                "hasUnread": (chat.unread_count or 0) > 0,
                "unreadMessagesCount": chat.unread_count or 0,
                "isMutedNotifications": bool(fan.is_muted) if fan else False,
            })
    chatter_id = split_inbox.acting_chatter_id()
    if chatter_id is not None:
        keeps = {aid: await split_inbox.filter_for(chatter_id, aid) for aid in {r["__accountId"] for r in out}}
        out = [r for r in out if (k := keeps[r["__accountId"]]) is None or k(r["withUser"]["id"])]
    return {"list": out, "source": "local-db"}


def install_pre_fix() -> None:
    routes = server.app.router.routes
    [old] = [r for r in routes if getattr(r, "path", None) == "/admin/chats/recent"]
    at = routes.index(old)
    routes.remove(old)
    server.app.get("/admin/chats/recent")(_pre_fix_chats_recent)
    routes.insert(at, routes.pop())


if __name__ == "__main__":
    if "--mutant" in sys.argv:
        install_pre_fix()
    uvicorn.run(server.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
