#!/usr/bin/env python3
"""One user action must not fan out into every Creator's OnlyFans call at once (5-10 Creators share a proxy).

  case_s4s_profiles_reads_users_me_through_the_lane_and_skips_dead_sessions
      GET /admin/s4s/profiles over 7 live Creators: at most `admission.OF_ME_READ`'s 4 `/users/me` reads in
      flight, every live one read once, the dead-session Creator never (its stored copy stays).

Run: ./venv/bin/python service/tests/test_pace_creator_bursts.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import automation_executor as ax  # noqa: E402
import relay_cache  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountHealth, UserAccount  # noqa: E402

IDS = fx.seed_two_agencies()
_EXTRA = [f"88030{i:02d}" for i in range(6)]   # with creator_a: 7 live Creators, one more dead
_DEAD = "8803099"


async def _seed() -> None:
    async with get_session() as s:
        for aid in (*_EXTRA, _DEAD):
            s.add(Account(id=aid, nickname=f"pace_{aid[-2:]}", color="#aaaaaa"))
    async with get_session() as s:
        for aid in (*_EXTRA, _DEAD):
            s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=aid))
        s.add(AccountHealth(account_id=_DEAD, session_dead_at=datetime.now(timezone.utc).replace(tzinfo=None), session_dead_reason="Wrong user."))


asyncio.run(_seed())


def case_s4s_profiles_reads_users_me_through_the_lane_and_skips_dead_sessions():
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}
    called: list[str] = []

    class _Client:
        def __init__(self, aid: str) -> None:
            self.aid = aid

        def me(self):
            with lock:
                called.append(self.aid)
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.15)
            with lock:
                state["now"] -= 1
            return {"name": f"OF {self.aid}", "username": f"u{self.aid}"}

    live = [IDS["creator_a"], *_EXTRA]
    for aid in (*live, _DEAD):
        relay_cache.invalidate("users_me", aid)
    orig = ax._make_client
    ax._make_client = lambda aid: _Client(aid)
    try:
        r = fx.login_owner("agency_a_owner").get("/admin/s4s/profiles")
    finally:
        ax._make_client = orig
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    got = {p["account_id"]: p for p in r.json()["profiles"]}
    assert sorted(called) == sorted(live), f"one read per live Creator, none for the dead one: {called}"
    assert 1 < state["peak"] <= 4, f"in-flight /users/me reads peaked at {state['peak']} (lane cap 4)"
    assert got[_EXTRA[0]]["username"] == f"u{_EXTRA[0]}", got[_EXTRA[0]]
    assert got[_DEAD]["display_name"] == "pace_99", got[_DEAD]


def case_s4s_timeout_keeps_the_lane_slot_until_the_read_returns():
    """A `/users/me` read that outlives its timeout still holds its slot: a hung proxy
    never has more than the lane's 4 reads running."""
    import s4s_api
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    class _Slow:
        def me(self):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.4)
            with lock:
                state["now"] -= 1
            return {"name": "x", "username": "x"}

    live = [IDS["creator_a"], *_EXTRA]
    for aid in live:
        relay_cache.invalidate("users_me", aid)
    orig, orig_t = ax._make_client, s4s_api.OF_IDENTITY_TIMEOUT_S
    ax._make_client = lambda aid: _Slow()
    s4s_api.OF_IDENTITY_TIMEOUT_S = 0.05
    try:
        r = fx.login_owner("agency_a_owner").get("/admin/s4s/profiles")
        time.sleep(1.0)   # the timed-out reads finish
    finally:
        ax._make_client, s4s_api.OF_IDENTITY_TIMEOUT_S = orig, orig_t
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert state["peak"] <= 4, f"reads running at once peaked at {state['peak']} (lane cap 4)"


_harness.run()
