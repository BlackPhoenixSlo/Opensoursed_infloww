#!/usr/bin/env python3
"""Proxy probes (service/proxy_probe.py) and the Test button.

Pins: `probe` is ONE GET of Cloudflare's cdn-cgi/trace through the proxy (never OnlyFans, never without
the proxy) and reads ip / country / colo and the time to first byte; a failed or garbled probe is not ok.
`probe_of` (the health probe) is one cookie-less GET of robots.txt on the API's own host. The Test
button's `ok` is probe_of's, the trace beside it display and region only, neither counted; a failed
trace keeps the last verified egress. /admin/proxies carries `health`.

No network: the curl session and the probes are fakes.

Run:  ./venv/bin/python service/tests/test_proxy_probe.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

import types  # noqa: E402

from curl_cffi import CurlInfo, requests as curl_requests  # noqa: E402

import proxies  # noqa: E402
import proxy_health  # noqa: E402
import proxy_health_decide  # noqa: E402
import proxy_probe  # noqa: E402
from _proxy_health_fixtures import _registry  # noqa: E402


_TRACE = "fl=1\nh=1.1.1.1\nip=203.0.113.7\nts=1\nvisit_scheme=https\nloc=HU\ncolo=BUD\nhttp=http/2\n"


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


def _probe_with(reply, fn=None):
    real = curl_requests.Session
    _FakeSession.calls, _FakeSession.reply = [], reply
    curl_requests.Session = _FakeSession
    try:
        return (fn or proxy_probe.probe)(proxies.get_by_label("hu-1"))
    finally:
        curl_requests.Session = real


def _resp(text=_TRACE, status=200, ttfb=0.1234):
    return types.SimpleNamespace(status_code=status, text=text,
                                 infos={CurlInfo.STARTTRANSFER_TIME: ttfb})


def case_parse_trace():
    t = proxy_probe.parse_trace(_TRACE)
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
    assert out["ok"] is False and "407" in out["error"] and out["refused"] is True, out
    from curl_cffi.const import CurlECode
    out = _probe_with(curl_requests.exceptions.Timeout("Operation timed out", CurlECode.OPERATION_TIMEDOUT))
    assert out["ok"] is False and out["refused"] is False, "a timeout is not a refused CONNECT"
    out = _probe_with(_resp(status=502))
    assert out["ok"] is False and "502" in out["error"], out
    out = _probe_with(_resp(text="<html>captive portal</html>"))
    assert out["ok"] is False and out["ip"] is None, out


def case_probe_of_gets_the_api_host_with_no_session():
    """The health probe: one GET of robots.txt on the host the API CONNECTs to (not the x-hash CDN), Chrome's
    TLS, no cookie or header; any HTTP answer is ok (the tunnel to OF opened), a refused CONNECT is refused."""
    import of_client
    _registry()
    out = _probe_with(_resp(text="", status=403), fn=proxy_probe.probe_of)
    assert out == {"ok": True, "ttfb_ms": 123, "error": None}, out
    (url, kw, session_kw), = _FakeSession.calls
    assert url == f"{of_client.OF_WEB_ORIGIN}/robots.txt" and of_client.API_BASE.startswith(of_client.OF_WEB_ORIGIN), url
    assert set(kw) == {"proxies", "timeout"} and session_kw["impersonate"] == of_client.IMPERSONATE, (kw, session_kw)
    out = _probe_with(curl_requests.exceptions.ProxyError("CONNECT tunnel failed, response 403"), fn=proxy_probe.probe_of)
    assert out["ok"] is False and out["refused"] is True and "403" in out["error"], out


_TRACE_HU = {"ok": True, "ip": "203.0.113.7", "geo": "HU", "colo": "BUD", "ttfb_ms": 80, "error": None}


def _test_click(label: str, of_ok: bool, traced: bool = True) -> dict:
    """The Test button with the trace answering `traced` and probe_of answering `of_ok` (refused when not)."""
    import proxies_admin_api
    real = proxy_probe.probe, proxy_probe.probe_of
    proxy_probe.probe = lambda p, timeout_s=15: (
        dict(_TRACE_HU) if traced else {"ok": False, "ip": None, "geo": None, "colo": None, "error": "timeout"})
    proxy_probe.probe_of = lambda p, timeout_s=15: (
        {"ok": True, "ttfb_ms": 90, "error": None} if of_ok else
        {"ok": False, "ttfb_ms": None, "error": "proxy_probe_failed: CONNECT 403", "refused": True})
    try:
        return proxies_admin_api.admin_proxies_test(label)
    finally:
        proxy_probe.probe, proxy_probe.probe_of = real


def case_routes_carry_health():
    _registry()
    import server   # route functions called directly: no request user, the unauthed path  # noqa: F401
    import proxies_admin_api
    out = _test_click("hu-1", True)
    assert out == {"ok": True, "error": None, "ttfb_ms": 90, "ip": "203.0.113.7", "geo": "HU", "colo": "BUD"}, out
    assert proxies.get_by_label("hu-1")["verified_geo"] == "HU", "the Test button still records"
    rows = {p["label"]: p for p in proxies_admin_api.admin_proxies_list()["proxies"]}
    h = rows["hu-1"]["health"]
    assert h["trace"] == {"ip": "203.0.113.7", "geo": "HU", "colo": "BUD"} and "probe" not in h, h
    assert rows["spare"]["health"] == {"down": False, "errors": 0, "state": "healthy", "inflight": 0, "inflight_peak": 0,
                                       "refusals": {"window_s": 600.0, "refused": 0, "calls": 0, "pct": 0.0}}, rows["spare"]
    assert rows["hu-1"]["health"]["refusals"]["calls"] == 0, "the Test trace is display only: never counted"
    assert rows["hu-1"]["health"]["state"] == "healthy"


# ── one health probe: probe_of; the trace is display and region only ──
def case_a_test_click_never_brings_a_down_proxy_back():
    _registry()
    proxy_health._state["hu-1"] = {**proxy_health_decide.blank(), "down": True, "bad_reason": "down", "errors": 3}
    assert _test_click("hu-1", True)["ok"], "probe_of answers: the click says ok"
    snap = proxy_health.snapshot("hu-1")
    assert snap["down"] and snap["errors"] == 3 and snap["refusals"]["calls"] == 0, snap
    assert snap["trace"]["geo"] == "HU" and proxy_health.last_geo({"label": "hu-1"}) == "HU", "ip/geo kept for display"


def case_a_test_click_says_not_ok_where_only_the_trace_answers():
    """The Test button's `ok` is the health probe's: a proxy answering Cloudflare's trace but refusing
    CONNECT to OF reads not ok (and verified_ip cleared), its ip still shown; nothing counted."""
    _registry()
    proxy_health._state.pop("hu-1", None)
    out = _test_click("hu-1", False)
    assert out["ok"] is False and "403" in out["error"] and out["ip"] == "203.0.113.7", out
    assert proxies.get_by_label("hu-1")["verified_ip"] is None, "a failed Test records not verified"
    snap = proxy_health.snapshot("hu-1")
    assert snap["errors"] == 0 and snap["refusals"]["calls"] == 0 and "probe" not in snap, snap


def case_a_test_click_whose_trace_fails_keeps_the_last_verified_egress():
    """OF answers but Cloudflare's trace does not (a provider blocking 1.1.1.1): ok, and the stored
    verified ip/geo (the row's "verified" text, the failover's region) are kept, not wiped, and shown."""
    _registry()
    assert _test_click("hu-1", True)["ok"]
    out = _test_click("hu-1", True, traced=False)
    p = proxies.get_by_label("hu-1")
    assert out["ok"] and (out["ip"], out["geo"]) == ("203.0.113.7", "HU"), out
    assert (p["verified_ip"], p["verified_geo"]) == ("203.0.113.7", "HU"), p


def case_probe_and_trace_keep_their_own_slots():
    proxy_health._state.pop("hu-1", None)
    proxy_health.note_trace("hu-1", {"ok": True, "ip": "203.0.113.7", "geo": "HU", "colo": "BUD"})
    proxy_health._keep_probe("hu-1", {"ok": False, "ttfb_ms": None, "error": "proxy_probe_failed: CONNECT 403",
                                      "refused": True})
    snap = proxy_health.snapshot("hu-1")
    assert snap["probe"] == {"ok": False, "ttfb_ms": None, "error": "proxy_probe_failed: CONNECT 403"}, snap
    assert snap["trace"] == {"ip": "203.0.113.7", "geo": "HU", "colo": "BUD"}, snap
    proxy_health.note_trace("hu-1", {"ok": False, "ip": None, "geo": None, "colo": None})
    assert proxy_health.snapshot("hu-1")["trace"]["geo"] == "HU", "a failed trace changes nothing"


if __name__ == "__main__":
    _harness.run()
