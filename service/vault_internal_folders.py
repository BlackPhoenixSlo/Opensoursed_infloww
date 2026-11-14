"""service/vault_internal_folders.py — the Inflowwww folders editor (Vault Pro › Extras).

Our own folders (`vault_folders` / `vault_folder_items`: the `AI-` script, lane and topic folders, the
`feet-*` pack rungs, tag folders, hand-made ones), listed and edited from Vault Pro. Our DB only: no
route here calls OnlyFans, whether or not the folder is mirrored to an OF list (`of_list_id`); pushing
one out stays the separate explicit `POST /admin/vault-ai/folders/{id}/publish`.

  GET    /admin/vault-ai/internal-folders                    list (also Full AI Chat's Content folders picker)
  POST   /admin/vault-ai/internal-folders                    create
  POST   /admin/vault-ai/internal-folders/{id}/rename
  POST   /admin/vault-ai/internal-folders/{id}/add           add media (copy), or move with `move_from`
  POST   /admin/vault-ai/internal-folders/{id}/remove
  POST   /admin/vault-ai/internal-folders/{id}/reorder       place media before another, renumber the folder
  DELETE /admin/vault-ai/internal-folders/{id}               soft (`deleted_at`)

Three rules:
  * An edit ADOPTS a generated folder. `vault_scripts.apply_ai_folders` rewrites / retires folders that
    are `created_by="vault_ai_script"` AND `AI-`-prefixed on every Build AI folders. The first rename,
    add, remove or reorder turns the folder into the operator's (`vault_pack_picker.CREATED_BY`, the
    reaper's existing shield), so a rebuild never touches it again; it builds a fresh generated copy
    beside it. `kind` in the list says which is which.
  * A pack rung (`feet-*`) is edited through `vault_pack_picker.triage`, never around it: photos only,
    the free rung only for a known-safe body, exclusive within the category. Rungs keep their name and
    cannot be deleted (the picker finds them by name); a rung's name is reserved for the picker.
  * Owner scope: a folder-limited chatter's list is empty and every write is 403.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import vault_folder_prices
import vault_pack_picker
import vault_scripts
from auth import assert_account_owned
from chatters import allowed_folder_ids_for_chatter
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem

log = logging.getLogger("of-relay.vault_ai_api")

router = APIRouter()

NAME_MAX = 120
# One request's media ids: a selection of the grid, never a whole vault.
MAX_IDS = 2000
_BASE = "/admin/vault-ai/internal-folders"


# ── Pure ─────────────────────────────────────────────────────────────

def folder_kind(name: str, created_by: str) -> str:
    """`pack` (a pack rung, edited through the picker's rules), `ai` (generated: the next Build AI
    folders rewrites or retires it) or `own` (the operator's: never touched by a rebuild)."""
    if vault_pack_picker.pack_rung_category(name) is not None:
        return "pack"
    if created_by == vault_scripts.AI_FOLDER_CREATOR and name.startswith(vault_scripts.AI_FOLDER_PREFIX):
        return "ai"
    return "own"


def reserved_name(name: str) -> bool:
    """A pack rung's name (any case): the picker finds its rungs by name, so no other folder may take one."""
    low = name.strip().lower()
    return any(low == n.lower() for c in vault_pack_picker.CATEGORIES.values() for n in c.folder_names)


def listing_sort_key(media_id: int, manual_order: int | None, created_at: datetime | None) -> tuple:
    """The folder listing's order (`vault_ai_api.local_items`): 0,1,2… first, then unordered newest
    first, then …-2,-1; ties by date then id, newest first."""
    bucket = 1 if manual_order is None else (0 if manual_order >= 0 else 2)
    age = -created_at.timestamp() if created_at is not None else float("inf")
    return (bucket, manual_order or 0, age, -media_id)


def place_before(order: list[int], moved: list[int], before: int | None) -> list[int]:
    """`order` with `moved` (members only, in the given order, once each) taken out and put back in
    front of `before` (None: at the end). ValueError when `before` is not a member or is being moved."""
    members = set(order)
    seen: set[int] = set()
    block = [m for m in moved if m in members and not (m in seen or seen.add(m))]
    if before is not None and (before not in members or before in seen):
        raise ValueError("bad_before")
    rest = [m for m in order if m not in seen]
    at = len(rest) if before is None else rest.index(before)
    return rest[:at] + block + rest[at:]


def _name(payload: dict) -> str:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail={"error": "name_required"})
    if len(name) > NAME_MAX:
        raise HTTPException(status_code=400, detail={"error": "name_too_long", "max": NAME_MAX})
    if reserved_name(name):
        raise HTTPException(status_code=400, detail={
            "error": "reserved_name",
            "message": f"{name} is a pack rung's name; the Feet pack owns it."})
    return name


def _media_ids(payload: dict, key: str = "media_ids") -> list[int]:
    """`payload[key]` as plain ints, once each, in order; anything else refuses the whole request."""
    raw = payload.get(key)
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail={"error": "media_ids_required"})
    bad = [m for m in raw if type(m) is not int]
    if bad:
        raise HTTPException(status_code=400, detail={"error": "invalid_media_ids", "media_ids": bad[:20]})
    if len(raw) > MAX_IDS:
        raise HTTPException(status_code=400, detail={"error": "too_many", "max": MAX_IDS})
    return list(dict.fromkeys(raw))


# ── Guards ───────────────────────────────────────────────────────────

async def _owner(payload_or_id: dict | str) -> str:
    """The request's account, owned and unrestricted (403 for a folder-limited chatter)."""
    account_id = payload_or_id if isinstance(payload_or_id, str) else str(payload_or_id.get("account_id") or "")
    if not account_id:
        raise HTTPException(status_code=400, detail={"error": "account_id_required"})
    assert_account_owned(account_id)
    if await allowed_folder_ids_for_chatter(account_id) is not None:
        raise HTTPException(status_code=403, detail={"error": "folder_not_allowed"})
    return account_id


async def _folder(s, account_id: str, folder_id: int) -> VaultFolder:
    folder = await s.get(VaultFolder, folder_id)
    if folder is None or folder.account_id != account_id or folder.deleted_at is not None:
        raise HTTPException(status_code=404, detail={"error": "folder_not_found"})
    return folder


def _rung_fixed(folder: VaultFolder) -> None:
    if vault_pack_picker.pack_rung_category(folder.name) is not None:
        raise HTTPException(status_code=400, detail={
            "error": "pack_rung_fixed",
            "message": f"{folder.name} is a Feet pack rung: it keeps its name and stays. Remove its items instead."})


async def _name_free(s, account_id: str, name: str, *, but: int | None = None) -> None:
    taken = (await s.execute(select(VaultFolder.id).where(
        VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None), VaultFolder.name == name,
        VaultFolder.id != (but if but is not None else -1)).limit(1))).first()
    if taken is not None:
        raise HTTPException(status_code=409, detail={
            "error": "name_taken", "message": f"A folder named {name} already exists."})


async def _in_mirror(s, account_id: str, media_ids: list[int]) -> None:
    """404 media that are not this account's live vault items (a stale tab on another model)."""
    known = set((await s.execute(select(VaultItem.media_id).where(
        VaultItem.account_id == account_id, VaultItem.media_id.in_(media_ids),
        VaultItem.removed_at.is_(None)))).scalars().all())
    foreign = [m for m in media_ids if m not in known]
    if foreign:
        raise HTTPException(status_code=404, detail={
            "error": "not_in_mirror", "media_ids": foreign[:20],
            "detail": "these media are not in this model's vault"})


def _adopt(folder: VaultFolder) -> bool:
    """The edit makes a generated folder the operator's (module docstring). True when it changed hands."""
    if folder.created_by != vault_scripts.AI_FOLDER_CREATOR:
        return False
    folder.created_by = vault_pack_picker.CREATED_BY
    return True


async def _members(s, account_id: str, folder_id: int, media_ids: list[int]) -> set[int]:
    return set((await s.execute(select(VaultFolderItem.media_id).where(
        VaultFolderItem.account_id == account_id, VaultFolderItem.folder_id == folder_id,
        VaultFolderItem.media_id.in_(media_ids)))).scalars().all())


async def _triage(account_id: str, cat: vault_pack_picker.Category, verdicts: dict[int, str | None]) -> None:
    """The pack picker's save, with its refusals as the picker's own 400s. Nothing written on a refusal."""
    try:
        await vault_pack_picker.triage(account_id, cat, verdicts)
    except vault_pack_picker.NotFreeSafe as e:
        raise HTTPException(status_code=400, detail={
            "error": "not_free_safe", "rung": cat.free_rung, "media_ids": e.media_ids,
            "message": f"{len(e.media_ids)} of these may not ride the free rung "
                       f"({cat.folder_name(cat.free_rung)}): Jev does not read the body as safe."}) from None
    except vault_pack_picker.PhotosOnly as e:
        raise HTTPException(status_code=400, detail={
            "error": f"{cat.name}_photos_only", "media_ids": e.media_ids,
            "message": f"A {cat.name} pack is photos only: {len(e.media_ids)} of these are not photos."}) from None


def _rung(cat: vault_pack_picker.Category, name: str) -> str:
    return next(r for r in cat.rungs if cat.folder_name(r) == name)


async def _take_out(account_id: str, folder_id: int, name: str, media_ids: list[int]) -> int:
    """Remove `media_ids` from the folder (a pack rung: through `triage`). Returns how many were in it."""
    async with get_session() as s:
        inside = sorted(await _members(s, account_id, folder_id, media_ids))
        cat = vault_pack_picker.pack_rung_category(name)
        if inside and cat is None:
            await s.execute(delete(VaultFolderItem).where(
                VaultFolderItem.account_id == account_id, VaultFolderItem.folder_id == folder_id,
                VaultFolderItem.media_id.in_(inside)))
            await s.commit()
    if inside and cat is not None:
        await _triage(account_id, cat, dict.fromkeys(inside))
    return len(inside)


async def _mark_edited(account_id: str, *folder_ids: int) -> list[int]:
    """Adopt the edited folders; the ids that changed hands."""
    out: list[int] = []
    async with get_session() as s:
        for fid in folder_ids:
            folder = await s.get(VaultFolder, fid)
            if folder is not None and folder.account_id == account_id and _adopt(folder):
                out.append(fid)
        await s.commit()
    return out


# ── Routes ───────────────────────────────────────────────────────────

@router.get(_BASE)
async def list_internal_folders(account_id: str = Query(...)) -> dict[str, Any]:
    """The live internal folders, name-sorted: `items` (unremoved members; Full AI Chat's Content folders
    picker, `vf:<id>`), of those `photos` / `videos`, `of_list_id` (set: mirrored to that OF list) and
    `kind` (`folder_kind`). A restricted chatter's allowed list names OF lists, so it sees none."""
    assert_account_owned(account_id)
    if await allowed_folder_ids_for_chatter(account_id) is not None:
        return {"list": []}
    kind_n = lambda k: func.coalesce(func.sum(case((VaultItem.kind == k, 1), else_=0)), 0)  # noqa: E731
    items = (select(VaultFolderItem.folder_id, func.count().label("n"),
                    kind_n("photo").label("photos"), kind_n("video").label("videos"))
             .join(VaultItem, (VaultItem.account_id == VaultFolderItem.account_id)
                   & (VaultItem.media_id == VaultFolderItem.media_id))
             .where(VaultFolderItem.account_id == account_id, VaultItem.removed_at.is_(None))
             .group_by(VaultFolderItem.folder_id).subquery())
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultFolder.id, VaultFolder.name, func.coalesce(items.c.n, 0),
                   func.coalesce(items.c.photos, 0), func.coalesce(items.c.videos, 0),
                   VaultFolder.of_list_id, VaultFolder.created_by)
            .outerjoin(items, items.c.folder_id == VaultFolder.id)
            .where(VaultFolder.account_id == account_id, VaultFolder.deleted_at.is_(None))
            .order_by(func.lower(VaultFolder.name), VaultFolder.id))).all()
    return {"list": [{"id": i, "name": n, "items": int(c), "photos": int(p), "videos": int(v),
                      "of_list_id": of, "kind": folder_kind(n, by)}
                     for i, n, c, p, v, of, by in rows]}


@router.post(_BASE)
async def create_internal_folder(payload: dict = Body(...)) -> dict[str, Any]:
    """A new empty folder of the operator's (`created_by="operator"`). 400 name_required / name_too_long /
    reserved_name, 409 name_taken."""
    account_id = await _owner(payload)
    name = _name(payload)
    async with get_session() as s:
        await _name_free(s, account_id, name)
        folder = VaultFolder(account_id=account_id, name=name, created_by=vault_pack_picker.CREATED_BY)
        s.add(folder)
        await s.commit()
        folder_id = folder.id
    log.info("internal folder created account=%s folder=%s", account_id, folder_id)
    return {"account_id": account_id, "folder_id": folder_id, "name": name}


@router.post(_BASE + "/{folder_id}/rename")
async def rename_internal_folder(folder_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Rename; a generated folder becomes the operator's. A pack rung keeps its name (400 pack_rung_fixed)."""
    account_id = await _owner(payload)
    name = _name(payload)
    async with get_session() as s:
        folder = await _folder(s, account_id, folder_id)
        _rung_fixed(folder)
        await _name_free(s, account_id, name, but=folder_id)
        folder.name = name
        adopted = _adopt(folder)
        await s.commit()
    return {"account_id": account_id, "folder_id": folder_id, "name": name,
            "adopted": [folder_id] if adopted else []}


@router.delete(_BASE + "/{folder_id}")
async def delete_internal_folder(folder_id: int, account_id: str = Query(...)) -> dict[str, Any]:
    """Soft-delete (`deleted_at`): the folder and its price leave, the media stay in the vault. An OF list
    it was mirrored to is left as it is (`of_list_id` in the answer). A pack rung stays (400 pack_rung_fixed)."""
    account_id = await _owner(account_id)
    async with get_session() as s:
        folder = await _folder(s, account_id, folder_id)
        _rung_fixed(folder)
        folder.deleted_at = datetime.utcnow()
        of_list_id = folder.of_list_id
        await s.commit()
    await vault_folder_prices.put(account_id, f"vf:{folder_id}", None)
    log.info("internal folder deleted account=%s folder=%s", account_id, folder_id)
    return {"account_id": account_id, "folder_id": folder_id, "deleted": True, "of_list_id": of_list_id}


@router.post(_BASE + "/{folder_id}/add")
async def add_to_internal_folder(folder_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Add `media_ids` (this account's live vault items, else 404 not_in_mirror) to the folder, after its
    ordered items. `move_from` (another live folder's id): also take them out of that one — a move.

    Into a pack rung the add IS the picker's verdict (`vault_pack_picker.triage`): 400
    `<category>_photos_only` / `not_free_safe` with the refused ids and nothing written; filing on one
    rung takes the item off the category's other rungs. Out of a rung likewise goes through the picker.
    The edited folders (target, and the source of a move) become the operator's (`adopted`)."""
    account_id = await _owner(payload)
    media_ids = _media_ids(payload)
    source_id = payload.get("move_from")
    if source_id is not None and (type(source_id) is not int or source_id == folder_id):
        raise HTTPException(status_code=400, detail={"error": "bad_move_from"})
    async with get_session() as s:
        target = await _folder(s, account_id, folder_id)
        source = await _folder(s, account_id, source_id) if source_id is not None else None
        await _in_mirror(s, account_id, media_ids)
        already = await _members(s, account_id, folder_id, media_ids)
        in_source = len(await _members(s, account_id, source_id, media_ids)) if source is not None else 0
        target_name, source_name = target.name, source.name if source else None
        cat = vault_pack_picker.pack_rung_category(target_name)
        if cat is None:
            for m in media_ids:
                await s.execute(sqlite_insert(VaultFolderItem)
                                .values(account_id=account_id, folder_id=folder_id, media_id=m)
                                .on_conflict_do_nothing(index_elements=["account_id", "folder_id", "media_id"]))
            await s.commit()
    if cat is not None:
        # Only the new ones: the picker re-files what it is handed, which would drop a member's place in the rung.
        fresh = [m for m in media_ids if m not in already]
        if fresh:
            await _triage(account_id, cat, dict.fromkeys(fresh, _rung(cat, target_name)))
    # A move between two rungs of one category is already done: filing is exclusive there.
    if source_name is not None and not (cat is not None and vault_pack_picker.pack_rung_category(source_name) is cat):
        await _take_out(account_id, source_id, source_name, media_ids)
    added = len(media_ids) - len(already)
    adopted = await _mark_edited(account_id, *([folder_id] if added else []), *([source_id] if in_source else []))
    return {"account_id": account_id, "folder_id": folder_id, "added": added,
            "already": len(already), "moved": in_source, "adopted": adopted}


@router.post(_BASE + "/{folder_id}/remove")
async def remove_from_internal_folder(folder_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Take `media_ids` out of the folder (the media stay in the vault). A pack rung: the picker's reject."""
    account_id = await _owner(payload)
    media_ids = _media_ids(payload)
    async with get_session() as s:
        name = (await _folder(s, account_id, folder_id)).name
    removed = await _take_out(account_id, folder_id, name, media_ids)
    adopted = await _mark_edited(account_id, folder_id) if removed else []
    return {"account_id": account_id, "folder_id": folder_id, "removed": removed, "adopted": adopted}


@router.post(_BASE + "/{folder_id}/reorder")
async def reorder_internal_folder(folder_id: int, payload: dict = Body(...)) -> dict[str, Any]:
    """Put `media_ids` (in that order) in front of member `before` (null: at the end) and renumber the
    whole folder's `manual_order` 0..n-1 in the order the listing shows it. 400 bad_before."""
    account_id = await _owner(payload)
    media_ids = _media_ids(payload)
    before = payload.get("before")
    if before is not None and type(before) is not int:
        raise HTTPException(status_code=400, detail={"error": "bad_before"})
    async with get_session() as s:
        folder = await _folder(s, account_id, folder_id)
        rows = (await s.execute(
            select(VaultFolderItem.media_id, VaultFolderItem.manual_order, VaultItem.created_at)
            .outerjoin(VaultItem, (VaultItem.account_id == VaultFolderItem.account_id)
                       & (VaultItem.media_id == VaultFolderItem.media_id))
            .where(VaultFolderItem.account_id == account_id, VaultFolderItem.folder_id == folder_id))).all()
        current = {int(m): mo for m, mo, _ in rows}
        order = [int(m) for m, _, _ in sorted(rows, key=lambda r: listing_sort_key(int(r[0]), r[1], r[2]))]
        try:
            placed = place_before(order, media_ids, before)
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": "bad_before"}) from None
        changed = [(i, m) for i, m in enumerate(placed) if current[m] != i]
        for i, m in changed:
            await s.execute(update(VaultFolderItem).where(
                VaultFolderItem.account_id == account_id, VaultFolderItem.folder_id == folder_id,
                VaultFolderItem.media_id == m).values(manual_order=i))
        # Adopt only when the order the operator sees moved; renumbering alone (a no-op drop) is no edit.
        adopted = placed != order and _adopt(folder)
        await s.commit()
    return {"account_id": account_id, "folder_id": folder_id, "items": len(placed),
            "adopted": [folder_id] if adopted else []}
