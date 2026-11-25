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
    calls = {"n": 0}

    def flaky_get(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ProxyError(_PROXY_403)
        return _Resp()

    c = _bare_client(types.SimpleNamespace(get=flaky_get))
    real_random, of_client.random = of_client.random, types.SimpleNamespace(random=lambda: 1.0)
    t0 = time.monotonic()
    try:
        h = c._ensure_x_hash()
    finally:
        of_client.random = real_random
    dt = (time.monotonic() - t0) * 1000
    assert h == "HASHVAL", h
    assert calls["n"] == 3, calls["n"]
    assert dt >= 1200, f"expected 0.4s + 0.8s pauses, got {dt:.0f}ms"


def case_xhash_cached_after_first_fetch():
    calls = {"n": 0}

    def count_get(url, **kw):
        calls["n"] += 1
        return _Resp()

    c = _bare_client(types.SimpleNamespace(get=count_get))
    c._ensure_x_hash()
    c._ensure_x_hash()
    assert calls["n"] == 1, calls["n"]


def case_xhash_persistent_failure_raises_after_five():
    for draw, want in ((1.0, [0.4, 0.8, 1.6, 3.2]), (0.0, [0.2, 0.4, 0.8, 1.6])):
        calls = {"n": 0}
        pauses = []

        def always_fail(url, **kw):
            calls["n"] += 1
            raise requests.exceptions.ProxyError(_PROXY_403)

        c = _bare_client(types.SimpleNamespace(get=always_fail))
        real_sleep, real_random = of_client.time.sleep, of_client.random
        of_client.time.sleep = pauses.append
        of_client.random = types.SimpleNamespace(random=lambda d=draw: d)
        try:
            c._ensure_x_hash()
            assert False, "should have raised ProxyError"
        except requests.exceptions.ProxyError:
            assert calls["n"] == 5, (draw, calls["n"])
            assert pauses == want, (draw, pauses)
        finally:
            of_client.time.sleep, of_client.random = real_sleep, real_random


def case_egress_ip_retries_then_succeeds():
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
