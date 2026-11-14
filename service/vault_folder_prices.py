"""vault_folder_prices — an agency's price per vault folder (Full AI Chat sell).

One row per (account, folder ref): `vf:<vault_folders.id>` (internal folder) or `of:<OF list id>`
(the refs `automations/full_ai_sell.load_rows` gives each item). No row = no custom price. Our DB
only: setting a price never writes to OnlyFans. Read by the sell executor only (`full_ai_sell`).

Routes (owner scope, beside the folder routes): `vault_ai_api` GET / POST /admin/vault-ai/folder-prices.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from db.engine import get_session
from db.models import VaultFolderPrice

# Same bounds as `full_ai_sell.MIN_CENTS` / `MAX_CENTS` (a sale price inside [$10, $200]).
MIN_CENTS = 1000
MAX_CENTS = 20000
# `vf:` + an internal folder id; `of:` + an OF list id (stored as OF sent it: digits in practice).
_REF = re.compile(r"^(vf:\d{1,18}|of:[A-Za-z0-9_-]{1,40})$")


def parse_ref(raw: object) -> str | None:
    """`raw` as a folder ref, or None when it is not one."""
    ref = str(raw or "").strip()
    return ref if _REF.match(ref) else None


def parse_cents(raw: object) -> int | None:
    """`raw` as a price in whole cents inside [MIN_CENTS, MAX_CENTS], else None (bools refused)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw != int(raw):
        return None
    cents = int(raw)
    return cents if MIN_CENTS <= cents <= MAX_CENTS else None


def highest(refs: Iterable[str], prices: dict[str, int]) -> int | None:
    """The highest price among the folders `refs` names, None when none is priced."""
    got = [prices[r] for r in refs if r in prices]
    return max(got) if got else None


async def load(account_id: str) -> dict[str, int]:
    """Every priced folder of the account: {ref: cents}."""
    async with get_session() as s:
        rows = (await s.execute(select(VaultFolderPrice.folder_ref, VaultFolderPrice.price_cents)
                                .where(VaultFolderPrice.account_id == account_id))).all()
    return {ref: int(c) for ref, c in rows}


async def put(account_id: str, ref: str, cents: int | None) -> None:
    """Set the folder's price (upsert), or clear it with None."""
    async with get_session() as s:
        if cents is None:
            await s.execute(delete(VaultFolderPrice).where(
                VaultFolderPrice.account_id == account_id, VaultFolderPrice.folder_ref == ref))
        else:
            await s.execute(sqlite_insert(VaultFolderPrice)
                            .values(account_id=account_id, folder_ref=ref, price_cents=cents)
                            .on_conflict_do_update(index_elements=["account_id", "folder_ref"],
                                                   set_={"price_cents": cents, "updated_at": datetime.utcnow()}))
        await s.commit()
