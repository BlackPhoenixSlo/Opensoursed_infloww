#!/usr/bin/env python3
import _harness  # noqa: F401 — MUST be first (binds a throwaway temp DB)

import asyncio  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import admission  # noqa: E402
import httpx  # noqa: E402
import proxies as proxy_registry  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, User, UserAccount  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from of_client import OFAPIError  # noqa: E402

proxy_registry.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="health_all_proxies_")) / "proxies.json"



class _FakeClient:

    def __init__(self, aid: str, me_fn):
        self.account_id = aid
        self.proxy_label = f"proxy-{aid}"
        self.proxy_url = f"http://proxy/{aid}"
        self._me_fn = me_fn

    def me(self) -> dict[str, Any]:
        return self._me_fn(self.account_id)


@contextmanager
def _fleet(accounts: list[dict], *, me_fn=None, load_fn=None,
           concurrency: int | None = None, budget_s: float | None = None):
    old_list = server.account_registry.list_accounts
    old_load = server._load_client
    old_conc = admission.HEALTH_PROBE.cap
    old_budget = server._HEALTH_PROBE_BUDGET_S
    server.account_registry.list_accounts = lambda *a, **k: list(accounts)
    if load_fn is not None:
        server._load_client = load_fn
    elif me_fn is not None:
        server._load_client = lambda aid: _FakeClient(aid, me_fn)
    if concurrency is not None:
        admission.HEALTH_PROBE.cap = concurrency
    if budget_s is not None:
        server._HEALTH_PROBE_BUDGET_S = budget_s
    server.relay_coalesce.reset_for_tests()
    try:
        yield
    finally:
        server.account_registry.list_accounts = old_list
        server._load_client = old_load
        admission.HEALTH_PROBE.cap = old_conc
        server._HEALTH_PROBE_BUDGET_S = old_budget
        server.relay_coalesce.reset_for_tests()


def _accts(n: int, *, has_session: bool = True) -> list[dict]:
    return [{"id": f"acct{i}", "nickname": f"model{i}", "color": "#fff",
             "has_session": has_session} for i in range(n)]


def _rows(resp: dict) -> dict[str, dict]:
    return {r["account_id"]: r for r in resp["accounts"]}


FLEET_OWNER = "health_fleet_owner"
SUBSET_OWNER = "health_subset_owner"
OWNER = None
SUBSET = None


def _sign_in_fleet_owners(n: int = 8):
    fx.seed_two_agencies()

    async def _seed() -> None:
        async with get_session() as s:
            for name in (FLEET_OWNER, SUBSET_OWNER):
                s.add(User(id=name, username=name, password=fx.PASSWORD))
            for i in range(n):
                s.add(Account(id=f"acct{i}", nickname=f"model{i}", color="#fff"))
        async with get_session() as s:
            for i in range(n):
                s.add(UserAccount(user_id=FLEET_OWNER, account_id=f"acct{i}"))
            s.add(UserAccount(user_id=SUBSET_OWNER, account_id="acct0"))

    asyncio.run(_seed())
    return fx.login_owner(FLEET_OWNER), fx.login_owner(SUBSET_OWNER)



async def case_the_fanout_is_bounded_not_unbounded() -> None:
    lock = threading.Lock()
    live = 0
    peak = 0

    def probe(aid: str) -> dict[str, Any]:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return {"ok": True, "name": f"name-{aid}"}

    with _fleet(_accts(8), concurrency=3):
        old = server._probe_account_blocking
        server._probe_account_blocking = probe
        try:
            resp = await server._health_all_accounts()
        finally:
            server._probe_account_blocking = old

    assert peak <= 3, f"peak in-flight probes was {peak}, cap is 3"
    assert peak > 1, f"peak was {peak} — the probes never actually overlapped"
    rows = _rows(resp)
    assert len(rows) == 8 and resp["ok"] is True, resp
    for i in range(8):
        assert rows[f"acct{i}"]["name"] == f"name-acct{i}", rows[f"acct{i}"]


async def case_every_failure_shape_lands_on_its_own_row() -> None:
    def load(aid: str):
        if aid == "acct1":
            raise HTTPException(status_code=503, detail={"error": "no_session_yet",
                                                         "account_id": aid})
        return _FakeClient(aid, _me)

    class _Resp:
        status_code = 401
        text = "unauthorized-body"

    def _me(aid: str) -> dict[str, Any]:
        if aid == "acct0":
            time.sleep(0.15)
            return {"id": 111, "name": "Ava"}
        if aid == "acct2":
            raise OFAPIError("401 from OF", response=_Resp())
        raise ValueError("kaboom")

    with _fleet(_accts(4), load_fn=load, concurrency=4):
        rows = _rows(await server._health_all_accounts())

    assert rows["acct0"] == {**rows["acct0"], "ok": True, "user_id": 111, "name": "Ava"}, rows["acct0"]
    assert rows["acct0"]["proxy"] == {"label": "proxy-acct0", "url": "http://proxy/acct0"}
    assert rows["acct1"]["ok"] is False and rows["acct1"]["error"] == "no_session_yet", rows["acct1"]
    assert rows["acct2"]["error"] == "upstream" and rows["acct2"]["upstream_status"] == 401, rows["acct2"]
    assert rows["acct2"]["upstream_body"] == "unauthorized-body", rows["acct2"]
    assert rows["acct3"]["error"] == "ValueError: kaboom", rows["acct3"]


def case_health_reuses_only_its_own_small_identity_projection() -> None:
    calls = []
    def me(aid):
        calls.append(aid)
        return {"id": 123, "name": "Ava", "avatar": "https://cdn/avatar.jpg",
                "avatarThumbs": {"c50": "https://cdn/small.jpg"}, "private": "not exported"}
    with _fleet([], me_fn=me):
        row = server._probe_account_blocking("123")
        assert row["profile"] == {"id": 123, "avatar": "https://cdn/avatar.jpg",
                                  "avatarThumbs": {"c50": "https://cdn/small.jpg"}}, row
        assert row["ok"] and row["user_id"] == 123 and row["name"] == "Ava", row
        other = server._probe_account_blocking("456")
        assert other["ok"] and other["user_id"] == 123 and "profile" not in other, other
    assert calls == ["123", "456"], calls
    for reply, expected in [({"id": "123"}, {"id": "123", "avatar": None, "avatarThumbs": None}),
                            ({"avatar": "wrong"}, None), ({"id": None}, None)]:
        with _fleet([], me_fn=lambda aid: reply):
            row = server._probe_account_blocking("123")
            assert row.get("profile") == expected, row
            assert row["ok"], row


async def case_health_profiles_remain_inside_the_ownership_clamp() -> None:
    with _fleet(_accts(2), me_fn=lambda aid: {"id": aid, "avatar": f"https://cdn/{aid}.jpg"}):
        snapshot = await server._health_all_accounts()
    own = server._clamp_health_all(snapshot, frozenset({"acct0"}))
    assert len(own["accounts"]) == 1, own
    assert own["accounts"][0]["profile"]["id"] == "acct0", own
    assert own["accounts"][0]["profile"]["avatar"] == "https://cdn/acct0.jpg", own
    assert len(snapshot["accounts"]) == 2, snapshot
    assert server._clamp_health_all(snapshot, frozenset())["accounts"] == []


async def case_a_timeout_does_not_cancel_the_probe() -> None:
    finished = threading.Event()

    def probe(aid: str) -> dict[str, Any]:
        if aid == "acct1":
            time.sleep(0.5)
            finished.set()
        return {"ok": True, "name": f"name-{aid}"}

    with _fleet(_accts(2), concurrency=2, budget_s=0.15):
        old = server._probe_account_blocking
        server._probe_account_blocking = probe
        try:
            rows = _rows(await server._health_all_accounts())
            assert rows["acct0"]["ok"] is True, rows["acct0"]
            assert rows["acct1"]["ok"] is False, rows["acct1"]
            assert rows["acct1"]["error"] == "timeout", rows["acct1"]
            assert rows["acct1"]["timed_out"] is True, rows["acct1"]
            assert not finished.is_set(), "the slow probe finished before the budget — bad fixture"
            assert len(server._health_probes_running) == 1, server._health_probes_running
            await asyncio.sleep(0.6)
            assert finished.is_set(), "the abandoned probe was cancelled, not left to finish"
            assert not server._health_probes_running, "the done-callback never unparked it"
        finally:
            server._probe_account_blocking = old


async def case_a_timeout_does_not_hand_its_slot_to_the_next_probe() -> None:
    starts: dict[str, float] = {}
    ends: dict[str, float] = {}

    def probe(aid: str) -> dict[str, Any]:
        starts[aid] = time.monotonic()
        time.sleep(0.3)
        ends[aid] = time.monotonic()
        return {"ok": True, "name": f"name-{aid}"}

    with _fleet(_accts(2), concurrency=1, budget_s=0.15):
        old = server._probe_account_blocking
        server._probe_account_blocking = probe
        try:
            rows = _rows(await server._health_all_accounts())
            assert rows["acct0"]["timed_out"] is True, rows["acct0"]
            assert rows["acct1"]["timed_out"] is True, rows["acct1"]
            assert not all(r.get("ok") for r in rows.values()), rows
            await asyncio.sleep(0.9)
            assert set(ends) == {"acct0", "acct1"}, ends
            assert starts["acct1"] >= ends["acct0"], (
                "probe 2 started at %.3f but probe 1 only finished at %.3f — the "
                "timeout freed a slot the OF call still held"
                % (starts["acct1"], ends["acct0"]))
        finally:
            server._probe_account_blocking = old
            server._health_probes_running.clear()



async def case_the_uis_retry_joins_the_inflight_probe() -> None:
    calls: list[str] = []

    def probe(aid: str) -> dict[str, Any]:
        calls.append(aid)
        time.sleep(0.05)
        return {"ok": True, "name": f"name-{aid}"}

    def client(signed_in) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                 base_url="http://testserver", cookies=dict(signed_in.cookies))

    async def get(http: httpx.AsyncClient) -> dict:
        r = await http.get("/health?all_accounts=1")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        return r.json()

    owner, subset = client(OWNER), client(SUBSET)
    with _fleet(_accts(3), concurrency=3):
        old = server._probe_account_blocking
        server._probe_account_blocking = probe
        try:
            first, retry, sub = await asyncio.gather(get(owner), get(owner), get(subset))
        finally:
            server._probe_account_blocking = old
            await owner.aclose()
            await subset.aclose()

    assert len(calls) == 3, f"{len(calls)} OF probes for 3 accounts — the retry re-fanned out"
    assert first == retry, "the retry got a different answer than the request it joined"
    assert set(_rows(first)) == {"acct0", "acct1", "acct2"}, first
    assert set(_rows(sub)) == {"acct0"}, f"the subset owner got {set(_rows(sub))}"
    assert _rows(sub)["acct0"] == _rows(first)["acct0"], (sub, first)


async def case_one_dead_proxy_does_not_time_out_the_healthy_creators() -> None:
    from concurrent.futures import ThreadPoolExecutor
    one = {f"acct{i}" for i in range(0, 50, 5)}
    two = one | {f"acct{i}" for i in range(1, 50, 5)}
    dead: set[str] = set()

    def probe(aid: str) -> dict[str, Any]:
        time.sleep(1.5 if aid in dead else 0.03)
        return {"ok": True, "name": aid}

    pool = ThreadPoolExecutor(max_workers=server._EXECUTOR_THREADS)
    asyncio.get_running_loop().set_default_executor(pool)
    old = server._probe_account_blocking
    server._probe_account_blocking = probe
    try:
        timed_out = {}
        for label, stuck, cap in (("one", one, None), ("two", two, None), ("one at 4", one, 4)):
            dead = stuck
            with _fleet(_accts(50), concurrency=cap, budget_s=1.0):
                admission.HEALTH_PROBE._sems.clear()
                rows = _rows(await server._health_all_accounts())
                admission.HEALTH_PROBE._sems.clear()
            timed_out[label] = {a for a, r in rows.items() if r.get("timed_out")}
            await asyncio.sleep(1.6)
    finally:
        server._probe_account_blocking = old
        pool.shutdown(wait=True)
    for label, stuck in (("one", one), ("two", two)):
        assert timed_out[label] == stuck, (
            f"{label} dead prox(ies) at the default cap {admission.HEALTH_PROBE.cap}: only theirs may time "
            f"out; healthy ones did too: {sorted(timed_out[label] - stuck)[:5]}")
    assert timed_out["one at 4"] - one, "at 4 slots the dead proxy should have starved healthy Creators"
    assert admission.HEALTH_PROBE.cap >= 22, admission.HEALTH_PROBE.cap


def case_the_clamp_never_mutates_the_coalesced_snapshot() -> None:
    url = "http://user:pass@203.0.113.10:8001"
    snapshot = {"ok": False, "accounts": [
        {"account_id": "acct0", "ok": True, "proxy": {"label": "p0", "url": url}},
        {"account_id": "acct1", "ok": False, "error": "timeout"},
    ]}
    out = server._clamp_health_all(snapshot, frozenset({"acct0"}))
    assert out == {"ok": True, "accounts": [
        {"account_id": "acct0", "ok": True, "proxy": {"label": "p0"}}]}, out
    assert snapshot == {"ok": False, "accounts": [
        {"account_id": "acct0", "ok": True, "proxy": {"label": "p0", "url": url}},
        {"account_id": "acct1", "ok": False, "error": "timeout"},
    ]}, f"the clamp mutated the snapshot: {snapshot}"


async def case_a_sessionless_account_is_never_probed() -> None:
    calls: list[str] = []

    def probe(aid: str) -> dict[str, Any]:
        calls.append(aid)
        return {"ok": True}

    accounts = _accts(1) + _accts(1, has_session=False)
    accounts[1]["id"] = "acct-nosession"
    with _fleet(accounts, concurrency=2):
        old = server._probe_account_blocking
        server._probe_account_blocking = probe
        try:
            rows = _rows(await server._health_all_accounts())
        finally:
            server._probe_account_blocking = old

    assert calls == ["acct0"], calls
    assert rows["acct-nosession"] == {
        "account_id": "acct-nosession", "nickname": "model0", "color": "#fff",
        "has_session": False, "ok": False, "error": "no_session"}, rows["acct-nosession"]


def case_the_endpoint_still_never_raises_500() -> None:
    client = OWNER

    def load(aid: str):
        raise RuntimeError("client pool exploded")

    with _fleet(_accts(3), load_fn=load, concurrency=2, budget_s=5):
        r = client.get("/health?all_accounts=1")

    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body["ok"] is False, body
    assert len(body["accounts"]) == 3, body
    for row in body["accounts"]:
        assert row["error"] == "RuntimeError: client pool exploded", row


def case_the_single_account_branch_still_answers() -> None:
    client = _harness.make_client()
    old = server._get_client
    server._get_client = lambda *a, **k: _FakeClient("acct0", lambda aid: {"id": 7, "name": "Ava"})
    _FakeClient.egress_ip = lambda self, *a, **k: "1.2.3.4"
    try:
        r = client.get("/health")
    finally:
        server._get_client = old
        del _FakeClient.egress_ip

    assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
    body = r.json()
    assert body == {"ok": True, "account_id": "acct0", "user_id": 7, "name": "Ava",
                    "proxy": {"label": "proxy-acct0", "url": "http://proxy/acct0",
                              "egress_ip": "1.2.3.4"}}, body


if __name__ == "__main__":
    _harness.bootstrap()
    OWNER, SUBSET = _sign_in_fleet_owners()
    _harness.run()
