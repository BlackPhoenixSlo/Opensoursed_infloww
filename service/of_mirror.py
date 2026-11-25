from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Iterable

from fastapi import HTTPException

import automation_executor as ax
from auth import assert_account_owned
from db.engine import get_session

log = logging.getLogger("of-relay.of_mirror")


def merge_mirrors(
    mirrors: Iterable[Any],
    live: list[dict] | None,
    *,
    of_id_attr: str,
    live_id_key: str,
    from_mirror: Callable[[Any, dict | None], dict],
    from_live: Callable[[dict], dict],
) -> list[dict]:
    by_id = {int(x[live_id_key]): x for x in (live or [])
             if x.get(live_id_key) is not None}
    out: list[dict] = []
    seen: set[int] = set()
    for m in mirrors:
        of_id = getattr(m, of_id_attr, None)
        hit = by_id.get(int(of_id)) if of_id is not None else None
        if hit is not None:
            seen.add(int(of_id))
        out.append(from_mirror(m, hit))
    for item in (live or []):
        oid = item.get(live_id_key)
        if oid is None or int(oid) in seen:
            continue
        out.append(from_live(item))
    return out


async def delete_mirrored(
    model,
    mirror_id: int,
    *,
    of_id_attr: str,
    of_delete: Callable[[Any, int], Any],
    not_found: str,
    label: str,
) -> dict[str, Any]:
    async with get_session() as s:
        row = await s.get(model, mirror_id)
        if row is None:
            raise HTTPException(404, not_found)
        assert_account_owned(row.account_id)
        account_id = row.account_id
        of_id = getattr(row, of_id_attr, None)

    # Session is closed before the OF call (a network round-trip that can hang; SQLite has one writer) and re-opened after.
    of_deleted = False
    if of_id is not None:
        try:
            client = await asyncio.to_thread(ax._make_client, account_id)
            await asyncio.to_thread(of_delete, client, int(of_id))
            of_deleted = True
        except Exception:
            log.warning("%s OF delete failed account=%s of_id=%s",
                        label, account_id, of_id, exc_info=True)

    async with get_session() as s:
        row = await s.get(model, mirror_id)
        if row is not None:
            await s.delete(row)
    log.info("%s_deleted id=%s of_deleted=%s", label, mirror_id, of_deleted)
    return {"deleted": mirror_id, "of_deleted": of_deleted}
