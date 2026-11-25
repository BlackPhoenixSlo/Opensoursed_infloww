#!/usr/bin/env python3
from __future__ import annotations

import _harness
_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

import automation_executor as ax  # noqa: E402,F401 — registers plugins
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message, SkipList  # noqa: E402


class FakeOF:
    def __init__(self):
        self.followed: list[int] = []
        self.unfollowed: list[int] = []
        self.resubscribed: list[int] = []
        self.users: dict[int, dict] = {}
        self.expired: list[dict] = []

    def get_user(self, user_id):
        return self.users.get(int(user_id), {})

    def follow_user(self, user_id):
        self.followed.append(int(user_id))
        return {"success": True}

    def unfollow_user(self, user_id, *, reason_id=None):
        self.unfollowed.append(int(user_id))
        return {"success": True}

    def resubscribe_user(self, user_id):
        self.resubscribed.append(int(user_id))
        return {"success": True}

    def recent_expired_subscribers(self):
        return {"list": self.expired, "hasMore": False}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed(aid, n_fans=3):
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Account(id=aid))
        for i in range(1, n_fans + 1):
            fid = 1000 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Fan{i}",
                      last_message_received_at=now - timedelta(hours=i)))
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 10 + 1,
                          direction="in", body="<p>hey</p>",
                          created_at=now - timedelta(hours=i)))


def _free(fake: FakeOF, *fan_ids: int) -> None:
    fake.users.update({fid: {"subscribePrice": 0} for fid in fan_ids})


async def case_dry_run_is_default():
    aid = "af_dry"
    await _seed(aid)
    fake = _use_fake()
    _free(fake, 1001, 1002, 1003)
    res = await run_once(aid, "auto_follow", payload={"action": "follow"})
    assert res.get("dry_run") is True, res
    assert res["candidates"] == 3 and len(res["would_follow"]) == 3, res
    assert fake.followed == [] and fake.resubscribed == [], "dry run must not call OF"


async def case_a_missing_or_removed_action_is_skipped_never_followed():
    aid = "af_bad_action"
    await _seed(aid)
    fake = _use_fake()
    _free(fake, 1001, 1002, 1003)
    for payload in ({}, {"dry_run": False}, {"action": None, "dry_run": False},
                    {"action": "like_messages", "dry_run": False},
                    {"action": "like_posts", "dry_run": False, "targets": {"post_ids": [1]}},
                    {"action": "ping", "dry_run": False}, {"action": "FOLLOW", "dry_run": False}):
        res = await run_once(aid, "auto_follow", payload=payload)
        assert res["skipped"] == "bad_action", (payload, res)
        assert res.get("action") == payload.get("action"), (payload, res)
    assert fake.followed == [] and fake.unfollowed == [] and fake.resubscribed == [], fake.followed


async def case_daily_cap_limits():
    aid = "af_cap"
    await _seed(aid, n_fans=5)
    fake = _use_fake()
    _free(fake, *range(1001, 1006))
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False, "daily_cap": 2})
    assert res["followed"] == 2, res
    assert len(fake.followed) == 2, fake.followed


async def case_follow_money_gate():
    aid = "af_follow_gate"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 2001}, {"id": 2002}, {"id": 2003}]
    fake.users = {
        2001: {"subscribePrice": 4.99},
        2002: {},
        2003: {"subscribePrice": 0},
    }
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False,
                                  "targets": {"source": "expired"}})
    assert fake.followed == [2003], fake.followed
    assert fake.resubscribed == [], fake.resubscribed
    assert res["paid_profile_skipped"] == 1, res
    assert res["no_price_skipped"] == 1, res
    assert res["followed"] == 1, res


async def case_follow_money_gate_rejects_a_boolean_price():
    aid = "af_follow_bool_price"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 2101}]
    fake.users = {2101: {"subscribePrice": False}}
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False,
                                  "targets": {"source": "expired"}})
    assert fake.followed == [], fake.followed
    assert fake.resubscribed == [], fake.resubscribed
    assert res["no_price_skipped"] == 1, res
    assert res["followed"] == 0, res


async def case_follow_expired_pool():
    aid = "af_follow_pool"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 3001}, {"id": 3002}, {"id": 3003}]
    fake.users = {
        3001: {"subscribePrice": 0},
        3002: {"subscribePrice": 0, "subscribedByExpireDate": "2026-01-01"},
        3003: {"subscribePrice": 0, "subscribedBy": True},
    }
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False,
                                  "targets": {"source": "expired"}})
    assert fake.followed == [3001], fake.followed
    assert fake.resubscribed == [3002], fake.resubscribed
    assert res["already_following"] == 1, res
    assert res["source"] == "expired", res
    # Both notifications start the ping cooldown, so ping can never double-notify a fan follow just reached.
    from db.models import FollowPingState
    async with get_session() as s:
        assert await s.get(FollowPingState, (aid, 3001)) is not None
        assert await s.get(FollowPingState, (aid, 3002)) is not None
        assert await s.get(FollowPingState, (aid, 3003)) is None


async def case_follow_headroom():
    aid = "af_follow_room"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 8001}, {"id": 8002}, {"id": 8003}]
    fake.users = {
        8001: {"subscribePrice": 9.99},
        8002: {"subscribePrice": 4.99},
        8003: {"subscribePrice": 0},
    }
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False, "daily_cap": 1,
                                  "targets": {"source": "expired"}})
    assert fake.followed == [8003], fake.followed
    assert res["followed"] == 1 and res["paid_profile_skipped"] == 2, res


async def _seed_quiet(aid: str, fans: dict[int, int]):
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Account(id=aid))
        for fid, days in fans.items():
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"F{fid}",
                      last_message_received_at=now - timedelta(days=days)))


async def case_follow_dry_run():
    aid = "af_follow_dry"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 4001}, {"id": 4002}]
    res = await run_once(aid, "auto_follow", payload={"action": "follow",
                                  "targets": {"source": "expired"}})
    assert res["dry_run"] is True, res
    assert res["candidates"] == 2, res
    assert res["would_follow"] == [], (
        f"preview promised {res['would_follow']} but the price gate skips both")
    assert res["no_price_skipped"] == 2, res
    assert fake.followed == [] and fake.resubscribed == [], "dry run must not mutate"


async def case_follow_dry_run_sees_already_following():
    aid = "af_follow_dry_noop"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 5001}, {"id": 5002}, {"id": 5003}]
    fake.users = {
        5001: {"subscribePrice": 0, "subscribedBy": True},
        5002: {"subscribePrice": 0, "subscribedBy": True},
        5003: {"subscribePrice": 0, "subscribedBy": True},
    }
    res = await run_once(aid, "auto_follow", payload={"action": "follow",
                                  "targets": {"source": "expired"}})
    assert res["would_follow"] == [], (
        f"preview promised follows for fans we already follow: {res['would_follow']}")
    assert res["already_following"] == 3, res
    assert fake.followed == [] and fake.unfollowed == [], "dry run must not mutate"


async def case_dry_run_without_a_session_says_so():
    aid = "af_no_session"
    await _seed_quiet(aid, {8001: 10})
    def _boom(account_id):
        raise RuntimeError("no session for account")
    ax._make_client = _boom  # type: ignore[attr-defined]
    res = await run_once(aid, "auto_follow", payload={"action": "follow"})
    assert res["status"] == "ok", res
    assert res["skipped"] == "of_unreachable", res
    assert "would_follow" not in res, "a preview that could not look must not forecast"


async def case_fan_ids_target():
    aid = "af_ids"
    await _seed(aid, n_fans=3)
    fake = _use_fake()
    _free(fake, 1001, 1002, 1003)
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False,
        "targets": {"source": "fan_ids", "fan_ids": [1001]},
    })
    assert res["followed"] == 1, res
    assert fake.followed == [1001], fake.followed


async def case_zero_cap_sends_nothing():
    aid = "af_zero"
    await _seed(aid, n_fans=5)
    fake = _use_fake()
    _free(fake, *range(1001, 1006))
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False, "daily_cap": 0})
    assert res["followed"] == 0, res
    assert fake.followed == [], fake.followed


async def case_smart_list_is_account_scoped():
    from db.models import SmartList
    aid, other = "af_scope", "af_scope_other"
    await _seed(aid, n_fans=2)
    await _seed(other, n_fans=2)
    async with get_session() as s:
        row = SmartList(account_id=other, name="theirs", rules_json="{}",
                        created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        s.add(row)
        await s.flush()
        foreign_id = row.id

    fake = _use_fake()
    _free(fake, 1001, 1002)
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "daily_cap": 10,
        "targets": {"source": "smart_list", "smart_list_id": foreign_id},
    })
    assert res["candidates"] == 0, res
    assert fake.followed == [], fake.followed



async def case_all_stored_is_the_default_pool():
    aid = "af_all_default"
    await _seed(aid, n_fans=3)
    fake = _use_fake()
    fake.expired = [{"id": 7777}]
    fake.users = {1001: {"subscribePrice": 0}, 1002: {"subscribePrice": 0},
                  1003: {"subscribePrice": 0}, 7777: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False})
    assert res["source"] == "all_stored", res
    assert sorted(fake.followed) == [1001, 1002, 1003], fake.followed
    assert 7777 not in fake.followed, "expired list is not the default any more"


async def case_all_stored_covers_unsubbed_fans_still_on_file():
    aid = "af_all_unsubbed"
    await _seed(aid, n_fans=1)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=4242, of_display_name="LongGone",
                  last_message_received_at=datetime.utcnow() - timedelta(days=365)))
    fake = _use_fake()
    fake.expired = []
    fake.users = {1001: {"subscribePrice": 0}, 4242: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False})
    assert 4242 in fake.followed, f"unsubbed-but-stored fan reached: {fake.followed}"
    assert res["followed"] == 2, res


async def case_backfill_advances_across_ticks():
    aid = "af_backfill_ticks"
    await _seed(aid, n_fans=8)
    fake = _use_fake()
    payload = {"action": "follow", "dry_run": False, "money_gate": False,
               "daily_cap": 3}

    r1 = await run_once(aid, "auto_follow", payload=payload)
    tick1 = list(fake.followed)
    assert r1["followed"] == 3 and len(tick1) == 3, (r1, tick1)

    r2 = await run_once(aid, "auto_follow", payload=payload)
    tick2 = fake.followed[3:]
    assert r2["followed"] == 3 and len(tick2) == 3, (r2, tick2)

    assert not (set(tick1) & set(tick2)), (
        f"tick 2 re-followed tick 1's fans: {tick1} vs {tick2}")
    assert r2["candidates"] == r1["candidates"] - 3, (r1, r2)

    r3 = await run_once(aid, "auto_follow", payload=payload)
    tick3 = fake.followed[6:]
    assert not (set(tick1 + tick2) & set(tick3)), (tick1, tick2, tick3)
    assert len(set(fake.followed)) == len(fake.followed) == 8, fake.followed


async def case_backfill_reaches_the_never_messaged_tier():
    aid = "af_backfill_nulls"
    await _seed(aid, n_fans=4)
    async with get_session() as s:
        for fid in (7001, 7002):
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Quiet{fid}",
                      last_message_received_at=None))
    fake = _use_fake()
    payload = {"action": "follow", "dry_run": False, "money_gate": False,
               "daily_cap": 2}

    for _ in range(3):
        await run_once(aid, "auto_follow", payload=payload)

    assert {7001, 7002} <= set(fake.followed), (
        f"never-messaged tier never reached: {fake.followed}")
    assert len(fake.followed) == len(set(fake.followed)) == 6, fake.followed


async def case_gated_backfill_walks_past_fans_we_already_follow():
    aid = "af_backfill_gated"
    now = datetime.utcnow()
    fake = _use_fake()
    async with get_session() as s:
        s.add(Account(id=aid))
        for i in range(10):
            fid = 2000 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Known{i}",
                      last_message_received_at=now - timedelta(minutes=i)))
            fake.users[fid] = {"subscribePrice": 0, "subscribedBy": True}
        for i in range(6):
            fid = 3000 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Quiet{i}",
                      last_message_received_at=None))
            fake.users[fid] = {"subscribePrice": 0}
    payload = {"action": "follow", "dry_run": False, "money_gate": True,
               "daily_cap": 2}

    r1 = await run_once(aid, "auto_follow", payload=payload)
    assert r1["followed"] == 0 and r1["already_following"] == 10, r1
    assert r1["pool_exhausted"] is True, r1
    assert fake.followed == [], fake.followed

    r2 = await run_once(aid, "auto_follow", payload=payload)
    assert r2["followed"] == 2, r2
    assert r2["pool_exhausted"] is False, r2
    assert all(f >= 3000 for f in fake.followed), fake.followed

    for _ in range(3):
        await run_once(aid, "auto_follow", payload=payload)
    assert len(set(fake.followed)) == 6, fake.followed
    assert set(fake.followed) == {3000 + i for i in range(6)}, fake.followed


async def case_gated_backfill_walks_past_priced_and_unreadable_profiles():
    aid = "af_backfill_priced_head"
    now = datetime.utcnow()
    fake = _use_fake()
    async with get_session() as s:
        s.add(Account(id=aid))
        for i in range(10):
            fid = 2500 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Priced{i}",
                      last_message_received_at=now - timedelta(minutes=i)))
            fake.users[fid] = ({"subscribePrice": 9.99} if i % 2 == 0
                               else {"subscribePrice": None})
        for i in range(6):
            fid = 3500 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Quiet{i}",
                      last_message_received_at=None))
            fake.users[fid] = {"subscribePrice": 0}
    payload = {"action": "follow", "dry_run": False, "money_gate": True,
               "daily_cap": 2}

    r1 = await run_once(aid, "auto_follow", payload=payload)
    assert r1["followed"] == 0 and r1["already_following"] == 0, r1
    assert r1["paid_profile_skipped"] == 5 and r1["no_price_skipped"] == 5, r1
    assert r1["pool_exhausted"] is True, r1
    assert fake.followed == [], fake.followed

    r2 = await run_once(aid, "auto_follow", payload=payload)
    assert r2["followed"] == 2, r2
    assert r2["pool_exhausted"] is False, r2
    assert all(f >= 3500 for f in fake.followed), fake.followed

    for _ in range(3):
        await run_once(aid, "auto_follow", payload=payload)
    assert set(fake.followed) == {3500 + i for i in range(6)}, fake.followed


async def case_follow_respects_the_shared_ping_cooldown():
    from automations import auto_follow as af
    aid = "af_follow_cooldown"
    await _seed_quiet(aid, {8001: 10, 8002: 11})
    fake = _use_fake()
    fake.users = {8001: {"subscribePrice": 0, "subscribedBy": True},
                  8002: {"subscribePrice": 0, "subscribedBy": True}}
    await af.stamp_ping(aid, 8001)

    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "money_gate": False})
    assert fake.followed == [8002], (
        f"a just-pinged fan must not be followed again: {fake.followed}")
    assert res["candidates"] == 1, res


async def case_fan_ids_overrides_the_cooldown():
    from automations import auto_follow as af
    from db.models import FollowPingState
    aid = "af_ids_override"
    await _seed_quiet(aid, {7001: 3, 7002: 3})
    await af.stamp_ping(aid, 7001)
    async with get_session() as s:
        before = await s.get(FollowPingState, (aid, 7001))
        assert before is not None and before.ping_count == 1

    fake = _use_fake()
    fake.users = {7001: {"subscribePrice": 0}, 7002: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False,
        "targets": {"source": "fan_ids", "fan_ids": [7001, 7002]},
    })
    assert sorted(fake.followed) == [7001, 7002], (
        f"a hand-named fan must be followed even inside the cooldown: {fake.followed}")
    assert res["candidates"] == 2, res
    assert res["followed"] == 2, res
    async with get_session() as s:
        after = await s.get(FollowPingState, (aid, 7001))
        assert after is not None and after.ping_count == 2, (
            f"the override must still stamp the ledger: {after and after.ping_count}")


async def case_pooled_source_still_obeys_the_cooldown():
    from automations import auto_follow as af
    from db.models import FollowPingState
    aid = "af_pooled_cooldown"
    await _seed_quiet(aid, {7101: 3, 7102: 3})
    # recent_active reads Message rows; 7101 is newer so it sorts first and takes the single slot unless excluded.
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=7101, message_id=71011,
                      direction="in", body="<p>hey</p>",
                      created_at=now - timedelta(hours=1)))
        s.add(Message(account_id=aid, fan_id=7102, message_id=71021,
                      direction="in", body="<p>hey</p>",
                      created_at=now - timedelta(hours=2)))
    await af.stamp_ping(aid, 7101)

    fake = _use_fake()
    fake.users = {7101: {"subscribePrice": 0}, 7102: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False,
        "targets": {"source": "all_stored"},
    })
    assert fake.followed == [7102], (
        f"a pooled source must still skip a stamped fan: {fake.followed}")
    assert res["candidates"] == 1, res

    async with get_session() as s:
        row = await s.get(FollowPingState, (aid, 7102))
        if row is not None:
            await s.delete(row)

    fake.followed.clear()
    res2 = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "daily_cap": 1,
        "targets": {"source": "recent_active", "days": 30},
    })
    assert fake.followed == [7102], (
        f"recent_active must skip the stamped fan and spend its one slot on "
        f"the other: {fake.followed}")
    assert res2["candidates"] == 1, res2
    assert res2["followed"] == 1, res2

    async with get_session() as s:
        row = await s.get(FollowPingState, (aid, 7102))
        if row is not None:
            await s.delete(row)

    fake.followed.clear()
    fake.expired = [{"id": 7101}, {"id": 7102}]
    res3 = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "daily_cap": 1,
        "targets": {"source": "expired"},
    })
    assert fake.followed == [7102], (
        f"expired must skip the stamped fan too: {fake.followed}")
    assert res3["candidates"] == 1, res3


async def case_all_stored_db_failure_is_not_a_clean_empty_run():
    from automations import auto_follow as af
    aid = "af_db_broken"
    await _seed(aid, n_fans=3)
    fake = _use_fake()
    fake.users = {1001: {"subscribePrice": 0}, 1002: {"subscribePrice": 0},
                  1003: {"subscribePrice": 0}}

    real = af._all_stored_fan_ids
    async def _broken(*a, **kw):
        raise RuntimeError("database is locked")
    af._all_stored_fan_ids = _broken  # type: ignore[assignment]
    try:
        res = await run_once(aid, "auto_follow", payload={
            "action": "follow", "dry_run": False,
            "targets": {"source": "all_stored"}})
    finally:
        af._all_stored_fan_ids = real  # type: ignore[assignment]

    assert res.get("status") != "ok", (
        f"a broken backfill query must not finalise as a healthy run: {res}")
    assert fake.followed == [], fake.followed


async def case_source_list_loops_and_dedups():
    aid = "af_src_list"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    fake.expired = [{"id": 1001}, {"id": 5005}]
    fake.users = {1001: {"subscribePrice": 0}, 1002: {"subscribePrice": 0},
                  5005: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False,
        "targets": {"source": ["expired", "all_stored"]},
    })
    assert res["source"] == "expired,all_stored", res
    assert sorted(fake.followed) == [1001, 1002, 5005], fake.followed
    assert len(fake.followed) == len(set(fake.followed)), "no fan followed twice"
    assert fake.followed[:2] == [1001, 5005], fake.followed


async def case_source_list_survives_a_broken_source():
    aid = "af_src_broken"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    def _boom(**kw):
        raise RuntimeError("OF list 500")
    fake.recent_expired_subscribers = _boom
    fake.users = {1001: {"subscribePrice": 0}, 1002: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False,
        "targets": {"source": ["expired", "all_stored"]},
    })
    assert res["status"] == "ok", res
    assert sorted(fake.followed) == [1001, 1002], fake.followed



async def case_money_gate_off_follows_blind_no_reads():
    aid = "af_gate_off"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    reads: list[int] = []
    fake.users = {1001: {"subscribePrice": 49.99},
                  1002: {"subscribePrice": 0}}
    _orig = fake.get_user
    fake.get_user = lambda uid: (reads.append(int(uid)), _orig(uid))[1]
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "money_gate": False,
    })
    assert sorted(fake.followed) == [1001, 1002], fake.followed
    assert reads == [], f"ungated path spends no get_user reads, got {reads}"
    assert res["money_gate"] is False, res
    assert res["followed"] == 2, res


async def case_money_gate_off_dry_run_admits_it_cannot_preview():
    aid = "af_gate_off_dry"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    fake.users = {1001: {"subscribePrice": 20.0}, 1002: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "money_gate": False,
    })
    assert fake.followed == [], "dry run mutates nothing"
    assert res["money_gate"] is False, res
    assert "paid_profile_skipped" not in res, res
    assert res["unpriced_follows"] == 2, res
    assert "money_gate off" in res["warning"], res


async def case_fansly_follow_is_free_so_the_gate_reads_nothing():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "fansly"))
    from fansly_shim import of_user
    aid = "af_fansly_free"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    reads: list[int] = []
    shape = of_user({"id": "1001", "username": "bob", "displayName": "Bob",
                     "subscriptionTiers": [{"id": "t1", "price": 5000}]})
    assert "subscribePrice" not in shape, shape
    fake.get_user = lambda uid: (reads.append(int(uid)), dict(shape, id=str(uid)))[1]
    real_platform = ax.account_registry.get_platform
    ax.account_registry.get_platform = lambda a: "fansly" if a == aid else "onlyfans"  # type: ignore[assignment]
    try:
        plan = await run_once(aid, "auto_follow", payload={"action": "follow", "dry_run": True})
        assert sorted(plan["would_follow"]) == [1001, 1002], plan
        assert reads == [], ("the plan reads no profile on Fansly", reads)
        res = await run_once(aid, "auto_follow", payload={"action": "follow", "dry_run": False})
        assert sorted(fake.followed) == [1001, 1002], (res, fake.followed)
        assert reads == [], ("a free follow spends no get_user read", reads)
        assert res["followed"] == 2 and res.get("no_price_skipped", 0) == 0, res
        aid2 = "af_of_noprice_control"
        await _seed(aid2, n_fans=1)
        fake2 = _use_fake()
        fake2.get_user = lambda uid: dict(shape, id=str(uid))
        res2 = await run_once(aid2, "auto_follow", payload={"action": "follow", "dry_run": False})
        assert fake2.followed == [] and res2["followed"] == 0, (res2, fake2.followed)
    finally:
        ax.account_registry.get_platform = real_platform  # type: ignore[assignment]


async def case_money_gate_defaults_on():
    aid = "af_gate_default"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    fake.users = {1001: {"subscribePrice": 12.0}, 1002: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False})
    assert fake.followed == [1002], fake.followed
    assert res["paid_profile_skipped"] == 1, res
    assert res["money_gate"] is True, res



async def case_dry_run_preview_reports_the_pool_it_is_not_draining():
    aid = "af_dry_eligible"
    await _seed(aid, n_fans=9)
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}
    payload = {"action": "follow", "dry_run": True, "daily_cap": 2,
               "targets": {"source": "all_stored"}}
    first = await run_once(aid, "auto_follow", payload=payload)
    second = await run_once(aid, "auto_follow", payload=payload)

    assert fake.followed == [], "a preview must not follow anybody"
    assert first["candidates"] == 9, first
    assert first["examined"] == 2, first
    assert first["eligible"] == 9, first
    assert second["would_follow"] == first["would_follow"], (first, second)
    assert second["eligible"] == 9, second


async def case_live_run_reports_the_pool_it_IS_draining():
    aid = "af_live_eligible"
    await _seed(aid, n_fans=9)
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}
    payload = {"action": "follow", "dry_run": False, "daily_cap": 2,
               "targets": {"source": "all_stored"}}

    first = await run_once(aid, "auto_follow", payload=payload)
    assert first["dry_run"] is False, first
    assert first["eligible"] == 9, first
    assert first["followed"] == 2, first

    second = await run_once(aid, "auto_follow", payload=payload)
    assert second["eligible"] == 7, second

    other = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "daily_cap": 2,
        "targets": {"source": "fan_ids", "fan_ids": [1001]}})
    assert "eligible" not in other, other


async def case_eligible_is_not_emitted_for_a_stacked_pool():
    aid = "af_eligible_stacked"
    await _seed(aid, n_fans=6)
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}
    fake.expired = [2001, 2002, 2003]

    stacked = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 2,
        "targets": {"source": ["expired", "all_stored"]}})
    assert stacked["candidates"] > 6, stacked
    assert "eligible" not in stacked, stacked

    alone = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 2,
        "targets": {"source": "all_stored"}})
    assert alone["eligible"] == 6, alone


async def case_eligible_subtracts_the_hard_skip_list():
    aid = "af_eligible_hardskip"
    await _seed(aid, n_fans=6)
    async with get_session() as s:
        for fid in (1001, 1002):
            s.add(SkipList(account_id=aid, fan_id=fid, reason="manual_restrict"))
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}

    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 2,
        "targets": {"source": "all_stored"}})
    assert res["eligible"] == 4, res
    assert res["candidates"] == 4, res


async def case_dry_run_preview_names_a_spent_pool():
    aid = "af_dry_exhausted"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    fake.users = {1001: {"subscribedBy": True}, 1002: {"subscribedBy": True}}
    spent = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 5,
        "targets": {"source": "all_stored"}})
    assert spent["would_follow"] == [], spent
    assert spent["examined"] == 2 and spent["candidates"] == 2, spent
    assert spent["pool_exhausted"] is True, spent

    partial = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 1,
        "targets": {"source": "all_stored"}})
    assert partial["examined"] == 1 and partial["candidates"] == 2, partial
    assert partial["pool_exhausted"] is False, partial


async def case_engine_default_pools_are_what_the_ui_claims():
    from automations import auto_follow as af
    assert af._source_list({}) == ["all_stored"], af._source_list({})
    assert af._source_list({"source": ""}) == ["all_stored"]
    import inspect
    src = inspect.getsource(af._resolve_targets)
    assert 'str(targets.get("source") or "recent_active")' in src, (
        "_resolve_targets' absent-source default (recent_active) moved")

    # AutoFollowTab.HEADROOM_FACTOR hand-mirrors this; drift would leave the panel quoting old arithmetic.
    assert af._HEADROOM_FACTOR == 5, (
        f"_HEADROOM_FACTOR is now {af._HEADROOM_FACTOR}; AutoFollowTab.tsx's "
        f"HEADROOM_FACTOR constant (grep it) must change with it or drainHint "
        f"reports the wrong range")
    assert af._headroom(30) == 30 * af._HEADROOM_FACTOR
    assert af._headroom(0) == af._HEADROOM_FACTOR


def case_select_follow_pool_table():
    from automations import auto_follow as af
    rows = [
        ([3, 1, 2], set(), 10, [3, 1, 2]),
        ([1, 2, 3, 4], {1}, 2, [2, 3]),
        ([1, 2], set(), 0, []),
    ]
    for merged, skip, head, want in rows:
        got = af.select_follow_pool(merged, hard_skip=skip, headroom=head)
        assert got == want, (merged, skip, head, got, want)


_harness.run(
    case_engine_default_pools_are_what_the_ui_claims,
    case_select_follow_pool_table,
    case_dry_run_is_default,
    case_a_missing_or_removed_action_is_skipped_never_followed,
    case_zero_cap_sends_nothing,
    case_smart_list_is_account_scoped,
    case_daily_cap_limits,
    case_follow_money_gate,
    case_follow_money_gate_rejects_a_boolean_price,
    case_follow_expired_pool,
    case_follow_headroom,
    case_follow_dry_run,
    case_follow_dry_run_sees_already_following,
    case_dry_run_without_a_session_says_so,
    case_fan_ids_target,
    case_all_stored_is_the_default_pool,
    case_all_stored_covers_unsubbed_fans_still_on_file,
    case_backfill_advances_across_ticks,
    case_backfill_reaches_the_never_messaged_tier,
    case_gated_backfill_walks_past_fans_we_already_follow,
    case_gated_backfill_walks_past_priced_and_unreadable_profiles,
    case_follow_respects_the_shared_ping_cooldown,
    case_fan_ids_overrides_the_cooldown,
    case_pooled_source_still_obeys_the_cooldown,
    case_all_stored_db_failure_is_not_a_clean_empty_run,
    case_source_list_loops_and_dedups,
    case_source_list_survives_a_broken_source,
    case_money_gate_off_follows_blind_no_reads,
    case_money_gate_off_dry_run_admits_it_cannot_preview,
    case_fansly_follow_is_free_so_the_gate_reads_nothing,
    case_money_gate_defaults_on,
    case_dry_run_preview_reports_the_pool_it_is_not_draining,
    case_dry_run_preview_names_a_spent_pool,
    case_live_run_reports_the_pool_it_IS_draining,
    case_eligible_is_not_emitted_for_a_stacked_pool,
    case_eligible_subtracts_the_hard_skip_list,
)
