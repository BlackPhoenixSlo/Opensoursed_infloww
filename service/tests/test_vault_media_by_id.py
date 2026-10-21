#!/usr/bin/env python3
"""
of_client.vault_media_by_id WIRE URL — the by-id read that resolves a saved
Brain slot image (`time_images` stores bare media ids) back to a media object
with thumbnails.

OF exposes a single-item read at GET /api2/v2/vault/media/{id} (verified live:
the response is one media dict shaped like an item inside vault_media()['list'],
with files.thumb/squarePreview/preview). There is NO batch form, so these tests
pin that the method hits the per-id path (id coerced to int) and passes the
response straight back — a refactor can't quietly turn it into a list query.

  case_byid_path       : GET .../vault/media/<id>, no query params, dict passthrough
  case_byid_coerces_int: a numeric-string id is coerced so the path has no quotes

Run: ./venv/bin/python service/tests/test_vault_media_by_id.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import of_client  # noqa: E402


def _client():
    """An OFClient that skips __init__ (no session/signing) and captures the
    GET path instead of hitting the network."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.captured: list[tuple[str, dict | None]] = []

    def _get_json(path, params=None):  # type: ignore[no-untyped-def]
        c.captured.append((path, params))
        return {"id": 4513252122, "type": "photo",
                "files": {"thumb": {"url": "https://cdn/thumb.jpg"}}}

    c.get_json = _get_json  # type: ignore[attr-defined]
    return c


def case_byid_path():
    c = _client()
    out = c.vault_media_by_id(4513252122)
    path, params = c.captured[-1]
    assert path.endswith("/vault/media/4513252122"), path
    assert path.startswith(of_client.API_BASE), path
    # By-id is a bare path read — no query params (no batch/ids[] smuggling).
    assert params is None, params
    # Response is handed straight back so callers get the full media dict.
    assert out["id"] == 4513252122, out
    assert out["files"]["thumb"]["url"], out


def case_byid_coerces_int():
    # A numeric-string id (e.g. straight off a JSON config) must coerce to int
    # so the path is .../vault/media/123, never .../vault/media/'123'.
    c = _client()
    c.vault_media_by_id("4513252122")  # type: ignore[arg-type]
    path, _ = c.captured[-1]
    assert path.endswith("/vault/media/4513252122"), path
    assert "'" not in path and '"' not in path, path


_harness.run(
    case_byid_path,
    case_byid_coerces_int,
)
