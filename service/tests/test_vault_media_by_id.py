#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import of_client  # noqa: E402


def _client():
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.captured: list[tuple[str, dict | None]] = []

    def _get_json(path, params=None):  # type: ignore[no-untyped-def]
        c.captured.append((path, params))
        return {"id": 4513252122, "type": "photo",
                "files": {"thumb": {"url": "https://cdn/thumb.jpg"}}}

    c.get_json = _get_json  # type: ignore[attr-defined]
    return c


# OF has a single-item read GET /vault/media/{id} and no batch form
def case_byid_path():
    c = _client()
    out = c.vault_media_by_id(4513252122)
    path, params = c.captured[-1]
    assert path.endswith("/vault/media/4513252122"), path
    assert path.startswith(of_client.API_BASE), path
    assert params is None, params
    # Response is handed straight back so callers get the full media dict.
    assert out["id"] == 4513252122, out
    assert out["files"]["thumb"]["url"], out


def case_byid_coerces_int():
    c = _client()
    c.vault_media_by_id("4513252122")  # type: ignore[arg-type]
    path, _ = c.captured[-1]
    assert path.endswith("/vault/media/4513252122"), path
    assert "'" not in path and '"' not in path, path


_harness.run(
    case_byid_path,
    case_byid_coerces_int,
)
