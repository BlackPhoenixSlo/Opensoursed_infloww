"""
The Shared refresher (docs/spec/watched-creator-refresher/phase-01-shared-refresher.md, ADR-0042): the shell. Off
unless `SHARED_REFRESHER=1` (read once at import): off, no loop, no event, no OF call.

One asyncio task (`start()` / `stop()`, the server's lifecycle) ticks every TICK_S: `events.open_tab_accounts()` is
`tracked`; `readable` = tracked ∩ `transaction_ingest.live_account_ids()` (no dead, deactivated or session-less
Creator), OnlyFans only; `leased` = tracked ∩ `view_lease.leased_ids()` (the lease tier: a lease only picks the tier,
it tracks nothing); `dead` = tracked ∩ `account_health.dead_session_map()`; `ws_since` = `of_ws.connected_since`
per readable Creator (the Live connection's stamp); then `shared_refresher_decide.plan` (the pure decision: who is
due, who changed). Each `Read` is one job on the Creator's proxy exit through the App-open warm's gate
(`app_open_warm.refresh`): one background walk, Caller kind `walk:shared_refresher`, running the server's `shared_refresher_reads` (`/users/me`
through the OF client, bypassing the cache, at background priority; then, kept and `decide.window_due` asked after
it, the chats window through `window_read`, the one page-0 window hook: a reader `set_window_reader` registered, else
the roster rewarm; at most one landed window read per Creator per Cycle). A job counts as in flight from its turn (when
the gate asks `wanted`) until its walk ends, so a queued job a warm displaced, or the gate dropped, marks nothing
and the Creator is planned again on the next tick (the gate's one entry per Creator keeps a still-queued one from
doubling). At its turn a job is dropped unread when its Creator left `tracked`, left `live_account_ids()` or got a
Last refresh since it was planned (`_wanted`); with no tab open `tracked` is empty, so no job is planned at all.
A landed read whose write-back was kept writes the Creator's Last refresh (`at` = its ask time); a failed or
discarded one leaves `at` and holds it `max(FLOOR_S, ladder_s(n))` (decide.after_read); a terminal 429 also holds
the Creator's whole exit for OF's asked wait, else `app_open_warm.HOLD_FLOOR_S` (`app_open_warm.hold`: 429s follow the proxy IP).
Netting (ADR-0044): one Last refresh per Creator, written by whichever of the refresher or the App-open warm landed:
the warm's kept `/users/me` calls `note_refresh` (server.app_open_warm_reads, refresher on), and the warm's reuse
decision reads `last_refresh` and `cycle_for` (app_open_warm._decide).
Each `Publish` is one `creator_refreshed` (events_decide: any-scope, coalesced per Creator) carrying the Creator's
snapshot `{account_id, boot, seq, now, at, cycle_s, live, live_since, values}` (P1 Contract 1). `values[name]` is a
registered contributor's `snapshot(aid)` (P1 Contract 8; none registered: `{}`), read from memory, 0 OF calls; a value
moved off-Cycle calls `note_values(aid)` from any thread, and the loop re-reads and publishes when `changed` (a
slot's own `at` alone is no change). A `live` flip (socket drop or reconnect, a Dead session) publishes within one
tick with no read; `live_since` is the epoch ms of the tick that first saw `live` take its current value (null while
`live` is null). All state is in Relay memory: a restart forgets it and spreads its first reads over FLOOR_S.

Knobs: SHARED_REFRESHER (0 | 1), SHARED_REFRESHER_LEASE_CYCLE_S (120), SHARED_REFRESHER_TAB_CYCLE_S (600, never
below the lease cycle); both clamp to FLOOR_S 60 (in `decide.cycle_s`, with SPREAD 0.1: each Creator's Cycle is
0.9-1.0 x its tier).

Machine cost at 50 Creators, ~30 tabs (P1 "Machine cost"): a tick is a union over <= 30 clamps of <= 50 ids, the
lease union and `plan` over <= 50 Creators, under 1 ms (g), plus 3 small DB reads per TICK_S (`live_account_ids`'
2 and the Dead-session map, i).
Reads <= 0.3/s, <= 1 worker thread per exit at once (5-10 exits, i). Events <= 10/min plus `live` flips, deliveries
<= 10 x 30 tabs = 5/s (i). State: 4 small dicts per Creator, <= 50 KB (g). CPU under 1 % of one core (g).
"""
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
                     tab_cycle_s=env_float("SHARED_REFRESHER_TAB_CYCLE_S", 600.0, 0.0))   # clamped in decide
TICK_S = 5.0
BOOT_MS = int(time.time() * 1000)       # the snapshot's `boot`: a tab compares (boot, seq)

_clock = time.monotonic                 # Last refresh's clock (tests inject one)
_state = decide.State()
_in_flight: set[str] = set()
_at_ms: dict[str, int] = {}             # Creator -> its Last refresh, epoch ms (the snapshot's `at`)
_seq: dict[str, int] = {}               # Creator -> publishes this boot
_live_since_ms: dict[str, int] = {}     # Creator -> epoch ms of the tick that set its `_state.live_since`
_task: asyncio.Task | None = None
_relay_loop: asyncio.AbstractEventLoop | None = None   # where `start()` ran: `note_values` hands work there
_contributors: dict[str, Any] = {}               # name -> contributor (`snapshot(aid)`, optional `window_due(aid)`)
_window_reader: Callable[[str], Awaitable[Any]] | None = None   # P1 Contract 9 (Phase 2's); None: the roster rewarm
_window_asked: dict[str, float] = {}    # Creator -> ask time of the Cycle whose window read landed (one per Cycle)


def _server():
    return relay_host.live_server()


def snapshot(account_id: str) -> dict[str, Any]:
    """The Creator's `Freshness` (P1 Contract 1) as of now."""
    v = _state.shown.get(account_id) or {"cycle_s": None, "live": None, "values": {}}
    return {"account_id": account_id, "boot": BOOT_MS, "seq": _seq.get(account_id, 0),
            "now": int(time.time() * 1000), "at": _at_ms.get(account_id),
            "cycle_s": None if v["cycle_s"] is None else int(v["cycle_s"]), "live": v["live"],
            "live_since": _live_since_ms.get(account_id) if account_id in _state.live_since else None,
            "values": _values_of(account_id)}


def live(account_id: str) -> str | None:
    """The Open-tab Creator's `live` as of the last tick (`decide.live_of`: "up" | "down" | "dead" | None)."""
    return (_state.shown.get(str(account_id)) or {}).get("live")


def register(name: str, contributor: Any) -> None:
    """P1 Contract 8: `contributor.snapshot(aid) -> JSON | None` rides `values[name]` (None: null); its optional
    `window_due(aid) -> bool` is asked after read 1 (ticket 19). An optional `on_tick(aid)` runs for each
    tracked account before the tick reads contributor values. Its state sits behind its own `threading.Lock`."""
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
    """A contributor's value moved (any thread): re-read and publish on the Relay loop. Not started: nothing."""
    loop = _relay_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(_values_noted, account_id)


def _values_noted(account_id: str) -> None:
    """On the loop: a tracked Creator whose values `changed` is published once; untracked waits for its next track."""
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
    """P1 Contract 9: the one page-0 chats window reader (Phase 2's); None: back to the roster rewarm."""
    global _window_reader
    _window_reader = fn


async def window_read(account_id: str) -> Any:
    """P1 Contract 9: read the Creator's page-0 chats window through the registered reader, else
    `accounts_admin_api.rewarm_roster_count` (one live read, rewarming the Fan List's page 0 and the roster count).
    With the refresher on, the Cycle's window step and the App-open warm's step 2 read it only here. Raises what the
    read raised."""
    fn = _window_reader
    if fn is not None:
        return await fn(account_id)
    import accounts_admin_api           # loaded by the server; not at import (it reads the live server)
    return await accounts_admin_api.rewarm_roster_count(account_id)


def _asked(account_id: str) -> bool:
    """A contributor asks for the window (its optional `window_due`); one that raises asks nothing."""
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
    """The Cycle's read 2, run by the reads helper after `/users/me` landed and was kept (inside its background
    scope, so the window holds the Creator's background lane): `decide.window_due` asked now (a contributor's
    observer ran inside read 1), at most one landed window read per Creator per Cycle (ask times a Cycle apart),
    whatever asked. True when it read."""
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
    """The gate's at-turn check for a job planned when the Creator's Last refresh was `planned_last` (P1 Pacing):
    still tracked (a tab still open on it), still in `live_account_ids()` (not dead, deactivated or session-less),
    and no Last refresh landed since; else dropped unread. Wanted: from here it is in flight until its walk ends."""
    async def wanted(account_id: str) -> bool:
        why = "untracked" if account_id not in events.open_tab_accounts() else None
        if why is None and account_id not in set(await transaction_ingest.live_account_ids()):
            why = "unreadable"
        if why is None and _state.last.get(account_id) != planned_last:   # after the await: no race with a landing
            why = "refreshed"
        if why is not None:
            log.info("shared_refresher_job_dropped account=%s reason=%s", account_id, why)
            return False
        _in_flight.add(account_id)
        return True
    return wanted


def ask_time() -> tuple[float, int]:
    """A read's ask time: (`_clock`, the Last refresh's clock; epoch ms, the snapshot's `at`)."""
    return _clock(), int(time.time() * 1000)


def note_refresh(account_id: str, asked: tuple[float, int]) -> None:
    """Netting (ADR-0044): the App-open warm's `/users/me` landed from OF, its write-back kept, and its other reads
    landed: the Creator's one Last refresh is that read's ask time (`ask_time()` taken before it), so the refresher
    reads it next at its slot and drops a job planned before (`_wanted`). Never moves it back. A cache hit, a
    discarded write-back or a failed warm calls nothing."""
    global _state
    mono, ms = asked
    if mono <= _state.last.get(account_id, float("-inf")):
        return
    _state = decide.after_read(_state, account_id, True, mono)
    _at_ms[account_id] = ms


def last_refresh(account_id: str) -> float | None:
    """The Creator's Last refresh (`_clock`, time.monotonic), None when none since boot: the warm's reuse age."""
    return _state.last.get(account_id)


def cycle_for(account_id: str) -> float:
    """The Creator's Cycle now (its lease tier while it holds a View lease, else the tab tier): the warm's reuse
    window, the one number the refresher schedules and publishes (`decide.cycle_s`)."""
    return decide.cycle_s(view_lease.is_leased(account_id), account_id, KNOBS)


async def _job(account_id: str) -> bool:
    """One Cycle's reads for one Creator (the gate runs it as its own task); True when they landed and their
    write-back was kept. Else `at` stays (the age shows) and the Creator climbs the Backoff ladder; a terminal 429
    also holds its whole exit for OF's asked wait (`app_open_warm.hold_on_429`)."""
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
        if ok:      # never back: a warm that asked later may have landed first (note_refresh)
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
            _live_since_ms[a] = now_ms          # this tick first saw `live` take its value (decide restarted it)
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
    """Start the loop (once) when ENABLED; else nothing."""
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
    """The ping's `fresh` (P1 Contract 7): `{aid: at}` for each of `account_ids` with a Last refresh (epoch ms)."""
    return {a: at for a in account_ids if (at := _at_ms.get(a)) is not None}
