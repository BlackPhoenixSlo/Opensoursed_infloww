from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import automation_executor as ax
from of_shapes import queue_id

log = logging.getLogger(__name__)


def _media_of(m: dict) -> set[int]:
    return {int(x["id"]) for x in m.get("media") or []
            if isinstance(x, dict) and str(x.get("id", "")).isdigit()}


async def sent_ppv(client: Any, fan_id: int, since: datetime, price_cents: int, *,
                   media=None) -> dict:
    # A timeout often still delivers: one chat read; with media, only the single non-mass-copy message carrying exactly those media.
    try:
        data = await asyncio.to_thread(lambda: client.get_messages(fan_id, limit=10, peek=True))
    except Exception:
        log.warning("could not read back a failed PPV fan=%s", fan_id,
                    exc_info=True)
        return {}
    items = data.get("list") if isinstance(data, dict) else data
    want = None if media is None else {int(x) for x in media}
    # Floor: main's `at > since`; Full AI (media) the attempt's whole second on, as link_window (OF stamps whole seconds).
    floor = since.replace(microsecond=0)
    hits = []
    for m in items or []:
        if not isinstance(m, dict) or str((m.get("fromUser") or {}).get("id")) == str(fan_id):
            continue
        at = ax._parse_iso(m.get("createdAt"))
        if not (m.get("id") and ax._to_cents(m.get("price")) == int(price_cents) and at is not None
                and (at > since if want is None else at >= floor)):
            continue
        if want is None:
            return m
        if _media_of(m) == want and queue_id(m) is None:
            hits.append(m)
    if len(hits) > 1:
        log.warning("PPV read-back ambiguous fan=%s matches=%d: none taken", fan_id, len(hits))
    return hits[0] if len(hits) == 1 else {}
