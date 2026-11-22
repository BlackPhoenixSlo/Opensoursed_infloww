"""vault_settings — three per-Creator vault switches: two OFF, one ON, until an owner flips them.

`folder_price_final`: a saved folder price is the final price of a paid Full AI offer (no price
Jev, no tease price, no haggle on folder-priced media). Off: Jev decides the price and the folder
price is only its input (owner 2026-11-15).
`standard_folders`: the fixed category list (`vault_standard_rules`) is created, filled from saved
analysis and shown in the vault; media in its Needs Review folder is not for sale. Off: no standard
folder is created or placed, none is listed (vault, Full AI Content folders picker) or editable
(`vault_internal_folders` 404s it), and Needs Review keeps nothing from sale. Folders and memberships
made while on are kept for the next turn-on.
`solo_sequences` (ON by default, client rule): Script Fill puts only solo media into Sequences; partner
(BG/GG) media is `not_solo` (`script_fill_decide._gate`). Off: partner media may be Filled, the other
gates still apply.

No row = the first two off, `solo_sequences` on; a NULL column reads as its default (`DEFAULTS`).
Routes: `vault_ai_api` GET / PUT /admin/vault-ai/settings (owner scope).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import VaultAccountSetting

KEYS = ("folder_price_final", "standard_folders", "solo_sequences")
DEFAULTS = {"folder_price_final": False, "standard_folders": False, "solo_sequences": True}


async def load(account_id: str) -> dict[str, bool]:
    async with get_session() as s:
        row = (await s.execute(
            select(*(getattr(VaultAccountSetting, k) for k in KEYS))
            .where(VaultAccountSetting.account_id == account_id))).first()
    if row is None:
        return dict(DEFAULTS)
    return {k: DEFAULTS[k] if v is None else bool(v) for k, v in zip(KEYS, row)}


async def on(account_id: str, key: str) -> bool:
    return (await load(account_id))[key]


async def put(account_id: str, **changes: bool) -> dict[str, bool]:
    """Set the named switches, keep the others; returns every stored switch."""
    vals = {**await load(account_id), **{k: bool(v) for k, v in changes.items() if k in KEYS}}
    async with get_session() as s:
        await s.execute(sqlite_insert(VaultAccountSetting)
                        .values(account_id=account_id, **vals)
                        .on_conflict_do_update(index_elements=["account_id"],
                                               set_={**vals, "updated_at": datetime.utcnow()}))
        await s.commit()
    return vals
