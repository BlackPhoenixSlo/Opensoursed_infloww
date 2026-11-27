from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterable

log = logging.getLogger("of-relay.media_cotag")


def fold_handle(raw: Any) -> str:
    return str(raw or "").strip().lstrip("@").lower()

_VERDICT_TTL_S = 600.0
# A MISS is retried sooner: usually the handle has not accepted the tag request yet, which an operator fixes mid-day.
_ID_HIT_TTL_S = 3600.0
_ID_MISS_TTL_S = 300.0
_VERDICT_CACHE_MAX = 20_000
_CFG_TTL_S = 60.0

# The two flags stay separate so flipping the video rule applies on the next config read.
_verdicts: dict[tuple[str, int], tuple[float, tuple[bool, bool]]] = {}
# The handle rides along so a Brain username change invalidates the cached id.
_ids: dict[str, tuple[float, int | None, str]] = {}
_acct_cfg: dict[str, tuple[float, tuple[bool, str | None]]] = {}

_engine = None



def enabled() -> bool:
    import runtime_switches
    return runtime_switches.on("OF_COTAG_ENABLED")


def _account_cfg(account_id: str) -> tuple[bool, str | None]:
    now = time.monotonic()
    cached = _acct_cfg.get(account_id)
    if cached and now - cached[0] < _CFG_TTL_S:
        return cached[1]
    always, username = False, None
    try:
        from sqlalchemy import text

        with _sync_engine().connect() as conn:
            row = conn.execute(text(
                "SELECT cotag_tag_videos, cotag_username FROM account_ai_config "
                "WHERE account_id = :a"), {"a": account_id}).first()
        if row is not None:
            always = bool(row[0])
            username = fold_handle(row[1]) or None
    except Exception:
        log.exception(
            "cotag: brain config lookup failed (account=%s) — using the "
            "defaults (video rule off, no co-creator)", account_id)
    _acct_cfg[account_id] = (now, (always, username))
    return always, username


def handle(account_id: Any) -> str:
    if not account_id:
        return ""
    return _account_cfg(str(account_id))[1] or ""



def _numeric_ids(media_files: Any) -> list[int] | None:
    if not media_files:
        return []
    out: list[int] = []
    for m in media_files:
        try:
            out.append(int(m))
        except (TypeError, ValueError):
            return None
    return out


def _multi_person(ai_fields_json: str | None) -> bool:
    import vault_scripts

    try:
        fields = json.loads(ai_fields_json) if ai_fields_json else {}
    except (TypeError, ValueError):
        fields = {}
    if not isinstance(fields, dict):
        fields = {}
    return not vault_scripts.is_solo(fields)


def _sync_engine():
    # Send path runs in asyncio.to_thread, so no async session; NullPool avoids fds held open (relay hit EMFILE before).
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine, event
        from sqlalchemy.pool import NullPool

        from db.engine import DATABASE_URL

        url = DATABASE_URL.replace("+aiosqlite", "").replace("+asyncpg", "")
        is_sqlite = url.startswith("sqlite")
        eng = create_engine(
            url,
            poolclass=NullPool,
            connect_args={"check_same_thread": False} if is_sqlite else {},
        )
        if is_sqlite:
            @event.listens_for(eng, "connect")
            def _read_only(dbapi_conn, _record):   # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA query_only=1")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()
        _engine = eng
    return _engine


def _describe_rows(account_id: str,
                   media_ids: Iterable[int]) -> dict[int, tuple[str | None, str | None]]:
    from sqlalchemy import bindparam, text

    stmt = text(
        "SELECT media_id, ai_fields_json, kind FROM vault_items "
        "WHERE account_id = :account_id AND media_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with _sync_engine().connect() as conn:
        rows = conn.execute(stmt, {"account_id": str(account_id),
                                   "ids": list(media_ids)})
        return {int(r[0]): (r[1], r[2]) for r in rows}


def _remember(key: tuple[str, int], flags: tuple[bool, bool]) -> None:
    if len(_verdicts) >= _VERDICT_CACHE_MAX:
        _verdicts.clear()
    _verdicts[key] = (time.monotonic(), flags)


def needs_cotag(account_id: str, media_files: Any) -> bool:
    ids = _numeric_ids(media_files)
    if ids is None:
        return True
    if not ids:
        return False
    always_videos, _ = _account_cfg(str(account_id))

    def _needs(flags: tuple[bool, bool]) -> bool:
        multi, video = flags
        return multi or (always_videos and video)

    now = time.monotonic()
    stale: list[int] = []
    for mid in ids:
        cached = _verdicts.get((str(account_id), mid))
        if cached and now - cached[0] < _VERDICT_TTL_S:
            if _needs(cached[1]):
                return True
        else:
            stale.append(mid)
    if not stale:
        return False

    try:
        rows = _describe_rows(account_id, stale)
    except Exception:
        log.exception(
            "cotag: vault lookup failed (account=%s media=%s) — tagging, because "
            "a lookup we could not run is not evidence that she is alone",
            account_id, stale,
        )
        return True

    verdict = False
    for mid in stale:
        # Missing describe data counts as multi-person.
        row = rows.get(mid)
        flags = (_multi_person(row[0] if row else None),
                 row is not None and str(row[1] or "").strip().lower() == "video")
        _remember((str(account_id), mid), flags)
        verdict = verdict or _needs(flags)
    return verdict



def lookup_tag_id(client, want: str | None = None) -> int | None:
    if want is None:
        want = handle(getattr(client, "account_id", None))
    resp = client.tagged_friend_users(search=want, limit=20)
    items = (resp or {}).get("items") or []
    for item in items:
        user = item.get("user") or {}
        for candidate in (user.get("username"), item.get("name"), user.get("name")):
            if str(candidate or "").strip().lstrip("@").lower() == want:
                # The top-level `id` is what the send body's userTags takes (verified against the live composer capture).
                raw = item.get("id") if item.get("id") is not None else user.get("id")
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None
    return None


def tag_user_id(client) -> int | None:
    account_id = str(getattr(client, "account_id", "") or "")
    want = handle(account_id)
    if not want:
        return None

    now = time.monotonic()
    cached = _ids.get(account_id)
    # A cached id is only good for the handle it resolved; a username change must re-resolve.
    if cached and cached[2] == want:
        ttl = _ID_HIT_TTL_S if cached[1] is not None else _ID_MISS_TTL_S
        if now - cached[0] < ttl:
            return cached[1]

    try:
        found = lookup_tag_id(client, want)
    except Exception:
        log.exception("cotag: tagged-friend lookup failed on account=%s", account_id)
        return None

    _ids[account_id] = (now, found, want)
    if found is None:
        log.error(
            "cotag: @%s is NOT in account %s's tagged-friend list — OF would 400 "
            "the send on an id it does not know, so multi-person media from this "
            "account goes out UNTAGGED until the tag request is accepted",
            want, account_id,
        )
    else:
        log.info("cotag: @%s resolves to %s on account %s", want, found, account_id)
    return found


def would_cotag(account_id: Any, media_files: Any) -> bool:
    return bool(enabled() and media_files and str(account_id or "")
                and needs_cotag(str(account_id), media_files))


def cotags_for(client, media_files: Any) -> list[int]:
    if not would_cotag(getattr(client, "account_id", ""), media_files):
        return []
    uid = tag_user_id(client)
    return [uid] if uid is not None else []


def story_mention(account_id: str, media_ids: Any) -> str | None:
    # Stories cannot carry userTags (OF re-runs the fresh-upload pipeline), so tag by @mention overlay text.
    try:
        if not enabled():
            return None
        if not str(account_id or "") or not needs_cotag(account_id, media_ids):
            return None
    except Exception:
        log.exception("cotag: story check failed — mentioning, because a check "
                      "we could not run is not evidence that she is alone")
    want = handle(account_id)
    return f"@{want}" if want else None


def forget_tag_id(account_id: str) -> None:
    # Dropped on OF rejecting a tagged body: else the resolver keeps handing out the refused id for its hour TTL.
    _ids.pop(str(account_id or ""), None)


def forget_account_cfg(account_id: str) -> None:
    _acct_cfg.pop(str(account_id or ""), None)
    _ids.pop(str(account_id or ""), None)


def reset_caches() -> None:
    _verdicts.clear()
    _ids.clear()
    _acct_cfg.clear()
