"""automations/_jev.py — what the Jev gates share: the TypeSafe transport and how a stored message reads.

Not a stream: it registers no kind and holds no outbound primitive. Each gate
(the FM off-script gate; `_router_jev`, Full AI Chat's
Router) keeps its own questions, thresholds and model pin, and its own one-line
`_client` (the tests' fake seam) over `client` here.

  - `q(instructions, true, false)`: one Noul's wording.
  - `text(body, media_count, max_chars)`: one stored message as a person reads
    it: OF's HTML stripped and unescaped; a media-only message is `MEDIA_ONLY`.
  - `client(key, model, timeout_s, max_retries)`: one cached async client per
    event loop, key and settings (connections are reused).
  - `ask_one(client_of, account_id, st, questions, model, timeout_s, error)`: one
    request on the account's key under a wall-clock cap; `(result, ms)` or `error`.
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from typing import Any

MEDIA_ONLY = "[sent a photo or video]"


def q(instructions: str, true: str, false: str) -> dict[str, Any]:
    return {"instructions": instructions, "criteria": {"true": true, "false": false}}


_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<\s*(?:br|/p)\s*/?>", re.I)


def text(body: str | None, media_count: int | None = 0, max_chars: int | None = None) -> str:
    """A stored message as a person reads it (OF bodies are HTML), cut to
    `max_chars` when one is given."""
    t = html.unescape(_TAG.sub("", _BR.sub("\n", body or ""))).strip()
    t = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", t))
    if not t and media_count:
        return MEDIA_ONLY
    return t if max_chars is None else t[:max_chars]


_clients: dict[tuple[int, str, str, float, int], Any] = {}


def client(key: str, model: str, timeout_s: float, max_retries: int) -> Any:
    """One async client per event loop, key and settings."""
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
    k = (id(asyncio.get_running_loop()), key, model, timeout_s, max_retries)
    c = _clients.get(k)
    if c is None:
        if len(_clients) > 8:       # old test loops: drop them, never grow
            _clients.clear()
        c = _clients[k] = AsyncTypeSafeClient(
            api_key=key, model=model,
            retry=RetryPolicy(max_retries=max_retries, timeout=timeout_s))
    return c


async def ask_one(client_of: Any, account_id: str | None, st: dict[str, Any], questions: dict[str, Any],
                  model: str, timeout_s: float | None, error: type[Exception]) -> tuple[Any, int]:
    """One `system_one` request on `account_id`'s TypeSafe key within `timeout_s` wall-clock
    seconds (None: no cap past the SDK's per-operation timeout). `(result, request ms)`; raises
    `error` on any failure: no budget left, no key, SDK missing, HTTP, timeout."""
    from tenant_keys import typesafe_key_for
    if timeout_s is not None and timeout_s <= 0:
        raise error("deadline")
    try:
        key = await typesafe_key_for(account_id)   # DB reads: may raise
        if not key:
            raise error("no TypeSafe key (agency or TYPESAFE_API_KEY)")
        t0 = time.perf_counter()   # Jev wall time is the request alone, not the key read
        res = await asyncio.wait_for(client_of(key).system_one(st, questions, model=model), timeout_s)
        return res, int((time.perf_counter() - t0) * 1000)
    except error:
        raise
    except Exception as e:      # SDK missing, HTTP, timeout
        raise error(f"{type(e).__name__}: {e}"[:300]) from e
