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
    t = html.unescape(_TAG.sub("", _BR.sub("\n", body or ""))).strip()
    t = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", t))
    if not t and media_count:
        return MEDIA_ONLY
    return t if max_chars is None else t[:max_chars]


_clients: dict[tuple[int, str, str, float, int], Any] = {}


def client(key: str, model: str, timeout_s: float, max_retries: int) -> Any:
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
    k = (id(asyncio.get_running_loop()), key, model, timeout_s, max_retries)
    c = _clients.get(k)
    if c is None:
        if len(_clients) > 8:
            _clients.clear()
        c = _clients[k] = AsyncTypeSafeClient(
            api_key=key, model=model,
            retry=RetryPolicy(max_retries=max_retries, timeout=timeout_s))
    return c


async def ask_one(client_of: Any, account_id: str | None, st: dict[str, Any], questions: dict[str, Any],
                  model: str, timeout_s: float | None, error: type[Exception]) -> tuple[Any, int]:
    from tenant_keys import typesafe_key_for
    if timeout_s is not None and timeout_s <= 0:
        raise error("deadline")
    try:
        key = await typesafe_key_for(account_id)
        if not key:
            raise error("no TypeSafe key (agency or TYPESAFE_API_KEY)")
        t0 = time.perf_counter()
        res = await asyncio.wait_for(client_of(key).system_one(st, questions, model=model), timeout_s)
        return res, int((time.perf_counter() - t0) * 1000)
    except error:
        raise
    except Exception as e:      # SDK missing, HTTP, timeout
        raise error(f"{type(e).__name__}: {e}"[:300]) from e
