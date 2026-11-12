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
.scratch/jev-vault-bench/feet-eval). Nothing else is proposed: no lower-scored
suggestions, no describe-word (qwen / LIKE) candidates (a photo Jev has not
classified yet waits for it), no videos (`triage` refuses one on any rung:
`PhotosOnly`). Each arrives PRESELECTED on the rung its Jev tier + covering
answer pick (`jev_pick`) when that rung is known and safe, so the operator
unticks what is wrong and files the rest in one click. The same rows make the
opt-in AI-feet folders. Items already filed always come back, whatever they
are, so a rung view can still unfile them. Nothing here talks to OnlyFans.

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
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem
from vault_mirror import visible_to

# Every folder this module makes is the OPERATOR's, not the pipeline's. This one
# string is what keeps `vault_scripts`' reaper off them: it retires only rows
# that are BOTH created_by="vault_ai_script" AND `AI-`-prefixed. Never backfill it.
CREATED_BY = "operator"

# A rung of this value (or null, or empty) means "not this category" — it clears
# the item from every rung. Nothing is stored about a rejection: there is no
# reject list to maintain and nothing repopulates one.
REJECT_VALUES = frozenset({"", "reject", "none"})


@dataclass(frozen=True)
class Category:
    """One sellable subject and its ladder.

    Adding a category is one entry in `CATEGORIES` plus an authored rung phrase
    per language — no new code. That is the whole of stage 3, so the shape is
    explicit rather than a bag of strings.

    `rungs` is the ladder, cheapest first. The folder name is f"{name}-{rung}",
    deliberately WITHOUT an `AI-` prefix so the reaper cannot reach these folders
    even if `created_by` were ever backfilled. A body-part ladder reads
    (covered, bare, bare with her body nude): `jev_pick` relies on that order.
    """
    name: str
    rungs: tuple[str, ...]
    # Jev v8 (`_jev`): `jev_seen` are `tags` keys any of which "y" says the part is in the picture / the
    # subject (a candidate needs one, plus the score gate); `jev_boosts` are `P` keys saying the part is
    # turned to the camera; `jev_detail` is the `tags` key naming what covers the part ("bare" = middle
    # rung, "not_in_picture" = absent, anything else covered = cheapest rung).
    jev_seen: tuple[str, ...] = ()
    jev_boosts: tuple[str, ...] = ()
    jev_detail: str | None = None

    @property
    def free_rung(self) -> str:
        """The cheapest rung: it rides free as the preview, so only a known-safe body may be filed on it."""
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
    """Raised instead of KeyError so the route layer can map it to a 400 without
    catching every KeyError the ORM might throw."""


class UnknownRung(ValueError):
    pass


class InvalidMediaIds(ValueError):
    """Verdict rows whose `media_id` is not a plain int (bool, float, str, missing, or a non-object row): the raw
    values, in order. Refused whole: coercing lands a verdict on the wrong item, dropping one loses it."""

    def __init__(self, media_ids: list[Any]):
        super().__init__(f"invalid media ids: {media_ids!r}")
        self.media_ids = media_ids


class NotFreeSafe(ValueError):
    """Jev rows the triage refused on the free rung (their body is not known-safe): `media_ids`."""

    def __init__(self, media_ids: list[int]):
        super().__init__(f"not free-safe: {media_ids}")
        self.media_ids = media_ids


class PhotosOnly(ValueError):
    """Media the triage refused on every rung: not a photo (`media_ids`). A pack is photos only (owner,
    2026-11-12); a clip's `_jev` is one frame's, so Jev never vouched for the rest of it."""

    def __init__(self, media_ids: list[int]):
        super().__init__(f"photos only: {media_ids}")
        self.media_ids = media_ids


def free_rung_category(folder_name: str | None) -> Category | None:
    """The category whose free rung this folder is (e.g. `feet-tease`), else None."""
    return next((c for c in CATEGORIES.values() if c.folder_name(c.free_rung) == folder_name), None)


def pack_rung_category(folder_name: str | None) -> Category | None:
    """The category one of whose rungs this folder is (e.g. `feet-nude`), else None."""
    return next((c for c in CATEGORIES.values() if folder_name in c.folder_names), None)


def category(name: str | None) -> Category:
    try:
        return CATEGORIES[(name or "").strip().lower()]
    except KeyError:
        raise UnknownCategory(name) from None


def normalise_verdicts(cat: Category, rows: list[dict[str, Any]]) -> dict[int, str | None]:
    """`[{media_id, rung}]` -> `{media_id: rung|None}`, rejecting unknown rungs.

    Filing is validated here rather than at the DB write so a typo'd rung is a
    refusal, never a silently-dropped verdict — a verdict the operator believes
    they made is the one thing this module must not lose. Likewise a `media_id`
    that is not a plain int (bool, float, str, missing) refuses the whole batch
    (`InvalidMediaIds`): never coerced onto another item, never dropped.
    """
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


# ── Score and prefill (pure: read the stored fields, never write them) ──
#
# The Jev v8 pass's block inside `ai_fields_json` (written by `vault_jev`; read-only here; contract:
# `vault_jev_rules.blob`). Only `status == "ok"` carries a trustworthy answer; any other `_jev` (failed,
# no NudeNet, junk) is ignored: the row is no candidate until Jev answers it.
JEV_KEY = "_jev"
JEV_LANE_TIERS = {"$100": 100, "$50": 50, "$10": 10, "free": 0}
# The three body answers that must all be "n" for a Jev row to ride free (y / unsure / missing: not free).
JEV_BODY = ("breasts_bare", "crotch_bare", "penetration")
# Jev scoring priors (rough, not a fit): a part turned to the camera (soles, bare toes) adds to
# `feet_subject` by noisy-OR at this weight; a part Jev says is not in the picture keeps this share.
_EV_JEV_BOOST = 0.3
_DAMP_JEV_ABSENT = 0.25


def _jev(fields: dict[str, Any]) -> dict[str, Any]:
    j = fields.get(JEV_KEY)
    return j if isinstance(j, dict) else {}


def jev_priced(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    """The row's `_jev` when the pass answered it (`status == "ok"` with a lane5), photo or video, else None: the
    lane + body answers `price_tier` and `free_ok` read (a video's are its max frame's: the clip's price)."""
    j = _jev(fields) if isinstance(fields, dict) else {}
    return j if j.get("status") == "ok" and j.get("lane5") else None


def jev_ok(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    """`jev_priced` for a PHOTO only: selected, ranked and prefilled from `_jev`. A video's `_jev` (`kind` "video")
    is None here: its tags are the max frame's only, so feet in any other frame would be dropped."""
    j = jev_priced(fields)
    return j if j is not None and j.get("kind") != "video" else None


def probability_key(cat: Category) -> str:
    """The key of a measured subject probability (0..1) inside `_jev`, e.g.
    `feet_subject`. Jev writes it; `jev_likelihood` reads it."""
    return f"{cat.name}_subject"


def _unit(p: Any) -> float | None:
    """A probability clamped to 0..1, or None for junk (bool, str, NaN, missing)."""
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p):
        return None
    return min(1.0, max(0.0, float(p)))


def _jev_tags(j: dict[str, Any]) -> dict[str, Any]:
    t = j.get("tags")
    return t if isinstance(t, dict) else {}


def jev_seen(cat: Category, j: dict[str, Any]) -> bool:
    """Jev says the part is in the picture or is its subject (any `cat.jev_seen` tag "y")."""
    tags = _jev_tags(j)
    return any(tags.get(k) == "y" for k in cat.jev_seen)


def jev_likelihood(cat: Category, j: dict[str, Any]) -> float:
    """How likely the part is the SUBJECT, from Jev alone: `feet_subject` (P feet_focus), raised by noisy-OR
    when the part is turned to the camera (`jev_boosts`: soles, bare toes), damped when Jev's covering answer
    says it is not in the picture."""
    p = _unit(j.get(probability_key(cat))) or 0.0
    probs = j.get("P") if isinstance(j.get("P"), dict) else {}
    boost = max([_unit(probs.get(k)) or 0.0 for k in cat.jev_boosts] or [0.0])
    p += (1.0 - p) * _EV_JEV_BOOST * boost   # noisy-OR, exact when there is no boost
    if cat.jev_detail and _jev_tags(j).get(cat.jev_detail) == "not_in_picture":
        p *= _DAMP_JEV_ABSENT
    return p


def jev_tier(j: dict[str, Any]) -> int | None:
    """Her body's price tier from Jev: lane5 $100 / $50 / $10, or 0 ONLY for lane5 "free" with breasts,
    crotch and penetration all "n". 🚨 "review", junk, or free with any body answer y / unsure / missing is
    None (unknown): settle nn.10 can file an unsure body free, and the free rung must never carry one."""
    lane5 = str(j.get("lane5") or "")
    if lane5 == "free":
        return 0 if all(j.get(k) == "n" for k in JEV_BODY) else None
    tier = JEV_LANE_TIERS.get(lane5)
    return tier if tier else None


def free_ok(fields: dict[str, Any] | None) -> bool | None:
    """May this item ride the free rung? Jev-priced rows (`jev_priced`, videos too): True only at Jev tier 0 (False
    otherwise; `triage` enforces it). Rows without a usable `_jev`: None (unknown; the operator decides)."""
    j = jev_priced(fields)
    return None if j is None else jev_tier(j) == 0


async def non_photos(s, account_id: str, media_ids: list[int]) -> list[int]:
    """Of `media_ids`, those whose `kind` is not a photo, sorted. A pack is photos only: `triage` refuses them on any
    rung; a rung's publish skips them (a clip filed before the rule)."""
    if not media_ids:
        return []
    return sorted(int(m) for (m,) in (await s.execute(
        select(VaultItem.media_id).where(
            VaultItem.account_id == account_id, VaultItem.media_id.in_(media_ids),
            VaultItem.kind != "photo")
    )).all())


async def unsafe_on_free(s, account_id: str, media_ids: list[int]) -> list[int]:
    """Of `media_ids`, those that may not ride the free rung (`free_ok` False), sorted. `triage` refuses them there;
    the free rung's publish skips them (a row filed before the guard, or whose Jev answer changed since)."""
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
    """The owner's price tier her BODY is at in this item, from Jev alone (`jev_priced`, a video's max frame
    too): `jev_tier` (100 inserted, 50 labia visible, 10 topless, 0 nothing on show and every body answer "n").
    None: Jev has not priced it, or its answer is unknown ("review", an unsure body)."""
    j = jev_priced(fields)
    return None if j is None else jev_tier(j)


# The most rows one candidate read scans: a whole 20k vault (what one Collect
# sweep mirrors) of Jev-seen photos. Bounds a pathological vault, no more.
_SCAN_CAP = 20_000

# The candidate gate (and so the prefill + preselect: the tile arrives ticked, the operator only confirms; the
# AI-feet folders take the same rows, `vault_topic_folders`). Measured on the owner's hand-picked feet set (Jev v8
# eval 2026-11-12, .scratch/jev-vault-bench/feet-eval): score >= .6 -> precision 1.0, recall .29; anything lower
# .33-.87. Below it a photo is no candidate at all (owner: a small set of good photos, not a lot of half-assed ones).
FEET_PRESELECT_SCORE = 0.6


def confident(cat: Category, fields: dict[str, Any] | None) -> dict[str, Any] | None:
    """The row's `_jev` when it is a candidate: a Jev photo (`jev_ok`; the caller checks the row's `kind`) that
    sees the part (`jev_seen`) at `jev_likelihood` >= `FEET_PRESELECT_SCORE`, else None."""
    j = jev_ok(fields)
    if j is None or not jev_seen(cat, j) or jev_likelihood(cat, j) < FEET_PRESELECT_SCORE:
        return None
    return j


def jev_pick(cat: Category, j: dict[str, Any]) -> str | None:
    """The rung a confident Jev photo (`confident`) arrives PRESELECTED on, else None (the operator decides).

    Her body on show at any price tier is the top rung whatever is on her feet: the cheapest rung rides free as
    the preview, so a priced body never lands there. 🚨 An UNKNOWN tier (`jev_tier` None: "review", an unsure
    body) is never picked: a body Jev half-saw would ride the free preview. A known tier 0 reads Jev's covering
    answer (`jev_detail`): bare -> the middle rung, covered -> the cheapest, not in the picture -> None.
    The one definition both the pack picker's `suggested` / `preselect` and the AI-feet folders
    (`vault_topic_folders`) use."""
    if confident(cat, {JEV_KEY: j}) is None:
        return None
    tier = jev_tier(j)
    if tier is None:
        return None
    if tier > 0:
        return cat.rungs[2]
    detail = _jev_tags(j).get(cat.jev_detail) if cat.jev_detail else None
    if detail in (None, "not_in_picture"):
        return None
    return cat.rungs[1] if detail == "bare" else cat.rungs[0]


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
    """The rungs and how full each is, cheapest first.

    One shape, returned by BOTH `candidates` and `triage`, so the client renders
    the shelf from the same source whether it just saved or just opened. A rung
    with no folder yet reports `folder_id: None` and count 0 rather than being
    absent — the ladder's shape should not depend on how far triage has got.
    `allowed`: a restricted chatter's counts are of the media it may see only
    (`vault_mirror.visible_to`).
    """
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


async def candidates(account_id: str, cat: Category, limit: int = 600, *,
                     allowed: frozenset[int] | None = None) -> dict[str, Any]:
    """The category's candidates, most likely first, each carrying the rung it
    is filed on now, its preselected rung and its body's price tier, plus the
    shelf those rungs currently make. `allowed`
    (chatters.allowed_folder_ids_for_chatter): a restricted chatter's OF folders —
    only candidates in them; None = the whole vault.

    The queue (unfiled) is the `confident` photos only: Jev answered it, sees the
    part (`_jev.tags`, read in SQL with the photo kind, so a feet photo whose
    describe never says "feet" is found) and scores it >= `FEET_PRESELECT_SCORE`.
    Python then scores and sorts (`jev_likelihood` needs the whole blob). `limit`
    caps that queue; items already on a rung always come back, after it, whatever
    they are (a video, a photo Jev never saw, a score below the gate), so the rung
    views still show them and they can be unfiled; they never take a queue slot.
    `suggested` and `preselect` are `jev_pick`: the tile arrives ticked on it, for
    the operator's one-click "File N preselected" (a `triage`). `free_ok` tells the
    client which tiles may not go on the free rung; `unsafe_on_free` marks one
    already filed there anyway (publish skips it).

    The description rides along because a tile is still rejectable on text
    alone, and that pass costs no pixels.

    🚨 The rung of an item is FOLDER MEMBERSHIP and nothing else. Never
    `ai_fields_json` (a shared blob — a read-modify-write clobbers whatever other
    writer touched it last) and never a column on `VaultItem` (membership is not
    single-valued: an item can be a feet keeper and a heels keeper at once).
    `suggested` is only a prefill the client shows until a verdict is saved.
    """
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
        # Malformed JSON never reaches json_extract (it raises); the instr prefilter skips most rows first.
        ai_ok = case((func.json_valid(ai), ai), else_=literal("{}"))
        jev_photo = ((VaultItem.kind == "photo")
                     & (func.instr(ai, '"_jev"') > 0)
                     & (func.coalesce(func.json_extract(ai_ok, "$._jev.kind"), "") != "video")   # `jev_ok`
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
            # Deterministic under the cap: the newest uploads (highest ids) win a capped scan.
            .order_by(VaultItem.media_id.desc())
            .limit(_SCAN_CAP)
        )).all()

    rows = []
    for media_id, kind, raw in items:
        mid = int(media_id)
        fields = vault_ai_brief.load_fields(raw)
        j = confident(cat, fields) if kind == "photo" else None
        if j is None and mid not in filed:
            continue  # not a confident Jev photo: no suggestion, it waits for Jev (or is not feet)
        ok = free_ok(fields)
        rung = jev_pick(cat, j) if j is not None else None
        rows.append({
            "media_id": mid,
            "kind": kind,
            "rung": filed.get(mid),
            "suggested": rung,
            "tier": price_tier(fields),
            "score": round(jev_likelihood(cat, j), 3) if j is not None else 0.0,
            "jev": jev_ok(fields) is not None,
            "preselect": rung is not None,
            "free_ok": ok,
            "unsafe_on_free": filed.get(mid) == cat.free_rung and ok is False,
            "description": str(fields.get("description") or "")[:400],
        })
    queue = sorted((r for r in rows if not r["rung"]),
                   key=lambda r: (-r["score"], r["media_id"]))
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
    refused (`PhotosOnly`, nothing written); rejecting one (rung None) is fine,
    so one filed before the rule can still come off. A Jev row whose body is not
    known-safe (`free_ok` False) is refused on the free rung: `NotFreeSafe`,
    nothing written. Rows without a usable `_jev` are the operator's call.
    """
    async with get_session() as s:
        ruled = [m for m, r in verdicts.items() if r is not None]
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
