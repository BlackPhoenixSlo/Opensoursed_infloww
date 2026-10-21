#!/usr/bin/env python3
"""Per-fan '*fix' correction throttle (_common.apply_typo_throttle).

The thumb-typo itself always rides, but the self-correct "*fix" bubble is rate
limited per fan ACROSS all senders: at most one per _TYPO_FIX_MIN_INTERVAL (1h)
OR per _TYPO_FIX_MIN_EXCHANGES (50) replies, whichever re-enables first. Without
this two corrections can land minutes apart and read like a bot.

Covered:
  case_impl_allow_flag        allow_correction=False suppresses the fix bubble but
                              keeps the inline slip byte-identical.
  case_allowed_truth_table    _typo_correction_allowed gate logic (time + count).
  case_first_fires_then_throttled  back-to-back replies: first corrects, second is
                              suppressed, the slip still rides, 'since' increments.
  case_reenables_by_count     state at 50 exchanges → correction allowed again.
  case_reenables_by_time      state >1h old → correction allowed again.

Run: ./venv/bin/python service/tests/test_typo_throttle.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from automations import _common  # noqa: E402
from automations._common import (  # noqa: E402
    _humanize_typos_impl, _typo_correction_allowed, apply_typo_throttle,
    _TYPO_FIX_MIN_EXCHANGES, _TYPO_FIX_STATE_KEY,
)
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan  # noqa: E402

# A single bubble that fires a typo + correction on many seeds (room to spare).
_PARTS = ["honestly could you really believe that happened tonight"]

_AID_N = 0


def _fresh_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_typo_{_AID_N}"


def _fix_seed() -> int:
    """First seed where the impl emits a correction bubble (allow_correction=True)."""
    for s in range(5000):
        _out, emitted = _humanize_typos_impl(_PARTS, random.Random(s),
                                             allow_correction=True)
        if emitted:
            return s
    raise AssertionError("no fix-producing seed found in 5000 (rate regression?)")


async def _seed_fan(aid: str, fan_id: int, state: dict | None = None) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        cf = json.dumps({_TYPO_FIX_STATE_KEY: state}) if state is not None else "{}"
        s.add(Fan(account_id=aid, fan_id=fan_id, custom_fields=cf))


async def _state(aid: str, fan_id: int) -> dict:
    async with get_session() as s:
        f = await s.get(Fan, (aid, fan_id))
        return json.loads(f.custom_fields).get(_TYPO_FIX_STATE_KEY, {})


# ── Pure cases ─────────────────────────────────────────────────────────

def case_impl_allow_flag():
    seed = _fix_seed()
    allowed, em_a = _humanize_typos_impl(_PARTS, random.Random(seed),
                                         allow_correction=True)
    blocked, em_b = _humanize_typos_impl(_PARTS, random.Random(seed),
                                         allow_correction=False)
    assert em_a is True and em_b is False, (em_a, em_b)
    assert len(allowed) == 2 and len(blocked) == 1, (allowed, blocked)
    # the inline slip is decided BEFORE the fix branch → identical either way
    assert allowed[0] == blocked[0], (allowed[0], blocked[0])


def case_allowed_truth_table():
    now = datetime(2026, 6, 20, 12, 0, 0)
    assert _typo_correction_allowed({}, now) is True               # never corrected
    assert _typo_correction_allowed({"at": None, "since": 3}, now) is True
    recent = (now - timedelta(minutes=5)).isoformat()
    assert _typo_correction_allowed({"at": recent, "since": 3}, now) is False
    old = (now - timedelta(hours=2)).isoformat()
    assert _typo_correction_allowed({"at": old, "since": 0}, now) is True   # time
    assert _typo_correction_allowed(
        {"at": recent, "since": _TYPO_FIX_MIN_EXCHANGES}, now) is True       # count
    assert _typo_correction_allowed(
        {"at": recent, "since": _TYPO_FIX_MIN_EXCHANGES - 1}, now) is False
    assert _typo_correction_allowed({"at": "garbage", "since": 0}, now) is True


# ── DB-backed throttle cases ───────────────────────────────────────────

def case_first_fires_then_throttled():
    async def go():
        aid, fan = _fresh_account(), 5001
        seed = _fix_seed()
        await _seed_fan(aid, fan)
        first = await apply_typo_throttle(aid, fan, list(_PARTS),
                                          random.Random(seed))
        assert len(first) == 2, ("first reply should self-correct", first)
        st1 = await _state(aid, fan)
        assert st1.get("since") == 0 and st1.get("at"), st1

        second = await apply_typo_throttle(aid, fan, list(_PARTS),
                                           random.Random(seed))
        assert len(second) == 1, ("second reply must be throttled", second)
        assert second[0] == first[0], "the slip still rides, only the fix is dropped"
        st2 = await _state(aid, fan)
        assert st2.get("since") == 1, st2  # the throttled reply counts toward 50
    asyncio.run(go())


def case_reenables_by_count():
    async def go():
        aid, fan = _fresh_account(), 5002
        seed = _fix_seed()
        recent = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
        await _seed_fan(aid, fan, {"at": recent, "since": _TYPO_FIX_MIN_EXCHANGES})
        out = await apply_typo_throttle(aid, fan, list(_PARTS), random.Random(seed))
        assert len(out) == 2, ("50 exchanges should re-enable the fix", out)
        assert (await _state(aid, fan)).get("since") == 0, "fire resets the counter"
    asyncio.run(go())


def case_reenables_by_time():
    async def go():
        aid, fan = _fresh_account(), 5003
        seed = _fix_seed()
        old = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        await _seed_fan(aid, fan, {"at": old, "since": 0})
        out = await apply_typo_throttle(aid, fan, list(_PARTS), random.Random(seed))
        assert len(out) == 2, (">1h should re-enable the fix", out)
    asyncio.run(go())


def case_blocked_within_window():
    async def go():
        aid, fan = _fresh_account(), 5004
        seed = _fix_seed()
        recent = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
        await _seed_fan(aid, fan, {"at": recent, "since": 5})
        out = await apply_typo_throttle(aid, fan, list(_PARTS), random.Random(seed))
        assert len(out) == 1, ("inside both windows → no fix", out)
        assert (await _state(aid, fan)).get("since") == 6, "counts toward the 50"
    asyncio.run(go())


if __name__ == "__main__":
    _harness.run(
        case_impl_allow_flag,
        case_allowed_truth_table,
        case_first_fires_then_throttled,
        case_reenables_by_count,
        case_reenables_by_time,
        case_blocked_within_window,
    )
