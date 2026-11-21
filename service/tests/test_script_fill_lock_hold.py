#!/usr/bin/env python3
"""test_script_fill_lock_hold — how long `fill/apply` holds the SQLite write lock on a big vault (spec phase 01 ›
Seam 2b, ticket 11).

A temp DB seeded with 12,000 Fillable-shaped vault items on Creator A of the two-Agency fixture (857 Shoots of
the decide suite's 13-item shape plus an exact copy of one photo each — 857 dupe pairs — and 2 loose photos; every
Shoot's last clip in one priced OF list) and one 6-Step Sequence. Apply runs over HTTP 5 times (the Sequence is
emptied between runs, so each run writes); a timing wrapper around `script_fill_api.immediate_session` (in the
test, not a product hook) measures BEGIN IMMEDIATE to COMMIT. Prints the median and max hold in ms (plus plan and
apply wall times) and fails when the max is over 2,000 ms: over the bar, the Phase is re-specced, not patched.

Contended (ticket 11): the same applies while 1 and then 4 `fill/plan` loops run on the SAME event loop
(httpx ASGITransport, as uvicorn serves the relay: one loop) — the hold bar still holds, and no other plan computes
while apply holds the write lock. A burst of 5 plans proves two plan computations never overlap (a counting wrapper
around `script_fill_decide.plan_over_vault`, in the test) and prints the fifth plan's wall: the wait behind 4 others.

Run: ./venv/bin/python service/tests/test_script_fill_lock_hold.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import sqlite3  # noqa: E402
import statistics  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import timedelta  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import _script_fill_fixtures as sf  # noqa: E402
import httpx  # noqa: E402
import script_fill_api  # noqa: E402
import server  # noqa: E402

IDS = fx.seed_two_agencies()
A = IDS["creator_a"]
SEQ = "Six step"
ITEMS = 12_000
SHOOTS = 857            # 857 x 14 = 11,998, + 2 loose photos
HOLD_MAX_MS = 2_000
RUNS = 5


async def _seed() -> None:
    rows = []
    for k in range(SHOOTS):
        base = 1_000 + k * 20
        shoot = sf.shoot(A, base, at=sf.T0 + timedelta(days=3 * k))  # past the 48 h outfit window
        shoot[12]["of_folder_ids"] = json.dumps([7])
        shoot.append(sf.vault_row(A, base + 14, "suggestive", dupe_of=base + 4,
                                  created_at=shoot[3]["created_at"]))
        rows += shoot
    rows += [sf.vault_row(A, 900_000 + n, "sfw", lane="free", colour="green") for n in (1, 2)]
    assert len(rows) == ITEMS, len(rows)
    await sf.insert_vault(rows, {(A, "of:7"): 9900})
    await sf.insert_sequence(sf.sequence_rows(A, SEQ, {
        1: ("1/3, freebie", "hey babe here's a little something", 0),
        2: ("1/3, ppv", "wanna see more?", 0),
        3: ("bridge", "how's your day going?", 0),
        4: ("2/3, ppv", "sending you 2 pics", 0),
        5: ("bridge", "did you like it?", 0),
        6: ("3/3, ppv", "the full video, all of me", 0)}, last=6))


asyncio.run(_seed())
fx.store_blob(IDS["agency_a_owner"], "roles", {"enforce": False})
OWNER = fx.login_owner("agency_a_owner")

_holds: list[float] = []
_real = script_fill_api.immediate_session
_locked = threading.Event()             # set from BEGIN IMMEDIATE to COMMIT of a timed apply


@contextlib.asynccontextmanager
async def _timed():
    t0 = time.perf_counter()
    async with _real() as s:
        _locked.set()
        try:
            yield s
        finally:
            _locked.clear()
    _holds.append((time.perf_counter() - t0) * 1000)


class _Overlap:
    """Counts `plan_over_vault` computations in flight (they run in threads): `peak` > 1 = two overlapped;
    `in_lock` = computations started while a timed apply held the write lock."""

    def __init__(self) -> None:
        self.mu = threading.Lock()
        self.now = self.peak = self.in_lock = 0
        self.real = script_fill_api.decide.plan_over_vault

    def __call__(self, *a, **k):
        with self.mu:
            self.now += 1
            self.peak = max(self.peak, self.now)
            self.in_lock += _locked.is_set()
        try:
            return self.real(*a, **k)
        finally:
            with self.mu:
                self.now -= 1

    def __enter__(self) -> "_Overlap":
        script_fill_api.decide.plan_over_vault = self
        return self

    def __exit__(self, *_exc) -> None:
        script_fill_api.decide.plan_over_vault = self.real


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://testserver",
                             cookies=dict(OWNER.cookies), timeout=120)


def _empty_sequence() -> None:
    con = sqlite3.connect(_harness.DB_PATH)
    try:
        con.execute("UPDATE saved_replies SET media_json = '[]', previews_json = '[]', price_cents = 0 "
                    "WHERE account_id = ? AND script_id = ?", (A, SEQ))
        con.commit()
    finally:
        con.close()


def case_apply_lock_hold_on_12000_items():
    url = f"/admin/saved-replies/fill/{{}}?account_id={A}"
    t0 = time.perf_counter()
    r = OWNER.post(url.format("plan"), json={"sequence": SEQ})
    plan_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200 and r.json()["status"] == "ok", (r.status_code, r.text[:500])
    walls = []
    script_fill_api.immediate_session = _timed
    try:
        for _ in range(RUNS):
            _empty_sequence()
            t0 = time.perf_counter()
            r = OWNER.post(url.format("apply"), json={"sequence": SEQ})
            walls.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200 and r.json()["status"] == "ok", (r.status_code, r.text[:500])
            assert len(r.json()["undo"]) == 4, r.json()["undo"]
    finally:
        script_fill_api.immediate_session = _real
    assert len(_holds) == RUNS, _holds
    med, top = statistics.median(_holds), max(_holds)
    print(f"lock hold on {ITEMS} items, {RUNS} applies: median {med:.0f} ms, max {top:.0f} ms "
          f"(all {[round(h) for h in _holds]}); plan wall {plan_ms:.0f} ms; "
          f"apply wall median {statistics.median(walls):.0f} ms, max {max(walls):.0f} ms")
    assert top <= HOLD_MAX_MS, f"max lock hold {top:.0f} ms > {HOLD_MAX_MS} ms: re-spec Phase 1 (do not patch)"


async def _contended(plans: int) -> None:
    """RUNS applies, each while `plans` fill/plan loops run on this loop; asserts the hold bar and that no
    other plan computed under the write lock."""
    url = f"/admin/saved-replies/fill/{{}}?account_id={A}"
    holds_at = len(_holds)
    stop = asyncio.Event()
    plan_walls: list[float] = []
    fails: list[str] = []

    async def loop_plans(c: httpx.AsyncClient) -> None:
        while not stop.is_set():
            t0 = time.perf_counter()
            r = await c.post(url.format("plan"), json={"sequence": SEQ})
            plan_walls.append((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                fails.append(f"{r.status_code} {r.text[:200]}")

    walls = []
    with _Overlap() as seen:
        async with _client() as c:
            bg = [asyncio.create_task(loop_plans(c)) for _ in range(plans)]
            await asyncio.sleep(0.5)          # the plan loops are queued / computing before the first apply
            script_fill_api.immediate_session = _timed
            try:
                for _ in range(RUNS):
                    await asyncio.to_thread(_empty_sequence)   # off the loop: a plan's write must commit
                    t0 = time.perf_counter()
                    r = await c.post(url.format("apply"), json={"sequence": SEQ})
                    walls.append((time.perf_counter() - t0) * 1000)
                    assert r.status_code == 200 and r.json()["status"] == "ok", (r.status_code, r.text[:500])
                    assert len(r.json()["undo"]) == 4, r.json()["undo"]
            finally:
                script_fill_api.immediate_session = _real
                stop.set()
                await asyncio.gather(*bg)
    holds = _holds[holds_at:]
    assert len(holds) == RUNS, holds
    assert not fails, fails
    med, top = statistics.median(holds), max(holds)
    print(f"CONTENDED lock hold, {plans} concurrent plan loop(s) ({len(plan_walls)} plans): median {med:.0f} ms, "
          f"max {top:.0f} ms (all {[round(h) for h in holds]}); apply wall median {statistics.median(walls):.0f} ms, "
          f"max {max(walls):.0f} ms; plan wall median {statistics.median(plan_walls):.0f} ms, "
          f"max {max(plan_walls):.0f} ms; peak plans computing at once {seen.peak}")
    assert seen.peak == 1, f"{seen.peak} plan computations overlapped"
    assert seen.in_lock == RUNS, f"{seen.in_lock} plans computed under the write lock for {RUNS} applies"
    assert top <= HOLD_MAX_MS, f"max lock hold {top:.0f} ms > {HOLD_MAX_MS} ms with {plans} concurrent plans"


async def case_apply_lock_hold_with_1_concurrent_plan():
    await _contended(1)


async def case_apply_lock_hold_with_4_concurrent_plans():
    await _contended(4)


async def case_plan_computations_never_overlap():
    """5 plans fired at once on one loop: one computation at a time; the slowest waited behind the other 4."""
    url = f"/admin/saved-replies/fill/plan?account_id={A}"

    async def one(c: httpx.AsyncClient) -> float:
        t0 = time.perf_counter()
        r = await c.post(url, json={"sequence": SEQ})
        assert r.status_code == 200 and r.json()["status"] == "ok", (r.status_code, r.text[:500])
        return (time.perf_counter() - t0) * 1000

    _empty_sequence()
    with _Overlap() as seen:
        async with _client() as c:
            walls = sorted(await asyncio.gather(*(one(c) for _ in range(5))))
    print(f"5 plans at once: peak computing {seen.peak}; walls {[round(w) for w in walls]} ms "
          f"(fifth = queued behind 4: {walls[-1]:.0f} ms)")
    assert seen.peak == 1, f"{seen.peak} plan computations overlapped"


_harness.run()
