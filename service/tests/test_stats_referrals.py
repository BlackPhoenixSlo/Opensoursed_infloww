#!/usr/bin/env python3
"""
GET /admin/stats/referrals — the Dashboard's Referrals tile and Creator
reports' Referrals channel (roadmap 1.12).

No transaction carries referral earnings, so the route reads OF's Statements ›
Referrals chart, one read per Creator, cached. These cases stub `_load_client`
with a fake that answers the shape of service/tests/fixtures/
of_statistics_reads.json's "/payouts/referrals/chart": no network.

  case_one_read_per_creator_in_cents      the window's whole days, dollars to
      cents, OF's day buckets as they come; Fansly skipped.
  case_a_failed_creator_is_unavailable    one Creator's 503 lists it, the rest
      still answer.
  case_cached_per_window                  a repeat is served from the cache; a
      new window reads again.
  case_account_filter                     `account_id` narrows to those Creators.
  case_signed_in_reads_only_its_creators  a signed-in caller's omitted filter
      is its own Creators with a session, never the rest.
  case_a_foreign_creator_is_403           naming a Creator not the caller's.
  case_late_creator_is_unavailable        one past the budget is listed, the
      rest answer; its read lands in the cache for the next ask.
  case_one_read_in_flight_per_creator     new windows while a Creator's read
      still runs list it unavailable without a second read.
  case_a_deactivated_creator_is_not_read  listed unavailable, no OF read.
  case_fixture_shape                      OF's captured answer parses.

Run: ./venv/bin/python service/tests/test_stats_referrals.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import copy  # noqa: E402
import time  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import account_health  # noqa: E402
import auth  # noqa: E402
import relay_cache  # noqa: E402
import server  # noqa: E402

FIX = json.loads((Path(__file__).parent / "fixtures" / "of_statistics_reads.json").read_text())

A, B, F = "9301001", "9301002", "9301003"   # two OnlyFans Creators and a Fansly one


class _FakeOF:
    def __init__(self, answer: dict | None, delay: float = 0.0) -> None:
        self.answer = answer
        self.delay = delay
        self.calls: list[tuple[str | None, str | None]] = []

    def referrals_chart(self, *, start=None, end=None) -> dict:
        self.calls.append((start, end))
        time.sleep(self.delay)
        if self.answer is None:
            raise HTTPException(status_code=503, detail={"error": "no_session"})
        return copy.deepcopy(self.answer)


def _chart(total, days):
    return {"total": total, "delta": 0, "chartCount": [],
            "chartAmount": [{"date": f"{d}T00:00:00+00:00", "count": c} for d, c in days]}


_fakes: dict[str, _FakeOF] = {}
server._load_client = lambda aid: _fakes[aid]  # type: ignore[assignment]
server.account_registry.list_accounts = lambda: [  # type: ignore[assignment]
    {"id": A, "has_session": True}, {"id": B, "has_session": True},
    {"id": F, "has_session": True}, {"id": "9301009", "has_session": False}]
server.account_registry.get_platform = lambda aid: "fansly" if aid == F else "onlyfans"  # type: ignore[assignment]


def _reset(**answers):
    _fakes.clear()
    for aid in (A, B, F):
        _fakes[aid] = _FakeOF(answers.get(aid))
        relay_cache.invalidate("payouts", aid)


async def _call(account_id=None, f="2026-10-01", t="2026-10-02"):
    return await server.admin_stats_referrals(account_id=account_id, from_=f, to=t)


async def case_one_read_per_creator_in_cents():
    _reset(**{A: _chart(12.5, [("2026-10-01", 2.5), ("2026-10-02", 10)]), B: _chart(0, [])})
    out = await _call()
    assert out["unavailable"] == [], out
    rows = {r["account_id"]: r for r in out["rows"]}
    assert set(rows) == {A, B}, f"Fansly or a session-less account was read: {out}"
    assert rows[A]["total_cents"] == 1250, rows[A]
    assert rows[A]["by_day"] == [{"day": "2026-10-01", "cents": 250}, {"day": "2026-10-02", "cents": 1000}], rows[A]
    assert rows[B] == {"account_id": B, "total_cents": 0, "by_day": []}, rows[B]
    assert _fakes[A].calls == [("2026-10-01 00:00:00", "2026-10-02 23:59:59")], _fakes[A].calls
    assert _fakes[F].calls == [], "Fansly has no referral program"


async def case_a_failed_creator_is_unavailable():
    _reset(**{A: _chart(3, [("2026-10-01", 3)])})   # B answers 503
    out = await _call()
    assert out["unavailable"] == [B], out
    assert [r["account_id"] for r in out["rows"]] == [A], out


async def case_cached_per_window():
    _reset(**{A: _chart(1, []), B: _chart(2, [])})
    first = await _call()
    assert await _call() == first
    assert len(_fakes[A].calls) == 1, f"a repeat read OF again: {_fakes[A].calls}"
    await _call(t="2026-10-03")
    assert len(_fakes[A].calls) == 2, f"a new window was served stale: {_fakes[A].calls}"


async def case_account_filter():
    _reset(**{A: _chart(1, []), B: _chart(2, [])})
    out = await _call(account_id=B)
    assert [r["account_id"] for r in out["rows"]] == [B], out
    assert _fakes[A].calls == [], "a Creator outside the filter was read"


async def case_fixture_shape():
    _reset(**{A: FIX["/payouts/referrals/chart"]})
    out = await _call(account_id=A)
    row = out["rows"][0]
    assert row["total_cents"] == 0 and [d["day"] for d in row["by_day"]][:2] == ["2026-10-01", "2026-10-02"], row


def _signed_in(ids):
    """Stand in for a signed-in principal owning `ids` (auth's clamp reads it)."""
    auth._actor_account_ids = lambda: frozenset(ids)  # type: ignore[assignment]


_anonymous = auth._actor_account_ids


async def case_signed_in_reads_only_its_creators():
    _reset(**{A: _chart(1, []), B: _chart(2, [])})
    _signed_in({B, "9301009"})   # one live Creator, one without a session
    try:
        out = await _call()
    finally:
        auth._actor_account_ids = _anonymous
    assert [r["account_id"] for r in out["rows"]] == [B] and out["unavailable"] == [], out
    assert _fakes[A].calls == [], "another principal's Creator was read"


async def case_a_foreign_creator_is_403():
    _reset(**{A: _chart(1, []), B: _chart(2, [])})
    _signed_in({B})
    try:
        await _call(account_id=A)
    except HTTPException as e:
        assert e.status_code == 403, e
    else:
        raise AssertionError("a foreign Creator was served")
    finally:
        auth._actor_account_ids = _anonymous
    assert _fakes[A].calls == []


async def case_late_creator_is_unavailable():
    _reset(**{A: _chart(1, [])})
    _fakes[B] = _FakeOF(_chart(2, []), delay=1.0)
    budget, server._REFERRALS_BUDGET_S = server._REFERRALS_BUDGET_S, 0.2
    try:
        out = await _call()
        assert out["unavailable"] == [B] and [r["account_id"] for r in out["rows"]] == [A], out
        assert len(server._referrals_running) == 1, "the late read was cancelled or dropped"
        await asyncio.gather(*server._referrals_running)
        out = await _call()
        assert out["unavailable"] == [] and {r["account_id"] for r in out["rows"]} == {A, B}, out
        assert len(_fakes[B].calls) == 1, "the late read did not land in the cache"
    finally:
        server._REFERRALS_BUDGET_S = budget


async def case_one_read_in_flight_per_creator():
    _reset(**{A: _chart(1, [])})
    _fakes[B] = _FakeOF(_chart(2, []), delay=1.0)
    budget, server._REFERRALS_BUDGET_S = server._REFERRALS_BUDGET_S, 0.2
    try:
        out = await _call()
        assert out["unavailable"] == [B], out
        # Another window while B's first read still runs: no second OF read.
        for t in ("2026-10-03", "2026-10-04"):
            out = await _call(t=t)
            assert out["unavailable"] == [B], out
        assert len(_fakes[B].calls) == 1, f"stale windows stacked up reads: {_fakes[B].calls}"
        await asyncio.gather(*server._referrals_running)
        _fakes[B].delay = 0.0
        out = await _call(t="2026-10-04")
        assert out["unavailable"] == [], out
        assert len(_fakes[B].calls) == 2, _fakes[B].calls
    finally:
        server._REFERRALS_BUDGET_S = budget


async def case_a_deactivated_creator_is_not_read():
    _reset(**{A: _chart(1, []), B: _chart(2, [])})
    await account_health.deactivate(B)
    try:
        out = await _call()
    finally:
        await account_health.activate(B)
    assert out["unavailable"] == [B] and [r["account_id"] for r in out["rows"]] == [A], out
    assert _fakes[B].calls == [], "a deactivated Creator was read"


_harness.run()
