#!/usr/bin/env python3
"""POST /api/of/v2/messages/queue holds the account's `broadcast_lock` from the
Auto_Exclude sync through the OF POST (W24), as automation sends do.

  case_lock_held_through_send_now / case_lock_held_through_scheduled:
      a list blast with excluded ids: the lock is held when OF's send / schedule
      call runs, and free once the route returns.
  case_explicit_ids_never_lock:
      an explicit-ids blast needs no list, so never takes the lock.
  case_failed_post_releases_the_lock:
      OF raising on the POST still frees the lock.
  case_concurrent_rewrite_waits_for_the_post:
      a task that takes the lock and clears Auto_Exclude (another blast's sync,
      a refresh) cannot run between this blast's sync and OF reading the list.

Run: ./venv/bin/python service/tests/test_mass_queue_lock.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import time  # noqa: E402

import mass_queue_api  # noqa: E402
import server  # noqa: E402
from audiences import broadcast_lock  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402

AUTO_LID = 555_001


class FakeOF:
    """Auto_Exclude list API plus the broadcast surface; records whether the
    account's broadcast lock was held at each POST and the list OF read."""

    def __init__(self, aid: str, *, fail: bool = False, read_after_s: float = 0.0):
        self.aid, self.fail, self.read_after_s = aid, fail, read_after_s
        self.lists: list[dict] = []
        self.members: dict[int, set[int]] = {}
        self.posts: list[tuple[str, bool, set[int]]] = []

    def get_lists(self, *, limit=20, offset=0):
        return {"list": self.lists[offset:offset + limit], "hasMore": offset + limit < len(self.lists)}

    def create_list(self, name):
        self.lists.append({"id": AUTO_LID, "name": name})
        self.members[AUTO_LID] = set()
        return self.lists[-1]

    def list_users_in(self, list_id, *, limit=20, offset=0):
        ids = sorted(self.members.get(int(list_id), set()))
        return {"list": [{"id": i} for i in ids[offset:offset + limit]], "hasMore": offset + limit < len(ids)}

    def add_user_to_list(self, list_id, user_id):
        self.members.setdefault(int(list_id), set()).add(int(user_id))

    def remove_user_from_list(self, list_id, user_id):
        self.members.get(int(list_id), set()).discard(int(user_id))

    def _post(self, kind: str) -> dict:
        held = broadcast_lock(self.aid).locked()
        time.sleep(self.read_after_s)  # OF reads `excludedLists` while the POST is in flight
        self.posts.append((kind, held, set(self.members.get(AUTO_LID, set()))))
        if self.fail:
            raise RuntimeError("OF 500")
        return {"id": 9001}

    def send_mass_message(self, text, **kw):
        return self._post("send")

    def schedule_mass_message(self, text, **kw):
        return self._post("schedule")


class _Patch:
    """Swap server seams for one route call: the account, the OF client and the
    mass_runs bookkeeping (covered by test_send_mass)."""

    def __init__(self, fake: FakeOF):
        self.fake = fake

    def __enter__(self):
        async def _open(*_a, **_k):
            return self.fake.aid, None, None

        async def _close(*_a, **_k):
            return None
        self.orig = (server._resolve_account_id, server._get_client,
                     mass_queue_api._open_mass_run, mass_queue_api._close_mass_run)
        server._resolve_account_id = lambda _req: self.fake.aid
        server._get_client = lambda: self.fake
        mass_queue_api._open_mass_run = _open
        mass_queue_api._close_mass_run = _close
        return self

    def __exit__(self, *_):
        (server._resolve_account_id, server._get_client,
         mass_queue_api._open_mass_run, mass_queue_api._close_mass_run) = self.orig


async def _account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


def _list_blast(**kw):
    return mass_queue_api._MassScheduleBody(text="hey", user_lists=["fans"], excluded_users=[7, 8], **kw)


async def case_lock_held_through_send_now():
    aid = "acc_lock_send"
    await _account(aid)
    fake = FakeOF(aid)
    with _Patch(fake):
        await mass_queue_api.of_send_or_schedule_mass(None, _list_blast())
    assert fake.posts == [("send", True, {7, 8})], fake.posts
    assert not broadcast_lock(aid).locked(), "released after the route returns"


async def case_lock_held_through_scheduled():
    aid = "acc_lock_sched"
    await _account(aid)
    fake = FakeOF(aid)
    with _Patch(fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, _list_blast(scheduled_date="2026-12-01T10:00:00.000Z"))
    assert fake.posts == [("schedule", True, {7, 8})], fake.posts
    assert not broadcast_lock(aid).locked()


async def case_explicit_ids_never_lock():
    aid = "acc_lock_ids"
    await _account(aid)
    fake = FakeOF(aid)
    with _Patch(fake):
        await mass_queue_api.of_send_or_schedule_mass(
            None, mass_queue_api._MassScheduleBody(text="hey", user_ids=[1, 2, 7], excluded_users=[7]))
    assert [(k, held) for k, held, _ in fake.posts] == [("send", False)], fake.posts
    assert fake.lists == [], "no Auto_Exclude list touched"


async def case_failed_post_releases_the_lock():
    aid = "acc_lock_fail"
    await _account(aid)
    fake = FakeOF(aid, fail=True)
    with _Patch(fake):
        try:
            await mass_queue_api.of_send_or_schedule_mass(None, _list_blast())
        except Exception:
            pass
        else:
            raise AssertionError("the OF error surfaces")
    assert [held for _, held, _ in fake.posts] == [True], fake.posts
    assert not broadcast_lock(aid).locked(), "a failed POST frees the lock"


async def case_concurrent_rewrite_waits_for_the_post():
    aid = "acc_lock_race"
    await _account(aid)
    fake = FakeOF(aid, read_after_s=0.1)

    async def taken():
        while not broadcast_lock(aid).locked():
            await asyncio.sleep(0)

    async def rewrite():  # another sync / refresh: waits for the lock, then clears the list
        await asyncio.wait_for(taken(), timeout=5)
        async with broadcast_lock(aid):
            fake.members.get(AUTO_LID, set()).clear()

    with _Patch(fake):
        await asyncio.gather(mass_queue_api.of_send_or_schedule_mass(None, _list_blast()), rewrite())
    assert fake.posts == [("send", True, {7, 8})], f"OF read a rewritten Auto_Exclude: {fake.posts}"
    assert fake.members[AUTO_LID] == set(), "the rewrite ran, after the POST"


_harness.run()
