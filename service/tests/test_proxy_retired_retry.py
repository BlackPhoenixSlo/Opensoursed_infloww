from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
import logging  # noqa: E402
import types  # noqa: E402

from fastapi import HTTPException  # noqa: E402

import accounts as account_registry  # noqa: E402
import client_pool  # noqa: E402
import relay_host  # noqa: E402
from of_client import OFAPIError, OFSessionRetired, OFSignedPoolBusy  # noqa: E402

_harness.make_client()
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
    user_id, x_of_rev = 1, "rev"

    def __init__(self, answer) -> None:
        self.retired, self.calls, self._answer = False, 0, answer

    def read(self):
        self.calls += 1
        return self._answer(self)

    def close_signed_sessions(self) -> None:
        self.retired = True


def _with_pool(answers):
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


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.msgs.append(record.getMessage())


def _status_logged(method: str) -> tuple[HTTPException, list[str]]:
    h = _Lines()
    server.log.addHandler(h)
    try:
        return _status(method), [m for m in h.msgs if m.startswith("signed_pool_503 ")]
    finally:
        server.log.removeHandler(h)


MARKED: list[str] = []
server._kick_mark_session_dead = lambda aid, *a, **k: MARKED.append(aid)


def case_retired_read_reruns_on_the_current_client():
    built = _with_pool([_evicted_under_it, _answers_101])
    e = _status("GET")
    assert e.status_code == 502 and e.detail["upstream_status"] == 400, (e.status_code, e.detail)
    assert [c.calls for c in built] == [1, 1], [c.calls for c in built]
    assert built[0].retired and built[1].retired, "the fresh client met the 101 itself: it is evicted"


def _pool_busy(c):
    raise OFSignedPoolBusy()


def case_pool_busy_read_answers_503_without_a_rerun():
    built = _with_pool([_pool_busy])
    e, lines = _status_logged("GET")
    assert lines == [f"signed_pool_503 account={AID} reason=signed_pool_busy method=GET"], lines
    assert e.status_code == 503 and e.detail["upstream_status"] == "signed_pool_busy", (e.status_code, e.detail)
    assert (e.headers or {}).get("Retry-After") == "5", e.headers
    assert [c.calls for c in built] == [1], [c.calls for c in built]


def case_retired_read_twice_answers_503():
    built = _with_pool([_evicted_under_it, _evicted_under_it, lambda c: {"ok": True}])
    e, lines = _status_logged("GET")
    assert lines == [f"signed_pool_503 account={AID} reason=session_retired method=GET"], lines
    assert e.status_code == 503 and e.headers == {"Retry-After": "1"}, (e.status_code, e.headers)
    assert e.detail["upstream_status"] == "session_retired", e.detail
    assert [c.calls for c in built] == [1, 1], [c.calls for c in built]


def case_retired_write_is_not_rerun():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        built = _with_pool([_evicted_under_it, lambda c: {"ok": True}])
        e, lines = _status_logged(method)
        assert lines == [f"signed_pool_503 account={AID} reason=session_retired method={method}"], (method, lines)
        assert e.status_code == 503 and e.headers == {"Retry-After": "1"}, (method, e.status_code)
        assert e.detail["upstream_status"] == "session_retired", (method, e.detail)
        assert [c.calls for c in built] == [1], (method, [c.calls for c in built])


def case_dead_session_on_a_replaced_client_keeps_the_fresh_one():
    def replaced_then_101(c):
        client_pool.evict(AID)
        client_pool.get(AID)
        raise _otp()
    built = _with_pool([replaced_then_101, lambda c: {"ok": True}])
    MARKED.clear()
    e = _status("GET")
    assert e.status_code == 502 and e.detail["upstream_status"] == 400, (e.status_code, e.detail)
    assert len(built) == 2 and client_pool._POOL.get(AID) is built[1], "fresh client evicted"
    assert not built[1].retired, "fresh client's signed sessions retired"
    assert MARKED == [], f"late 101 from a retired client paused the Creator: {MARKED}"
    assert _proxy("GET") == {"ok": True}


def case_dead_session_on_the_pooled_client_marks_it():
    _with_pool([_answers_101])
    MARKED.clear()
    e = _status("GET")
    assert e.status_code == 502, e.status_code
    assert MARKED == [AID], MARKED


def case_preloaded_client_late_101_keeps_the_fresh_one():
    def replaced_then_101(c):
        client_pool.evict(AID)
        client_pool.get(AID)
        raise _otp()
    built = _with_pool([replaced_then_101, lambda c: {"ok": True}])
    req = types.SimpleNamespace(method="POST", headers={"x-account-id": AID}, query_params={})
    token = server._request_ctx.set(req)
    try:
        stale = server._get_client()
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
