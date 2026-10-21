#!/usr/bin/env python3
"""The Auto-follow list (Infloww parity): the per-creator switch, the follow
counts per day window, and the details rows of fans followed."""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

import auto_follow_api as api  # noqa: E402
import automation_rules_api as rules_api  # noqa: E402
from automations import auto_follow  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (Account, AutomationRule, Fan, FollowLog,  # noqa: E402
                       FollowPingState)

_AID_N = 0


def _aid() -> str:
    global _AID_N
    _AID_N += 1
    return f"acc_af_{_AID_N}"


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_follow(aid: str, fan_id: int, times: list[datetime], **fan) -> None:
    """A fan followed at each of `times` (log rows + the per-fan state)."""
    async with get_session() as s:
        if fan is not None and await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id, **fan))
        for t in times:
            s.add(FollowLog(account_id=aid, fan_id=fan_id, followed_at=t))
        s.add(FollowPingState(account_id=aid, fan_id=fan_id,
                              last_pinged_at=max(times), ping_count=len(times)))


def _row(res: dict, aid: str) -> dict:
    return next(r for r in res["rows"] if r["account_id"] == aid)


async def case_stamp_ping_appends_to_the_log() -> None:
    aid = _aid()
    await _seed_account(aid)
    await auto_follow.stamp_ping(aid, 501)
    await auto_follow.stamp_ping(aid, 501)
    async with get_session() as s:
        n = len((await s.execute(select(FollowLog).where(FollowLog.account_id == aid))).all())
        st = await s.get(FollowPingState, (aid, 501))
    assert n == 2, n
    assert st.ping_count == 2, st.ping_count


async def case_stats_count_each_window() -> None:
    aid = _aid()
    await _seed_account(aid)
    starts = api._day_starts_utc(api._zone("UTC"), datetime.utcnow())
    today = starts["today"]  # midnight itself counts as today
    yday = starts["yesterday"] + timedelta(hours=1)
    d5 = starts["today"] - timedelta(days=5)
    d20 = starts["today"] - timedelta(days=20)
    d60 = starts["today"] - timedelta(days=60)
    await _seed_follow(aid, 1, [today, yday])
    await _seed_follow(aid, 2, [d5, d20, d60])

    r = _row(await api.auto_follow_stats(account_id=aid, tz="UTC"), aid)
    assert r["total"] == 5, r                  # lifetime: ping_count sum
    assert (r["today"], r["yesterday"], r["d7"], r["d30"]) == (1, 1, 3, 4), r
    assert r["last_followed_at"] == today.isoformat(), r
    assert r["on"] is False, r


async def case_stats_list_an_account_with_nothing_yet() -> None:
    aid = _aid()
    await _seed_account(aid)
    r = _row(await api.auto_follow_stats(account_id=aid, tz="Not/AZone"), aid)
    assert r == {"account_id": aid, "on": False, "total": 0, "today": 0,
                 "yesterday": 0, "d7": 0, "d30": 0, "last_followed_at": None}, r


async def case_switch_creates_the_expired_follow_rule() -> None:
    """Infloww's switch: "Automatically follow fans whose subscriptions have
    expired". A rule made by it follows OF's recently-expired list, live, with
    the money gate left at its default (on)."""
    aid = _aid()
    await _seed_account(aid)
    out = await rules_api.switch_kind(rules_api.KindSwitch(
        account_id=aid, kind="auto_follow", enable=True))
    assert out["action"] == "created", out
    async with get_session() as s:
        rule = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid, AutomationRule.kind == "auto_follow"))).scalar_one()
    steps = json.loads(rule.steps_json)
    assert steps == {"action": "follow", "targets": {"source": "expired"}, "dry_run": False}, steps
    assert "money_gate" not in steps, "the gate must stay at its default (on)"
    assert _row(await api.auto_follow_stats(account_id=aid), aid)["on"] is True

    await rules_api.switch_kind(rules_api.KindSwitch(account_id=aid, kind="auto_follow", enable=False))
    assert _row(await api.auto_follow_stats(account_id=aid), aid)["on"] is False


async def case_switch_keeps_an_existing_rules_payload() -> None:
    aid = _aid()
    await _seed_account(aid)
    mine = {"action": "follow", "dry_run": True, "daily_cap": 7}
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, kind="auto_follow", name="mine",
                             trigger_json='{"every_seconds": 3600}',
                             steps_json=json.dumps(mine), is_enabled=False))
    await rules_api.switch_kind(rules_api.KindSwitch(account_id=aid, kind="auto_follow", enable=True))
    async with get_session() as s:
        rule = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid))).scalar_one()
    assert rule.is_enabled and json.loads(rule.steps_json) == mine, rule.steps_json


async def case_records_sort_and_range() -> None:
    aid = _aid()
    await _seed_account(aid)
    t0 = datetime(2026, 9, 1, 12, 0, 0)
    exp = datetime(2026, 9, 30)
    await _seed_follow(aid, 11, [t0], of_username="a", lifetime_spend_cents=500)
    await _seed_follow(aid, 12, [t0 + timedelta(days=2)], of_display_name="Bee",
                       lifetime_spend_cents=9000, subscription_expires_at=exp)
    await _seed_follow(aid, 13, [t0 + timedelta(days=4)], custom_nickname="Cee",
                       of_display_name="ignored")

    res = await api.auto_follow_records(account_id=aid, sort="followed_at", order="desc",
                                        start=None, end=None, limit=50, offset=0)
    assert res["total"] == 3 and [r["fan_id"] for r in res["rows"]] == [13, 12, 11], res
    assert [r["name"] for r in res["rows"]] == ["Cee", "Bee", "a"], res
    bee = res["rows"][1]
    assert bee["total_spend_cents"] == 9000 and bee["expires_at"] == exp.isoformat(), bee

    res = await api.auto_follow_records(account_id=aid, sort="spend", order="desc",
                                        start=None, end=None, limit=50, offset=0)
    assert [r["fan_id"] for r in res["rows"]] == [12, 11, 13], res

    res = await api.auto_follow_records(
        account_id=aid, sort="followed_at", order="asc",
        start=(t0 + timedelta(days=1)).isoformat() + "Z",
        end=(t0 + timedelta(days=3)).isoformat() + "Z", limit=50, offset=0)
    assert res["total"] == 1 and res["rows"][0]["fan_id"] == 12, res

    try:
        await api.auto_follow_records(account_id=aid, sort="nope", order="desc",
                                      start=None, end=None, limit=50, offset=0)
        raise AssertionError("an unknown sort must be refused")
    except HTTPException as e:
        assert e.status_code == 422


_harness.run()
