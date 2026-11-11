#!/usr/bin/env python3
"""of_origin.loopback_url: the one loopback rule for test seams that receive a
signed request or a secret (OF_API_ORIGIN via parse(), TURNSTILE_VERIFY_URL in
tracking_links_api._verify_url).

  case_loopback_url_accepts_only_loopback_http: scheme, host, userinfo, port.
  case_parse_still_wants_a_bare_origin: parse() keeps refusing a path / query
      and rebuilds the origin as before.

Run: ./venv/bin/python service/tests/test_of_origin.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

import of_origin  # noqa: E402


def case_loopback_url_accepts_only_loopback_http():
    ok = ["http://127.0.0.1:9/x", "https://localhost/x?y=1", "http://[::1]:8080"]
    bad = ["https://evil.example.com/x", "http://user:pw@127.0.0.1:9/x", "http://user@127.0.0.1/x",
           "http://127.0.0.1.evil.example/x", "ftp://127.0.0.1/x", "http://127.0.0.1:99999/x", "", "nonsense"]
    assert all(of_origin.loopback_url(u) is not None for u in ok), ok
    assert [u for u in bad if of_origin.loopback_url(u) is not None] == [], bad


def case_parse_still_wants_a_bare_origin():
    assert of_origin.parse("") == ""
    assert of_origin.parse(" http://127.0.0.1:8123/ ") == "http://127.0.0.1:8123"
    assert of_origin.parse("http://[::1]:9") == "http://[::1]:9"
    for raw in ("http://127.0.0.1:9/api2", "http://127.0.0.1:9/?q=1", "http://u:p@127.0.0.1:9",
                "https://onlyfans.com"):
        try:
            of_origin.parse(raw)
        except RuntimeError:
            continue
        raise AssertionError(f"parse accepted {raw!r}")


_harness.run()
