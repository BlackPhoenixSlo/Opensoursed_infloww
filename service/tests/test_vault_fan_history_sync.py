#!/usr/bin/env python3
"""
The vault picker's bought/sent badges: `vault_sends` filled by the chat-open backfill and by
`POST /admin/vault/fan-history/sync` (OF chat gallery walk, cached per Fan). Fake OF client only.

  case_backfill_flips_bought_never_back:
      an existing (media, message) row flips to was_purchased=True when an item shows it bought
      (`updated`, history returned); a later unbought item never flips it back; a re-sent identical
      batch changes nothing and returns no history.
  case_backfill_stores_of_created_at:
      a new row takes the item's `sent_at` (OF createdAt) instead of "now".
  case_sync_walk_inserts_and_flips:
      a first sync walks every page (cursor = nextLastId, from_user = the Creator, skip_users=all,
      limit 50), inserts missing rows with price/createdAt, flips an existing priced+opened row,
      leaves free sends was_purchased NULL, skips a message from anyone but the Creator, and
      records the sync row (pages, complete).
  case_sync_cache_hit_makes_no_of_call:
      synced within 7 days → zero OF calls, cached history; synced 8 days ago walks again.
  case_sync_failure_cools_down_an_hour:
      an OF error → local history, only last_attempt_at written; within the hour
      zero OF calls; an hour later it walks again.
  case_sync_page_cap:
      an endless gallery stops at 10 pages, complete=False.
  case_sync_concurrent_opens_walk_once:
      two opens of the same Fan at once → one walk; the second gets the cached history.
  case_sync_foreign_account_is_refused:
      another owner's account → 403, no OF call.

Run: venv/bin/python service/tests/test_vault_fan_history_sync.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import threading  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert, select, update  # noqa: E402

import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, FanMediaSync, Transaction, User, UserAccount, VaultSend  # noqa: E402

_harness.make_client()
import server  # noqa: E402

ACC, OTHER = "1000001", "2000002"
_ACCOUNTS = (ACC, OTHER)
account_registry.get_account = lambda aid: {"id": aid} if aid in _ACCOUNTS else None
account_registry.list_accounts = lambda: [{"id": a, "has_session": True} for a in _ACCOUNTS]
account_registry.is_account = lambda aid: aid in _ACCOUNTS


async def _setup() -> None:
    async with get_session() as s:
        a = User(id=uuid.uuid4().hex, username="owner_sync", password="pw")
        b = User(id=uuid.uuid4().hex, username="owner_other", password="pw")
        s.add_all([a, b, *(Account(id=x, nickname=x) for x in _ACCOUNTS)])
        await s.flush()
        s.add_all([UserAccount(user_id=a.id, account_id=ACC), UserAccount(user_id=b.id, account_id=OTHER)])
        await s.commit()


asyncio.run(_setup())


def _login(username: str = "owner_sync") -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login", json={"username": username, "password": "pw"})
    assert r.status_code == 200, r.text
    return c


def _q(stmt):
    async def go():
        async with get_session() as s:
            return (await s.execute(stmt)).all()
    return asyncio.run(go())


def _exec(stmt) -> None:
    async def go():
        async with get_session() as s:
            await s.execute(stmt)
            await s.commit()
    asyncio.run(go())


def _rows(fan: int) -> dict[tuple[int, int], tuple]:
    return {(m, msg): (bought, price, sent_at) for m, msg, bought, price, sent_at in _q(
        select(VaultSend.media_id, VaultSend.message_id, VaultSend.was_purchased, VaultSend.price_cents,
               VaultSend.sent_at).where(VaultSend.account_id == ACC, VaultSend.fan_id == fan))}


def _sync_row(fan: int):
    rows = _q(select(FanMediaSync.synced_at, FanMediaSync.last_attempt_at, FanMediaSync.pages,
                     FanMediaSync.complete).where(FanMediaSync.account_id == ACC, FanMediaSync.fan_id == fan))
    return rows[0] if rows else None


def _msg(mid: int, media: list[int], *, price: float = 0, opened: bool = False, sender: int | None = int(ACC),
         created: str = "2026-03-04T05:06:07+00:00") -> dict:
    m = {"id": mid, "price": price, "isOpened": opened, "createdAt": created, "media": [{"id": x} for x in media]}
    if sender is not None:
        m["fromUser"] = {"id": sender}
    return m


class _Gallery:
    """A fake OF client: `chat_media` answers `pages` in order (the last one repeats), records its kwargs."""

    user_id = ACC

    def __init__(self, pages: list[dict] | None = None, error: Exception | None = None, gate=None):
        self.pages = pages or [{"list": [], "hasMore": False}]
        self.error = error
        self.gate = gate
        self.calls: list[dict] = []

    def chat_media(self, chat_id, **kw):
        self.calls.append({"chat_id": chat_id, **kw})
        if self.gate is not None:
            self.gate.wait(10)
        if self.error is not None:
            raise self.error
        return self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]


class _Using:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.orig = server._load_client
        server._load_client = lambda _aid: self.fake
        return self.fake

    def __exit__(self, *_exc):
        server._load_client = self.orig


def _sync(c: TestClient, fan: int, **extra):
    return c.post("/admin/vault/fan-history/sync", json={"account_id": ACC, "fan_id": fan, **extra})


def case_backfill_flips_bought_never_back() -> None:
    c = _login()
    fan = 501
    r = c.post("/admin/vault/sends", json={
        "account_id": ACC, "fan_id": fan, "media_ids": [301], "message_id": 10, "price_cents": 500})
    assert r.status_code == 200, r.text
    assert _rows(fan)[(301, 10)][0] is None

    def bf(bought):
        return c.post("/admin/vault/sends/backfill", json={"account_id": ACC, "fan_id": fan, "items": [
            {"message_id": 10, "media_ids": [301], "price_cents": 500, "was_purchased": bought}]}).json()

    body = bf(True)
    assert (body["inserted"], body["updated"]) == (0, 1), body
    assert body["history"]["by_media"]["301"]["was_purchased"] is True, body
    assert _rows(fan)[(301, 10)][0] is True
    body = bf(False)
    assert (body["inserted"], body["updated"], "history" in body) == (0, 0, False), body
    assert _rows(fan)[(301, 10)][0] is True, "a bought row flipped back"
    body = bf(True)
    assert (body["inserted"], body["updated"], body["skipped"], "history" in body) == (0, 0, 1, False), body


def case_backfill_stores_of_created_at() -> None:
    c = _login()
    fan = 502
    r = c.post("/admin/vault/sends/backfill", json={"account_id": ACC, "fan_id": fan, "items": [
        {"message_id": 11, "media_ids": [302], "price_cents": 0, "sent_at": "2026-01-02T03:04:05Z"},
        {"message_id": 12, "media_ids": [303], "price_cents": 0, "sent_at": "garbage"}]})
    assert r.status_code == 200 and r.json()["inserted"] == 2, r.text
    rows = _rows(fan)
    assert rows[(302, 11)][2] == datetime(2026, 1, 2, 3, 4, 5), rows
    assert abs(rows[(303, 12)][2] - datetime.utcnow()) < timedelta(minutes=5), rows


def case_sync_walk_inserts_and_flips() -> None:
    c = _login()
    fan = 503
    c.post("/admin/vault/sends", json={
        "account_id": ACC, "fan_id": fan, "media_ids": [401], "message_id": 20, "price_cents": 900})
    fake = _Gallery([
        {"list": [
            _msg(20, [401], price=9, opened=True),
            _msg(21, [402], sender=fan),                       # the Fan's own attachment
            _msg(22, [403], opened=True, sender=None),          # free, no fromUser: the Creator's (from_user)
        ], "hasMore": True, "nextLastId": "22"},
        {"list": [_msg(23, [404, 405], price=12, created="2025-12-01T00:00:00Z")], "hasMore": False},
    ])
    with _Using(fake):
        r = _sync(c, fan)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {k: body[k] for k in ("synced", "cached", "inserted", "updated", "pages", "complete")} == {
        "synced": True, "cached": False, "inserted": 3, "updated": 1, "pages": 2, "complete": True}, body
    assert [(k["chat_id"], k["last_id"], k["from_user"], k["skip_users"], k["limit"]) for k in fake.calls] == [
        (fan, None, ACC, "all", 50), (fan, "22", ACC, "all", 50)], fake.calls
    rows = _rows(fan)
    assert set(rows) == {(401, 20), (403, 22), (404, 23), (405, 23)}, rows
    assert rows[(401, 20)][0] is True
    assert rows[(403, 22)][:2] == (None, 0)
    assert rows[(404, 23)][:3] == (False, 1200, datetime(2025, 12, 1)), rows[(404, 23)]
    hist = body["history"]["by_media"]
    assert hist["401"]["was_purchased"] is True and "402" not in hist and hist["404"]["was_purchased"] is False, hist
    synced_at, attempt, pages, complete = _sync_row(fan)
    assert synced_at is not None and attempt == synced_at and (pages, complete) == (2, True)


def case_sync_cache_hit_makes_no_of_call() -> None:
    c = _login()
    fan = 504
    with _Using(_Gallery([{"list": [_msg(30, [501])], "hasMore": False}])):
        assert _sync(c, fan).json()["synced"] is True
    fake = _Gallery([{"list": [_msg(31, [502])], "hasMore": False}])
    with _Using(fake):
        body = _sync(c, fan).json()
    assert fake.calls == [] and (body["synced"], body["cached"]) == (False, True), body
    assert set(body["history"]["by_media"]) == {"501"}, body
    _exec(update(FanMediaSync).where(FanMediaSync.account_id == ACC, FanMediaSync.fan_id == fan).values(
        synced_at=datetime.utcnow() - timedelta(days=8), last_attempt_at=datetime.utcnow() - timedelta(days=8)))
    with _Using(fake):
        assert _sync(c, fan).json()["synced"] is True
    assert len(fake.calls) == 1


def case_sync_failure_cools_down_an_hour() -> None:
    c = _login()
    fan = 505
    c.post("/admin/vault/sends", json={"account_id": ACC, "fan_id": fan, "media_ids": [601], "message_id": 40})
    bad = _Gallery(error=RuntimeError("OF said no"))
    with _Using(bad):
        r = _sync(c, fan)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["synced"], body["cached"], set(body["history"]["by_media"])) == (False, False, {"601"}), body
    synced_at, attempt, pages, _ = _sync_row(fan)
    assert synced_at is None and attempt is not None and pages == 0
    good = _Gallery([{"list": [_msg(41, [602])], "hasMore": False}])
    with _Using(good):
        assert _sync(c, fan).json()["cached"] is True
    assert good.calls == [], good.calls
    _exec(update(FanMediaSync).where(FanMediaSync.account_id == ACC, FanMediaSync.fan_id == fan).values(
        last_attempt_at=datetime.utcnow() - timedelta(minutes=61)))
    with _Using(good):
        body = _sync(c, fan).json()
    assert len(good.calls) == 1 and body["synced"] is True and "602" in body["history"]["by_media"], body


def case_sync_page_cap() -> None:
    c = _login()
    fan = 506
    fake = _Gallery([{"list": [_msg(50 + i, [701])], "hasMore": True, "nextLastId": 50 + i}
                     for i in range(10)])
    with _Using(fake):
        body = _sync(c, fan).json()
    assert len(fake.calls) == 10 and (body["pages"], body["complete"]) == (10, False), (len(fake.calls), body)
    assert _sync_row(fan)[2:] == (10, False)


def case_sync_concurrent_opens_walk_once() -> None:
    fan = 507
    gate = threading.Event()
    fake = _Gallery([{"list": [_msg(60, [801])], "hasMore": False}], gate=gate)
    out: list = []
    with TestClient(server.app) as c, _Using(fake):
        assert c.post("/auth/login", json={"username": "owner_sync", "password": "pw"}).status_code == 200
        ts = [threading.Thread(target=lambda: out.append(_sync(c, fan).json())) for _ in range(2)]
        for t in ts:
            t.start()
        for _ in range(100):
            if fake.calls:
                break
            threading.Event().wait(0.05)
        threading.Event().wait(0.2)
        gate.set()
        for t in ts:
            t.join(15)
    assert len(fake.calls) == 1, fake.calls
    assert sorted((b["synced"], b["cached"]) for b in out) == [(False, True), (True, False)], out
    assert all("801" in b["history"]["by_media"] for b in out), out


def case_sync_foreign_account_is_refused() -> None:
    c = _login("owner_other")
    fake = _Gallery()
    with _Using(fake):
        r = _sync(c, 508)
    assert r.status_code == 403 and fake.calls == [], (r.status_code, r.text, fake.calls)


async def case_overlapping_backfills_insert_once() -> None:
    from vault_sends_api import _VaultBackfillItem, _upsert_sends

    fan = 509
    items = [_VaultBackfillItem(message_id=70, media_ids=[901], price_cents=800, was_purchased=True)]
    results = await asyncio.gather(*(_upsert_sends(ACC, fan, items) for _ in range(2)))
    assert sum(result[0] for result in results) == 1, results
    async with get_session() as s:
        rows = (await s.scalars(select(VaultSend).where(VaultSend.account_id == ACC, VaultSend.fan_id == fan))).all()
        assert len(rows) == 1 and rows[0].was_purchased is True


def case_gallery_pages_use_walk_pacer() -> None:
    import time
    from unittest.mock import patch

    import of_pacing

    class PacedGallery(_Gallery):
        def chat_media(self, chat_id, **kw):
            def read():
                calls_at.append(time.monotonic())
                return super(PacedGallery, self).chat_media(chat_id, **kw)

            return of_pacing.paced(ACC, read)

    calls_at = []
    fake = PacedGallery([{"list": [], "hasMore": True, "nextLastId": 7},
                         {"list": [], "hasMore": False}])
    gap = 0.2
    try:
        with _Using(fake), patch.object(of_pacing, "PAGE_GAP_S", gap), patch.object(of_pacing, "JITTER_S", 0):
            body = _sync(_login(), 516).json()
        assert body["synced"] and body["pages"] == 2, body
        assert calls_at[1] - calls_at[0] >= gap - 0.01, calls_at
    finally:
        of_pacing._next_at.pop(ACC, None)


def case_gallery_429_walk_paces_retries_once_and_cools_down() -> None:
    import time
    from unittest.mock import patch

    from fastapi import HTTPException
    import of_pacing

    class PacedGallery(_Gallery):
        def chat_media(self, chat_id, **kw):
            def read():
                calls_at.append(time.monotonic())
                return super(PacedGallery, self).chat_media(chat_id, **kw)

            return of_pacing.paced(ACC, read)

    c = _login()
    calls_at: list[float] = []
    fake = PacedGallery(error=HTTPException(502, {"upstream_status": 429, "upstream_body": "Please allow 0 seconds"}))
    gap = 0.2
    try:
        with _Using(fake), patch.object(of_pacing, "PAGE_GAP_S", gap), patch.object(of_pacing, "JITTER_S", 0):
            for fan in (510, 511):
                body = _sync(c, fan).json()
                assert (body["synced"], body["cached"], body["history"]) == (False, False, {"by_media": {}}), body
                synced_at, attempt, _, _ = _sync_row(fan)
                assert synced_at is None and attempt is not None
            assert len(calls_at) == 4, calls_at
            assert all(b - a >= gap - 0.01 for a, b in zip(calls_at, calls_at[1:])), calls_at
            for fan in (510, 511):
                assert _sync(c, fan).json()["cached"] is True
            assert len(calls_at) == 4, calls_at
    finally:
        of_pacing._next_at.pop(ACC, None)
        of_pacing._gates.pop(ACC, None)


def case_sync_uses_signed_creator_id() -> None:
    c = _login()
    fake = _Gallery([{"list": [_msg(70, [902], sender=321), _msg(71, [903])], "hasMore": False}])
    fake.user_id = "321"
    with _Using(fake):
        body = _sync(c, 512).json()
    assert str(fake.calls[0]["from_user"]) == "321"
    assert set(body["history"]["by_media"]) == {"902"}


def case_sync_without_of_identity_returns_local_history() -> None:
    c = _login()
    fake = _Gallery()
    fake.user_id = "fansly-id"
    with _Using(fake):
        assert _sync(c, 513).json() == {"history": {"by_media": {}}, "synced": False, "cached": False}
    assert fake.calls == [] and _sync_row(513) is None


def case_sync_invalid_cursor_never_stamps_success() -> None:
    c = _login()
    for fan, pages in (
        (514, [{"list": [_msg(70, [902])], "hasMore": True}]),
        (515, [{"list": [], "hasMore": True, "nextLastId": 7},
               {"list": [], "hasMore": True, "nextLastId": "7"}]),
    ):
        fake = _Gallery(pages)
        with _Using(fake):
            body = _sync(c, fan).json()
        assert body["synced"] is False and body["history"] == {"by_media": {}}, body
        assert _sync_row(fan)[0] is None
        assert len(fake.calls) == len(pages)


def case_backfill_duplicate_bought_copy_wins() -> None:
    c = _login()
    item = {"message_id": 80, "media_ids": [904], "price_cents": 800}
    body = c.post("/admin/vault/sends/backfill", json={"account_id": ACC, "fan_id": 516, "items": [
        {**item, "was_purchased": False}, {**item, "was_purchased": True},
    ]}).json()
    assert body["inserted"] == 1
    assert body["history"]["by_media"]["904"]["was_purchased"] is True
    assert _rows(516)[(904, 80)][0] is True


def case_history_deduplicates_message_sends_and_payments() -> None:
    fan = 517
    send = {"account_id": ACC, "fan_id": fan, "media_id": 905, "message_id": 81, "price_cents": 800}
    _exec(insert(VaultSend).values([send, send, {**send, "media_id": 906},
                                   *[{**send, "media_id": 907, "message_id": None}] * 2]))
    _exec(insert(Transaction).values(account_id=ACC, fan_id=fan, message_id=81, kind="ppv",
                                     amount_cents=800, occurred_at=datetime(2026, 3, 4)))

    response = _login().get("/admin/vault/fan-history", params={"account_id": ACC, "fan_id": fan})
    assert response.status_code == 200, response.text
    history = response.json()["by_media"]
    for media in ("905", "906"):
        entry = history[media]
        assert (entry["total_paid_cents"], entry["send_count"], entry["was_purchased"]) == (800, 1, True)
    assert history["907"]["send_count"] == 2


_harness.run()
