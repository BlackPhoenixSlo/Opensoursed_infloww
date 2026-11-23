"""Badge reads, the shell (creator-badges phase 0C, ADR-0051). The OF counter is an input only: it reaches the
decide calls and the `badge_read` log line, never a publish (owner amendment #2)."""
from __future__ import annotations

import asyncio
import itertools
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

import app_open_warm
import badge_reads_decide as decide
import badge_watch
import event_transcode_decide as td
import events
import of_call_counter
import of_pacing
import of_ws
import proxies as proxy_registry
import proxy_health
import read_flip
import relay_cache
import relay_host
import shared_refresher
import unread_total
import unread_total_decide as utd
from unread_total_decide import _fan, _row_unread

log = logging.getLogger("of-relay.badge_reads")

MODE = os.environ.get("BADGE_READS", "").strip().lower() or "full"
if MODE not in ("full", "lean", "off"):
    log.warning("badge_reads_bad_knob BADGE_READS=%r; full", MODE)
    MODE = "full"
ENABLED = unread_total.ENABLED and MODE != "off"
GAP_MS = decide.GAP_MS.get(MODE, decide.GAP_MS["full"])
PAGE = 10
TICK_S = 1.0
MAX_FRAMES = 256
ARRIVALS_OUTSIDE_WINDOW = 64
PROXY_MS = 5000
POLL_MS = 15_000
SETTLE_POLL_S = 0.05


def _clock() -> int:
    return int(time.time() * 1000)


_lock = threading.Lock()
_frames: dict[str, list[int]] = {}              # Creator -> receipt times of counter frames not yet decided
_counter: dict[str, int] = {}                   # Creator -> the newest frame's OF counter
_seen_at: dict[str, int] = {}                   # Creator -> the newest frame's receipt time
_frame_n: dict[str, int] = {}                   # Creator -> counter frames received so far
_gates: dict[str, decide.Gate] = {}
_capped_at: dict[str, int] = {}                 # Creator -> when `badge_read_capped` was last logged
_sets: dict[str, decide.UnreadSet] = {}         # Creator -> the latest Unread set
_dms: dict[str, list[int]] = {}                 # Creator -> receipt times of recent inbound DMs
_echoes: dict[str, list[int]] = {}              # Creator -> receipt times of recent Creator echoes (Echo, Outbound)
_ids: dict[str, frozenset[int]] = {}            # Creator -> the restricted registry as of its last read
_muted: dict[tuple[str, int], bool] = {}        # (Creator, fan) -> a mute / unmute that went through the Relay
_intents: dict[str, tuple[decide.Intent, ...]] = {}
_intent_ids = itertools.count(1)
_reads: set[asyncio.Task] = set()               # the reads in flight (held: a bare task may be collected)
_proxy_down: frozenset[str] = frozenset()       # Open-tab Creators whose proxy is down, as of `_proxy_at`
_proxy_at: int | None = None
_capped: set[str] = set()                       # the gate answered Capped since the last admitted read
_polled: dict[str, int] = {}                    # Creator -> its last socket-down poll ask (first: the drop seen)
_queued: set[str] = set()                       # Creators a finished mass asked one window re-read for
_arrivals: dict[str, dict[int, dict[str, int]]] = {}   # Creator -> fan -> kind -> newest arrival (`utd.overlay`)
_task: asyncio.Task | None = None


@dataclass(frozen=True)
class UnreadView:
    fans: frozenset[int]
    asked_at: int


def unread_set(account_id: str) -> UnreadView | None:
    with _lock:
        s = _sets.get(str(account_id))
    return None if s is None else UnreadView(s.fans, s.at)


def rescore(account_id: str, window_rows: list[dict], restricted_ids: frozenset[int], as_of: int) -> bool:
    """With an Unread set held, R from it: rows a newer window holds and the registry as just loaded, so a restrict
    moves red at the next fold (a hover), not the next counter frame. Stamped at the set's own time, so a read that
    lands after the fold still writes. False when no set is held."""
    aid = str(account_id)
    with _lock:
        s = _sets.get(aid)
        if s is None:
            return False
        s = _sets[aid] = decide.refresh_rows(s, window_rows, as_of)
        ids = _ids[aid] = restricted_ids
        r = decide.restricted_unread(s, ids)
    unread_total.set_restricted_unread(aid, r, s.as_of)
    return True


def restricted_unread(account_id: str) -> int | None:
    aid = str(account_id)
    with _lock:
        s = _sets.get(aid)
        return None if s is None else decide.restricted_unread(s, _ids.get(aid, frozenset()))


_busts: dict[str, tuple[int, asyncio.Task[dict[str, int]]]] = {}    # Creator -> its last `?bust=` read's start, task


async def hover(account_id: str, read: Callable[[], Awaitable[dict[str, int]]],
                held: Callable[[], Awaitable[dict[str, int] | None]]) -> dict[str, int] | None:
    """Not an Attribution start: hover reads stay out of the gate and its hourly cap."""
    aid, now = str(account_id), _clock()
    with _lock:
        last = _busts.get(aid)
        verdict = decide.hover(None if last is None else last[0], last is not None and not last[1].done(), now,
                               MODE == "off", unread_total.ENABLED)
        if verdict == "read":
            last = _busts[aid] = (now, asyncio.create_task(_hover_read(aid, read), name=f"badge-hover:{aid}"))
    if verdict == "direct":
        return await read()
    if verdict == "held":
        return await held()
    return await asyncio.shield(last[1])


async def _hover_read(aid: str, read: Callable[[], Awaitable[dict[str, int]]]) -> dict[str, int]:
    value = await read()
    if value.get("as_of"):
        with _lock:
            counter = _counter.get(aid)
        log.info("badge_read account=%s kind=hover calls=- rows=%d counter=%s complete=- mismatch=- flips=0 "
                 "restricted=-", aid, len(unread_total._window_rows(aid) or ()), "-" if counter is None else counter)
    return value


@dataclass(frozen=True)
class _List:
    rows: list
    has_more: bool
    partial: bool
    calls: int
    asked_at: int
    frames_at_ask: int
    failed: BaseException | None = None     # page 2's error, kept for its 429 (the exit hold)
    sent_at: int | None = None              # page 1's answer time, past any pacer wait


def on_frame(account_id: str | None, event_type: str | None, event: Any) -> None:
    """Each frame at receipt. A DM or a Creator echo is recorded for the Amber overlay and re-folds amber whatever
    `BADGE_READS` says (Phase B's Knob on); the Unread set and the counter's reads only with badge reads on."""
    if not unread_total.ENABLED or not account_id:
        return
    try:
        aid, now = str(account_id), _clock()
        r = td.route(event)
        if r is not None and r[0] == "chat_message":
            k = td.dm_key(aid, r[2])
            if k is None:
                fan = _fan({"withUser": r[2].get("fromUser")})
                if fan is not None:
                    note_arrival(aid, fan, utd.DM, now)
                if ENABLED:
                    _on_dm(aid, r[2], now)
            elif isinstance(k, (td.Echo, td.Outbound)):
                if isinstance(k, td.Echo):
                    note_arrival(aid, k.fan_id, utd.ECHO, now)
                if ENABLED:
                    _on_echo(aid, k, now)
            _amber_refresh(aid)
            return
        if not ENABLED:
            return
        n = td.counter_of(event)
        if n is None:
            return
        with _lock:
            ts = _frames.setdefault(aid, [])
            ts.append(now)
            del ts[:-MAX_FRAMES]
            prev = _counter.get(aid)
            _counter[aid] = n
            _seen_at[aid] = now
            _frame_n[aid] = _frame_n.get(aid, 0) + 1
        if prev is not None and n < prev:
            badge_watch.on_drop(aid)
    except Exception:  # noqa: BLE001 — the pump must not stop on a frame
        log.warning("badge_reads_frame_failed account=%s", account_id, exc_info=True)


def _on_dm(aid: str, m: dict, now: int) -> None:
    fan = _fan({"withUser": m.get("fromUser")})
    row = unread_total._window_row(aid, fan) if fan is not None else None
    muted = _muted.get((aid, fan), isinstance(row, dict) and row.get("isMutedNotifications") is True)
    _apply(aid, None if fan is None else decide.DmIn(fan, now, muted), _dms, now)


def _on_echo(aid: str, echo: td.Echo | td.Outbound, now: int) -> None:
    if not isinstance(echo, td.Echo):
        _apply(aid, None, _echoes, now)
        return
    fan = echo.fan_id
    row = unread_total._window_row(aid, fan)
    prev = _apply(aid, decide.Echo(fan, now), _echoes, now)
    unread = row is not None and _row_unread(row)
    if unread:
        relay_cache.patch("list_chats", aid, _patcher({fan: 0}))
    if unread or (prev is not None and fan in prev.fans):
        read_flip.publish(aid, fan, 0, now)


def on_mute(chat_id: int, muted: bool) -> None:
    if not ENABLED:
        return
    try:
        aid = relay_host.request_account_header()
        if aid:
            with _lock:
                _muted[(str(aid), int(chat_id))] = bool(muted)
    except Exception:  # noqa: BLE001 — fire_mute does not catch: a raise would fail a mute that landed
        log.warning("badge_reads_mute_failed chat=%s", chat_id, exc_info=True)


def request_window_read(account_id: str) -> None:
    """A finished mass of 5+ (`event_transcode_decide.queue_reread`): one page-0 window re-read through the gate
    (`kind=queue`), so Fans it answered leave amber. No I/O; a request while one is pending joins it."""
    if not ENABLED:
        return
    try:
        with _lock:
            _queued.add(str(account_id))
    except Exception:  # noqa: BLE001 — the frame path must not stop on a re-read ask
        log.warning("badge_reads_queue_ask_failed account=%s", account_id, exc_info=True)


def _refresh_proxy_down(pumped: frozenset[str], now: int) -> None:
    global _proxy_down, _proxy_at
    _proxy_at = now
    try:
        bad = proxy_health.bad_reasons()
        _proxy_down = frozenset(a for a in pumped if bad and (proxy_registry.get_for_account(a) or {}).get("label")
                                in bad)
    except Exception:  # noqa: BLE001 — the last answer stands until the next refresh
        log.warning("badge_reads_proxy_check_failed", exc_info=True)


def _cause(aid: str, live: str | None) -> str | None:
    if live == "dead":
        return utd.DEAD
    if aid in _proxy_down:
        return utd.PROXY_DOWN
    return utd.CAPPED if aid in _capped else None


def record_intent(account_id: str, fan_id: int | None, *, at: int | None = None,
                  only_if_unread: bool = False) -> int | None:
    """A Write intent, recorded before the OF write (`at`: its pre-write time, else now); its id, None when not
    recorded."""
    if not ENABLED:
        return None
    try:
        aid, fan = str(account_id), None if fan_id is None else int(fan_id)
        held = unread_total._window_row(aid, fan) if only_if_unread and fan is not None else None
        if not decide.should_record(only_if_unread, held):
            return None
        created = _clock() if at is None else int(at)
        with _lock:
            iid = next(_intent_ids)
            _intents[aid] = (*_intents.get(aid, ()), decide.Intent(iid, fan, created))
        return iid
    except Exception:  # noqa: BLE001 — the write goes ahead; its frame may cost one read
        log.warning("badge_reads_intent_failed account=%s fan=%s", account_id, fan_id, exc_info=True)
        return None


def landed(intent_id: int | None) -> None:
    if intent_id is not None:
        now = _clock()
        with _lock:
            for aid, intents in _intents.items():
                _intents[aid] = decide.respond(intents, intent_id, now)


def retire(intent_id: int | None) -> None:
    if intent_id is not None:
        with _lock:
            for aid, intents in _intents.items():
                _intents[aid] = decide.retire(intents, intent_id)


def on_read_flip(account_id: str, fan_id: int | None, unread: int, at: int | None) -> None:
    """A read flip of ours that landed: ReadDone / UnreadDone on the held set, stamped `at` (before the write)."""
    if not ENABLED or at is None or (unread and fan_id is None):
        return
    try:
        fan = None if fan_id is None else int(fan_id)
        _apply(str(account_id), decide.UnreadDone(fan, at) if unread else decide.ReadDone(fan, at))
    except Exception:  # noqa: BLE001 — the write landed; the set waits for the next read
        log.warning("badge_reads_read_flip_failed account=%s fan=%s", account_id, fan_id, exc_info=True)


def _apply(aid: str, event: decide.SetEvent | None, times: dict[str, list[int]] | None = None,
           now: int = 0) -> decide.UnreadSet | None:
    """Records the arrival at `now` in `times` (when given) and applies `event` to the held set, under one lock; R is
    written after it when the set moved. Returns the set as it was."""
    with _lock:
        if times is not None:
            ts = times.setdefault(aid, [])
            ts.append(now)
            del ts[:-MAX_FRAMES]
        prev = _sets.get(aid)
        if prev is None or event is None:
            return prev
        s = _sets[aid] = decide.apply(prev, event)
        r = decide.restricted_unread(s, _ids.get(aid, frozenset()))
    if s is not prev:
        unread_total.set_restricted_unread(aid, r, s.as_of)
        _amber_refresh(aid)
    return prev


def _amber_refresh(aid: str) -> None:
    import accounts_admin_api  # noqa: PLC0415 — lazy: it imports this module's peers
    accounts_admin_api.amber_refresh(aid)


def note_arrival(account_id: str, fan_id: int, kind: str, at: int) -> None:
    aid, fan = str(account_id), int(fan_id)
    window = {f for row in unread_total._window_rows(aid) or () if (f := _fan(row)) is not None}
    with _lock:
        held = _arrivals.setdefault(aid, {})
        kinds = held.pop(fan, {})
        held[fan] = {**kinds, kind: max(at, kinds.get(kind, at))}
        others = [f for f in held if f not in window]
        for f in others[:max(0, len(others) - ARRIVALS_OUTSIDE_WINDOW)]:
            del held[f]


def arrivals(account_id: str) -> dict[int, dict[str, int]]:
    with _lock:
        return {f: dict(k) for f, k in _arrivals.get(str(account_id), {}).items()}


async def tick() -> None:
    if not ENABLED:
        return
    now, open_tabs = _clock(), events.open_tab_accounts()
    lives = {a: shared_refresher.live(a) for a in open_tabs}
    pumped = frozenset(a for a, v in lives.items() if v in ("up", "down"))
    if pumped and (_proxy_at is None or now - _proxy_at >= PROXY_MS):
        _refresh_proxy_down(pumped, now)
    eligible = pumped - _proxy_down
    for aid in open_tabs:
        unread_total.set_grey_cause(aid, _cause(aid, lives[aid]))
    down = {a for a in eligible if of_ws.connected_since(a) is None}
    asks: set[str] = set()
    with _lock:
        for aid in set(_polled) - down:
            del _polled[aid]
        for aid in down:
            if aid not in _polled:
                _polled[aid] = now
            elif now - _polled[aid] >= POLL_MS:
                _polled[aid] = now
                asks.add(aid)
        for aid, ts in list(_frames.items()):
            due = [t for t in ts if t + decide.DECIDE_AFTER_MS <= now]
            if not due:
                continue
            _frames[aid] = ts[len(due):]
            intents = _intents.get(aid, ())
            for t in due:
                ok, intents = decide.explain(t, _dms.get(aid, ()), _echoes.get(aid, ()), intents)
                if not ok:
                    asks.add(aid)
            if aid in _intents:
                _intents[aid] = intents
        for aid, intents in list(_intents.items()):
            _intents[aid] = decide.prune(intents, now)
            if not _intents[aid]:
                del _intents[aid]
        for held, window in ((_dms, decide.DM_WINDOW_MS), (_echoes, decide.ECHO_WINDOW_MS)):
            keep = now - decide.DECIDE_AFTER_MS - window
            for aid, ts in list(held.items()):
                held[aid] = [t for t in ts if t >= keep]
                if not held[aid]:
                    del held[aid]
        for aid in set(_sets) - eligible:
            del _sets[aid]
        asks |= {a for a, g in _gates.items() if g.pending}
        for aid in asks - eligible:
            if aid in _gates:
                _gates[aid] = replace(_gates[aid], pending=False)
        _queued.intersection_update(eligible)
        queued = set(_queued)
    for aid in sorted((asks | queued) & eligible):
        queue = aid not in asks     # an Attribution ask goes first; the queue's waits for the gate after it
        held = app_open_warm.exit_held_s(aid)
        with _lock:
            prev = _gates.get(aid, decide.Gate())
            _gates[aid], verdict = decide.admit(prev, now, GAP_MS, decide.CAP_PER_HOUR, held)
            if queue:
                if not isinstance(verdict, decide.Start):
                    # `pending` re-asks an Attribution read; a waiting queue ask stays in `_queued` instead.
                    _gates[aid] = replace(_gates[aid], pending=prev.pending)
                if not isinstance(verdict, decide.Wait):
                    _queued.discard(aid)
            capped_log = not queue and isinstance(verdict, decide.Capped) \
                and now - _capped_at.get(aid, -decide.HOUR_MS) >= decide.HOUR_MS
            if capped_log:
                _capped_at[aid] = now
            was = aid in _capped
            if isinstance(verdict, decide.Capped) and not queue:
                _capped.add(aid)
            elif isinstance(verdict, decide.Start):
                _capped.discard(aid)
            flip = was != (aid in _capped)
        if flip:
            unread_total.set_grey_cause(aid, _cause(aid, lives.get(aid)))
        if capped_log:
            log.info("badge_read_capped account=%s", aid)
        if isinstance(verdict, decide.Start):
            read = _queue_read(aid) if queue else _read(aid, "poll" if aid in down else "frame")
            t = asyncio.create_task(read, name=f"badge-read:{aid}")
            _reads.add(t)
            t.add_done_callback(lambda _t, a=aid: _read_done(_t, a))


def _read_done(task: asyncio.Task, account_id: str) -> None:
    _reads.discard(task)
    sent_at = None if task.cancelled() or task.exception() is not None else task.result()
    with _lock:
        if account_id in _gates:
            _gates[account_id] = decide.done(_gates[account_id], sent_at)


def _list_unread(account_id: str) -> _List:
    client = relay_host.load_client(account_id)
    with relay_host.priority_lane_background(account_id):
        asked_at = _clock()
        with _lock:
            frames_at_ask = _frame_n.get(account_id, 0)
        pages: list[list] = []
        has_more, failed, sent_at = False, None, None
        for offset in (0, PAGE):
            if offset and (len(pages[0]) < PAGE or not has_more):
                break
            try:
                body = client.list_chats(limit=PAGE, offset=offset, filter="unread") or {}
            except Exception as exc:  # noqa: BLE001 — page 1's raises; page 2's leaves the read partial
                if not offset:
                    raise
                failed = exc
                log.info("badge_read_page2_failed account=%s error=%s", account_id, type(exc).__name__)
                break
            sent_at = sent_at or _clock()
            pages.append(body.get("list") or [])
            has_more = bool(body.get("hasMore"))
    rows, seen, dup_only = [], set(), False
    for i, page in enumerate(pages):
        added = 0
        for r in page:
            f = _fan(r)
            if f not in seen:
                seen.add(f)
                rows.append(r)
                added += 1
        dup_only = dup_only or (i > 0 and bool(page) and added == 0)
    return _List(rows, has_more, failed is not None or dup_only, len(pages) + (failed is not None), asked_at,
                 frames_at_ask, failed, sent_at)


def _patcher(changes: dict[int, int]):
    from accounts_admin_api import _ROSTER_WINDOW_KEY  # noqa: PLC0415 — lazy: it imports this module's peers

    def _fn(extras: tuple, value: Any) -> Any:
        if extras != _ROSTER_WINDOW_KEY or not isinstance(value, dict):
            return None
        key = "list" if "list" in value else "chats"
        rows = []
        for r in value.get(key) or []:
            u = changes.get(_fan(r))
            if u is None:
                rows.append(r)
            else:
                n = int(r.get("unreadMessagesCount") or 0)
                rows.append({**r, "hasUnread": bool(u), "unreadMessagesCount": max(1, n) if u else 0})
        return {**value, key: rows}
    return _fn


def _hold(account_id: str, exc: BaseException) -> None:
    wait = app_open_warm.hold_on_429(account_id, exc)
    if wait is not None:
        log.info("badge_read_429_hold account=%s hold_s=%.0f", account_id, wait)


async def _settle(aid: str, counted: int, counter: int, asked_at: int) -> tuple[int, bool]:
    end = time.monotonic() + decide.FRAME_LAG_MS / 1000
    while time.monotonic() < end:
        await asyncio.sleep(SETTLE_POLL_S)
        with _lock:
            counter, frame_at = _counter.get(aid, counter), _seen_at.get(aid)
        if decide.settled(counted, counter, frame_at, asked_at):
            return counter, True
    return counter, False


async def _read(account_id: str, kind: str) -> int | None:
    aid = account_id
    try:
        got = await of_pacing.walk(aid, "badge_attribution", lambda: asyncio.to_thread(_list_unread, aid))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a failed read flips nothing; the next frame asks again
        got = None
        log.info("badge_read_failed account=%s error=%s", aid, type(exc).__name__)
        _hold(aid, exc)
    finally:
        app_open_warm.note_read(aid)
    if got is not None and got.failed is not None:
        _hold(aid, got.failed)
    if got is not None:
        try:
            from automations._common import load_of_restricted_ids  # noqa: PLC0415 — lazy: DB layer
            ids = frozenset(await load_of_restricted_ids(aid))
            with _lock:
                _ids[aid] = ids
        except Exception:  # noqa: BLE001 — R falls back to the registry of the last read
            log.warning("badge_read_registry_failed account=%s", aid, exc_info=True)
    with _lock:
        counter = None if kind == "poll" else _counter.get(aid)
        since = 0 if got is None else _frame_n.get(aid, 0) - got.frames_at_ask
    if got is None:
        log.info("badge_read account=%s kind=%s calls=1 rows=0 counter=%s complete=0 mismatch=0 flips=0 "
                 "restricted=-", aid, kind, "-" if counter is None else counter)
        return None
    asked_at = got.asked_at
    complete = decide.complete(got.rows, got.has_more, got.partial, counter, since, got.calls)
    mismatch = decide.mismatch(got.rows, got.has_more, got.partial, counter, since, got.calls)
    if decide.settles(got.calls, mismatch):
        counter, complete = await _settle(aid, decide._counted(got.rows), counter, asked_at)
        mismatch = not complete
    flips: list[tuple[int, int]] = []
    r: int | None = None
    try:
        with _lock:
            prev = _sets.get(aid)
            flips = decide.diff(unread_total._window_rows(aid), prev, got.rows, complete, asked_at)
            s = _sets[aid] = decide.replace_set(prev, got.rows, asked_at, complete)
            r = decide.restricted_unread(s, _ids.get(aid, frozenset()))
        unread_total.set_restricted_unread(aid, r, s.as_of)
        if kind == "poll" and complete:
            unread_total.observe_poll(aid, sum(1 for row in got.rows if utd.of_counts(row)), asked_at)
        if flips:
            relay_cache.patch("list_chats", aid, _patcher(dict(flips)))
        for fan, unread in flips:
            read_flip.publish(aid, fan, unread, asked_at)
        _amber_refresh(aid)
    except Exception:  # noqa: BLE001 — the read landed; a missed diff waits for the next frame
        log.warning("badge_read_diff_failed account=%s", aid, exc_info=True)
    log.info("badge_read account=%s kind=%s calls=%d rows=%d counter=%s complete=%d mismatch=%d flips=%d "
             "restricted=%s", aid, kind, got.calls, len(got.rows), "-" if counter is None else counter,
             int(complete), int(mismatch), len(flips), "-" if r is None else r)
    return got.sent_at


def _walk_calls(account_id: str, kind: str) -> int:
    return sum(n for caller, _path, aid, _s, n in of_call_counter.snapshot()["rows"]
               if caller == f"walk:{kind}" and aid == account_id)


async def _queue_read(account_id: str) -> None:
    """The mass's window re-read: the one page-0 reader (it publishes flips), paced as a background walk."""
    aid = account_id
    before = _walk_calls(aid, "badge_queue")
    try:
        await of_pacing.walk(aid, "badge_queue", lambda: shared_refresher.window_read(aid))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a failed re-read leaves amber to the next window read
        log.info("badge_read_failed account=%s kind=queue error=%s", aid, type(exc).__name__)
        _hold(aid, exc)
    finally:
        app_open_warm.note_read(aid)
    log.info("badge_read account=%s kind=queue calls=%d rows=%d counter=- complete=- mismatch=- flips=- "
             "restricted=-", aid, _walk_calls(aid, "badge_queue") - before, len(unread_total._window_rows(aid) or ()))


async def _loop() -> None:
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.warning("badge_reads_tick_failed", exc_info=True)
        await asyncio.sleep(TICK_S)


def start() -> asyncio.Task | None:
    global _task
    if not ENABLED:
        return None
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="badge-reads")
    return _task
