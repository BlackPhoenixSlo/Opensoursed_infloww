#!/usr/bin/env python3
"""/chats serve-time smart signals (`server._annotate_chat_rows`).

The Fan List paints "restricted", "needs human" and "auto-renew off" straight
off the chat rows, with no extra call, from data we already store (the
restricted stamp's own cases live in test_of_restrict.py):
  - needsHuman:   fans.customs_owed_at is set (a custom is owed);
  - autoRenewOff: the account's LAST roster crawl (subscriber_snapshot) listed
                  the fan with renew off and an expiry still ahead; a crawl
                  older than a day vouches for nothing.
Stamps go on a COPY (the cached window is shared), and with nothing to stamp
the exact same object comes back.

Run:  ./venv/bin/python service/tests/test_chat_signals.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete  # noqa: E402

import server  # noqa: E402
from automations._common import set_of_restricted_skip  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, SubscriberSnapshot  # noqa: E402

AID = "acct-signals"


def _page(*ids):
    return {"list": [{"withUser": {"id": i}, "unreadMessagesCount": 0} for i in ids], "hasMore": False}


async def _reset():
    async with get_session() as s:
        for aid in (AID, "other-acct"):
            if await s.get(Account, aid) is None:
                s.add(Account(id=aid))
        await s.execute(delete(Fan).where(Fan.account_id == AID))
        await s.execute(delete(SubscriberSnapshot).where(SubscriberSnapshot.account_id == AID))
        await s.commit()


async def _snapshot(rows, *, seen_at):
    async with get_session() as s:
        for fid, renew_on, expired_at in rows:
            s.add(SubscriberSnapshot(account_id=AID, fan_id=fid, renew_on=renew_on,
                                     expired_at=expired_at, seen_at=seen_at))
        await s.commit()


async def case_nothing_stored_returns_same_object():
    await _reset()
    page = _page(1, 2)
    assert await server._annotate_chat_rows(AID, page) is page
    assert await server._annotate_chat_rows(AID, {}) == {}


async def case_owed_custom_stamps_needs_human_on_a_copy():
    await _reset()
    async with get_session() as s:
        s.add(Fan(account_id=AID, fan_id=11, customs_owed_at=datetime.utcnow()))
        s.add(Fan(account_id=AID, fan_id=12))
        s.add(Fan(account_id="other-acct", fan_id=13, customs_owed_at=datetime.utcnow()))
        await s.commit()
    page = _page(11, 12, 13)
    out = await server._annotate_chat_rows(AID, page)
    assert out["list"][0]["withUser"].get("needsHuman") is True, out
    assert "needsHuman" not in out["list"][1]["withUser"], out
    assert "needsHuman" not in out["list"][2]["withUser"], "another account's ledger leaked"
    assert "needsHuman" not in page["list"][0]["withUser"], "annotation mutated the cached window"
    assert out["hasMore"] is False


async def case_last_crawl_renew_off_stamps_auto_renew_off():
    await _reset()
    now = datetime.utcnow()
    last, older = now - timedelta(minutes=5), now - timedelta(hours=3)
    await _snapshot([
        (21, False, now + timedelta(days=3)),   # renew off, still subscribed → stamped
        (22, True, now + timedelta(days=3)),    # renew on
        (23, False, now - timedelta(hours=1)),  # already lapsed: expired, not "off"
        (24, False, None),                      # no expiry known: still listed active
    ], seen_at=last)
    await _snapshot([(25, False, now + timedelta(days=3))], seen_at=older)  # gone since
    out = await server._annotate_chat_rows(AID, _page(21, 22, 23, 24, 25))
    stamped = [r["withUser"]["id"] for r in out["list"] if r["withUser"].get("autoRenewOff")]
    assert stamped == [21, 24], stamped


async def case_stale_crawl_vouches_for_nothing():
    await _reset()
    now = datetime.utcnow()
    await _snapshot([(31, False, now + timedelta(days=3))], seen_at=now - timedelta(days=2))
    page = _page(31)
    assert await server._annotate_chat_rows(AID, page) is page


async def case_non_numeric_ids_are_skipped():
    await _reset()
    async with get_session() as s:
        s.add(Fan(account_id=AID, fan_id=41, customs_owed_at=datetime.utcnow()))
        await s.commit()
    page = {"list": [{"withUser": {"id": "abc"}}, {"withUser": {}}, {"withUser": {"id": "41"}}]}
    out = await server._annotate_chat_rows(AID, page)
    assert [bool(r["withUser"].get("needsHuman")) for r in out["list"]] == [False, False, True], out


async def case_chats_key_and_every_signal_in_one_copy():
    """A page under "chats" (not "list") is stamped too, and a fan carrying all
    three signals gets them on ONE copied row."""
    await _reset()
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Fan(account_id=AID, fan_id=51, customs_owed_at=now))
        await s.commit()
    await _snapshot([(51, False, now + timedelta(days=3))], seen_at=now - timedelta(minutes=1))
    await set_of_restricted_skip(AID, 51, True)
    try:
        page = {"chats": [{"withUser": {"id": 51}}, {"withUser": {"id": 52}}], "hasMore": True}
        out = await server._annotate_chat_rows(AID, page)
        assert out["chats"][0]["withUser"] == {
            "id": 51, "isRestricted": True, "needsHuman": True, "autoRenewOff": True}, out
        assert out["chats"][1] is page["chats"][1], "an unstamped row is passed through, not copied"
        assert page["chats"][0]["withUser"] == {"id": 51}, "annotation mutated the cached window"
        assert out["hasMore"] is True
    finally:
        await set_of_restricted_skip(AID, 51, False)


_harness.run(
    case_nothing_stored_returns_same_object,
    case_owed_custom_stamps_needs_human_on_a_copy,
    case_last_crawl_renew_off_stamps_auto_renew_off,
    case_stale_crawl_vouches_for_nothing,
    case_non_numeric_ids_are_skipped,
    case_chats_key_and_every_signal_in_one_copy,
)
