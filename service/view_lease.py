"""
The View lease registry (ADR-0031, phase-01 1a): which Creators some tab has on screen now.

A holder is (principal kind, principal id, tab id). Each renewal (`POST /admin/view-lease`)
replaces that holder's whole set and its `selected` Creator (leased too); a holder lapses `TTL_S` after its
last renewal. The union of live holders is the Viewing half of Demand, which
`transaction_ingest` polls at the fast tier. In Relay memory by design: a restart is rebuilt by
the next renewals (one TTL at most). Expired holders are pruned on every call.

Knob `VIEW_LEASE_TTL_S` (default 60 s), read here only. `now` is monotonic seconds (default
`time.monotonic()`), passed by tests.

Legacy tabs (fetch-diet P1a fix): a tab loaded before 1a shipped runs JS that never renews a
lease. The app's `/events` stream says `lease=1` since then; an unmarked one from a browser page
(it has a Referer; the desktop app's main-process notifier and scripts send none) is such a tab,
and while it is open every Creator its session can access (the route's clamp, watchers dropped)
counts as leased, the pre-1a cadence for that operator. `legacy_stream_ids` decides,
`legacy_held` holds it: re-held on every frame (heartbeat 20 s), dropped when the stream ends,
lapsing TTL_S after its last frame if an end is never seen.
"""
from __future__ import annotations

import contextlib
import math
import time
from typing import AsyncIterator, Callable, Iterable, NamedTuple

from env_knob import env_float

_DEFAULT_TTL_S = 60.0

# Above zero (a zero TTL would lease nothing).
TTL_S = env_float("VIEW_LEASE_TTL_S", _DEFAULT_TTL_S, lo=math.nextafter(0.0, 1.0))

Holder = tuple[str, str, str]   # (principal kind, principal id, tab id)


class _Hold(NamedTuple):
    ids: frozenset[str]
    selected: str | None
    at: float


_holders: dict[Holder, _Hold] = {}


def _now(now: float | None) -> float:
    return time.monotonic() if now is None else now


def _prune(now: float) -> None:
    for h in [h for h, v in _holders.items() if now - v.at >= TTL_S]:
        del _holders[h]
    for k in [k for k, (_, at) in _streams.items() if now - at >= TTL_S]:
        del _streams[k]


def renew(holder: Holder, account_ids: Iterable[str], selected: str | None,
          now: float | None = None) -> list[str]:
    """Replace `holder`'s set and `selected`; `selected` is leased too (it is on screen). No ids and
    no `selected` releases the holder. Returns the Creators to refresh at once: those no live
    holder leased before, plus `selected` when it differs from this holder's previous `selected`
    (even if another holder leases it)."""
    now = _now(now)
    _prune(now)
    before = _union()
    prev = _holders.get(holder)
    ids = frozenset(account_ids) | ({selected} if selected is not None else frozenset())
    if ids:
        _holders[holder] = _Hold(ids, selected, now)
    else:
        _holders.pop(holder, None)
    out = sorted(ids - before)
    if selected is not None and selected != (prev.selected if prev else None) and selected not in out:
        out.append(selected)
    return out


def refresh_plan(gains: Iterable[str], selected: str | None, *, opened: bool, current: Callable[[str], bool],
                 fresh: Callable[[str], bool]) -> tuple[list[str], list[str]]:
    """`renew`'s answer split into (read now, paced). `selected` reads now unless `fresh` (a poll, ok or
    not, started within purchase_poll_decide.SELECT_MIN_AGE_S). The other gains go through app_open_warm's per-exit
    gate (app_open_warm.pace), except a
    `current` one and all of them on an `opened` post (the App-open warm reads them)."""
    gains = list(gains)
    now = [a for a in gains if a == selected and not fresh(a)]
    paced = [] if opened else [a for a in gains if a != selected and not current(a)]
    return now, paced


def _union() -> set[str]:
    return {a for v in _holders.values() for a in v.ids} | {a for ids, _ in _streams.values() for a in ids}


# ── Legacy tabs (module docstring) ──

_streams: dict[object, tuple[frozenset[str], float]] = {}


def legacy_stream_ids(lease: str | None, referer: str | None, accounts: frozenset[str] | None,
                      is_watcher: Callable[[str], bool]) -> frozenset[str]:
    """The Creators an `/events` stream leases while open: none when it is marked (`lease` given:
    the app since 1a renews its own), has no Referer (not a browser page) or is unclamped
    (`accounts` None: the anonymous escape hatch, no wildcard); else `accounts` minus watchers."""
    if lease is not None or not referer or accounts is None:
        return frozenset()
    return frozenset(a for a in accounts if not is_watcher(a))


def hold_stream(key: object, ids: frozenset[str], now: float | None = None) -> None:
    """(Re)hold an open legacy stream's `ids` from `now`."""
    now = _now(now)
    _prune(now)
    _streams[key] = (ids, now)


def drop_stream(key: object) -> None:
    _streams.pop(key, None)


async def legacy_held(stream: AsyncIterator[bytes], ids: frozenset[str]) -> AsyncIterator[bytes]:
    """`stream` passed through, holding `ids` while it runs (re-held per frame); closes `stream`
    when this ends, as the response would."""
    key = object()
    try:
        async with contextlib.aclosing(stream):
            async for chunk in stream:
                hold_stream(key, ids)
                yield chunk
    finally:
        drop_stream(key)


def leased_ids(now: float | None = None) -> set[str]:
    """The union of every live holder's Creators and every open legacy stream's."""
    _prune(_now(now))
    return _union()


def is_leased(account_id: str, now: float | None = None) -> bool:
    return account_id in leased_ids(now)
