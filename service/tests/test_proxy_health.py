#!/usr/bin/env python3
"""Proxy health (roadmap 2.14, service/proxy_health.py + proxies.probe).

Pins: the probe is ONE GET of Cloudflare's cdn-cgi/trace through the proxy
(never OnlyFans, never without the proxy) and reads ip / country / colo and
the time to first byte; a failed or garbled probe is not ok. DOWN_AFTER
errors in a row mark a proxy down and announce `proxy_switched` {down} to
each Creator on it; one answer brings it back up (announced too); a healthy
proxy staying healthy writes nothing. A ProxyError out of OFClient._http_call
counts as an error and an answer as a success. The Test route keeps the
probe in `health`, /admin/proxies carries `health`, /admin/accounts carries
`proxy_down`. The periodic probe is off unless PROXY_HEALTH_INTERVAL_S is
set, and probes only proxies a Creator is on.

No network: the curl session and the OF client's http are fakes.

Run:  ./venv/bin/python service/tests/test_proxy_health.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import os  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402

from curl_cffi import CurlInfo, requests as curl_requests  # noqa: E402

import events  # noqa: E402
import proxies  # noqa: E402
import proxy_health  # noqa: E402
from of_client import OFClient  # noqa: E402

_TRACE = "fl=1\nh=1.1.1.1\nip=203.0.113.7\nts=1\nvisit_scheme=https\nloc=HU\ncolo=BUD\nhttp=http/2\n"


def _registry() -> None:
    proxies.REGISTRY_PATH = Path(tempfile.mkdtemp(prefix="proxyhealth_")) / "proxies.json"
    proxies.upsert({"label": "hu-1", "scheme": "http", "host": "198.51.100.1", "port": 8080,
                    "username": "u", "password": "p"})
    proxies.upsert({"label": "spare", "scheme": "http", "host": "198.51.100.2", "port": 8080})
    proxies.assign_account("hu-1", "101")
    proxies.assign_account("hu-1", "102")
    proxy_health._state.clear()


class _Events:
    def __enter__(self):
        self.seen, self._real = [], events.publish_state
        events.publish_state = lambda t, **kw: self.seen.append((t, kw))
        return self

    def __exit__(self, *_):
        events.publish_state = self._real


class _FakeSession:
    calls: list = []
    reply = None

    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, url, **kw):
        _FakeSession.calls.append((url, kw, self.kw))
        if isinstance(_FakeSession.reply, Exception):
            raise _FakeSession.reply
        return _FakeSession.reply


def _probe_with(reply):
    real = curl_requests.Session
    _FakeSession.calls, _FakeSession.reply = [], reply
    curl_requests.Session = _FakeSession
    try:
        return proxies.probe(proxies.get_by_label("hu-1"))
    finally:
        curl_requests.Session = real


def _resp(text=_TRACE, status=200, ttfb=0.1234):
    return types.SimpleNamespace(status_code=status, text=text,
                                 infos={CurlInfo.STARTTRANSFER_TIME: ttfb})


def case_parse_trace():
    t = proxies.parse_trace(_TRACE)
    assert (t["ip"], t["loc"], t["colo"]) == ("203.0.113.7", "HU", "BUD"), t


def case_probe_reads_the_trace_through_the_proxy():
    _registry()
    out = _probe_with(_resp())
    assert out == {"ok": True, "ip": "203.0.113.7", "geo": "HU", "colo": "BUD",
                   "ttfb_ms": 123, "error": None}, out
    (url, kw, session_kw), = _FakeSession.calls
    assert url == "https://1.1.1.1/cdn-cgi/trace", "Cloudflare's trace, never OnlyFans"
    assert kw["proxies"] == {"http": "http://u:p@198.51.100.1:8080",
                             "https": "http://u:p@198.51.100.1:8080"}, kw
    assert CurlInfo.STARTTRANSFER_TIME in session_kw["curl_infos"]


def case_probe_failures_are_not_ok():
    _registry()
    out = _probe_with(curl_requests.exceptions.ProxyError("CONNECT tunnel failed, response 407"))
    assert out["ok"] is False and "407" in out["error"], out
    out = _probe_with(_resp(status=502))
    assert out["ok"] is False and "502" in out["error"], out
    out = _probe_with(_resp(text="<html>captive portal</html>"))
    assert out["ok"] is False and out["ip"] is None, out


def case_down_after_consecutive_errors_and_back_up():
    _registry()
    with _Events() as ev:
        for _ in range(proxy_health.DOWN_AFTER - 1):
            proxy_health.record("hu-1", False, "boom")
        assert not proxy_health.snapshot("hu-1")["down"] and ev.seen == []
        proxy_health.record("hu-1", False, "boom")
        snap = proxy_health.snapshot("hu-1")
        assert snap["down"] and snap["errors"] == proxy_health.DOWN_AFTER, snap
        assert sorted(ev.seen, key=lambda e: e[1]["account_id"]) == [
            ("proxy_switched", {"account_id": "101", "proxied": True, "down": True}),
            ("proxy_switched", {"account_id": "102", "proxied": True, "down": True}),
        ], ev.seen
        assert proxy_health.down_labels() == {"hu-1"}
        ev.seen.clear()
        proxy_health.record("hu-1", False, "boom")   # still down: no second announce
        assert ev.seen == []
        proxy_health.record("hu-1", True)
        assert not proxy_health.snapshot("hu-1")["down"]
        assert [e[1]["down"] for e in ev.seen] == [False, False], ev.seen


def case_an_answer_resets_the_count():
    _registry()
    for _ in range(proxy_health.DOWN_AFTER - 1):
        proxy_health.record("hu-1", False, "boom")
    proxy_health.record("hu-1", True)
    proxy_health.record("hu-1", False, "boom")
    assert proxy_health.snapshot("hu-1")["errors"] == 1, "errors must be consecutive"


def case_healthy_success_writes_nothing():
    _registry()
    proxy_health.record("hu-1", True)
    proxy_health.record(None, False, "direct: no proxy")
    assert proxy_health._state == {}


def _bare_client(get):
    c = OFClient.__new__(OFClient)
    c.account_id = "101"
    c.user_id = "101"
    c.proxy_label = "hu-1"
    c.proxy_url = "http://u:p@198.51.100.1:8080"
    c.timeout_s = 5
    c._x_hash = "x"
    c.http = types.SimpleNamespace(get=get)
    c._signed_headers = lambda url: {}
    c._proxy_retry = lambda fn, **kw: fn()
    c._persist_cf_cookies = lambda r: None
    return c


def case_of_calls_feed_the_state():
    _registry()

    def _refused(url, **kw):
        raise curl_requests.exceptions.ProxyError("CONNECT tunnel failed, response 403")
    c = _bare_client(_refused)
    with _Events():
        for _ in range(proxy_health.DOWN_AFTER):
            try:
                c._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
            except curl_requests.exceptions.ProxyError:
                pass
            else:
                raise AssertionError("the ProxyError must still reach the caller")
        assert proxy_health.snapshot("hu-1")["down"]
        ok = _bare_client(lambda url, **kw: types.SimpleNamespace(headers={}, ok=True))
        ok._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
    assert not proxy_health.snapshot("hu-1")["down"]


def case_a_refused_proxy_connect_counts_a_timeout_does_not():
    _registry()
    from curl_cffi.const import CurlECode

    def _raises(exc):
        def _get(url, **kw):
            raise exc
        return _bare_client(_get)
    with _Events():
        for exc in (curl_requests.exceptions.Timeout("Operation timed out", CurlECode.OPERATION_TIMEDOUT),
                    curl_requests.exceptions.ConnectionError("TLS reset", CurlECode.RECV_ERROR)):
            try:
                _raises(exc)._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
            except Exception:
                pass
        assert proxy_health.snapshot("hu-1")["errors"] == 0, "not told apart from OF: not counted"
        refused = curl_requests.exceptions.ConnectionError(
            "Failed to connect to 198.51.100.1 port 8080", CurlECode.COULDNT_CONNECT)
        try:
            _raises(refused)._http_call("GET", "https://onlyfans.com/api2/v2/users/me")
        except curl_requests.exceptions.ConnectionError:
            pass
        else:
            raise AssertionError("the error must still reach the caller")
        assert proxy_health.snapshot("hu-1")["errors"] == 1


def case_routes_carry_health():
    _registry()
    import server   # route functions called directly: no request user, the unauthed path
    real = proxies.probe
    proxies.probe = lambda p, timeout_s=15: {"ok": True, "ip": "203.0.113.7", "geo": "HU",
                                             "colo": "BUD", "ttfb_ms": 80, "error": None}
    try:
        out = server.admin_proxies_test("hu-1")
    finally:
        proxies.probe = real
    assert out["colo"] == "BUD", out
    assert proxies.get_by_label("hu-1")["verified_geo"] == "HU", "the Test button still records"
    rows = {p["label"]: p for p in server.admin_proxies_list()["proxies"]}
    assert rows["hu-1"]["health"]["probe"]["ttfb_ms"] == 80, rows["hu-1"]["health"]
    assert rows["spare"]["health"] == {"down": False, "errors": 0}, rows["spare"]


def case_accounts_list_flags_proxy_down():
    _registry()
    import server
    from fastapi import Response
    import asyncio
    fake_user = types.SimpleNamespace(account_ids={"101", "201"})
    real_user, real_list = server._get_request_user, server.account_registry.list_accounts
    server._get_request_user = lambda: fake_user
    server.account_registry.list_accounts = lambda: [{"id": "101"}, {"id": "201"}]
    try:
        for _ in range(proxy_health.DOWN_AFTER):
            proxy_health.record("hu-1", False, "boom")
        out = asyncio.run(server.admin_accounts_list(Response()))
    finally:
        server._get_request_user, server.account_registry.list_accounts = real_user, real_list
    flags = {a["id"]: a["proxy_down"] for a in out["accounts"]}
    assert flags == {"101": True, "201": False}, flags


def case_periodic_probe_is_opt_in():
    os.environ.pop(proxy_health.INTERVAL_ENV, None)
    assert proxy_health.interval_s() == 0
    os.environ[proxy_health.INTERVAL_ENV] = "60"
    try:
        assert proxy_health.interval_s() == proxy_health._MIN_INTERVAL_S, "floored, never chatty"
    finally:
        os.environ.pop(proxy_health.INTERVAL_ENV, None)


def case_probe_all_only_creator_proxies():
    _registry()
    probed: list[str] = []
    real = proxies.probe
    proxies.probe = lambda p, timeout_s=15: probed.append(p["label"]) or {"ok": True}
    try:
        assert proxy_health.probe_all() == 1
    finally:
        proxies.probe = real
    assert probed == ["hu-1"], "the unbound proxy is not probed"


if __name__ == "__main__":
    _harness.run()
