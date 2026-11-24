from __future__ import annotations

import asyncio
import itertools
import logging
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Mapping

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
import relay_host
import shared_refresher
import unread_total
import unread_total_decide as utd
from unread_total_decide import window_fan_id, _row_unread

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
_frames: dict[str, list[decide.CounterFrame]] = {}
_counter: dict[str, int] = {}                   # Creator -> the newest frame's OF counter
_seen_at: dict[str, int] = {}                   # Creator -> the newest frame's receipt time
_frame_n: dict[str, int] = {}                   # Creator -> counter frames received so far
_gates: dict[str, decide.Gate] = {}
_first_read_events: dict[str, decide.UnreadSet] = {}
_sets: dict[str, decide.UnreadSet] = {}         # Creator -> the latest Unread set
_dms: dict[str, list[decide.Activity]] = {}
_echoes: dict[str, list[decide.Activity]] = {}
_echo_ids: dict[str, dict[str, None]] = {}
_replied: dict[tuple[str, int], tuple[bool | None, int]] = {}  # (Creator, fan) -> his state before our reply, landed at
_retry_due: set[str] = set()
_ids: dict[str, frozenset[int]] = {}            # Creator -> the restricted registry as of its last read
_muted: dict[tuple[str, int], tuple[bool, int]] = {}   # (Creator, fan) -> a mute / unmute through the Relay, landed at
_intents: dict[str, tuple[decide.Intent, ...]] = {}
_intent_ids = itertools.count(1)
_reads: set[asyncio.Task] = set()               # the reads in flight (held: a bare task may be collected)
_proxy_down: frozenset[str] = frozenset()       # Open-tab Creators whose proxy is down, as of `_proxy_at`
_proxy_at: int | None = None
_polled: dict[str, int] = {}                    # Creator -> its last socket-down poll ask (first: the drop seen)
_queued: set[str] = set()                       # Creators a finished mass asked one window re-read for
_arrivals: dict[str, dict[int, dict[str, int]]] = {}   # Creator -> fan -> kind -> newest arrival (`utd.overlay`)
_latest_message_at: dict[tuple[str, int], int] = {}
_task: asyncio.Task | None = None


@dataclass(frozen=True)
class UnreadView:
    fans: frozenset[int]
    asked_at: int


def unread_set(account_id: str) -> UnreadView | None:
    with _lock:
        s = _sets.get(str(account_id))
    return None if s is None else UnreadView(s.fans, s.at)


def rescore(account_id: str, window_rows: list[dict] | None, restricted_ids: frozenset[int], as_of: int) -> None:
    aid = str(account_id)
    with _lock:
        s = _sets.get(aid)
        if s is not None:
            for row in window_rows or ():
                fan = window_fan_id(row)
                if fan is None or fan not in s.entries:
                    continue
                mute = _muted.get((aid, fan))
                window_mute = row.get("isMutedNotifications")
                if mute is not None and isinstance(window_mute, bool) and as_of > max(mute[1], s.entries[fan][1]):
                    _muted[(aid, fan)] = (window_mute, as_of)
            s = _sets[aid] = decide.refresh_rows(s, window_rows or [], as_of)
            _ids[aid] = restricted_ids
        elif window_rows is not None:
            s = decide.replace_set(None, window_rows, as_of, True)
    if s is not None:
        _publish_restricted(aid, s, restricted_ids)


def patch_restriction(aid: str, fan: int, change: Callable[[dict], dict]) -> None:
    with _lock:
        state = _sets.get(aid)
        if state is not None and fan in state.entries:
            row, stamp = state.entries[fan]
            if row is not None:
                _sets[aid] = replace(state, entries={**state.entries, fan: (change(row), stamp)})


def _score_restricted(aid: str, s: decide.UnreadSet, ids: frozenset[int]) -> utd.Restricted:
    mutes = {f: mute for f in s.entries if (mute := _muted.get((aid, f))) is not None}
    return decide.restricted_unread(s, ids, mutes)


def _publish_restricted(aid: str, s: decide.UnreadSet, ids: frozenset[int]) -> int:
    with _lock:
        r = _score_restricted(aid, s, ids)
    unread_total.set_restricted_unread(aid, r, s.as_of)
    return r.n


def restricted_unread(account_id: str) -> int | None:
    aid = str(account_id)
    with _lock:
        s = _sets.get(aid)
        return None if s is None else _score_restricted(aid, s, _ids.get(aid, frozenset())).n


_busts: dict[str, tuple[int, asyncio.Task[dict[str, int]]]] = {}    # Creator -> its last `?bust=` read's start, task


async def hover(account_id: str, read: Callable[[], Awaitable[dict[str, int]]],
                held: Callable[[], Awaitable[dict[str, int] | None]]) -> dict[str, int] | None:
    """Not an Attribution start: hover reads stay out of the gate."""
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
    if not unread_total.ENABLED or not account_id:
        return
    try:
        aid, now = str(account_id), _clock()
        r = td.route(event)
        if r is not None and r[0] == "chat_message":
            k = td.dm_key(aid, r[2])
            if k is None:
                fan = window_fan_id({"withUser": r[2].get("fromUser")})
                if fan is not None:
                    note_arrival(aid, fan, utd.DM, now, message_at=_message_at(r[2], now))
                    if ENABLED:
                        _on_dm(aid, fan, now)
            elif isinstance(k, (td.Echo, td.Outbound)):
                _on_echo(aid, k, r[2], now)
            _amber_refresh(aid)
            return
        n = td.counter_of(event)
        if n is None:
            return
        with _lock:
            prev = _counter.get(aid)
            if ENABLED:
                ts = _frames.setdefault(aid, [])
                ts.append(decide.CounterFrame(now, None if prev is None else n - prev))
                del ts[:-MAX_FRAMES]
                _seen_at[aid] = now
                _frame_n[aid] = _frame_n.get(aid, 0) + 1
            _counter[aid] = n
        if prev is not None and n < prev:
            badge_watch.on_drop(aid)
    except Exception:  # noqa: BLE001 — the pump must not stop on a frame
        log.warning("badge_reads_frame_failed account=%s", account_id, exc_info=True)


def _message_at(message: dict, now: int) -> int:
    return utd.created_ms({"lastMessage": message}) or now


def _on_dm(aid: str, fan: int, now: int) -> None:
    row = unread_total._window_row(aid, fan)
    own = _muted.get((aid, fan))
    muted = own[0] if own is not None else row is not None and row.get("isMutedNotifications") is True
    prior = decide.prior_unread(_sets.get(aid), fan, row)
    delta = decide.expected_delta("dm", muted, prior)
    _apply(aid, decide.DmIn(fan, now, muted), _dms, decide.Activity(now, fan, delta))


def _on_echo(aid: str, echo: td.Echo | td.Outbound, message: dict, now: int) -> None:
    if echo.message_id:
        key = str(echo.message_id)
        with _lock:
            seen = _echo_ids.setdefault(aid, {})
            if key in seen:
                return
            seen[key] = None
            if len(seen) > MAX_FRAMES:
                del seen[next(iter(seen))]
    if isinstance(echo, td.Outbound):
        if ENABLED:
            _apply(aid, None, _echoes, decide.Activity(now, None, None))
        return
    fan, at = echo.fan_id, _message_at(message, now)
    row = unread_total._window_row(aid, fan)
    row_at = utd.created_ms(row) if row is not None else None
    if decide.echo_is_stale(at, row_at, _latest_message_at.get((aid, fan))):
        return
    note_arrival(aid, fan, utd.ECHO, now, message_at=at)
    if not ENABLED:
        return
    with _lock:
        replied = _replied.pop((aid, fan), None)
    prior = decide.echo_prior(_sets.get(aid), fan, row, replied, now)
    delta = decide.expected_delta("echo", False, prior)
    prev = _apply(aid, decide.Echo(fan, now), _echoes, decide.Activity(now, fan, delta))
    unread = row is not None and _row_unread(row)
    if unread:
        patch_window_read_and_mute(aid, {fan: 0})
    if unread or (prev is not None and fan in prev.fans):
        read_flip.publish(aid, fan, 0, now)


def on_mute(aid: str, chat_id: int, muted: bool) -> None:
    aid = str(aid) if aid else ""
    if ENABLED and aid:
        with _lock:
            fan = int(chat_id)
            _muted[(aid, fan)] = (bool(muted), _clock())
            s = _sets.get(aid)
            ids = _ids.get(aid, frozenset())
        if s is not None and fan in s.entries:
            _publish_restricted(aid, s, ids)
    try:
        patch_window_read_and_mute(aid, mutes={chat_id: muted})
    except Exception:  # noqa: BLE001
        log.warning("amber_mute_patch_failed account=%s fan=%s", aid, chat_id, exc_info=True)
    _amber_refresh(aid)


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
    return None


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


def on_reply(account_id: str, fan_id: int, at: int) -> None:
    if ENABLED:
        try:
            aid, fan, now = str(account_id), int(fan_id), _clock()
            prior = decide.prior_unread(_sets.get(aid), fan, unread_total._window_row(aid, fan))
            with _lock:
                _replied[(aid, fan)] = decide.reply_prior(_replied.get((aid, fan)), prior, now)
        except Exception:  # noqa: BLE001 — the send landed; its echo falls back to the held state
            log.warning("badge_reads_reply_failed account=%s fan=%s", account_id, fan_id, exc_info=True)
    on_read_flip(account_id, fan_id, 0, at)


def on_read_flip(account_id: str, fan_id: int | None, unread: int, at: int | None) -> None:
    """A read flip of ours that landed: ReadDone / UnreadDone on the held set, stamped `at` (before the write)."""
    if not ENABLED or at is None or (unread and fan_id is None):
        return
    try:
        fan, now = None if fan_id is None else int(fan_id), _clock()
        _apply(str(account_id), decide.UnreadDone(fan, at, now) if unread else decide.ReadDone(fan, at, now))
    except Exception:  # noqa: BLE001 — the write landed; the set waits for the next read
        log.warning("badge_reads_read_flip_failed account=%s fan=%s", account_id, fan_id, exc_info=True)


def _apply(aid: str, event: decide.SetEvent | None, times: dict[str, list[decide.Activity]] | None = None,
           activity: decide.Activity | None = None) -> decide.UnreadSet | None:
    with _lock:
        if times is not None and activity is not None:
            ts = times.setdefault(aid, [])
            ts.append(activity)
            del ts[:-MAX_FRAMES]
        prev = _sets.get(aid)
        if event is None:
            return prev
        if prev is None:
            if aid in _first_read_events:
                _first_read_events[aid] = decide.apply(_first_read_events[aid], event)
            return None
        s = _sets[aid] = decide.apply(prev, event)
        ids = _ids.get(aid, frozenset())
    if s is not prev:
        _publish_restricted(aid, s, ids)
        _amber_refresh(aid)
    return prev


def _amber_refresh(aid: str) -> None:
    import accounts_admin_api  # noqa: PLC0415 — lazy: it imports this module's peers
    accounts_admin_api.amber_refresh(aid)


def note_arrival(account_id: str, fan_id: int, kind: str, at: int, *, message_at: int | None = None) -> None:
    aid, fan = str(account_id), int(fan_id)
    window = {f for row in unread_total._window_rows(aid) or () if (f := window_fan_id(row)) is not None}
    with _lock:
        if message_at is not None:
            previous = _latest_message_at.get((aid, fan), message_at)
            _latest_message_at[(aid, fan)] = max(message_at, previous)
        held = _arrivals.setdefault(aid, {})
        kinds = held.pop(fan, {})
        held[fan] = {**kinds, kind: max(at, kinds.get(kind, at))}
        others = [f for f in held if f not in window]
        for f in others[:max(0, len(others) - ARRIVALS_OUTSIDE_WINDOW)]:
            del held[f]
            _latest_message_at.pop((aid, f), None)


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
            due = [t for t in ts if t.at + decide.DECIDE_AFTER_MS <= now]
            if not due:
                continue
            _frames[aid] = ts[len(due):]
            intents, dms, echoes = _intents.get(aid, ()), _dms.get(aid, ()), _echoes.get(aid, ())
            for t in due:
                ok, dms, echoes, intents = decide.explain(t, dms, echoes, intents)
                if not ok:
                    asks.add(aid)
            for held, acts in ((_intents, intents), (_dms, list(dms)), (_echoes, list(echoes))):
                if aid in held:
                    held[aid] = acts
        for aid, intents in list(_intents.items()):
            _intents[aid] = decide.prune(intents, now)
            if not _intents[aid]:
                del _intents[aid]
        for held, window in ((_dms, decide.DM_WINDOW_MS), (_echoes, decide.ECHO_WINDOW_MS)):
            keep = now - decide.DECIDE_AFTER_MS - window
            for aid, ts in list(held.items()):
                held[aid] = [t for t in ts if t.at >= keep]
                if not held[aid]:
                    del held[aid]
        for key, (_prior, landed_at) in list(_replied.items()):
            if now - landed_at > decide.ECHO_WINDOW_MS:
                del _replied[key]
        for aid in set(_sets) - eligible:
            del _sets[aid]
        _retry_due.intersection_update(eligible)
        asks |= _retry_due
        asks |= {a for a, g in _gates.items() if g.pending}
        for aid in asks - eligible:
            if aid in _gates:
                _gates[aid] = replace(_gates[aid], pending=False)
        _queued.intersection_update(eligible)
        queued = set(_queued)
    for aid in sorted((asks | queued) & eligible):
        held = app_open_warm.exit_held_s(aid)
        with _lock:
            prev = _gates.get(aid, decide.Gate())
            _gates[aid], verdict = decide.admit(prev, now, GAP_MS, held, attribution=aid in asks, queued=aid in queued)
            if isinstance(verdict, decide.Start) and verdict.queue:
                _queued.discard(aid)
        if isinstance(verdict, decide.Start):
            read = _queue_read(aid) if verdict.queue else _read(aid, "poll" if aid in down else "frame")
            t = asyncio.create_task(read, name=f"badge-read:{aid}")
            _reads.add(t)
            t.add_done_callback(lambda _t, a=aid: _read_done(_t, a))


def _read_done(task: asyncio.Task, account_id: str) -> None:
    _reads.discard(task)
    sent_at = None if task.cancelled() or task.exception() is not None else task.result()
    with _lock:
        _first_read_events.pop(account_id, None)
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
            f = window_fan_id(r)
            if f not in seen:
                seen.add(f)
                rows.append(r)
                added += 1
        dup_only = dup_only or (i > 0 and bool(page) and added == 0)
    return _List(rows, has_more, failed is not None or dup_only, len(pages) + (failed is not None), asked_at,
                 frames_at_ask, failed, sent_at)


def patch_window_read_and_mute(
    aid: str, changes: Mapping[int, int] | None = None, mutes: Mapping[int, bool] | None = None,
) -> None:
    import accounts_admin_api
    changes, mutes = changes or {}, mutes or {}

    def patch(row: dict, fan: int) -> dict:
        unread = changes.get(fan)
        if unread is not None:
            row = utd.unread_row(row, unread)
        if fan in mutes:
            row = {**row, "isMutedNotifications": mutes[fan]}
        return row

    accounts_admin_api.patch_window(aid, {fan: lambda row, f=fan: patch(row, f)
                                           for fan in changes.keys() | mutes.keys()})


def _hold(account_id: str, exc: BaseException) -> bool:
    wait = app_open_warm.hold_on_429(account_id, exc)
    if wait is None:
        return False
    log.info("badge_read_429_hold account=%s hold_s=%.0f", account_id, wait)
    return True


async def _settle(aid: str, counted: int, counter: int | None, asked_at: int,
                  frames_at_ask: int) -> tuple[int | None, bool, bool]:
    end = time.monotonic() + decide.FRAME_LAG_MS / 1000
    while True:
        await asyncio.sleep(SETTLE_POLL_S)
        with _lock:
            counter, frame_at = _counter.get(aid, counter), _seen_at.get(aid)
            since = _frame_n.get(aid, 0) - frames_at_ask
        complete, mismatch = decide.settle_outcome(counted, counter, frame_at, asked_at, since)
        if not mismatch or time.monotonic() >= end:
            return counter, complete, mismatch


async def _read(account_id: str, kind: str) -> int | None:
    aid = account_id
    exit_held = False
    with _lock:
        retry = aid in _retry_due
        _retry_due.discard(aid)
        if aid not in _sets:
            _first_read_events[aid] = decide.UnreadSet(_clock() - 1)
    try:
        got = await of_pacing.walk(aid, "badge_attribution", lambda: asyncio.to_thread(_list_unread, aid))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a failed read flips nothing; the next frame asks again
        got = None
        log.info("badge_read_failed account=%s error=%s", aid, type(exc).__name__)
        exit_held = _hold(aid, exc)
    finally:
        app_open_warm.note_read(aid)
    if got is not None and got.failed is not None:
        exit_held = _hold(aid, got.failed)
    if exit_held and not retry:
        with _lock:
            _retry_due.add(aid)
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
        counter, complete, mismatch = await _settle(aid, decide._counted(got.rows), counter,
                                                   asked_at, got.frames_at_ask)
    from accounts_admin_api import held_window
    flips: list[tuple[int, int]] = []
    r: int | None = None
    try:
        with _lock:
            prev = _sets.get(aid)
            held = held_window(aid)
            window = utd.window_rows(held) if held is not None else None
            window_at = held.get("asked_at") if held is not None else None
            journal = prev if prev is not None else _first_read_events.get(aid)
            flips = decide.diff(window, prev, got.rows, complete, asked_at, window_at, fence=journal)
            mutes = decide.mute_changes(window, window_at, got.rows,
                                        {f: v for (a, f), v in _muted.items() if a == aid}, asked_at)
            for fan, muted in mutes.items():
                if (aid, fan) in _muted:
                    _muted[(aid, fan)] = (muted, asked_at)
            s = _sets[aid] = decide.replace_set(journal, got.rows, asked_at, complete, window, window_at)
            ids = _ids.get(aid, frozenset())
        r = _publish_restricted(aid, s, ids)
        if kind == "poll" and complete:
            unread_total.observe_poll(aid, sum(1 for row in got.rows if utd.of_counts(row)), asked_at)
        if flips or mutes:
            patch_window_read_and_mute(aid, dict(flips), mutes)
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
