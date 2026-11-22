"""
The Unread total (docs/spec/watched-creator-refresher/phase-02-unread-total-first-paint.md, ADR-0043): the shell.
Each Creator's one Unread total, OF's whole-inbox `/users/me` `chatMessagesCount`, held in Relay memory (a restart
forgets it; the reconnect reads refill it) under `_lock` and decided by `unread_total_decide` (pure).

Off unless `UNREAD_TOTAL=1` and `SHARED_REFRESHER=1` (both read once at import, P1 C11): off, the observer returns at
once, no contributor and no window reader are registered (no `values.unread_total` key; Phase 1 reads windows with
the roster rewarm), nothing is held. ASSUMPTION (spec, parked check
C): `chatMessagesCount` counts unread chats. The Knob has been ON on AE since 2026-11-20 (with SHARED_REFRESHER,
owner switch-on; sweep baseline re-pinned then); check C is still the proof the number means that.

Source: every 2xx `GET /api2/v2/users/me` OF actually answered, whoever asked (the route, S4S's `_of_me`, health
probes, account config, the Live connection's reconnect auth, the Shared refresher's Cycle and the App-open warm):
`of_client._observe_unread_total`, beside the consent observer, calls `observe_response` on the worker thread that
made the read; a cache hit never reaches the client, so it is never a confirmation. A failed read (429, error, a
Dead session's 401) observes nothing: the total stays frozen at its last `at`. A 2xx body without a valid counter
drops the held total (null): it moved Last refresh but confirmed nothing. 0 OF calls of its own.

Publish: registered with the Shared refresher as contributor `unread_total` (P1 C8): `snapshot(aid)` rides
`freshness.values.unread_total = {n, at} | null` on both accounts answers and `creator_refreshed`; a changed `n`
calls `shared_refresher.note_values(aid)` (thread-safe), an unchanged one nothing.
A confirmation whose number differs from the held value at its ask time logs `unread_total_drift account=<id>
dir=down|up expected=<n> observed=<n>`.

Drift (ticket 21): a confirmation below the held value beyond slack (a read made elsewhere) leaves the Creator's
window due (`window_due`, the contributor's ask, P1 C8); the refresher reads it after that `/users/me`, in the same
job, at most once per Creator per Cycle whatever asked (P1 C9; a drift still due waits for its next Cycle).
`window_read` is Phase 1's one page-0 window reader (`set_window_reader`, P1 C9: the Cycle's window step and the
App-open warm's step 2 both read through it): the held page-0 rows peeked, the ask time stamped, the roster rewarm
(`accounts_admin_api.rewarm_roster_count`, one live read rewarming the window), the new rows peeked, then
`decide.flips` each published as `chat_read_changed` (`read_flip.publish`) stamped at the ask time; only after a flip
or on a drift read, the Creator's other `list_chats` entries (deeper pages, `filter=unread`) are dropped, so the All
and Unread lists agree again. Rows below page 0 stay until a tab re-reads them (spec needs-human; the badge drops).

Between Cycles (0 OF calls): `on_dm_in` (event_transcoder, an inbound DM, before its window patch), `on_read_flip`
(read_flip.after_write, a landed mark read / unread / all, before its bust) and `on_reply` (server._record_fan_send,
a landed send to a fan, before its bust) move the total by the chat's prior state (`decide.prior_of`: our own record
this Cycle, else the held page-0 row peeked via `relay_cache.peek` at the roster window key before the path patches
or drops it, else unknown, with slack) (`decide.adjust`); a changed `n` calls `note_values`. Each never raises: the
event already happened. Knob off: return at once.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import relay_cache
import shared_refresher
import unread_total_decide as decide
from env_knob import env_float

log = logging.getLogger("of-relay.unread_total")

ENABLED = shared_refresher.ENABLED and env_float("UNREAD_TOTAL", 0.0, 0.0) == 1.0

_ME = re.compile(r"/api2/v2/users/me/?")
_lock = threading.Lock()
_held: dict[str, decide.State] = {}     # Creator -> its held total


def observe_response(account_id: str, method: str, url: str, r: Any, asked_at: int) -> None:
    """The OF client's observer (any thread): a 2xx `GET /users/me` answer, read at `asked_at` (epoch ms), is
    `observe`d; anything else, or Knob off, returns at once."""
    if not ENABLED or method != "GET" or not 200 <= int(getattr(r, "status_code", 0) or 0) < 300:
        return
    if not _ME.fullmatch(urlsplit(url).path):
        return
    observe(str(account_id), json.loads(r.text or "null"), asked_at)


def observe(account_id: str, me_body: Any, asked_at: int) -> None:
    """One `/users/me` body OF returned for the Creator, asked at `asked_at`: a body carrying an int
    `chatMessagesCount` confirms the total (`decide.reconcile`); a changed `n` is published via `note_values`.
    A body without one moves the Creator's Last refresh (the read landed) but confirms nothing: a held total is
    dropped (published as null), so the tab's age, `max(Last refresh, total at)`, is always the total's own
    confirmation time and an unconfirmable total never looks fresh (W30-mu #19). Only the total goes (`n`, `at`,
    `base`): the per-fan records, the adjustments still landing and a due window read stay for the next one. Both
    kinds order by `asked_at` against one watermark (`decide.unconfirmed`, `reconcile`): an older answer of either
    kind landing late changes nothing (W30-mu #45)."""
    if not ENABLED:
        return
    n = decide.count(me_body)
    if n is None:
        with _lock:
            held = _held.get(account_id, decide.State())
            st = decide.unconfirmed(held, asked_at)
            dropped = held.n is not None and st.n is None
            _held[account_id] = st
        if dropped:
            log.warning("unread_total_unconfirmed account=%s: a /users/me answer without chatMessagesCount", account_id)
            shared_refresher.note_values(account_id)
        return
    with _lock:
        held = _held.get(account_id, decide.State())
        want = decide.expected(held, asked_at)
        st, actions = decide.reconcile(held, n, asked_at, int(time.time() * 1000))
        _held[account_id] = st
    if decide.LOG_DRIFT in actions:
        log.info("unread_total_drift account=%s dir=%s expected=%s observed=%s",
                 account_id, "down" if n < (want or 0) else "up", want, n)
    if decide.PUBLISH in actions:
        shared_refresher.note_values(account_id)


def _window_rows(account_id: str) -> list | None:
    """The Creator's held page-0 chats window rows (any age), else None. No OF call."""
    from accounts_admin_api import _ROSTER_WINDOW_KEY  # noqa: PLC0415 — lazy: it imports this module's peers
    held = relay_cache.peek("list_chats", account_id, _ROSTER_WINDOW_KEY)
    return (held.get("list") or held.get("chats") or []) if isinstance(held, dict) else None


def _window_row(account_id: str, fan_id: int) -> dict | None:
    """The fan's row in that window, else None."""
    return next((r for r in _window_rows(account_id) or () if decide._fan(r) == fan_id), None)


def _adjust(account_id: str, fan_id: int | None, event_of) -> None:
    """One between-Cycle move: `event_of(fan, prior)` is the event, given the fan (int, None: every chat) and the
    chat's prior state."""
    if not ENABLED:
        return
    try:
        aid, fan = str(account_id), None if fan_id is None else int(fan_id)
        row = None if fan is None else _window_row(aid, fan)
        with _lock:
            st = _held.get(aid, decide.State())
            nxt = decide.adjust(st, event_of(fan, decide.prior_of(st, fan, row)), int(time.time() * 1000))
            _held[aid] = nxt
        if nxt.n != st.n:
            shared_refresher.note_values(aid)
    except Exception:  # noqa: BLE001 — the event already happened; a missed move waits for the next confirmation
        log.warning("unread_total_adjust_failed account=%s fan=%s", account_id, fan_id, exc_info=True)


def on_dm_in(account_id: str, fan_id: int, at: int | None = None) -> None:
    """An inbound DM from `fan_id` (before the transcoder patches the window), `at` its `createdAt` epoch ms (None:
    unknown)."""
    _adjust(account_id, fan_id, lambda fan, prior: decide.DmIn(fan, prior, at))


def on_read_flip(account_id: str, fan_id: int | None, unread: int, at: int | None) -> None:
    """Our landed read flip (`fan_id` None: mark all read), `at` its pre-write epoch ms (None: now), before the
    bust."""
    _adjust(account_id, fan_id, lambda fan, prior: decide.ReadFlip(
        fan, int(unread), int(time.time() * 1000) if at is None else int(at), prior))


def on_reply(account_id: str, fan_id: int) -> None:
    """Our landed send to `fan_id` (before the send route's bust)."""
    _adjust(account_id, fan_id, decide.Reply)


def snapshot(account_id: str) -> dict[str, int] | None:
    """P1 C8: `values.unread_total`, `{n, at}`, None before the Creator's first confirmation."""
    with _lock:
        return decide.slot(_held.get(account_id, decide.State()))


def window_due(account_id: str) -> bool:
    """P1 C8: a downward drift no window read has served yet (the refresher bounds it to one read per Cycle)."""
    with _lock:
        return _held.get(str(account_id), decide.State()).due is not None


async def window_read(account_id: str) -> Any:
    """P1 C9, Phase 2's window reader: the roster rewarm's one live page-0 read, diffed against the window held
    before it (see the module docstring). Returns and raises what the rewarm did; the diff never fails the read."""
    import accounts_admin_api  # noqa: PLC0415 — loaded by the server; not at import (it reads the live server)
    import read_flip  # noqa: PLC0415
    aid = str(account_id)
    old = _window_rows(aid)
    with _lock:
        drift = _held.get(aid, decide.State()).due is not None
    asked_at = int(time.time() * 1000)
    out = await accounts_admin_api.rewarm_roster_count(aid)
    try:
        new = _window_rows(aid)
        if new is None:             # the write-back was discarded (an invalidation landed): a drift stays due
            return out
        with _lock:
            if aid in _held:
                _held[aid] = decide.read_window(_held[aid], asked_at)
        flipped = decide.flips(old, new, asked_at, drift)
        for fan, unread in flipped:
            read_flip.publish(aid, fan, unread, asked_at)
        if flipped or drift:
            relay_cache.invalidate("list_chats", aid, match=lambda ex: ex != accounts_admin_api._ROSTER_WINDOW_KEY)
    except Exception:  # noqa: BLE001 — the read landed; a missed diff waits for the next window read
        log.warning("unread_total_window_diff_failed account=%s", aid, exc_info=True)
    return out


if ENABLED:
    shared_refresher.register("unread_total", sys.modules[__name__])
    shared_refresher.set_window_reader(window_read)
