#!/usr/bin/env python3
"""tests/test_health_all_accounts.py — the /setup probe's admission gate.

`GET /health?all_accounts=1` is one live OF round-trip per account. It used to
make them serially (7 accounts measured 4.11s then 3.06s against 0.60s for a
single account) and now makes them concurrently — but a bare fan-out would have
been a downgrade, and every case below guards one of the reasons why:

  • the fan-out is BOUNDED. These probes call `_load_client()` + `c.me()`
    directly, not through `_proxy`, so no `_priority_lane` and no per-account
    cap stands between them and the shared proxy / executor / descriptor
    ceilings.
  • the budget is NOT a cancel. `c.me()` blocks in a thread and outlives any
    cancellation, so a timed-out probe keeps running and keeps its slot. A gate
    that released on timeout would report a bound it was not holding.
  • the UI's `retry: 1` must JOIN an in-flight fan-out, not double it.
  • per-account result association, and the "never raises 500" contract,
    survive the move off the serial loop.

The route answers only a signed-in caller, for their own Creators (round 2,
ticket 12), so the two cases that go through it sign in an owner of their
fleet first, with the `_agency_fixtures` login; the account and proxy
registries sit on `tempfile.mkdtemp` trees, never the real files.

Run:  ./venv/bin/python service/tests/test_health_all_accounts.py
"""
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


# ── Fixtures ───────────────────────────────────────────────────────────

class _FakeClient:
    """Enough OFClient surface for the health row: `me()` and the proxy pair."""

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
    """Bind a fake registry + client loader (and optionally the two knobs).

    Restores everything, including the knobs, so one case cannot leak a 0.2s
    budget into the next one and fail it for the wrong reason.
    """
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


# The owner of the fleet the route-level cases probe: owns acct0..acct7 in
# `user_accounts`, so the route's clamp keeps every row. A second owner holds
# acct0 only, so a caller with a subset can join the same fan-out. Set in __main__.
FLEET_OWNER = "health_fleet_owner"
SUBSET_OWNER = "health_subset_owner"
OWNER = None
SUBSET = None


def _sign_in_fleet_owners(n: int = 8):
    """Seed the fleet's owner and the subset owner (the shared bench's password
    and login) and return their signed-in clients. `seed_two_agencies` also
    moves the account registry onto a temp tree."""
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


# ── Cases ──────────────────────────────────────────────────────────────

async def case_the_fanout_is_bounded_not_unbounded() -> None:
    """8 accounts, 3 slots: never more than 3 OF calls in flight at once.

    The whole point of the gate. Without it the answer is 8 — and on a real
    fleet that is 8 simultaneous proxy connections and 8 executor threads taken
    by an admin table nobody is watching.
    """
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
    # Association: every row carries ITS OWN account's answer, not a neighbour's.
    for i in range(8):
        assert rows[f"acct{i}"]["name"] == f"name-acct{i}", rows[f"acct{i}"]


async def case_every_failure_shape_lands_on_its_own_row() -> None:
    """Per-account association survives the move off the serial loop.

    One account of each kind, answered out of order (the healthy one is slow so
    it finishes LAST), so a fan-out that zipped results back positionally by
    completion order would scramble them here.
    """
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
            time.sleep(0.15)          # healthy, and deliberately the slowest
            return {"id": 111, "name": "Ava"}
        if aid == "acct2":
            raise OFAPIError("401 from OF", response=_Resp())
        raise ValueError("kaboom")     # acct3

    with _fleet(_accts(4), load_fn=load, concurrency=4):
        rows = _rows(await server._health_all_accounts())

    assert rows["acct0"] == {**rows["acct0"], "ok": True, "user_id": 111, "name": "Ava"}, rows["acct0"]
    assert rows["acct0"]["proxy"] == {"label": "proxy-acct0", "url": "http://proxy/acct0"}
    assert rows["acct1"]["ok"] is False and rows["acct1"]["error"] == "no_session_yet", rows["acct1"]
    assert rows["acct2"]["error"] == "upstream" and rows["acct2"]["upstream_status"] == 401, rows["acct2"]
    assert rows["acct2"]["upstream_body"] == "unauthorized-body", rows["acct2"]
    assert rows["acct3"]["error"] == "ValueError: kaboom", rows["acct3"]


async def case_a_timeout_does_not_cancel_the_probe() -> None:
    """The budget stops WAITING; it does not stop the OF call.

    `c.me()` blocks in a worker thread — cancelling the task that awaits it
    would return a response while the call kept running anyway. So the row says
    `timeout` (an honest "still running", not a dead session) and the probe is
    left to finish. This asserts it actually does.
    """
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
            # Parked, so the loop cannot collect a task nobody else references.
            assert len(server._health_probes_running) == 1, server._health_probes_running
            await asyncio.sleep(0.6)
            assert finished.is_set(), "the abandoned probe was cancelled, not left to finish"
            assert not server._health_probes_running, "the done-callback never unparked it"
        finally:
            server._probe_account_blocking = old


async def case_a_timeout_does_not_hand_its_slot_to_the_next_probe() -> None:
    """A slot belongs to the RUNNING call, never to whoever is still waiting.

    One slot, two accounts, and the first probe outruns the budget. If the gate
    released on timeout, probe 2 would start while probe 1's OF call was still
    in flight — a bound reported but not held. Instead probe 2 waits for the
    real completion, so it starts after (and times out too).
    """
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
    """AccountsTable's query inherits `retry: 1`, so a slow answer can fire a
    SECOND `?all_accounts=1` on top of the first. Coalesced, that retry joins
    the in-flight fan-out; uncoalesced it would double every OF call at exactly
    the moment the relay is already struggling to answer."""
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

    # All three requests on this one loop, through the real cookie and session
    # middleware: the fleet's owner and their retry, plus an owner of acct0
    # alone, who joins the same in-flight fan-out and must get only acct0.
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
    # One fan-out, clamped per caller: the subset owner's rows are theirs alone,
    # and the fleet owner's answer still holds every row.
    assert set(_rows(first)) == {"acct0", "acct1", "acct2"}, first
    assert set(_rows(sub)) == {"acct0"}, f"the subset owner got {set(_rows(sub))}"
    assert _rows(sub)["acct0"] == _rows(first)["acct0"], (sub, first)


async def case_one_dead_proxy_does_not_time_out_the_healthy_creators() -> None:
    """50 Creators, 10 of them behind one dead proxy: the other 40 still answer.

    The default ceiling is sized for this (admission.HEALTH_PROBE): a probe
    behind a dead proxy keeps its slot past the budget until the client gives
    up, and one proxy carries 5-10 accounts. Times are production's scaled by
    1/20 — healthy 0.6 s -> 0.03, stuck to `OFClient.timeout_s` 30 s -> 1.5,
    the route's 20 s budget -> 1.0 — on an executor the relay's own size, so
    the threads are not what binds. Then the same fleet at the old 4: the stuck
    probes take every slot and healthy Creators come back `timeout`, which is
    the bug this default fixes.
    """
    from concurrent.futures import ThreadPoolExecutor
    one = {f"acct{i}" for i in range(0, 50, 5)}            # spread, as a proxy's accounts are
    two = one | {f"acct{i}" for i in range(1, 50, 5)}      # a second dead proxy: 20 stuck
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
                admission.HEALTH_PROBE._sems.clear()    # this loop's semaphore takes the cap under test
                rows = _rows(await server._health_all_accounts())
                admission.HEALTH_PROBE._sems.clear()
            timed_out[label] = {a for a, r in rows.items() if r.get("timed_out")}
            await asyncio.sleep(1.6)                     # let the stuck probes finish and free their slots
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
    """Every waiter on the fan-out gets a deep copy today, but the clamp itself
    must not lean on that: it builds new rows and leaves the snapshot whole."""
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
    """No session means no client to load — the row is answered off the
    registry alone, and must not spend a slot or an OF call to say so."""
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
    """The contract the serial loop's try/except used to carry. It now lives in
    a worker thread, where an escaping exception is no longer inside the loop
    that wrapped it — so this asserts the whole route end to end, over HTTP."""
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
    """The handler is `async def` now, so the single-account body — still two
    blocking OF calls, `me()` and `egress_ip()` — has to reach a thread rather
    than run on the event loop. This is the guard that it still runs at all."""
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
