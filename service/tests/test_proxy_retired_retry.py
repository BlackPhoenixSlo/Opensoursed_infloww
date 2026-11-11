"""
server._proxy when client_pool evicts the OFClient a call is on (service/server.py
+ client_pool.evict). Slop 2026-10-25-session-health-otp, red since 0b87e9621: a
Creator flips to 2FA, the first inbox read's 101 evicts its client, the old
client's signed sessions retire, and the other reads still on it answered 502
with upstream 500 "signed session retired" instead of OF's 400.

  case_retired_read_reruns_on_the_current_client: a GET whose client retired
      mid-call runs once more on the pool's fresh client; OF's real answer (400,
      101) is what the caller gets.
  case_retired_read_twice_answers_503: once only; then 503 + Retry-After.
  case_retired_write_is_not_rerun: a non-GET is never re-run (a multi-request
      write could repeat what it sent): 503 + Retry-After, one call.
  case_dead_session_on_a_replaced_client_keeps_the_fresh_one: a 101 met on a
      client the pool already replaced evicts nothing; the fresh one stays live.
  case_preloaded_client_late_101_keeps_the_fresh_one: the same for a client
      loaded before _proxy (mass send's bound method) and named by `client=`.
  case_evict_only: client_pool.evict(aid, only=c) drops c only while pooled.

OFClient.from_account is stubbed; no network.

Run: ./venv/bin/python service/tests/test_proxy_retired_retry.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
import types  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import accounts as account_registry  # noqa: E402
import client_pool  # noqa: E402
import relay_host  # noqa: E402
from of_client import OFAPIError, OFSessionRetired  # noqa: E402

_harness.make_client()  # neutralises the startup spawns
import server  # noqa: E402

AID = "acc_retired_retry"
account_registry.get_account = lambda aid: {"id": aid, "nickname": aid}
account_registry.get_platform = lambda aid: "onlyfans"

OTP_BODY = ('{"error":{"code":101,"message":"Confirm it is you","payload":{"otpState":'
            '{"appOtp":true},"strong":false}}}')


class _Resp:
    status_code, text = 400, OTP_BODY

    def json(self):
        return json.loads(OTP_BODY)


def _otp() -> OFAPIError:
    return OFAPIError(f"400 for https://onlyfans.com/api2/v2/chats\n{OTP_BODY}", response=_Resp())


class _Fake:
    """An OFClient as the pool sees it; `answer(client)` is what its read does."""
    user_id, x_of_rev = 1, "rev"

    def __init__(self, answer) -> None:
        self.retired, self.calls, self._answer = False, 0, answer

    def read(self):
        self.calls += 1
        return self._answer(self)

    def close_signed_sessions(self) -> None:
        self.retired = True


def _with_pool(answers):
    """Pool builds one _Fake per answer, in order; returns the built list."""
    built: list[_Fake] = []
    it = iter(answers)
    client_pool.OFClient.from_account = staticmethod(lambda aid: built.append(_Fake(next(it))) or built[-1])
    client_pool.evict(AID)
    return built


def _proxy(method: str):
    req = types.SimpleNamespace(method=method, headers={"x-account-id": AID}, query_params={})
    token = server._request_ctx.set(req)
    try:
        return server._proxy(lambda: server._get_client().read())
    finally:
        server._request_ctx.reset(token)


def _evicted_under_it(c):
    """A concurrent read's 101 evicted this client before its request left."""
    client_pool.evict(AID)
    raise OFSessionRetired()


def _answers_101(c):
    raise _otp()


def _status(method: str) -> HTTPException:
    try:
        _proxy(method)
    except HTTPException as e:
        return e
    raise AssertionError("_proxy answered")


server._kick_mark_session_dead = lambda *a, **k: None  # the flag's own tests: test_agency_notifications


def case_retired_read_reruns_on_the_current_client():
    built = _with_pool([_evicted_under_it, _answers_101])
    e = _status("GET")
    assert e.status_code == 502 and e.detail["upstream_status"] == 400, (e.status_code, e.detail)
    assert [c.calls for c in built] == [1, 1], [c.calls for c in built]
    assert built[0].retired and built[1].retired, "the fresh client met the 101 itself: it is evicted"


def case_retired_read_twice_answers_503():
    built = _with_pool([_evicted_under_it, _evicted_under_it, lambda c: {"ok": True}])
    e = _status("GET")
    assert e.status_code == 503 and e.headers == {"Retry-After": "1"}, (e.status_code, e.headers)
    assert e.detail["upstream_status"] == "session_retired", e.detail
    assert [c.calls for c in built] == [1, 1], [c.calls for c in built]


def case_retired_write_is_not_rerun():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        built = _with_pool([_evicted_under_it, lambda c: {"ok": True}])
        e = _status(method)
        assert e.status_code == 503 and e.headers == {"Retry-After": "1"}, (method, e.status_code)
        assert e.detail["upstream_status"] == "session_retired", (method, e.detail)
        assert [c.calls for c in built] == [1], (method, [c.calls for c in built])


def case_dead_session_on_a_replaced_client_keeps_the_fresh_one():
    def replaced_then_101(c):
        client_pool.evict(AID)         # another read's 101 evicted this one...
        client_pool.get(AID)           # ...and a later read built the fresh one
        raise _otp()                   # this read's own 101 comes back after both
    built = _with_pool([replaced_then_101, lambda c: {"ok": True}])
    e = _status("GET")
    assert e.status_code == 502 and e.detail["upstream_status"] == 400, (e.status_code, e.detail)
    assert len(built) == 2 and client_pool._POOL.get(AID) is built[1], "fresh client evicted"
    assert not built[1].retired, "fresh client's signed sessions retired"
    assert _proxy("GET") == {"ok": True}


def case_preloaded_client_late_101_keeps_the_fresh_one():
    def replaced_then_101(c):
        client_pool.evict(AID)
        client_pool.get(AID)
        raise _otp()
    built = _with_pool([replaced_then_101, lambda c: {"ok": True}])
    req = types.SimpleNamespace(method="POST", headers={"x-account-id": AID}, query_params={})
    token = server._request_ctx.set(req)
    try:
        stale = server._get_client()       # loaded outside _proxy, as mass_queue_api's send
        post = stale.read
        try:
            relay_host.proxy(lambda: post(), client=stale)
        except HTTPException as e:
            assert e.status_code == 502 and e.detail["upstream_status"] == 400, (e.status_code, e.detail)
        else:
            raise AssertionError("_proxy answered")
    finally:
        server._request_ctx.reset(token)
    assert len(built) == 2 and client_pool._POOL.get(AID) is built[1], "fresh client evicted"
    assert not built[1].retired, "fresh client's signed sessions retired"


def case_evict_only():
    built = _with_pool([lambda c: None, lambda c: None])
    stale = client_pool.get(AID)
    client_pool.evict(AID)
    fresh = client_pool.get(AID)
    client_pool.evict(AID, only=stale)
    assert client_pool._POOL.get(AID) is fresh and not fresh.retired
    client_pool.evict(AID, only=fresh)
    assert AID not in client_pool._POOL and fresh.retired
    assert built == [stale, fresh]


_harness.run()
