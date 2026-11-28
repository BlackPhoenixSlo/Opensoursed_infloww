#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fansly"))

_harness.make_client()

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
import events  # noqa: E402
import events_decide as ed  # noqa: E402
import server  # noqa: E402
import split_inbox  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
from fansly_ws import FanslyWebSocket  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="fansly_unsend_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

AID = "700237824869654528"
OF_AID = "9999003"
FAN = "500251712226222081"
OTHER_FAN = "500251712226222082"
OF_FAN = "354841559"
MID = "900544249226047511"
GRANTED, DENIED = "chatter-granted", "chatter-denied"
SPLIT = {"group_count": 2, "assignments": {}, "chatter_groups": {GRANTED: 2, DENIED: 1}}

UNSEND = {"type": 10, "message": {
    "type": 1, "senderId": FAN, "groupId": "900544249083420672", "id": MID,
    "attachments": [], "inReplyTo": "", "interactions": [],
    "createdAt": 1788288661, "deletedAt": 1788288700, "embeds": [], "content": "take it back"}}


async def _seed_owner() -> None:
    async with get_session() as s:
        s.add(User(id="owner-unsend", username="unsendowner", password="pw"))
        for aid in (AID, OF_AID):
            s.add(Account(id=aid, nickname=aid))
            s.add(UserAccount(user_id="owner-unsend", account_id=aid))


asyncio.run(_seed_owner())
client = TestClient(server.app)


class _ShimFake:
    account_id = AID
    user_id = None
    _group_to_fan: dict = {}

    def __init__(self):
        self.calls: list[tuple] = []

    def get_messages(self, chat_id, *, limit, order, before_id=None, peek=False):
        self.calls.append((str(chat_id), before_id))
        return {"list": [{"id": (before_id or 10**18) - 1, "text": "x"}], "hasMore": True}


def _wire(service_id: int, event: dict) -> dict:
    return {"t": 10000, "d": json.dumps({"serviceId": service_id, "event": json.dumps(event)})}


def _seed(aid: str, platform: str | None) -> None:
    meta = {"id": aid, "nickname": aid}
    if platform:
        meta["platform"] = platform
    account_registry.save_meta(aid, meta)


def _get(fake: _ShimFake, aid: str, fan: str, before_id: int | None = None) -> None:
    url = f"/api/of/v2/chats/{fan}/messages?limit=20&order=desc"
    if before_id is not None:
        url += f"&before_id={before_id}"
    with patch.object(server, "_get_client", lambda *_a: fake):
        r = client.get(url, headers={"x-account-id": aid})
    assert r.status_code == 200, (r.status_code, r.text)


def _drain(q: asyncio.Queue) -> list:
    out = []
    while not q.empty():
        item = q.get_nowait()
        out.extend(item if isinstance(item, list) else [item])
    return out


async def _through_relay(aid: str, event: dict, chatters: tuple) -> tuple:
    subs = [events._register("all", frozenset({aid}), frozenset(), False, None, who) for who in chatters]
    try:
        await server._broadcast_event({"__account_id": aid, "__account_name": "t", **event})
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        await asyncio.gather(*pending, return_exceptions=True)
        return tuple(_drain(s.q) for s in subs)
    finally:
        for s in subs:
            await events.unsubscribe("all", s.q)


def case_unsend_reaches_only_granted_chatter_and_history_refetches():
    assert split_inbox.group_of(FAN, SPLIT) == 2 and split_inbox.group_of(OTHER_FAN, SPLIT) == 1
    _seed(AID, "fansly")
    split_inbox.remember(AID, SPLIT)
    fake = _ShimFake()
    pages = [(FAN, 900544249226047600), (FAN, 900544249226040000), (OTHER_FAN, 900544249226047600)]
    try:
        _get(fake, AID, FAN)
        for fan, before in pages:
            _get(fake, AID, fan, before)
            _get(fake, AID, fan, before)
        assert fake.calls == [(FAN, None)] + [(f, b) for f, b in pages], \
            ("head page always fetched, history pages served from cache on repeat", fake.calls)

        event = FanslyWebSocket(_ShimFake())._translate(_wire(5, UNSEND))
        granted, denied, owner = asyncio.run(_through_relay(AID, event, (GRANTED, DENIED, None)))

        expected = {"chat_message_deleted": {"id": MID, "fan_id": FAN}, "__account_id": AID}
        assert [{k: f[k] for k in expected} for f in granted] == [expected], granted
        assert denied == [], denied
        assert len(owner) == 1, owner

        fake.calls.clear()
        for fan, before in pages:
            _get(fake, AID, fan, before)
        assert fake.calls == [(f, b) for f, b in pages[:2]], \
            ("both of that fan's history pages re-fetch, the other fan's stays cached", fake.calls)
    finally:
        split_inbox.remember(AID, split_inbox.unset())


def case_onlyfans_message_unchanged_and_keeps_history_cache():
    _seed(OF_AID, None)
    fake = _ShimFake()
    _get(fake, OF_AID, OF_FAN, 50)
    (got,) = asyncio.run(_through_relay(OF_AID, {"api2_chat_message": {
        "id": 10001090338391, "text": "hi", "fromUser": {"id": int(OF_FAN)},
        "createdAt": "2026-06-13T03:30:28+00:00"}}, (None,)))
    assert [ed.first_key(f) for f in got] == ["api2_chat_message"], got
    _get(fake, OF_AID, OF_FAN, 50)
    assert fake.calls == [(OF_FAN, 50)], ("OnlyFans history page still cached", fake.calls)


if __name__ == "__main__":
    with client:
        assert client.post("/auth/login", json={"username": "unsendowner", "password": "pw"}).status_code == 200
        _harness.run()
