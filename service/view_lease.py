"""
The View lease registry (ADR-0031, phase-01 1a): which Creators some tab has on screen now.

A holder is (principal kind, principal id, tab id). Each renewal (`POST /admin/view-lease`)
replaces that holder's whole set and its `selected` Creator (leased too); a holder lapses `TTL_S` after its
last renewal. The union of live holders is the Viewing half of Demand, which
`transaction_ingest` polls at the fast tier. In Relay memory by design: a restart is rebuilt by
the next renewals (one TTL at most). Expired holders are pruned on every call.

Knob `VIEW_LEASE_TTL_S` (default 60 s), read here only. `now` is monotonic seconds (default
`time.monotonic()`), passed by tests.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Iterable, NamedTuple

log = logging.getLogger("of-relay.view_lease")

_DEFAULT_TTL_S = 60.0


def _ttl_s() -> float:
    raw = os.environ.get("VIEW_LEASE_TTL_S")
    if raw is None or raw.strip() == "":
        return _DEFAULT_TTL_S
    try:
        v = float(raw)
    except ValueError:
        v = math.nan
    if not math.isfinite(v) or v <= 0:
        log.warning("view_lease_bad_env value=%r — using default %.0f", raw, _DEFAULT_TTL_S)
        return _DEFAULT_TTL_S
    return v


TTL_S = _ttl_s()

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


def _union() -> set[str]:
    return {a for v in _holders.values() for a in v.ids}


def leased_ids(now: float | None = None) -> set[str]:
    """The union of every live holder's Creators."""
    _prune(_now(now))
    return _union()


def is_leased(account_id: str, now: float | None = None) -> bool:
    return account_id in leased_ids(now)
