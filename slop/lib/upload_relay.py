from __future__ import annotations

import os

CONVERT_HOST = "convert.onlyfans.com"


def wire(app, loopback, relay) -> None:
    origin = os.environ.get("OF_API_ORIGIN", "").rstrip("/")
    if not origin:
        return
    from cffi_wrap import path_query, wrap_request

    def to_fake(_session, u, _k):
        return f"{origin}/convert" + path_query(u) if u.hostname == CONVERT_HOST else None

    wrap_request(to_fake, "__slop_upload__")
