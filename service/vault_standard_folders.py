"""Idempotent standard-folder placement using saved analysis, scoped per account.

Only memberships owned by this mapper are reconciled. Stable folder IDs keep
prices and ordering intact; custom folders and the original AI data are untouched.

Per-Creator switch `vault_settings.standard_folders`, off by default: off, `sync` creates and
places nothing and `listing` is empty.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import delete, func, select

import vault_settings
from db.engine import get_session
from db.of_writer import immediate_session
from db.models import Account, VaultFolder, VaultFolderItem, VaultItem
from vault_ai_effective import overrides
from vault_standard_rules import PREFIX, REVIEW, categories, classify, key, parse_key

log = logging.getLogger(__name__)
BATCH = 250


class CategoryMediaType(ValueError):
    """Filing media of the other kind into a standard category (a photo into Videos / …)."""

    def __init__(self, kind: str) -> None:
        super().__init__("category_media_type")
        self.kind = kind


async def _ensure(s, account_id: str) -> dict[str, VaultFolder]:
    rows = (await s.scalars(select(VaultFolder).where(
        VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None),
        VaultFolder.created_by.startswith(PREFIX)))).all()
    by_key = {r.created_by: r for r in rows}
    for kind, group in (("photo", "Photos"), ("video", "Videos")):
        for slug, label in categories(kind):
            marker = key(kind, slug)
            if marker not in by_key:
                folder = VaultFolder(account_id=account_id, name=f"{group} / {label}", created_by=marker)
                s.add(folder)
                by_key[marker] = folder
    await s.flush()
    return by_key


async def _place(s, account_id: str, folders: dict, items: list) -> None:
    if not items:
        return
    ids = [i.media_id for i in items]
    folder_ids = [f.id for f in folders.values()]
    rows = (await s.execute(select(VaultFolderItem.media_id, VaultFolderItem.folder_id).where(
        VaultFolderItem.account_id == account_id, VaultFolderItem.media_id.in_(ids),
        VaultFolderItem.folder_id.in_(folder_ids)))).all()
    existing: dict[int, set[int]] = {}
    for mid, fid in rows:
        existing.setdefault(mid, set()).add(fid)
    for item in items:
        wanted = {folders[key(item.kind, slug)].id for slug in classify(item)}
        current = existing.get(item.media_id, set())
        if current - wanted:
            await s.execute(delete(VaultFolderItem).where(
                VaultFolderItem.account_id == account_id, VaultFolderItem.media_id == item.media_id,
                VaultFolderItem.folder_id.in_(current - wanted)))
        for fid in wanted - current:
            s.add(VaultFolderItem(account_id=account_id, media_id=item.media_id, folder_id=fid))


async def sync(account_id: str, media_ids: list[int] | None = None) -> int:
    """Create empty defaults even before describing. Backfill in bounded commits.

Re-read items under the write lock so an older sweep cannot overwrite a newer
manual correction. Refreshes never call vision, OF, or any selling endpoint.
"""
    if not await vault_settings.on(account_id, "standard_folders"):
        return 0
    after, count = -1, 0
    while True:
        # No unique name constraint exists on legacy folders: BEGIN IMMEDIATE before the first read serializes
        # creation across workers, not just within one process.
        async with immediate_session() as s:
            if await s.scalar(select(Account.id).where(Account.id == account_id)) is None:
                raise ValueError("account_not_found")
            folders = await _ensure(s, account_id)
            q = select(VaultItem).where(VaultItem.account_id == account_id, VaultItem.media_id > after)
            if media_ids is not None:
                q = q.where(VaultItem.media_id.in_(media_ids))
            items = list((await s.scalars(q.order_by(VaultItem.media_id).limit(BATCH))).all())
            await _place(s, account_id, folders, items)
        count += len(items)
        if len(items) < BATCH:
            return count
        after = items[-1].media_id


async def after_analysis(account_id: str, media_id: int) -> None:
    # A placement failure must not turn a successful paid description into a
    # failure that invites paying for it twice. Refresh safely retries placement.
    try:
        await sync(account_id, [media_id])
    except Exception:
        log.exception("Standard folder placement failed account=%s media=%s; refresh retries", account_id, media_id)


async def listing(account_id: str) -> dict:
    if not await vault_settings.on(account_id, "standard_folders"):
        return {"list": [], "pending": 0}
    async with get_session() as s:
        rows = (await s.execute(select(VaultFolder.id, VaultFolder.created_by, func.count(VaultItem.media_id))
            .outerjoin(VaultFolderItem, (VaultFolderItem.folder_id == VaultFolder.id)
                       & (VaultFolderItem.account_id == account_id))
            .outerjoin(VaultItem, (VaultItem.media_id == VaultFolderItem.media_id)
                       & (VaultItem.account_id == account_id) & VaultItem.removed_at.is_(None))
            .where(VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None),
                   VaultFolder.created_by.startswith(PREFIX))
            .group_by(VaultFolder.id, VaultFolder.created_by))).all()
        pending = await s.scalar(select(func.count()).select_from(VaultItem).where(
            VaultItem.account_id == account_id, VaultItem.removed_at.is_(None),
            VaultItem.kind.in_(("photo", "video")),
            (VaultItem.describe_status.is_(None) | (VaultItem.describe_status != "described"))))
    by_key = {marker: (fid, n) for fid, marker, n in rows}
    result = []
    for kind in ("photo", "video"):
        for slug, label in categories(kind):
            found = by_key.get(key(kind, slug))
            if found:
                result.append({"id": found[0], "kind": kind, "slug": slug, "name": label,
                               "items": found[1], "priceable": slug != REVIEW})
    return {"list": result, "pending": pending or 0}


async def remember(s, account_id: str, folder: VaultFolder, ids: list[int], included: bool) -> None:
    """Persist explicit operator filing decisions through later descriptions. Raises `CategoryMediaType` (nothing
    written) when an included item is not of the category's kind."""
    parsed = parse_key(folder.created_by)
    if parsed is None:
        return
    items = list((await s.scalars(select(VaultItem).where(
        VaultItem.account_id == account_id, VaultItem.media_id.in_(ids)).with_for_update())).all())
    if included and any(item.kind != parsed[0] for item in items):
        raise CategoryMediaType(parsed[0])
    for item in items:
        ov = dict(overrides(item))
        choices = dict(ov.get("_standard_folders") or {})
        choices[folder.created_by] = included
        if included and parsed[1] != REVIEW:
            choices[key(parsed[0], REVIEW)] = False
        ov["_standard_folders"] = choices
        item.operator_overrides_json = json.dumps(ov)
