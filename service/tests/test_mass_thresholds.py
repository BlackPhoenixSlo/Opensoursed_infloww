#!/usr/bin/env python3
"""Online-fans mass message thresholds — Total spent / Tipped over /
Subscribed over / Expired over, resolved from our own records.

  case_spent_threshold:
      lifetime_spend_cents >= the bar passes; bots and blacklisted never do.
  case_tipped_threshold:
      the sum of PAID tip transactions counts; a refunded tip doesn't.
  case_subscribed_over_reads_every_date_source:
      fans.subscribed_at, the roster snapshot, the first subscription charge and
      an OF roster row's subscribeAt all count (a candidate with no fans row
      passes on a known date); a fan with no date fails.
  case_expired_over_reads_the_snapshot:
      _threshold_base: dropped from the latest complete crawl AND expired N+ days ago.
  case_resolver_online_now_intersects_the_roster:
      online_now reads OF's online list once and keeps only qualifying fans on it.
  case_resolver_narrows_a_segment:
      explicit ids (a picked segment) are narrowed, never widened.
  case_route_sends_explicit_ids_without_lists:
      a thresholded online send drops userLists and the online filter and sends
      the qualifying ids.
  case_route_refuses_zero_matches_before_sending:
      nobody clears → 422, and OF is never called.
  case_route_refuses_scheduled_or_expired_online:
      scheduled + online-only, or expired + online-only → 422.
  case_route_narrows_the_picked_lists_never_widens:
      not online: the picked lists' members ∩ qualifying fans, nobody else.
  case_route_refuses_without_an_audience / case_route_refuses_an_unreadable_list:
      no list and no ids, or a list OF won't page → 422, nothing sent.
  case_route_expired_over_reads_the_expired_fans:
      Expired over swaps Fans/Following for the crawl's expired fans; no crawl → 422.
  case_route_refuses_past_the_id_cap:
      more qualifying fans than THRESHOLD_IDS_MAX → 422, not a split send.
  case_route_refuses_an_online_roster_past_the_cap:
      more fans online than ONLINE_ROSTER_MAX → 422, not a silently cut roster;
      exactly ONLINE_ROSTER_MAX is sent.
  case_route_subtracts_the_excluded_lists:
      excluded lists' members are subtracted server-side; an unreadable one → 422.
  case_route_tenure_keeps_a_list_member_without_a_fan_row:
      Subscribed over keeps a list member with no fans row but a crawl date.
  case_route_expired_over_a_custom_list_needs_a_crawl:
      Expired over on a custom list with no crawl → "not known yet" 422.
  case_route_expired_over_narrows_a_custom_list:
      with a crawl, a custom list is cut to its fans expired N+ days.

Run: ./venv/bin/python service/tests/test_mass_thresholds.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import automation_executor as ax  # noqa: E402
import server  # noqa: E402
from audiences import _threshold_base, resolve_mass_audience, threshold_fan_ids  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Blacklist, Fan, SubscriberSnapshot, Transaction  # noqa: E402

NOW = datetime.utcnow()


class FakeOF:
    """The online list plus the broadcast surface; nothing leaves the process."""

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
    assert await threshold_fan_ids(aid, {2, 3}, min_spent_cents=2000) == set()   # never wider


async def case_tipped_threshold():
    aid = "acc_thr_tips"
    await _seed(aid, {11: {}, 12: {}, 13: {}})
    await _tx(aid, 11, "tip", 1500)
    await _tx(aid, 11, "tip", 1000)            # 11: $25 across two tips
    await _tx(aid, 12, "tip", 3000, status="refunded")
    await _tx(aid, 13, "ppv_message", 9000)    # a purchase is not a tip
    assert await threshold_fan_ids(aid, {11, 12, 13}, min_tips_cents=2000) == {11}


async def case_subscribed_over_reads_every_date_source():
    aid = "acc_thr_tenure"
    await _seed(aid, {21: {"subscribed_at": NOW - timedelta(days=40)},
                      22: {}, 23: {}, 24: {}, 25: {"subscribed_at": NOW - timedelta(days=3)}})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=22, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=31)))
        # 27: a list member with NO fans row, but the crawl knows his date.
        s.add(SubscriberSnapshot(account_id=aid, fan_id=27, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=40)))
    await _tx(aid, 23, "subscription", 999, days_ago=60)
    roster = [{"id": 24, "subscribedOnData": {"subscribeAt": (NOW - timedelta(days=45)).isoformat() + "Z"}},
              {"id": 26, "subscribedOnData": {"subscribeAt": (NOW - timedelta(days=90)).isoformat() + "+00:00"}}]
    pool = {21, 22, 23, 24, 25, 26, 27, 28}     # 28: no row, no date anywhere
    got = await threshold_fan_ids(aid, pool, subscribed_over_days=30, roster=roster)
    # 25 subscribed 3 days ago; 26 is on OF's list only (no fans row yet) and
    # passes; 27 has no fans row but a snapshot date and passes; 28 fails.
    assert got == {21, 22, 23, 24, 26, 27}, got
    assert await threshold_fan_ids(aid, pool, subscribed_over_days=30) == {21, 22, 23, 27}


async def case_expired_over_reads_the_snapshot():
    aid = "acc_thr_expired"
    await _seed(aid, {31: {}, 32: {}, 33: {}})
    last, prev = NOW, NOW - timedelta(days=1)
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=31, seen_at=prev,
                                 expired_at=NOW - timedelta(days=20)))   # gone 20d
        s.add(SubscriberSnapshot(account_id=aid, fan_id=32, seen_at=prev,
                                 expired_at=NOW - timedelta(days=2)))    # gone 2d
        s.add(SubscriberSnapshot(account_id=aid, fan_id=33, seen_at=last,
                                 expired_at=NOW - timedelta(days=20)))   # still listed
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
    assert res["included_users"] == [41], res          # 42 is offline, 43 below the bar


async def case_resolver_narrows_a_segment():
    aid = "acc_thr_segment"
    await _seed(aid, {51: {"lifetime_spend_cents": 9000}, 52: {"lifetime_spend_cents": 9000},
                      53: {"lifetime_spend_cents": 10}})
    res = await resolve_mass_audience(aid, included_users=[51, 53], min_spent_cents=5000,
                                      exclude_pending_sends=False)
    assert res["included_users"] == [51], res          # 52 qualifies but isn't in the segment
    off = await resolve_mass_audience(aid, included_users=[53], exclude_pending_sends=False)
    assert off["included_users"] == [53], off          # no threshold → untouched


class _Patch:
    """Swap server seams for one route call: the account, the OF client and the
    mass_runs bookkeeping (covered by test_send_mass)."""

    def __init__(self, aid: str, fake: FakeOF):
        self.aid, self.fake = aid, fake

    def __enter__(self):
        async def _open(*_a, **_k):
            return self.aid, None, None

        async def _close(*_a, **_k):
            return None
        self.orig = (server._resolve_account_id, server._get_client,
                     server._open_mass_run, server._close_mass_run, ax._make_client)
        server._resolve_account_id = lambda _req: self.aid
        server._get_client = lambda: self.fake
        server._open_mass_run = _open
        server._close_mass_run = _close
        ax._make_client = lambda _aid: self.fake
        return self

    def __exit__(self, *_):
        (server._resolve_account_id, server._get_client,
         server._open_mass_run, server._close_mass_run, ax._make_client) = self.orig


def _body(**kw):
    return server._MassScheduleBody(text="hey", user_lists=["fans", "following"],
                                    online_only=True, **kw)


async def case_route_sends_explicit_ids_without_lists():
    aid = "acc_thr_route"
    await _seed(aid, {61: {"lifetime_spend_cents": 9000}, 62: {"lifetime_spend_cents": 100}})
    fake = FakeOF(online=[{"id": 61}, {"id": 62}])
    with _Patch(aid, fake):
        await server.of_send_or_schedule_mass(None, _body(min_total_spent=50))
    (sent,) = fake.sent
    assert sent["included_users"] == [61], sent
    assert sent["user_lists"] == [] and sent["online_only"] is False and sent["filters"] is None, sent


async def case_route_refuses_zero_matches_before_sending():
    aid = "acc_thr_zero"
    await _seed(aid, {71: {"lifetime_spend_cents": 100}})
    fake = FakeOF(online=[{"id": 71}])
    with _Patch(aid, fake):
        try:
            await server.of_send_or_schedule_mass(None, _body(min_total_spent=50))
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
                await server.of_send_or_schedule_mass(None, _body(**kw))
            except HTTPException as e:
                assert e.status_code == 422, (kw, e)
            else:
                raise AssertionError(f"{kw} with online-only must be refused")
    assert fake.roster_reads == 0 and fake.sent == []


def _list_body(lists, **kw):
    return server._MassScheduleBody(text="hey", user_lists=lists, **kw)


async def _refused(aid, fake, body) -> str:
    with _Patch(aid, fake):
        try:
            await server.of_send_or_schedule_mass(None, body)
        except HTTPException as e:
            assert e.status_code == 422, e
            assert fake.sent == [], fake.sent
            return str(e.detail)
    raise AssertionError("expected a 422 before any send")


async def case_route_narrows_the_picked_lists_never_widens():
    """Not online: the picked lists' members (read off OF) ∩ qualifying fans.
    A qualifying fan on no picked list — an old expired buyer — stays out."""
    aid = "acc_thr_lists"
    await _seed(aid, {81: {"lifetime_spend_cents": 9000}, 82: {"lifetime_spend_cents": 100},
                      83: {"lifetime_spend_cents": 9000}, 84: {"lifetime_spend_cents": 9000},
                      85: {"lifetime_spend_cents": 9000}})
    fake = FakeOF(fans=[81, 82], following=[84], lists={777: [85]})
    with _Patch(aid, fake):
        await server.of_send_or_schedule_mass(
            None, _list_body(["fans", "following", "777"], min_total_spent=50))
    (sent,) = fake.sent
    assert sent["included_users"] == [81, 84, 85], sent   # 83 is on no picked list
    assert sent["user_lists"] == [], sent


async def case_route_refuses_without_an_audience():
    """No list, no ids, not online: nothing to narrow, so nothing is sent (it
    used to mean every qualifying fan on record)."""
    aid = "acc_thr_nolists"
    await _seed(aid, {86: {"lifetime_spend_cents": 9000}})
    detail = await _refused(aid, FakeOF(fans=[86]), _list_body([], min_total_spent=50))
    assert "No fan clears" in detail, detail


async def case_route_refuses_an_unreadable_list():
    aid = "acc_thr_unread"
    await _seed(aid, {87: {"lifetime_spend_cents": 9000}})
    for lists in (["recent"], ["999"]):        # unknown built-in; a list OF won't page
        detail = await _refused(aid, FakeOF(fans=[87]), _list_body(lists, min_total_spent=50))
        assert "Couldn't read who is on" in detail, (lists, detail)


async def case_route_expired_over_reads_the_expired_fans():
    """Expired over: the built-in Fans/Following stand for the crawl's expired
    fans; with no complete crawl yet, refused rather than guessed."""
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
        s.add(SubscriberSnapshot(account_id=aid, fan_id=93, seen_at=NOW))   # still active
    fake = FakeOF(fans=[93])   # no list 999: with Fans picked it is never read
    with _Patch(aid, fake):
        await server.of_send_or_schedule_mass(
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
    """More fans online than the roster read: refused, never a silently cut
    roster (the read asks for one past the cap to know)."""
    import audiences
    aid = "acc_thr_online_cap"
    await _seed(aid, {101: {"lifetime_spend_cents": 9000}, 102: {"lifetime_spend_cents": 9000},
                      103: {"lifetime_spend_cents": 9000}})
    fake = FakeOF(online=[{"id": 101}, {"id": 102}, {"id": 103}])
    orig, audiences.ONLINE_ROSTER_MAX = audiences.ONLINE_ROSTER_MAX, 2
    try:
        detail = await _refused(aid, fake, _body(min_total_spent=50))
        assert "More than 2 fans are online" in detail, detail
        at_cap = FakeOF(online=[{"id": 101}, {"id": 102}])   # exactly the cap: sent
        with _Patch(aid, at_cap):
            await server.of_send_or_schedule_mass(None, _body(min_total_spent=50))
    finally:
        audiences.ONLINE_ROSTER_MAX = orig
    (sent,) = at_cap.sent
    assert sent["included_users"] == [101, 102], sent


async def case_route_subtracts_the_excluded_lists():
    """OF's `excludedLists` is verified on list audiences only, so a
    thresholded (explicit ids) send subtracts the excluded lists' members
    itself; one OF won't page is refused, not skipped."""
    aid = "acc_thr_excl"
    await _seed(aid, {111: {"lifetime_spend_cents": 9000}, 112: {"lifetime_spend_cents": 9000}})
    fake = FakeOF(fans=[111, 112], lists={555: [112]})
    with _Patch(aid, fake):
        await server.of_send_or_schedule_mass(
            None, _list_body(["fans"], excluded_user_lists=["555"], min_total_spent=50))
    (sent,) = fake.sent
    assert sent["included_users"] == [111], sent

    detail = await _refused(aid, FakeOF(fans=[111, 112]),
                            _list_body(["fans"], excluded_user_lists=["999"], min_total_spent=50))
    assert "Couldn't read who is on the excluded list 999" in detail, detail


async def case_route_tenure_keeps_a_list_member_without_a_fan_row():
    """A list member we have no fans row for, but whose subscribe date the
    crawl knows, clears Subscribed over."""
    aid = "acc_thr_norow"
    await _seed(aid, {})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=121, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=40)))
        s.add(SubscriberSnapshot(account_id=aid, fan_id=122, seen_at=NOW,
                                 subscribe_at=NOW - timedelta(days=5)))
    fake = FakeOF(lists={778: [121, 122]})
    with _Patch(aid, fake):
        await server.of_send_or_schedule_mass(
            None, _list_body(["778"], subscribed_over_days=30))
    (sent,) = fake.sent
    assert sent["included_users"] == [121], sent


async def case_route_expired_over_a_custom_list_needs_a_crawl():
    """Expired over on a custom list only, no crawl yet: the same 'not known
    yet' refusal, not an empty-audience one."""
    aid = "acc_thr_exp_custom"
    await _seed(aid, {131: {}})
    detail = await _refused(aid, FakeOF(lists={779: [131]}),
                            _list_body(["779"], expired_over_days=14))
    assert "Expired fans aren't known yet" in detail, detail


async def case_route_expired_over_narrows_a_custom_list():
    """With a crawl, a custom list's members are cut to the fans expired N+
    days: the list's still-active fan stays out."""
    aid = "acc_thr_exp_list"
    await _seed(aid, {141: {}, 142: {}})
    async with get_session() as s:
        s.add(SubscriberSnapshot(account_id=aid, fan_id=141, seen_at=NOW - timedelta(days=1),
                                 expired_at=NOW - timedelta(days=20)))   # gone 20d
        s.add(SubscriberSnapshot(account_id=aid, fan_id=142, seen_at=NOW))   # still active
    fake = FakeOF(lists={780: [141, 142]})
    with _Patch(aid, fake):
        await server.of_send_or_schedule_mass(None, _list_body(["780"], expired_over_days=14))
    (sent,) = fake.sent
    assert sent["included_users"] == [141], sent


_harness.run()
