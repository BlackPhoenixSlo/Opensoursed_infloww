from __future__ import annotations

import logging
from typing import Any, Iterable

from sqlalchemy import func, select

import vault_mirror
import vault_stills
from db.engine import get_session
from db.models import VaultItem

log = logging.getLogger("of-relay.vault_ingest")


async def has_live_mirror(account_id: str) -> bool:
    async with get_session() as s:
        return bool(await s.scalar(
            select(func.count()).select_from(VaultItem)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None))
        ))


async def ingest_ids(account_id: str, media_ids: Iterable[Any], client: Any) -> int:
    # A failure here is never the run's failure: the import already succeeded on OF and a re-collect recovers the mirror row.
    # Only seed a mirror the grid reads (live rows, removed_at IS NULL): seeding a buried one flips the grid onto a few tiles.
    if not await has_live_mirror(account_id):
        log.info("mirror ingest: account=%s has no LIVE mirror row (never "
                 "collected, or every row soft-deleted) — the grid is reading OF "
                 "directly and already shows the import; skipping", account_id)
        return 0

    rows: list[dict[str, Any]] = []
    for mid in dict.fromkeys(int(m) for m in media_ids if m is not None):
        try:
            # mark_gone=False: an id just uploaded is no evidence of deletion; a 404 blip must not bury media the operator can see.
            fresh = await vault_stills.resolve_fresh(account_id, mid, client,
                                                     mark_gone=False)
        except Exception as e:  # noqa: BLE001 — one bad id is not the batch
            log.warning("mirror ingest: OF read raised for media=%s: %s", mid, e)
            continue
        if fresh.media is None:
            log.warning("mirror ingest: no payload for media=%s (%s)",
                        mid, fresh.reason)
            continue
        vals = vault_mirror.row_values(account_id, fresh.media)
        if vals is not None:
            rows.append(vals)

    if not rows:
        return 0
    try:
        async with get_session() as s:
            for vals in rows:
                await s.execute(vault_mirror.upsert_stmt(vals))
            await s.commit()
    except Exception as e:  # noqa: BLE001 — the media IS in her vault either way
        log.warning("mirror ingest: write failed for account=%s (%d rows): %s",
                    account_id, len(rows), e)
        return 0
    log.info("mirror ingest: account=%s landed=%d", account_id, len(rows))
    return len(rows)
