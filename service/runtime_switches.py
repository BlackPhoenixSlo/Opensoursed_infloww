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
write (200 concurrent saves leave the cache and the row agreeing). One relay
process per DB (a fleet shard has its own), so no cross-process invalidation.

NOT LOADED IS VISIBLE. If the boot read fails, consumers run on env / defaults
(the pre-registry behaviour) and `loaded()` is False: the panel shows a banner and
the server retries `load()` in the background until it reads the table.

AN OVERRIDE THAT DISAGREES WITH A SET ENV VAR IS FLAGGED (`overrides_env`, and a
WARNING at load), because it outranks a later env change. The UI's toggle clears
the override instead of storing one when it lands back on the env / default value.

WRITES NEED THE FOUNDER PASSWORD (system_admin_api), as every master write should
(auth.require_master).
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


def value(name: str) -> Any:
    """The effective value: DB override > env > default. Sync and cheap (hot path)."""
    o = _overrides.get(name)
    if o is not None:
        return o["value"]
    return _env(BY_NAME[name])[0]


def on(name: str) -> bool:
    return bool(value(name))


def coerce(sw: Switch, v: Any) -> Any:
    """A UI value for `sw`, or ValueError. bool switches take JSON booleans only;
    numbers take finite whole numbers within [minimum, maximum]."""
    if sw.kind == "bool":
        if not isinstance(v, bool):
            raise ValueError(f"{sw.env} is on/off: send true or false")
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
    effective = o["value"] if o is not None else env_value
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
            sw = BY_NAME.get(r.name)
            if sw is None:
                continue   # a retired switch's row: kept, not consulted
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
    succeeds consumers run on env / defaults and `loaded()` is False."""
    global _overrides, _loaded
    async with _get_lock():
        _overrides = await _read_rows()
        _loaded = True
    if _overrides:
        log.info("runtime switch overrides: %s", {k: v["value"] for k, v in _overrides.items()})
    for name, o in _overrides.items():
        if _disagrees(BY_NAME[name], o):
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


async def set_override(name: str, v: Any, *, by: str | None) -> dict[str, Any]:
    """Store (v not None) or clear (v None) the override, then refresh the cache.
    KeyError: unknown name. ValueError: illegal value."""
    from sqlalchemy import delete

    from db.engine import get_session
    from db.models import RuntimeSwitch

    global _overrides, _loaded
    sw = BY_NAME[name]
    clean = None if v is None else coerce(sw, v)
    async with _get_lock():
        async with get_session() as s:
            if clean is None:
                await s.execute(delete(RuntimeSwitch).where(RuntimeSwitch.name == name))
            else:
                await s.merge(RuntimeSwitch(name=name, value_json=json.dumps(clean),
                                            updated_by=by, updated_at=datetime.utcnow()))
        _overrides = await _read_rows()
        _loaded = True
    log.info("runtime switch %s override=%r by=%s", name, clean, by)
    return describe(name)
