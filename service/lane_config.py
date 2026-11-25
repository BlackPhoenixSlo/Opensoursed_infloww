from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_json import write_atomic

log = logging.getLogger("of-relay.lane-config")

# Leaf: imports nothing from the relay, since lanes are built at module import before the loop or db_init exist. Precedence env > stored override > code default; env is the lockout escape hatch. Changes apply at restart: semaphores/executors are built once.
_HERE = Path(__file__).resolve().parent


def _default_path() -> Path:
    explicit = os.environ.get("LANE_CONFIG_PATH", "").strip()
    if explicit:
        return Path(explicit)
    # Beside the SQLite file, not secrets/ (mounted under /private/tmp, cleared on reboot); parsed so a Postgres URL or moved DB doesn't land in an ephemeral dir.
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite") and "///" in url:
        db_file = Path(url.split("///", 1)[1].split("?", 1)[0])
        if db_file.parent.is_dir():
            return db_file.parent / "lane_config.json"
    if (_HERE / "dbdata").is_dir():
        return _HERE / "dbdata" / "lane_config.json"
    return _HERE / "lane_config.json"


_PATH = _default_path()
_HISTORY = _PATH.with_name("lane_config_history.jsonl")

_lock = threading.Lock()
_stored_cache: dict[str, int] | None = None

_defaults: dict[str, int] = {}
_live: dict[str, int] = {}
_switches: set[str] = set()
_read_at_use: set[str] = set()


def _clamp(value: Any) -> int:
    return max(1, int(value))


_SWITCH_WORDS = {"0": 0, "1": 1, "off": 0, "on": 1, "false": 0, "true": 1, "no": 0, "yes": 1}


def _legal(name: str, value: Any) -> int:
    if name not in _switches:
        return _clamp(value)
    if isinstance(value, bool):
        return int(value)
    v = _SWITCH_WORDS.get(str(value).strip().lower())
    if v is None:
        raise ValueError(f"{name} is a switch: 0 (off) or 1 (on), got {value!r}")
    return v


def _load() -> dict[str, int]:
    # Never raises: a missing or corrupt store must boot on code defaults, a ceiling failing closed at import is an outage.
    try:
        raw = json.loads(_PATH.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        log.warning("lane_config unreadable at %s — using code defaults", _PATH,
                    exc_info=True)
        return {}
    if not isinstance(raw, dict):
        log.warning("lane_config is not an object — using code defaults")
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            log.warning("lane_config: %s=%r is not an int — ignoring", key, value)
    return out


def stored() -> dict[str, int]:
    # Unknown keys are kept: a knob whose module isn't imported yet looks the same as a retired one, and dropping it on the next save loses a setting.
    global _stored_cache
    with _lock:
        if _stored_cache is None:
            _stored_cache = _load()
        return dict(_stored_cache)


def _from_env(env_var: str) -> int | None:
    raw = os.environ.get(env_var)
    if raw is None or not str(raw).strip():
        return None
    try:
        return _legal(env_var, raw)
    except (TypeError, ValueError):
        log.warning("%s=%r is not an int — falling through to stored/default",
                    env_var, raw)
        return None


def _current(env_var: str, default: int) -> tuple[int, str]:
    from_env = _from_env(env_var)
    if from_env is not None:
        return from_env, "env"
    from_store = stored().get(env_var)
    if from_store is not None:
        try:
            return _legal(env_var, from_store), "stored"
        except ValueError:
            log.warning("lane_config: stored %s=%r is not legal — using the default", env_var, from_store)
    return _legal(env_var, default), "default"


def overridden(env_var: str) -> bool:
    return _from_env(env_var) is not None or env_var in stored()


def resolve(env_var: str, default: int) -> int:
    value, _ = _current(env_var, default)
    _defaults[env_var] = _legal(env_var, default)
    _live.setdefault(env_var, value)
    return value


def resolve_switch(env_var: str, default: bool) -> bool:
    _switches.add(env_var)
    value, _ = _current(env_var, int(default))
    _defaults[env_var] = int(bool(default))
    _live[env_var] = value
    return bool(value)


def resolve_live(env_var: str, default: int) -> int:
    value = resolve(env_var, default)
    _read_at_use.add(env_var)
    _live[env_var] = value
    return value


def record_live(env_var: str, value: int) -> None:
    _live[env_var] = _legal(env_var, value)


def knob_names() -> frozenset[str]:
    return frozenset(_defaults)


def set_many(values: dict[str, Any]) -> dict[str, int]:
    known = knob_names()
    clean: dict[str, int | None] = {}
    for name, value in values.items():
        if name not in known:
            raise ValueError(f"unknown knob: {name}")
        if value is None:
            clean[name] = None
            continue
        try:
            clean[name] = _legal(name, value)
        except (TypeError, ValueError) as e:
            if name in _switches:
                raise ValueError(str(e))
            raise ValueError(f"{name} must be an integer, got {value!r}")

    global _stored_cache
    with _lock:
        current = dict(_stored_cache) if _stored_cache is not None else _load()
        changes: list[dict[str, Any]] = []
        for name, value in clean.items():
            before = current.get(name)
            if value is None:
                current.pop(name, None)
            else:
                current[name] = value
            if before != value:
                changes.append({
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "key": name,
                    "old": before,
                    "new": value,
                })
        _write(current)
        _stored_cache = dict(current)
        _append_history(changes)
        log.info("lane_config saved %s -> %s", sorted(clean), _PATH)
        return dict(current)


def _write(data: dict[str, int]) -> None:
    write_atomic(_PATH, data)


def _append_history(changes: list[dict[str, Any]]) -> None:
    if not changes:
        return
    try:
        _HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY, "a+b") as fh:
            # Heal a torn tail first: appending after a half line would glue this row onto the fragment and lose a real change.
            fh.seek(0, os.SEEK_END)
            if fh.tell() > 0:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    fh.write(b"\n")
            for row in changes:
                fh.write((json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
    except OSError:
        log.warning("lane_config history append failed at %s", _HISTORY,
                    exc_info=True)


def note_restart() -> None:
    with _lock:
        _append_history([{
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": "relay restarted from the panel",
        }])


def history(limit: int = 50) -> list[dict[str, Any]]:
    try:
        lines = _HISTORY.read_text("utf-8").splitlines()
    except FileNotFoundError:
        return []
    except Exception:
        # UnicodeDecodeError is a ValueError, not OSError: one corrupt byte must not 500 the panel's GET and POST.
        log.warning("lane_config history unreadable at %s", _HISTORY,
                    exc_info=True)
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-max(1, int(limit)):]):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def describe() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    saved = stored()
    for env_var in sorted(_defaults):
        default = _defaults[env_var]
        value, src = _current(env_var, default)
        live = value if env_var in _switches or env_var in _read_at_use else _live.get(env_var)
        rows.append({
            "name": env_var,
            "value": value,
            "default": default,
            "stored": saved.get(env_var),
            "source": src,
            "env_locked": src == "env",
            "live": live,
            "pending": live is not None and live != value,
            "switch": env_var in _switches,
        })
    return rows


def path() -> str:
    return str(_PATH)
