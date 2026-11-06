#!/usr/bin/env python3
"""Screen bundles (service/screens_api.py): one call answers a screen's first paint with
exactly what the per-Creator routes answer, under the same authorization, and never waits
for the slowest Creator.

The seam is the Relay over HTTP with real session cookies (the shared two-Agency fixture,
plus a second Creator for Agency A), so every hook runs as for the browser. OnlyFans is a
recording fake behind `server._load_client` (the per-Creator resolver still runs first).

Run: ./venv/bin/python service/tests/test_screens_api.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import anyio.from_thread  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts as account_registry  # noqa: E402
import employees  # noqa: E402
import of_pacing  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, UserAccount  # noqa: E402
from of_client import OFAPIError  # noqa: E402

IDS = fx.seed_two_agencies()
A1, B1, A2 = IDS["creator_a"], IDS["creator_b"], "1000003"


async def _second_creator() -> None:
    async with get_session() as s:
        s.add(Account(id=A2, nickname="creator_a2", color="#aaaaaa"))
    async with get_session() as s:
        s.add(UserAccount(user_id=IDS["agency_a_owner"], account_id=A2))


asyncio.run(_second_creator())
for aid in (A1, B1, A2):
    d = account_registry.ACCOUNTS_DIR / aid
    d.mkdir(exist_ok=True)
    account_registry.upsert_account(aid, nickname=f"n{aid}")
    (d / "latest.json").write_text(json.dumps({"session": "s.json"}))   # has_session

EMP_A = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
# One event loop for every request, as in the running relay: TestClient's
# default is a fresh loop per request, which strands relay_cache's locks and
# makes the loop's shutdown wait for a slow Creator's worker thread.
_LOOP = contextlib.ExitStack()   # held for the process: closing it stops the loop
PORTAL = _LOOP.enter_context(anyio.from_thread.start_blocking_portal())


def _one_loop(client):
    client.portal = PORTAL
    return client


OWNER_A = _one_loop(fx.login_owner("agency_a_owner"))
CHATTER_A = _one_loop(fx.login_chatter("chatter_a"))
CHATTER_AB = _one_loop(fx.login_chatter("chatter_ab"))
WINDOW = {"from": "2026-10-01T00:00:00Z", "to": "2026-10-31T00:00:00Z"}


class FakeOF:
    """Each Creator's OnlyFans: bodies derived from its id, every call recorded."""

    def __init__(self, aid: str, slow_s: float = 0.0, fail: set[str] | None = None) -> None:
        self.aid, self.slow_s, self.fail = aid, slow_s, fail or set()

    def _call(self, name: str, body):
        with LOCK:
            CALLS.append((self.aid, name))
        if self.slow_s:
            time.sleep(self.slow_s)
        if name in self.fail:
            raise OFAPIError("boom", response=_Resp(500, '{"error":"slop"}'))
        return body

    def me(self):
        return self._call("me", {"id": int(self.aid), "username": f"u{self.aid}", "name": f"C {self.aid}"})

    def subscription_counts_all(self):
        n = int(self.aid) % 97
        return self._call("counts", {"subscribers": {"active": n, "all": 2 * n, "expired": n}})

    def subscribers_chart(self, start=None, end=None, by=None):
        return self._call("chart", {"subscribers": int(self.aid) % 13, "start": start, "end": end, "by": by})

    def notifications_count(self):
        return self._call("notif", {"all": int(self.aid) % 7, "tip": 1})

    def list_chats(self, **kw):
        n = 30 if self.aid == A1 else 3
        rows = [{"withUser": {"id": int(self.aid) * 100 + i}, "lastMessage": {"id": i, "text": "hi"},
                 "unreadMessagesCount": 0} for i in range(n)]
        off, lim = int(kw.get("offset") or 0), int(kw.get("limit") or 10)
        return self._call("chats", {"list": rows[off:off + lim], "hasMore": off + lim < n})


class _Resp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code, self.text = status_code, text


LOCK = threading.Lock()
CALLS: list[tuple[str, str]] = []
FAKES: dict[str, FakeOF] = {}


def _use(**fakes: FakeOF) -> None:
    FAKES.clear()
    FAKES.update({f.aid: f for f in fakes.values()})
    CALLS.clear()
    import relay_cache
    import screens_api
    relay_cache._cache.clear()
    screens_api._SHARED.clear()   # a finished read is reused for SHARE_S: never across cases


server._load_client = lambda aid: FAKES[aid]
_use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))


def _get(client, path: str, aid: str | None = None, **params):
    r = client.get(path, params=params, headers={"X-Account-Id": aid} if aid else {})
    return r.status_code, r.json()


def _dash(client, **params):
    r = client.get("/admin/screens/dashboard", params={**WINDOW, **params})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.headers.get("cache-control") == "no-store"
    return r.json()


def _by_id(got: dict) -> dict[str, dict]:
    return {c["id"]: c for c in got["creators"]}


def _put(client, tab: str, blob: dict) -> None:
    r = client.put(f"/admin/settings/{tab}", json=blob)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def _role(pages: dict[str, bool]) -> None:
    _put(OWNER_A, "roles", {"enforce": True, "roles": [{"id": "fx", "name": "Fixture fx", "description": "",
                                                         "permissions": pages, "scope": "self"}],
                            "assignments": {str(EMP_A): "fx"}})


def _reset_roles() -> None:
    _put(OWNER_A, "roles", {"enforce": False})


# ── Same bodies as the per-Creator routes ──────────────────────────────────

def case_owner_dashboard_is_the_per_creator_routes_in_one_call():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    got = _dash(OWNER_A)
    assert [c["id"] for c in got["creators"]] == [a["id"] for a in got["accounts"]["accounts"]], "roster order"
    assert sorted(c["id"] for c in got["creators"]) == [A1, A2], got["creators"]
    assert got["errors"] == [], got["errors"]
    assert got["settings"] == _get(OWNER_A, "/admin/settings/applied")[1]
    assert got["accounts"] == _get(OWNER_A, "/admin/accounts")[1]
    assert got["perModel"] == _get(OWNER_A, "/admin/stats/per-model", **WINDOW)[1]
    for c in got["creators"]:
        assert not c["stale"] and c["asOf"], c
        assert c["profile"] == _get(OWNER_A, "/api/of/v2/users/me", c["id"])[1]
        assert c["subscriberCounts"] == _get(OWNER_A, "/api/of/v2/subscriptions/count/all", c["id"])[1]
        assert c["newFans"] == _get(OWNER_A, "/api/of/v2/subscriptions/subscribers/chart", c["id"],
                                    start=WINDOW["from"], end=WINDOW["to"])[1]
    assert all(aid != B1 for aid, _ in CALLS), CALLS


def case_dashboard_without_dates_reads_the_chart_as_the_hook_does():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    got = OWNER_A.get("/admin/screens/dashboard").json()
    assert _by_id(got)[A1]["newFans"] == {"subscribers": int(A1) % 13, "start": None, "end": None, "by": None}


def case_owner_inbox_is_the_per_creator_routes_in_one_call():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    r = OWNER_A.get("/admin/screens/inbox")
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-store", r.text
    got = r.json()
    assert sorted(got["chats"]) == [A1, A2] and got["errors"] == [] and got["stale"] == [], got
    for aid in (A1, A2):
        assert got["notificationCounts"][aid] == _get(OWNER_A, "/api/of/v2/users/notifications/count", aid)[1]
        assert got["chats"][aid] == _get(OWNER_A, "/api/of/v2/chats", aid, limit=25, offset=0, order="recent")[1]
    assert got["nextCursorByAccount"] == {A1: 25, A2: None}, got["nextCursorByAccount"]
    nxt = OWNER_A.get("/admin/screens/inbox", params={"cursor": 25}).json()
    assert nxt["chats"][A1] == _get(OWNER_A, "/api/of/v2/chats", A1, limit=25, offset=25, order="recent")[1]
    assert nxt["nextCursorByAccount"][A1] is None


def _lanes() -> dict[str, dict]:
    with server._lane_stats_lock:
        return {aid: dict(server._lane_stats.get(aid) or server._new_lane_stat()) for aid in (A1, A2)}


def case_only_the_open_creator_reads_as_the_user():
    """A user-priority bundle: every other Creator's inner reads are background (their lane's
    background cap, never user-active), the focused one keeps the caller's priority."""
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    of_pacing._last_user.clear()
    before = _lanes()
    r = OWNER_A.get("/admin/screens/inbox", params={"focus": A1}, headers={"X-Priority": "user"})
    assert r.status_code == 200 and not r.json()["errors"], r.text
    after = _lanes()
    d = {aid: {k: after[aid][k] - before[aid][k] for k in ("calls_user", "calls_background")} for aid in (A1, A2)}
    assert d[A1]["calls_user"] > 0 and d[A1]["calls_background"] == 0, d
    assert d[A2]["calls_user"] == 0 and d[A2]["calls_background"] > 0, d
    assert set(of_pacing._last_user) == {A1}, of_pacing._last_user


def case_reads_queued_at_the_deadline_run_on():
    """More reads than BUNDLE_READS and a deadline before the queue drains: the queued reads still
    reach OF, so the next bundle is complete with no new OF call (never the same tail skipped)."""
    import screens_api
    _use(a1=FakeOF(A1, slow_s=0.3), a2=FakeOF(A2, slow_s=0.3))
    real, screens_api.BUNDLE_READS = screens_api.BUNDLE_READS, 1
    try:
        first = _dash(OWNER_A, deadline_ms=100)
        assert len({(e["accountId"], e["read"]) for e in first["errors"]}) >= 5, first["errors"]
        time.sleep(7 * 0.3 + 0.8)   # 7 reads (per-model has no OF call), one at a time
        n = len(CALLS)
        assert sorted(set(CALLS)) == sorted({(a, c) for a in (A1, A2) for c in ("me", "counts", "chart")}), CALLS
    finally:
        screens_api.BUNDLE_READS = real
    second = _dash(OWNER_A, deadline_ms=1000)
    assert second["errors"] == [] and all(not c["stale"] for c in second["creators"]), second
    assert CALLS[n:] == [], CALLS[n:]


# ── Scope ──────────────────────────────────────────────────────────────────

def case_chatter_sees_only_its_creators_and_naming_another_reads_nothing():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    got = _dash(CHATTER_A)
    assert [c["id"] for c in got["creators"]] == [A1, A2], got["creators"]
    assert got["accounts"] == _get(CHATTER_A, "/chatter/me/accounts")[1]
    narrowed = _dash(CHATTER_A, accounts=f"{B1},{A2}")
    assert [c["id"] for c in narrowed["creators"]] == [A2], narrowed
    assert {"accountId": B1, "read": "*", "status": 404, "detail": "not on this screen"} in narrowed["errors"]
    inbox = CHATTER_A.get("/admin/screens/inbox", params={"accounts": B1}).json()
    assert inbox["chats"] == {} and inbox["errors"][0]["status"] == 404
    assert all(aid != B1 for aid, _ in CALLS), CALLS
    both = _dash(CHATTER_AB)
    assert sorted(c["id"] for c in both["creators"]) == sorted([A1, A2, B1])


def case_a_role_without_the_dashboard_gets_the_routes_own_403():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    _role({"/messages-pro": True})
    try:
        got = _dash(CHATTER_A)
        want = _get(CHATTER_A, "/api/of/v2/subscriptions/count/all", A1)
        assert want[0] == 403, want
        errs = {(e["accountId"], e["read"]): e for e in got["errors"]}
        assert errs[A1, "subscriberCounts"]["status"] == 403
        assert errs[A1, "subscriberCounts"]["detail"] == want[1]["detail"], (errs, want)
        assert got["creators"][0]["subscriberCounts"] is None
        assert not any(name == "counts" for _, name in CALLS), CALLS
    finally:
        _reset_roles()


def case_a_hidden_per_model_card_reads_none_of_it():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    _role({"/": True, "/messages-pro": True, "/#card-per-model": False})
    try:
        got = _dash(CHATTER_A)
        assert "/#card-per-model" in got["settings"]["permissions"]["denied_cards"]
        assert got["perModel"] is None
        assert all("subscriberCounts" not in c and "newFans" not in c for c in got["creators"]), got["creators"]
        assert {name for _, name in CALLS} == {"me"}, CALLS
    finally:
        _reset_roles()


# ── Never the slowest Creator ──────────────────────────────────────────────

def case_a_slow_creator_is_stale_and_the_rest_is_on_time():
    _use(a1=FakeOF(A1), a2=FakeOF(A2, slow_s=1.5))
    t0 = time.monotonic()
    got = _dash(OWNER_A, deadline_ms=300)
    took = time.monotonic() - t0
    assert took < 1.2, f"bundle waited {took:.2f}s for the slow Creator"
    a1, a2 = _by_id(got)[A1], _by_id(got)[A2]
    assert not a1["stale"] and a1["profile"]["id"] == int(A1), a1
    assert a2["stale"] and a2["profile"] is None, a2
    late = {e["read"] for e in got["errors"] if e["accountId"] == A2}
    assert late == {"profile", "subscriberCounts", "newFans"}, got["errors"]
    assert all(e["status"] == 504 and e["detail"] == {"upstream_status": "bundle_deadline"}
               for e in got["errors"]), got["errors"]


def case_an_of_error_is_the_routes_own_502():
    _use(a1=FakeOF(A1, fail={"counts"}), a2=FakeOF(A2))
    got = _dash(OWNER_A)
    want = _get(OWNER_A, "/api/of/v2/subscriptions/count/all", A1)
    assert want[0] == 502, want
    [e] = [e for e in got["errors"] if e["accountId"] == A1]
    assert e["read"] == "subscriberCounts" and e["status"] == 502 and e["detail"] == want[1]["detail"], (e, want)
    assert _by_id(got)[A1]["profile"] is not None and _by_id(got)[A2]["subscriberCounts"] is not None


def case_counts_are_one_of_read_across_concurrent_dashboards():
    _use(a1=FakeOF(A1, slow_s=0.2), a2=FakeOF(A2, slow_s=0.2))
    clients = [OWNER_A] + [_one_loop(fx.login_owner("agency_a_owner")) for _ in range(5)]
    out: list[dict] = []
    ts = [threading.Thread(target=lambda c=c: out.append(_dash(c))) for c in clients]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(out) == 6 and all(not o["errors"] for o in out), [o["errors"] for o in out]
    for aid in (A1, A2):
        for name in ("counts", "chart"):
            assert CALLS.count((aid, name)) == 1, (aid, name, CALLS)



def case_identical_reads_in_flight_run_once():
    """190 owner phones opening the inbox together: each Creator's page is annotated (3 DB
    reads) once, not once per phone; each caller still passed its own gate."""
    _use(a1=FakeOF(A1, slow_s=0.2), a2=FakeOF(A2, slow_s=0.2))
    real, ran = server._annotate_chat_rows, []

    async def counted(aid, resp):
        ran.append(aid)
        return await real(aid, resp)

    server._annotate_chat_rows = counted
    try:
        clients = [OWNER_A] + [_one_loop(fx.login_owner("agency_a_owner")) for _ in range(5)]
        out: list[dict] = []
        ts = [threading.Thread(target=lambda c=c: out.append(c.get("/admin/screens/inbox").json()))
              for c in clients]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        server._annotate_chat_rows = real
    assert len(out) == 6 and all(sorted(o["chats"]) == [A1, A2] for o in out), out
    assert all(o["chats"] == out[0]["chats"] for o in out)
    assert sorted(ran) == [A1, A2], ran



def case_a_failed_read_is_never_reused():
    _use(a1=FakeOF(A1, fail={"notif"}), a2=FakeOF(A2))
    first = OWNER_A.get("/admin/screens/inbox").json()
    assert A1 not in first["notificationCounts"] and any(e["accountId"] == A1 for e in first["errors"]), first
    FAKES[A1].fail = set()
    again = OWNER_A.get("/admin/screens/inbox").json()
    assert again["notificationCounts"].get(A1) == {"all": int(A1) % 7, "tip": 1}, again



def case_a_warm_cache_never_reaches_a_caller_without_that_creator():
    """Codex #7: relay_cache answers a hit before any route code, so the gate runs first. B1's
    counts and chart are warm from its own owner; owner A (no role hook: the resolver is its only
    gate; a chatter's role hook also checks the Agency) names B1: nothing read, nothing served."""
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    warm = _dash(_one_loop(fx.login_owner("agency_b_owner")))
    assert _by_id(warm)[B1]["subscriberCounts"] is not None, warm["creators"]
    n = len(CALLS)
    got = _dash(OWNER_A, accounts=B1)
    assert got["creators"] == [] and got["errors"] == [
        {"accountId": B1, "read": "*", "status": 404, "detail": "not on this screen"}], got
    assert CALLS[n:] == [], CALLS[n:]

_harness.run()
