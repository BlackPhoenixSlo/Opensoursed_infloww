#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, Chat, Chatter, ChatterUser, Fan, User, UserAccount, UserSetting,
)
import split_inbox  # noqa: E402

client = _harness.make_client()
import server  # noqa: E402
from _pre_enforcement import seed_pre_enforcement_install  # noqa: E402

MUTANT = os.environ.get("STALL_MUTANT") == "1"
PW = "secretpw"
NOW = datetime.utcnow().replace(microsecond=0)

F_OWNER, F1, F2 = "owner_stall_filter", "acct_stall_f1", "acct_stall_f2"
BOUND, FREE = "chatter_stall_bound", "chatter_stall_free"
F1_IN = [2002, 2004, 1001]
F1_OUT = [3001, 3003, 3005, 3007, 2000]
F2_IN = [4001, 4003, 4005]
F2_OUT = [4002, 4004, 4006, 4008, 4010]

S_OWNER = "owner_stall_herd"
MODELS, CHATS, HERD, LIMIT = 200, 300, 100, 100
HERD_CPU_S = 1.5


async def _seed_filter_world() -> None:
    async with get_session() as s:
        s.add(User(id=F_OWNER, username="stallfilterowner", password=PW))
        for aid in (F1, F2):
            s.add(Account(id=aid, nickname=aid, color="#aaaaaa"))
            s.add(UserAccount(user_id=F_OWNER, account_id=aid))
        for cid in (BOUND, FREE):
            s.add(Chatter(id=cid, username=cid, password=PW, display_name=cid, created_at=NOW, last_seen_at=NOW))
    async with get_session() as s:
        for cid in (BOUND, FREE):
            s.add(ChatterUser(chatter_id=cid, user_id=F_OWNER, created_at=NOW))
        s.add(AccountAiConfig(account_id=F1, split_inbox_json=json.dumps(
            {"group_count": 2, "assignments": {"1001": 1, "2000": 2}, "chatter_groups": {BOUND: 1}})))
        s.add(UserSetting(user_id=F_OWNER, tab=split_inbox.DEFAULT_TAB, config_json=json.dumps(
            {"group_count": 2, "assignments": {}, "chatter_groups": {BOUND: 2}})))
        for aid, older, newer in ((F1, F1_IN, F1_OUT), (F2, F2_IN, F2_OUT)):
            for i, fid in enumerate(older):
                s.add(Chat(account_id=aid, fan_id=fid, last_message_id=fid, last_message_at=NOW - timedelta(days=2, seconds=i)))
            for i, fid in enumerate(newer):
                s.add(Chat(account_id=aid, fan_id=fid, last_message_id=fid, last_message_at=NOW - timedelta(seconds=i)))


async def _seed_herd_world() -> None:
    rng = random.Random(15)
    async with get_session() as s:
        s.add(User(id=S_OWNER, username="stallherdowner", password=PW))
        for m in range(MODELS):
            s.add(Account(id=f"acct_herd_{m:03d}", nickname=f"herd {m}", color="#aaaaaa"))
            s.add(UserAccount(user_id=S_OWNER, account_id=f"acct_herd_{m:03d}"))
        for c in range(HERD):
            s.add(Chatter(id=f"herd{c:03d}", username=f"herd{c:03d}", password=PW, display_name=f"herd {c}",
                          created_at=NOW, last_seen_at=NOW))
    async with get_session() as s:
        for c in range(HERD):
            s.add(ChatterUser(chatter_id=f"herd{c:03d}", user_id=S_OWNER, created_at=NOW))
        s.add(UserSetting(user_id=S_OWNER, tab=split_inbox.DEFAULT_TAB, config_json=json.dumps(
            {"group_count": 2, "assignments": {}, "chatter_groups": {f"herd{c:03d}": c % 2 + 1 for c in range(HERD // 2)}})))
        fans, chats = [], []
        for m in range(MODELS):
            aid = f"acct_herd_{m:03d}"
            for f in range(CHATS):
                fid = 10_000 + m * 100_000 + f
                fans.append({"account_id": aid, "fan_id": fid, "of_username": f"u{fid}", "of_display_name": f"Fan {fid}"})
                chats.append({"account_id": aid, "fan_id": fid, "last_message_id": fid, "last_message_preview": "hey",
                              "last_message_at": NOW - timedelta(seconds=rng.randint(0, 10 ** 6)), "unread_count": f % 3})
        await s.execute(insert(Fan), fans)
        await s.execute(insert(Chat), chats)
    await seed_pre_enforcement_install()


asyncio.run(_seed_filter_world())
asyncio.run(_seed_herd_world())


def _login(kind: str, name: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post("/auth/login" if kind == "owner" else "/chatter/login", json={"username": name, "password": PW})
    assert r.status_code == 200, (name, r.status_code, r.text)
    return c


def _fans(c: TestClient, limit: int, account_id: str | None = None) -> list[int]:
    q = f"/admin/chats/recent?limit={limit}" + (f"&account_id={account_id}" if account_id else "")
    r = c.get(q)
    assert r.status_code == 200, (q, r.status_code, r.text)
    return [row["withUser"]["id"] for row in r.json()["list"]]


def case_explicit_moves_filter_before_the_limit():
    got = _fans(_login("chatter", BOUND), 3, F1)
    assert sorted(got) == sorted(F1_IN), ("newer group-2 chats must not hide older group-1 ones", got)
    assert 1001 in got and 2000 not in got, "moved in shows, moved out does not"


def case_inherited_default_filters_before_the_limit():
    got = _fans(_login("chatter", BOUND), 3, F2)
    assert sorted(got) == sorted(F2_IN), ("the owner's default binds this Creator too", got)


def case_all_scope_fills_the_limit_from_every_creator():
    got = _fans(_login("chatter", BOUND), len(F1_IN) + len(F2_IN))
    assert sorted(got) == sorted(F1_IN + F2_IN), got


def case_unbound_chatter_and_owner_see_the_newest():
    for c in (_login("chatter", FREE), _login("owner", "stallfilterowner")):
        assert _fans(c, 3, F1) == F1_OUT[:3]
        assert _fans(c, 3, F2) == F2_OUT[:3]


def case_response_shape_is_unchanged():
    r = _login("owner", "stallfilterowner").get(f"/admin/chats/recent?limit=1&account_id={F1}")
    assert r.json() == {"list": [{
        "__accountId": F1,
        "withUser": {"id": 3001, "name": None, "username": None, "avatar": None},
        "lastMessage": {"id": 3001, "text": "", "createdAt": NOW.isoformat() + "Z"},
        "hasUnread": False, "unreadMessagesCount": 0, "isMutedNotifications": False,
    }], "source": "local-db"}, r.json()


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cpu_s(pid: int) -> float:
    raw = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    secs = 0.0
    for part in raw.split(":"):
        secs = secs * 60 + float(part)
    return secs


class _CpuSampler(threading.Thread):
    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid, self.deltas, self.stop = pid, [], threading.Event()

    def run(self) -> None:
        last, at = _cpu_s(self.pid), time.monotonic()
        while not self.stop.wait(1.0):
            cpu, now = _cpu_s(self.pid), time.monotonic()
            self.deltas.append((cpu - last) / (now - at))
            last, at = cpu, now


async def _herd(base: str, pid: int) -> tuple[list[float], float]:
    clients = [httpx.AsyncClient(base_url=base, timeout=120, limits=httpx.Limits(max_keepalive_connections=0))
               for _ in range(HERD)]
    try:
        for i in range(0, HERD, 10):
            rs = await asyncio.gather(*(clients[c].post("/chatter/login", json={"username": f"herd{c:03d}", "password": PW})
                                        for c in range(i, min(i + 10, HERD))))
            assert all(r.status_code == 200 for r in rs), [r.text for r in rs if r.status_code != 200][:1]

        async def one(c: httpx.AsyncClient) -> float:
            t = time.perf_counter()
            r = await c.get(f"/admin/chats/recent?limit={LIMIT}")
            assert r.status_code == 200 and r.json()["list"], (r.status_code, r.text[:200])
            return time.perf_counter() - t
        cpu = _cpu_s(pid)
        ds = sorted(await asyncio.gather(*(one(c) for c in clients)))
        return ds, _cpu_s(pid) - cpu
    finally:
        await asyncio.gather(*(c.aclose() for c in clients))


def case_hundred_all_loads_do_not_stall_the_relay():
    port = _port()
    env = {k: v for k, v in os.environ.items() if k != "CHATTERLY_DB_NULLPOOL"}
    cmd = [sys.executable, str(Path(__file__).with_name("_stall_relay.py")), str(port)] + (["--mutant"] if MUTANT else [])
    proc = subprocess.Popen(cmd, cwd=str(_harness._SERVICE), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120
        while True:
            assert proc.poll() is None, f"relay exited {proc.returncode}"
            try:
                if httpx.get(base + "/livez", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic() < deadline, "relay never answered /livez"
            time.sleep(0.2)
        rounds = []
        for _ in range(2):
            sampler = _CpuSampler(proc.pid)
            sampler.start()
            ds, cpu = asyncio.run(_herd(base, proc.pid))
            time.sleep(1.5)
            sampler.stop.set()
            sampler.join()
            p95, mx = ds[int(len(ds) * 0.95) - 1], ds[-1]
            rounds.append(cpu)
            print(f"    herd {len(ds)} x limit {LIMIT} on {MODELS} Creators: p95 {p95:.2f}s max {mx:.2f}s "
                  f"relay cpu {cpu:.2f}s, per s {[round(d, 2) for d in sampler.deltas]}{' (MUTANT)' if MUTANT else ''}")
        bad = min(rounds) > HERD_CPU_S
        if MUTANT:
            if bad:
                print("STALL_MUTANT_RED")
            else:
                print("STALL_MUTANT_SURVIVED")
        assert not bad, f"stall: best herd of {rounds} relay CPU seconds exceeded {HERD_CPU_S}s"
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    _harness.run()
