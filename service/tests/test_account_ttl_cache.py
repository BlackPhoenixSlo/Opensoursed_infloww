#!/usr/bin/env python3
"""Per-account TTL cache on the OF account reads (roadmap W2 2.7).

`/users/me`, `/users/me/stats/*`, `/payouts/*` and `/earnings/chart` are
answered from `server._account_ttl` for 60-120 s. Pinned over HTTP with real
session cookies and a fake OF transport (the real OFClient methods run; only
the socket call is replaced, so no request leaves the process):

  • one account's entry never answers another: two accounts, two upstream
    calls, each sees its own body; a caller who does not own an account is
    refused (403) even when that account's entry is warm;
  • every parameter is in the key (limit=10 and limit=20 are two entries);
  • concurrent misses on one key share ONE upstream call;
  • an upstream error is not cached;
  • write-through: an accepted OF write clears the reads it changes, for
    every caller of the client (a route, or code holding the client the way
    promotions_api and the promo re-arm automation do), and only for that
    account; a refused write and an unrelated write clear nothing.

Run: ./venv/bin/python service/tests/test_account_ttl_cache.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402

import _agency_fixtures as fx  # noqa: E402
import accounts  # noqa: E402
import of_client  # noqa: E402
import relay_cache  # noqa: E402
import server  # noqa: E402

IDS = fx.seed_two_agencies()
A, B = IDS["creator_a"], IDS["creator_b"]
for _aid in (A, B):   # meta, so an explicit X-Account-Id resolves (not 404)
    accounts.upsert_account(_aid, nickname=f"creator {_aid}")
OWNER_A = fx.login_owner("agency_a_owner")
OWNER_B = fx.login_owner("agency_b_owner")
MASTER = fx.login_owner("agency_master")


class _Resp:
    def __init__(self, url: str, status: int, body) -> None:
        self.url, self.status_code = url, status
        self.ok = 200 <= status < 300
        self.text = json.dumps(body)
        self.headers: dict = {}

    def json(self):
        return json.loads(self.text)


class _FakeOF:
    """One account's OFClient with only the socket call replaced: records
    (method, path) and answers `{"account": id, "n": call number}`."""

    def __init__(self, account_id: str) -> None:
        self.client = of_client.OFClient.__new__(of_client.OFClient)
        self.client.account_id = account_id
        self.client._http_call = self._http_call
        self.calls: list[tuple[str, str]] = []
        self.delay_s = 0.0
        self.fail_next = False
        self._lock = threading.Lock()

    def _http_call(self, method: str, url: str, *, json_body=None):
        if self.delay_s:
            time.sleep(self.delay_s)
        with self._lock:
            self.calls.append((method, of_client._short_path(url)))
            n = len(self.calls)
            if self.fail_next:
                self.fail_next = False
                return _Resp(url, 400, {"error": "nope"})
        return _Resp(url, 200, {"account": self.client.account_id, "n": n})

    def gets(self, path: str) -> int:
        return sum(1 for m, p in self.calls if m == "GET" and p == path)


FAKES: dict[str, _FakeOF] = {}


def _fresh() -> None:
    relay_cache._cache.clear()
    FAKES.clear()
    FAKES.update({A: _FakeOF(A), B: _FakeOF(B)})


def _fake_get_client(*_a, **_k):
    return FAKES[server._resolve_account_id(server._request_ctx.get())].client


server._get_client = _fake_get_client


def _get(client, path: str, account: str):
    r = client.get(path, headers={"X-Account-Id": account})
    assert r.status_code == 200, f"{path} as {account}: {r.status_code} {r.text}"
    return r.json()


# ── Isolation ───────────────────────────────────────────────────────────────

def case_two_accounts_get_their_own_entry_and_a_repeat_is_served_from_it():
    _fresh()
    a1 = _get(MASTER, "/api/of/v2/users/me", A)
    b1 = _get(MASTER, "/api/of/v2/users/me", B)
    assert a1["account"] == A and b1["account"] == B, (a1, b1)
    assert _get(MASTER, "/api/of/v2/users/me", A) == a1
    assert _get(MASTER, "/api/of/v2/users/me", B) == b1
    assert FAKES[A].gets("/api2/v2/users/me") == 1 and FAKES[B].gets("/api2/v2/users/me") == 1


def case_a_warm_entry_never_answers_a_caller_who_does_not_own_the_account():
    _fresh()
    for path in ("/api/of/v2/users/me", "/api/of/v2/payouts/balances",
                 "/api/of/v2/earnings/chart?filter=total_amount",
                 "/api/of/v2/users/me/stats/overview"):
        _get(OWNER_A, path, A)
        r = OWNER_B.get(path, headers={"X-Account-Id": A})
        assert r.status_code == 403 and str(A) not in r.text, f"{path}: {r.status_code} {r.text}"
        r = OWNER_B.get(f"{path}{'&' if '?' in path else '?'}account_id={A}")
        assert r.status_code == 403, f"{path} (query): {r.status_code} {r.text}"
    assert _get(OWNER_B, "/api/of/v2/users/me", B)["account"] == B


def case_every_parameter_is_part_of_the_key():
    _fresh()
    p10 = _get(OWNER_A, "/api/of/v2/payouts/requests?limit=10", A)
    p20 = _get(OWNER_A, "/api/of/v2/payouts/requests?limit=20", A)
    assert p10 != p20 and FAKES[A].gets("/api2/v2/payouts/requests") == 2
    assert _get(OWNER_A, "/api/of/v2/payouts/requests?limit=10", A) == p10
    # A path parameter too: two /stats/top kinds are two entries.
    _get(OWNER_A, "/api/of/v2/users/me/stats/top/message", A)
    _get(OWNER_A, "/api/of/v2/users/me/stats/top/story", A)
    _get(OWNER_A, "/api/of/v2/users/me/stats/top/message", A)
    tops = [p for m, p in FAKES[A].calls if "/stats/top" in p or "/top" in p]
    assert len(tops) == 2, FAKES[A].calls


def case_concurrent_misses_share_one_upstream_call():
    _fresh()
    FAKES[A].delay_s = 0.2

    async def burst():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver",
                                     cookies=dict(OWNER_A.cookies)) as c:
            return await asyncio.gather(*[
                c.get("/api/of/v2/payouts/balances", headers={"X-Account-Id": A})
                for _ in range(8)])

    replies = asyncio.run(burst())
    assert [r.status_code for r in replies] == [200] * 8, [r.text for r in replies]
    assert len({r.text for r in replies}) == 1
    assert FAKES[A].gets("/api2/v2/payouts/balances") == 1, FAKES[A].calls


def case_an_upstream_error_is_not_cached():
    _fresh()
    FAKES[A].fail_next = True
    r = OWNER_A.get("/api/of/v2/payouts/balances", headers={"X-Account-Id": A})
    assert r.status_code == 502, r.text
    assert _get(OWNER_A, "/api/of/v2/payouts/balances", A)["n"] == 2
    assert FAKES[A].gets("/api2/v2/payouts/balances") == 2


# ── Write-through ───────────────────────────────────────────────────────────

def case_a_payout_request_clears_the_payout_reads_and_users_me_of_that_account_only():
    _fresh()
    bal = _get(OWNER_A, "/api/of/v2/payouts/balances", A)
    me = _get(OWNER_A, "/api/of/v2/users/me", A)
    stats = _get(OWNER_A, "/api/of/v2/users/me/stats/overview", A)
    b_bal = _get(OWNER_B, "/api/of/v2/payouts/balances", B)
    r = OWNER_A.post("/api/of/v2/payouts/requests", json={"withdrawal_amount": 20},
                     headers={"X-Account-Id": A})
    assert r.status_code == 200, r.text
    assert _get(OWNER_A, "/api/of/v2/payouts/balances", A) != bal
    assert _get(OWNER_A, "/api/of/v2/users/me", A) != me
    assert _get(OWNER_A, "/api/of/v2/users/me/stats/overview", A) == stats  # not a payout read
    assert _get(OWNER_B, "/api/of/v2/payouts/balances", B) == b_bal         # other account kept


def case_profile_bundle_and_promotion_writes_clear_users_me():
    _fresh()
    writes = [
        ("patch", "/api/of/v2/users/me", {"about": "hi"}),
        ("patch", "/api/of/v2/users/me/reply-on-subscribe", {"enabled": True}),
        ("delete", "/api/of/v2/subscriptions/bundles/7", None),
        ("post", "/api/of/v2/promotions/9/finish", None),
    ]
    for method, path, body in writes:
        before = _get(OWNER_A, "/api/of/v2/users/me", A)
        kw = {"headers": {"X-Account-Id": A}}
        if body is not None:
            kw["json"] = body
        r = getattr(OWNER_A, method)(path, **kw)
        assert r.status_code == 200, f"{method} {path}: {r.status_code} {r.text}"
        assert _get(OWNER_A, "/api/of/v2/users/me", A) != before, f"{path} left users/me cached"


def case_a_write_made_outside_any_route_clears_too_the_way_the_promo_automation_writes():
    _fresh()
    before = _get(OWNER_A, "/api/of/v2/users/me", A)
    FAKES[A].client.create_promo(subscribe_counts=1, discount=50)   # promo_reactivate's call
    assert _get(OWNER_A, "/api/of/v2/users/me", A) != before


def case_a_refused_or_unrelated_write_clears_nothing():
    _fresh()
    me = _get(OWNER_A, "/api/of/v2/users/me", A)
    bal = _get(OWNER_A, "/api/of/v2/payouts/balances", A)
    FAKES[A].fail_next = True
    try:
        FAKES[A].client.request_json("PATCH", f"{of_client.API_BASE}/users/me", json_body={})
    except of_client.OFAPIError:
        pass
    else:
        raise AssertionError("a 400 write did not raise")
    FAKES[A].client.request_json("POST", f"{of_client.API_BASE}/chats/1/messages", json_body={})
    FAKES[A].client.request_json("POST", f"{of_client.API_BASE}/promotionsx", json_body={})
    assert _get(OWNER_A, "/api/of/v2/users/me", A) == me
    assert _get(OWNER_A, "/api/of/v2/payouts/balances", A) == bal


def case_a_failing_cache_bust_never_fails_the_accepted_write():
    _fresh()
    original = relay_cache.invalidate

    def boom(*_a, **_k):
        raise RuntimeError("bust broke")

    relay_cache.invalidate = boom
    try:
        out = FAKES[A].client.request_json("PATCH", f"{of_client.API_BASE}/users/me",
                                           json_body={"about": "x"})
    finally:
        relay_cache.invalidate = original
    assert out == {"account": A, "n": 1}, out


_harness.run()
