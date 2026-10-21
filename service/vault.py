"""
vault.py — DB-backed read endpoints for vault items, presets, and saved
replies. Per T-B5 these are cache-first: vault content changes rarely
enough that serving from SQLite (mirrored by the WS transcoder + the OF
import paths) gives the UI a fast, paginated read without burning OF
rate-limit budget.

The OF-passthrough path at /api/of/v2/vault/* stays intact — switching it
to DB-first is a separate decision pending SSE reliability measurement
(plan 07 §2). These admin routes are additive.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from db.engine import get_session
from db.models import Message, VaultSend
from auth import assert_account_owned

log = logging.getLogger("of-relay.vault")
router = APIRouter()


def _safe_load_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


@router.get("/admin/vault/media-stats")
async def vault_media_stats(account_id: str = Query(...)) -> dict[str, Any]:
    """Per-media sales stats for the vault picker, account-wide (Infloww's
    Sent count / Unlock count / Unlock rate, plus "Recently used"), over 1:1
    chat sends only. One GROUP BY over `vault_sends` on `ix_vault_sends_media`.

    by_media: { "<media_id>": { sent, priced, unlocks, unlock_rate, last_sent_at } }
      sent    — distinct fans a 1:1 send reached,
      priced  — of those, fans it reached with a price,
      unlocks — fans who bought it (`was_purchased`),
      unlock_rate — unlocks / priced, None with no priced send.

    Left out, because they are not 1:1 sends and would read as ~100% unlocks:
    rows on a mass message (`messages.mass_run_id`: the ownership stamp after
    a mass PPV was bought, or a history backfill of one) and purchase stamps
    with no message (a wall-post purchase). The mass check is a PK lookup per
    row. A 1:1 row recorded without its message id that a purchase later
    flipped drops out too: an undercount, never an inflation."""
    assert_account_owned(account_id)
    fan = VaultSend.fan_id
    on_mass = (select(Message.message_id)
               .where(Message.account_id == VaultSend.account_id,
                      Message.fan_id == VaultSend.fan_id,
                      Message.message_id == VaultSend.message_id,
                      Message.mass_run_id.is_not(None))
               .exists())
    async with get_session() as s:
        rows = (await s.execute(
            select(
                VaultSend.media_id,
                func.count(func.distinct(fan)),
                func.count(func.distinct(case((VaultSend.price_cents > 0, fan)))),
                func.count(func.distinct(case((VaultSend.was_purchased.is_(True), fan)))),
                func.max(VaultSend.sent_at),
            )
            .where(VaultSend.account_id == account_id, ~on_mass,
                   or_(VaultSend.message_id.is_not(None), VaultSend.was_purchased.is_not(True)))
            .group_by(VaultSend.media_id)
        )).all()
    return {"by_media": {
        str(mid): {
            "sent": int(sent),
            "priced": int(priced),
            "unlocks": int(unlocks),
            "unlock_rate": round(unlocks / priced, 4) if priced else None,
            "last_sent_at": last.isoformat() if last else None,
        }
        for mid, sent, priced, unlocks, last in rows
    }}


