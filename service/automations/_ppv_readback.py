"""_ppv_readback — did OF take a priced DM whose send raised? One read of the
fan's chat: our newest line at that price after `since`, else {}. Shared by
every lane that sends PPVs (a timeout often still delivers)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import automation_executor as ax  # _parse_iso / _to_cents

log = logging.getLogger(__name__)


async def sent_ppv(client: Any, fan_id: int, since: datetime, price_cents: int) -> dict:
    """A priced send raised, but OF may have taken it: one read of his chat,
    and our newest message in it since `since` at the PPV's price (OF's row),
    else {} (the read failing too)."""
    try:
        data = await asyncio.to_thread(lambda: client.get_messages(fan_id, limit=10))
    except Exception:
        log.warning("could not read back a failed PPV fan=%s", fan_id,
                    exc_info=True)
        return {}
    items = data.get("list") if isinstance(data, dict) else data
    for m in items or []:
        if not isinstance(m, dict) or str((m.get("fromUser") or {}).get("id")) == str(fan_id):
            continue
        at = ax._parse_iso(m.get("createdAt"))
        if (m.get("id") and ax._to_cents(m.get("price")) == int(price_cents) and at is not None
                and at > since):
            return m
    return {}
