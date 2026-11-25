#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — module under test
import client_pool  # noqa: E402 — the OFClient pool behind ax._make_client
from automation_executor import (  # noqa: E402
    acquire_fan_lease,
    enqueue_job,
    release_fan_lease,
    run_once,
)
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AccountAiConfig,
    AutomationRule,
    AutomationRun,
    Chat,
    Fan,
    MassRun,
    Message,
    ScheduledJob,
    ScrapeHistory,
    Transaction,
)

OWN_ID = "999"



def _of_msg(
    mid: int, from_fan: bool, text: str, created: str, *, fan_id: int,
    price: float = 0, is_opened=None, is_tip: bool = False, media_count: int = 0,
    media: list | None = None,
) -> dict:
    if from_fan:
        from_user = {
            "id": fan_id, "username": "bob_fan", "name": "Bob",
            "avatar": "http://a/bob.jpg", "subscribedOn": True,
        }
    else:
        from_user = {"id": int(OWN_ID), "username": "me", "name": "Me"}
    return {
        "id": mid,
        "text": f"<p>{text}</p>",
        "price": price,
        "isOpened": is_opened,
        "isTip": is_tip,
        "mediaCount": media_count,
        "media": media or [],
        "fromUser": from_user,
        "createdAt": created,
    }


class FakeClient:

    def __init__(self, chats: dict[int, list[dict]], user_id: str = OWN_ID):
        self.user_id = user_id
        self._chats = {int(k): v for k, v in chats.items()}

    def list_chats(self, *, limit: int = 10, offset: int = 0,
                   order: str = "recent", **kw) -> dict:
        return {
            "list": [
                {"withUser": {
                    "id": cid, "username": f"sweep_{cid}", "name": f"Sweep {cid}",
                    "avatar": "http://a/sw.jpg", "subscribedOn": True,
                }}
                for cid in self._chats
            ],
            "hasMore": False,
        }

    def get_messages(self, chat_id, *, limit: int = 10, order: str = "desc",
                     before_id=None, **kw) -> dict:
        msgs = self._chats.get(int(chat_id), [])
        if before_id is None:
            return {"list": list(msgs), "hasMore": False}
        return {"list": [], "hasMore": False}


class PagedFakeClient:

    def __init__(self, chat_id: int, msgs: list[dict], *, user_id: str = OWN_ID,
                 page_rows: int = 13):
        self.user_id = user_id
        self.chat_id = int(chat_id)
        self._asc = sorted(msgs, key=lambda m: m["id"])
        self.page_rows = page_rows
        self.calls: list[tuple] = []

    def list_chats(self, **kw) -> dict:
        return {"list": [], "hasMore": False}

    def get_messages(self, chat_id, *, limit: int = 10, order: str = "desc",
                     before_id=None, offset=None, **kw) -> dict:
        self.calls.append((order, before_id, offset))
        n = min(self.page_rows, limit)  # OF returns fewer than `limit`
        if order == "asc":
            start = int(offset or 0)
            window = self._asc[start:start + n]
            has_more = start + n < len(self._asc)
            return {"list": list(window), "hasMore": has_more}
        pool = [m for m in reversed(self._asc)
                if before_id is None or m["id"] < int(before_id)]
        window = pool[:n]
        return {"list": list(window), "hasMore": len(pool) > n}


class PagedListClient:

    def __init__(self, chat_ids: list[int], user_id: str = OWN_ID, page: int = 10):
        self.user_id = user_id
        self._ids = [int(c) for c in chat_ids]
        self._page = page
        self.offsets_requested: list[int] = []

    def list_chats(self, *, limit: int = 10, offset: int = 0,
                   order: str = "recent", **kw) -> dict:
        self.offsets_requested.append(offset)
        window = self._ids[offset:offset + self._page]
        return {
            "list": [{"withUser": {"id": cid, "username": f"u{cid}",
                                   "name": f"N{cid}", "subscribedOn": True}}
                     for cid in window],
            "hasMore": offset + self._page < len(self._ids),
        }

    def get_messages(self, chat_id, *, limit: int = 10, order: str = "desc",
                     before_id=None, offset=None, **kw) -> dict:
        if order == "asc" or before_id is not None:
            return {"list": [], "hasMore": False}
        cid = int(chat_id)
        return {"list": [_of_msg(cid * 10 + 1, True, "hi", "2026-06-03T10:00:00+00:00",
                                 fan_id=cid)], "hasMore": False}


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _read_chat(aid: str, fan: int, unread: int = 0) -> None:
    async with get_session() as s:
        row = await s.get(Chat, (aid, fan))
        if row is None:
            s.add(Chat(account_id=aid, fan_id=fan, unread_count=unread))
        else:
            row.unread_count = unread


def _use_fake(chats: dict[int, list[dict]]) -> None:
    fake = FakeClient(chats)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]



async def case_scrape_job_persists_both_directions():
    aid, fan = "acc_scrape1", 2001
    await _seed_account(aid)
    _use_fake({fan: [
        _of_msg(5003, True, "hey there", "2026-06-01T10:00:00+00:00", fan_id=fan),
        _of_msg(5002, False, "hello!", "2026-06-01T09:59:00+00:00", fan_id=fan),
        _of_msg(5001, True, "hi", "2026-06-01T09:58:00+00:00", fan_id=fan),
    ]})

    job_id = await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    res = await run_once(aid, "scrape_chats")

    assert res["status"] == "ok", res
    assert res["job_id"] == job_id, res
    assert res["messages_inserted"] == 3, res
    assert res["messages_seen"] == 3, res

    async with get_session() as s:
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1, f"one run row, got {len(runs)}"
        assert runs[0].status == "ok", runs[0].status
        assert runs[0].kind == "scrape_chats"
        assert runs[0].completed_at is not None, "completed_at stamped"
        stats = json.loads(runs[0].stats_json)
        assert stats["messages_inserted"] == 3 and stats["chats_scanned"] == 1, stats
        assert "duration_ms" in stats, "duration recorded"

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all()
        assert len(msgs) == 3, f"three messages persisted, got {len(msgs)}"
        assert sorted(m.direction for m in msgs) == ["in", "in", "out"], \
            [m.direction for m in msgs]

        job = await s.get(ScheduledJob, job_id)
        assert job.status == "done", f"job marked done, got {job.status}"

        chat = await s.get(Chat, (aid, fan))
        assert chat is not None and chat.last_message_id == 5003, chat
        assert "hey there" in (chat.last_message_preview or ""), chat.last_message_preview

        hist = await s.get(ScrapeHistory, (aid, fan))
        assert hist is not None and hist.last_message_id == 5003, "scrape cursor advanced"

        f = await s.get(Fan, (aid, fan))
        assert f is not None, "fan row created"
        assert f.of_username == "bob_fan" and f.of_display_name == "Bob", \
            (f.of_username, f.of_display_name)



async def case_scrape_fast_skip():
    aid, fan = "acc_scrape2", 2002
    await _seed_account(aid)
    _use_fake({fan: [
        _of_msg(6002, True, "yo", "2026-06-02T10:00:00+00:00", fan_id=fan),
        _of_msg(6001, True, "sup", "2026-06-02T09:59:00+00:00", fan_id=fan),
    ]})

    await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    r1 = await run_once(aid, "scrape_chats")
    assert r1["messages_inserted"] == 2, r1

    await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    r2 = await run_once(aid, "scrape_chats")
    assert r2["status"] == "ok", r2
    assert r2["messages_inserted"] == 0, r2
    assert r2["messages_seen"] == 0, r2

    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all()
        assert len(msgs) == 2, f"no duplicates, got {len(msgs)}"
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 2 and all(r.status == "ok" for r in runs), \
            [r.status for r in runs]



async def case_scrape_all_chats_sweep():
    aid, fan_a, fan_b = "acc_scrape3", 3001, 3002
    await _seed_account(aid)
    _use_fake({
        fan_a: [_of_msg(7001, True, "from A", "2026-06-03T10:00:00+00:00", fan_id=fan_a)],
        fan_b: [_of_msg(7002, True, "from B", "2026-06-03T10:01:00+00:00", fan_id=fan_b)],
    })

    await enqueue_job(aid, "scrape_chats", payload={})
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["chats_scanned"] == 2, res
    assert res["messages_inserted"] == 2, res

    async with get_session() as s:
        fa = await s.get(Fan, (aid, fan_a))
        assert fa is not None and fa.of_username == "sweep_3001", \
            "identity lifted from withUser in the sweep"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 2, len(msgs)



async def case_scrape_sweep_paginates_all_chats():
    aid = "acc_scrape_pg"
    await _seed_account(aid)
    chat_ids = list(range(4001, 4024))
    fake = PagedListClient(chat_ids)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    await enqueue_job(aid, "scrape_chats", payload={})
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["chats_scanned"] == 23, res
    assert fake.offsets_requested == [0, 10, 20], fake.offsets_requested
    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 23, len(msgs)



async def case_scrape_full_sweep_mark_only_on_empty_payload():
    aid, read, unread = "acc_scrape_unread", 4101, 4102
    await _seed_account(aid)
    chats = {c: [_of_msg(c * 10, True, "hi", "2026-06-04T10:00:00+00:00", fan_id=c)]
             for c in (read, unread)}
    fetched: list[int] = []

    class UnreadClient(FakeClient):
        def list_chats(self, **kw) -> dict:
            page = super().list_chats(**kw)
            for row in page["list"]:
                row["unreadMessagesCount"] = 2 if row["withUser"]["id"] == unread else 0
            return page

        def get_messages(self, chat_id, **kw) -> dict:
            fetched.append(int(chat_id))
            return super().get_messages(chat_id, **kw)

    ax._make_client = lambda account_id: UnreadClient(chats)  # type: ignore[attr-defined]
    for payload, want_fetched, full in (({}, {read, unread}, True),
                                        ({"fan_ids": [unread]}, {unread}, False),
                                        ({"limit": 50}, {read, unread}, False)):
        fetched.clear()
        await enqueue_job(aid, "scrape_chats", payload=payload)
        res = await run_once(aid, "scrape_chats")
        assert res["status"] == "ok" and set(fetched) == want_fetched, (payload, res, fetched)
        assert res.get("full_sweep", False) is full, (payload, res)



async def case_scrape_long_convo_both_ends():
    aid, fan = "acc_long", 5100
    await _seed_account(aid)
    msgs = [
        _of_msg(i, from_fan=(i % 2 == 0), text=f"m{i}",
                created=f"2026-06-01T00:{i // 60:02d}:{i % 60:02d}+00:00", fan_id=fan)
        for i in range(1, 201)
    ]
    fake = PagedFakeClient(fan, msgs)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    await _read_chat(aid, fan)

    await enqueue_job(aid, "scrape_chats",
                      payload={"chat_ids": [fan], "recent_cap": 50, "oldest_cap": 50})
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["messages_inserted"] <= 110, res
    assert res["messages_inserted"] >= 90, res

    orders = {o for (o, _bid, _off) in fake.calls}
    assert await _gap(aid, fan) == (200, 50, 151), await _gap(aid, fan)
    assert orders == {"desc", "asc"}, fake.calls
    assert any(off == 0 for (_o, _bid, off) in fake.calls if _o == "asc"), \
        "oldest end started at offset=0"

    async with get_session() as s:
        ids = sorted(m.message_id for m in (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all())
        assert ids[0] == 1, f"convo START (id 1) persisted, got {ids[0]}"
        assert ids[-1] == 200, f"convo END (id 200) persisted, got {ids[-1]}"
        assert 100 not in ids, "the middle is intentionally skipped"
        assert len(ids) <= 110, f"never thousands, got {len(ids)}"

        hist = await s.get(ScrapeHistory, (aid, fan))
        assert hist.last_message_id == 200, "fast-skip cursor at the newest id"


async def case_scrape_desc_catch_up_no_refetch_start():
    aid, fan = "acc_catchup", 5200
    await _seed_account(aid)
    msgs = [
        _of_msg(i, from_fan=(i % 2 == 0), text=f"m{i}",
                created=f"2026-06-02T00:{i // 60:02d}:{i % 60:02d}+00:00", fan_id=fan)
        for i in range(1, 201)
    ]
    fake = PagedFakeClient(fan, msgs)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=180,
                            last_message_text="m180"))

    await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["messages_inserted"] == 20, res

    assert all(o == "desc" for (o, _bid, _off) in fake.calls), fake.calls

    async with get_session() as s:
        ids = sorted(m.message_id for m in (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all())
        assert ids == list(range(181, 201)), ids
        assert 1 not in ids, "convo start was NOT re-fetched on a catch-up"


async def _stored_ids(aid: str, fan: int) -> list[int]:
    async with get_session() as s:
        return sorted(m for m in (await s.execute(select(Message.message_id).where(
            Message.account_id == aid, Message.fan_id == fan))).scalars().all())


async def _gap(aid: str, fan: int):
    async with get_session() as s:
        h = await s.get(ScrapeHistory, (aid, fan))
        return h.last_message_id, h.gap_after_id, h.gap_before_id


def _msgs(fan: int, ids) -> list[dict]:
    return [_of_msg(i, from_fan=(i % 2 == 0), text=f"m{i}",
                    created=f"2026-06-02T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+00:00", fan_id=fan)
            for i in ids]


async def case_gap_only_scrape_keeps_recency_and_preview():
    from automations.scrape_chats import _scrape_one_chat
    aid, fan = "acc_catchup", 5393
    fresh = datetime(2026, 6, 3)
    await _seed_account(aid)
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=30,
                            gap_after_id=10, gap_before_id=15))
        s.add(Fan(account_id=aid, fan_id=fan, of_username="current", last_message_received_at=fresh,
                  last_message_sent_at=fresh))
        s.add(Chat(account_id=aid, fan_id=fan, last_message_id=29,
                   last_message_preview="current", last_message_at=fresh))
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 31)))
    chunk = await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=10, max_pages=2)
    assert (chunk.inserted, chunk.seen) == (4, 4)
    assert chunk.history_saved and not chunk.rate_limited and not chunk.gap_left, chunk
    async with get_session() as s:
        saved_fan = await s.get(Fan, (aid, fan))
        saved_chat = await s.get(Chat, (aid, fan))
        assert saved_fan.of_username == "current"
        assert (saved_fan.last_message_received_at, saved_fan.last_message_sent_at) == (fresh, fresh)
        assert (saved_chat.last_message_id, saved_chat.last_message_preview,
                saved_chat.last_message_at) == (29, "current", fresh)


async def case_dropped_dm_scrape_only_peeks():
    from events_persist import DM_DROPPED_SOURCE
    from webhook_dispatch import enqueue_fan_scrape
    aid, fan = "acc_catchup", 5391
    await _seed_account(aid)
    await _read_chat(aid, fan)
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 130)))
    ax._make_client = lambda account_id: fake
    assert await enqueue_fan_scrape(aid, fan, DM_DROPPED_SOURCE, peek_only=True)
    assert (await run_once(aid, "scrape_fan"))["status"] == "ok"
    assert fake.calls and all(order == "desc" for order, _, _ in fake.calls), fake.calls


async def case_idle_scrape_keeps_a_concurrently_opened_gap():
    from automations.scrape_chats import _scrape_one_chat
    aid, fan = "acc_catchup", 5392
    await _seed_account(aid)
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=10))

    started, release = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()

    class Idle(PagedFakeClient):
        def get_messages(self, chat_id, **kw):
            loop.call_soon_threadsafe(started.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result(timeout=5)
            return super().get_messages(chat_id, **kw)

    async def scrape(fake):
        return await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=10,
                                      max_pages=1, recent_cap=3)

    idle = asyncio.create_task(scrape(Idle(fan, _msgs(fan, range(1, 11)))))
    await asyncio.wait_for(started.wait(), 5)
    try:
        await scrape(PagedFakeClient(fan, _msgs(fan, range(1, 31))))
    finally:
        release.set()
        chunk = await idle
    assert not chunk.history_saved and chunk.gap_left, chunk
    assert await _gap(aid, fan) == (30, 10, 28), await _gap(aid, fan)


async def case_scrape_capped_catch_up_keeps_the_middle():
    aid, fan = "acc_catchup", 5300
    await _seed_account(aid)
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 201)))
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=20, last_message_text="m20"))

    payload = {"chat_ids": [fan], "recent_cap": 50}
    await enqueue_job(aid, "scrape_chats", payload=payload)
    assert (await run_once(aid, "scrape_chats"))["status"] == "ok"
    assert await _stored_ids(aid, fan) == list(range(151, 201))
    assert await _gap(aid, fan) == (200, 20, 151), await _gap(aid, fan)

    for want_lo, gap in ((101, (200, 20, 101)), (51, (200, 20, 51)), (21, (200, None, None))):
        await enqueue_job(aid, "scrape_chats", payload=payload)
        assert (await run_once(aid, "scrape_chats"))["status"] == "ok"
        assert await _stored_ids(aid, fan) == list(range(want_lo, 201)), want_lo
        assert await _gap(aid, fan) == gap, (want_lo, await _gap(aid, fan))
    async with get_session() as s:
        assert (await s.get(ScrapeHistory, (aid, fan))).last_message_text == "m200"
    assert all(o == "desc" for (o, _b, _off) in fake.calls), fake.calls


async def case_scrape_gap_merges_when_the_newest_end_caps_again():
    aid, fan = "acc_catchup", 5301
    await _seed_account(aid)
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 201)))
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=20, last_message_text="m20"))
    payload = {"chat_ids": [fan], "recent_cap": 50}
    await enqueue_job(aid, "scrape_chats", payload=payload)
    await run_once(aid, "scrape_chats")
    fake._asc += _msgs(fan, range(201, 301))
    await enqueue_job(aid, "scrape_chats", payload=payload)
    await run_once(aid, "scrape_chats")
    assert await _gap(aid, fan) == (300, 20, 251), await _gap(aid, fan)
    for _ in range(6):
        await enqueue_job(aid, "scrape_chats", payload=payload)
        await run_once(aid, "scrape_chats")
    assert await _stored_ids(aid, fan) == list(range(21, 301))
    assert await _gap(aid, fan) == (300, None, None)


class _ThrottledAfter(PagedFakeClient):
    def __init__(self, *a, ok_pages: int, **kw):
        super().__init__(*a, **kw)
        self.ok_pages = ok_pages

    def get_messages(self, chat_id, **kw) -> dict:
        if len(self.calls) >= self.ok_pages:
            from of_client import OFAPIError
            self.calls.append(("429", kw.get("before_id"), None))
            raise OFAPIError("429", response=type("R", (), {"status_code": 429})())
        return super().get_messages(chat_id, **kw)


async def case_scrape_full_pull_keeps_what_it_read_on_429():
    from automations.scrape_chats import _scrape_one_chat
    from of_client import OFAPIError
    aid, fan = "acc_catchup", 5302
    await _seed_account(aid)
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=10, last_message_text="m10"))
    fake = _ThrottledAfter(fan, _msgs(fan, range(1, 201)), ok_pages=3)
    chunk = await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=50,
                                       max_pages=40, recent_cap=300, mode="pull")
    assert chunk.rate_limited and chunk.seen == 39
    assert chunk.inserted == 39 and await _stored_ids(aid, fan) == list(range(162, 201)), chunk
    assert await _gap(aid, fan) == (200, 10, 162)
    assert all(o in ("desc", "429") for (o, _b, _off) in fake.calls), fake.calls

    fake = PagedFakeClient(fan, _msgs(fan, range(1, 201)))
    await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=50,
                           max_pages=40, recent_cap=300, mode="pull")
    assert await _stored_ids(aid, fan) == list(range(11, 201))
    assert await _gap(aid, fan) == (200, None, None)

    fake = _ThrottledAfter(fan, _msgs(fan, range(1, 201)), ok_pages=0)
    try:
        await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=50,
                               max_pages=40, recent_cap=300, mode="pull")
    except OFAPIError as e:
        assert "429" in str(e), e
    else:
        raise AssertionError("page-1 429 must raise")


async def case_scrape_full_pull_first_scrape_cut_by_429_keeps_a_gap_to_the_start():
    from automations.scrape_chats import _scrape_one_chat
    aid, fan = "acc_catchup", 5307
    await _read_chat(aid, fan)
    fake = _ThrottledAfter(fan, _msgs(fan, range(1, 101)), ok_pages=2)
    await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=50,
                           max_pages=40, recent_cap=300, mode="pull")
    assert await _stored_ids(aid, fan) == list(range(75, 101))
    assert await _gap(aid, fan) == (100, 0, 75), await _gap(aid, fan)
    assert {o for (o, _b, _off) in fake.calls} == {"desc", "429"}, fake.calls
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 101)))
    await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=50, max_pages=40)
    assert await _stored_ids(aid, fan) == list(range(1, 101))
    assert await _gap(aid, fan) == (100, None, None)


async def case_scrape_full_pull_first_scrape_reads_to_the_start():
    from automations.scrape_chats import _scrape_one_chat
    aid, fan = "acc_catchup", 5303
    await _seed_account(aid)
    await _read_chat(aid, fan)
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 301)))
    await _scrape_one_chat(aid, OWN_ID, fake, fan, None, page_size=50,
                           max_pages=40, recent_cap=300, mode="pull")
    assert await _stored_ids(aid, fan) == list(range(1, 301))
    assert {o for (o, _b, _off) in fake.calls} == {"desc"}, fake.calls


async def case_rescrape_now_commits_a_bounded_chunk_and_resumes():
    import messages as msg_routes
    from automations import scrape_chats as sc
    aid, fan = "acc_catchup", 5394
    await _seed_account(aid)
    fake = PagedFakeClient(fan, _msgs(fan, range(1, 125)))
    budget = msg_routes._PULL_MAX_CHUNKS
    real = (ax._make_client, msg_routes.assert_account_owned, sc._PAGE_SLEEP_S)
    ax._make_client = lambda _aid: fake
    msg_routes.assert_account_owned = lambda _aid: None
    msg_routes._PULL_MAX_CHUNKS, sc._PAGE_SLEEP_S = 1, 0
    try:
        first = await msg_routes.rescrape_chat_now(aid, fan)
        assert first["seen"] == 100 and not first["ok"] and first["status"] == "partial", first
        assert await _gap(aid, fan) == (124, 0, 25)
        assert await _stored_ids(aid, fan) == list(range(25, 125))
        second = await msg_routes.rescrape_chat_now(aid, fan)
        assert second["seen"] == 24 and second["ok"] and second["status"] == "complete", second
        assert await _gap(aid, fan) == (124, None, None)
        assert await _stored_ids(aid, fan) == list(range(1, 125))
    finally:
        ax._make_client, msg_routes.assert_account_owned, sc._PAGE_SLEEP_S = real
        msg_routes._PULL_MAX_CHUNKS = budget


async def case_rescrape_now_retries_after_losing_the_gap_cas():
    import messages as msg_routes
    from automations import scrape_chats as sc
    aid, fan = "acc_catchup", 5397
    await _seed_account(aid)
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=10))

    timeline = _msgs(fan, range(1, 31))
    loop = asyncio.get_running_loop()

    class InterleavedPull(PagedFakeClient):
        def get_messages(self, chat_id, **kw):
            if not self.calls:
                winner = PagedFakeClient(fan, timeline[:15])
                scrape = sc._scrape_one_chat(aid, OWN_ID, winner, fan, None,
                                             page_size=13, max_pages=1, mode="peek")
                asyncio.run_coroutine_threadsafe(scrape, loop).result(timeout=5)
            return super().get_messages(chat_id, **kw)

    fake = InterleavedPull(fan, timeline)
    real = (ax._make_client, ax._SCRAPE_MAX_PAGES, msg_routes.assert_account_owned, sc._PAGE_SLEEP_S)
    ax._make_client = lambda _aid: fake
    ax._SCRAPE_MAX_PAGES = 1
    msg_routes.assert_account_owned = lambda _aid: None
    sc._PAGE_SLEEP_S = 0
    try:
        result = await msg_routes.rescrape_chat_now(aid, fan)
        assert result["ok"] and result["status"] == "complete", result
        assert await _stored_ids(aid, fan) == list(range(11, 31)), result
        assert await _gap(aid, fan) == (30, None, None)
    finally:
        ax._make_client, ax._SCRAPE_MAX_PAGES, msg_routes.assert_account_owned, sc._PAGE_SLEEP_S = real


async def case_rescrape_now_stops_on_429_with_a_resumable_gap():
    import messages as msg_routes
    from automations import scrape_chats as sc
    aid, fan = "acc_catchup", 5396
    await _seed_account(aid)
    fake = _ThrottledAfter(fan, _msgs(fan, range(1, 125)), ok_pages=2)
    real = (ax._make_client, msg_routes.assert_account_owned, sc._PAGE_SLEEP_S)
    ax._make_client = lambda _aid: fake
    msg_routes.assert_account_owned = lambda _aid: None
    sc._PAGE_SLEEP_S = 0
    try:
        result = await msg_routes.rescrape_chat_now(aid, fan)
        assert not result["ok"] and result["status"] == "partial" and result["seen"] == 26, result
        assert len(fake.calls) == 3, fake.calls
        assert await _gap(aid, fan) == (124, 0, 99)

        fake.ok_pages = 4
        result = await msg_routes.rescrape_chat_now(aid, fan)
        assert not result["ok"] and result["status"] == "partial" and result["seen"] == 0, result
        assert len(fake.calls) == 5, fake.calls
        assert await _gap(aid, fan) == (124, 0, 99)
    finally:
        ax._make_client, msg_routes.assert_account_owned, sc._PAGE_SLEEP_S = real


async def case_rescrape_now_pulls_whole_history_and_continues_past_the_wait():
    import time as _time
    import messages as msg_routes
    from automations import scrape_chats as sc
    aid, fan = "acc_catchup", 5306
    await _seed_account(aid)
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=5, last_message_text="m5"))

    class Slow(PagedFakeClient):
        def get_messages(self, chat_id, **kw):
            _time.sleep(0.02)
            return super().get_messages(chat_id, **kw)

    fake = Slow(fan, _msgs(fan, range(1, 501)))
    real = (ax._make_client, msg_routes.assert_account_owned, msg_routes._PULL_WAIT_S, sc._PAGE_SLEEP_S)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    msg_routes.assert_account_owned = lambda _a: None
    msg_routes._PULL_WAIT_S, sc._PAGE_SLEEP_S = 0.05, 0
    try:
        first = await msg_routes.rescrape_chat_now(aid, fan)
        assert not first["ok"] and first.get("status") == "pending", first
        task = msg_routes._full_pulls[(aid, fan)]
        again = await msg_routes.rescrape_chat_now(aid, fan)
        assert again.get("status") == "pending" and msg_routes._full_pulls[(aid, fan)] is task, again
        await task
        assert (aid, fan) not in msg_routes._full_pulls
        assert await _stored_ids(aid, fan) == list(range(6, 501))
        assert await _gap(aid, fan) == (500, None, None)
        assert {o for (o, _b, _off) in fake.calls} == {"desc"}
        msg_routes._PULL_WAIT_S = 5
        done = await msg_routes.rescrape_chat_now(aid, fan)
        assert done["ok"] and done["status"] == "complete" and done["inserted"] == 0, done
    finally:
        ax._make_client, msg_routes.assert_account_owned, msg_routes._PULL_WAIT_S, sc._PAGE_SLEEP_S = real


async def case_scrape_heals_only_a_stored_zero_price():
    from automations.scrape_chats import _upsert_message
    aid, fan = "acc_catchup", 5304
    await _seed_account(aid)
    async with get_session() as s:
        for mid, cents in ((1, 0), (2, 700)):
            s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out", sender_name="",
                          body="ppv", media_ids="[]", media_count=0, price_cents=cents, is_tip=False,
                          is_unsent=False, raw_json="{}", created_at=datetime(2026, 6, 1)))
    async with get_session() as s:
        for mid in (1, 2):
            await _upsert_message(s, aid, fan, OWN_ID, _of_msg(
                mid, False, "ppv", "2026-06-01T00:00:00+00:00", fan_id=fan, price=12.5, is_opened=False))
    async with get_session() as s:
        got = {m.message_id: m.price_cents for m in (await s.execute(select(Message).where(
            Message.account_id == aid, Message.fan_id == fan))).scalars()}
    assert got == {1: 1250, 2: 700}, got


async def case_thread_page_save_upserts_by_id():
    from automations.scrape_chats import save_thread_page
    aid, fan = "acc_catchup", 5305
    await _seed_account(aid)
    await save_thread_page(aid, fan, OWN_ID, list(reversed(_msgs(fan, range(40, 51)))))
    await save_thread_page(aid, fan, OWN_ID, list(reversed(_msgs(fan, range(35, 46)))))
    assert await _stored_ids(aid, fan) == list(range(35, 51))
    async with get_session() as s:
        dirs = {m.message_id: m.direction for m in (await s.execute(select(Message).where(
            Message.account_id == aid, Message.fan_id == fan))).scalars()}
    assert dirs[40] == "in" and dirs[41] == "out", dirs


async def case_stale_thread_page_keeps_confirmed_unsend():
    from automations.scrape_chats import save_thread_page
    from messages_unsent import mark_unsent
    aid, fan, mid = "acc_catchup", 5395, 41
    await _seed_account(aid)
    rows = _msgs(fan, [mid])
    await save_thread_page(aid, fan, OWN_ID, rows)
    assert await mark_unsent(aid, mid, fan) == 1
    async with get_session() as s:
        unsent_at = (await s.get(Message, (aid, fan, mid))).unsent_at
    await save_thread_page(aid, fan, OWN_ID, rows)
    async with get_session() as s:
        saved = await s.get(Message, (aid, fan, mid))
        assert saved.is_unsent and unsent_at is not None and saved.unsent_at == unsent_at



class ScriptedSweepClient(FakeClient):

    def __init__(self, script: list[tuple[int, str]]):
        from curl_cffi import requests as cc
        self._cc = cc
        self.script = dict(script)
        super().__init__({c: [_of_msg(c * 10 + 1, True, "hi", "2026-06-05T10:00:00+00:00", fan_id=c)]
                          for c, _ in script})
        self.tried: list[int] = []

    def get_messages(self, chat_id, **kw) -> dict:
        cid = int(chat_id)
        if kw.get("before_id") is None and kw.get("order", "desc") == "desc":
            self.tried.append(cid)
        how = self.script[cid]
        exc = self._cc.exceptions
        if how in ("429", "503", "404"):
            from of_client import OFAPIError
            raise OFAPIError(how, response=type("R", (), {"status_code": int(how)})())
        if how == "proxy":
            raise exc.ProxyError("proxy refused")
        if how == "timeout":
            raise exc.Timeout("timed out")
        if how == "parse":
            raise json.JSONDecodeError("Expecting value", "<html>", 0)
        if how == "otp":
            from of_client import OFAPIError
            raise OFAPIError('400 {"error":{"code":101,"message":"Confirm it is you",'
                             '"payload":{"otpState":{},"strong":true}}}')
        return super().get_messages(chat_id, **kw)


async def _sweep(aid: str, script: list[tuple[int, str]]):
    from automations import scrape_chats as sc
    await _seed_account(aid)
    fake = ScriptedSweepClient(script)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    real_sleep, sc._PAGE_SLEEP_S = sc._PAGE_SLEEP_S, 0
    try:
        return await sc._automation_scrape_chats(aid, {}, run_id=0), fake
    except RuntimeError as e:
        return e, fake
    finally:
        sc._PAGE_SLEEP_S = real_sleep


async def case_scrape_sweep_stops_after_five_systemic_failures_in_a_row():
    for aid, how in (("acc_ff_429", "429"), ("acc_ff_proxy", "proxy")):
        base = 6000 if how == "429" else 6100
        script = [(base, "ok")] + [(base + i, how) for i in range(1, 20)]
        res, fake = await _sweep(aid, script)
        assert isinstance(res, RuntimeError), (how, res)
        assert fake.tried == [base] + [base + i for i in range(1, 6)], (how, fake.tried)
        async with get_session() as s:
            assert await s.get(ScrapeHistory, (aid, base)) is not None, "the good chat is kept"
            n = len((await s.execute(select(Message).where(Message.account_id == aid))).scalars().all())
            assert n == 1, (how, n)
    script = [(6200, "ok"), (6201, "503"), (6202, "timeout"), (6203, "429"), (6204, "proxy"),
              (6205, "503"), (6206, "ok")]
    res, fake = await _sweep("acc_ff_mix", script)
    assert isinstance(res, RuntimeError) and fake.tried == [6200 + i for i in range(6)], (res, fake.tried)


async def case_scrape_sweep_fail_fast_counts_only_in_a_row():
    s429 = [(6300, "ok")] + [(6300 + i, "429") for i in range(1, 5)] + [(6305, "ok")] + \
        [(6305 + i, "429") for i in range(1, 5)] + [(6310, "ok")]
    res, fake = await _sweep("acc_ff_reset", s429)
    assert isinstance(res, dict) and res["full_sweep"] is True and res["chats_scanned"] == 3, res
    assert len(fake.tried) == 11, fake.tried
    parse = [(6400, "ok")] + [(6400 + i, "parse") for i in range(1, 6)] + [(6406, "ok")]
    res, fake = await _sweep("acc_ff_parse", parse)
    assert isinstance(res, dict) and res["full_sweep"] is True and res["chats_scanned"] == 2, res
    assert len(fake.tried) == 7, fake.tried
    mixed = [(6500, "ok")] + [(6500 + i, "429") for i in range(1, 5)] + [(6505, "parse")] + \
        [(6505 + i, "429") for i in range(1, 5)] + [(6510, "ok")]
    res, fake = await _sweep("acc_ff_nonsys", mixed)
    assert isinstance(res, dict) and res["full_sweep"] is True and len(fake.tried) == 11, (res, fake.tried)
    gone = [(6600, "ok"), (6601, "429"), (6602, "429"), (6603, "404"), (6604, "404"), (6605, "404"),
            (6606, "429"), (6607, "429"), (6608, "429"), (6609, "ok")]
    res, fake = await _sweep("acc_ff_gone", gone)
    assert isinstance(res, RuntimeError) and fake.tried == [6600 + i for i in range(9)], (res, fake.tried)
    res, fake = await _sweep("acc_ff_allgone", [(6700, "ok")] + [(6700 + i, "404") for i in range(1, 11)])
    assert isinstance(res, dict) and res["full_sweep"] is True and len(fake.tried) == 11, res


async def case_scrape_sweep_fail_fast_before_first_scan_and_knob():
    import os
    res, fake = await _sweep("acc_ff_first", [(6800 + i, "parse") for i in range(20)])
    assert isinstance(res, RuntimeError) and "0 of 20" in str(res), res
    assert len(fake.tried) == 5, fake.tried
    os.environ["SCRAPE_SWEEP_FAIL_FAST"] = "3"
    try:
        res, fake = await _sweep("acc_ff_knob", [(6900, "ok")] + [(6900 + i, "429") for i in range(1, 10)])
        assert isinstance(res, RuntimeError) and len(fake.tried) == 4, (res, fake.tried)
    finally:
        del os.environ["SCRAPE_SWEEP_FAIL_FAST"]


async def case_scrape_sweep_stops_at_its_time_budget():
    import os
    from automations import scrape_chats as sc
    real_clock = sc._clock
    t = {"now": 0.0}

    def tick() -> float:
        now = t["now"]
        t["now"] += 400.0
        return now
    script = [(7000 + i, "ok") for i in range(10)]
    try:
        sc._clock = tick
        res, fake = await _sweep("acc_budget", script)
        assert isinstance(res, dict) and res["full_sweep"] is True, res
        assert res["budget_stopped"] is True and res["chats_left"] == 7, res
        assert res["chats_scanned"] == 3 and fake.tried == [7000, 7001, 7002], (res, fake.tried)
        t["now"] = 0.0
        res, fake = await _sweep("acc_budget", script)
        assert fake.tried == [7003, 7004, 7005], fake.tried
        t["now"] = 0.0
        res, fake = await _sweep("acc_budget", script)
        assert fake.tried == [7006, 7007, 7008], fake.tried
        t["now"] = 0.0
        res, fake = await _sweep("acc_budget", script)
        assert fake.tried == [7009, 7000, 7001], fake.tried
        os.environ["SCRAPE_SWEEP_BUDGET_S"] = "0"
        t["now"] = 0.0
        res, fake = await _sweep("acc_budget_off", [(7100 + i, "ok") for i in range(10)])
        assert res["chats_scanned"] == 10 and "budget_stopped" not in res, res
        del os.environ["SCRAPE_SWEEP_BUDGET_S"]
        t["now"] = 0.0
        ids = [7200 + i for i in range(6)]
        fake = ScriptedSweepClient([(c, "ok") for c in ids])
        ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
        real_sleep, sc._PAGE_SLEEP_S = sc._PAGE_SLEEP_S, 0
        try:
            res = await sc._automation_scrape_chats("acc_budget", {"fan_ids": ids}, run_id=0)
        finally:
            sc._PAGE_SLEEP_S = real_sleep
        assert res["chats_scanned"] == 6 and "budget_stopped" not in res, res
    finally:
        sc._clock = real_clock
        os.environ.pop("SCRAPE_SWEEP_BUDGET_S", None)


async def case_scrape_budget_failing_chats_do_not_stay_first():
    from automations import scrape_chats as sc
    real_clock = sc._clock
    t = {"now": 0.0}

    def tick() -> float:
        now = t["now"]
        t["now"] += 400.0
        return now
    script = [(7300 + i, "parse") for i in range(3)] + [(7303 + i, "ok") for i in range(4)]
    try:
        sc._clock = tick
        res, fake = await _sweep("acc_budget", script)
        assert isinstance(res, RuntimeError) and fake.tried == [7300, 7301, 7302], (res, fake.tried)
        t["now"] = 0.0
        res, fake = await _sweep("acc_budget", script)
        assert fake.tried == [7303, 7304, 7305], f"failing chats stayed first: {fake.tried}"
        assert all(("acc_budget", c) in sc._attempted_at for c in (7300, 7301, 7302)), "failing chat lost its entry"
        assert not any(("acc_budget", c) in sc._attempted_at for c in (7303, 7304, 7305)), \
            "a scraped chat kept its attempt entry"
    finally:
        sc._clock = real_clock


async def case_scrape_explicit_backfill_that_scraped_nothing_raises():
    from automations import scrape_chats as sc
    real_sleep, sc._PAGE_SLEEP_S = sc._PAGE_SLEEP_S, 0
    try:
        await _seed_account("acc_bf_fail")
        from of_client import OFAPIError
        for script, raises in (([(7400, "429")], OFAPIError), ([(7401, "404")], None),
                               ([(7402, "ok"), (7403, "429")], None),
                               ([(7405, "429"), (7406, "429")], RuntimeError)):
            fake = ScriptedSweepClient(script)
            ax._make_client = lambda account_id, f=fake: f  # type: ignore[attr-defined]
            try:
                res = await sc._automation_scrape_chats(
                    "acc_bf_fail", {"fan_ids": [c for c, _ in script]}, run_id=0)
            except (RuntimeError, OFAPIError) as e:
                res = e
            if raises is None:
                assert isinstance(res, dict) and "full_sweep" not in res, (script, res)
            else:
                assert type(res) is raises, (script, res)
        import account_health
        ax._make_client = lambda account_id: ScriptedSweepClient([(7404, "otp")])  # type: ignore[attr-defined]
        try:
            res = await sc._automation_scrape_chats("acc_bf_fail", {"fan_ids": [7404]}, run_id=0)
        except (RuntimeError, OFAPIError) as e:
            res = e
        assert isinstance(res, OFAPIError), f"one-fan backfill lost OF's typed error: {res!r}"
        assert account_health.is_session_dead_error(res) == "otp_required", res
    finally:
        sc._PAGE_SLEEP_S = real_sleep



def _mass_msg(mid: int, *, fan_id: int, text: str | None = None, queued: bool = True) -> dict:
    m = _of_msg(mid, False, text or f"mass {mid}",
                f"2026-06-06T{mid // 60 % 24:02d}:{mid % 60:02d}:00+00:00", fan_id=fan_id)
    if queued:
        m["isFromQueue"] = True
    return m


class DeepSweepClient(PagedFakeClient):

    def list_chats(self, **kw) -> dict:
        return {"list": [{"withUser": {"id": self.chat_id, "username": f"deep_{self.chat_id}",
                                       "name": "Deep", "subscribedOn": True},
                          "isMutedNotifications": True}], "hasMore": False}


async def _scrape(aid: str, fake, payload: dict) -> dict:
    from automations import scrape_chats as sc
    await _seed_account(aid)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    real_sleep, sc._PAGE_SLEEP_S = sc._PAGE_SLEEP_S, 0
    try:
        return await sc._automation_scrape_chats(aid, payload, run_id=0)
    finally:
        sc._PAGE_SLEEP_S = real_sleep


async def _thread(aid: str, fan: int) -> tuple:
    async with get_session() as s:
        ids = sorted(m.message_id for m in (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan))).scalars().all())
        return ids, await s.get(ScrapeHistory, (aid, fan)), await s.get(Chat, (aid, fan)), \
            await s.get(Fan, (aid, fan))


async def case_scrape_silent_mass_only_chat_costs_one_page_and_defers():
    aid, fan = "acc_defer", 5300
    msgs = [_mass_msg(i, fan_id=fan) for i in range(1, 151)]
    fake = DeepSweepClient(fan, msgs)
    await _seed_account(aid)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=5_000_000_000_000_150, direction="out",
                      sender_name="", body="mass 150", media_ids="[]", media_count=0, price_cents=0,
                      is_tip=False, is_unsent=False, is_promise=False, automation_kind="mass_message",
                      created_at=datetime(2026, 6, 6, 2, 30)))

    res = await _scrape(aid, fake, {})
    assert res["full_sweep"] is True and res["chats_scanned"] == 1, res
    assert fake.calls == [("desc", None, None)], fake.calls
    ids, hist, chat, f = await _thread(aid, fan)
    assert ids == list(range(138, 151)), ids
    assert hist.last_message_id is None and hist.history_deferred_at is not None, \
        (hist.last_message_id, hist.history_deferred_at)
    assert hist.last_scrape_at is not None
    assert chat.last_message_id == 150 and "mass 150" in chat.last_message_preview, chat.last_message_id
    assert f.of_username == "deep_5300" and f.is_muted is True, (f.of_username, f.is_muted)
    async with get_session() as s:
        real = await s.get(Message, (aid, fan, 150))
        assert real.automation_kind == "mass_message", real.automation_kind

    res = await _scrape(aid, fake, {})
    assert res["full_sweep"] is True and fake.calls == [("desc", None, None)] * 2, fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.last_message_id is None and hist.history_deferred_at is not None


async def case_scrape_not_silent_chats_are_backfilled_as_today():
    def reply_on_page1(fan):
        msgs = [_mass_msg(i, fan_id=fan) for i in range(1, 151)]
        msgs[145] = _of_msg(146, True, "hey", "2026-06-06T02:26:00+00:00", fan_id=fan)
        return msgs

    variants = (
        ("reply", reply_on_page1, False, 150),
        ("dbin", lambda fan: [_mass_msg(i, fan_id=fan) for i in range(1, 151)], "in", 150),
        ("manual", lambda fan: [_mass_msg(i, fan_id=fan, queued=False) for i in range(1, 151)], False, 150),
        ("short", lambda fan: [_mass_msg(i, fan_id=fan) for i in range(1, 11)], False, 10),
        ("paid", lambda fan: [_mass_msg(i, fan_id=fan) for i in range(1, 151)], "tx", 150),
    )
    for k, (name, build, db_seed, newest) in enumerate(variants):
        fan, aid = 5400 + k, "acc_defer"
        today = DeepSweepClient(fan + 50, build(fan + 50))
        await _seed_account(aid)
        await _read_chat(aid, fan + 50)
        await _scrape(aid, today, {"fan_ids": [fan + 50]})
        fake = DeepSweepClient(fan, build(fan))
        if db_seed == "in":
            async with get_session() as s:
                s.add(Message(account_id=aid, fan_id=fan, message_id=9999, direction="in", sender_name="",
                              body="old dm", media_ids="[]", media_count=0, price_cents=0, is_tip=False,
                              is_unsent=False, is_promise=False, created_at=datetime(2026, 5, 1)))
        if db_seed == "tx":
            async with get_session() as s:
                s.add(Transaction(account_id=aid, fan_id=fan, kind="ppv_message", amount_cents=1500,
                                  occurred_at=datetime(2026, 5, 1), provider_transaction_id=f"tx{fan}",
                                  source="ingest"))
        res = await _scrape(aid, fake, {})
        assert res["full_sweep"] is True, (name, res)
        assert fake.calls == today.calls, (name, fake.calls, today.calls)
        if name != "short":
            assert {o for o, _b, _off in fake.calls} == {"desc", "asc"}, (name, fake.calls)
        _, hist, _, _ = await _thread(aid, fan)
        assert hist.last_message_id == newest and hist.history_deferred_at is None, \
            (name, hist.last_message_id, hist.history_deferred_at)


async def case_scrape_cursor_write_clears_the_deferred_mark():
    for aid, fan, how in (("acc_defer", 5500, "explicit"), ("acc_defer", 5501, "reply")):
        msgs = [_mass_msg(i, fan_id=fan) for i in range(1, 151)]
        fake = DeepSweepClient(fan, msgs)
        await _scrape(aid, fake, {})
        _, hist, _, _ = await _thread(aid, fan)
        assert hist.history_deferred_at is not None, how
        fake.calls.clear()
        if how == "reply":
            fake._asc.append(_of_msg(151, True, "finally", "2026-06-06T03:00:00+00:00", fan_id=fan))
        await _scrape(aid, fake, {"fan_ids": [fan], "source": "deferred_history", "after_click_at": datetime.utcnow().isoformat()} if how == "explicit" else {})
        assert {o for o, _b, _off in fake.calls} == {"desc", "asc"}, (how, fake.calls)
        assert ("asc", None, 0) in fake.calls, (how, fake.calls)
        ids, hist, _, _ = await _thread(aid, fan)
        want = 151 if how == "reply" else 150
        assert hist.last_message_id == want and hist.history_deferred_at is None, \
            (how, hist.last_message_id, hist.history_deferred_at)
        assert ids[0] == 1 and ids[-1] == want, (how, ids[:3], ids[-3:])


async def case_scrape_empty_explicit_backfill_clears_the_deferred_mark():
    from datetime import datetime as _dt
    aid = "acc_defer_empty"
    await _seed_account(aid)
    for fan, payload, cleared in ((5700, None, True), (5701, {}, False)):
        async with get_session() as s:
            s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=None,
                                history_deferred_at=_dt.utcnow()))
            await s.commit()
        await _scrape(aid, DeepSweepClient(fan, []), {"fan_ids": [fan]} if payload is None else payload)
        _, hist, _, _ = await _thread(aid, fan)
        assert (hist.history_deferred_at is None) is cleared, (fan, hist.history_deferred_at)


async def case_scrape_non_positive_limits_still_read_before_clearing_the_mark():
    from datetime import datetime as _dt
    aid = "acc_defer_empty"
    await _seed_account(aid)
    for fan, bad in ((5710, {"recent_cap": -1}), (5711, {"max_pages": -1}), (5712, {"page_size": -5})):
        async with get_session() as s:
            s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=None,
                                history_deferred_at=_dt.utcnow()))
            await s.commit()
        fake = DeepSweepClient(fan, [_of_msg(fan * 10 + 1, True, "hi", "2026-06-05T10:00:00+00:00", fan_id=fan)])
        await _scrape(aid, fake, {"fan_ids": [fan], **bad})
        _, hist, _, _ = await _thread(aid, fan)
        assert fake.calls, f"{bad}: no OF read"
        assert hist.last_message_id == fan * 10 + 1, (bad, hist.last_message_id)


async def case_scrape_eager_history_knob_restores_todays_calls():
    import os
    fan = 5600
    today = DeepSweepClient(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)])
    await _seed_account("acc_defer")
    await _read_chat("acc_defer", fan)
    await _scrape("acc_defer", today, {"fan_ids": [fan]})
    fan += 1
    fake = DeepSweepClient(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)])
    os.environ["SCRAPE_EAGER_HISTORY"] = "1"
    try:
        await _scrape("acc_defer", fake, {})
    finally:
        del os.environ["SCRAPE_EAGER_HISTORY"]
    assert fake.calls == today.calls and len(fake.calls) > 1, (fake.calls, today.calls)
    _, hist, _, _ = await _thread("acc_defer", fan)
    assert hist.last_message_id == 150 and hist.history_deferred_at is None


async def case_scrape_deferred_backfill_counts_under_its_own_caller_kind():
    import of_call_counter

    class Labelled(DeepSweepClient):
        def get_messages(self, chat_id, **kw):
            self.kinds.append(of_call_counter.caller_kind())
            return super().get_messages(chat_id, **kw)

    got = {}
    for fan, source, deferred in ((5700, "deferred_history", True), (5701, "blast_reply", True),
                                  (5702, "blast_reply", False)):
        fake = Labelled(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)])
        fake.kinds = []
        await _seed_account("acc_defer")
        await _read_chat("acc_defer", fan)
        if deferred:
            async with get_session() as s:
                s.add(ScrapeHistory(account_id="acc_defer", fan_id=fan, last_message_id=None,
                                    last_scrape_at=datetime.utcnow(),
                                    history_deferred_at=datetime.utcnow()))
        ax._make_client = lambda account_id, f=fake: f  # type: ignore[attr-defined]
        payload = {"fan_ids": [fan], "source": source}
        if source == "deferred_history":
            payload["after_click_at"] = datetime.utcnow().isoformat()
        res = await ax.run_once("acc_defer", "scrape_chats", payload=payload)
        assert res["status"] == "ok", res
        got[fan] = set(fake.kinds)
        assert (("asc", None, 0) in fake.calls) is (fan != 5701), (fan, fake.calls)
    assert got == {5700: {"auto:scrape_chats:deferred_history"},
                   5701: {"auto:scrape_chats:deferred_history"},
                   5702: {"auto:scrape_chats"}}, got



class PeekRecordingClient(DeepSweepClient):

    def __init__(self, *a, unread: int = 0, on_page1=None, on_list=None, **kw):
        super().__init__(*a, **kw)
        self.kw_calls: list[dict] = []
        self.unread = unread
        self.on_page1 = on_page1
        self.on_list = on_list

    def list_chats(self, **kw) -> dict:
        page = super().list_chats(**kw)
        for row in page["list"]:
            row["unreadMessagesCount"] = self.unread
        if self.on_list:
            self.on_list()
        return page

    def get_messages(self, chat_id, **kw):
        self.kw_calls.append(dict(kw))
        if len(self.kw_calls) == 1 and self.on_page1:
            self.on_page1()
        return super().get_messages(chat_id, **kw)


def _fan_msgs(fan: int, n: int = 150) -> list[dict]:
    return [_of_msg(i, i % 2 == 0, f"m{i}", f"2026-06-07T{i // 60 % 24:02d}:{i % 60:02d}:00+00:00",
                    fan_id=fan) for i in range(1, n + 1)]


def _page_one_only(calls) -> bool:
    return calls == [("desc", None, None)]


def _recent_end_only(calls) -> bool:
    return (len(calls) > 1 and calls[0] == ("desc", None, None) and calls[1] == ("desc", 138, None)
            and all(o == "desc" and b is not None for o, b, _off in calls[1:]))


async def case_scrape_page_one_peeks():
    aid = "acc_peek"
    await _seed_account(aid)
    for fan, payload in ((5800, {}), (5801, {"fan_ids": [5801]})):
        await _read_chat(aid, fan)
        fake = PeekRecordingClient(fan, _fan_msgs(fan))
        await _scrape(aid, fake, payload)
        first, second = fake.kw_calls[0], fake.kw_calls[1]
        assert first.get("peek") is True and first.get("before_id") is None \
            and first.get("order") == "desc", (payload, first)
        assert second.get("before_id") == 138 and second.get("order") == "desc", (payload, second)
        assert all(("peek" in c) is (c.get("order") == "desc") for c in fake.kw_calls), (payload, fake.kw_calls)
        assert any(c.get("order") == "asc" for c in fake.kw_calls), (payload, fake.kw_calls)


async def case_scrape_unread_long_first_scrape_defers_backfill():
    aid = "acc_peek"
    await _seed_account(aid)
    for fan, row, want_marker in ((5810, True, 0), (5812, False, 1)):
        if row:
            await _read_chat(aid, fan)
        fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=2)
        res = await _scrape(aid, fake, {})
        assert res["chats_scanned"] == 1, res
        assert _recent_end_only(fake.calls), fake.calls
        ids, hist, chat, _ = await _thread(aid, fan)
        assert ids == list(range(51, 151)), ids
        assert hist.last_message_id is None and hist.history_deferred_at is not None
        assert chat.unread_count == want_marker, (fan, chat.unread_count)


async def case_scrape_read_long_first_scrape_runs_both_ends():
    aid, fan = "acc_peek", 5811
    fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=0)
    res = await _scrape(aid, fake, {})
    assert res["chats_scanned"] == 1, res
    assert ("asc", None, 0) in fake.calls, fake.calls
    ids, hist, _, _ = await _thread(aid, fan)
    assert ids[0] == 1 and ids[-1] == 150 and hist.last_message_id == 150, (ids[:3], hist.last_message_id)
    assert hist.history_deferred_at is None


async def case_scrape_explicit_unread_by_local_marker_defers():
    aid = "acc_peek"
    await _seed_account(aid)
    for fan, unread, want_asc in ((5820, 1, False), (5821, 0, True)):
        await _read_chat(aid, fan, unread)
        fake = PeekRecordingClient(fan, _fan_msgs(fan))
        await _scrape(aid, fake, {"fan_ids": [fan]})
        assert (("asc", None, 0) in fake.calls) is want_asc, (unread, fake.calls)
        assert want_asc or _recent_end_only(fake.calls), fake.calls
        _, hist, _, _ = await _thread(aid, fan)
        assert (hist.history_deferred_at is None) is want_asc, (unread, hist.history_deferred_at)


async def case_scrape_explicit_missing_chat_row_defers():
    aid, fan = "acc_peek", 5830
    fake = PeekRecordingClient(fan, _fan_msgs(fan))
    await _scrape(aid, fake, {"fan_ids": [fan]})
    assert _recent_end_only(fake.calls), fake.calls
    _, hist, chat, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None and hist.last_message_id is None
    assert chat.unread_count == 0, chat.unread_count
    fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=0)
    await _scrape(aid, fake, {})
    assert ("asc", None, 0) in fake.calls, fake.calls


async def case_scrape_deferred_row_backfills_only_on_the_click():
    import webhook_dispatch as wd
    aid, fan = "acc_peek", 5840
    await _seed_account(aid)
    await _read_chat(aid, fan, 1)
    fake = PeekRecordingClient(fan, _fan_msgs(fan))
    await _scrape(aid, fake, {"fan_ids": [fan]})
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None
    await _read_chat(aid, fan, 0)
    for payload in ({"fan_ids": [fan]}, {"fan_ids": [fan], "source": wd.GEN_INFO_PICK_SOURCE},
                    {"fan_ids": [fan], "source": wd.DEFERRED_HISTORY_SOURCE},
                    {"fan_ids": [fan], "source": "blast_reply"}):
        fake.calls.clear()
        await _scrape(aid, fake, payload)
        assert _page_one_only(fake.calls), (payload, fake.calls)
        _, hist, _, _ = await _thread(aid, fan)
        assert hist.history_deferred_at is not None and hist.last_message_id is None, payload
    fake.calls.clear()
    await _scrape(aid, fake, {"fan_ids": [fan], "source": wd.DEFERRED_HISTORY_SOURCE,
                                   "after_click_at": datetime.utcnow().isoformat()})
    assert ("asc", None, 0) in fake.calls, fake.calls
    ids, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is None and hist.last_message_id == 150
    assert ids[0] == 1, ids[:3]


async def case_scrape_click_backfill_before_local_zeroing_pulls_both_ends():
    import webhook_dispatch as wd
    aid, fan = "acc_peek", 5841
    await _seed_account(aid)
    await _read_chat(aid, fan, 1)
    fake = PeekRecordingClient(fan, _fan_msgs(fan))
    await _scrape(aid, fake, {"fan_ids": [fan]})
    fake.calls.clear()
    await _scrape(aid, fake, {"fan_ids": [fan], "source": wd.DEFERRED_HISTORY_SOURCE,
                                   "after_click_at": datetime.utcnow().isoformat()})
    assert ("asc", None, 0) in fake.calls, fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is None


async def case_scrape_resweep_of_a_deferred_unread_chat_reads_page_one():
    aid, fan = "acc_peek", 5901
    await _seed_account(aid)
    await _read_chat(aid, fan, 1)
    fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=1)
    await _scrape(aid, fake, {})
    assert _recent_end_only(fake.calls), fake.calls
    fake.calls.clear()
    await _scrape(aid, fake, {})
    assert _page_one_only(fake.calls), fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None and hist.last_message_id is None


async def case_scrape_sweep_backfills_a_deferred_row_read_on_both_sides():
    aid, fan = "acc_peek", 5900
    await _seed_account(aid)
    await _read_chat(aid, fan, 0)
    await _scrape(aid, PeekRecordingClient(fan, _fan_msgs(fan), unread=2), {})
    _, hist, chat, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None and chat.unread_count == 0, chat.unread_count
    fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=0)
    await _scrape(aid, fake, {"fan_ids": [fan]})
    assert _page_one_only(fake.calls), fake.calls
    fake.calls.clear()
    await _scrape(aid, fake, {})
    assert ("asc", None, 0) in fake.calls, fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is None and hist.last_message_id == 150


async def case_scrape_eager_history_does_not_backfill_unread():
    import os
    aid, fan = "acc_peek", 5850
    fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=3)
    os.environ["SCRAPE_EAGER_HISTORY"] = "1"
    try:
        await _scrape(aid, fake, {})
    finally:
        del os.environ["SCRAPE_EAGER_HISTORY"]
    assert _recent_end_only(fake.calls), fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None


async def case_scrape_unread_silent_mass_chat_still_costs_one_page():
    aid, fan = "acc_peek", 5855
    await _seed_account(aid)
    fake = PeekRecordingClient(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)], unread=2)
    await _scrape(aid, fake, {})
    assert fake.calls == [("desc", None, None)], fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None and hist.last_message_id is None


async def case_scrape_unread_flip_before_asc_defers():
    aid, fan = "acc_peek", 5860
    await _seed_account(aid)
    await _read_chat(aid, fan, 0)

    fake = PeekRecordingClient(fan, _fan_msgs(fan), on_page1=_bump_marker(aid, fan, 1))
    await _scrape(aid, fake, {"fan_ids": [fan]})
    assert all(o == "desc" for o, _b, _off in fake.calls), fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None and hist.last_message_id is None


async def case_scrape_dm_during_ascending_pace_defers():
    from unittest.mock import patch
    from automations import scrape_chats

    aid, fan = "acc_peek", 5861
    await _seed_account(aid)
    await _read_chat(aid, fan, 0)
    fake = PeekRecordingClient(fan, _fan_msgs(fan))
    pauses = 0
    sleep = asyncio.sleep

    async def paced(delay, *args):
        nonlocal pauses
        if delay == 17:
            pauses += 1
            if pauses == 2:
                await _read_chat(aid, fan, 1)
            delay = 0
        return await sleep(delay, *args)

    with (patch.object(scrape_chats, "_PAGE_SLEEP_S", 17),
          patch.object(asyncio, "sleep", paced), patch.object(ax, "_make_client", return_value=fake)):
        await scrape_chats._automation_scrape_chats(aid, {"fan_ids": [fan], "max_pages": 1}, run_id=0)
    assert pauses >= 2
    assert _page_one_only(fake.calls), fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None


async def case_scrape_dm_between_click_and_job_defers():
    import webhook_dispatch as wd

    aid, fan = "acc_peek", 5862
    await _seed_account(aid)
    await _read_chat(aid, fan, 1)
    messages = _fan_msgs(fan)
    click = datetime(2026, 6, 7, 2, 30)
    messages[-1]["createdAt"] = "2026-06-07T02:30:01+00:00"
    fake = PeekRecordingClient(fan, messages)
    await _scrape(aid, fake, {"fan_ids": [fan], "source": wd.DEFERRED_HISTORY_SOURCE,
                              "after_click_at": click.isoformat()})
    assert _recent_end_only(fake.calls), fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None


def _bump_marker(aid: str, fan: int, unread: int):
    def go():
        async def _go():
            await _read_chat(aid, fan, unread)
        asyncio.run(_go())
    return go


async def case_scrape_dm_after_the_sweep_list_defers():
    aid, fan = "acc_peek", 5870
    await _seed_account(aid)
    await _read_chat(aid, fan, 0)
    fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=0, on_list=_bump_marker(aid, fan, 1))
    await _scrape(aid, fake, {})
    assert all(o == "desc" for o, _b, _off in fake.calls), fake.calls
    _, hist, chat, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None and hist.last_message_id is None
    assert chat.unread_count == 1, chat.unread_count


async def case_scrape_click_mid_scrape_stays_read():
    aid, fan = "acc_peek", 5880
    await _seed_account(aid)
    await _read_chat(aid, fan, 1)
    fake = PeekRecordingClient(fan, _fan_msgs(fan), on_page1=_bump_marker(aid, fan, 0))
    await _scrape(aid, fake, {"fan_ids": [fan]})
    assert all(o == "desc" for o, _b, _off in fake.calls), fake.calls
    _, hist, chat, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is not None
    assert chat.unread_count == 0, chat.unread_count


async def case_scrape_fansly_keeps_both_ends():
    aid, fan = "acc_peek", 5890
    real = ax.account_registry.get_platform
    ax.account_registry.get_platform = lambda account_id: "fansly" if account_id == aid else real(account_id)
    try:
        fake = PeekRecordingClient(fan, _fan_msgs(fan), unread=2)
        await _scrape(aid, fake, {})
    finally:
        ax.account_registry.get_platform = real
    assert ("asc", None, 0) in fake.calls, fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.history_deferred_at is None and hist.last_message_id == 150


async def case_scrape_short_unread_chat_is_read_whole_and_not_deferred():
    aid, fan = "acc_peek", 5895
    fake = PeekRecordingClient(fan, _fan_msgs(fan, 10), unread=2)
    await _scrape(aid, fake, {})
    assert fake.calls == [("desc", None, None)], fake.calls
    ids, hist, _, _ = await _thread(aid, fan)
    assert ids == list(range(1, 11)), ids
    assert hist.last_message_id == 10 and hist.history_deferred_at is None


async def case_history_deferred_at_self_heals_on_init_db():
    import importlib
    import os
    import sqlite3
    import tempfile
    from pathlib import Path

    import sqlalchemy as sa
    import sqlalchemy.dialects.sqlite  # noqa: F401
    from sqlalchemy.schema import CreateTable

    db_engine = importlib.import_module("db.engine")
    tmp = Path(tempfile.gettempdir())
    old, fresh = tmp / f"sh_old_{os.getpid()}.db", tmp / f"sh_fresh_{os.getpid()}.db"
    for p in (old, fresh):
        p.unlink(missing_ok=True)
    ddl = str(CreateTable(ScrapeHistory.__table__).compile(dialect=sa.dialects.sqlite.dialect()))
    con = sqlite3.connect(old)
    con.executescript(f"""
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('0108_tracking_link_bot_check');
        {ddl};
        ALTER TABLE scrape_history DROP COLUMN history_deferred_at;
        INSERT INTO scrape_history (account_id, fan_id, last_message_id, last_scrape_at)
            VALUES ('legacy1', 1, 42, '2026-06-01 00:00:00');
    """)
    con.commit()
    con.close()
    prev = db_engine.DATABASE_URL
    try:
        for p in (old, fresh):
            db_engine.DATABASE_URL = f"sqlite+aiosqlite:///{p}"
            await db_engine.init_db()
    finally:
        db_engine.DATABASE_URL = prev
    for p in (old, fresh):
        con = sqlite3.connect(p)
        cols = {r[1] for r in con.execute("PRAGMA table_info(scrape_history)")}
        rows = con.execute("SELECT account_id, last_message_id, history_deferred_at FROM scrape_history").fetchall()
        con.close()
        p.unlink(missing_ok=True)
        assert "history_deferred_at" in cols, (p.name, sorted(cols))
        assert rows == ([("legacy1", 42, None)] if p == old else []), (p.name, rows)



async def case_fan_lease_acquire_block_steal():
    aid = "acc_lease"

    assert await acquire_fan_lease(aid, 7777, "welcome_chatter_for_info", ttl_s=60) is True, "fresh acquire"
    assert await acquire_fan_lease(aid, 7777, "send_followup", ttl_s=60) is False, \
        "live lease blocks a second automation"
    await release_fan_lease(aid, 7777)
    assert await acquire_fan_lease(aid, 7777, "send_followup", ttl_s=60) is True, \
        "acquire after release"

    assert await acquire_fan_lease(aid, 8888, "welcome_chatter_for_info", ttl_s=-5) is True, "insert expired"
    assert await acquire_fan_lease(aid, 8888, "reply_mass_funnel", ttl_s=60) is True, \
        "steal an expired lease"
    assert await acquire_fan_lease(aid, 8888, "send_welcome", ttl_s=60) is False, \
        "the freshly-stolen lease is now live and blocks"



async def case_fan_cooldown_set_check_expire():
    aid = "acc_cooldown"
    await _seed_account(aid)

    assert await ax.fan_on_cooldown(aid, 5101) is False, "no row → not on cooldown"
    until = await ax.start_fan_cooldown(aid, 5101)
    assert await ax.fan_on_cooldown(aid, 5101) is True, "fresh cooldown is active"
    async with get_session() as s:
        f = await s.get(Fan, (aid, 5101))
        assert f is not None and f.automation_paused_until == until, "upserted the pause"

    await ax.start_fan_cooldown(aid, 5101, cooldown_s=-5)
    assert await ax.fan_on_cooldown(aid, 5101) is False, "expired cooldown clears"



async def case_kind_priority_ordering():
    order = [
        "send_welcome", "welcome_chatter_for_info",
        "send_followup", "reply_mass_funnel", "send_mass_message",
    ]
    ranks = [ax.kind_priority(k) for k in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks), ranks
    assert ax.kind_priority("totally_unknown") > ranks[-1], ax.kind_priority("totally_unknown")


async def case_supervisor_dispatches_high_priority_first():
    aid = "acc_prio"
    await _seed_account(aid)
    await enqueue_job(aid, "send_followup", payload={})
    await enqueue_job(aid, "welcome_chatter_for_info", payload={})
    await enqueue_job(aid, "send_welcome", payload={})

    dispatched: list[str] = []
    orig = ax.run_once

    async def _record(account_id, kind, **kw):
        dispatched.append(kind)
        return {"status": "ok"}

    ax.run_once = _record  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]

    assert dispatched[:3] == ["send_welcome", "welcome_chatter_for_info", "send_followup"], dispatched


async def case_supervisor_dispatches_least_recently_served_account_first():
    a_low, z_high = "acc_lrs_a", "acc_lrs_z"
    for aid in (a_low, z_high):
        await _seed_account(aid)
        await enqueue_job(aid, "send_followup", payload={})
    ax._last_served[a_low] = asyncio.get_running_loop().time()
    ax._last_served.pop(z_high, None)

    dispatched: list[str] = []
    orig = ax.run_once

    async def _record(account_id, kind, **kw):
        if account_id in (a_low, z_high):
            dispatched.append(account_id)
        return {"status": "ok"}

    ax.run_once = _record  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]

    assert dispatched == [z_high, a_low], dispatched
    assert ax._last_served[z_high] <= ax._last_served[a_low], (
        "winning a slot must stamp the account as served")


async def case_due_pairs_carry_their_oldest_due_run_at():
    old, new = "acc_due_old", "acc_due_new"
    now = datetime.utcnow()
    for aid in (old, new):
        await _seed_account(aid)
    await enqueue_job(old, "scrape_chats", payload={}, run_at=now - timedelta(hours=3))
    await enqueue_job(old, "scrape_chats", payload={}, run_at=now - timedelta(hours=1))
    await enqueue_job(new, "scrape_chats", payload={}, run_at=now - timedelta(minutes=5))
    due = {p.account_id: p.due_at for p in await ax._due_job_pairs() if p.account_id in (old, new)}
    want = (now - timedelta(hours=3) - datetime(1970, 1, 1)).total_seconds()
    assert abs(due[old] - want) < 1 and due[old] < due[new], due
    async with get_session() as s:
        for j in (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id.in_((old, new))))).scalars():
            j.status = "done"


async def _employees() -> tuple[int, int]:
    from db.models import Employee
    from employees import get_automation_employee_id
    async with get_session() as s:
        op = Employee(display_name="op_tier")
        s.add(op)
        await s.flush()
        op_id = op.id
    try:
        auto_id = await get_automation_employee_id()
    except LookupError:
        async with get_session() as s:
            auto = Employee(display_name="Automation", is_active=False)
            s.add(auto)
            await s.flush()
            auto_id = auto.id
    return op_id, auto_id


async def case_an_operators_job_dispatches_first_in_the_operator_tier():
    op_id, auto_id = await _employees()
    a_op, a_auto, a_sys = "acc_tier_op", "acc_tier_auto", "acc_tier_sys"
    for a in (a_op, a_auto, a_sys):
        await _seed_account(a)
    await enqueue_job(a_auto, "send_welcome", payload={})
    await enqueue_job(a_sys, "unsend_messages", payload={}, created_by_employee_id=auto_id)
    await enqueue_job(a_op, "unsend_messages", payload={}, created_by_employee_id=op_id)

    pairs = {(a, k): op for a, k, op, *_ in await ax._due_job_pairs()}
    assert pairs[(a_op, "unsend_messages")] is True, pairs
    assert pairs[(a_auto, "send_welcome")] is False, pairs
    assert pairs[(a_sys, "unsend_messages")] is False, ("the Automation employee is not an operator", pairs)

    seen: list[tuple[str, bool]] = []
    orig = ax.run_once

    async def _record(account_id, kind, **kw):
        if account_id.startswith("acc_tier_"):
            seen.append((account_id, ax.run_slot.current().operator))
        return {"status": "ok"}

    ax.run_once = _record  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]
    assert seen[0] == (a_op, True), seen
    assert dict(seen) == {a_op: True, a_auto: False, a_sys: False}, seen
    async with get_session() as s:
        await s.execute(ScheduledJob.__table__.update()
                        .where(ScheduledJob.account_id.in_([a_op, a_auto, a_sys]))
                        .values(status="done"))


async def case_run_now_on_an_automation_kind_is_rate_limited_as_automation():
    import dm_rate
    import os
    op_id, _auto_id = await _employees()
    a_ar, a_uns = "acc_tier_runnow", "acc_tier_runnow_uns"
    for a in (a_ar, a_uns):
        await _seed_account(a)
    await enqueue_job(a_ar, "autoreply", payload={}, created_by_employee_id=op_id)
    await enqueue_job(a_uns, "unsend_messages", payload={}, created_by_employee_id=op_id)
    pairs = {(a, k): op for a, k, op, *_ in await ax._due_job_pairs()}
    assert pairs[(a_ar, "autoreply")] is False, ("Run now made autoreply an operator run", pairs)
    assert pairs[(a_uns, "unsend_messages")] is True, pairs

    saved_env, saved_w, saved_s = os.environ.get(dm_rate.KNOB), dm_rate.WINDOW_S, dm_rate.SLACK_S
    os.environ[dm_rate.KNOB] = "1"
    dm_rate.WINDOW_S, dm_rate.SLACK_S = 0.2, 0.0
    dm_rate._reset()
    waited: dict[str, list[float]] = {}
    orig = ax.run_once

    async def _run(account_id, kind, **kw):        # two DMs of the run, each a turn then the send
        if account_id in (a_ar, a_uns):
            for _ in range(2):
                waited.setdefault(account_id, []).append(await dm_rate.turn(account_id))
                dm_rate.record(account_id)
        return {"status": "ok"}
    ax.run_once = _run  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]
        dm_rate.WINDOW_S, dm_rate.SLACK_S = saved_w, saved_s
        dm_rate._reset()
        if saved_env is None:
            os.environ.pop(dm_rate.KNOB, None)
        else:
            os.environ[dm_rate.KNOB] = saved_env
        async with get_session() as s:
            await s.execute(ScheduledJob.__table__.update()
                            .where(ScheduledJob.account_id.in_([a_ar, a_uns])).values(status="done"))
    assert waited[a_ar][0] == 0.0 and waited[a_ar][1] > 0, ("Run now's DMs bypassed the limiter", waited)
    assert waited[a_uns] == [0.0, 0.0], ("an operator kind's DMs waited", waited)


async def case_the_claim_takes_the_operators_job_first():
    op_id, auto_id = await _employees()
    aid = "acc_tier_claim"
    await _seed_account(aid)
    old = datetime.utcnow() - timedelta(minutes=5)
    j_auto = await enqueue_job(aid, "unsend_messages", payload={}, run_at=old,
                               created_by_employee_id=auto_id)
    j_bare = await enqueue_job(aid, "unsend_messages", payload={}, run_at=old)
    j_op = await enqueue_job(aid, "unsend_messages", payload={}, created_by_employee_id=op_id)
    order = [(await ax._claim_due_job(aid, "unsend_messages")).id for _ in range(3)]
    assert order[0] == j_op, (order, j_op)
    assert set(order[1:]) == {j_auto, j_bare}, order


async def case_the_run_slots_size_from_the_active_creators():
    import os
    import account_health
    import lane_config
    import run_slot
    knob = "AUTOMATION_MAX_CONCURRENT_RUNS"
    assert not lane_config.overridden(knob)
    pool = run_slot.SlotPool(4)
    await ax._size_run_slots(pool)
    base = await ax._active_models()
    assert pool.n == run_slot.auto_runs(base), (pool.n, base)
    extra = [f"acc_size_{i}" for i in range(max(0, 51 - base))]
    for a in extra:
        await _seed_account(a)
    await ax._size_run_slots(pool)
    assert pool.n == run_slot.auto_runs(base + len(extra)) == 7, (pool.n, base, len(extra))
    row = next(r for r in lane_config.describe() if r["name"] == knob)
    assert row["live"] == row["value"] == row["default"] == 7 and not row["pending"], row
    for a in extra[:20]:
        await account_health.deactivate(a)
    await ax._size_run_slots(pool)
    assert pool.n == run_slot.auto_runs(base + len(extra) - 20), (pool.n, base)
    os.environ[knob] = "9"
    try:
        for a in extra[20:]:
            await account_health.deactivate(a)
        n_before = pool.n
        await ax._size_run_slots(pool)
        assert pool.n == n_before, ("an env-pinned pool was resized", pool.n)
    finally:
        del os.environ[knob]
    await ax._size_run_slots(pool)
    assert pool.n == run_slot.auto_runs(base), (pool.n, base)


async def _settle_jobs(*aids: str) -> None:
    async with get_session() as s:
        await s.execute(ScheduledJob.__table__.update()
                        .where(ScheduledJob.account_id.in_(aids)).values(status="done"))


async def case_the_bulk_slots_size_from_the_active_creators():
    import os
    import account_health
    import lane_config
    import run_slot
    knob = "AUTOMATION_MAX_CONCURRENT_BULK"
    assert not lane_config.overridden(knob)
    base = await ax._active_models()
    extra = [f"acc_bulk_size_{i}" for i in range(max(0, 41 - base))]
    for a in extra:
        await _seed_account(a)
    models = base + len(extra)
    aid = "acc_bulk_size_job"
    await _seed_account(aid)
    models += 1
    saved_sem, orig = ax._bulk_sem, ax.run_once

    async def _ok(account_id, kind, **kw):
        return {"status": "ok"}
    ax._bulk_sem, ax.run_once = None, _ok  # type: ignore[attr-defined]
    try:
        await enqueue_job(aid, "scrape_chats", payload={})
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
        pool = ax._bulk_sem
        assert pool.n == run_slot.auto_bulk(models) >= 5 and pool.reserve == 1, (pool.n, pool.reserve, models)
        row = next(r for r in lane_config.describe() if r["name"] == knob)
        assert row["live"] == row["value"] == row["default"] == pool.n and not row["pending"], row
        os.environ[knob] = "3"
        try:
            for a in extra:
                await account_health.deactivate(a)
            n_before = pool.n
            await ax._drain_due_jobs_once()
            await ax._join_inflight_runs()
            assert pool.n == n_before, ("an env-pinned bulk pool was resized", pool.n)
        finally:
            del os.environ[knob]
        await ax._size_bulk_slots(pool)
        assert pool.n == run_slot.auto_bulk(models - len(extra)), (pool.n, models, len(extra))
    finally:
        ax._bulk_sem, ax.run_once = saved_sem, orig  # type: ignore[attr-defined]
        await _settle_jobs(aid)


async def case_an_operators_priority_mass_takes_the_bulk_reserve_past_two_sweeps():
    import os
    knob = "AUTOMATION_MAX_CONCURRENT_BULK"
    op_id, _auto_id = await _employees()
    a, b, c = "acc_bulk_res_a", "acc_bulk_res_b", "acc_bulk_res_op"
    for x in (a, b, c):
        await _seed_account(x)
    go = asyncio.Event()
    held: list[str] = []
    op_slot: dict = {}
    saved_sem, orig = ax._bulk_sem, ax.run_once

    async def _run(account_id, kind, **kw):
        slot = ax.run_slot.current()
        if kind == "scrape_chats" and account_id in (a, b):
            held.append(account_id)
            await go.wait()
        elif kind == "priority_mass" and account_id == c:
            op_slot.update(pool=slot.pool, reserve=slot.reserve, operator=slot.operator)
        return {"status": "ok"}
    os.environ[knob] = "2"
    ax._bulk_sem, ax.run_once = None, _run  # type: ignore[attr-defined]
    try:
        await enqueue_job(a, "scrape_chats", payload={})
        await enqueue_job(b, "scrape_chats", payload={})
        await ax._drain_due_jobs_once()
        for _ in range(200):
            if len(held) == 2:
                break
            await asyncio.sleep(0.01)
        assert sorted(held) == [a, b] and ax._bulk_sem.free == 0, (held, ax._bulk_sem.free)
        await enqueue_job(c, "priority_mass", payload={}, created_by_employee_id=op_id)
        await ax._drain_due_jobs_once()
        for _ in range(200):
            if op_slot:
                break
            await asyncio.sleep(0.01)
        assert op_slot == {"pool": ax._bulk_sem, "reserve": True, "operator": True}, (
            "the operator's priority_mass waited behind the sweeps", op_slot)
    finally:
        go.set()
        await ax._join_inflight_runs()
        del os.environ[knob]
        ax._bulk_sem, ax.run_once = saved_sem, orig  # type: ignore[attr-defined]
        await _settle_jobs(a, b, c)


async def case_a_one_fan_scrape_runs_beside_the_accounts_sweep():
    import threading
    import webhook_dispatch as wd
    aid, sweep_chat, fan = "acc_fan_beside_sweep", 9101, 9102
    await _seed_account(aid)
    entered, release = threading.Event(), threading.Event()

    class _ParkedSweep(FakeClient):
        def get_messages(self, chat_id, **kw):
            if int(chat_id) == sweep_chat:
                entered.set()
                release.wait(10)
            return super().get_messages(chat_id, **kw)
    fake = _ParkedSweep({
        sweep_chat: [_of_msg(91011, True, "sweep", "2026-06-03T10:00:00+00:00", fan_id=sweep_chat)],
        fan: [_of_msg(91021, True, "after the blast", "2026-06-03T10:01:00+00:00", fan_id=fan)],
    })
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    pools: dict = {}
    orig = ax.run_once

    async def _spy(account_id, kind, **kw):
        if account_id == aid:
            pools[kind] = ax.run_slot.current().pool
        return await orig(account_id, kind, **kw)

    async def _run(kind):
        async with get_session() as s:
            return (await s.execute(select(AutomationRun).where(
                AutomationRun.account_id == aid, AutomationRun.kind == kind))).scalar_one_or_none()
    ax.run_once = _spy  # type: ignore[attr-defined]
    try:
        await enqueue_job(aid, "scrape_chats", payload={})
        await ax._drain_due_jobs_once()
        assert await asyncio.to_thread(entered.wait, 5), "the sweep never reached OF"
        wd._fan_scrape_claims.pop((aid, fan), None)
        assert await wd.enqueue_fan_scrape(aid, fan, "blast_reply") is True
        await ax._drain_due_jobs_once()
        run = None
        for _ in range(250):
            run = await _run("scrape_fan")
            if run is not None and run.status == "ok":
                break
            await asyncio.sleep(0.02)
        assert run is not None and run.status == "ok", ("the one-fan scrape waited for the sweep", run)
        assert not release.is_set() and (await _run("scrape_chats")).status == "running"
        assert pools == {"scrape_chats": ax._bulk_sem, "scrape_fan": ax._run_sem}, pools
        async with get_session() as s:
            got = (await s.execute(select(Message.message_id).where(
                Message.account_id == aid, Message.fan_id == fan))).scalars().all()
        assert got == [91021], got
    finally:
        release.set()
        await ax._join_inflight_runs()
        ax.run_once = orig  # type: ignore[attr-defined]
    assert (await _run("scrape_chats")).status == "ok"



async def case_client_pool_reuses_and_evicts():
    class _StubClient:
        user_id = "u1"
        x_of_rev = "rev1"

        def close_signed_sessions(self) -> None:
            pass

    class _Stub:
        @staticmethod
        def from_account(account_id: str):
            return _StubClient()

    real_of_client, client_pool.OFClient = client_pool.OFClient, _Stub  # type: ignore[assignment]
    try:
        client_pool.evict()
        first = client_pool.get("acc_pool")
        assert client_pool.get("acc_pool") is first, "same account → same client"
        assert client_pool.get("acc_other") is not first, "pool is per account"
        client_pool.evict("acc_pool")
        assert client_pool.get("acc_pool") is not first, "evict → rebuilt from disk"
        client_pool.evict()
        assert client_pool.get("acc_other") is not first, "evict(None) → all accounts"
    finally:
        client_pool.OFClient = real_of_client  # type: ignore[assignment]
        client_pool.evict()



async def case_unknown_kind_errors():
    res = await run_once("acc_unknown", "does_not_exist")
    assert res["status"] == "error", res
    assert res["reason"] == "unknown_kind", res
    async with get_session() as s:
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == "acc_unknown")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "error", runs
        assert runs[0].error_text and "unknown" in runs[0].error_text.lower()


async def case_unknown_kind_consumes_ghost_job():
    aid = "acc_ghost_job"
    await _seed_account(aid)
    job_id = await enqueue_job(aid, "retired_ghost_kind", payload={})
    res = await run_once(aid, "retired_ghost_kind")
    assert res["status"] == "error" and res["reason"] == "unknown_kind", res
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.status == "error", f"ghost job must be consumed, got {job.status}"
        assert "unknown" in (job.last_error or "").lower(), job.last_error
    res2 = await run_once(aid, "retired_ghost_kind")
    async with get_session() as s:
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
    assert len(runs) == 2, runs
    async with get_session() as s:
        pending = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.status == "pending")
        )).scalars().all()
    assert not pending, pending


async def case_a_failed_run_retries_unless_its_rule_went_off_mid_run():
    from automation_registry import register
    from run_decide import JOB_RETRY_BACKOFF_S
    aid, kind = "acc_park_rule_off", "park_probe_kind"
    await _seed_account(aid)
    switch_off: dict[str, int | None] = {"rule": None}

    @register(kind)
    async def _failing(account_id, payload, *, run_id):
        if switch_off["rule"] is not None:
            async with get_session() as s:
                (await s.get(AutomationRule, switch_off["rule"])).is_enabled = False
        raise RuntimeError("OF refused the write")

    async def _rule(name: str) -> int:
        async with get_session() as s:
            rule = AutomationRule(account_id=aid, name=name, kind=kind,
                                  trigger_json=json.dumps({"every_seconds": 3600}),
                                  steps_json="{}", is_enabled=True)
            s.add(rule)
            await s.flush()
            return rule.id

    job_id = await enqueue_job(aid, kind, payload={}, rule_id=await _rule("on"))
    t0 = datetime.utcnow()
    res = await run_once(aid, kind)
    assert res["status"] == "error" and res["job_id"] == job_id, res
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.attempts == 1, job.attempts
        assert job.status == "pending", job.status
        assert job.run_at >= t0 + timedelta(seconds=JOB_RETRY_BACKOFF_S - 1), job.run_at
        assert "OF refused the write" in job.last_error, job.last_error
        job.status = "done"

    switch_off["rule"] = await _rule("off")
    job_id = await enqueue_job(aid, kind, payload={}, rule_id=switch_off["rule"])
    res = await run_once(aid, kind)
    assert res["status"] == "error" and res["job_id"] == job_id, res
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.attempts == 1, job.attempts
        assert job.status == "cancelled", job.status
        assert job.last_error.startswith(f"{ax.RULE_OFF_REASON} ("), job.last_error
        assert "OF refused the write" in job.last_error, job.last_error


async def case_a_refused_one_shot_waits_out_the_proxy_unless_a_write_may_have_landed():
    from curl_cffi.requests.exceptions import ProxyError
    from automation_registry import _REGISTRY
    import run_decide
    aid = "acc_refused_one_shot"
    await _seed_account(aid)
    mode = {"accept_first": False, "other_first": False}

    def _refuse():
        raise ProxyError("CONNECT tunnel failed, response 403")

    async def _send(account_id, payload, *, run_id):
        if mode.pop("other_first", False):
            raise RuntimeError("OF answered garbage")
        if mode["accept_first"]:
            await ax.of_write_paced(account_id, lambda: {"id": 1}, min_gap_s=0,
                                    send_purpose="not_fan_dm")
        await ax.of_write_paced(account_id, _refuse, min_gap_s=0, send_purpose="not_fan_dm")

    saved = {k: _REGISTRY[k] for k in ("send_mass_message", "scheduled_send")}
    _REGISTRY.update({k: _send for k in saved})
    payload = {"fan_id": 1, "text": "hi"}
    try:
        kind = "send_mass_message"
        mode["other_first"] = True
        job_id = await enqueue_job(aid, kind, payload=payload)
        res = await run_once(aid, kind)
        async with get_session() as s:
            job = await s.get(ScheduledJob, job_id)
            assert job.status == "pending" and not job.last_error.startswith(run_decide.PROXY_RETRY), job.last_error
            job.run_at = datetime.utcnow()
        for n in range(1, run_decide.PROXY_RETRIES + 2):
            t0 = datetime.utcnow()
            res = await run_once(aid, kind)
            assert res["status"] == "error" and res["job_id"] == job_id, res
            async with get_session() as s:
                job = await s.get(ScheduledJob, job_id)
                assert job.attempts == n + 1, (n, job.attempts)
                if n <= run_decide.PROXY_RETRIES:
                    assert job.status == "pending", (n, job.status)
                    assert job.run_at >= t0 + timedelta(minutes=run_decide.PROXY_RETRY_MINUTES) - timedelta(seconds=1), job.run_at
                    assert job.last_error.startswith(f"{run_decide.PROXY_RETRY}:{n} ("), job.last_error
                    job.run_at = datetime.utcnow()
                else:
                    assert job.status == "error", job.status
                    assert job.last_error.startswith(f"{run_decide.PROXY_REFUSED} ("), job.last_error
                    assert "403" in job.last_error, job.last_error

        kind = "scheduled_send"
        job_id = await enqueue_job(aid, kind, payload=payload)
        t0 = datetime.utcnow()
        res = await run_once(aid, kind)
        assert res["status"] == "error" and res["job_id"] == job_id, res
        async with get_session() as s:
            job = await s.get(ScheduledJob, job_id)
            assert job.status == "pending" and not job.last_error.startswith(run_decide.PROXY_RETRY), job.last_error
            assert job.run_at <= t0 + timedelta(seconds=run_decide.JOB_RETRY_BACKOFF_S + 5), job.run_at

        mode["accept_first"] = True  # OF took a write, then the proxy refused: send once
        job_id = await enqueue_job(aid, "send_mass_message", payload=payload)
        res = await run_once(aid, "send_mass_message")
        assert res["status"] == "error" and res["job_id"] == job_id, res
        async with get_session() as s:
            job = await s.get(ScheduledJob, job_id)
            assert job.status == "error", job.status
            assert job.last_error.startswith(run_decide.MAY_HAVE_SENT), job.last_error
    finally:
        _REGISTRY.update(saved)


async def case_orphaned_one_shot_parks_sweep_requeues():
    aid = "acc_orphans"
    await _seed_account(aid)
    send_id = await enqueue_job(aid, "scheduled_send", payload={"fan_id": 1, "text": "hi"})
    others = [await enqueue_job(aid, k, payload={}) for k in ("mass_premade", "send_mass_message")]
    reply_id = await enqueue_job(aid, "auto_reply", payload={})
    async with get_session() as s:
        for jid in (send_id, reply_id, *others):
            (await s.get(ScheduledJob, jid)).status = "running"
        run = AutomationRun(account_id=aid, kind="scheduled_send",
                            started_at=datetime.utcnow(), status="running")
        s.add(run)
        await s.flush()
        run_id = run.id
    for _ in range(2):
        await ax._reconcile_orphans()
        async with get_session() as s:
            send = await s.get(ScheduledJob, send_id)
            reply = await s.get(ScheduledJob, reply_id)
            run = await s.get(AutomationRun, run_id)
            assert send.status == "error", f"orphaned scheduled_send {send.status}: may have sent"
            assert send.last_error == "interrupted, may have sent", send.last_error
            assert reply.status == "pending", f"orphaned sweep {reply.status}"
            for jid in others:
                job = await s.get(ScheduledJob, jid)
                assert job.status == "error" and job.last_error == "interrupted, may have sent", (
                    job.kind, job.status, job.last_error)
            assert run.status == "error" and "interrupted" in (run.error_text or ""), run.status


async def case_orphaned_mass_run_ends_interrupted_never_resent():
    aid = "acc_mass_orphan"
    await _seed_account(aid)
    async with get_session() as s:
        orphan = MassRun(account_id=aid, automation_kind="mass_premade", status="running")
        closed = MassRun(account_id=aid, automation_kind="mass_premade", status="ok", queue_id=7)
        s.add_all([orphan, closed])
        await s.flush()
        orphan_id, closed_id = orphan.id, closed.id
        jobs_before = len((await s.execute(select(ScheduledJob.id))).all())
    for _ in range(2):
        await ax._reconcile_orphans()
        async with get_session() as s:
            o, c = await s.get(MassRun, orphan_id), await s.get(MassRun, closed_id)
            assert o.status == ax.MASS_RUN_INTERRUPTED == "interrupted", o.status
            assert o.completed_at is not None and o.queue_id is None
            assert c.status == "ok" and c.queue_id == 7, (c.status, c.queue_id)
            assert len((await s.execute(select(ScheduledJob.id))).all()) == jobs_before



async def case_supervisor_drain_runs_due_job():
    aid, fan = "acc_super", 4001
    await _seed_account(aid)
    _use_fake({fan: [_of_msg(8001, True, "drained", "2026-06-04T10:00:00+00:00", fan_id=fan)]})

    job_id = await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    await ax._drain_due_jobs_once()
    await ax._join_inflight_runs()

    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.status == "done", f"drain consumed the job, got {job.status}"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all()
        assert len(msgs) == 1, len(msgs)
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs



async def case_drain_waits_for_a_run_that_claimed_a_send_then_refuses_new_claims():
    finished = []

    async def sending_run():
        assert ax.begin_send()
        await asyncio.sleep(0.3)
        finished.append(True)

    async def planning_run():
        await asyncio.sleep(5)

    sender = asyncio.create_task(sending_run())
    planner = asyncio.create_task(planning_run())
    await asyncio.sleep(0)
    try:
        out = await ax.drain(timeout_s=5)
        assert out["waited"] == 1 and out["left"] == 0, out
        assert finished == [True] and sender.done() and not planner.done()
        assert ax.begin_send() is False, "a pass must not claim while the relay drains"
    finally:
        planner.cancel()
        ax._draining = False


async def case_drain_stops_waiting_once_the_send_is_settled():
    async def run_with_a_slow_tail():
        assert ax.begin_send()
        await asyncio.sleep(0.2)
        ax.end_send()
        await asyncio.sleep(30)

    t = asyncio.create_task(run_with_a_slow_tail())
    await asyncio.sleep(0)
    try:
        out = await ax.drain(timeout_s=10)
        assert out["waited"] == 1 and out["left"] == 0 and out["s"] < 2, out
        assert not t.done()
    finally:
        t.cancel()
        ax._draining = False


async def case_drain_is_bounded_by_its_timeout():
    async def stuck_run():
        assert ax.begin_send()
        await asyncio.sleep(30)

    t = asyncio.create_task(stuck_run())
    await asyncio.sleep(0)
    try:
        out = await ax.drain(timeout_s=0.2)
        assert out["waited"] == 1 and out["left"] == 1 and out["s"] < 2, out
    finally:
        t.cancel()
        ax._draining = False


async def case_a_draining_supervisor_starts_no_run_and_leaves_the_job_pending():
    aid = "acc_draining"
    await _seed_account(aid)
    _use_fake({})
    job_id = await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [4002]})
    ax._draining = True
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax._draining = False
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.status == "pending", job.status
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid))).scalars().all()
        assert runs == [], runs



async def case_rule_materializes_job():
    aid = "acc_rule"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="periodic scrape", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [5555]}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"a due rule materialized at least one job, got {n}"

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "scrape_chats",
                ScheduledJob.status == "pending",
            )
        )).scalars().all()
        assert len(jobs) == 1, f"exactly one job, got {len(jobs)}"
        assert json.loads(jobs[0].payload_json) == {"chat_ids": [5555]}, jobs[0].payload_json
        assert jobs[0].rule_id is not None, "job links back to the rule"

    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending"
            )
        )).scalars().all()
        assert len(jobs) == 1, "no duplicate while a pending job exists"


async def case_rule_with_unregistered_kind_stays_inert():
    aid = "acc_rule_ghost"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="retired engine", kind="ghost_kind",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({}),
            is_enabled=True,
        ))

    await ax._materialize_due_rules()

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid)
        )).scalars().all()
        assert jobs == [], f"unregistered kind must not enqueue, got {jobs}"
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert runs == [], f"and no error runs either, got {runs}"


async def case_future_oneshot_does_not_starve_rule():
    aid = "acc_starve"
    await _seed_account(aid)
    await enqueue_job(
        aid, "unsend_messages",
        payload={"targets": [{"story_id": 42}]},
        run_at=datetime.utcnow() + timedelta(hours=6),
    )
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="auto-unsend mass", kind="unsend_messages",
            trigger_json=json.dumps({"every_seconds": 3600}),
            steps_json=json.dumps({"policy": {"mass_text_hours": 4}}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule must materialize despite the future cleanup, got {n}"

    async with get_session() as s:
        due = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.status == "pending",
                ScheduledJob.run_at <= datetime.utcnow(),
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(due) == 1, f"the rule's own due job exists, got {len(due)}"

    await ax._materialize_due_rules()
    async with get_session() as s:
        rule_jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(rule_jobs) == 1, "no duplicate of the rule's due job"


async def case_rule_quiet_hours_holds_job():
    aid = "acc_quiet_in"
    await _seed_account(aid)
    off = 3
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=off))
    h = (datetime.utcnow().hour + off) % 24
    band = [(h - 1) % 24, (h + 2) % 24]
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="quiet scrape", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [1]}),
            quiet_hours_json=json.dumps(band), is_enabled=True,
        ))

    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
        )).scalars().all()
    assert jobs == [], f"quiet-hours rule must NOT enqueue, got {len(jobs)}"


async def case_rule_quiet_hours_outside_band_materializes():
    aid = "acc_quiet_out"
    await _seed_account(aid)
    off = 3
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=off))
    h = (datetime.utcnow().hour + off) % 24
    band = [(h + 3) % 24, (h + 5) % 24]
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="awake scrape", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [2]}),
            quiet_hours_json=json.dumps(band), is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, "rule outside its quiet band must still materialize"
    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
        )).scalars().all()
    assert len(jobs) == 1, f"exactly one job, got {len(jobs)}"


async def case_quiet_hours_never_run_on_the_server_clock():
    aid = "acc_quiet_noclock"
    await _seed_account(aid)
    h = datetime.utcnow().hour
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="clockless", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [3]}),
            quiet_hours_json=json.dumps([(h - 1) % 24, (h + 2) % 24]),
            is_enabled=True))
    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.status == "pending"))).scalars().all()
    assert len(jobs) == 1, "a clockless account has no local band to be inside"

    aid2 = "acc_quiet_bothclocks"
    await _seed_account(aid2)
    off = 3
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid2, utc_offset=off,
                              timezone="America/Los_Angeles"))
    her_h = (datetime.utcnow().hour + off) % 24
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid2, name="two clocks", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [4]}),
            quiet_hours_json=json.dumps([(her_h - 1) % 24, (her_h + 2) % 24]),
            is_enabled=True))
    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid2, ScheduledJob.status == "pending"))).scalars().all()
    assert jobs == [], "the band around the OFFSET's hour must hold the job"


async def case_quiet_band_clock_read_only_for_due_free_rules():
    import logging
    now = datetime.utcnow()
    band = json.dumps([0, 23])
    busy, notdue, noclk = "acc_clk_busy", "acc_clk_notdue", "acc_clk_noclock"
    for aid in (busy, notdue, noclk):
        await _seed_account(aid)
    hourly = json.dumps({"every_seconds": 3600})
    async with get_session() as s:
        s.add(ScheduledJob(account_id=busy, kind="scrape_chats", payload_json="{}",
                           run_at=now - timedelta(seconds=5), status="pending"))
        s.add(AutomationRule(account_id=busy, name="busy", kind="scrape_chats",
                             trigger_json=hourly, steps_json="{}",
                             quiet_hours_json=band, is_enabled=True))
        nd = AutomationRule(account_id=notdue, name="not due", kind="scrape_chats",
                            trigger_json=hourly, steps_json="{}",
                            quiet_hours_json=band, is_enabled=True)
        s.add(nd)
        for kind in ("scrape_chats", "send_welcome"):
            s.add(AutomationRule(account_id=noclk, name=f"noclock {kind}", kind=kind,
                                 trigger_json=hourly, steps_json="{}",
                                 quiet_hours_json=band, is_enabled=True))
        await s.flush()
        s.add(ScheduledJob(account_id=notdue, kind="scrape_chats", payload_json="{}",
                           run_at=now, status="done", rule_id=nd.id, created_at=now))

    reads: list[str] = []
    real = ax._account_clock

    async def counting(s, account_id, offsets, now):
        reads.append(account_id)
        return await real(s, account_id, offsets, now)

    warned: list[str] = []

    class _H(logging.Handler):
        def emit(self, rec):
            if "quiet_hours_no_clock" in rec.getMessage():
                warned.append(rec.getMessage())

    h = _H()
    ax.log.addHandler(h)
    ax._account_clock = counting
    try:
        await ax._materialize_due_rules()
    finally:
        ax._account_clock = real
        ax.log.removeHandler(h)
    assert busy not in reads and notdue not in reads, reads
    assert reads.count(noclk) == 2, reads
    assert len([w for w in warned if noclk in w]) == 1, warned
    async with get_session() as s:
        jobs = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == noclk, ScheduledJob.status == "pending"))).scalars().all()
        assert len(jobs) == 2, "clockless: the band cannot apply, both rules fire"
        for r in (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id.in_((busy, notdue, noclk))))).scalars():
            r.is_enabled = False


async def case_oneshot_runs_dont_reset_rule_cadence():
    aid = "acc_cadence"
    await _seed_account(aid)
    await ax._open_run(aid, "unsend_messages")

    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="auto-unsend mass", kind="unsend_messages",
            trigger_json=json.dumps({"every_seconds": 3600}),
            steps_json=json.dumps({"policy": {"mass_text_hours": 4}}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule must materialize despite a recent one-shot run, got {n}"
    async with get_session() as s:
        rule_jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(rule_jobs) == 1, f"the rule enqueued its own job, got {len(rule_jobs)}"

    await ax._materialize_due_rules()
    async with get_session() as s:
        rule_jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(rule_jobs) == 1, "interval holds — no duplicate within the window"


async def case_clock_rule_not_starved_by_same_kind_run():
    aid = "acc_clock_cadence"
    await _seed_account(aid)

    fixed_now = datetime(2020, 1, 1, 12, 0, 0)
    real_dt = ax.datetime

    class _Frozen(real_dt):  # type: ignore[misc, valid-type]
        @classmethod
        def utcnow(cls):
            return fixed_now

    async with get_session() as s:
        s.add(AutomationRun(
            account_id=aid, kind="auto_stories",
            started_at=datetime(2020, 1, 1, 11, 30, 0),
            completed_at=datetime(2020, 1, 1, 11, 30, 5),
            status="ok",
        ))
        s.add(AutomationRule(
            account_id=aid, name="daily story", kind="auto_stories",
            trigger_json=json.dumps({"daily_at": ["11:00"], "tz_offset_minutes": 0}),
            steps_json=json.dumps({}),
            is_enabled=True,
        ))

    ax.datetime = _Frozen  # type: ignore[assignment]
    try:
        n = await ax._materialize_due_rules()
        assert n >= 1, f"daily_at slot must fire despite a later same-kind run, got {n}"
        async with get_session() as s:
            jobs = (await s.execute(
                select(ScheduledJob).where(
                    ScheduledJob.account_id == aid,
                    ScheduledJob.kind == "auto_stories",
                    ScheduledJob.rule_id.isnot(None),
                )
            )).scalars().all()
            assert len(jobs) == 1, f"exactly one job from the slot, got {len(jobs)}"

        await ax._materialize_due_rules()
        async with get_session() as s:
            jobs = (await s.execute(
                select(ScheduledJob).where(
                    ScheduledJob.account_id == aid,
                    ScheduledJob.kind == "auto_stories",
                    ScheduledJob.rule_id.isnot(None),
                )
            )).scalars().all()
            assert len(jobs) == 1, "slot fires once per day — no duplicate"
    finally:
        ax.datetime = real_dt  # type: ignore[assignment]


_harness.run(
    case_scrape_job_persists_both_directions,
    case_scrape_fast_skip,
    case_scrape_all_chats_sweep,
    case_scrape_sweep_paginates_all_chats,
    case_scrape_full_sweep_mark_only_on_empty_payload,
    case_scrape_long_convo_both_ends,
    case_scrape_desc_catch_up_no_refetch_start,
    case_gap_only_scrape_keeps_recency_and_preview,
    case_dropped_dm_scrape_only_peeks,
    case_idle_scrape_keeps_a_concurrently_opened_gap,
    case_scrape_capped_catch_up_keeps_the_middle,
    case_scrape_gap_merges_when_the_newest_end_caps_again,
    case_scrape_full_pull_keeps_what_it_read_on_429,
    case_scrape_full_pull_first_scrape_reads_to_the_start,
    case_scrape_full_pull_first_scrape_cut_by_429_keeps_a_gap_to_the_start,
    case_rescrape_now_commits_a_bounded_chunk_and_resumes,
    case_rescrape_now_retries_after_losing_the_gap_cas,
    case_rescrape_now_stops_on_429_with_a_resumable_gap,
    case_rescrape_now_pulls_whole_history_and_continues_past_the_wait,
    case_scrape_heals_only_a_stored_zero_price,
    case_thread_page_save_upserts_by_id,
    case_stale_thread_page_keeps_confirmed_unsend,
    case_scrape_sweep_stops_after_five_systemic_failures_in_a_row,
    case_scrape_sweep_fail_fast_counts_only_in_a_row,
    case_scrape_sweep_fail_fast_before_first_scan_and_knob,
    case_scrape_sweep_stops_at_its_time_budget,
    case_scrape_budget_failing_chats_do_not_stay_first,
    case_scrape_explicit_backfill_that_scraped_nothing_raises,
    case_scrape_silent_mass_only_chat_costs_one_page_and_defers,
    case_scrape_not_silent_chats_are_backfilled_as_today,
    case_scrape_cursor_write_clears_the_deferred_mark,
    case_scrape_empty_explicit_backfill_clears_the_deferred_mark,
    case_scrape_non_positive_limits_still_read_before_clearing_the_mark,
    case_scrape_eager_history_knob_restores_todays_calls,
    case_scrape_deferred_backfill_counts_under_its_own_caller_kind,
    case_scrape_page_one_peeks,
    case_scrape_unread_long_first_scrape_defers_backfill,
    case_scrape_read_long_first_scrape_runs_both_ends,
    case_scrape_explicit_unread_by_local_marker_defers,
    case_scrape_explicit_missing_chat_row_defers,
    case_scrape_deferred_row_backfills_only_on_the_click,
    case_scrape_sweep_backfills_a_deferred_row_read_on_both_sides,
    case_scrape_eager_history_does_not_backfill_unread,
    case_scrape_unread_silent_mass_chat_still_costs_one_page,
    case_scrape_unread_flip_before_asc_defers,
    case_scrape_dm_during_ascending_pace_defers,
    case_scrape_dm_between_click_and_job_defers,
    case_scrape_click_backfill_before_local_zeroing_pulls_both_ends,
    case_scrape_resweep_of_a_deferred_unread_chat_reads_page_one,
    case_scrape_dm_after_the_sweep_list_defers,
    case_scrape_click_mid_scrape_stays_read,
    case_scrape_fansly_keeps_both_ends,
    case_scrape_short_unread_chat_is_read_whole_and_not_deferred,
    case_history_deferred_at_self_heals_on_init_db,
    case_fan_lease_acquire_block_steal,
    case_fan_cooldown_set_check_expire,
    case_kind_priority_ordering,
    case_supervisor_dispatches_high_priority_first,
    case_supervisor_dispatches_least_recently_served_account_first,
    case_due_pairs_carry_their_oldest_due_run_at,
    case_an_operators_job_dispatches_first_in_the_operator_tier,
    case_the_claim_takes_the_operators_job_first,
    case_run_now_on_an_automation_kind_is_rate_limited_as_automation,
    case_the_run_slots_size_from_the_active_creators,
    case_the_bulk_slots_size_from_the_active_creators,
    case_an_operators_priority_mass_takes_the_bulk_reserve_past_two_sweeps,
    case_a_one_fan_scrape_runs_beside_the_accounts_sweep,
    case_client_pool_reuses_and_evicts,
    case_unknown_kind_errors,
    case_unknown_kind_consumes_ghost_job,
    case_a_failed_run_retries_unless_its_rule_went_off_mid_run,
    case_a_refused_one_shot_waits_out_the_proxy_unless_a_write_may_have_landed,
    case_orphaned_one_shot_parks_sweep_requeues,
    case_orphaned_mass_run_ends_interrupted_never_resent,
    case_supervisor_drain_runs_due_job,
    case_rule_materializes_job,
    case_rule_with_unregistered_kind_stays_inert,
    case_future_oneshot_does_not_starve_rule,
    case_oneshot_runs_dont_reset_rule_cadence,
    case_clock_rule_not_starved_by_same_kind_run,
    case_rule_quiet_hours_holds_job,
    case_rule_quiet_hours_outside_band_materializes,
    case_quiet_hours_never_run_on_the_server_clock,
    case_quiet_band_clock_read_only_for_due_free_rules,
    case_drain_waits_for_a_run_that_claimed_a_send_then_refuses_new_claims,
    case_drain_stops_waiting_once_the_send_is_settled,
    case_drain_is_bounded_by_its_timeout,
    case_a_draining_supervisor_starts_no_run_and_leaves_the_job_pending,
)
