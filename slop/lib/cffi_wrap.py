"""One wrap of `curl_cffi.requests.Session.request` for the relay parts that send an off-host URL to a loopback
fake (img_relay: the CDN hosts; upload_relay: convert.onlyfans.com). Not a relay part itself (no `_relay` suffix).

  wrap_request(route, mark)
       Wraps the current `Session.request`: per call, `route(session, parts, kwargs)` (parts = urlsplit of the URL)
       answers the URL to send instead (it may edit kwargs, e.g. headers) or None to send the call unchanged.
       `mark`: an attribute set True on the wrapper; when the current request already has it, nothing is wrapped
       (idempotent). The wrapper copies the wrapped one's `__slop_guard__`, so a wrap over relay.py's
       `_guard_curl_cffi()` stays skipped by it.
  path_query(parts)  the URL's path, plus `?query` when it has one.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def path_query(parts) -> str:
    return parts.path + (f"?{parts.query}" if parts.query else "")


def wrap_request(route, mark: str) -> None:
    from curl_cffi import requests as cffi
    inner = cffi.Session.request
    if getattr(inner, mark, False):
        return

    def request(self, method, url, *a, **k):
        to = route(self, urlsplit(str(url)), k)
        return inner(self, method, url if to is None else to, *a, **k)

    setattr(request, mark, True)
    request.__slop_guard__ = getattr(inner, "__slop_guard__", False)
    cffi.Session.request = request
