from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable

from sqlalchemy import String, and_, case, func, or_, select, type_coerce

MAX_GROUPS = 9
DEFAULT_TAB = "split_inbox_default"

_configs: dict[str, dict[str, Any]] = {}
_generations: dict[str, int] = {}
_inherited: set[str] = set()
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


def apply(cfg: dict[str, Any], edit: dict[str, Any]) -> dict[str, Any]:
    bound = {**cfg["chatter_groups"], **edit["chatter_groups"]}
    return clean({
        "group_count": edit["group_count"] or cfg["group_count"],
        "assignments": {**cfg["assignments"], **edit["assignments"]},
        "chatter_groups": {k: g for k, g in bound.items() if g is not None},
    })


def parse(raw: str | dict | None) -> dict[str, Any]:
    if not raw:
        return unset()
    try:
        return clean(raw if isinstance(raw, dict) else json.loads(raw))
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


_INT64 = (-(2 ** 63), 2 ** 63 - 1)


def group_sql(fan_col: Any, cfg: dict[str, Any]) -> Any:
    # SQLite's INTEGER affinity stores ascii-digit text as INTEGER (REAL past int64): a TEXT id never takes the digit rule.
    n = cfg["group_count"]
    by_group: dict[int, tuple[list[int], list[str]]] = {}
    for key, g in cfg["assignments"].items():
        if not (_is_int(g) and 1 <= g <= n):
            continue
        ints, texts = by_group.setdefault(g, ([], []))
        digits = key.removeprefix("-")
        as_int = int(key) if len(digits) <= 19 and digits.isascii() and digits.isdigit() else None
        if as_int is not None and str(as_int) == key and _INT64[0] <= as_int <= _INT64[1]:
            ints.append(as_int)
        else:
            texts.append(key)
    whens = []
    for g, (ints, texts) in sorted(by_group.items()):
        if ints:
            whens.append((and_(func.typeof(fan_col) == "integer", fan_col.in_(ints)), g))
        if texts:
            whens.append((and_(func.typeof(fan_col) == "text", type_coerce(fan_col, String).in_(texts)), g))
    whens.append((and_(func.typeof(fan_col) == "integer", fan_col >= 0), fan_col % n + 1))
    return case(*whens, else_=1)


def sql_scope(chatter_id: str, account_ids: Iterable[str], account_col: Any, fan_col: Any) -> tuple[Any, tuple] | None:
    open_ids: list[str] = []
    narrowed: dict[str, tuple[dict[str, Any], int, list[str]]] = {}
    for aid in dict.fromkeys(str(a) for a in account_ids):
        cfg = _configs[aid]
        g = bound_group(cfg, chatter_id)
        if g is None:
            open_ids.append(aid)
            continue
        narrowed.setdefault(json.dumps([cfg, g], sort_keys=True), (cfg, g, []))[2].append(aid)
    if not narrowed:
        return None
    parts = [and_(account_col.in_(aids), group_sql(fan_col, cfg) == g) for cfg, g, aids in narrowed.values()]
    if open_ids:
        parts.append(account_col.in_(open_ids))
    return or_(*parts), tuple(sorted((k, tuple(aids)) for k, (_, _, aids) in narrowed.items()))


def bound_group(cfg: dict[str, Any], chatter_id: str) -> int | None:
    if cfg["group_count"] <= 1:
        return None
    return cfg["chatter_groups"].get(str(chatter_id))


def generation(account_id: str) -> int:
    return _generations.get(str(account_id), 0)


def _bump(aid: str) -> int:
    aid = str(aid)
    _generations[aid] = generation(aid) + 1
    return _generations[aid]


def _store(aid: str, cfg: dict[str, Any], inherited: bool) -> None:
    _configs[aid] = cfg
    (_inherited.add if inherited else _inherited.discard)(aid)


def remember(account_id: str, cfg: dict[str, Any], *, inherited: bool = False) -> None:
    aid = str(account_id)
    _store(aid, cfg, inherited)
    _bump(aid)


def heal(account_id: str, cfg: dict[str, Any], *, since: int, inherited: bool = False) -> dict[str, Any]:
    aid = str(account_id)
    if generation(aid) == since:
        _store(aid, cfg, inherited)
    return _configs.get(aid, cfg)


async def granted(chatter_ids: Iterable[str]) -> dict[str, frozenset[str]]:
    from chatters import load_identity
    out: dict[str, frozenset[str]] = {}
    for cid in chatter_ids:
        entry = await load_identity(cid)
        out[cid] = entry.identity.account_ids if entry is not None else frozenset()
    return out


async def _defaults(s, account_ids: list[str]) -> dict[str, dict[str, Any]]:
    from db.models import UserAccount, UserSetting
    owners = (await s.execute(
        select(UserAccount.account_id, UserAccount.user_id).where(UserAccount.account_id.in_(account_ids))
        .order_by(UserAccount.user_id)
    )).all()
    blobs = dict((await s.execute(
        select(UserSetting.user_id, UserSetting.config_json)
        .where(UserSetting.user_id.in_(sorted({uid for _, uid in owners})), UserSetting.tab == DEFAULT_TAB)
    )).all())
    seen: dict[str, dict[str, dict[str, Any]]] = {}
    for aid, uid in owners:
        if uid in blobs:
            d = parse(blobs[uid])
            seen.setdefault(aid, {})[json.dumps(d, sort_keys=True)] = d
    return {aid: next(iter(ds.values())) for aid, ds in seen.items() if len(ds) == 1}


async def resolve(s, account_ids: Iterable[str]) -> dict[str, tuple[dict[str, Any], bool]]:
    from db.models import AccountAiConfig
    ids = list(dict.fromkeys(str(a) for a in account_ids))
    rows = dict((await s.execute(
        select(AccountAiConfig.account_id, AccountAiConfig.split_inbox_json)
        .where(AccountAiConfig.account_id.in_(ids))
    )).all())
    out = {aid: (parse(rows[aid]), False) for aid in ids if rows.get(aid)}
    bare = [aid for aid in ids if aid not in out]
    if not bare:
        return out
    defaults = await _defaults(s, bare)
    for aid in bare:
        out[aid] = (defaults.get(aid, unset()), True)
    return out


def derive_default(configs: dict[str, dict[str, Any]], grants: dict[str, frozenset[str]],
                   fallback_count: int) -> dict[str, Any]:
    counts = {cfg["group_count"] for cfg in configs.values()}
    bound: dict[str, int] = {}
    for cid, may in grants.items():
        seen = {configs[aid]["chatter_groups"].get(cid) for aid in configs if aid in may}
        if len(seen) == 1 and None not in seen:
            bound[cid] = seen.pop()
    return clean({"group_count": counts.pop() if len(counts) == 1 else fallback_count, "chatter_groups": bound})


async def _refresh_inherited(s, account_ids: Iterable[str]) -> None:
    since = {str(aid): _bump(aid) for aid in account_ids}
    stale = [aid for aid in since if aid in _inherited and aid in _configs]
    if not stale:
        return
    try:
        fresh = await resolve(s, stale)
    except BaseException:
        for aid in stale:
            if generation(aid) == since[aid]:
                _configs.pop(aid, None)
                _inherited.discard(aid)
        raise
    for aid, (cfg, inherited) in fresh.items():
        heal(aid, cfg, since=since[aid], inherited=inherited)


async def default_changed(owner_id: str) -> None:
    from db.engine import get_session
    from db.models import UserAccount
    async with get_session() as s:
        ids = (await s.execute(
            select(UserAccount.account_id).where(UserAccount.user_id == owner_id)
        )).scalars().all()
        await _refresh_inherited(s, ids)


async def owner_link_changed(account_id: str) -> None:
    from db.engine import get_session
    try:
        async with get_session() as s:
            await _refresh_inherited(s, [account_id])
    except Exception:
        logging.getLogger(__name__).exception("split inbox owner-link refresh failed account=%s", account_id)


_resolving: dict[tuple, asyncio.Future] = {}


async def _resolve_once(missing: list[str], since: dict[str, int]) -> dict[str, tuple[dict[str, Any], bool]]:
    from db.engine import get_session
    key = (id(asyncio.get_running_loop()), *since.items())
    fut = _resolving.get(key)
    if fut is None:
        async def _go() -> dict[str, tuple[dict[str, Any], bool]]:
            async with get_session() as s:
                return await resolve(s, missing)
        fut = _resolving[key] = asyncio.ensure_future(_go())
        fut.add_done_callback(lambda _: _resolving.pop(key, None))
    return await asyncio.shield(fut)


async def warm(account_ids: Iterable[str]) -> None:
    ids = list(dict.fromkeys(str(a) for a in account_ids))
    while missing := [aid for aid in ids if aid not in _configs]:
        since = {aid: generation(aid) for aid in missing}
        fresh = await _resolve_once(missing, since)
        for aid, (cfg, inherited) in fresh.items():
            if aid not in _configs:
                heal(aid, cfg, since=since[aid], inherited=inherited)


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


@dataclass(frozen=True)
class InboxFilter:
    config: dict[str, Any]
    group: int

    def __call__(self, fan_id: Any) -> bool:
        return group_of(fan_id, self.config) == self.group

    def version(self) -> str:
        effective = self.config["group_count"], self.config["assignments"], self.group
        return sha256(json.dumps(effective, sort_keys=True).encode()).hexdigest()


async def filter_for(chatter_id: str | None, account_id: str) -> InboxFilter | None:
    if chatter_id is None:
        return None
    cfg = await config(account_id)
    g = bound_group(cfg, chatter_id)
    if g is None:
        return None
    return InboxFilter(cfg, g)


def acting_chatter_id() -> str | None:
    from chatters import current_actor
    actor = current_actor()
    return actor.id if actor is not None and actor.kind == "chatter" else None


async def chatter_inbox_filter(account_id: str) -> InboxFilter | None:
    return await filter_for(acting_chatter_id(), account_id)


def filter_rows(resp: dict[str, Any], keep: InboxFilter | None) -> dict[str, Any]:
    if keep is None or not isinstance(resp, dict):
        return resp
    key = "list" if "list" in resp else "chats" if "chats" in resp else "rows" if "rows" in resp else None
    if key is None:
        return resp
    return {
        **resp,
        key: [r for r in resp.get(key) or [] if keep((r.get("withUser") or {}).get("id"))],
        "split_version": keep.version(),
    }


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
