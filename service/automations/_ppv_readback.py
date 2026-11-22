"""_ppv_readback — did OF take a priced DM whose send raised? One read of the
fan's chat: our newest line at that price after `since`, else {}. Shared by
every lane that sends PPVs (a timeout often still delivers). `media` given (Full
AI): only OF's one item carrying exactly those media, never a mass copy, created
in `since`'s whole second or later (OF stamps whole seconds; the same floor as
`full_ai_settle.link_window`)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import automation_executor as ax  # _parse_iso / _to_cents
from of_shapes import queue_id   # pure: OF's mass-copy marker on a chat item

log = logging.getLogger(__name__)


def _media_of(m: dict) -> set[int]:
    return {int(x["id"]) for x in m.get("media") or []
            if isinstance(x, dict) and str(x.get("id", "")).isdigit()}


async def sent_ppv(client: Any, fan_id: int, since: datetime, price_cents: int, *,
                   media=None) -> dict:
    """A priced send raised, but OF may have taken it: one read of his chat,
    and our newest message in it since `since` at the PPV's price (OF's row),
    else {} (the read failing too). `media` (every id the POST carried): the one
    such message with exactly those media ids and no `queueId` (a mass copy);
    none or several = {}."""
    try:
        data = await asyncio.to_thread(lambda: client.get_messages(fan_id, limit=10))
    except Exception:
        log.warning("could not read back a failed PPV fan=%s", fan_id,
                    exc_info=True)
        return {}
    items = data.get("list") if isinstance(data, dict) else data
    want = None if media is None else {int(x) for x in media}
    # The floor: main's `at > since`; Full AI's (`media`) the attempt's whole second on, as `link_window`.
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
