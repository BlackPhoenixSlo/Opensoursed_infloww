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

So the query proposes and the operator disposes. The proposing is cheap but
ranked (`likelihood`): the stored structured fields first (`primary_folder`,
`body_focus` and how crowded it is, `tags`), the description's words after, so
the likely keepers lead the grid; and each tile arrives with the rung its flags
suggest (`suggest`, read off the owner's price tiers) so the operator mostly
confirms. Nothing here talks to OnlyFans.

Routes live in `vault_ai_api` (house convention — that module owns every
`/admin/vault-ai/*` route and the `vault_*` siblings own the logic).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, or_, select
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

    `term` is LIKE-scanned against `search_text` (the denormalised
    tags + description + notes blob) AND against `ai_fields_json`. The union is
    the generator the 2026-08-01 triage was drawn from, and it is deliberately
    over-inclusive: rejecting is cheap, missing a keeper is not.

    `rungs` is the ladder, cheapest first. The folder name is f"{name}-{rung}",
    deliberately WITHOUT an `AI-` prefix so the reaper cannot reach these folders
    even if `created_by` were ever backfilled. A body-part ladder reads
    (covered, bare, bare with her body nude): `suggest` relies on that order.

    `words` are description words that name the subject outright ("soles",
    "toes") rather than merely mention the part; they generate candidates too
    and weigh more than `term` in `likelihood`. `covered_by` are garments over
    the part that put an item on the cheapest rung, unless the description has
    one of `bare_words`.
    """
    name: str
    term: str
    rungs: tuple[str, ...]
    words: tuple[str, ...] = ()
    covered_by: tuple[str, ...] = ()
    bare_words: tuple[str, ...] = ()

    def folder_name(self, rung: str) -> str:
        return f"{self.name}-{rung}"

    @property
    def folder_names(self) -> list[str]:
        return [self.folder_name(r) for r in self.rungs]


CATEGORIES: dict[str, Category] = {
    c.name: c for c in (
        Category(name="feet", term="feet", rungs=("tease", "nude", "nude-body"),
                 words=("soles", "toes", "barefoot", "bare feet"),
                 covered_by=("sock", "stocking", "tights", "pantyhose", "heel",
                             "boot", "shoe", "sneaker", "slipper", "trainer"),
                 bare_words=("barefoot", "bare feet", "bare soles")),
    )
}


class UnknownCategory(KeyError):
    """Raised instead of KeyError so the route layer can map it to a 400 without
    catching every KeyError the ORM might throw."""


class UnknownRung(ValueError):
    pass


def category(name: str | None) -> Category:
    try:
        return CATEGORIES[(name or "").strip().lower()]
    except KeyError:
        raise UnknownCategory(name) from None


def normalise_verdicts(cat: Category, rows: list[dict[str, Any]]) -> dict[int, str | None]:
    """`[{media_id, rung}]` -> `{media_id: rung|None}`, rejecting unknown rungs.

    Filing is validated here rather than at the DB write so a typo'd rung is a
    refusal, never a silently-dropped verdict — a verdict the operator believes
    they made is the one thing this module must not lose.
    """
    out: dict[int, str | None] = {}
    for row in rows or []:
        try:
            media_id = int(row["media_id"])
        except (KeyError, TypeError, ValueError):
            continue
        rung = str(row.get("rung") or "").strip().lower()
        if rung in REJECT_VALUES:
            out[media_id] = None
        elif rung in cat.rungs:
            out[media_id] = rung
        else:
            raise UnknownRung(rung)
    return out


# ── Ranking and prefill (pure: read the stored fields, never write them) ──
#
# The generator stays the wide LIKE union (rejecting is cheap, missing a keeper
# is not); what this adds is the ORDER and a prefilled rung. The grid used to
# come back in media_id order, so every screen of it was the base rate: ~22%
# keepers. Each signal below is one piece of evidence that the part is the
# SUBJECT, folded by noisy-OR, so two weak signals beat one and no threshold is
# hand-tuned per signal. The weights are rough priors, not a fit.
_EV_FOLDER = 0.85   # primary_folder names the category: the describe pass's own call
_EV_TAG = 0.5       # a tag says so (tags list what is VISIBLE, so weaker)
_EV_WORD = 0.4      # the description names the subject outright ("soles", "toes")
_EV_TERM = 0.12     # the description merely mentions the part: the 22% signal
# body_focus lists the part whenever it is VISIBLE, so it is evidence only as
# strong as it is alone: ["feet"] is a feet picture, ["face", "breasts", "legs",
# "feet"] a lingerie pose with her feet in frame.
_EV_FOCUS_ALONE = 0.7
# A payoff act or a partner makes the part a bystander, whatever was tagged.
_DAMP_ACT = 0.4
_DAMP_PARTNER = 0.5
_BYSTANDER_ACTS = frozenset({
    "fingering", "toy_insertion", "toy_on_clit", "riding_toy", "rubbing_clit",
    "masturbation_orgasm", "squirt", "blowjob", "handjob", "cumshot",
    "sex_missionary", "sex_doggy", "sex_riding",
})


# The Jev pass's block inside `ai_fields_json` (written by the describe side;
# read-only here): {"v", "lane5": "$100"|"$50"|"$10"|"free", "feet_subject":
# P(feet focus), ...}. Absent on rows Jev never saw: then the qwen reading rules.
JEV_KEY = "_jev"
JEV_LANE_TIERS = {"$100": 100, "$50": 50, "$10": 10, "free": 0}


def _jev(fields: dict[str, Any]) -> dict[str, Any]:
    j = fields.get(JEV_KEY)
    return j if isinstance(j, dict) else {}


def probability_key(cat: Category) -> str:
    """The key of a measured subject probability (0..1) inside `_jev`, e.g.
    `feet_subject`. Jev writes it; `likelihood` reads it when present."""
    return f"{cat.name}_subject"


def _words(fields: dict[str, Any], key: str) -> list[str]:
    v = fields.get(key)
    if isinstance(v, str):
        v = [v]
    return [str(x).strip().lower() for x in v] if isinstance(v, list) else []


def _measured(cat: Category, fields: dict[str, Any]) -> float | None:
    p = _jev(fields).get(probability_key(cat))
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p):
        return None
    return min(1.0, max(0.0, float(p)))


def likelihood(cat: Category, fields: dict[str, Any] | None, text: str = "") -> float:
    """How likely the category's part is the SUBJECT of this item, 0..1.

    Jev's measured `_jev[probability_key]` wins outright when the row has one. Otherwise
    the structured fields' evidence, then the description's words (`text`, the
    search blob, stands in on a row with no description).
    """
    fields = fields if isinstance(fields, dict) else {}
    measured = _measured(cat, fields)
    if measured is not None:
        return measured
    ev: list[float] = []
    if _words(fields, "primary_folder")[:1] == [cat.name]:
        ev.append(_EV_FOLDER)
    tags = set(_words(fields, "tags"))
    if cat.term in tags or tags & set(cat.words):
        ev.append(_EV_TAG)
    focus = _words(fields, "body_focus")
    if cat.term in focus:
        ev.append(_EV_FOCUS_ALONE / len(focus))
    blob = (str(fields.get("description") or "") or text or "").lower()
    if any(w in blob for w in cat.words):
        ev.append(_EV_WORD)
    elif cat.term in blob:
        ev.append(_EV_TERM)
    p = 1.0 - math.prod(1.0 - e for e in ev)
    if set(_words(fields, "acts")) & _BYSTANDER_ACTS:
        p *= _DAMP_ACT
    if fields.get("partner_visible") is True:
        p *= _DAMP_PARTNER
    return p


def price_tier(fields: dict[str, Any] | None) -> int | None:
    """The owner's price tier her BODY is at in this item: 100 something
    inserted, 50 labia visible, 10 topless or full frontal with the labia hidden
    (a hand, not a garment, over her vulva), 0 nothing on show. The anus never
    sets a price. None: the flags pass never looked and nothing is inserted.

    Jev's `_jev.lane5` wins when present ("free" is a known 0; "review", the
    NudeNet veto, is unknown: None, so never prefilled free). Else read off
    the qwen `settled_reading`, so a disputed item prices as the lanes price
    it, and an insertion the frame cannot show (penetration_offscreen) is none.
    """
    if not isinstance(fields, dict):
        return None
    lane5 = str(_jev(fields).get("lane5") or "")
    if lane5 == "review":
        return None  # Jev's NudeNet veto: may be explicit, so never a known (free) tier
    lane = JEV_LANE_TIERS.get(lane5)
    if lane is not None:
        return lane
    f = vault_ai_brief.settled_reading(fields) or fields
    if (vault_ai_brief.penetration_claimed(f)
            and "penetration_offscreen" not in vault_ai_brief.settled_codes(f)):
        return 100
    if not vault_ai_brief.flags_known(f):
        return None
    if vault_ai_brief.is_bare(f, "vulva_vis"):
        return 50
    if vault_ai_brief.is_bare(f, "breasts_vis"):
        return 10
    over = vault_ai_brief.garment_over(f, "vulva_vis")
    if (vault_ai_brief.vis(f, "vulva_vis") == "covered" and over
            and not vault_ai_brief.is_clothing(over)):
        return 10
    return 0


# The most rows one candidate read scans: a whole 20k vault (what one Collect
# sweep mirrors) mentioning the part. Bounds a pathological LIKE hit, no more.
_SCAN_CAP = 20_000

# Below this likelihood a tile gets no prefilled rung: the operator decides.
SUGGEST_MIN = 0.5
_NUDE_STATES = frozenset({"fully_nude", "partially_off", "pulled_down", "pulled_aside"})


def suggest(cat: Category, fields: dict[str, Any] | None, p: float) -> str | None:
    """The rung to prefill, or None (not likely enough to be the subject).

    Her body on show at any price tier is the top rung whatever is on her feet:
    the cheapest rung rides free as the preview, so a priced body must never be
    prefilled there. 🚨 An UNKNOWN tier (no `_jev.lane5`, no qwen flags) is never
    prefilled below the top rung: a nude body the describe missed would ride the
    free preview. Its describe `clothing_state` may still say nude (-> the top,
    paid rung); anything else gets no prefill and the operator decides. A known
    tier 0: the part covered (`covered_by`, unless the description has a
    `bare_words`) is the cheapest rung, bare the middle one.
    """
    if p < SUGGEST_MIN or len(cat.rungs) < 3 or not isinstance(fields, dict):
        return None
    tier = price_tier(fields)
    if tier is None:
        nude = str(fields.get("clothing_state") or "").lower() in _NUDE_STATES
        return cat.rungs[2] if nude else None
    if tier > 0:
        return cat.rungs[2]
    desc = str(fields.get("description") or "").lower()
    worn = " ".join(_words(fields, "clothing_items"))
    if (not any(w in desc for w in cat.bare_words)
            and any(g in worn for g in cat.covered_by)):
        return cat.rungs[0]
    return cat.rungs[1]


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
    is filed on now, its prefilled rung and its body's price tier, plus the
    shelf those rungs currently make. `allowed`
    (chatters.allowed_folder_ids_for_chatter): a restricted chatter's OF folders —
    only candidates in them; None = the whole vault.

    One SQL for the candidates (the LIKE union, newest first under `_SCAN_CAP`) and a Python
    sort by `likelihood`: the ranking needs every candidate's fields before it
    can cut. `limit` caps the UNFILED candidates (the triage queue); items
    already on a rung always come back, after them, so the rung views still show
    them and they never take a queue slot.

    The description rides along because roughly half the set is rejectable on
    text alone — "walks away from the camera on a paved street" is not a feet
    picture whatever the tag says — and that pass costs no pixels.

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
        filed = {
            int(media_id): by_id[folder_id].removeprefix(f"{cat.name}-")
            for media_id, folder_id in (
                (await s.execute(
                    select(VaultFolderItem.media_id, VaultFolderItem.folder_id).where(
                        VaultFolderItem.account_id == account_id,
                        VaultFolderItem.folder_id.in_(list(by_id)),
                    )
                )).all() if by_id else []
            )
            if folder_id in by_id
        }

        text = func.coalesce(VaultItem.search_text, "")
        items = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.ai_fields_json,
                   VaultItem.search_text)
            .where(
                VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                or_(
                    *(text.like(f"%{w}%") for w in (cat.term, *cat.words)),
                    func.coalesce(VaultItem.ai_fields_json, "").like(f'%"{cat.term}"%'),
                ),
                visible_to(allowed),
            )
            # Deterministic under the cap: the newest uploads (highest ids) win a capped scan.
            .order_by(VaultItem.media_id.desc())
            .limit(_SCAN_CAP)
        )).all()

    rows = []
    for media_id, kind, raw, search_text in items:
        fields = vault_ai_brief.load_fields(raw)
        p = likelihood(cat, fields, search_text or "")
        rows.append({
            "media_id": int(media_id),
            "kind": kind,
            "rung": filed.get(int(media_id)),
            "suggested": suggest(cat, fields, p),
            "tier": price_tier(fields),
            "score": round(p, 3),
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
    """
    async with get_session() as s:
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
