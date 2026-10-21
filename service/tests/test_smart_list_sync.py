#!/usr/bin/env python3
"""smart_list_sync — ACTIVE Smart Lists mirrored into OnlyFans user lists.

  case_first_sync_creates_and_adds       no OF list yet → create (id persisted),
                                         bulk-add the target, state ok, paced as
                                         not_fan_dm.
  case_diff_removes_after_full_crawl     extras on the OF list are removed, kept
                                         members untouched.
  case_truncated_crawl_writes_nothing    a crawl that hits the 20k backstop is a
                                         failed sync: no adds, no removals.
  case_write_budget_leaves_pending       the per-run write quota stops mid-diff
                                         (state pending); the next run finishes.
  case_unconfirmed_adds_are_reported     ids OF does not echo back are counted,
                                         not claimed as members.
  case_rename_is_reconciled              of_list_name != name → rename_list.
  case_inactive_and_locked_rows_skipped  only active lists sync; a crash-left
                                         `syncing` lock is released at run start.
  case_stale_roster_blocks_sub_lists     a list reading subscription facts syncs
                                         nothing when the roster crawl is unusable.
  case_empty_fan_table_holds_removals    no stored fans → no removals.
  case_of_list_gone_is_forgotten         404 on the crawl clears of_list_id.
  case_rename_waits_for_the_crawl        a list deleted on OF is forgotten, never
                                         renamed first.
  case_delete_of_list                    a `deleting` tombstone's OF list is
                                         deleted, then the row; a failed delete
                                         keeps it; payload ids are ignored.

Run: ./venv/bin/python service/tests/test_smart_list_sync.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automations import smart_list_sync as sls  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Fan, SmartList, SubscriberSnapshot,
)
from of_client import OFAPIError  # noqa: E402

_REAL_PACED = ax.of_write_paced
_REAL_MAKE_CLIENT = ax._make_client
_REAL_BUDGET = sls._MAX_WRITES_PER_RUN
PURPOSES: list = []

WHALES = {"rules": [{"field": "lifetime_spend", "op": ">=", "value": 10000}]}


class FakeOF:
    def __init__(self, *, lists=None, echo=True, roster=None):
        self.lists: dict[int, set[int]] = {int(k): set(v) for k, v in (lists or {}).items()}
        self.calls: list[tuple] = []
        self.echo = echo
        self.roster = roster or []
        self._next = 700

    def create_list(self, name):
        self._next += 1
        self.lists[self._next] = set()
        self.calls.append(("create_list", name))
        return {"id": self._next}

    def rename_list(self, list_id, name):
        self.calls.append(("rename_list", int(list_id), name))
        return {"id": int(list_id), "name": name}

    def delete_list(self, list_id):
        self.calls.append(("delete_list", int(list_id)))
        self.lists.pop(int(list_id), None)
        return {}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        if int(list_id) not in self.lists:
            raise OFAPIError("404 for lists", response=type("R", (), {"status_code": 404})())
        members = sorted(self.lists[int(list_id)])
        return [{"id": m} for m in members[offset:offset + limit]]

    def add_users_to_lists(self, users_by_list):
        self.calls.append(("add_users_to_lists", users_by_list))
        out = {}
        for lid, ids in users_by_list.items():
            self.lists.setdefault(int(lid), set()).update(ids)
            out[lid] = list(ids) if self.echo else []
        return out

    def remove_user_from_list(self, list_id, user_id):
        self.calls.append(("remove_user_from_list", int(list_id), int(user_id)))
        self.lists[int(list_id)].discard(int(user_id))
        return {}

    def subscribers(self, *, type="active", limit=10, offset=0, **kw):
        return {"list": self.roster[offset:offset + limit],
                "hasMore": offset + limit < len(self.roster)}


class EndlessOF(FakeOF):
    def list_users_in(self, list_id, *, limit=20, offset=0):
        return [{"id": 1_000_000 + offset + i} for i in range(limit)]


async def _unpaced(account_id, fn, **kw):
    PURPOSES.append(kw.get("send_purpose"))
    return await _REAL_PACED(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})


def _use(fake):
    ax._make_client = lambda account_id: fake
    ax.of_write_paced = _unpaced
    PURPOSES.clear()
    return fake


def _restore():
    ax._make_client = _REAL_MAKE_CLIENT
    ax.of_write_paced = _REAL_PACED
    sls._MAX_WRITES_PER_RUN = _REAL_BUDGET


async def _seed(aid, *, spenders=(1, 2, 3), small=(4,), rules=WHALES, active=True,
                of_list_id=None, of_list_name=None, state=None) -> int:
    async with get_session() as s:
        s.add(Account(id=aid))
    async with get_session() as s:
        for f in spenders:
            s.add(Fan(account_id=aid, fan_id=f, lifetime_spend_cents=20000))
        for f in small:
            s.add(Fan(account_id=aid, fan_id=f, lifetime_spend_cents=100))
        row = SmartList(account_id=aid, name="Whales", rules_json=json.dumps(rules),
                        is_active=active, of_list_id=of_list_id,
                        of_list_name=of_list_name or ("Whales" if of_list_id else None),
                        sync_state=state)
        s.add(row)
        await s.flush()
        return int(row.id)


async def _row(lid) -> SmartList:
    async with get_session() as s:
        return await s.get(SmartList, lid)


async def _sync(aid, payload=None):
    return await sls.run(aid, payload or {}, run_id=1)


async def case_first_sync_creates_and_adds():
    aid = "sls_first"
    lid = await _seed(aid)
    fake = _use(FakeOF())
    try:
        out = await _sync(aid)
    finally:
        _restore()
    assert out["ok"] == 1, out
    row = await _row(lid)
    assert row.of_list_id == 701 and row.of_list_name == "Whales", row.of_list_id
    assert fake.lists[701] == {1, 2, 3}, fake.lists
    assert ("create_list", "Whales") in fake.calls, fake.calls
    assert row.sync_state == "ok" and row.member_count == 3 and row.synced_at, \
        (row.sync_state, row.member_count)
    assert PURPOSES and set(PURPOSES) == {"not_fan_dm"}, PURPOSES


async def case_diff_removes_after_full_crawl():
    aid = "sls_diff"
    lid = await _seed(aid, of_list_id=800)
    fake = _use(FakeOF(lists={800: {1, 2, 4, 99}}))
    try:
        await _sync(aid)
    finally:
        _restore()
    assert fake.lists[800] == {1, 2, 3}, fake.lists
    removed = {c[2] for c in fake.calls if c[0] == "remove_user_from_list"}
    assert removed == {4, 99}, fake.calls
    assert ("create_list", "Whales") not in fake.calls
    assert (await _row(lid)).member_count == 3


async def case_truncated_crawl_writes_nothing():
    aid = "sls_trunc"
    lid = await _seed(aid, of_list_id=801)
    fake = _use(EndlessOF(lists={801: set()}))
    try:
        await _sync(aid)
    finally:
        _restore()
    assert fake.calls == [], fake.calls
    row = await _row(lid)
    assert row.sync_state == "error" and "incomplete" in row.sync_error, row.sync_error


async def case_write_budget_leaves_pending():
    aid = "sls_budget"
    lid = await _seed(aid, of_list_id=802)
    fake = _use(FakeOF(lists={802: {1, 2, 3, 90, 91, 92}}))
    try:
        sls._MAX_WRITES_PER_RUN = 2
        out = await _sync(aid)
        assert out["pending"] == 1 and out["writes"] == 2, out
        assert (await _row(lid)).sync_state == "pending"
        assert len(fake.lists[802] & {90, 91, 92}) == 1, fake.lists
        sls._MAX_WRITES_PER_RUN = 40
        out = await _sync(aid)
    finally:
        _restore()
    assert out["ok"] == 1, out
    assert fake.lists[802] == {1, 2, 3}, fake.lists


async def case_unconfirmed_adds_are_reported():
    aid = "sls_unconf"
    lid = await _seed(aid, of_list_id=803)
    _use(FakeOF(lists={803: set()}, echo=False))
    try:
        await _sync(aid)
    finally:
        _restore()
    row = await _row(lid)
    assert row.member_count == 0, row.member_count
    assert "3 fans could not be added" in (row.sync_error or ""), row.sync_error


async def case_rename_is_reconciled():
    aid = "sls_rename"
    lid = await _seed(aid, of_list_id=804, of_list_name="Old name")
    fake = _use(FakeOF(lists={804: {1, 2, 3}}))
    try:
        await _sync(aid)
    finally:
        _restore()
    assert ("rename_list", 804, "Whales") in fake.calls, fake.calls
    assert (await _row(lid)).of_list_name == "Whales"


async def case_inactive_and_locked_rows_skipped():
    aid = "sls_inactive"
    await _seed(aid, active=False, of_list_id=805)
    fake = _use(FakeOF(lists={805: {77}}))
    try:
        out = await _sync(aid)
    finally:
        _restore()
    assert out == {"status": "skipped", "reason": "no_active_lists"}, out
    assert fake.calls == []

    aid = "sls_locked"
    lid = await _seed(aid, of_list_id=806, state="syncing")
    fake = _use(FakeOF(lists={806: set()}))
    try:
        out = await _sync(aid)
    finally:
        _restore()
    # The crash-left lock is released and the list syncs in the same run.
    assert out["ok"] == 1, out
    assert (await _row(lid)).sync_state == "ok"


async def case_stale_roster_blocks_sub_lists():
    aid = "sls_roster"
    rules = {"rules": [{"field": "status", "op": "==", "value": "active"}]}
    lid = await _seed(aid, rules=rules, of_list_id=807)
    fake = _use(FakeOF(lists={807: {1, 2}}, roster=[]))   # empty roster crawl
    try:
        await _sync(aid)
    finally:
        _restore()
    assert [c for c in fake.calls if c[0] != "create_list"] == [], fake.calls
    row = await _row(lid)
    assert row.sync_state == "error" and "roster unavailable" in row.sync_error, row.sync_error

    # A usable crawl: the active roster drives the list.
    now = datetime.utcnow()
    fake = _use(FakeOF(lists={807: {1, 2}}, roster=[
        {"id": 2, "subscribedOnData": {"subscribeAt": (now - timedelta(days=9)).isoformat() + "Z",
                                       "expiredAt": (now + timedelta(days=21)).isoformat() + "Z",
                                       "status": "active"}},
        {"id": 3, "subscribedOnData": {"subscribeAt": (now - timedelta(days=2)).isoformat() + "Z",
                                       "expiredAt": (now + timedelta(days=28)).isoformat() + "Z",
                                       "status": "active"}},
    ]))
    try:
        await _sync(aid)
    finally:
        _restore()
    assert fake.lists[807] == {2, 3}, fake.lists
    async with get_session() as s:
        snap = (await s.execute(select(SubscriberSnapshot.fan_id).where(
            SubscriberSnapshot.account_id == aid))).scalars().all()
    assert sorted(snap) == [2, 3], snap


async def case_empty_fan_table_holds_removals():
    aid = "sls_nofans"
    lid = await _seed(aid, spenders=(), small=(), of_list_id=808)
    fake = _use(FakeOF(lists={808: {1, 2}}))
    try:
        await _sync(aid)
    finally:
        _restore()
    assert fake.lists[808] == {1, 2}, fake.lists
    assert "removals held" in (await _row(lid)).sync_error


async def case_of_list_gone_is_forgotten():
    aid = "sls_gone"
    lid = await _seed(aid, of_list_id=809)
    _use(FakeOF())                                          # 809 does not exist
    try:
        await _sync(aid)
    finally:
        _restore()
    row = await _row(lid)
    assert row.of_list_id is None and row.sync_state == "error", (row.of_list_id, row.sync_state)
    fake = _use(FakeOF())
    try:
        await _sync(aid)
    finally:
        _restore()
    assert ("create_list", "Whales") in fake.calls, fake.calls


async def case_rename_waits_for_the_crawl():
    aid = "sls_rename_gone"
    lid = await _seed(aid, of_list_id=812, of_list_name="Old name")
    fake = _use(FakeOF())                                   # 812 was deleted on OF
    try:
        await _sync(aid)
    finally:
        _restore()
    assert not any(c[0] == "rename_list" for c in fake.calls), fake.calls
    assert (await _row(lid)).of_list_id is None


class FlakyDeleteOF(FakeOF):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.fail = True

    def delete_list(self, list_id):
        if self.fail:
            self.calls.append(("delete_list_failed", int(list_id)))
            raise OFAPIError("500", response=type("R", (), {"status_code": 500})())
        return super().delete_list(list_id)


async def case_delete_of_list():
    aid = "sls_delete"
    lid = await _seed(aid, active=False, of_list_id=810, state="deleting")
    other = "sls_delete_other"                     # another account's tombstone
    await _seed(other, active=False, of_list_id=813, state="deleting")
    fake = _use(FlakyDeleteOF(lists={810: {1}, 811: {2}, 813: {3}}))
    try:
        # A payload naming an OF list (811 — made by hand) is ignored outright.
        await sls.run(aid, {"delete_of_list_id": 811}, run_id=1)
        assert (await _row(lid)) is not None, "a failed delete keeps the tombstone"
        fake.fail = False
        out = await sls.run(aid, {"delete_of_list_id": 811}, run_id=2)
    finally:
        _restore()
    assert out["deleted"] == 1, out
    assert fake.calls == [("delete_list_failed", 810), ("delete_list", 810)], fake.calls
    assert set(fake.lists) == {811, 813}, fake.lists
    assert (await _row(lid)) is None
    assert PURPOSES == ["not_fan_dm", "not_fan_dm"], PURPOSES


_harness.run(
    case_first_sync_creates_and_adds,
    case_diff_removes_after_full_crawl,
    case_truncated_crawl_writes_nothing,
    case_write_budget_leaves_pending,
    case_unconfirmed_adds_are_reported,
    case_rename_is_reconciled,
    case_inactive_and_locked_rows_skipped,
    case_stale_roster_blocks_sub_lists,
    case_empty_fan_table_holds_removals,
    case_of_list_gone_is_forgotten,
    case_rename_waits_for_the_crawl,
    case_delete_of_list,
)
