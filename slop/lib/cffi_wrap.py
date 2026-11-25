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
