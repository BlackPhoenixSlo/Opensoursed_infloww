"""The pack picker — triage a category's vault candidates into rungs.

One button, one modal, one save. The operator sees every item in the vault that
might belong to a category, files each on a rung (or rejects it), and saves. The
rungs become internal `VaultFolder`s; publishing them to her real OnlyFans vault
is a separate, explicit step (`vault_ai_api._push_folder_to_of`).

WHY A HUMAN IS IN THIS LOOP. The vault's own taxonomy cannot find this content.
Measured on prod 2026-08-10: `primary_folder='feet'` is set on 265 items
roster-wide but on ZERO items of either pilot account, and on ZERO of the 68
items the operator hand-picked on 08-01. `body_focus` DOES list "feet" — on 278
items on 8000149 — but it lists feet whenever they are merely VISIBLE, not when
they are the subject, so a lingerie pose with her feet in frame matches. Hence a
4.5x over-inclusive generator (307 candidates -> 68 keepers, 22%), and hence this
module: selling straight off the tag would charge a fan for three photos he did
not ask for out of every four.

PRECISION ONLY (owner, 2026-11-12: "better a small set of good photos than a
lot of half-assed ones", "drop videos from feet"). A candidate is a PHOTO the
Jev v8 pass answered (`_jev.status == "ok"`, `jev_ok`) that sees the part
(`jev_seen`) at a score (`jev_likelihood`) >= `FEET_PRESELECT_SCORE` (.6:
precision 1.0 on the owner's hand-picked set, anything lower .33-.87;
.scratch/jev-vault-bench/feet-eval). Each arrives PRESELECTED on the rung its
Jev tier + covering answer pick (`jev_pick`) when that rung is known and safe,
so the operator unticks what is wrong and files the rest in one click. After
them come the POSSIBLE ones (owner 2026-11-13): Jev photos that see the part at
`FEET_POSSIBLE_MIN` (.3) <= score < the gate (`possible`), unticked, `suggested`
from the same tier + covering rule without the gate (`jev_rung`), for the
operator to check; never preselected. With no confident photo left the queue is
only these. Feet live here only: Build AI folders has no feet topic (owner
2026-11-13, `vault_topic_folders`). Nothing else: no describe-word
(qwen / LIKE) candidates (a photo Jev has not classified yet waits for it), no
videos (`triage` refuses one on any rung: `PhotosOnly`). Items already filed
always come back, whatever they are, so a rung view can still unfile them. The
pack reads the vault itself, never the AI- folders (it works before they are
built). Nothing here talks to OnlyFans.

Prepare content (`full_ai_prepare._feet`, owner 2026-11-14: the default ticks were right) presses "File N
preselected" itself, once, while the account has no feet-* folder: the preselected photos only, each on its
preselected rung. The possible ones still wait for the operator here.

THE FREE RUNG is guarded hard: `jev_tier` is 0 only for lane5 "free" with
breasts / crotch / penetration all "n"; `triage` refuses (`NotFreeSafe`) a
Jev-priced row (`jev_priced`: a video's max frame too) on the free rung
otherwise, and publishing the free rung skips one already filed there
(`unsafe_on_free`: rows filed before this guard existed).

Routes live in `vault_ai_api` (house convention — that module owns every
`/admin/vault-ai/*` route and the `vault_*` siblings own the logic).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, delete, func, literal, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import vault_ai_brief
import vault_jev_rules
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem
from vault_mirror import visible_to

# Folders here are the operator's: this string keeps vault_scripts' reaper (created_by="vault_ai_script" AND AI- prefix) off them. Never backfill.
CREATED_BY = "operator"

# A rung of one of these clears the item from every rung; no reject list is stored.
REJECT_VALUES = frozenset({"", "reject", "none"})


@dataclass(frozen=True)
class Category:
    name: str
    rungs: tuple[str, ...]
    jev_seen: tuple[str, ...] = ()
    jev_boosts: tuple[str, ...] = ()
    jev_detail: str | None = None

    @property
    def free_rung(self) -> str:
        return self.rungs[0]

    def folder_name(self, rung: str) -> str:
        return f"{self.name}-{rung}"

    @property
    def folder_names(self) -> list[str]:
        return [self.folder_name(r) for r in self.rungs]


CATEGORIES: dict[str, Category] = {
    c.name: c for c in (
        Category(name="feet", rungs=("tease", "nude", "nude-body"),
                 jev_seen=("feet_any", "feet_focus"),
                 jev_boosts=("soles_visible", "bare_toes_visible"),
                 jev_detail="feet_detail"),
    )
}


class UnknownCategory(KeyError):
    pass


class UnknownRung(ValueError):
    pass


class InvalidMediaIds(ValueError):

    def __init__(self, media_ids: list[Any]):
        super().__init__(f"invalid media ids: {media_ids!r}")
        self.media_ids = media_ids


class NotFreeSafe(ValueError):

    def __init__(self, media_ids: list[int]):
        super().__init__(f"not free-safe: {media_ids}")
        self.media_ids = media_ids


class PhotosOnly(ValueError):

    def __init__(self, media_ids: list[int]):
        super().__init__(f"photos only: {media_ids}")
        self.media_ids = media_ids


class NotInMirror(ValueError):

    def __init__(self, media_ids: list[int]):
        super().__init__(f"not in mirror: {media_ids}")
        self.media_ids = media_ids


def free_rung_category(folder_name: str | None) -> Category | None:
    return next((c for c in CATEGORIES.values() if c.folder_name(c.free_rung) == folder_name), None)


def pack_rung_category(folder_name: str | None) -> Category | None:
    return next((c for c in CATEGORIES.values() if folder_name in c.folder_names), None)


def category(name: str | None) -> Category:
    try:
        return CATEGORIES[(name or "").strip().lower()]
    except KeyError:
        raise UnknownCategory(name) from None


def normalise_verdicts(cat: Category, rows: list[dict[str, Any]]) -> dict[int, str | None]:
    rows = list(rows or [])
    bad = [row.get("media_id") if isinstance(row, dict) else row for row in rows
           if not (isinstance(row, dict) and type(row.get("media_id")) is int)]
    if bad:
        raise InvalidMediaIds(bad)
    out: dict[int, str | None] = {}
    for row in rows:
        media_id = row["media_id"]
        rung = str(row.get("rung") or "").strip().lower()
        if rung in REJECT_VALUES:
            out[media_id] = None
        elif rung in cat.rungs:
            out[media_id] = rung
        else:
            raise UnknownRung(rung)
    return out


JEV_KEY = "_jev"
JEV_LANE_TIERS = {"$100": 100, "$50": 50, "$10": 10, "free": 0}
# Jev scoring priors (rough, not a fit).
_EV_JEV_BOOST = 0.3
_DAMP_JEV_ABSENT = 0.25


def _jev(fields: dict[str, Any]) -> dict[str, Any]:
    j = fields.get(JEV_KEY)
    return j if isinstance(j, dict) else {}


def jev_priced(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    j = _jev(fields) if isinstance(fields, dict) else {}
    return j if j.get("status") == "ok" and j.get("lane5") else None


def jev_ok(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    j = jev_priced(fields)
    return j if j is not None and j.get("kind") != "video" else None


def probability_key(cat: Category) -> str:
    return f"{cat.name}_subject"


def _unit(p: Any) -> float | None:
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p):
        return None
    return min(1.0, max(0.0, float(p)))


def _jev_tags(j: dict[str, Any]) -> dict[str, Any]:
    t = j.get("tags")
    return t if isinstance(t, dict) else {}


def jev_seen(cat: Category, j: dict[str, Any]) -> bool:
    tags = _jev_tags(j)
    return any(tags.get(k) == "y" for k in cat.jev_seen)


def jev_likelihood(cat: Category, j: dict[str, Any]) -> float:
    p = _unit(j.get(probability_key(cat))) or 0.0
    probs = j.get("P") if isinstance(j.get("P"), dict) else {}
    boost = max([_unit(probs.get(k)) or 0.0 for k in cat.jev_boosts] or [0.0])
    p += (1.0 - p) * _EV_JEV_BOOST * boost
    if cat.jev_detail and _jev_tags(j).get(cat.jev_detail) == "not_in_picture":
        p *= _DAMP_JEV_ABSENT
    return p


def jev_tier(j: dict[str, Any]) -> int | None:
    lane5 = str(j.get("lane5") or "")
    # Tier 0 only when every body answer is n; review/unsure/missing is unknown, never free.
    if lane5 == "free":
        return 0 if vault_jev_rules.body_free(j) else None
    tier = JEV_LANE_TIERS.get(lane5)
    return tier if tier else None


def free_ok(fields: dict[str, Any] | None) -> bool | None:
    if vault_ai_brief.free_vetoed(fields):
        return False
    j = jev_priced(fields)
    return None if j is None else jev_tier(j) == 0


async def non_photos(s, account_id: str, media_ids: list[int]) -> list[int]:
    if not media_ids:
        return []
    return sorted(int(m) for (m,) in (await s.execute(
        select(VaultItem.media_id).where(
            VaultItem.account_id == account_id, VaultItem.media_id.in_(media_ids),
            VaultItem.kind != "photo")
    )).all())


async def not_in_mirror(s, account_id: str, media_ids: list[int]) -> list[int]:
    if not media_ids:
        return []
    live = set((await s.execute(select(VaultItem.media_id).where(
        VaultItem.account_id == account_id, VaultItem.media_id.in_(media_ids),
        VaultItem.removed_at.is_(None)))).scalars().all())
    return sorted(int(m) for m in set(media_ids) - live)


async def unsafe_on_free(s, account_id: str, media_ids: list[int]) -> list[int]:
    if not media_ids:
        return []
    return sorted(
        int(m) for m, raw in (await s.execute(
            select(VaultItem.media_id, VaultItem.ai_fields_json).where(
                VaultItem.account_id == account_id, VaultItem.media_id.in_(media_ids))
        )).all()
        if free_ok(vault_ai_brief.load_fields(raw)) is False
    )


def price_tier(fields: dict[str, Any] | None) -> int | None:
    j = jev_priced(fields)
    return None if j is None else jev_tier(j)


# One Collect sweep mirrors up to a 20k vault; bounds a pathological one.
_SCAN_CAP = 20_000

# Measured on the owner's hand-picked feet set: >=.6 gives precision 1.0, recall .29; owner wants few good photos, not many half-good.
FEET_PRESELECT_SCORE = 0.6

# Below this a photo is no candidate. Measured on an AE account: the top 10 (.31-.50) held 7 real feet, 1 clear false positive.
FEET_POSSIBLE_MIN = 0.3


def confident(cat: Category, fields: dict[str, Any] | None) -> dict[str, Any] | None:
    j = jev_ok(fields)
    if j is None or not jev_seen(cat, j) or jev_likelihood(cat, j) < FEET_PRESELECT_SCORE:
        return None
    return j


def jev_rung(cat: Category, j: dict[str, Any]) -> str | None:
    tier = jev_tier(j)
    # An unknown tier is never picked: a body Jev half-saw would ride the free preview.
    if tier is None:
        return None
    if tier > 0:
        return cat.rungs[2]
    detail = _jev_tags(j).get(cat.jev_detail) if cat.jev_detail else None
    if detail in (None, "not_in_picture"):
        return None
    return cat.rungs[1] if detail == "bare" else cat.rungs[0]


def jev_pick(cat: Category, j: dict[str, Any]) -> str | None:
    if confident(cat, {JEV_KEY: j}) is None:
        return None
    return jev_rung(cat, j)


def possible(cat: Category, fields: dict[str, Any] | None) -> dict[str, Any] | None:
    j = jev_ok(fields)
    if j is None or not jev_seen(cat, j):
        return None
    score = jev_likelihood(cat, j)
    if score >= FEET_PRESELECT_SCORE or score < FEET_POSSIBLE_MIN:
        return None
    return j


async def _folders_by_name(s, account_id: str, cat: Category) -> dict[str, VaultFolder]:
    return {
        f.name: f for f in (await s.execute(
            select(VaultFolder).where(
                VaultFolder.account_id == account_id,
                VaultFolder.name.in_(cat.folder_names),
                VaultFolder.deleted_at.is_(None),
            )
        )).scalars().all()
    }


async def _shelf(s, account_id: str, cat: Category,
                 folders: dict[str, VaultFolder],
                 allowed: frozenset[int] | None = None) -> list[dict[str, Any]]:
    ids = [f.id for f in folders.values()]
    counts = dict((await s.execute(
        select(VaultFolderItem.folder_id, func.count())
        .outerjoin(VaultItem, (VaultItem.account_id == VaultFolderItem.account_id)
              & (VaultItem.media_id == VaultFolderItem.media_id))
        .where(
            VaultFolderItem.account_id == account_id,
            VaultFolderItem.folder_id.in_(ids),
            visible_to(allowed),
        ).group_by(VaultFolderItem.folder_id)
    )).all()) if ids else {}
    out = []
    for rung in cat.rungs:
        folder = folders.get(cat.folder_name(rung))
        out.append({
            "rung": rung,
            "name": cat.folder_name(rung),
            "folder_id": folder.id if folder else None,
            "count": int(counts.get(folder.id, 0)) if folder else 0,
            "of_list_id": folder.of_list_id if folder else None,
        })
    return out


# A rung is FOLDER MEMBERSHIP only: never ai_fields_json (shared blob, read-modify-write clobbers) nor a VaultItem column (an item can sit on several rungs).
async def candidates(account_id: str, cat: Category, limit: int = 600, *,
                     allowed: frozenset[int] | None = None) -> dict[str, Any]:
    async with get_session() as s:
        folders = await _folders_by_name(s, account_id, cat)
        shelf = await _shelf(s, account_id, cat, folders, allowed)

        by_id = {f.id: name for name, f in folders.items()}
        on_rung = (select(VaultFolderItem.media_id, VaultFolderItem.folder_id).where(
            VaultFolderItem.account_id == account_id, VaultFolderItem.folder_id.in_(list(by_id))))
        filed = {
            int(media_id): by_id[folder_id].removeprefix(f"{cat.name}-")
            for media_id, folder_id in ((await s.execute(on_rung)).all() if by_id else [])
        }

        ai = func.coalesce(VaultItem.ai_fields_json, "")
        ai_ok = case((func.json_valid(ai), ai), else_=literal("{}"))
        jev_photo = ((VaultItem.kind == "photo")
                     & (func.instr(ai, '"_jev"') > 0)
                     & (func.coalesce(func.json_extract(ai_ok, "$._jev.kind"), "") != "video")
                     & or_(*(func.json_extract(ai_ok, f"$._jev.tags.{k}") == "y" for k in cat.jev_seen)))
        items = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.ai_fields_json)
            .where(
                VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                or_(jev_photo, VaultItem.media_id.in_(on_rung.with_only_columns(VaultFolderItem.media_id)))
                if by_id else jev_photo,
                visible_to(allowed),
            )
            .order_by(VaultItem.media_id.desc())
            .limit(_SCAN_CAP)
        )).all()

    rows = []
    for media_id, kind, raw in items:
        mid = int(media_id)
        fields = vault_ai_brief.load_fields(raw)
        j = confident(cat, fields) if kind == "photo" else None
        maybe = possible(cat, fields) if kind == "photo" and j is None else None
        if j is None and maybe is None and mid not in filed:
            continue
        ok = free_ok(fields)
        seen = j if j is not None else maybe
        rung = jev_pick(cat, j) if j is not None else jev_rung(cat, maybe) if maybe is not None else None
        if rung == cat.free_rung and ok is False:
            rung = None
        rows.append({
            "media_id": mid,
            "kind": kind,
            "rung": filed.get(mid),
            "suggested": rung,
            "tier": price_tier(fields),
            "score": round(jev_likelihood(cat, seen), 3) if seen is not None else 0.0,
            "jev": jev_ok(fields) is not None,
            "preselect": j is not None and rung is not None,
            "possible": maybe is not None,
            "free_ok": ok,
            "unsafe_on_free": filed.get(mid) == cat.free_rung and ok is False,
            "description": str(fields.get("description") or "")[:400],
        })
    queue = sorted((r for r in rows if not r["rung"]),
                   key=lambda r: (r["possible"], -r["score"], r["media_id"]))
    on_rungs = sorted((r for r in rows if r["rung"]),
                      key=lambda r: (cat.rungs.index(r["rung"]), r["media_id"]))
    return {
        "category": cat.name,
        "rungs": list(cat.rungs),
        "folders": shelf,
        "candidates": queue[:max(1, min(int(limit), 2000))] + on_rungs,
        "filed": len(on_rungs),
    }


async def triage(
    account_id: str, cat: Category, verdicts: dict[int, str | None], *,
    allowed: frozenset[int] | None = None,
) -> list[dict[str, Any]]:
    """Save the operator's verdicts. Creates the rung folders on first save.

    All rungs are created on the first save even if empty, so the shelf's shape
    is visible from the start rather than appearing a rung at a time.

    A verdict is EXCLUSIVE within a category (filing on `nude` takes it off
    `tease`) and independent across categories. Both fall out of one pass:
    clearing this category's membership for the ruled media before re-adding is
    what makes filing exclusive AND makes a re-save a no-op.

    🚨 A pack is photos only: a video (any non-photo `kind`) on any rung is
    refused (`PhotosOnly`, nothing written), and so is an id with no live mirror
    row (`NotInMirror`); rejecting one (rung None) is fine,
    so one filed before the rule can still come off. A Jev row whose body is not
    known-safe (`free_ok` False) is refused on the free rung: `NotFreeSafe`,
    nothing written; so is any row the describe/flags veto (disputed, a region
    bare), Jev or not. Other rows without a usable `_jev` are the operator's call.
    """
    async with get_session() as s:
        ruled = [m for m, r in verdicts.items() if r is not None]
        missing = await not_in_mirror(s, account_id, ruled)
        if missing:
            raise NotInMirror(missing)
        not_photo = await non_photos(s, account_id, ruled)
        if not_photo:
            raise PhotosOnly(not_photo)
        unsafe = await unsafe_on_free(s, account_id, [m for m, r in verdicts.items() if r == cat.free_rung])
        if unsafe:
            raise NotFreeSafe(unsafe)
        folders = await _folders_by_name(s, account_id, cat)
        for rung in cat.rungs:
            if cat.folder_name(rung) not in folders:
                folder = VaultFolder(
                    account_id=account_id, name=cat.folder_name(rung),
                    created_by=CREATED_BY,
                )
                s.add(folder)
                await s.flush()
                folders[folder.name] = folder

        folder_ids = [f.id for f in folders.values()]
        await s.execute(
            delete(VaultFolderItem).where(
                VaultFolderItem.account_id == account_id,
                VaultFolderItem.folder_id.in_(folder_ids),
                VaultFolderItem.media_id.in_(list(verdicts)),
            )
        )
        for media_id, rung in verdicts.items():
            if rung is None:
                continue
            await s.execute(
                sqlite_insert(VaultFolderItem)
                .values(account_id=account_id,
                        folder_id=folders[cat.folder_name(rung)].id,
                        media_id=media_id)
                .on_conflict_do_nothing(
                    index_elements=["account_id", "folder_id", "media_id"])
            )
        await s.commit()
        return await _shelf(s, account_id, cat, folders, allowed)
