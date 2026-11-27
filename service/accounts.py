from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SESSIONS_DIR = HERE / "sessions"
ACCOUNTS_DIR = SESSIONS_DIR / "accounts"
ACTIVE_FILE = SESSIONS_DIR / "active.json"
MIGRATED_MARKER = SESSIONS_DIR / ".migrated"
_CELLS = bool(os.environ.get("OI_CELL_MAP"))

_lock = threading.Lock()

_COLORS = ["#7C5CFF", "#22C55E", "#F59E0B", "#EF4444", "#06B6D4",
           "#EC4899", "#84CC16", "#A855F7", "#0EA5E9", "#F97316"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    SESSIONS_DIR.mkdir(exist_ok=True)
    ACCOUNTS_DIR.mkdir(exist_ok=True)


class NotAnAccountId(ValueError):
    # Only this is "no such account": a ValueError from below the guard (JSONDecodeError, NUL, lone surrogate) must not be mistaken for it.
    pass


def account_dir(account_id: str) -> Path:
    # An id is one dir NAME: NAME_MAX counts bytes; NUL/lone surrogate are legal in str, illegal in a filename.
    aid = str(account_id)
    try:
        raw = aid.encode()
    except UnicodeEncodeError:
        raw = None
    if (raw is None or len(raw) > 255 or b"\x00" in raw
            or aid in ("", ".", "..") or "/" in aid or "\\" in aid):
        raise NotAnAccountId(f"not an account id: {aid[:40]!r}")
    return ACCOUNTS_DIR / aid


def _account_path(account_id: str, *parts: str) -> Path | None:
    try:
        return account_dir(account_id).joinpath(*parts)
    except NotAnAccountId:
        return None



def migrate_legacy() -> dict[str, Any]:
    _ensure_dirs()
    with _lock:
        if MIGRATED_MARKER.exists():
            return {"migrated": False, "reason": "already-migrated"}

        legacy_sessions = sorted(SESSIONS_DIR.glob("session_*.json"))
        if not legacy_sessions:
            MIGRATED_MARKER.write_text(_utc_now())
            return {"migrated": False, "reason": "no-legacy-sessions"}

        moved: list[dict[str, str]] = []
        for sp in legacy_sessions:
            try:
                s = json.loads(sp.read_text())
            except Exception:
                continue
            uid = (s.get("headers") or {}).get("user_id")
            if not uid:
                continue
            uid = str(uid)
            adir = account_dir(uid)
            adir.mkdir(parents=True, exist_ok=True)
            target = adir / sp.name
            if not target.exists():
                shutil.move(str(sp), str(target))
            else:
                sp.unlink(missing_ok=True)
            moved.append({"file": sp.name, "account": uid})

            chunk_name = (s.get("signing") or {}).get("chunk_2313_file")
            if chunk_name:
                ch = SESSIONS_DIR / chunk_name
                if ch.exists():
                    ct = adir / chunk_name
                    if not ct.exists():
                        shutil.move(str(ch), str(ct))

        seen_accounts: set[str] = set()
        for entry in moved:
            uid = entry["account"]
            if uid in seen_accounts:
                continue
            seen_accounts.add(uid)
            _initialise_account_from_sessions(uid)

        newest: tuple[Path, str] | None = None
        for adir in ACCOUNTS_DIR.iterdir():
            if not adir.is_dir():
                continue
            for sp in adir.glob("session_*.json"):
                if newest is None or sp.stat().st_mtime > newest[0].stat().st_mtime:
                    newest = (sp, adir.name)
        if newest:
            _write_active_unlocked(newest[1])

        MIGRATED_MARKER.write_text(_utc_now())
        return {"migrated": True, "moved": moved, "active": newest[1] if newest else None}


def _initialise_account_from_sessions(account_id: str) -> None:
    adir = account_dir(account_id)
    sessions = sorted(adir.glob("session_*.json"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        return
    newest = sessions[-1]
    try:
        s = json.loads(newest.read_text())
    except Exception:
        return

    meta_path = adir / "meta.json"
    if not meta_path.exists():
        meta = {
            "id": account_id,
            "nickname": f"Account {account_id}",
            "color": _COLORS[abs(hash(account_id)) % len(_COLORS)],
            "created_at": _utc_now(),
            "last_used_at": s.get("captured_at"),
        }
        meta_path.write_text(json.dumps(meta, indent=2))

    latest_path = adir / "latest.json"
    if not latest_path.exists():
        latest_path.write_text(json.dumps({
            "session": newest.name,
            "ts": newest.stem.removeprefix("session_"),
        }, indent=2))



def load_meta(account_id: str) -> dict[str, Any] | None:
    p = _account_path(account_id, "meta.json")
    if p is None or not p.exists():
        return None
    try:
        meta = json.loads(p.read_text())
    except Exception:
        return None
    return meta if isinstance(meta, dict) else None


def save_meta(account_id: str, meta: dict[str, Any]) -> None:
    with _lock:
        adir = account_dir(account_id)
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "meta.json").write_text(json.dumps(meta, indent=2))


# role "watcher" = fan account, no Creator: left out of every roster (no pump/scrape/ingest).
ROLE_WATCHER = "watcher"
ROLES = (ROLE_WATCHER,)


def get_role(account_id: str) -> str | None:
    meta = load_meta(account_id) or {}
    role = meta.get("role")
    return role if role in ROLES else None


def is_watcher(account_id: str) -> bool:
    return get_role(account_id) == ROLE_WATCHER


def set_role(account_id: str, role: str | None) -> dict[str, Any]:
    if role is not None and role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    return upsert_account(account_id, role=role or "")


def _has_session(adir: Path) -> bool:
    import platforms
    return any((adir / f).exists() for f in platforms.SESSION_FILES)


def list_accounts(include_watchers: bool = False) -> list[dict[str, Any]]:
    _ensure_dirs()
    out: list[dict[str, Any]] = []
    if not ACCOUNTS_DIR.is_dir():
        return out
    for adir in ACCOUNTS_DIR.iterdir():
        if not adir.is_dir():
            continue
        meta = load_meta(adir.name)
        if not meta:
            _initialise_account_from_sessions(adir.name)
            meta = load_meta(adir.name)
            if not meta:
                continue
        if not include_watchers and meta.get("role") == ROLE_WATCHER:
            continue
        meta["has_session"] = _has_session(adir)
        meta.setdefault("platform", "onlyfans")
        meta.setdefault("name", None)
        out.append(meta)
    out.sort(key=lambda m: m.get("last_used_at") or "", reverse=True)
    return out


def is_account(account_id: str) -> bool:
    # OSError must propagate: a falsy answer on error is fail-open for the isolation gate.
    p = _account_path(account_id)
    return p is not None and p.is_dir()


_IDS_CACHE: tuple[tuple[int, int, int, int], frozenset[str]] | None = None


def account_ids() -> frozenset[str]:
    # Keyed on ACCOUNTS_DIR identity, never a TTL (a TTL keeps a DELETED account authorised); errors propagate, empty set would fail-open.
    global _IDS_CACHE
    try:
        st = ACCOUNTS_DIR.stat()
    except FileNotFoundError:
        return frozenset()
    stamp = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns)
    cached = _IDS_CACHE
    if cached is not None and cached[0] == stamp:
        return cached[1]
    ids = frozenset(d.name for d in ACCOUNTS_DIR.iterdir() if d.is_dir())
    _IDS_CACHE = (stamp, ids)
    return ids


def get_account(account_id: str) -> dict[str, Any] | None:
    return load_meta(account_id)


def upsert_account(account_id: str, *,
                   nickname: str | None = None,
                   color: str | None = None,
                   platform: str | None = None,
                   name: str | None = None,
                   role: str | None = None) -> dict[str, Any]:
    import platforms
    existing = load_meta(account_id) or {}
    meta = {
        "id": account_id,
        "nickname": nickname if nickname is not None else existing.get("nickname") or f"Account {account_id}",
        "color": color if color is not None else existing.get("color") or _COLORS[abs(hash(account_id)) % len(_COLORS)],
        "platform": (platform if platform is not None
                     else existing.get("platform") or "onlyfans"),
        "name": name if name is not None else existing.get("name"),
        "created_at": existing.get("created_at") or _utc_now(),
        "last_used_at": existing.get("last_used_at"),
    }
    kept_role = existing.get("role") if role is None else role
    if kept_role:
        meta["role"] = kept_role
    meta["platform"] = platforms.require(meta["platform"]).key
    save_meta(account_id, meta)
    return meta


def get_platform(account_id: str) -> str:
    meta = load_meta(account_id) or {}
    return meta.get("platform") or "onlyfans"


class PlatformCollision(Exception):
    pass


def ensure_platform(account_id: str, key: str) -> None:
    import platforms
    wanted = platforms.require(key)
    meta = load_meta(account_id)
    meta_platform = platforms.get(meta.get("platform")) if meta is not None else None
    if isinstance(meta_platform, platforms.UnknownPlatform):
        raise PlatformCollision(
            f"account {account_id} has the unknown Platform key {meta_platform.key!r}; "
            f"a {wanted.label} session can't be linked to it until the key is fixed")
    if _CELLS:
        import creator_reservations
        creator_reservations.admit(account_id, wanted.key)
    adir = _account_path(account_id)
    if adir is None or not adir.is_dir():
        return
    for held in platforms.ALL:
        if held is wanted:
            continue
        if (held is meta_platform
                or (adir / held.session_file).exists()
                or (held is platforms.ONLYFANS and any(adir.glob("session_*.json")))):
            raise PlatformCollision(
                f"account {account_id} is already a {held.label} Creator; "
                f"a {wanted.label} session can't be linked to it")


def delete_account(account_id: str) -> bool:
    with _lock:
        adir = account_dir(account_id)
        if not adir.is_dir():
            return False
        shutil.rmtree(adir)
        if _read_active_unlocked() == account_id:
            _write_active_unlocked(None)
        return True



def _read_active_unlocked() -> str | None:
    if not ACTIVE_FILE.exists():
        return None
    try:
        return json.loads(ACTIVE_FILE.read_text()).get("active_account_id")
    except Exception:
        return None


def _write_active_unlocked(account_id: str | None) -> None:
    ACTIVE_FILE.write_text(json.dumps({"active_account_id": account_id}, indent=2))


def get_stored_active_account_id() -> str | None:
    with _lock:
        return _read_active_unlocked()


def get_active_account_id() -> str | None:
    with _lock:
        active = _read_active_unlocked()
    if active and is_watcher(active):
        active = None
    if active and (d := _account_path(active)) is not None and _has_session(d):
        return active

    candidates = [a for a in list_accounts() if a.get("has_session")]
    if not candidates:
        return None
    fallback = candidates[0]["id"]
    set_active_account_id(fallback)
    return fallback


def set_active_account_id(account_id: str | None) -> bool:
    # A watcher is never the default: a route without X-Account-Id would act as it.
    if account_id is not None and is_watcher(account_id):
        return False
    _ensure_dirs()
    with _lock:
        _write_active_unlocked(account_id)
    return True



def latest_session_path(account_id: str) -> Path | None:
    latest = _account_path(account_id, "latest.json")
    if latest is None or not latest.exists():
        return None
    try:
        sp = latest.parent / json.loads(latest.read_text())["session"]
    # Not `except Exception`: OSError (fd exhaustion) must propagate, else a healthy account reads as having no session.
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return sp if sp.exists() else None


def record_session(account_id: str, session_path: Path) -> None:
    with _lock:
        adir = account_dir(account_id)
        adir.mkdir(parents=True, exist_ok=True)
        ts = session_path.stem.removeprefix("session_")
        (adir / "latest.json").write_text(json.dumps({
            "session": session_path.name, "ts": ts,
        }, indent=2))
        meta = load_meta(account_id) or {
            "id": account_id,
            "nickname": f"Account {account_id}",
            "color": _COLORS[abs(hash(account_id)) % len(_COLORS)],
            "platform": "onlyfans",
            "name": None,
            "created_at": _utc_now(),
        }
        meta["last_used_at"] = _utc_now()
        (adir / "meta.json").write_text(json.dumps(meta, indent=2))
