"""service/tests/test_of_client_deny_list.py — OFClient refuses, before
sending, every call that ends or reports on the Creator's own OF account:
`users/logout`, `users/delete/request`, a non-GET `sessions`, OF's
`/api2/v2/log` telemetry and the `bug*.onlyfans.com` reporter. Everything else
(a GET of `sessions` included) still goes out.

A bare OFClient via __new__ with a recording fake self.http, so nothing ever
reaches the network; the harness only for the Relay's answer to a refusal.
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import types  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from of_client import API_BASE, OFClient, OFDeniedError  # noqa: E402


class _Resp:
    ok = True
    status_code = 200
    text = "{}"
    headers: dict = {}

    def json(self):
        return {}


def _client():
    sent: list[tuple[str, str]] = []

    def _get(url, **_kw):
        sent.append(("GET", url))
        return _Resp()

    def _request(method, url, **_kw):
        sent.append((method, url))
        return _Resp()

    c = OFClient.__new__(OFClient)
    c.account_id = "TEST"
    c.user_id = "999"
    c.timeout_s = 5
    c._x_hash = "HASH"
    c.proxy_label = None
    c.proxy_url = None
    c.http = types.SimpleNamespace(get=_get, request=_request)
    c._signed_headers = lambda _url: {}
    return c, sent


def _refused(c, method, url):
    try:
        if method == "GET":
            c.get(url)
        else:
            c.request(method, url)
    except OFDeniedError:
        return True
    return False


def case_each_denied_call_is_refused_and_nothing_is_sent():
    c, sent = _client()
    for method, url in [
        ("POST", f"{API_BASE}/users/logout"),
        ("GET", f"{API_BASE}/users/logout"),
        ("POST", f"{API_BASE}/users/delete/request"),
        ("DELETE", f"{API_BASE}/sessions"),
        ("DELETE", f"{API_BASE}/sessions/123"),
        ("POST", f"{API_BASE}/sessions/123/"),
        ("POST", f"{API_BASE}/log"),
        ("GET", "/api2/v2/log?x=1"),
        ("POST", "https://bugs.onlyfans.com/api/report"),
        ("GET", "https://bugreport.onlyfans.com/"),
    ]:
        assert _refused(c, method, url), f"{method} {url} was not refused"
    assert sent == [], sent


def case_a_refusal_is_logged():
    c, _ = _client()
    seen: list[str] = []
    original = of_client.log_of.error
    of_client.log_of.error = lambda msg, *a, **_k: seen.append(msg % a)
    try:
        assert _refused(c, "POST", f"{API_BASE}/users/logout")
    finally:
        of_client.log_of.error = original
    assert len(seen) == 1 and "/api2/v2/users/logout" in seen[0] and "TEST" in seen[0], seen


def case_neighbouring_calls_still_go_out():
    c, sent = _client()
    for method, url in [
        ("GET", f"{API_BASE}/sessions"),
        ("GET", f"{API_BASE}/users/me"),
        ("PATCH", f"{API_BASE}/users/me"),
        ("GET", f"{API_BASE}/logins"),
        ("GET", f"{API_BASE}/users/delete"),
        ("GET", "https://onlyfans.com/api2/v2/users/list"),
    ]:
        assert not _refused(c, method, url), f"{method} {url} was refused"
    assert [m for m, _ in sent] == ["GET", "GET", "PATCH", "GET", "GET", "GET"], sent


def case_the_relay_answers_a_refusal_as_its_own_403_not_an_upstream_error():
    """OFDeniedError is an OFAPIError (every `except OFAPIError` still catches it), but server._proxy
    answers it as the Relay's refusal, never as OF's 502."""
    assert issubclass(OFDeniedError, of_client.OFAPIError)
    c, sent = _client()

    try:
        server._proxy(lambda: c.request("POST", f"{API_BASE}/users/logout"))
    except HTTPException as e:
        assert e.status_code == 403, e.status_code
        assert e.detail["upstream_status"] == "refused_by_relay", e.detail
        assert "users/logout" in e.detail["upstream_body"], e.detail
    else:
        raise AssertionError("_proxy let a refused call through")
    assert sent == []


_harness.run()
