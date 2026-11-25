from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Iterable

from sqlalchemy import select

MAX_GROUPS = 9

_configs: dict[str, dict[str, Any]] = {}
_generations: dict[str, int] = {}
_save_locks: dict[str, asyncio.Lock] = {}


def save_lock(account_id: str) -> asyncio.Lock:
    return _save_locks.setdefault(account_id, asyncio.Lock())


def unset() -> dict[str, Any]:
    return {"group_count": 1, "assignments": {}, "chatter_groups": {}}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def clean(cfg: dict) -> dict[str, Any]:
    n = cfg.get("group_count")
    if not _is_int(n) or not 1 <= n <= MAX_GROUPS:
        raise ValueError(f"group_count must be an integer from 1 to {MAX_GROUPS}")
    out: dict[str, Any] = {"group_count": n}
    for key in ("assignments", "chatter_groups"):
        raw = cfg.get(key, {})
        if not isinstance(raw, dict):
            raise ValueError(f"{key} must be an object")
        out[key] = {str(k): g for k, g in raw.items() if _is_int(g) and 1 <= g <= n}
    return out


def parse(raw: str | None) -> dict[str, Any]:
    if not raw:
        return unset()
    try:
        return clean(json.loads(raw))
    except Exception:
        return unset()


def group_of(fan_id: Any, cfg: dict[str, Any]) -> int:
    n = cfg["group_count"]
    sid = str(fan_id)
    moved = cfg["assignments"].get(sid)
    if _is_int(moved) and 1 <= moved <= n:
        return moved
    if sid.isascii() and sid.isdigit():
        return int(sid) % n + 1
    return 1


def bound_group(cfg: dict[str, Any], chatter_id: str) -> int | None:
    if cfg["group_count"] <= 1:
        return None
    return cfg["chatter_groups"].get(str(chatter_id))


def generation(account_id: str) -> int:
    return _generations.get(str(account_id), 0)


def remember(account_id: str, cfg: dict[str, Any]) -> None:
    aid = str(account_id)
    _configs[aid] = cfg
    _generations[aid] = generation(aid) + 1


def heal(account_id: str, cfg: dict[str, Any], *, since: int) -> dict[str, Any]:
    aid = str(account_id)
    if generation(aid) == since:
        _configs[aid] = cfg
    return _configs[aid]


async def warm(account_ids: Iterable[str]) -> None:
    from db.engine import get_session
    from db.models import AccountAiConfig
    missing = [str(a) for a in account_ids if str(a) not in _configs]
    if not missing:
        return
    async with get_session() as s:
        rows = dict((await s.execute(
            select(AccountAiConfig.account_id, AccountAiConfig.split_inbox_json)
            .where(AccountAiConfig.account_id.in_(missing))
        )).all())
    for aid in missing:
        _configs.setdefault(aid, parse(rows.get(aid)))


async def config(account_id: str) -> dict[str, Any]:
    await warm([account_id])
    return _configs[str(account_id)]


def bound_cached(chatter_id: str, account_id: Any) -> bool:
    cfg = _configs.get(str(account_id))
    return cfg is not None and bound_group(cfg, chatter_id) is not None


def allows_cached(chatter_id: str, account_id: Any, fan_id: Any) -> bool:
    cfg = _configs.get(str(account_id))
    if cfg is None:
        return True
    g = bound_group(cfg, chatter_id)
    return g is None or group_of(fan_id, cfg) == g


async def filter_for(chatter_id: str | None, account_id: str) -> Callable[[Any], bool] | None:
    if chatter_id is None:
        return None
    cfg = await config(account_id)
    g = bound_group(cfg, chatter_id)
    if g is None:
        return None
    return lambda fan_id: group_of(fan_id, cfg) == g


def acting_chatter_id() -> str | None:
    from chatters import current_actor
    actor = current_actor()
    return actor.id if actor is not None and actor.kind == "chatter" else None


async def chatter_inbox_filter(account_id: str) -> Callable[[Any], bool] | None:
    return await filter_for(acting_chatter_id(), account_id)


def filter_rows(resp: dict[str, Any], keep: Callable[[Any], bool] | None) -> dict[str, Any]:
    if keep is None or not isinstance(resp, dict):
        return resp
    key = "list" if "list" in resp else "chats" if "chats" in resp else "rows" if "rows" in resp else None
    if key is None:
        return resp
    return {**resp, key: [r for r in resp.get(key) or [] if keep((r.get("withUser") or {}).get("id"))]}


def without_count(body: dict, key: str) -> dict:
    return {k: v for k, v in body.items() if k != key} if key in body else body


def without_unread_total(body: dict) -> dict:
    values = body.get("values") or {}
    narrowed = without_count(values, "unread_total")
    return body if narrowed is values else {**body, "values": narrowed}


def narrow(chatter_id: str | None, frame: dict) -> dict | None:
    import events_decide as ed

    if chatter_id is None:
        return frame
    kind = ed.first_key(frame)
    body = frame.get(kind)
    aid = frame.get("__account_id")
    if kind in ("creator_refreshed", "creator_warmed") and isinstance(body, dict):
        aid = aid or body.get("account_id")
        if aid is None or not bound_cached(chatter_id, aid):
            return frame
        narrowed = without_unread_total(body) if kind == "creator_refreshed" else without_count(body, "roster")
        return frame if narrowed is body else {**frame, kind: narrowed}
    if kind == "toasts" and isinstance(body, list):
        kept = [toast for toast in body if (fan := ed.toast_fan_id(toast)) is None
                or allows_cached(chatter_id, aid, fan)]
        if len(kept) == len(body):
            return frame
        return {**frame, kind: kept} if kept else None
    fan = ed.frame_fan_id(frame)
    return frame if fan is None or allows_cached(chatter_id, aid, fan) else None
