#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import automation_executor as ax  # noqa: E402
import server  # noqa: E402
import mass_queue_api  # noqa: E402
from audiences import _threshold_base, resolve_mass_audience, threshold_fan_ids  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Blacklist, Fan, SubscriberSnapshot, Transaction  # noqa: E402

NOW = datetime.utcnow()


class FakeOF:

    def __init__(self, online=(), fans=(), following=(), lists=None):
        self.online = list(online)
        self.fans, self.follows = list(fans), list(following)
        self.lists = dict(lists or {})
        self.roster_reads = 0
        self.sent: list[dict] = []

    def iter_online_subscribers(self, *, max_fans=1000, **_):
        self.roster_reads += 1
        return self.online[:max_fans]

    @staticmethod
    def _page(ids, limit, offset):
        rows = [{"id": i} for i in ids[offset:offset + limit]]
        return {"list": rows, "hasMore": offset + limit < len(ids)}

    def subscribers(self, *, limit=10, offset=0, **_):
        return self._page(self.fans, limit, offset)

    def following(self, *, limit=10, offset=0, **_):
        return self._page(self.follows, limit, offset)

    def list_users_in(self, list_id, *, limit=20, offset=0):
        if int(list_id) not in self.lists:
            raise RuntimeError(f"OF 404 list {list_id}")
        return self._page(self.lists[int(list_id)], limit, offset)["list"]

    def send_mass_message(self, text, **kw):
        self.sent.append({"text": text, **kw})
        return {"id": 5150}


async def _seed(aid: str, fans: dict[int, dict]) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
            await s.flush()
        for fid, kw in fans.items():
            s.add(Fan(account_id=aid, fan_id=fid, **kw))


async def _tx(aid: str, fid: int, kind: str, cents: int, *, status="cleared", days_ago=1.0):
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fid, kind=kind, amount_cents=cents,
                          status=status, occurred_at=NOW - timedelta(days=days_ago)))


async def case_spent_threshold():
    aid = "acc_thr_spent"
    await _seed(aid, {1: {"lifetime_spend_cents": 5000}, 2: {"lifetime_spend_cents": 1999},
                      3: {"lifetime_spend_cents": 9000, "is_bot": True},
                      4: {"lifetime_spend_cents": 9000}})
    async with get_session() as s:
        s.add(Blacklist(fan_id=4))
    assert await threshold_fan_ids(aid, {1, 2, 3, 4}, min_spent_cents=2000) == {1}
    assert await threshold_fan_ids(aid, {2, 3}, min_spent_cents=2000) == set()


async def case_tipped_threshold():
    aid = "acc_thr_tips"
    await _seed(aid, {11: {}, 12: {}, 13: {}})
    await _tx(aid, 11, "tip", 1500)
    await _tx(aid, 11, "tip", 1000)
    await _tx(aid, 12, "tip", 3000, status="refunded")
    await _tx(aid, 13, "ppv_message", 9000)
    assert await threshold_fan_ids(aid, {11, 12, 13}, min_tips_cents=2000) == {11}


async def case_subscribed_over_reads_every_date_source():
    aid = "acc_thr_tenure"
    await _seed(aid, {21: {"subscribed_at": NOW - timedelta(days=40)},
                      22: {}, 23: {}, 24: {}, 25: {"subscribed_at": NOW - timedelta(days=3)}})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=22, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=31)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=27, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=40)))
    await _tx(aid, 23, "subscription", 999, days_ago=60)
    roster = [{"id": 24, "subscribedOnData": {"subscribeAt": (NOW - timedelta(days=45)).isoformat() + "Z"}},
              {"id": 26, "subscribedOnData": {"subscribeAt": (NOW - timedelta(days=90)).isoformat() + "+00:00"}}]
    pool = {21, 22, 23, 24, 25, 26, 27, 28}
    got = await threshold_fan_ids(aid, pool, subscribed_over_days=30, roster=roster)
    assert got == {21, 22, 23, 24, 26, 27}, got
    assert await threshold_fan_ids(aid, pool, subscribed_over_days=30) == {21, 22, 23, 27}


async def case_expired_over_reads_the_snapshot():
    aid = "acc_thr_expired"
    await _seed(aid, {31: {}, 32: {}, 33: {}})
    last, prev = NOW, NOW - timedelta(days=1)
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=31, seen_at=prev,
                                 expired_at=NOW - timedelta(days=20)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=32, seen_at=prev,
                                 expired_at=NOW - timedelta(days=2)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=33, seen_at=last,
                                 expired_at=NOW - timedelta(days=20)))
    base = await _threshold_base(aid, user_lists=["fans"], excluded_lists=None, included=[],
                                 roster=None, expired_over_days=14, client=None, now=NOW)
    assert base == {31}, base


async def case_resolver_online_now_intersects_the_roster():
    aid = "acc_thr_online"
    await _seed(aid, {41: {"lifetime_spend_cents": 9000}, 42: {"lifetime_spend_cents": 9000},
                      43: {"lifetime_spend_cents": 0}})
    fake = FakeOF(online=[{"id": 41}, {"id": 43}])
    res = await resolve_mass_audience(aid, min_spent_cents=5000, online_now=True,
                                      user_lists=["fans"], exclude_pending_sends=False,
                                      client=fake)
    assert fake.roster_reads == 1
    assert res["included_users"] == [41], res


async def case_resolver_narrows_a_segment():
    aid = "acc_thr_segment"
    await _seed(aid, {51: {"lifetime_spend_cents": 9000}, 52: {"lifetime_spend_cents": 9000},
                      53: {"lifetime_spend_cents": 10}})
    res = await resolve_mass_audience(aid, included_users=[51, 53], min_spent_cents=5000,
                                      exclude_pending_sends=False)
    assert res["included_users"] == [51], res
    off = await resolve_mass_audience(aid, included_users=[53], exclude_pending_sends=False)
    assert off["included_users"] == [53], off


class _Patch:

    def __init__(self, aid: str, fake: FakeOF):
        self.aid, self.fake = aid, fake

    def __enter__(self):
        async def _open(*_a, **_k):
            return self.aid, None, None

        async def _close(*_a, **_k):
            return None
        self.orig = (server._resolve_account_id, server._get_client,
                     mass_queue_api._open_mass_run, mass_queue_api._close_mass_run, ax._make_client)
        server._resolve_account_id = lambda _req: self.aid
        server._get_client = lambda: self.fake
        mass_queue_api._open_mass_run = _open
        mass_queue_api._close_mass_run = _close
        ax._make_client = lambda _aid: self.fake
        return self

    def __exit__(self, *_):
        (server._resolve_account_id, server._get_client,
         mass_queue_api._open_mass_run, mass_queue_api._close_mass_run, ax._make_client) = self.orig


def _body(**kw):
    return mass_queue_api._MassScheduleBody(text="hey", user_lists=["fans", "following"],
                                    online_only=True, **kw)


async def case_route_sends_explicit_ids_without_lists():
    aid = "acc_thr_route"
    await _seed(aid, {61: {"lifetime_spend_cents": 9000}, 62: {"lifetime_spend_cents": 100}})
    fake = FakeOF(online=[{"id": 61}, {"id": 62}])
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(None, _body(min_total_spent=50))
    (sent,) = fake.sent
    assert sent["included_users"] == [61], sent
    assert sent["user_lists"] == [] and sent["online_only"] is False and sent["filters"] is None, sent


async def case_route_refuses_zero_matches_before_sending():
    aid = "acc_thr_zero"
    await _seed(aid, {71: {"lifetime_spend_cents": 100}})
    fake = FakeOF(online=[{"id": 71}])
    with _Patch(aid, fake):
        try:
            await mass_queue_api.of_send_or_schedule_mass(None, _body(min_total_spent=50))
        except HTTPException as e:
            assert e.status_code == 422, e
        else:
            raise AssertionError("a thresholded send nobody clears must be refused")
    assert fake.sent == [], fake.sent


async def case_route_refuses_scheduled_or_expired_online():
    fake = FakeOF()
    for kw in ({"min_total_spent": 5, "scheduled_date": "2026-11-07T10:00:00+01:00"},
               {"expired_over_days": 7}):
        with _Patch("acc_thr_refuse", fake):
            try:
                await mass_queue_api.of_send_or_schedule_mass(None, _body(**kw))
            except HTTPException as e:
                assert e.status_code == 422, (kw, e)
            else:
                raise AssertionError(f"{kw} with online-only must be refused")
    assert fake.roster_reads == 0 and fake.sent == []


def _list_body(lists, **kw):
    return mass_queue_api._MassScheduleBody(text="hey", user_lists=lists, **kw)


async def _refused(aid, fake, body) -> str:
    with _Patch(aid, fake):
        try:
            await mass_queue_api.of_send_or_schedule_mass(None, body)
        except HTTPException as e:
            assert e.status_code == 422, e
            assert fake.sent == [], fake.sent
            return str(e.detail)
    raise AssertionError("expected a 422 before any send")


async def case_route_narrows_the_picked_lists_never_widens():
    aid = "acc_thr_lists"
    await _seed(aid, {81: {"lifetime_spend_cents": 9000}, 82: {"lifetime_spend_cents": 100},
                      83: {"lifetime_spend_cents": 9000}, 84: {"lifetime_spend_cents": 9000},
                      85: {"lifetime_spend_cents": 9000}})
    fake = FakeOF(fans=[81, 82], following=[84], lists={777: [85]})
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, _list_body(["fans", "following", "777"], min_total_spent=50))
    (sent,) = fake.sent
    assert sent["included_users"] == [81, 84, 85], sent
    assert sent["user_lists"] == [], sent


async def case_route_refuses_without_an_audience():
    aid = "acc_thr_nolists"
    await _seed(aid, {86: {"lifetime_spend_cents": 9000}})
    detail = await _refused(aid, FakeOF(fans=[86]), _list_body([], min_total_spent=50))
    assert "No fan clears" in detail, detail


async def case_route_refuses_an_unreadable_list():
    aid = "acc_thr_unread"
    await _seed(aid, {87: {"lifetime_spend_cents": 9000}})
    for lists in (["recent"], ["999"]):
        detail = await _refused(aid, FakeOF(fans=[87]), _list_body(lists, min_total_spent=50))
        assert "Couldn't read who is on" in detail, (lists, detail)


async def case_route_expired_over_reads_the_expired_fans():
    detail = await _refused("acc_thr_exp_nocrawl", FakeOF(),
                            _list_body(["fans", "following"], expired_over_days=14))
    assert "Expired fans aren't known yet" in detail, detail

    aid = "acc_thr_exp_route"
    await _seed(aid, {91: {}, 92: {}, 93: {}})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=91, seen_at=NOW - timedelta(days=1),
                                 expired_at=NOW - timedelta(days=20)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=92, seen_at=NOW - timedelta(days=1),
                                 expired_at=NOW - timedelta(days=3)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=93, seen_at=NOW))
    fake = FakeOF(fans=[93])
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, _list_body(["fans", "following", "999"], expired_over_days=14))
    (sent,) = fake.sent
    assert sent["included_users"] == [91], sent


async def case_route_refuses_past_the_id_cap():
    import audiences
    aid = "acc_thr_cap"
    await _seed(aid, {94: {"lifetime_spend_cents": 9000}, 95: {"lifetime_spend_cents": 9000}})
    orig, audiences.THRESHOLD_IDS_MAX = audiences.THRESHOLD_IDS_MAX, 1
    try:
        detail = await _refused(aid, FakeOF(fans=[94, 95]),
                                _list_body(["fans"], min_total_spent=50))
    finally:
        audiences.THRESHOLD_IDS_MAX = orig
    assert "at most 1" in detail, detail


async def case_route_refuses_an_online_roster_past_the_cap():
    import audiences
    aid = "acc_thr_online_cap"
    await _seed(aid, {101: {"lifetime_spend_cents": 9000}, 102: {"lifetime_spend_cents": 9000},
                      103: {"lifetime_spend_cents": 9000}})
    fake = FakeOF(online=[{"id": 101}, {"id": 102}, {"id": 103}])
    orig, audiences.ONLINE_ROSTER_MAX = audiences.ONLINE_ROSTER_MAX, 2
    try:
        detail = await _refused(aid, fake, _body(min_total_spent=50))
        assert "More than 2 fans are online" in detail, detail
        at_cap = FakeOF(online=[{"id": 101}, {"id": 102}])
        with _Patch(aid, at_cap):
            await mass_queue_api.of_send_or_schedule_mass(None, _body(min_total_spent=50))
    finally:
        audiences.ONLINE_ROSTER_MAX = orig
    (sent,) = at_cap.sent
    assert sent["included_users"] == [101, 102], sent


# OF verifies excludedLists on list audiences only, so a thresholded (explicit ids) send subtracts them itself.
async def case_route_subtracts_the_excluded_lists():
    aid = "acc_thr_excl"
    await _seed(aid, {111: {"lifetime_spend_cents": 9000}, 112: {"lifetime_spend_cents": 9000}})
    fake = FakeOF(fans=[111, 112], lists={555: [112]})
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, _list_body(["fans"], excluded_user_lists=["555"], min_total_spent=50))
    (sent,) = fake.sent
    assert sent["included_users"] == [111], sent

    detail = await _refused(aid, FakeOF(fans=[111, 112]),
                            _list_body(["fans"], excluded_user_lists=["999"], min_total_spent=50))
    assert "Couldn't read who is on the excluded list 999" in detail, detail


async def case_route_explicit_ids_subtract_the_excluded_lists():
    aid = "acc_excl_explicit"
    await _seed(aid, {151: {}, 152: {}})
    fake = FakeOF(lists={556: [152]})
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, _list_body([], user_ids=[151, 152], excluded_user_lists=["556"]))
    (sent,) = fake.sent
    assert sent["included_users"] == [151], sent

    detail = await _refused(aid, FakeOF(),
                            _list_body([], user_ids=[151, 152], excluded_user_lists=["998"]))
    assert "Couldn't read who is on the excluded list 998" in detail, detail

    detail = await _refused(aid, FakeOF(lists={556: [151, 152]}),
                            _list_body([], user_ids=[151, 152, 151], excluded_user_lists=["556"]))
    assert "the excluded lists hold all 2 fan(s)" in detail, detail


async def case_route_tenure_keeps_a_list_member_without_a_fan_row():
    aid = "acc_thr_norow"
    await _seed(aid, {})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=121, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=40)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=122, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=5)))
    fake = FakeOF(lists={778: [121, 122]})
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, _list_body(["778"], subscribed_over_days=30))
    (sent,) = fake.sent
    assert sent["included_users"] == [121], sent


async def case_route_expired_over_a_custom_list_needs_a_crawl():
    aid = "acc_thr_exp_custom"
    await _seed(aid, {131: {}})
    detail = await _refused(aid, FakeOF(lists={779: [131]}),
                            _list_body(["779"], expired_over_days=14))
    assert "Expired fans aren't known yet" in detail, detail


async def case_route_expired_over_narrows_a_custom_list():
    aid = "acc_thr_exp_list"
    await _seed(aid, {141: {}, 142: {}})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=141, seen_at=NOW - timedelta(days=1),
                                 expired_at=NOW - timedelta(days=20)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=142, seen_at=NOW))
    fake = FakeOF(lists={780: [141, 142]})
    with _Patch(aid, fake):
        await mass_queue_api.of_send_or_schedule_mass(None, _list_body(["780"], expired_over_days=14))
    (sent,) = fake.sent
    assert sent["included_users"] == [141], sent


_harness.run()
