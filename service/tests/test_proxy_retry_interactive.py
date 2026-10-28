"""service/tests/test_proxy_retry_interactive.py — a read someone is waiting on
fails fast on a dead proxy; background work and every write keep the full retry.

Prod 2026-10-28: a proxy answering CONNECT 403 made the Fan List, bell and
thread reads run _proxy_retry's 5 tries (0.4 + 0.8 + 1.6 + 3.2 s of pauses)
before the 502. server._proxy now marks a request that is not
`X-Priority: background` (of_client.INTERACTIVE_READ); its GETs, x-hash warmup
included, take INTERACTIVE_RETRY (2 tries, one 0.2 s pause). A write under the
same request, and anything with no request (ingest, automations), keeps 5.

A bare OFClient via __new__ with a fake self.http, so nothing reaches the
network; the harness for account_health (the write gate) and server._proxy.

Run:  ./venv/bin/python service/tests/test_proxy_retry_interactive.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import types  # noqa: E402

from curl_cffi import requests  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402
from of_client import API_BASE, INTERACTIVE_READ, OFClient  # noqa: E402

_PROXY_403 = "Failed to perform, curl: (56) CONNECT tunnel failed, response 403"
_FULL = [0.4, 0.8, 1.6, 3.2]


def _dead_client(x_hash="HASH"):
    """A client whose proxy refuses every CONNECT; `sent` counts each attempt
    as (method, url)."""
    sent: list[tuple[str, str]] = []

    def _fail(method):
        def call(url, *a, **_kw):
            if method == "REQUEST":
                method_, url = url, a[0]
            else:
                method_ = method
            sent.append((method_, url))
            raise requests.exceptions.ProxyError(_PROXY_403)
        return call

    c = OFClient.__new__(OFClient)
    c.account_id = c.user_id = "999"
    c.user_agent = "ua"
    c.timeout_s = 5
    c._x_hash = x_hash
    c.proxy_label = None
    c.proxy_url = "http://u:p@host:1234"
    c._signed_headers = lambda url: {}
    c.http = types.SimpleNamespace(get=_fail("GET"), request=_fail("REQUEST"))
    return c, sent


class _Pauses:
    def __enter__(self):
        self.seen, self._real = [], of_client.time.sleep
        of_client.time.sleep = self.seen.append
        return self.seen

    def __exit__(self, *_):
        of_client.time.sleep = self._real


def _call(c, method, *, interactive):
    token = INTERACTIVE_READ.set(interactive)
    try:
        c.request(method, f"{API_BASE}/chats")
    except requests.exceptions.ProxyError:
        return
    finally:
        INTERACTIVE_READ.reset(token)
    raise AssertionError("a dead proxy answered")


def case_interactive_read_gives_up_after_two_tries():
    c, sent = _dead_client()
    with _Pauses() as pauses:
        _call(c, "GET", interactive=True)
    assert len(sent) == 2, sent
    assert pauses == [0.2], pauses


def case_background_read_keeps_five_tries():
    c, sent = _dead_client()
    with _Pauses() as pauses:
        _call(c, "GET", interactive=False)
    assert len(sent) == 5, sent
    assert pauses == _FULL, pauses


def case_write_keeps_five_tries_even_when_someone_waits():
    """A send/mark-read under a user's request: never a different retry count."""
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        c, sent = _dead_client()
        with _Pauses() as pauses:
            _call(c, method, interactive=True)
        assert [m for m, _ in sent] == [method] * 5, (method, sent)
        assert pauses == _FULL, (method, pauses)


def case_interactive_read_xhash_warmup_fails_fast_too():
    """A fresh client's first signed read: the warmup must not spend the ~6 s
    the read itself no longer spends."""
    c, sent = _dead_client(x_hash=None)
    with _Pauses() as pauses:
        _call(c, "GET", interactive=True)
    assert len(sent) == 2 and all("/hash/" in u for _, u in sent), sent
    assert pauses == [0.2], pauses


def case_write_xhash_warmup_keeps_five_tries():
    c, sent = _dead_client(x_hash=None)
    with _Pauses() as pauses:
        _call(c, "POST", interactive=True)
    assert len(sent) == 5 and all("/hash/" in u for _, u in sent), sent
    assert pauses == _FULL, pauses


class _Counted:
    """proxy_health.record as seen by the client: the (label, ok) it reports."""
    def __enter__(self):
        self.seen, self._real = [], of_client.proxy_health.record
        of_client.proxy_health.record = lambda label, ok, error=None: self.seen.append((label, ok))
        return self.seen

    def __exit__(self, *_):
        of_client.proxy_health.record = self._real


def case_only_a_full_policy_failure_counts_toward_down():
    """docs/adr/0030: an interactive read gives up inside ~1 s, so three of them
    fit in one CONNECT-403 blip; only a full-policy (5-try) final failure is
    evidence the proxy is down."""
    for method, interactive, want in (("GET", True, []), ("GET", False, [("px", False)]),
                                      ("POST", True, [("px", False)])):
        c, _ = _dead_client()
        c.proxy_label = "px"
        with _Pauses(), _Counted() as seen:
            _call(c, method, interactive=interactive)
        assert seen == want, (method, interactive, seen)


def _refused_port_client(x_hash):
    """A proxied client whose proxy port refuses TCP: curl 7, which curl_cffi
    raises as ConnectionError (measured: a closed loopback port as the proxy)."""
    from curl_cffi.const import CurlECode
    sent: list[str] = []

    def _refused(url, *a, **_kw):
        sent.append(url)
        raise requests.exceptions.ConnectionError(
            "Failed to perform, curl: (7) Failed to connect to 127.0.0.1 port 9", CurlECode.COULDNT_CONNECT)
    c, _ = _dead_client(x_hash=x_hash)
    c.proxy_label = "px"
    c.http = types.SimpleNamespace(get=_refused, request=lambda m, url, **kw: _refused(url))
    return c, sent


def case_refused_proxy_port_counts_in_the_warmup_too():
    """F1: a fresh client on a curl-7-dead proxy fails in the x-hash warmup,
    before the signed call; it is counted there, once, and not retried."""
    for x_hash in (None, "HASH"):
        c, sent = _refused_port_client(x_hash)
        with _Pauses() as pauses, _Counted() as seen:
            try:
                c.request("POST", f"{API_BASE}/chats")
            except requests.exceptions.ConnectionError:
                pass
            else:
                raise AssertionError("a refused proxy answered")
        assert seen == [("px", False)] and len(sent) == 1 and pauses == [], (x_hash, seen, sent, pauses)
    c, _ = _refused_port_client(None)
    with _Pauses(), _Counted() as seen:
        try:
            _call(c, "GET", interactive=True)
        except requests.exceptions.ConnectionError:
            pass
    assert seen == [], "an interactive read's failure never counts"


def _under_request(headers, fn):
    req = None if headers is None else types.SimpleNamespace(headers=headers, query_params={})
    token = server._request_ctx.set(req)
    try:
        return server._proxy(fn)
    finally:
        server._request_ctx.reset(token)


def case_proxy_marks_only_a_waiting_request_interactive():
    assert _under_request({}, INTERACTIVE_READ.get) is True
    assert _under_request({"x-priority": "user"}, INTERACTIVE_READ.get) is True
    assert _under_request({"x-priority": "background"}, INTERACTIVE_READ.get) is False
    assert _under_request(None, INTERACTIVE_READ.get) is False, "no request: server-side job"
    assert INTERACTIVE_READ.get() is False, "the flag leaked out of _proxy"


def case_proxy_resets_the_flag_on_error():
    c, _ = _dead_client()
    with _Pauses():
        try:
            _under_request({}, lambda: c.get_json(f"{API_BASE}/chats"))
        except HTTPException:
            pass
    assert INTERACTIVE_READ.get() is False


def case_dead_proxy_read_is_a_502_after_two_tries():
    """End to end through the route wrapper: the UI's proxy_unreachable 502."""
    c, sent = _dead_client()
    with _Pauses() as pauses:
        try:
            _under_request({}, lambda: c.get_json(f"{API_BASE}/users/notifications"))
        except HTTPException as e:
            assert e.status_code == 502, e.status_code
            assert e.detail["upstream_status"] == "proxy_unreachable", e.detail
        else:
            raise AssertionError("_proxy answered a dead proxy")
    assert len(sent) == 2, sent
    assert pauses == [0.2], pauses


_harness.run()
