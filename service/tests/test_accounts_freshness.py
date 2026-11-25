#!/usr/bin/env python3
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))  # noqa: E401,E702
import _harness  # noqa: E402  (first: temp DB)

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import importlib  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import accounts as account_registry  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Chatter, ChatterUser, User, UserAccount  # noqa: E402

_harness.make_client()
import server  # noqa: E402
import shared_refresher  # noqa: E402

A, B, W = "acc_fr_a", "acc_fr_b", "acc_fr_watch"
_CREATORS = (A, B)

account_registry.get_account = lambda aid: {"id": aid} if aid in (*_CREATORS, W) else None
account_registry.list_accounts = lambda include_watchers=False: [{"id": a, "has_session": True} for a in _CREATORS] + (
    [{"id": W, "has_session": True, "role": account_registry.ROLE_WATCHER}] if include_watchers else [])
account_registry.is_account = lambda aid: aid in (*_CREATORS, W)
account_registry.get_role = lambda aid: account_registry.ROLE_WATCHER if aid == W else None
account_registry.get_active_account_id = lambda: A


def _no_of(*_a, **_k):
    raise AssertionError("an accounts list made an OF call")


server._load_client = _no_of


async def _setup() -> None:
    async with get_session() as s:
        boss = User(id=uuid.uuid4().hex, username="boss", password="pw")
        s.add(boss)
        s.add_all([Account(id=a, nickname=a) for a in (*_CREATORS, W)])
        cid = uuid.uuid4().hex
        s.add(Chatter(id=cid, username="chat", password="pw", display_name="Chat",
                      created_at=datetime.utcnow(), last_seen_at=datetime.utcnow()))
        await s.flush()
        s.add_all([UserAccount(user_id=boss.id, account_id=a) for a in (*_CREATORS, W)])
        s.add(ChatterUser(chatter_id=cid, user_id=boss.id, created_at=datetime.utcnow()))


asyncio.run(_setup())


def _login(path: str, username: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post(path, json={"username": username, "password": "pw"})
    assert r.status_code == 200, f"{username} login failed: {r.status_code} {r.text}"
    return c


@contextlib.contextmanager
def _knob(on: bool):
    env = os.environ.get("SHARED_REFRESHER")
    if on:
        os.environ["SHARED_REFRESHER"] = "1"
    else:
        os.environ.pop("SHARED_REFRESHER", None)
    mod = importlib.reload(shared_refresher)
    try:
        yield mod
    finally:
        if env is None:
            os.environ.pop("SHARED_REFRESHER", None)
        else:
            os.environ["SHARED_REFRESHER"] = env
        importlib.reload(shared_refresher)


def _owner_rows() -> tuple[dict, dict]:
    body = _login("/auth/login", "boss").get("/admin/accounts").json()
    return {a["id"]: a for a in body["accounts"]}, {w["id"]: w for w in body["watchers"]}


def _chatter_rows() -> dict:
    r = _login("/chatter/login", "chat").get("/chatter/me/accounts")
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return {a["account_id"]: a for a in r.json()}


def _assert_snapshot_rows(rows: dict, mod, t0: int, t1: int, where: str) -> None:
    assert set(rows) == set(_CREATORS), (where, sorted(rows))
    for aid, row in rows.items():
        f = row.get("freshness")
        assert isinstance(f, dict), (where, aid, row)
        assert set(f) == {"account_id", "boot", "seq", "now", "at", "cycle_s", "live", "live_since", "values"}, \
            (where, f)
        assert f["account_id"] == aid and f["boot"] == mod.BOOT_MS and f["seq"] == 0, (where, f)
        assert t0 <= f["now"] <= t1, (where, "now: the Relay clock at send time", f["now"], t0, t1)
        assert f["cycle_s"] is None, (where, "not tracked: cycle_s null", f)
        want = {k: v for k, v in mod.snapshot(aid).items() if k != "now"}
        assert {k: v for k, v in f.items() if k != "now"} == want, (where, f, want)


def case_owner_rows_carry_freshness_when_on():
    with _knob(True) as mod:
        assert mod.ENABLED
        t0 = int(time.time() * 1000)
        rows, watchers = _owner_rows()
        t1 = int(time.time() * 1000)
        _assert_snapshot_rows(rows, mod, t0, t1, "owner")
        assert "freshness" not in watchers[W], ("a watcher is never tracked", watchers[W])


def case_chatter_rows_carry_freshness_when_on():
    with _knob(True) as mod:
        t0 = int(time.time() * 1000)
        rows = _chatter_rows()
        t1 = int(time.time() * 1000)
        watcher = rows.pop(W)
        _assert_snapshot_rows(rows, mod, t0, t1, "chatter")
        assert "freshness" not in watcher, ("a watcher is never tracked", watcher)


def case_rows_carry_a_published_seq():
    with _knob(True) as mod:
        mod._seq[A] = 3
        mod._at_ms[A] = 1_700_000_000_000
        owner, _ = _owner_rows()
        chatter = _chatter_rows()
        for where, row in (("owner", owner[A]), ("chatter", chatter[A])):
            assert (row["freshness"]["seq"], row["freshness"]["at"]) == (3, 1_700_000_000_000), (where, row)


def case_no_field_when_off():
    with _knob(False) as mod:
        assert not mod.ENABLED
        rows, watchers = _owner_rows()
        chatter = _chatter_rows()
        assert set(rows) == set(_CREATORS) and set(chatter) == {*_CREATORS, W}, (sorted(rows), sorted(chatter))
        for where, row in [*(("owner", r) for r in rows.values()), *(("watcher", w) for w in watchers.values()),
                           *(("chatter", r) for r in chatter.values())]:
            assert "freshness" not in row, (where, row)


if __name__ == "__main__":
    _harness.run()
