#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import asyncio  # noqa: E402
import time  # noqa: E402

import mass_queue_api  # noqa: E402
import server  # noqa: E402
from audiences import broadcast_lock  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account  # noqa: E402
from db.models import MassRun  # noqa: E402
from of_client import OFAPIError  # noqa: E402
from curl_cffi import requests as curl  # noqa: E402
from fastapi import HTTPException  # noqa: E402

AUTO_LID = 555_001


class FakeOF:

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
        time.sleep(self.read_after_s)
        self.posts.append((kind, held, set(self.members.get(AUTO_LID, set()))))
        if self.fail:
            raise RuntimeError("OF 500")
        return {"id": 9001}

    def send_mass_message(self, text, **kw):
        return self._post("send")

    def schedule_mass_message(self, text, **kw):
        return self._post("schedule")


class _Patch:

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


async def _failed_real_proxy(kind: str, expected: str):
    aid = f"acc_lock_{kind}"
    await _account(aid)
    fake = FakeOF(aid)
    minted = []
    def fail(*_a, **_k):
        if kind == "proxy":
            raise curl.exceptions.ProxyError("CONNECT tunnel failed")
        if kind == "of400":
            response = type("Response", (), {"status_code": 400, "text": "rejected"})()
            raise OFAPIError("rejected", response=response)
        raise curl.exceptions.ReadTimeout("timeout")
    fake.send_mass_message = fail
    async def mint(*_a, **_k):
        async with get_session() as s:
            mr = MassRun(account_id=aid, audience_filter="{}", recipient_count=0, status="running")
            s.add(mr)
            await s.flush()
            minted.append(mr.id)
        return aid, None, minted[-1]
    with _Patch(fake):
        mass_queue_api._open_mass_run = mint
        try:
            await mass_queue_api.of_send_or_schedule_mass(
                None, mass_queue_api._MassScheduleBody(text="hey", user_ids=[1]))
        except HTTPException as e:
            assert e.__cause__ is not None, kind
        else:
            raise AssertionError("failure must surface")
    async with get_session() as s:
        mr = await s.get(MassRun, minted[0])
    assert mr.status == expected, (kind, mr.status)
    assert (mr.completed_at is not None) is (expected != "running")


async def case_real_proxy_failure_classifies_minted_run():
    await _failed_real_proxy("proxy", "refused")
    await _failed_real_proxy("of400", "failed")
    await _failed_real_proxy("timeout", "running")


async def case_concurrent_rewrite_waits_for_the_post():
    aid = "acc_lock_race"
    await _account(aid)
    fake = FakeOF(aid, read_after_s=0.1)

    async def taken():
        while not broadcast_lock(aid).locked():
            await asyncio.sleep(0)

    async def rewrite():
        await asyncio.wait_for(taken(), timeout=5)
        async with broadcast_lock(aid):
            fake.members.get(AUTO_LID, set()).clear()

    with _Patch(fake):
        await asyncio.gather(mass_queue_api.of_send_or_schedule_mass(None, _list_blast()), rewrite())
    assert fake.posts == [("send", True, {7, 8})], f"OF read a rewritten Auto_Exclude: {fake.posts}"
    assert fake.members[AUTO_LID] == set(), "the rewrite ran, after the POST"


async def case_a_may_have_sent_post_refuses_the_same_retry():
    aid = "acc_lock_retry"
    await _account(aid)
    fake = FakeOF(aid)
    def timeout(*_a, **_k):
        raise curl.exceptions.ReadTimeout("timeout")
    fake.send_mass_message = timeout
    body = lambda text="hey": mass_queue_api._MassScheduleBody(text=text, user_ids=[1])  # noqa: E731
    with _Patch(fake):
        try:
            await mass_queue_api.of_send_or_schedule_mass(None, body())
        except HTTPException:
            pass
        else:
            raise AssertionError("the timeout surfaces")
        sent = []
        fake.send_mass_message = lambda text, **kw: sent.append(text) or {"id": 9002}
        try:
            await mass_queue_api.of_send_or_schedule_mass(None, body())
        except HTTPException as e:
            assert e.status_code == 409, e.status_code
        else:
            raise AssertionError("the identical retry must be refused")
        assert sent == [], sent
        await mass_queue_api.of_send_or_schedule_mass(None, body("other"))
        assert sent == ["other"], sent

    aid = "acc_lock_retry400"
    await _account(aid)
    fake = FakeOF(aid)
    def of400(*_a, **_k):
        response = type("Response", (), {"status_code": 400, "text": "rejected"})()
        raise OFAPIError("rejected", response=response)
    fake.send_mass_message = of400
    with _Patch(fake):
        try:
            await mass_queue_api.of_send_or_schedule_mass(None, body())
        except HTTPException:
            pass
        sent = []
        fake.send_mass_message = lambda text, **kw: sent.append(text) or {"id": 9003}
        await mass_queue_api.of_send_or_schedule_mass(None, body())
        assert sent == ["hey"], sent


async def case_an_identical_send_while_the_first_is_in_flight_is_refused():
    import threading
    for aid, mk in (("acc_inflight_list", _list_blast),
                    ("acc_inflight_ids",
                     lambda: mass_queue_api._MassScheduleBody(text="hey", user_ids=[1]))):
        await _account(aid)
        fake = FakeOF(aid)
        entered, go, posts = threading.Event(), threading.Event(), []

        def hang(text, **_kw):
            posts.append(text)
            entered.set()
            go.wait(5)
            raise curl.exceptions.ReadTimeout("timeout")
        fake.send_mass_message = hang
        with _Patch(fake):
            first = asyncio.create_task(mass_queue_api.of_send_or_schedule_mass(None, mk()))
            assert await asyncio.to_thread(entered.wait, 5), "the first POST started"
            twin = asyncio.create_task(mass_queue_api.of_send_or_schedule_mass(None, mk()))
            await asyncio.sleep(0.05)
            go.set()
            r1, r2 = await asyncio.gather(first, twin, return_exceptions=True)
            assert isinstance(r1, HTTPException) and r1.status_code != 409, (aid, r1)
            assert isinstance(r2, HTTPException) and r2.status_code == 409, (aid, r2)
            assert posts == ["hey"], (aid, posts)
            try:
                await mass_queue_api.of_send_or_schedule_mass(None, mk())
            except HTTPException as e:
                assert e.status_code == 409, (aid, e.status_code)
            else:
                raise AssertionError("a retry after the timeout must be refused")
            assert posts == ["hey"], (aid, posts)

    aid = "acc_inflight_ok"
    await _account(aid)
    fake = FakeOF(aid)
    with _Patch(fake):
        await mass_queue_api.of_send_or_schedule_mass(None, _list_blast())
        await mass_queue_api.of_send_or_schedule_mass(None, _list_blast())
    assert [k for k, _, _ in fake.posts] == ["send", "send"], fake.posts


_harness.run()
