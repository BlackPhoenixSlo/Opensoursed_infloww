from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable

import account_health
import app_open_warm
import events
import of_pacing
import of_ws
import platforms
import relay_host
import shared_refresher_decide as decide
import transaction_ingest
import view_lease
from env_knob import env_float

log = logging.getLogger("of-relay.shared_refresher")

ENABLED = env_float("SHARED_REFRESHER", 0.0, 0.0) == 1.0
KNOBS = decide.Knobs(lease_cycle_s=env_float("SHARED_REFRESHER_LEASE_CYCLE_S", 120.0, 0.0),
                     tab_cycle_s=env_float("SHARED_REFRESHER_TAB_CYCLE_S", 600.0, 0.0))
TICK_S = 5.0
BOOT_MS = int(time.time() * 1000)

_clock = time.monotonic
_state = decide.State()
_in_flight: set[str] = set()
_at_ms: dict[str, int] = {}
_seq: dict[str, int] = {}
_live_since_ms: dict[str, int] = {}
_task: asyncio.Task | None = None
_relay_loop: asyncio.AbstractEventLoop | None = None
_contributors: dict[str, Any] = {}
_window_reader: Callable[[str], Awaitable[Any]] | None = None
_window_asked: dict[str, float] = {}


def _server():
    return relay_host.live_server()


def snapshot(account_id: str) -> dict[str, Any]:
    v = _state.shown.get(account_id) or {"cycle_s": None, "live": None, "values": {}}
    return {"account_id": account_id, "boot": BOOT_MS, "seq": _seq.get(account_id, 0),
            "now": int(time.time() * 1000), "at": _at_ms.get(account_id),
            "cycle_s": None if v["cycle_s"] is None else int(v["cycle_s"]), "live": v["live"],
            "live_since": _live_since_ms.get(account_id) if account_id in _state.live_since else None,
            "values": _values_of(account_id)}


def live(account_id: str) -> str | None:
    return (_state.shown.get(str(account_id)) or {}).get("live")


def register(name: str, contributor: Any) -> None:
    _contributors[name] = contributor


def _values_of(account_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, c in list(_contributors.items()):
        try:
            out[name] = c.snapshot(account_id)
        except Exception:  # noqa: BLE001 — one contributor's bug drops its slot, never the snapshot or the tick
            log.warning("shared_refresher_contributor_failed name=%s account=%s", name, account_id, exc_info=True)
    return out


def note_values(account_id: str) -> None:
    loop = _relay_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(_values_noted, account_id)


def _values_noted(account_id: str) -> None:
    global _state
    prev = _state.shown.get(account_id)
    if prev is None:
        return
    nxt = {**prev, "values": _values_of(account_id)}
    if decide.changed(prev, nxt):
        _state = replace(_state, shown={**_state.shown, account_id: nxt})
        _publish(account_id)


def _publish(account_id: str) -> None:
    _seq[account_id] = _seq.get(account_id, 0) + 1
    events.publish({"creator_refreshed": snapshot(account_id), "__account_id": account_id})


def set_window_reader(fn: Callable[[str], Awaitable[Any]] | None) -> None:
    global _window_reader
    _window_reader = fn


async def window_read(account_id: str) -> Any:
    fn = _window_reader
    if fn is not None:
        return await fn(account_id)
    # Loaded by the server, not at import (it reads the live server).
    import accounts_admin_api
    return await accounts_admin_api.rewarm_roster_count(account_id)


def _asked(account_id: str) -> bool:
    for name, c in list(_contributors.items()):
        ask = getattr(c, "window_due", None)
        if ask is None:
            continue
        try:
            if ask(account_id):
                return True
        except Exception:  # noqa: BLE001 — one contributor's bug never fails the Cycle
            log.warning("shared_refresher_contributor_failed name=%s account=%s", name, account_id, exc_info=True)
    return False


def _window_step(account_id: str, asked: float) -> Callable[[], Awaitable[bool]]:
    async def step() -> bool:
        cycle = (_state.shown.get(account_id) or {}).get("cycle_s") or decide.FLOOR_S
        prev = _window_asked.get(account_id)
        if prev is not None and asked - prev < cycle:
            return False
        if not decide.window_due(relay_host.chats_window_fetched_at().get(account_id),
                                 of_ws.connected_since(account_id), _asked(account_id), prev is None):
            return False
        await window_read(account_id)
        _window_asked[account_id] = asked
        return True
    return step


def _wanted(planned_last: float | None) -> Callable[[str], Awaitable[bool]]:
    async def wanted(account_id: str) -> bool:
        why = "untracked" if account_id not in events.open_tab_accounts() else None
        if why is None and account_id not in set(await transaction_ingest.live_account_ids()):
            why = "unreadable"
        if why is None and _state.last.get(account_id) != planned_last:
            why = "refreshed"
        if why is not None:
            log.info("shared_refresher_job_dropped account=%s reason=%s", account_id, why)
            return False
        _in_flight.add(account_id)
        return True
    return wanted


def ask_time() -> tuple[float, int]:
    return _clock(), int(time.time() * 1000)


def note_refresh(account_id: str, asked: tuple[float, int]) -> None:
    global _state
    mono, ms = asked
    if mono <= _state.last.get(account_id, float("-inf")):
        return
    _state = decide.after_read(_state, account_id, True, mono)
    _at_ms[account_id] = ms


def last_refresh(account_id: str) -> float | None:
    return _state.last.get(account_id)


def cycle_for(account_id: str) -> float:
    return decide.cycle_s(view_lease.is_leased(account_id), account_id, KNOBS)


async def _job(account_id: str) -> bool:
    global _state
    asked, asked_ms = _clock(), int(time.time() * 1000)
    ok = False
    try:
        ok = await of_pacing.walk(account_id, "shared_refresher", lambda: _server().shared_refresher_reads(
            account_id, window=_window_step(account_id, asked))) is True
        if not ok:
            log.info("shared_refresher_read_discarded account=%s", account_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — held by the ladder; its `at` stays, so the age shows
        wait = app_open_warm.hold_on_429(account_id, exc)
        log.info("shared_refresher_read_failed account=%s error=%s hold_s=%s", account_id, type(exc).__name__,
                 "-" if wait is None else f"{wait:.0f}")
    finally:
        _in_flight.discard(account_id)
        _state = decide.after_read(_state, account_id, ok, asked)
        if ok:  # never back: a warm that asked later may have landed first (note_refresh)
            _at_ms[account_id] = max(asked_ms, _at_ms.get(account_id, asked_ms))
    return ok


async def tick() -> None:
    """One pass: who is Open-tab and readable, then the decision's effects."""
    global _state
    tracked = events.open_tab_accounts()
    live = set(await transaction_ingest.live_account_ids()) if tracked else set()
    readable = frozenset(a for a in tracked
                         if a in live and platforms.Lack.SHARED_REFRESH not in platforms.for_account(a).lacks)
    leased = frozenset(tracked & view_lease.leased_ids()) if tracked else frozenset()
    dead = frozenset(tracked & (await account_health.dead_session_map()).keys()) if tracked else frozenset()
    now_ms, prev_live = int(time.time() * 1000), {a: v["live"] for a, v in _state.shown.items()}
    for name, contributor in list(_contributors.items()):
        on_tick = getattr(contributor, "on_tick", None)
        if on_tick is not None:
            for aid in tracked:
                try:
                    on_tick(aid)
                except Exception:
                    log.warning("shared_refresher_tick_failed name=%s account=%s", name, aid, exc_info=True)
    inputs = decide.Inputs(now=_clock(), tracked=tracked, readable=readable,
                           warm_pending=frozenset(a for a in tracked if app_open_warm.pending(a)),
                           in_flight=frozenset(_in_flight), leased=leased,
                           ws_since={a: of_ws.connected_since(a) for a in readable}, dead=dead,
                           values={a: _values_of(a) for a in tracked} if _contributors else {})
    _state, effects = decide.plan(_state, inputs, KNOBS)
    for a in _state.live_since:
        if prev_live.get(a) != _state.shown[a]["live"]:
            _live_since_ms[a] = now_ms
    for e in effects:
        if isinstance(e, decide.Read):
            app_open_warm.refresh(e.account_id, _job, wanted=_wanted(_state.last.get(e.account_id)))
        else:
            _publish(e.account_id)


async def _loop() -> None:
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("shared_refresher_tick_failed", exc_info=True)
        await asyncio.sleep(TICK_S)


def start() -> asyncio.Task | None:
    global _task, _relay_loop
    if not ENABLED:
        return None
    _relay_loop = asyncio.get_running_loop()
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="shared-refresher")
    return _task


async def stop() -> None:
    global _task
    t, _task = _task, None
    if t is not None and not t.done():
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t


def fresh_at(account_ids: frozenset[str]) -> dict[str, int]:
    return {a: at for a in account_ids if (at := _at_ms.get(a)) is not None}
