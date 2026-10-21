#!/usr/bin/env python3
"""
The Vault page's folder Search and its media "Go to date" (OF Manager), read-only.

Wire shapes from OF's web bundle: the folder column's Search is
GET /api2/v2/vault/lists?view=main&...&query=<text> (an empty search sends no
query); "Go to date" is GET /api2/v2/vault/media?...&beforePublishDate=YYYY-MM-DD
("All time" sends nothing).

  case_lists_query_wire     : vault_lists sends `query` only when it has text
  case_media_before_wire    : vault_media sends `beforePublishDate` only when set
  case_cache_keys           : each is in its cache key; the keys without them are unchanged
  case_routes_pass_them     : the routes forward them to the client and key the cache on them
  case_before_date_pattern  : the route only takes YYYY-MM-DD

Run: ./venv/bin/python service/tests/test_vault_search_go_to_date.py
"""
from __future__ import annotations

import _harness  # MUST be first

_harness.bootstrap()

import re  # noqa: E402

import of_client  # noqa: E402
import server  # noqa: E402


def _client():
    """An OFClient that skips __init__ and captures each GET instead of sending it."""
    c = of_client.OFClient.__new__(of_client.OFClient)
    c.captured = []

    def _get_json(path, params=None):  # type: ignore[no-untyped-def]
        c.captured.append((path, dict(params or {})))
        return {"list": [], "hasMore": False}

    c.get_json = _get_json  # type: ignore[attr-defined]
    return c


def case_lists_query_wire():
    c = _client()
    c.vault_lists(view="main", limit=50, offset=0, query="  beach ")
    path, params = c.captured[-1]
    assert path.endswith("/vault/lists"), path
    assert params == {"view": "main", "limit": 50, "offset": 0, "query": "beach"}, params
    for empty in (None, "", "   "):
        c.vault_lists(view="main", limit=50, offset=0, query=empty)
        assert "query" not in c.captured[-1][1], c.captured[-1]


def case_media_before_wire():
    c = _client()
    c.vault_media(limit=24, before_publish_date="2026-09-08")
    assert c.captured[-1][1]["beforePublishDate"] == "2026-09-08", c.captured[-1]
    c.vault_media(limit=24)
    assert "beforePublishDate" not in c.captured[-1][1], c.captured[-1]


def case_cache_keys():
    # The keys every existing caller (and test_chatter_access) builds are unchanged.
    assert server.vault_lists_cache_key(view="main", limit=50, offset=0) == "lists:view=main|limit=50|offset=0"
    assert server.vault_media_cache_key() == "media:type=all|list=None|offset=0|limit=24|sort=desc|field=recent|query="
    assert server.vault_lists_cache_key(view="main", limit=50, offset=0, q_norm="beach") == "lists:view=main|limit=50|offset=0|query=beach"
    assert server.vault_media_cache_key(before="2026-09-08").endswith("|before=2026-09-08")


async def case_routes_pass_them():
    c = _client()
    calls: dict[str, list] = {"get": [], "put": []}

    async def _get(aid, key):
        calls["get"].append(key)
        return None

    async def _put(aid, key, payload):
        calls["put"].append(key)

    async def _no_gate(aid):
        return None

    saved = (server._get_client, server._resolve_account_id, server._allowed_folder_ids_for_chatter,
             server.vault_cache.get, server.vault_cache.put)
    server._get_client = lambda *a, **k: c  # type: ignore[assignment]
    server._resolve_account_id = lambda *a, **k: "acc1"  # type: ignore[assignment]
    server._allowed_folder_ids_for_chatter = _no_gate  # type: ignore[assignment]
    server.vault_cache.get, server.vault_cache.put = _get, _put  # type: ignore[assignment]
    try:
        await server.of_vault_lists(view="main", limit=50, offset=0, query=" beach ", refresh=False)
        assert c.captured[-1][1].get("query") == "beach", c.captured[-1]
        assert calls["put"][-1] == "lists:view=main|limit=50|offset=0|query=beach", calls
        await server.of_vault_media(limit=24, offset=0, type="all", list_id=None, sort="desc",
                                    field="recent", query=None, before_publish_date="2026-09-08",
                                    refresh=False)
        assert c.captured[-1][1].get("beforePublishDate") == "2026-09-08", c.captured[-1]
        assert calls["put"][-1].endswith("|before=2026-09-08"), calls
    finally:
        (server._get_client, server._resolve_account_id, server._allowed_folder_ids_for_chatter,
         server.vault_cache.get, server.vault_cache.put) = saved


def case_before_date_pattern():
    route = next(r for r in server.app.routes if getattr(r, "path", "") == "/api/of/v2/vault/media")
    param = next(p for p in route.dependant.query_params if p.name == "before_publish_date")
    pattern = next(m.pattern for m in param.field_info.metadata if hasattr(m, "pattern"))
    assert re.fullmatch(pattern, "2026-09-08")
    for bad in ("2026-9-8", "08/09/2026", "2026-09-08T00:00", "x"):
        assert not re.fullmatch(pattern, bad), bad


_harness.run(
    case_lists_query_wire,
    case_media_before_wire,
    case_cache_keys,
    case_routes_pass_them,
    case_before_date_pattern,
)
