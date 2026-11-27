from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal

log = logging.getLogger("of-relay.runtime-switches")

Kind = Literal["bool", "number"]
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")
SCOPE_SEP = "@"


@dataclass(frozen=True)
class Switch:
    env: str
    label: str
    effect: str
    kind: Kind
    default: Any
    parse_env: Callable[[str], Any]
    where: str
    minimum: int | None = None
    maximum: int | None = None
    off_only: bool = False


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in _TRUE


def _not_off(raw: str) -> bool:
    return raw.strip().lower() not in _FALSE


SWITCHES: tuple[Switch, ...] = (
    Switch("W7_WEBHOOK_DISPATCH_DISABLED", "Instant DM dispatch off",
           "On: an inbound fan DM no longer queues and wakes its automation at once; replies wait "
           "for the next periodic sweep.",
           "bool", False, _truthy, "webhook_dispatch._global_kill_switch"),
    Switch("STYLE_FORCE_OFF", "Human texting style off",
           "On: every realism / style flag (typos, spacing, non-native, consistency, painful texting, "
           "cat stickers) reads off on every account.",
           "bool", False, lambda raw: bool(raw), "automations/_common.py style loaders"),
    Switch("OF_COTAG_ENABLED", "Release-form co-tags",
           "Off: no release-form co-tags on media sends and no @mention on auto stories.",
           "bool", True, lambda raw: (raw or "1").strip().lower() not in (*_FALSE, ""),
           "media_cotag.enabled"),
    Switch("S4S_LIVE_POSTING", "S4S live posting",
           "Off: S4S post slots cancel with \"live posting off\"; nothing is posted to OnlyFans.",
           "bool", True, _not_off, "s4s_api.live_posting"),
    Switch("MAX_EMPLOYEES_PER_USER", "Employee seats per agency",
           "Most active employees one agency may have; 0 = no cap. Applies to new hires and "
           "re-enables; employees already active stay.",
           "number", 20, lambda raw: int(raw or "0"), "employees", minimum=0, maximum=500),
    Switch("SMART_LIST_MAX_ACTIVE", "Active smart lists per Creator",
           "Most smart lists one Creator may have active (each costs OF writes). Applies to new "
           "activations; lists already active stay.",
           "number", 10, lambda raw: int(raw), "smart_lists_api", minimum=1, maximum=50),
    Switch("FULL_AI_CHAT_OFF", "Full AI Chat off",
           "On: Full AI Chat sends nothing on any Creator; its Fans go back to the other automations.",
           "bool", False, _truthy, "automations/full_ai_owner_io._off"),
    Switch("PROMO_PREEMPT_ENABLED", "Re-create promos before they end",
           "Off: Keep running re-creates a promo only after it ends (no re-create at 90% filled "
           "or shortly before OnlyFans's end time).",
           "bool", True, _not_off, "automations/promo_reactivate, promo_create_guard._recheck"),
    Switch("OF_LIVE_WINDOW_ENABLED", "Go live in the desktop app",
           "On: Go live and Start open OnlyFans's own streaming page in the desktop app (the web "
           "shows a Download the app button). Off: both stay Not available.",
           "bool", False, _truthy, "of_live_window"),
    Switch("OFM_NEW_WRITES_ENABLED", "OF Manager new writes",
           "On: in OF Manager, Close all sessions, Block by country / IP, Social media's and Things I "
           "Like's add and remove, Reset stream key, Streaming blocked users' block and unblock, Edit "
           "profile's cover and avatar, Messaging's Tip-from-free-followers and Security's Fully "
           "private switches and a tracking link's Share work and save to OnlyFans; so do Edit "
           "profile's Bio formatting, email's Update frequency, Record video / voice, a vault "
           "list's More and a chat's own-message Countdown, Copy as draft and Unsend PPV, which send requests the app "
           "already sent before. Off: all stay Not available (the own-message extras are not shown); the Relay refuses the "
           "first group's writes (the second group is only hidden in the app). "
           "Turns on only from the server's env; here it can only be forced off, for every Creator. "
           "Per Creator: the Creator's owner can force it off for that Creator alone "
           "(Settings › OF Manager writes); on for a Creator = on here and not forced off there.",
           "bool", False, _truthy, "server._ofm_new_writes_on", off_only=True),
    Switch("LEAK_TRACKER_ENABLED", "Leak tracker",
           "On (with LEAK_TRACKER_URL set and cell mode off): Agencies whose Leak tracker flag is on see "
           "Creators › Leak tracker. Off: the page is hidden and every Leak tracker route answers 404. "
           "Turns on only from the server's env; here it can only be forced off.",
           "bool", False, _truthy, "leak_tracker.deployment_on", off_only=True),
)
BY_NAME: dict[str, Switch] = {s.env: s for s in SWITCHES}

_overrides: dict[str, dict[str, Any]] = {}
# One lock covers the DB write and the re-read, so the cache equals the table as of the last write;
# the committed row enters the cache first, so a failed re-read cannot leave a saved force-off unenforced.
_lock: asyncio.Lock | None = None
_loaded = False
_warned_env: set[tuple[str, str]] = set()


def _env(sw: Switch) -> tuple[Any, bool]:
    raw = os.environ.get(sw.env)
    if raw is None:
        return sw.default, False
    try:
        return sw.parse_env(raw), True
    except (TypeError, ValueError, OverflowError):
        if (sw.env, raw) not in _warned_env:
            _warned_env.add((sw.env, raw))
            log.warning("%s=%r is not legal — using the default %r", sw.env, raw, sw.default)
        return sw.default, False


def scoped(name: str, account_id: str) -> str:
    return f"{name}{SCOPE_SEP}{account_id}"


def creator_override(name: str, account_id: str) -> dict[str, Any] | None:
    return _overrides.get(scoped(name, account_id))


def value(name: str, account_id: str | None = None) -> Any:
    sw = BY_NAME[name]
    if sw.off_only and not _loaded:
        return False  # fail closed: the unread table may hold a force-off
    o = _overrides.get(name)  # DB override > env > default, on purpose the reverse of lane_config
    v = o["value"] if o is not None and not (sw.off_only and o["value"]) else _env(sw)[0]
    if v and account_id and sw.off_only and creator_override(name, account_id) is not None:
        return False
    return v


def on(name: str, account_id: str | None = None) -> bool:
    return bool(value(name, account_id))


def on_for(name: str, account: Callable[[], str] | None = None) -> bool:
    return on(name) and (account is None or on(name, account()))


def require_switch(name: str, account: Callable[[], str] | None = None) -> Callable[[], None]:
    def _require() -> None:
        if not on_for(name, account):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
    return _require


def coerce(sw: Switch, v: Any) -> Any:
    if sw.kind == "bool":
        if not isinstance(v, bool):
            raise ValueError(f"{sw.env} is on/off: send true or false")
        if v and sw.off_only:
            raise ValueError(f"{sw.env} turns on only from the server's env; here it can only be forced off")
        return v
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or (isinstance(v, float) and not math.isfinite(v)) or int(v) != v:
        raise ValueError(f"{sw.env} takes a whole number")
    v = int(v)
    if sw.minimum is not None and v < sw.minimum:
        raise ValueError(f"{sw.env} must be at least {sw.minimum}")
    if sw.maximum is not None and v > sw.maximum:
        raise ValueError(f"{sw.env} must be at most {sw.maximum}")
    return v


def loaded() -> bool:
    return _loaded


def _disagrees(sw: Switch, o: dict[str, Any] | None) -> bool:
    if o is None:
        return False
    env_value, from_env = _env(sw)
    return from_env and o["value"] != env_value


def describe(name: str) -> dict[str, Any]:
    sw = BY_NAME[name]
    env_value, from_env = _env(sw)
    o = _overrides.get(name)
    effective = value(name)
    return {
        "env": sw.env, "label": sw.label, "effect": sw.effect, "kind": sw.kind,
        "default": sw.default, "minimum": sw.minimum, "maximum": sw.maximum, "where": sw.where,
        "env_raw": os.environ.get(sw.env),
        "env_value": env_value if from_env else None,
        "override": None if o is None else o["value"],
        "override_at": None if o is None else o["updated_at"],
        "override_by": None if o is None else o["updated_by"],
        "source": "override" if o is not None else ("env" if from_env else "default"),
        "fallback": env_value,
        "overrides_env": _disagrees(sw, o),
        "effective": effective,
        "active": effective != sw.default,
    }


def describe_all() -> list[dict[str, Any]]:
    return [describe(s.env) for s in SWITCHES]


async def _read_rows() -> dict[str, dict[str, Any]]:
    from sqlalchemy import select

    from db.engine import get_session
    from db.models import RuntimeSwitch

    out: dict[str, dict[str, Any]] = {}
    async with get_session() as s:
        for r in (await s.execute(select(RuntimeSwitch))).scalars():
            base, sep, aid = r.name.partition(SCOPE_SEP)
            sw = BY_NAME.get(base)
            if sw is None or (sep and not (sw.off_only and aid)):
                continue
            try:
                v = coerce(sw, json.loads(r.value_json))
            except (ValueError, TypeError):
                log.warning("runtime_switches: stored %s=%r is not legal — ignored", r.name, r.value_json)
                continue
            out[r.name] = {"value": v, "updated_by": r.updated_by,
                           "updated_at": r.updated_at.isoformat() if r.updated_at else None}
    return out


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def load() -> None:
    global _overrides, _loaded
    async with _get_lock():
        _overrides = await _read_rows()
        _loaded = True
    if _overrides:
        log.info("runtime switch overrides: %s", {k: v["value"] for k, v in _overrides.items()})
    for name, o in _overrides.items():
        if name in BY_NAME and _disagrees(BY_NAME[name], o):
            log.warning("runtime switch %s: the Settings override %r beats the env %s=%r; "
                        "clear it in Settings → System to let the env apply",
                        name, o["value"], name, os.environ.get(name))


async def load_until_loaded(interval_s: float = 30.0) -> None:
    while not _loaded:
        await asyncio.sleep(interval_s)
        try:
            await load()
            log.info("runtime switch overrides loaded on retry")
        except Exception:
            log.exception("runtime switch overrides still not loaded; retrying in %ss", interval_s)


async def set_override(name: str, v: Any, *, by: str | None, account_id: str | None = None) -> dict[str, Any]:
    from sqlalchemy import delete

    from db.engine import get_session
    from db.models import RuntimeSwitch

    global _overrides, _loaded
    sw = BY_NAME[name]
    if account_id is not None and not (sw.off_only and account_id):
        raise ValueError(f"{name} has no per-Creator override")
    clean = None if v is None else coerce(sw, v)
    key = name if account_id is None else scoped(name, account_id)
    async with _get_lock():
        at = datetime.utcnow()
        async with get_session() as s:
            if clean is None:
                await s.execute(delete(RuntimeSwitch).where(RuntimeSwitch.name == key))
            else:
                await s.merge(RuntimeSwitch(name=key, value_json=json.dumps(clean), updated_by=by, updated_at=at))
        # cache the committed row before the re-read so a failed re-read cannot leave a saved force-off unenforced
        published = {k: o for k, o in _overrides.items() if k != key}
        if clean is not None:
            published[key] = {"value": clean, "updated_by": by, "updated_at": at.isoformat()}
        _overrides = published
        try:
            _overrides = await _read_rows()
            _loaded = True
        except Exception:
            log.exception("runtime switch %s: saved, but the re-read failed; the cache holds the saved value", key)
    log.info("runtime switch %s override=%r by=%s", key, clean, by)
    return describe(name)
