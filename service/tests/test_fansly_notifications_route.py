#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import sys  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))
from stateful_fake import StatefulFansly  # noqa: E402

http = _harness.make_client()

_AID = "8803911"
server._resolve_account_id = lambda _req=None: _AID  # type: ignore[assignment]


async def _owner() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="notif_route_boss", password="pw")
        s.add_all([boss, Account(id=_AID, nickname=_AID)])
        await s.flush()
        s.add(UserAccount(user_id=boss.id, account_id=_AID))

asyncio.run(_owner())
assert http.post("/auth/login", json={"username": "notif_route_boss", "password": "pw"}).status_code == 200


def _feed(**params) -> dict:
    fake = StatefulFansly()
    fan = fake.notifications[0]["correlationGroupId"]
    for nid, code in (("900000000000000804", 15016), ("900000000000000803", 3003), ("900000000000000802", 15016)):
        fake.notifications.insert(0, {"id": nid, "accountId": fake.account_id, "type": code, "correlationId": nid,
                                      "correlationGroupId": fan, "acknowledgedAt": 0, "createdAt": 1767225660,
                                      "metadata": None})
    with patch.object(server, "_get_client", return_value=fake.client()):
        r = http.get("/api/of/v2/users/notifications", params={**params, "refresh": "true"},
                     headers={"X-Account-Id": _AID})
    assert r.status_code == 200, r.text
    return r.json()


def case_a_follow_arrives_as_followed():
    got = _feed(limit=10)
    assert [n["type"] for n in got["list"]] == ["subscribed", "followed", "subscribed", "purchases"], got
    assert [n["type"] for n in _feed(limit=10, type="followed")["list"]] == ["followed"]


def case_a_filtered_page_ends_paging_at_the_last_filtered_row():
    pages = [_feed(limit=1, offset=n, type="subscribed") for n in range(3)]
    assert [([x["id"] for x in p["list"]], p["hasMore"]) for p in pages] == [
        (["900000000000000802"], True), (["900000000000000804"], False), ([], False)], pages


_harness.run()
