"""service/runtime_switches.py — the relay's env kill switches and runtime caps,
settable from Settings → System (GET/PUT /admin/system/switches).

Each switch used to be an env var only, so turning one meant an env edit and a
restart. Now each consumer reads it through `value(name)`, and the owner can set
an override from the UI that applies at the next read, no restart.

PRECEDENCE::

    DB override (runtime_switches row)  >  env var  >  code default

The reverse of `lane_config` (env wins there) on purpose: these are switches an
owner flips during an incident, and an env var the deploy pins must not make the
UI toggle a no-op. "Clear override" goes back to whatever env / default says.

THE ENV PARSE IS EACH CONSUMER'S OWN. Every switch keeps the exact env rule its
consumer had (STYLE_FORCE_OFF: any non-empty value is on; OF_COTAG_ENABLED: unset
or empty is on), so adopting the registry changed where a value comes from and
never what an env value means.

READS ARE CHEAP. `value()` is a dict lookup plus `os.environ.get`: no DB, no
await. `_global_kill_switch` calls it on every inbound DM. The overrides live in
`_overrides`, loaded once at boot (`load()`, server startup) and replaced
whole after each write. Writes are serialised by one lock that covers the DB
write and the re-read, so the cache always equals the table as of the last
write (200 concurrent saves leave the cache and the row agreeing). The committed
row goes into the cache before the re-read, so a failed re-read cannot leave a
saved force-off unenforced. One relay
process per DB (a fleet shard has its own), so no cross-process invalidation.

NOT LOADED IS VISIBLE. If the boot read fails, consumers run on env / defaults
(the pre-registry behaviour) and `loaded()` is False: the panel shows a banner and
the server retries `load()` in the background until it reads the table. An off_only
switch reads off until then (fails closed): the unread table may hold its force-off,
box-wide or for a Creator, and env-on alone must not turn it back on.

AN OVERRIDE THAT DISAGREES WITH A SET ENV VAR IS FLAGGED (`overrides_env`, and a
WARNING at load), because it outranks a later env change. The UI's toggle clears
the override instead of storing one when it lands back on the env / default value.

WRITES NEED THE FOUNDER PASSWORD (system_admin_api), as every master write should
(auth.require_master).

PER-CREATOR FORCE-OFF (off_only switches only). A row named `<SWITCH>@<account_id>` (value false)
forces the switch off for that one Creator: `value(name, account_id)` is the box-wide value AND
no such row. Like the box-wide override it can only turn off, never on. Its write is the Creator's
owner's (server PUT /admin/ofm-writes/{account_id}), not the founder's; it shares this cache and lock.
"""
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
SCOPE_SEP = "@"   # a per-Creator force-off row's name: "<SWITCH>@<account_id>"


@dataclass(frozen=True)
class Switch:
    env: str
    label: str
    effect: str
    kind: Kind
    default: Any
    parse_env: Callable[[str], Any]   # a present env string -> value (may raise)
    where: str                        # the consumer, for the panel and grep
    minimum: int | None = None        # number only
    maximum: int | None = None        # number only: a UI override above it is refused
    off_only: bool = False            # bool only: env turns it on; a UI override may only force it off


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
)
BY_NAME: dict[str, Switch] = {s.env: s for s in SWITCHES}

# name -> {"value": ..., "updated_at": iso, "updated_by": str|None}. Replaced whole, never mutated.
_overrides: dict[str, dict[str, Any]] = {}
_lock: asyncio.Lock | None = None
_loaded = False                       # the table has been read since boot
_warned_env: set[tuple[str, str]] = set()   # (name, raw) already logged as illegal


def _env(sw: Switch) -> tuple[Any, bool]:
    """(value, from_env). An unparseable env value falls back to the default, logged."""
    raw = os.environ.get(sw.env)
    if raw is None:
        return sw.default, False
    try:
        return sw.parse_env(raw), True
    except (TypeError, ValueError, OverflowError):
        if (sw.env, raw) not in _warned_env:   # once per bad value, not per read (hot path)
            _warned_env.add((sw.env, raw))
            log.warning("%s=%r is not legal — using the default %r", sw.env, raw, sw.default)
        return sw.default, False


def scoped(name: str, account_id: str) -> str:
    """The row name of `name`'s force-off for one Creator."""
    return f"{name}{SCOPE_SEP}{account_id}"


def creator_override(name: str, account_id: str) -> dict[str, Any] | None:
    """`account_id`'s force-off of `name` ({"value": False, "updated_at", "updated_by"}), or None."""
    return _overrides.get(scoped(name, account_id))


def value(name: str, account_id: str | None = None) -> Any:
    """The effective value: DB override > env > default (an off_only switch: env AND not forced off;
    with `account_id`, AND that Creator not forced off either; off while the table is not loaded).
    Sync and cheap (hot path)."""
    sw = BY_NAME[name]
    if sw.off_only and not _loaded:
        return False   # a force-off may sit in the unread table (NOT LOADED IS VISIBLE)
    o = _overrides.get(name)
    v = o["value"] if o is not None and not (sw.off_only and o["value"]) else _env(sw)[0]
    if v and account_id and sw.off_only and creator_override(name, account_id) is not None:
        return False
    return v


def on(name: str, account_id: str | None = None) -> bool:
    return bool(value(name, account_id))


def on_for(name: str, account: Callable[[], str] | None = None) -> bool:
    """`name` on box-wide and, given `account` (the request's Creator), for that Creator. `account` is asked only
    once the switch is on box-wide; its own refusal (e.g. 403 not your account) passes through."""
    return on(name) and (account is None or on(name, account()))


def require_switch(name: str, account: Callable[[], str] | None = None) -> Callable[[], None]:
    """A route guard (FastAPI dependency, or a direct call) for an inert-until-on switch: 404 while `name` is off
    (`on_for`: box-wide, then for `account`'s Creator), before any OF call, so a client's probe reads the route as
    absent."""
    def _require() -> None:
        if not on_for(name, account):
            from fastapi import HTTPException   # lazy: this module stays importable without FastAPI
            raise HTTPException(status_code=404, detail="Not Found")
    return _require


def coerce(sw: Switch, v: Any) -> Any:
    """A UI value for `sw`, or ValueError. bool switches take JSON booleans only;
    numbers take finite whole numbers within [minimum, maximum]."""
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
    """An override that differs from a SET env var: it outranks any later env change."""
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
        # What "Clear override" goes back to; the UI clears instead of storing it.
        "fallback": env_value,
        "overrides_env": _disagrees(sw, o),
        "effective": effective,
        # Engaged: something moved it off its code default (a kill switch is ON, a cap retuned).
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
                continue   # a retired switch's row (or a Creator row of a switch that has none): kept, not consulted
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
    """Boot: read every override into the cache. Raises on failure; until a read
    succeeds consumers run on env / defaults (an off_only switch: off) and `loaded()` is False."""
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
    """Background retry after a failed boot load: read until it works."""
    while not _loaded:
        await asyncio.sleep(interval_s)
        try:
            await load()
            log.info("runtime switch overrides loaded on retry")
        except Exception:
            log.exception("runtime switch overrides still not loaded; retrying in %ss", interval_s)


async def set_override(name: str, v: Any, *, by: str | None, account_id: str | None = None) -> dict[str, Any]:
    """Store (v not None) or clear (v None) the override, publish it to the cache, then re-read the table (a failed
    re-read keeps the published value; `loaded()` unchanged). `account_id`: that Creator's
    force-off instead (off_only switches only; v False or None). KeyError: unknown name. ValueError: illegal value."""
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
        # Committed: publish it before the re-read, so a failed re-read never leaves a committed force-off unenforced.
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
