#!/usr/bin/env python3
"""
vault_sweep stops (11-14: a wrong TypeSafe key failed 5336/5336 photos and the drawer said nothing).

  case_breaker_stops_after_a_run_of_failures:
      BREAK_AFTER failures in a row stop the sweep with `stop` naming the first error; later ids never visited;
      `finished_at` stamped.
  case_neutral_and_successes_never_trip_it:
      DRM / gone / not-flaggable items don't count; one success resets the streak.
  case_sweep_stop_is_published:
      a visit raising SweepStop stops the sweep at that item with its {message, fix}.

Run: cd service && ../venv/bin/python tests/test_vault_sweep_stop.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from contextlib import nullcontext  # noqa: E402

import vault_sweep  # noqa: E402


async def _run(ids, visit):
    into: dict = {}
    res = await vault_sweep.run(ids, visit, concurrency=1, gate=nullcontext, into=into, key="k", label="t")
    return res, into["k"]


async def case_breaker_stops_after_a_run_of_failures():
    seen = []

    async def bad(m):
        seen.append(m)
        return {"ok": False, "status": "error", "detail": f"401 nope {m}"}
    res, prog = await _run(list(range(100)), bad)
    n = vault_sweep.BREAK_AFTER
    assert seen == list(range(n)) and res.done == n == res.failed, (seen[-3:], res)
    assert prog["stop"] == res.stop and prog["stop"]["message"] == f"Stopped: {n} items in a row failed.", prog
    assert "First error: 401 nope 0" in prog["stop"]["fix"] and prog["finished_at"], prog


async def case_neutral_and_successes_never_trip_it():
    n = vault_sweep.BREAK_AFTER

    async def mixed(m):
        if m % n == n - 1:
            return {"ok": True, "status": "described"}
        return {"ok": False, "status": "error", "detail": "x"}
    res, prog = await _run(list(range(4 * n)), mixed)
    assert res.stop is None and res.done == 4 * n, res

    async def drm(m):
        return {"ok": False, "status": "blocked_drm"}
    res, prog = await _run(list(range(3 * n)), drm)
    assert res.stop is None and res.done == 3 * n == res.failed and prog["stop"] is None, res


async def case_sweep_stop_is_published():
    async def v(m):
        if m == 2:
            raise vault_sweep.SweepStop("Stopped: NudeNet missing.", "Ask the admin.")
        return {"ok": True}
    res, prog = await _run([0, 1, 2, 3, 4], v)
    assert res.done == 3 and res.failed == 1, res
    assert prog["stop"] == {"message": "Stopped: NudeNet missing.", "fix": "Ask the admin."}, prog
    assert prog["error"] == "Stopped: NudeNet missing.", prog


_harness.run()
