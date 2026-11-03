"""The media upload's part of the slop relay (lib/relay.py loads it; `wire` runs at the end of its `_wire`).
No `OF` class: the upload is the REAL `OFClient` (service/of_upload.py) against lib/of_wire.py.

Only under `OF_API_ORIGIN` (a scenario's `OF_WIRE`); without it this module does nothing. The product's
convert claim (`UploadMixin.convert_register`) posts to a hard-coded `https://convert.onlyfans.com/file/upload`,
the one host on the upload path that `OF_API_ORIGIN` does not cover (the S3 host comes from the fake's own
`putUrl`). So `curl_cffi.requests.Session.request` is wrapped: a request to `convert.onlyfans.com` goes to
`$OF_API_ORIGIN/convert/<path>` instead (lib/of_wire.py's `POST /convert/file/upload`), everything else is
untouched. The wrap sits outside relay.py's `_guard_curl_cffi` (that guard runs earlier in `_wire`), so the
rewritten URL is loopback and every other off-host target is still refused and logged.

Bypass, declared: the convert host is rewritten in curl_cffi, in the relay process (no DNS or TLS to it);
the request's method, headers, multipart body and timeout are the product's.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

CONVERT_HOST = "convert.onlyfans.com"


def wire(app, loopback, relay) -> None:
    origin = os.environ.get("OF_API_ORIGIN", "").rstrip("/")
    if not origin:
        return
    from curl_cffi import requests as cffi
    inner = cffi.Session.request

    def to_fake(self, method, url, *a, **k):
        u = urlsplit(str(url))
        if u.hostname == CONVERT_HOST:
            url = f"{origin}/convert{u.path}" + (f"?{u.query}" if u.query else "")
        return inner(self, method, url, *a, **k)

    # Copied so a later `_guard_curl_cffi()` (relay.py) skips it: re-wrapped, it would refuse convert pre-rewrite.
    to_fake.__slop_guard__ = getattr(inner, "__slop_guard__", False)
    cffi.Session.request = to_fake
