#!/usr/bin/env python3
import _harness

_harness.bootstrap()

import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from db.engine import get_session  # noqa: E402
from db.models import Account, Chat, Fan, Message  # noqa: E402

GOLDEN = Path(__file__).with_name("test_seed_exact_ids.onlyfans.golden.jsonl")
T0 = datetime(2026, 6, 4, 12, 0, 0)
FANSLY_AID, FANSLY_FAN, FANSLY_MSG = "900539700124344320", 900539700124344321, 900539700124344400
SMALL_FAN, SMALL_MSG = 123456789, 987654321

client = _harness.make_client()


def _msg(aid: str, fan: int, mid: int, minute: int, direction: str = "in", **kw) -> Message:
    at = T0.replace(minute=minute)
    return Message(account_id=aid, fan_id=fan, message_id=mid, direction=direction, body=f"m{mid}",
                   created_at=at, ingested_at=at, **kw)


async def _seed_onlyfans() -> None:
    async with get_session() as s:
        s.add(Account(id="612"))
        s.add_all([Fan(account_id="612", fan_id=f, of_username=f"u{f}", of_display_name=f"Fan {f}", is_muted=m)
                   for f, m in ((903, True), (904, False))])
        s.add_all([Chat(account_id="612", fan_id=f, unread_count=f - 903, last_message_id=9500 + f,
                        last_message_preview=f"hi {f}", last_message_at=T0.replace(minute=f - 900))
                   for f in (903, 904, 905)])
        s.add_all([
            _msg("612", 903, 9401, 1),
            _msg("612", 903, 9402, 2, "out", price_cents=1500, is_paid=False),
            _msg("612", 903, 9403, 3),
            _msg("612", 903, 5_000_000_000_000_001, 4, "out"),
            _msg("612", 903, 6_000_000_000_000_001, 5, is_tip=True, price_cents=500),
        ])


async def _seed_fansly() -> None:
    async with get_session() as s:
        if await s.get(Account, FANSLY_AID):
            return
        s.add(Account(id=FANSLY_AID))
        s.add(Fan(account_id=FANSLY_AID, fan_id=FANSLY_FAN, of_username="nova_fan"))
        s.add_all([
            Chat(account_id=FANSLY_AID, fan_id=FANSLY_FAN, last_message_id=FANSLY_MSG + 2,
                 last_message_preview="latest", last_message_at=T0),
            Chat(account_id=FANSLY_AID, fan_id=SMALL_FAN, last_message_id=SMALL_MSG,
                 last_message_at=T0.replace(minute=1)),
        ])
        s.add_all([_msg(FANSLY_AID, FANSLY_FAN, FANSLY_MSG + i, i) for i in range(3)])
        s.add(_msg(FANSLY_AID, SMALL_FAN, SMALL_MSG, 1))


def _onlyfans_bytes() -> bytes:
    recent = client.get("/admin/chats/recent", params={"account_id": "612"})
    history = client.get("/admin/messages/612/903", params={"limit": 2})
    older = client.get("/admin/messages/612/903", params={"limit": 2, "before_id": 9403})
    for r in (recent, history, older):
        assert r.status_code == 200, (r.status_code, r.text)
    return recent.content + b"\n" + history.content + b"\n" + older.content + b"\n"


async def case_onlyfans_seed_and_history_bytes_unchanged():
    await _seed_onlyfans()
    got = _onlyfans_bytes()
    assert got == GOLDEN.read_bytes(), got.decode()


async def case_fansly_recent_seed_keeps_ids_exact():
    await _seed_fansly()
    body = json.loads(client.get("/admin/chats/recent", params={"account_id": FANSLY_AID}).content)
    rows = {str(r["withUser"]["id"]): r for r in body["list"]}
    big, small = rows[str(FANSLY_FAN)], rows[str(SMALL_FAN)]
    assert big["withUser"]["id"] == str(FANSLY_FAN), big
    assert big["lastMessage"]["id"] == str(FANSLY_MSG + 2), big
    assert small["withUser"]["id"] == SMALL_FAN, small
    assert small["lastMessage"]["id"] == SMALL_MSG, small


async def case_fansly_history_keeps_ids_and_cursor_exact():
    await _seed_fansly()
    page = json.loads(client.get(f"/admin/messages/{FANSLY_AID}/{FANSLY_FAN}", params={"limit": 2}).content)
    assert [m["message_id"] for m in page["messages"]] == [str(FANSLY_MSG + 2), str(FANSLY_MSG + 1)], page
    assert {m["fan_id"] for m in page["messages"]} == {str(FANSLY_FAN)}, page
    assert page["next_before_id"] == str(FANSLY_MSG + 1), page
    older = json.loads(client.get(f"/admin/messages/{FANSLY_AID}/{FANSLY_FAN}",
                                  params={"limit": 2, "before_id": page["next_before_id"]}).content)
    assert [m["message_id"] for m in older["messages"]] == [str(FANSLY_MSG)], older
    assert older["next_before_id"] is None, older
    small = json.loads(client.get(f"/admin/messages/{FANSLY_AID}/{SMALL_FAN}", params={"limit": 1}).content)
    assert small["messages"][0]["message_id"] == SMALL_MSG and small["messages"][0]["fan_id"] == SMALL_FAN, small
    assert small["next_before_id"] == SMALL_MSG, small


_harness.run()
