"""vault_settings — two per-Creator vault switches, both OFF until an owner turns them on.

`folder_price_final`: a saved folder price is the final price of a paid Full AI offer (no price
Jev, no tease price, no haggle on folder-priced media). Off: Jev decides the price and the folder
price is only its input (owner 2026-11-15).
`standard_folders`: the fixed category list (`vault_standard_rules`) is created, filled from saved
analysis and shown in the vault; media in its Needs Review folder is not for sale. Off: no standard
folder is created, placed or read.

No row = both off. Routes: `vault_ai_api` GET / PUT /admin/vault-ai/settings (owner scope).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import VaultAccountSetting

KEYS = ("folder_price_final", "standard_folders")
OFF = {k: False for k in KEYS}


async def load(account_id: str) -> dict[str, bool]:
    async with get_session() as s:
        row = (await s.execute(
            select(VaultAccountSetting.folder_price_final, VaultAccountSetting.standard_folders)
            .where(VaultAccountSetting.account_id == account_id))).first()
    return dict(OFF) if row is None else {k: bool(v) for k, v in zip(KEYS, row)}


async def on(account_id: str, key: str) -> bool:
    return (await load(account_id))[key]


async def put(account_id: str, **changes: bool) -> dict[str, bool]:
    """Set the named switches, keep the others; returns the stored pair."""
    vals = {**await load(account_id), **{k: bool(v) for k, v in changes.items() if k in KEYS}}
    async with get_session() as s:
        await s.execute(sqlite_insert(VaultAccountSetting)
                        .values(account_id=account_id, **vals)
                        .on_conflict_do_update(index_elements=["account_id"],
                                               set_={**vals, "updated_at": datetime.utcnow()}))
        await s.commit()
    return vals
