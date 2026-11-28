#!/usr/bin/env python3
import _harness  # MUST be first: binds temp DB

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
from unittest.mock import patch  # noqa: E402

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
    (d / "latest.json").write_text(json.dumps({"session": "s.json"}))

EMP_A = asyncio.run(employees.get_or_create_mirror_employee(
    IDS["chatter_a"], IDS["agency_a_owner"], display_name="chatter_a", color="#bbbbbb"))
# One loop for every request as in the relay: TestClient's per-request loop strands relay_cache's locks
_LOOP = contextlib.ExitStack()
PORTAL = _LOOP.enter_context(anyio.from_thread.start_blocking_portal())


def _one_loop(client):
    client.portal = PORTAL
    return client


OWNER_A = _one_loop(fx.login_owner("agency_a_owner"))
CHATTER_A = _one_loop(fx.login_chatter("chatter_a"))
CHATTER_AB = _one_loop(fx.login_chatter("chatter_ab"))
WINDOW = {"from": "2026-10-01T00:00:00Z", "to": "2026-10-31T00:00:00Z"}


class FakeOF:

    def __init__(self, aid: str, slow_s: float = 0.0, fail: set[str] | None = None) -> None:
        self.aid, self.slow_s, self.fail = aid, slow_s, fail or set()
        self.more_fans = 0

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
        n = int(self.aid) % 97 + self.more_fans
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
    screens_api._SHARED.clear()
    screens_api._LAST.clear()


server._load_client = lambda aid: FAKES[aid]
_use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))


def _get(client, path: str, aid: str | None = None, **params):
    r = client.get(path, params=params, headers={"X-Account-Id": aid} if aid else {})
    return r.status_code, r.json()


def _view(env: dict) -> dict:
    assert set(env) == {"answers", "asOf"} and isinstance(env["asOf"], int), set(env)
    v: dict = {"errors": [], "refreshing": [], "asOf": env["asOf"]}
    seen: set[tuple] = set()
    for a in env["answers"]:
        assert ("body" in a) != ("status" in a) and {"accountId", "read"} <= set(a), a
        assert (a["accountId"], a["read"]) not in seen, f"duplicate answer {a}"
        seen.add((a["accountId"], a["read"]))
        if "status" in a:
            v["errors"].append(a)
            continue
        if a.get("refreshing"):
            v["refreshing"].append({"accountId": a["accountId"], "read": a["read"]})
        if a["accountId"] is None:
            v[a["read"]] = a["body"]
        else:
            v.setdefault(a["read"], {})[a["accountId"]] = a["body"]
    return v


def _late(v: dict) -> set[tuple]:
    return {(e["accountId"], e["read"]) for e in v["errors"]
            if e["status"] == 504 and e["detail"] == {"upstream_status": "bundle_deadline"}}


def _dash(client, **params):
    r = client.get("/admin/screens/dashboard", params={**WINDOW, **params})
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    assert r.headers.get("cache-control") == "no-store"
    return _view(r.json())


def _inbox(client, **params):
    r = client.get("/admin/screens/inbox", params=params)
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-store", r.text
    return _view(r.json())


def _put(client, tab: str, blob: dict) -> None:
    r = client.put(f"/admin/settings/{tab}", json=blob)
    assert r.status_code == 200, f"PUT {tab}: {r.status_code} {r.text}"


def _role(pages: dict[str, bool]) -> None:
    _put(OWNER_A, "roles", {"enforce": True, "roles": [{"id": "fx", "name": "Fixture fx", "description": "",
                                                         "permissions": pages, "scope": "self"}],
                            "assignments": {str(EMP_A): "fx"}})


def _reset_roles() -> None:
    _put(OWNER_A, "roles", {"enforce": False})



def case_owner_dashboard_is_the_per_creator_routes_in_one_call():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    got = _dash(OWNER_A)
    assert list(got["profile"]) == [a["id"] for a in got["accounts"]["accounts"]], "roster order"
    assert sorted(got["profile"]) == [A1, A2], got["profile"]
    assert got["errors"] == [], got["errors"]
    assert got["settings"] == _get(OWNER_A, "/admin/settings/applied")[1]
    assert got["accounts"] == _get(OWNER_A, "/admin/accounts")[1]
    assert got["perModel"] == _get(OWNER_A, "/admin/stats/per-model", **WINDOW)[1]
    for aid in got["profile"]:
        assert got["profile"][aid] == _get(OWNER_A, "/api/of/v2/users/me", aid)[1]
        assert got["subscriberCounts"][aid] == _get(OWNER_A, "/api/of/v2/subscriptions/count/all", aid)[1]
        assert got["newFans"][aid] == _get(OWNER_A, "/api/of/v2/subscriptions/subscribers/chart", aid,
                                           start=WINDOW["from"], end=WINDOW["to"])[1]
    assert all(aid != B1 for aid, _ in CALLS), CALLS


def case_dashboard_without_dates_reads_the_chart_as_the_hook_does():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    got = _view(OWNER_A.get("/admin/screens/dashboard").json())
    assert got["newFans"][A1] == {"subscribers": int(A1) % 13, "start": None, "end": None, "by": None}


def case_owner_inbox_is_the_per_creator_routes_in_one_call():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    got = _inbox(OWNER_A)
    assert got["accounts"] == _get(OWNER_A, "/admin/accounts")[1]
    assert sorted(got["chats"]) == [A1, A2] and got["errors"] == [], got
    for aid in (A1, A2):
        assert got["notificationCounts"][aid] == _get(OWNER_A, "/api/of/v2/users/notifications/count", aid)[1]
        assert got["chats"][aid] == _get(OWNER_A, "/api/of/v2/chats", aid, limit=25, offset=0, order="recent")[1]
    assert {a: got["chats"][a]["hasMore"] for a in (A1, A2)} == {A1: True, A2: False}, got["chats"]
    nxt = _inbox(OWNER_A, cursor=25)
    assert nxt["chats"][A1] == _get(OWNER_A, "/api/of/v2/chats", A1, limit=25, offset=25, order="recent")[1]
    assert nxt["chats"][A1]["hasMore"] is False



def case_a_deep_inbox_bundle_cannot_forward_explicit_intent():
    for headers in ({"X-List-Caller": "replay"}, {"X-List-Intent": "explicit"}):
        _use(a1=FakeOF(A1), a2=FakeOF(A2))
        r = OWNER_A.get("/admin/screens/inbox", params={"cursor": 100}, headers=headers)
        assert r.status_code == 200, r.text
        got = _view(r.json())
        refused = {e["accountId"] for e in got["errors"] if e["read"] == "chats" and e["status"] == 428}
        assert refused == {A1, A2} and "chats" not in got, got
        assert not any(name == "chats" for _, name in CALLS), CALLS


def case_the_inbox_lists_only_onlyfans_creators():
    saved = account_registry.load_meta(A2)
    try:
        for key, listed in ((None, True), ("onlyfans", True), (" OnlyFans ", True), ("myspace", False),
                            ("fansly", False)):
            meta = {k: v for k, v in saved.items() if k != "platform"}
            if key is not None:
                meta["platform"] = key
            account_registry.save_meta(A2, meta)
            _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
            assert (A2 in _inbox(OWNER_A)["chats"]) is listed, key
    finally:
        account_registry.save_meta(A2, saved)

@contextlib.contextmanager
def _platform(aid: str, key: str):
    saved = account_registry.load_meta(aid)
    account_registry.save_meta(aid, {**saved, "platform": key})
    try:
        yield
    finally:
        account_registry.save_meta(aid, saved)


def _loads(aid: str):
    with LOCK:
        CALLS.append((aid, "client"))
    return FAKES[aid]


REFUSED = "subscribers chart: not on this platform"
CHART_ROUTE = (
    ("onlyfans", FakeOF, 200, {"subscribers": int(A2) % 13, "start": "a", "end": "b", "by": None},
     [(A2, "client"), (A2, "chart")]),
    ("fansly", FakeOF, 501, {"detail": REFUSED}, []),
)


def case_the_chart_route_on_fansly_answers_501_before_any_client():
    for platform, fake, status, body, calls in CHART_ROUTE:
        _use(a2=fake(A2))
        with _platform(A2, platform), patch.object(server, "_load_client", _loads):
            got = _get(OWNER_A, "/api/of/v2/subscriptions/subscribers/chart", A2, start="a", end="b")
        assert got == (status, body), (platform, got)
        assert CALLS == calls, (platform, CALLS)


NEW_FANS_WARM = (
    ({}, "_LAST"),
    ({"accounts": f"{A1},{A2}"}, "_cached"),
)


def case_fansly_new_fans_refuses_before_its_warm_last_value_and_cache():
    import relay_cache
    import screens_api
    for params, warm_path in NEW_FANS_WARM:
        _use(a1=FakeOF(A1), a2=FakeOF(A2))
        warm = _dash(OWNER_A)
        assert warm["newFans"][A2] is not None and not warm["errors"], warm
        assert any(k[1:3] == ("newFans", A2) for k in screens_api._LAST), warm_path
        assert any(k[:2] == ("screen_subs_chart", A2) for k in relay_cache._cache), warm_path
        n = len(CALLS)
        with _platform(A2, "fansly"):
            got = _dash(OWNER_A, **params)
        assert got["errors"] == [{"accountId": A2, "read": "newFans", "status": 501, "detail": REFUSED}], (
            warm_path, got["errors"])
        assert got["newFans"] == {A1: warm["newFans"][A1]}, (warm_path, got["newFans"])
        assert {r: got[r][A2] for r in ("profile", "subscriberCounts")} == {
            r: warm[r][A2] for r in ("profile", "subscriberCounts")}, warm_path
        assert [c for c in CALLS[n:] if c[0] == A2 and c[1] == "chart"] == [], (warm_path, CALLS[n:])


def _lanes() -> dict[str, dict]:
    with server._lane_stats_lock:
        return {aid: dict(server._lane_stats.get(aid) or server._new_lane_stat()) for aid in (A1, A2)}


def case_only_the_open_creator_reads_as_the_user():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    of_pacing._last_user.clear()
    before = _lanes()
    r = OWNER_A.get("/admin/screens/inbox", params={"focus": A1}, headers={"X-Priority": "user"})
    assert r.status_code == 200 and not _view(r.json())["errors"], r.text
    after = _lanes()
    d = {aid: {k: after[aid][k] - before[aid][k] for k in ("calls_user", "calls_background")} for aid in (A1, A2)}
    assert d[A1]["calls_user"] > 0 and d[A1]["calls_background"] == 0, d
    assert d[A2]["calls_user"] == 0 and d[A2]["calls_background"] > 0, d
    assert set(of_pacing._last_user) == {A1}, of_pacing._last_user


def case_reads_queued_at_the_deadline_run_on():
    import screens_api
    _use(a1=FakeOF(A1, slow_s=0.3), a2=FakeOF(A2, slow_s=0.3))
    real, screens_api.BUNDLE_READS = screens_api.BUNDLE_READS, 1
    try:
        first = _dash(OWNER_A, deadline_ms=100)
        assert len({(e["accountId"], e["read"]) for e in first["errors"]}) >= 5, first["errors"]
        time.sleep(7 * 0.3 + 0.8)
        n = len(CALLS)
        assert sorted(set(CALLS)) == sorted({(a, c) for a in (A1, A2) for c in ("me", "counts", "chart")}), CALLS
    finally:
        screens_api.BUNDLE_READS = real
    second = _dash(OWNER_A, deadline_ms=1000)
    assert second["errors"] == [], second
    assert CALLS[n:] == [], CALLS[n:]



def case_chatter_sees_only_its_creators_and_naming_another_reads_nothing():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    got = _dash(CHATTER_A)
    assert list(got["profile"]) == [A1, A2], got["profile"]
    assert "accounts" not in got, "a chatter's list is /chatter/me/accounts: never a bundle answer"
    narrowed = _dash(CHATTER_A, accounts=f"{B1},{A2}")
    assert list(narrowed["profile"]) == [A2], narrowed
    assert {"accountId": B1, "read": "*", "status": 404, "detail": "not on this screen"} in narrowed["errors"]
    inbox = _inbox(CHATTER_A, accounts=B1)
    assert "chats" not in inbox and inbox["errors"][0]["status"] == 404
    assert all(aid != B1 for aid, _ in CALLS), CALLS
    both = _dash(CHATTER_AB)
    assert sorted(both["profile"]) == sorted([A1, A2, B1])


def case_a_shared_inbox_read_never_crosses_a_split_inbox_binding():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    put = lambda cfg: OWNER_A.put("/admin/split-inbox", json={"account_id": A1, "config": cfg})
    assert put({"group_count": 2, "assignments": {},
                "chatter_groups": {IDS["chatter_a"]: 1, IDS["chatter_ab"]: 2}}).status_code == 200
    try:
        ids = lambda c: [r["withUser"]["id"] for r in _inbox(c, accounts=A1)["chats"][A1]["list"]]
        owner, one, two = ids(OWNER_A), ids(CHATTER_A), ids(CHATTER_AB)
        assert len(owner) == 25 and {i % 2 for i in owner} == {0, 1}, owner
        assert one and all(i % 2 == 0 for i in one), one
        assert two and all(i % 2 == 1 for i in two), two
    finally:
        put({"group_count": 1, "assignments": {}, "chatter_groups": {}})


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
        assert A1 not in got.get("subscriberCounts", {}), got
        assert not any(name == "counts" for _, name in CALLS), CALLS
    finally:
        _reset_roles()


def case_a_hidden_per_model_card_reads_none_of_it():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    _role({"/": True, "/messages-pro": True, "/#card-per-model": False})
    try:
        got = _dash(CHATTER_A)
        assert "/#card-per-model" in got["settings"]["permissions"]["denied_cards"]
        assert "perModel" not in got
        assert "subscriberCounts" not in got and "newFans" not in got, got
        assert {name for _, name in CALLS} == {"me"}, CALLS
    finally:
        _reset_roles()



def case_a_slow_creator_is_stale_and_the_rest_is_on_time():
    _use(a1=FakeOF(A1), a2=FakeOF(A2, slow_s=1.5))
    t0 = time.monotonic()
    got = _dash(OWNER_A, deadline_ms=300)
    took = time.monotonic() - t0
    assert took < 1.2, f"bundle waited {took:.2f}s for the slow Creator"
    assert got["profile"][A1]["id"] == int(A1) and not {r for a, r in _late(got) if a == A1}, got
    assert A2 not in got["profile"], got["profile"]
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
    assert got["profile"][A1] is not None and got["subscriberCounts"][A2] is not None


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
    _use(a1=FakeOF(A1, slow_s=0.2), a2=FakeOF(A2, slow_s=0.2))
    real, ran = server._annotate_chat_rows, []

    async def counted(aid, resp):
        ran.append(aid)
        return await real(aid, resp)

    server._annotate_chat_rows = counted
    try:
        clients = [OWNER_A] + [_one_loop(fx.login_owner("agency_a_owner")) for _ in range(5)]
        out: list[dict] = []
        ts = [threading.Thread(target=lambda c=c: out.append(_inbox(c))) for c in clients]
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
    first = _inbox(OWNER_A)
    assert A1 not in first["notificationCounts"] and any(e["accountId"] == A1 for e in first["errors"]), first
    FAKES[A1].fail = set()
    again = _inbox(OWNER_A)
    assert again["notificationCounts"].get(A1) == {"all": int(A1) % 7, "tip": 1}, again



def case_a_warm_cache_never_reaches_a_caller_without_that_creator():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    warm = _dash(_one_loop(fx.login_owner("agency_b_owner")))
    assert warm["subscriberCounts"][B1] is not None, warm
    n = len(CALLS)
    got = _dash(OWNER_A, accounts=B1)
    assert "profile" not in got and got["errors"] == [
        {"accountId": B1, "read": "*", "status": 404, "detail": "not on this screen"}], got
    assert CALLS[n:] == [], CALLS[n:]




def _active(v: dict, aid: str) -> int:
    return v["subscriberCounts"][aid]["subscribers"]["active"]


def case_the_last_value_answers_at_once_and_the_follow_up_has_the_new_one():
    import relay_cache
    import screens_api
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    first = _dash(OWNER_A)
    assert first["refreshing"] == [] and first["errors"] == [], first
    old = _active(first, A1)
    relay_cache._cache.clear()
    screens_api._SHARED.clear()
    FAKES[A1].slow_s, FAKES[A1].more_fans = 1.0, 5
    t0 = time.monotonic()
    got = _dash(OWNER_A)
    took = time.monotonic() - t0
    assert took < 0.5, f"waited {took:.2f}s for OF behind a last value"
    assert _active(got, A1) == old and not got["errors"], got
    assert {(e["accountId"], e["read"]) for e in got["refreshing"]} == {
        (a, r) for a in (A1, A2) for r in ("profile", "subscriberCounts", "newFans")}, got["refreshing"]
    follow = _dash(OWNER_A, accounts=f"{A1},{A2}", deadline_ms=5000)
    assert follow["refreshing"] == [] and _active(follow, A1) == old + 5, follow
    assert CALLS.count((A1, "counts")) == 2, CALLS
    again = _dash(OWNER_A)
    assert _active(again, A1) == old + 5 and again["refreshing"], again


def case_a_last_value_is_only_its_own_principals():
    _use(a1=FakeOF(A1), a2=FakeOF(A2), b1=FakeOF(B1))
    assert _dash(OWNER_A)["refreshing"] == []
    assert _dash(OWNER_A)["refreshing"], "the owner's own second bundle: its last values"
    chatter = _dash(CHATTER_A)
    assert chatter["refreshing"] == [] and list(chatter["profile"]) == [A1, A2], chatter
    other = _dash(_one_loop(fx.login_owner("agency_b_owner")))
    assert other["refreshing"] == [] and list(other["profile"]) == [B1], other


def case_a_last_value_never_outlives_its_gate():
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    warm = _dash(CHATTER_A)
    assert warm["subscriberCounts"][A1] is not None, warm
    _role({"/messages-pro": True})
    try:
        got = _dash(CHATTER_A)
        errs = {(e["accountId"], e["read"]): e["status"] for e in got["errors"]}
        assert errs[A1, "subscriberCounts"] == 403 and A1 not in got.get("subscriberCounts", {}), got
        assert not any(e["read"] == "subscriberCounts" for e in got["refreshing"]), got["refreshing"]
    finally:
        _reset_roles()


def case_last_values_are_bounded_and_age_out():
    import screens_api
    _use(a1=FakeOF(A1), a2=FakeOF(A2))
    real = screens_api.STALE_ENTRIES, screens_api.STALE_MAX_S
    try:
        screens_api.STALE_ENTRIES = 2
        _dash(OWNER_A)
        assert len(screens_api._LAST) == 2, list(screens_api._LAST)
        screens_api.STALE_ENTRIES, screens_api.STALE_MAX_S = real[0], 0.0
        _dash(OWNER_A)
        assert _dash(OWNER_A)["refreshing"] == [], "older than STALE_MAX_S: read before answering"
    finally:
        screens_api.STALE_ENTRIES, screens_api.STALE_MAX_S = real

_harness.run()
