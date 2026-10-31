"""service/tests/test_of_client_retry_table.py — of_client.retry_step, the pure
decision `_proxy_retry` makes after each failed attempt, as a table; plus the
wiring: `_proxy_retry` sleeps what it says, records proxy_health what it says,
and `_http_call` reads `of_client.INTERACTIVE_RETRY` at call time (slop's
faults reassign it).

A bare OFClient via __new__ with a fake fn, so nothing reaches the network.

Run:  ./venv/bin/python service/tests/test_of_client_retry_table.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import types  # noqa: E402

from curl_cffi import requests  # noqa: E402
from curl_cffi.const import CurlECode  # noqa: E402

import of_client  # noqa: E402
from of_client import (  # noqa: E402
    API_BASE, FULL_RETRY, INTERACTIVE_READ, INTERACTIVE_RETRY, OFClient, Raise, Retry,
    retry_step,
)

F, I = FULL_RETRY, INTERACTIVE_RETRY
NOCOUNT = FULL_RETRY._replace(counts=False)

# (policy, attempt, exc_kind, proxied) -> expected
TABLE = [
    # ProxyError: retried with a doubling pause (the sticky IP: same session)...
    (F, 0, "proxy", True, Retry(0.4)),
    (F, 1, "proxy", True, Retry(0.8)),
    (F, 2, "proxy", True, Retry(1.6)),
    (F, 3, "proxy", True, Retry(3.2)),
    (F, 3, "proxy", False, Retry(3.2)),
    (I, 0, "proxy", True, Retry(0.2)),
    # ...until the last try, whose failure counts only under a counting policy.
    (F, 4, "proxy", True, Raise(True)),
    (F, 4, "proxy", False, Raise(True)),
    (I, 1, "proxy", True, Raise(False)),
    (NOCOUNT, 4, "proxy", True, Raise(False)),
    (I._replace(counts=True), 1, "proxy", True, Raise(True)),
    # curl 7 (couldn't connect): never retried; counts only when proxied.
    (F, 0, "couldnt_connect", True, Raise(True)),
    (F, 0, "couldnt_connect", False, Raise(False)),
    (I, 0, "couldnt_connect", True, Raise(False)),
    (F, 2, "couldnt_connect", True, Raise(True)),
    # Any other ConnectionError: raised, never counted.
    (F, 0, "connection", True, Raise(False)),
    (I, 0, "connection", False, Raise(False)),
]


def case_retry_step_table():
    for policy, attempt, kind, proxied, want in TABLE:
        got = retry_step(policy, attempt, kind, proxied)
        assert type(got) is type(want) and got == want, (policy, attempt, kind, proxied, got, want)


def case_full_pauses_double_over_five_tries():
    pauses = [s.pause for a in range(F.tries)
              if isinstance(s := retry_step(F, a, "proxy", True), Retry)]
    assert pauses == [0.4, 0.8, 1.6, 3.2], pauses


def _bare(proxy_url="http://u:p@host:1234"):
    c = OFClient.__new__(OFClient)
    c.account_id = c.user_id = "999"
    c.proxy_label = "px1"
    c.proxy_url = proxy_url
    return c


class _Spy:
    """Captures of_client.time.sleep and of_client.proxy_health.record."""
    def __enter__(self):
        self.sleeps, self.records = [], []
        self._sleep, self._record = of_client.time.sleep, of_client.proxy_health.record
        of_client.time.sleep = self.sleeps.append
        of_client.proxy_health.record = lambda *a: self.records.append(a)
        return self

    def __exit__(self, *_):
        of_client.time.sleep, of_client.proxy_health.record = self._sleep, self._record


def _raising(exc, calls):
    def fn():
        calls.append(1)
        raise exc
    return fn


def case_proxy_retry_full_sleeps_then_counts_once():
    c, calls = _bare(), []
    err = requests.exceptions.ProxyError("CONNECT 403")
    with _Spy() as spy:
        try:
            c._proxy_retry(_raising(err, calls), what="t", policy=F)
        except requests.exceptions.ProxyError:
            pass
        else:
            raise AssertionError("no raise")
    assert len(calls) == 5, calls
    assert spy.sleeps == [0.4, 0.8, 1.6, 3.2], spy.sleeps
    assert spy.records == [("px1", False, "CONNECT 403")], spy.records


def case_proxy_retry_interactive_does_not_count():
    c, calls = _bare(), []
    with _Spy() as spy:
        try:
            c._proxy_retry(_raising(requests.exceptions.ProxyError("x"), calls), policy=I)
        except requests.exceptions.ProxyError:
            pass
    assert len(calls) == 2 and spy.sleeps == [0.2] and spy.records == [], (calls, spy.sleeps, spy.records)


def case_proxy_retry_curl7_proxied_vs_direct():
    for proxy_url, want in (("http://u:p@h:1", [("px1", False, "refused")]), (None, [])):
        c, calls = _bare(proxy_url), []
        err = requests.exceptions.ConnectionError("refused", code=CurlECode.COULDNT_CONNECT)
        with _Spy() as spy:
            try:
                c._proxy_retry(_raising(err, calls), policy=F)
            except requests.exceptions.ConnectionError:
                pass
        assert len(calls) == 1 and spy.sleeps == [] and spy.records == want, (proxy_url, spy.records)


def case_proxy_retry_other_connection_error_not_counted():
    c, calls = _bare(), []
    err = requests.exceptions.ConnectionError("reset", code=CurlECode.RECV_ERROR)
    with _Spy() as spy:
        try:
            c._proxy_retry(_raising(err, calls), policy=F)
        except requests.exceptions.ConnectionError:
            pass
    assert len(calls) == 1 and spy.records == [], spy.records


def case_proxy_retry_reraises_same_object_and_passes_others_through():
    """One except clause for ProxyError|ConnectionError: the caller still gets
    the very exception raised, and anything else leaves untouched on try one."""
    errs = (requests.exceptions.ProxyError("p"),
            requests.exceptions.ConnectionError("c", code=CurlECode.COULDNT_CONNECT),
            requests.exceptions.ConnectionError("r", code=CurlECode.RECV_ERROR),
            requests.exceptions.Timeout("t"), RuntimeError("boom"))
    for err in errs:
        c, calls = _bare(), []
        with _Spy() as spy:
            try:
                c._proxy_retry(_raising(err, calls), policy=I)
            except BaseException as got:  # noqa: BLE001 — identity is the assertion
                assert got is err, (err, got)
            else:
                raise AssertionError("no raise")
        if isinstance(err, (requests.exceptions.ProxyError, requests.exceptions.ConnectionError)):
            continue
        assert len(calls) == 1 and spy.sleeps == [] and spy.records == [], (err, calls, spy.records)


def case_proxy_retry_recovers_after_a_blip():
    c, n = _bare(), []

    def fn():
        n.append(1)
        if len(n) < 3:
            raise requests.exceptions.ProxyError("blip")
        return "ok"
    with _Spy() as spy:
        assert c._proxy_retry(fn, policy=F) == "ok"
    assert spy.sleeps == [0.4, 0.8] and spy.records == [], (spy.sleeps, spy.records)


def case_interactive_retry_global_read_at_call_time():
    """slop/lib/faults.py reassigns of_client.INTERACTIVE_RETRY; _http_call must see it."""
    sent = []

    def _get(url, *a, **kw):
        sent.append(url)
        raise requests.exceptions.ProxyError("CONNECT 403")
    c = _bare()
    c.user_agent, c.timeout_s, c._x_hash = "ua", 5, "HASH"
    c._signed_headers = lambda url: {}
    c.http = types.SimpleNamespace(get=_get)
    saved = of_client.INTERACTIVE_RETRY
    of_client.INTERACTIVE_RETRY = saved._replace(tries=3)
    token = INTERACTIVE_READ.set(True)
    try:
        with _Spy() as spy:
            try:
                c.request("GET", f"{API_BASE}/chats")
            except requests.exceptions.ProxyError:
                pass
    finally:
        INTERACTIVE_READ.reset(token)
        of_client.INTERACTIVE_RETRY = saved
    assert len(sent) == 3 and spy.sleeps == [0.2, 0.4], (sent, spy.sleeps)


_harness.run()
