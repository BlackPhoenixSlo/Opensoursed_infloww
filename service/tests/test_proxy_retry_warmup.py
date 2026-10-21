"""service/tests/test_proxy_retry_warmup.py — the x-hash / egress warmup
fetches must funnel through OFClient._proxy_retry, same as real OF calls.

Regression guard for the bug where _ensure_x_hash() ran a RAW self.http.get
outside _http_call's retry (and outside its try/except), so a single
datacenter CONNECT-403 blip failed the whole automation tick/job in ~78ms
with no retry — because _make_client builds a fresh client every tick, the
unprotected warmup fired on the first signed request of every run.

No DB / no _harness needed: we build a bare OFClient via __new__ and inject a
fake self.http, so this runs as a plain script like the rest of the suite.
"""
import sys
import os
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from curl_cffi import requests  # noqa: E402
import of_client  # noqa: E402
from of_client import OFClient  # noqa: E402

_PROXY_403 = "Failed to perform, curl: (56) CONNECT tunnel failed, response 403"


def _bare_client(http):
    """An OFClient with just the attrs _ensure_x_hash / egress_ip touch — no
    session load, no network at construction."""
    c = OFClient.__new__(OFClient)
    c.account_id = "TEST"
    c.user_id = "999"
    c.user_agent = "ua"
    c.timeout_s = 5
    c._x_hash = None
    c.proxy_label = "dc"
    c.proxy_url = "http://u:p@host:1234"
    c.http = http
    return c


class _Resp:
    def __init__(self, text="  HASHVAL  ", ok=True):
        self.text = text
        self.ok = ok

    def raise_for_status(self):
        pass


def case_xhash_retries_then_succeeds():
    """Transient ProxyError on the first 2 attempts → retried, 3rd succeeds.
    The >=1200ms wall time proves the 0.4s + 0.8s _proxy_retry pauses actually
    ran (i.e. this isn't the old fast-fail path)."""
    calls = {"n": 0}

    def flaky_get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ProxyError(_PROXY_403)
        return _Resp()

    c = _bare_client(types.SimpleNamespace(get=flaky_get))
    t0 = time.monotonic()
    h = c._ensure_x_hash()
    dt = (time.monotonic() - t0) * 1000
    assert h == "HASHVAL", h
    assert calls["n"] == 3, calls["n"]
    assert dt >= 1200, f"expected 0.4s + 0.8s pauses, got {dt:.0f}ms"


def case_xhash_cached_after_first_fetch():
    """Second call returns the cached value — no second network hit."""
    calls = {"n": 0}

    def count_get(url, **kw):
        calls["n"] += 1
        return _Resp()

    c = _bare_client(types.SimpleNamespace(get=count_get))
    c._ensure_x_hash()
    c._ensure_x_hash()
    assert calls["n"] == 1, calls["n"]


def case_xhash_persistent_failure_raises_after_five():
    """A genuinely dead/blocked proxy still surfaces (we don't retry forever)
    — exactly `tries` attempts with doubling pauses, then the ProxyError
    propagates."""
    calls = {"n": 0}
    pauses = []

    def always_fail(url, **kw):
        calls["n"] += 1
        raise requests.exceptions.ProxyError(_PROXY_403)

    c = _bare_client(types.SimpleNamespace(get=always_fail))
    real_sleep = of_client.time.sleep
    of_client.time.sleep = pauses.append
    try:
        c._ensure_x_hash()
        assert False, "should have raised ProxyError"
    except requests.exceptions.ProxyError:
        assert calls["n"] == 5, calls["n"]
        assert pauses == [0.4, 0.8, 1.6, 3.2], pauses
    finally:
        of_client.time.sleep = real_sleep


def case_egress_ip_retries_then_succeeds():
    """egress_ip swallows failures (returns None), but should still retry the
    transient blip rather than give up on the first 403."""
    calls = {"n": 0}

    def flaky_get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.exceptions.ProxyError(_PROXY_403)
        return _Resp(text="1.2.3.4")

    c = _bare_client(types.SimpleNamespace(get=flaky_get))
    ip = c.egress_ip()
    assert ip == "1.2.3.4", ip
    assert calls["n"] == 2, calls["n"]


def _run(*cases):
    for fn in cases:
        fn()
        print(f"[ok] {fn.__name__}")
    print("all proxy-retry warmup tests passed")


if __name__ == "__main__":
    _run(
        case_xhash_retries_then_succeeds,
        case_xhash_cached_after_first_fetch,
        case_xhash_persistent_failure_raises_after_five,
        case_egress_ip_retries_then_succeeds,
    )
