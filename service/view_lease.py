from __future__ import annotations

import contextlib
import math
import time
from typing import AsyncIterator, Callable, Iterable, NamedTuple

from env_knob import env_float

_DEFAULT_TTL_S = 60.0

# Above zero: a zero TTL would lease nothing.
TTL_S = env_float("VIEW_LEASE_TTL_S", _DEFAULT_TTL_S, lo=math.nextafter(0.0, 1.0))

Holder = tuple[str, str, str]


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
    gains = list(gains)
    now = [a for a in gains if a == selected and not fresh(a)]
    paced = [] if opened else [a for a in gains if a != selected and not current(a)]
    return now, paced


def _union() -> set[str]:
    return {a for v in _holders.values() for a in v.ids} | {a for ids, _ in _streams.values() for a in ids}



_streams: dict[object, tuple[frozenset[str], float]] = {}


def legacy_stream_ids(lease: str | None, referer: str | None, accounts: frozenset[str] | None,
                      is_watcher: Callable[[str], bool]) -> frozenset[str]:
    if lease is not None or not referer or accounts is None:
        return frozenset()
    return frozenset(a for a in accounts if not is_watcher(a))


def hold_stream(key: object, ids: frozenset[str], now: float | None = None) -> None:
    now = _now(now)
    _prune(now)
    _streams[key] = (ids, now)


def drop_stream(key: object) -> None:
    _streams.pop(key, None)


async def legacy_held(stream: AsyncIterator[bytes], ids: frozenset[str]) -> AsyncIterator[bytes]:
    key = object()
    try:
        async with contextlib.aclosing(stream):
            async for chunk in stream:
                hold_stream(key, ids)
                yield chunk
    finally:
        drop_stream(key)


def leased_ids(now: float | None = None) -> set[str]:
    _prune(_now(now))
    return _union()


def is_leased(account_id: str, now: float | None = None) -> bool:
    return account_id in leased_ids(now)
