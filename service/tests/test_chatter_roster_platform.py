#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402

_harness.bootstrap()

import asyncio  # noqa: E402
import tempfile  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chatter, ChatterUser, User, UserAccount  # noqa: E402

_TMP = tempfile.TemporaryDirectory(prefix="chatter_roster_platform_")
account_registry.SESSIONS_DIR = Path(_TMP.name)
account_registry.ACCOUNTS_DIR = Path(_TMP.name) / "accounts"
account_registry.ACTIVE_FILE = Path(_TMP.name) / "active.json"
account_registry.MIGRATED_MARKER = Path(_TMP.name) / ".migrated"

_harness.make_client()
import server  # noqa: E402

FANSLY, LEGACY = "900539700124344320", "312110001"

account_registry.save_meta(FANSLY, {"id": FANSLY, "nickname": "Nova", "platform": "fansly"})
account_registry.save_meta(LEGACY, {"id": LEGACY, "nickname": "Ava"})


async def _setup() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        s.add(boss)
        s.add_all([Account(id=a, nickname=a) for a in (FANSLY, LEGACY)])
        cid = uuid.uuid4().hex
        s.add(Chatter(id=cid, username="chat", password="pw", display_name="Chat",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=a) for a in (FANSLY, LEGACY)])
        s.add(ChatterUser(chatter_id=cid, user_id=boss.id, created_at=datetime.utcnow()))


asyncio.run(_setup())


def case_chatter_roster_carries_each_creators_platform():
    c = TestClient(server.app)
    r = c.post("/chatter/login", json={"username": "chat", "password": "pw"})
    assert r.status_code == 200, (r.status_code, r.text)
    r = c.get("/chatter/me/accounts")
    assert r.status_code == 200, (r.status_code, r.text[:200])
    got = {a["account_id"]: a.get("platform") for a in r.json()}
    assert got == {FANSLY: "fansly", LEGACY: "onlyfans"}, got


if __name__ == "__main__":
    _harness.run()
