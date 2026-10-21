#!/usr/bin/env python3
"""auto_follow automation tests (Growth feature #3). OF is faked — no network.

THE CASE LIST IS THE `_harness.run(...)` CALL AT THE BOTTOM OF THIS FILE, not a
paragraph up here. A hand-written prose index sat here for months and nothing
checked it: it named 29 of 38 cases, so a reader who trusted it (which is the
only reason to write one) believed nine tests did not exist. `test_send_welcome`
is 11 of 101 and `test_ai_chatter` 13 of 267 — the convention was abandoned
everywhere, and an index that is 24% complete is worse than none.

Every case's own docstring says what it pins and why, which is the one place that
cannot go stale without the case going with it.

Run: ./venv/bin/python service/tests/test_auto_follow.py
"""
from __future__ import annotations

import _harness  # MUST be first
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
        # fan_id → user payload for get_user; the follow action's price gate
        # reads subscribePrice / subscribedBy / subscribedByExpireDate off it.
        self.users: dict[int, dict] = {}
        # what recent_expired_subscribers returns ({"list":[...]} like OF)
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
            # one inbound message, so the fan is `recent_active`
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 10 + 1,
                          direction="in", body="<p>hey</p>",
                          created_at=now - timedelta(hours=i)))


def _free(fake: FakeOF, *fan_ids: int) -> None:
    """Free profiles we don't follow yet: the gate follows each one."""
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
    """Q9: `follow` is the only action. A rule with no action, or one of the
    removed like_messages / like_posts / ping, SKIPS — it never falls back to
    follow, because a follow can BUY a priced profile."""
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
    """subscribe PAYS on a priced profile. Only an explicit subscribePrice==0
    may be followed; a missing/unreadable price is a SKIP, never a follow."""
    aid = "af_follow_gate"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 2001}, {"id": 2002}, {"id": 2003}]
    fake.users = {
        2001: {"subscribePrice": 4.99},   # paid page — skip
        2002: {},                          # no price readable — skip
        2003: {"subscribePrice": 0},       # free — follow
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
    """`subscribePrice: false` is NOT a free page. `bool` subclasses `int` in
    python, so a raw `False` off the OF payload cleared the
    `isinstance(price, (int, float))` number check and then compared equal to 0
    — read as "free", followed, and CHARGED if the page was in fact priced.
    The `isinstance(price, bool)` leg in `_classify`'s money gate is the only
    thing between that payload and the account's card.

    This is the ONLY case that exercises that leg: with it reverted the whole
    rest of this file still passes and this case is the one that goes red
    (`followed == 1`, `no_price_skipped == 0`)."""
    aid = "af_follow_bool_price"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 2101}]
    fake.users = {2101: {"subscribePrice": False}}  # unreadable, NOT free
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False,
                                  "targets": {"source": "expired"}})
    assert fake.followed == [], fake.followed
    assert fake.resubscribed == [], fake.resubscribed
    assert res["no_price_skipped"] == 1, res
    assert res["followed"] == 0, res


async def case_follow_expired_pool():
    """Default pool is OF's recent-expired list; a lapsed relationship
    (subscribedByExpireDate) re-follows via /resubscribe, a fresh one via
    /subscribe, an active follow (subscribedBy) is left alone."""
    aid = "af_follow_pool"
    await _seed(aid)
    fake = _use_fake()
    fake.expired = [{"id": 3001}, {"id": 3002}, {"id": 3003}]
    fake.users = {
        3001: {"subscribePrice": 0},                                       # fresh
        3002: {"subscribePrice": 0, "subscribedByExpireDate": "2026-01-01"},  # lapsed
        3003: {"subscribePrice": 0, "subscribedBy": True},                 # active
    }
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False,
                                  "targets": {"source": "expired"}})
    assert fake.followed == [3001], fake.followed
    assert fake.resubscribed == [3002], fake.resubscribed
    assert res["already_following"] == 1, res
    assert res["source"] == "expired", res
    # Both notifications start the ping cooldown, so the ping action can never
    # double-notify a fan the follow action just reached.
    from db.models import FollowPingState
    async with get_session() as s:
        assert await s.get(FollowPingState, (aid, 3001)) is not None
        assert await s.get(FollowPingState, (aid, 3002)) is not None
        assert await s.get(FollowPingState, (aid, 3003)) is None  # skipped → no stamp


async def case_follow_headroom():
    """Gate skips must not consume the cap: with cap=1 and two paid profiles
    ahead of a free one, the free fan still gets followed. (The old pool[:cap]
    slice returned zero follows here.)"""
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
    """Account + Fan rows with last_message_received_at N days back
    ({fan_id: days_quiet})."""
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Account(id=aid))
        for fid, days in fans.items():
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"F{fid}",
                      last_message_received_at=now - timedelta(days=days)))


async def case_follow_dry_run():
    """Dry run must not follow/resubscribe — and must not promise follows the
    gate would refuse. These two fans have no readable price, so the live run
    skips both; a preview that lists them as `would_follow` is a forecast of
    something that cannot happen."""
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
    """The no-op that hid in production for six days: `follow` aimed at fans we
    ALREADY follow. Every one returns already_following, so the run fires zero
    notifications — but the preview counted them as candidates and reported
    them as `would_follow`, so the rule looked ready to work."""
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
    """The preview needs OF to run the gate. With no usable session it must
    report that it could not look — never a forecast, and never a hard error on
    what is only a plan."""
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
    """daily_cap=0 is the operator's stop switch. `int(payload.get(...) or 50)`
    treated an explicit 0 as "unset" and fired a full batch of REAL actions."""
    aid = "af_zero"
    await _seed(aid, n_fans=5)
    fake = _use_fake()
    _free(fake, *range(1001, 1006))
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False, "daily_cap": 0})
    assert res["followed"] == 0, res
    assert fake.followed == [], fake.followed


async def case_smart_list_is_account_scoped():
    """A smart_list_id is a bare int in steps_json. Unscoped, a typo resolved
    ANOTHER creator's segment and spent this account's follow budget on fans it
    has no relationship with."""
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


# ── Backfill pool: all_stored ─────────────────────────────────────────

async def case_all_stored_is_the_default_pool():
    """`follow` with no targets now sweeps EVERY stored fan (the operator's
    "follow back all"), not OF's narrow recent-expired list."""
    aid = "af_all_default"
    await _seed(aid, n_fans=3)
    fake = _use_fake()
    fake.expired = [{"id": 7777}]          # would be the OLD default pool
    fake.users = {1001: {"subscribePrice": 0}, 1002: {"subscribePrice": 0},
                  1003: {"subscribePrice": 0}, 7777: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow",
                         payload={"action": "follow", "dry_run": False})
    assert res["source"] == "all_stored", res
    assert sorted(fake.followed) == [1001, 1002, 1003], fake.followed
    assert 7777 not in fake.followed, "expired list is not the default any more"


async def case_all_stored_covers_unsubbed_fans_still_on_file():
    """The third tier the operator asked about: a fan who already unsubbed but
    is still stored. They have no recent message and are not on any OF list —
    only `all_stored` reaches them."""
    aid = "af_all_unsubbed"
    await _seed(aid, n_fans=1)
    async with get_session() as s:
        # On file, but silent for a year and absent from every OF pool.
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
    """THE regression test for the ungated backfill forever-loop.

    `_all_stored_fan_ids` is a stateless `ORDER BY … LIMIT headroom` — it has no
    cursor of its own, so the ping-cooldown ledger IS its progress marker. With
    the ledger unread, every tick re-fetched the identical head of the table:
    the ungated path re-bought the same `daily_cap` fans forever, and the gated
    path stalled at `already=headroom` with the rest of the table out of reach.

    Ungated on purpose — the gated path masks the bug, because
    `already_following` does not consume the cap so a gated batch walks deeper
    on its own. A single-tick test cannot see any of this.
    """
    aid = "af_backfill_ticks"
    await _seed(aid, n_fans=8)
    fake = _use_fake()
    # daily_cap 3 → 3 fans per tick, headroom 15 (the whole pool fits, so a
    # stalled window would show up as a repeat, not as a short pool).
    payload = {"action": "follow", "dry_run": False, "money_gate": False,
               "daily_cap": 3}

    r1 = await run_once(aid, "auto_follow", payload=payload)
    tick1 = list(fake.followed)
    assert r1["followed"] == 3 and len(tick1) == 3, (r1, tick1)

    r2 = await run_once(aid, "auto_follow", payload=payload)
    tick2 = fake.followed[3:]
    assert r2["followed"] == 3 and len(tick2) == 3, (r2, tick2)

    # The pool ADVANCED: not one fan from tick 1 is bought a second time.
    assert not (set(tick1) & set(tick2)), (
        f"tick 2 re-followed tick 1's fans: {tick1} vs {tick2}")
    # And the run only ever sees fans it has not actioned — the candidate pool
    # shrinks by exactly what the previous tick consumed.
    assert r2["candidates"] == r1["candidates"] - 3, (r1, r2)

    r3 = await run_once(aid, "auto_follow", payload=payload)
    tick3 = fake.followed[6:]
    assert not (set(tick1 + tick2) & set(tick3)), (tick1, tick2, tick3)
    assert len(set(fake.followed)) == len(fake.followed) == 8, fake.followed


async def case_backfill_reaches_the_never_messaged_tier():
    """A fan with a NULL last_message_received_at sorts LAST by construction
    (`nullslast`), so he is only ever reachable once the ledger has walked the
    dated fans out of the window. He was one of the three tiers the backfill
    exists for, and before the ledger filter he was unreachable at ANY cap."""
    aid = "af_backfill_nulls"
    await _seed(aid, n_fans=4)          # dated fans 1001..1004
    async with get_session() as s:
        for fid in (7001, 7002):
            # Never messaged us: on file, no inbound, no OF list will name them.
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Quiet{fid}",
                      last_message_received_at=None))
    fake = _use_fake()
    payload = {"action": "follow", "dry_run": False, "money_gate": False,
               "daily_cap": 2}

    # Tick 1+2 drain the four dated fans; only then can the NULL tier surface.
    for _ in range(3):
        await run_once(aid, "auto_follow", payload=payload)

    assert {7001, 7002} <= set(fake.followed), (
        f"never-messaged tier never reached: {fake.followed}")
    assert len(fake.followed) == len(set(fake.followed)) == 6, fake.followed


async def case_gated_backfill_walks_past_fans_we_already_follow():
    """🔴 THE GATED half of the forever-loop, which the ungated case above cannot
    see — and it is the half all three prod rules run.

    `_follow_batch` stamped the ping ledger for `_NOTIFY_OUTCOMES` only.
    `already_following` fires no notification, so it stamped nothing, was excluded
    by nothing, and re-occupied the head of the `LIMIT headroom` window on every
    tick forever. It is not an error and not rare: it is the STEADY STATE of any
    account that has been following fans back. Once `headroom` consecutive head
    rows are already-followed, the never-messaged tier — which sorts LAST by
    construction — is unreachable at any cap, and the run reports `status ok`,
    `followed: 0`, `already_following == candidates`: a lane that looks healthy
    while doing nothing, which is exactly the shape that went unnoticed for six
    days on the dry-run preview.

    Seeded as the report reproduced it: a wall of already-followed fans with
    RECENT `last_message_received_at` (so they sort first) in front of a
    never-messaged tier."""
    aid = "af_backfill_gated"
    now = datetime.utcnow()
    fake = _use_fake()
    async with get_session() as s:
        s.add(Account(id=aid))
        for i in range(10):                       # the wall, newest-first
            fid = 2000 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Known{i}",
                      last_message_received_at=now - timedelta(minutes=i)))
            fake.users[fid] = {"subscribePrice": 0, "subscribedBy": True}
        for i in range(6):                        # …and the tier behind it
            fid = 3000 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Quiet{i}",
                      last_message_received_at=None))
            fake.users[fid] = {"subscribePrice": 0}
    payload = {"action": "follow", "dry_run": False, "money_gate": True,
               "daily_cap": 2}                    # headroom 10 = the wall exactly

    r1 = await run_once(aid, "auto_follow", payload=payload)
    # Tick 1 is the wall, and it says so out loud rather than looking quiet.
    assert r1["followed"] == 0 and r1["already_following"] == 10, r1
    assert r1["pool_exhausted"] is True, r1
    assert fake.followed == [], fake.followed

    # 🔴 Tick 2 must be past it. Before the examined marker this was tick 1 again,
    # forever.
    r2 = await run_once(aid, "auto_follow", payload=payload)
    assert r2["followed"] == 2, r2
    assert r2["pool_exhausted"] is False, r2
    assert all(f >= 3000 for f in fake.followed), fake.followed

    for _ in range(3):
        await run_once(aid, "auto_follow", payload=payload)
    assert len(set(fake.followed)) == 6, fake.followed
    assert set(fake.followed) == {3000 + i for i in range(6)}, fake.followed


async def case_gated_backfill_walks_past_priced_and_unreadable_profiles():
    """🔴 The OTHER pinned head, and the one the first fix left open.

    `already_following` is the steady state, so it is the shape that bites first —
    but a head made of PRICED profiles (following would cost money) and profiles
    with no readable price pins the `LIMIT headroom` window exactly as hard, and
    those two verdicts never expire on their own the way a stamp does. The run
    reports `status ok`, `followed: 0`, `already_following: 0` — so the counter
    added for the first shape read False on this one, i.e. it was blind on
    precisely the state it exists to name.

    Both are verdicts from a profile we successfully READ, which is why they are
    progress and why they are stamped. The error path is not, and its 404 residual
    stays documented on `_all_stored_fan_ids` rather than fixed here — we cannot
    tell a dead account from a transient OF failure out of the exception alone."""
    aid = "af_backfill_priced_head"
    now = datetime.utcnow()
    fake = _use_fake()
    async with get_session() as s:
        s.add(Account(id=aid))
        for i in range(10):                       # the wall, newest-first
            fid = 2500 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Priced{i}",
                      last_message_received_at=now - timedelta(minutes=i)))
            # Half priced, half unreadable — neither is `already_following`.
            fake.users[fid] = ({"subscribePrice": 9.99} if i % 2 == 0
                               else {"subscribePrice": None})
        for i in range(6):                        # …and the tier behind it
            fid = 3500 + i
            s.add(Fan(account_id=aid, fan_id=fid, of_display_name=f"Quiet{i}",
                      last_message_received_at=None))
            fake.users[fid] = {"subscribePrice": 0}
    payload = {"action": "follow", "dry_run": False, "money_gate": True,
               "daily_cap": 2}                    # headroom 10 = the wall exactly

    r1 = await run_once(aid, "auto_follow", payload=payload)
    assert r1["followed"] == 0 and r1["already_following"] == 0, r1
    assert r1["paid_profile_skipped"] == 5 and r1["no_price_skipped"] == 5, r1
    # 🔴 …and the run says so. The narrower `already_following == len(pool)` test
    # read False here, which is the whole reason this shape stayed invisible.
    assert r1["pool_exhausted"] is True, r1
    assert fake.followed == [], fake.followed

    # 🔴 Tick 2 must be past the wall.
    r2 = await run_once(aid, "auto_follow", payload=payload)
    assert r2["followed"] == 2, r2
    assert r2["pool_exhausted"] is False, r2
    assert all(f >= 3500 for f in fake.followed), fake.followed

    for _ in range(3):
        await run_once(aid, "auto_follow", payload=payload)
    assert set(fake.followed) == {3500 + i for i in range(6)}, fake.followed


async def case_follow_respects_the_shared_ping_cooldown():
    """The follow action reads the SAME ledger the welcome and lifecycle
    follows stamp (`stamp_ping`). A fan notified inside
    `min_days_between_pings` is not followed on top of it — one fan, one
    notification, whichever subsystem caused it."""
    from automations import auto_follow as af
    aid = "af_follow_cooldown"
    await _seed_quiet(aid, {8001: 10, 8002: 11})
    fake = _use_fake()
    fake.users = {8001: {"subscribePrice": 0, "subscribedBy": True},
                  8002: {"subscribePrice": 0, "subscribedBy": True}}
    # Another lane just notified 8001 and stamped the ledger.
    await af.stamp_ping(aid, 8001)

    # The follow action must now leave 8001 alone and take only 8002. Ungated,
    # so nothing but the ledger can be doing the excluding.
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "money_gate": False})
    assert fake.followed == [8002], (
        f"a just-pinged fan must not be followed again: {fake.followed}")
    assert res["candidates"] == 1, res


async def case_fan_ids_overrides_the_cooldown():
    """An explicit `fan_ids` list is an OPERATOR OVERRIDE, not a pool: it
    follows exactly the fans named, ledger or no ledger.

    The cooldown exists to stop US nagging fans out of pools WE picked. A
    hand-typed `fan_ids: [7001, 7002]` silently becoming "follow 7002" because
    7001 was reached by some other rule last week is the automation overruling
    a direct instruction. Operator's call, 2026-09-06. The follow still STAMPS
    — the exemption is the read only, so the automatic sources still steer
    clear of a fan an operator just reached by hand."""
    from automations import auto_follow as af
    from db.models import FollowPingState
    aid = "af_ids_override"
    await _seed_quiet(aid, {7001: 3, 7002: 3})
    # 7001 was notified moments ago — deep inside the 14-day cooldown.
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
    # …and the override still stamps, so the POOLED sources keep their brake.
    async with get_session() as s:
        after = await s.get(FollowPingState, (aid, 7001))
        assert after is not None and after.ping_count == 2, (
            f"the override must still stamp the ledger: {after and after.ping_count}")


async def case_pooled_source_still_obeys_the_cooldown():
    """The other half of the fan_ids carve-out: EXACTLY fan_ids is exempt.
    The same stamped fan, reached through a pool we picked rather than a list
    the operator typed, is still skipped. If this ever goes green alongside a
    widened exemption, the cooldown has stopped protecting the backfill.

    Every assertion here is written to CHANGE when the exemption widens, which
    the first version of this case was not:

      • The `all_stored` half cannot pin `skip` at all. `_all_stored_fan_ids`
        takes `exclude=` and applies it as SQL `NOT IN` before the LIMIT — that
        is deliberate (the window has to slide, see the docstring), but it means
        the merge loop's `skip` is a second, redundant filter on that path.
        Widen the exemption to every source and `all_stored` still returns one
        fan. It is kept because the SQL exclusion is worth pinning; it is not
        what pins the carve-out.
      • So the boundary is pinned on the LIST-shaped sources, `recent_active`
        and `expired`, where `skip` is the only filter there is. Both are given
        a real, non-empty pool — the earlier version seeded no Message rows, so
        `recent_active` resolved to ZERO candidates and "the stamped fan is
        absent" was true of an empty list.
      • `daily_cap: 1` on those halves. With the default cap of 50 an extra fan
        just rides along and the asserted outcome is unchanged; at 1 the stamped
        fan, if he is not excluded, TAKES the only slot — so the widened
        exemption shows up as the wrong fan being bought, not merely as one
        extra call nobody looks at.
    """
    from automations import auto_follow as af
    from db.models import FollowPingState
    aid = "af_pooled_cooldown"
    await _seed_quiet(aid, {7101: 3, 7102: 3})
    # recent_active reads Message rows, not the cached Fan column. 7101 is the
    # NEWER of the two so he sorts FIRST — at daily_cap 1 an unexcluded 7101
    # consumes the single slot and 7102 never gets followed.
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

    # recent_active — the list-shaped path, where `skip` is the ONLY filter.
    # 7102 was just followed above, so re-stamp nothing: only 7101 is stamped
    # by the cooldown we are testing... except _follow_batch stamped 7102 too.
    # Clear 7102's stamp so this half tests exactly one exclusion.
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

    # expired — the third path through the same `skip`, an OF-supplied list we
    # never touch with SQL. Same shape, same verdict.
    async with get_session() as s:
        row = await s.get(FollowPingState, (aid, 7102))
        if row is not None:
            await s.delete(row)

    fake.followed.clear()
    fake.expired = [{"id": 7101}, {"id": 7102}]   # 7101 first, as OF orders it
    res3 = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "daily_cap": 1,
        "targets": {"source": "expired"},
    })
    assert fake.followed == [7102], (
        f"expired must skip the stamped fan too: {fake.followed}")
    assert res3["candidates"] == 1, res3


async def case_all_stored_db_failure_is_not_a_clean_empty_run():
    """A per-source `except: continue` is right for somebody else's list going
    dark. It is wrong for our own database: an OperationalError out of
    `_all_stored_fan_ids` was swallowed and the run reported
    `{'followed': 0, 'candidates': 0, 'errors': 0}` — a clean, successful,
    EMPTY tick, every tick, forever, with nothing anywhere saying the backfill
    had stopped. It must escape."""
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
    """`source` accepts a LIST and loops it in order; a fan in two pools is
    followed exactly once."""
    aid = "af_src_list"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    fake.expired = [{"id": 1001}, {"id": 5005}]   # 1001 also in all_stored
    fake.users = {1001: {"subscribePrice": 0}, 1002: {"subscribePrice": 0},
                  5005: {"subscribePrice": 0}}
    res = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False,
        "targets": {"source": ["expired", "all_stored"]},
    })
    assert res["source"] == "expired,all_stored", res
    assert sorted(fake.followed) == [1001, 1002, 5005], fake.followed
    assert len(fake.followed) == len(set(fake.followed)), "no fan followed twice"
    # expired came first in the list → 1001/5005 lead the pool
    assert fake.followed[:2] == [1001, 5005], fake.followed


async def case_source_list_survives_a_broken_source():
    """One dead source must not cost the other pools their turn."""
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


# ── money_gate: off buys paid profiles, on is the default ─────────────

async def case_money_gate_off_follows_blind_no_reads():
    """money_gate:false follows EVERYONE with no profile read — including the
    priced page the gate exists to refuse. This is the operator's explicit
    choice; the test pins it so nobody 'fixes' it by accident."""
    aid = "af_gate_off"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    reads: list[int] = []
    fake.users = {1001: {"subscribePrice": 49.99},   # would be refused if gated
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
    """An ungated dry run must not report `paid_profile_skipped` — that would
    promise a protection that is switched off. It says so instead."""
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
    """🔴 On the Fansly lane the gate has no price to read. The shim's `get_user`
    returns its `of_user` shape — no `subscribePrice` at all — so a gated follow
    classified EVERY fan as `no_price` and the lane that had been following
    became a permanent no-op the day the gate went on by default. Fansly's
    follow is a free POST by construction, so on that platform the gated path
    IS the blind follow: no read, everyone examined is followed, and the plan
    (dry run) says the same."""
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
        # …and the same shape on an OF account is still refused: no price, no follow.
        aid2 = "af_of_noprice_control"
        await _seed(aid2, n_fans=1)
        fake2 = _use_fake()
        fake2.get_user = lambda uid: dict(shape, id=str(uid))
        res2 = await run_once(aid2, "auto_follow", payload={"action": "follow", "dry_run": False})
        assert fake2.followed == [] and res2["followed"] == 0, (res2, fake2.followed)
    finally:
        ax.account_registry.get_platform = real_platform  # type: ignore[assignment]


async def case_money_gate_defaults_on():
    """Absent the knob the gate stays ON — the rules already live in prod must
    not start paying because a new option exists."""
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
    """A DRY RUN NEVER ADVANCES THE BACKFILL WINDOW, and the report has to admit it.

    `_stamp_examined` is called by `_follow_batch` only, so a rule parked in dry
    run — this tab's default, and its recommended posture — re-reads the identical
    `LIMIT headroom` head of the table on every tick and prints the identical
    plan. Measured before the fix: 3 dry ticks, 0 stamps, byte-for-byte the same
    output. `candidates` alone is headroom-sized, so on a 3663-fan account it
    reported 20 and looked exactly like a 20-fan account that was finished.

    `eligible` is the count the LIVE run would still be working through. The
    preview must NOT stamp anything (a plan that mutates state is not a plan —
    see `auto_follow._run_follow`), so the fix is honesty, not progress: the same
    plan twice, and a number beside it saying how much of the pool it is standing
    still in front of.
    """
    aid = "af_dry_eligible"
    await _seed(aid, n_fans=9)
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}
    payload = {"action": "follow", "dry_run": True, "daily_cap": 2,
               "targets": {"source": "all_stored"}}
    first = await run_once(aid, "auto_follow", payload=payload)
    second = await run_once(aid, "auto_follow", payload=payload)

    assert fake.followed == [], "a preview must not follow anybody"
    # headroom is cap x5 = 10, so all 9 fans are candidates; only `cap` are read.
    assert first["candidates"] == 9, first
    assert first["examined"] == 2, first
    assert first["eligible"] == 9, first
    # THE POINT: nothing moved, and the second tick says the same thing. Before
    # this, the identical-ness was the whole defect and nothing reported it.
    assert second["would_follow"] == first["would_follow"], (first, second)
    assert second["eligible"] == 9, second


async def case_live_run_reports_the_pool_it_IS_draining():
    """R3-4. `eligible` was computed inside `if dry_run:`, so the number the
    panel's drain hint is built on vanished the moment a rule went LIVE — the
    only state in which it is a measurement of progress rather than a measurement
    of standing still. `AutoFollowTab` then reverted to "Run it once and this
    line will say how many fans are left to walk", an instruction that could not
    be satisfied in the state it rendered in.

    A live tick emits it, and — unlike a dry tick — it FALLS, because
    `_follow_batch` stamps `follow_examined_at` on every fan it reaches."""
    aid = "af_live_eligible"
    await _seed(aid, n_fans=9)
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}
    payload = {"action": "follow", "dry_run": False, "daily_cap": 2,
               "targets": {"source": "all_stored"}}

    first = await run_once(aid, "auto_follow", payload=payload)
    assert first["dry_run"] is False, first
    # Measured at the START of the tick, so it is comparable with `candidates`
    # (also a start-of-tick number) — `app/lib/runStats.tsx`'s `runStatsChunks`
    # compares the two.
    assert first["eligible"] == 9, first
    assert first["followed"] == 2, first

    second = await run_once(aid, "auto_follow", payload=payload)
    # THE POINT. A dry rule reports the same number forever; a live one reports
    # progress, which is the whole reason the hint exists.
    assert second["eligible"] == 7, second

    # And it stays absent on a rule that is not walking the backfill at all —
    # the one state in which the panel is entitled to show no number.
    other = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": False, "daily_cap": 2,
        "targets": {"source": "fan_ids", "fan_ids": [1001]}})
    assert "eligible" not in other, other


async def case_eligible_is_not_emitted_for_a_stacked_pool():
    """🔴 `eligible` COUNTS ONE POOL; `candidates` COUNTS THE MERGED ONE.

    It was emitted whenever `"all_stored" in sources`, but `candidates` beside it
    is the merged pool of EVERY source — and `runStats` renders the drain chunk on
    `eligible > candidates`, i.e. it explicitly invites the comparison. On
    `["expired", "all_stored"]` the two count different populations: fans OF hands
    back from its win-back list are candidates and are not in the `all_stored`
    eligible count at all, so the "N left to walk" line was arithmetic over two
    unrelated numbers.

    The honest answer for a stacked rule is no number."""
    aid = "af_eligible_stacked"
    await _seed(aid, n_fans=6)
    fake = _use_fake()
    fake.users = {1000 + i: {"subscribePrice": 0} for i in range(1, 10)}
    # OF's win-back list hands back three fans this account has never stored.
    fake.expired = [2001, 2002, 2003]

    stacked = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 2,
        "targets": {"source": ["expired", "all_stored"]}})
    assert stacked["candidates"] > 6, stacked      # the MERGED pool
    assert "eligible" not in stacked, stacked

    # …and the un-stacked rule, which IS entitled to the number, still has it.
    alone = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 2,
        "targets": {"source": "all_stored"}})
    assert alone["eligible"] == 6, alone


async def case_eligible_subtracts_the_hard_skip_list():
    """🔴 THE POOL DROPS HARD-SKIPPED FANS; THE COUNT BESIDE IT DID NOT.

    `_run_follow` filters `hard_skip` out of the pool in python (it has to apply
    to every source, including the `fan_ids` one that is exempt from the
    cooldown), and `_all_stored_eligible_count` never knew about it — so
    `eligible` over-reported by the whole hard-skip list on every account that has
    one, on the number an operator reads as "fans left to walk"."""
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
    # 6 stored, 2 hard-skipped: the pool sees 4 and so must the count.
    assert res["eligible"] == 4, res
    assert res["candidates"] == 4, res


async def case_dry_run_preview_names_a_spent_pool():
    """`pool_exhausted` was live-path only, so the one chunk that explains a
    pinned window could not be reached from a dry run — the exact place the
    six-day no-op hid. It is on the preview now, and it is STRICTER there: a
    preview reads at most `cap` fans, so "nobody would be notified" only means
    "the pool is spent" when the look covered the whole pool."""
    aid = "af_dry_exhausted"
    await _seed(aid, n_fans=2)
    fake = _use_fake()
    # Both already followed: a full look, and nobody left to notify.
    fake.users = {1001: {"subscribedBy": True}, 1002: {"subscribedBy": True}}
    spent = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 5,
        "targets": {"source": "all_stored"}})
    assert spent["would_follow"] == [], spent
    assert spent["examined"] == 2 and spent["candidates"] == 2, spent
    assert spent["pool_exhausted"] is True, spent

    # Same verdicts, but the cap stopped the look after one fan. "Nobody in the
    # first 1 of 2" is a much weaker claim and must not wear the same name.
    partial = await run_once(aid, "auto_follow", payload={
        "action": "follow", "dry_run": True, "daily_cap": 1,
        "targets": {"source": "all_stored"}})
    assert partial["examined"] == 1 and partial["candidates"] == 2, partial
    assert partial["pool_exhausted"] is False, partial


async def case_engine_default_pools_are_what_the_ui_claims():
    """The panel hand-mirrors these two answers across a LANGUAGE boundary.

    `AutoFollowTab.ENGINE_DEFAULT_SOURCE` decides what the Target dropdown shows
    for a rule whose `targets.source` is ABSENT, and it has to be the pool the
    engine will really walk. Getting it wrong is not cosmetic: it showed
    "Recently-expired fans" for a rule the engine was running as a 3663-fan
    backfill, and the next save of any unrelated field wrote that lie into the
    rule. Nothing but this case can catch a drift — TypeScript cannot read
    `_source_list`, and `_source_list`'s default has no other test.

    ⚠️ If you change either default, change `ENGINE_DEFAULT_SOURCE` with it.
    Grep `ENGINE_DEFAULT_SOURCE` — that constant is the other half of this."""
    from automations import auto_follow as af
    # follow, with no targets at all, IS the whole-audience backfill.
    assert af._source_list({}) == ["all_stored"], af._source_list({})
    assert af._source_list({"source": ""}) == ["all_stored"]
    # ...and everything that goes through _resolve_targets defaults to
    # recently-active. Asserted from the docstring-declared branch rather than by
    # running a query: the branch IS the default.
    import inspect
    src = inspect.getsource(af._resolve_targets)
    assert 'str(targets.get("source") or "recent_active")' in src, (
        "_resolve_targets' absent-source default (recent_active) moved")

    # R3-16. The THIRD engine internal the panel hand-mirrors, and the one that
    # had no seam check while the other two did. `AutoFollowTab.HEADROOM_FACTOR`
    # is the fast end of the drain hint's range — the hint reads "20-100 days",
    # and if this factor drifts the panel keeps quoting the old arithmetic with
    # no test anywhere going red.
    assert af._HEADROOM_FACTOR == 5, (
        f"_HEADROOM_FACTOR is now {af._HEADROOM_FACTOR}; AutoFollowTab.tsx's "
        f"HEADROOM_FACTOR constant (grep it) must change with it or drainHint "
        f"reports the wrong range")
    assert af._headroom(30) == 30 * af._HEADROOM_FACTOR
    # ...and the floor, which the panel does NOT mirror: cap 0 still walks 5.
    # `drainHint` renders "never (max actions is 0)" for that rule instead of
    # dividing by zero, which is the honest answer — a cap of 0 notifies nobody.
    assert af._headroom(0) == af._HEADROOM_FACTOR


_harness.run(
    case_engine_default_pools_are_what_the_ui_claims,
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
