"""automations/full_ai_sell.py — Full AI Chat's Sell executor (spec 03b, ticket 10 r3).

The sell step runs `load_rows` -> `pool` -> `shoots_for` -> `pick` and gets one
Pick or a Refusal. Pure apart from the async `load_rows` (DB reads) and
`shoots_for` (a coroutine doing no I/O when given rows and prints). No network,
no LLM, no OF client, send, lease or cooldown: it joins Shadow's strict no-send
scan (test_full_ai_shadow.py). There is no offer cap.

`in_folders(refs, include, exclude)`: the Creator's folder choice. Refs are
`vf:<vault_folders.id>` and `of:<OF list id>`; an empty include is the whole
vault, unfiled items too; exclude wins; a ref naming no live folder matches
nothing, and a non-empty include never falls back to all.

`list_price_cents(jev, fields, kind)`: one price per item, ticket 10 r3. A
current Jev blob prices by its lane ($10 / $50 / $100; a review lane has no
price, checked before `lane_of` reads a review clip's `read_lane5`); without
one, the shelf price ($50 / $10; 0 is no price, never free). An explicit act
moves the lane up the owner's ladder ($50 / $100 / $150). Clamped to $10-$200.
"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from sqlalchemy import select

import vault_ai_brief
import vault_dupes
import vault_pack_picker
import vault_scripts
import vault_topic_folders as vtf
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem

log = logging.getLogger("of-relay.automation.full_ai_sell")

Subject = Literal["feet", "butt", "tits", "pussy", "nude", "lingerie", "bikini", "shower", "toy",
                  "masturbation", "blowjob", "sex", "anything"]
Format = Literal["photo", "video", "any"]
Reason = Literal["sell_off", "inventory_unknown", "no_priced_items", "no_match", "all_owned"]

MIN_CENTS = 1000
MAX_CENTS = 20000
_LANE_CENTS = {"free": 0, "$10": 1000, "$50": 5000, "$100": 10000, "$150": 15000}


@dataclass(frozen=True)
class Ask:
    """What he asks for: the Router's `asks_subject` / `asks_format` and his `intensity` (1-4)."""
    subject: Subject
    format: Format
    intensity: int


@dataclass(frozen=True)
class Pick:
    """One offer: locked `media` (first = `ref`, the `>>OFFER` ref), free `previews`, the price."""
    ref: int
    media: tuple[int, ...]
    previews: tuple[int, ...]
    price_cents: int
    list_cents: int
    subject: str
    format: str
    lane: str
    facts: dict[str, Any]


@dataclass(frozen=True)
class Refusal:
    reason: Reason


# Ask subject -> the TOPICS it retrieves (ticket 10 r3). feet reads the Feet-pack rungs instead
# (no feet topic, by owner); lingerie is Jev's outfit tag, a split topic of its own here.
_LINGERIE = vtf.Topic("lingerie", "lingerie", "in lingerie or a bodysuit", "split",
                      lambda j, f: vtf._tag(j, "outfit") == "lingerie_or_bodysuit")
_TOPICS: dict[str, tuple[vtf.Topic, ...]] = {
    subject: tuple(vtf.BY_SLUG[s] for s in slugs) for subject, slugs in {
        "butt": ("butt_tease", "butt_bare"), "tits": ("tits", "boobs_closeup"),
        "pussy": ("pussy", "spread"), "nude": ("nude",), "bikini": ("bikini",),
        "shower": ("shower_bath",), "toy": ("toy_tease", "toy_play"),
        "masturbation": ("masturbation",), "blowjob": ("blowjob",), "sex": ("sex", "with_partner"),
    }.items()}
_TOPICS["lingerie"] = (_LINGERIE,)
FEET_PACK = "feet"   # `vault_pack_picker.CATEGORIES` name; `load_rows` puts it in a row's `packs`
# ASSUMPTION: a subject matches when `split` files the row in any of its topics (so a row
# with no current Jev blob matches only feet / anything), and feet reads the row's `packs`
# (its Feet-pack rung folders). Overturned if retrieval should read the describe fields alone.

# The asks sold without the solo rule (a partner is the point of them).
_PARTNER_OK = frozenset({"sex", "blowjob"})


def in_folders(refs: Iterable[str], include: Iterable[str], exclude: Iterable[str]) -> bool:
    """The item (its folder `refs`) is inside the folder choice."""
    refs = set(refs)
    if refs & set(exclude):
        return False
    include = set(include)
    return not include or bool(refs & include)


def seed_for(account_id: str, fan_id: str, trigger_key: str) -> str:
    """The Pick's seed: a replayed Turn draws the same Pick."""
    return f"pick:{account_id}:{fan_id}:{trigger_key}"


def clamp_cents(cents: int) -> int:
    """A sale price inside [$10, $200]."""
    return max(MIN_CENTS, min(MAX_CENTS, int(cents)))


def list_price_cents(jev: dict[str, Any] | None, fields: dict[str, Any], kind: str) -> int | None:
    """The item's list price in cents, or None (not for sale). `jev` is its current Jev blob
    (`vault_topic_folders.jev_of(fields)`), None without one.

    ASSUMPTION: the Jev "free" lane prices 0, an item kept in the pool only as a preview or a
    free item, never a locked paid one (ticket 10 r3: "free" -> preview/gift only); 0 is not
    clamped up. Overturned if the owner wants free-lane items out of the pool."""
    fields = fields or {}
    if jev is not None:
        if jev.get("lane5") == "review":
            return None
        lane = vtf.lane_of(jev)
    else:
        lane = {50: "$50", 10: "$10"}.get(vault_scripts.shelf_price(fields, kind))
    if lane not in vtf.PRICES:
        return None
    if vtf._explicit(jev or {}, fields):
        # Explicit topics are never free (`vault_topic_folders.split`).
        if lane == "free":
            return None
        lane = vtf._EXPLICIT_OF[lane]
    cents = _LANE_CENTS[lane]
    return cents and clamp_cents(cents)


def _of_refs(raw: str | None) -> set[str]:
    """`vault_items.of_folder_ids` as `of:<id>` refs. The ids are kept as stored, int or string
    (`vault_mirror` stores OF's `listStates[].id` unconverted). Bad JSON or a non-list raises.

    ASSUMPTION: a bad stored value is an error (-> inventory_unknown), not `[]` as the house parse
    (`vault_of_folders_decide.parse_folder_ids`) reads it: the spec makes any error reading folder
    refs fail closed, and `[]` would read as unfiled, inside an empty include. Overturned if bad
    values are common enough that refusing the whole vault costs more than the unfiled read."""
    ids = json.loads(raw) if raw else []
    if not isinstance(ids, list):
        raise ValueError(f"of_folder_ids not a list: {raw!r}")
    return {f"of:{x}" for x in ids if x is not None}


async def load_rows(account_id: str) -> tuple[list[dict[str, Any]], list[list[int]],
                                              dict[int, dict[str, Any]]] | Refusal:
    """The Creator's vault as the pool reads it: `vault_scripts._load_rows` rows, each with its
    folder `refs` (`vf:<id>` per live internal folder, `of:<id>` per OF list) and `packs` (the
    Pack categories of its folders, e.g. feet); the dupe groups, read straight from
    `vault_dupes.find_duplicates` (an error there would drop the dupe expansion of Owned media);
    and the near-dupe `prints` (`vault_scripts._fingerprints`, `{}` on its own error: only
    near-dupe collapse inside a shoot is lost). Any error in rows, refs or dupe groups ->
    Refusal("inventory_unknown").

    ASSUMPTION: a deleted folder (`deleted_at` set) gives no ref, so a choice naming it matches
    nothing (ticket 41). Overturned if a deleted folder's members should still count as in it."""
    try:
        rows = await vault_scripts._load_rows(account_id)
        async with get_session() as s:
            of_raw = dict((await s.execute(
                select(VaultItem.media_id, VaultItem.of_folder_ids)
                .where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)))).all())
            members = (await s.execute(
                select(VaultFolderItem.media_id, VaultFolder.id, VaultFolder.name)
                .join(VaultFolder, VaultFolder.id == VaultFolderItem.folder_id)
                .where(VaultFolderItem.account_id == account_id, VaultFolder.account_id == account_id,
                       VaultFolder.deleted_at.is_(None)))).all()
        refs: dict[int, set[str]] = {}
        packs: dict[int, set[str]] = {}
        for mid, raw in of_raw.items():
            refs.setdefault(int(mid), set()).update(_of_refs(raw))
        for mid, fid, name in members:
            refs.setdefault(int(mid), set()).add(f"vf:{fid}")
            if (cat := vault_pack_picker.pack_rung_category(name)) is not None:
                packs.setdefault(int(mid), set()).add(cat.name)
        res = await vault_dupes.find_duplicates(account_id, rehash=False)
        groups = [[int(m["media_id"]) for m in (c["original"], *c["dupes"])] for c in res["clusters"]]
    except Exception:  # noqa: BLE001 — fail closed, never an un-expanded owned set
        log.exception("sell inventory unreadable account=%s", account_id)
        return Refusal("inventory_unknown")
    prints = await vault_scripts._fingerprints(account_id)
    out = [{**r, "refs": refs.get(r["media_id"], set()), "packs": packs.get(r["media_id"], set())}
           for r in rows]
    return out, groups, prints


def expand_owned(owned: Iterable[int], dupe_groups: list[list[int]]) -> set[int]:
    """`owned` plus every duplicate copy of each owned item (one copy owned = the set owned, D13)."""
    out = {int(m) for m in owned}
    for group in dupe_groups:
        if out.intersection(group):
            out.update(int(m) for m in group)
    return out


def pool(rows: list[dict[str, Any]], dupe_groups: list[list[int]], owned: Iterable[int],
         folders: dict[str, Any], ask: Ask) -> list[dict[str, Any]] | Refusal:
    """The rows `pick` may draw from, each with its script `why` and `list_cents`, or a Refusal.

    Folder filter, then `collapse_dupes`, then `_with_script_why` (`_unpriced_dispute` reads it),
    then drop Owned media and every dupe copy of it, partner content unless `ask` is sex /
    blowjob, disputed-price items and items with no list price. No offer history is read, so an
    unbought item stays however often it was offered.

    ASSUMPTION: an empty pool is a Refusal, not `[]`, so the cause survives (ticket 10 r3's
    `pool -> list | Refusal`): nothing in the folders -> no_match, nothing priced -> no_priced_items,
    nothing solo for a solo ask -> no_match, every sellable item owned -> all_owned. Overturned if
    the sell step wants `[]` and derives the reason itself.
    ASSUMPTION: unknown solo (`sellability().solo` None: no `people_count`, no `partner_visible`)
    is dropped, as `vault_scripts.is_solo` refuses to guess. Overturned if the owner wants V1
    rows (no people answer) sold on solo asks."""
    include, exclude = folders.get("include") or [], folders.get("exclude") or []
    # `r["refs"]`, never a default: a row without refs would read as unfiled and slip past exclude.
    chosen = [r for r in rows if in_folders(r["refs"], include, exclude)]
    chosen, _ = vault_scripts.collapse_dupes(chosen, dupe_groups)
    if not chosen:
        return Refusal("no_match")
    priced = []
    for r in map(vault_scripts._with_script_why, chosen):
        fields = r.get("fields") or {}
        cents = list_price_cents(vtf.jev_of(fields), fields, r["kind"])
        if cents is not None and not vault_scripts._unpriced_dispute(r):
            priced.append({**r, "list_cents": cents})
    if not priced:
        return Refusal("no_priced_items")
    if ask.subject not in _PARTNER_OK:
        priced = [r for r in priced if vault_ai_brief.sellability(r.get("fields") or {})["solo"] is True]
        if not priced:
            return Refusal("no_match")
    gone = expand_owned(owned, dupe_groups)
    left = [r for r in priced if r["media_id"] not in gone]
    return left or Refusal("all_owned")


async def shoots_for(account_id: str, pool: list[dict[str, Any]],
                     prints: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """The pool's shoots, photo-only ones too (no clip minimum, one item is enough, no escalation
    needed). With `rows` and `prints` passed it reads nothing, but it is a coroutine, so it runs in
    the sell step and `pick` stays pure."""
    return await vault_scripts.collect_outfit_scripts(
        account_id, rows=pool, prints=prints, min_items=1, min_videos=0, require_escalation=False)


def target_cents(intensity: int) -> int:
    """The heat target lane: intensity 1-2 -> $10, 3 -> $50, 4 -> $100."""
    return 1000 if intensity <= 2 else 5000 if intensity == 3 else 10000


def _lane(cents: int) -> str:
    return next((lane for lane, c in _LANE_CENTS.items() if c == cents), f"${cents // 100}")


def _matches(row: dict[str, Any], ask: Ask) -> bool:
    if ask.format != "any" and row["kind"] != ask.format:
        return False
    if ask.subject == "anything":
        return True
    if ask.subject == "feet":
        return FEET_PACK in (row.get("packs") or ())
    fields = row.get("fields") or {}
    jev = vtf.jev_of(fields)
    return jev is not None and any(vtf.split(t, jev, fields) is not None
                                   for t in _TOPICS.get(ask.subject, ()))


def _free_safe(row: dict[str, Any]) -> bool:
    """A free-lane row may go out free: Jev's free guard holds."""
    jev = vtf.jev_of(row.get("fields") or {})
    return jev is not None and vtf.free_ok(jev)


def _draw(rows: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    return rng.choice(sorted(rows, key=lambda r: r["media_id"]))


def _facts(locked: list[dict[str, Any]]) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    for r in locked:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"kinds": kinds,
            "items": [vault_ai_brief.sellability(r.get("fields") or {},
                                                 duration_seconds=r.get("duration_seconds"))
                      for r in locked]}


def _offer(locked: list[dict[str, Any]], previews: list[dict[str, Any]], ask: Ask, *,
           free: bool, subject: str | None = None) -> Pick:
    top = max(r["list_cents"] for r in locked)
    return Pick(ref=locked[0]["media_id"], media=tuple(r["media_id"] for r in locked),
                previews=tuple(r["media_id"] for r in previews), price_cents=0 if free else top,
                list_cents=top, subject=subject or ask.subject, format=locked[0]["kind"], lane=_lane(top),
                facts=_facts(locked))


def pick(pool: list[dict[str, Any]], shoots: list[dict[str, Any]], ask: Ask, *,
         seed: str, free: bool = False) -> Pick | Refusal:
    """One Pick from `pool` (`pool()`'s rows, the sell step having handled its Refusal) for `ask`,
    by a seeded draw (`seed_for`). Pure.

    Retrieval is broad, through the TOPICS rules (`vault_topic_folders.split`); feet from the
    Feet-pack rungs; the format filters the kind. The lane is the lowest at or above the heat
    target (`target_cents`), else the subject's lowest; one row of it is drawn. A clip is sold
    alone. A photo is sold with up to 3 more matching photos of its shoot (one of `shoots`,
    priced at or under it) and at most one free preview: a free-lane photo of that shoot passing
    `free_ok`. The price is the highest list price among the locked items.

    `free=True` (the make_right free item): one item, price 0, the lowest matching lane; the
    caller passes the pool minus every media already sent to him. No match -> the lowest-lane
    item, its subject "anything" (the Pick never names a subject its media lacks).
    ASSUMPTION: a photo in no shoot (no `outfit_key`: e.g. a nude with nothing on) sells alone,
    no companions or preview; requiring a shoot would leave such photos unsellable. Overturned
    if the owner wants loose photos never sold.
    ASSUMPTION: companions are priced at or under the anchor, so the set's price stays on the
    chosen lane. Overturned if a set may climb above the heat target.
    ASSUMPTION: free mode on an empty pool (everything already sent) -> Refusal("all_owned"), the
    nearest reason in the spec's set (he has seen it all). Overturned by a reason of its own.
    ASSUMPTION: the free fallback ("no match -> lowest-lane unseen item", ticket 10 r3) ignores
    subject and format. Overturned if a gift must keep the asked format."""
    rng = random.Random(seed)
    if free:
        unseen = [r for r in pool if r["list_cents"] > 0 or _free_safe(r)]
        if not unseen:
            return Refusal("all_owned")
        cands = [r for r in unseen if _matches(r, ask)]
        subject = None if cands else "anything"
        cands = cands or unseen
        low = min(r["list_cents"] for r in cands)
        return _offer([_draw([r for r in cands if r["list_cents"] == low], rng)], [], ask, free=True,
                      subject=subject)

    matching = [r for r in pool if _matches(r, ask)]
    if not matching:
        return Refusal("no_match")
    cands = [r for r in matching if r["list_cents"] > 0]
    if not cands:
        return Refusal("no_priced_items")
    lanes = sorted({r["list_cents"] for r in cands})
    lane = next((c for c in lanes if c >= target_cents(ask.intensity)), lanes[0])
    anchor = _draw([r for r in cands if r["list_cents"] == lane], rng)
    if anchor["kind"] == "video":
        return _offer([anchor], [], ask, free=False)

    shoot = next((s for s in shoots if anchor["media_id"] in {i["media_id"] for i in s["items"]}), None)
    in_shoot = [i["media_id"] for i in shoot["items"]] if shoot else []
    by_id = {r["media_id"]: r for r in pool}
    mates = [r for r in cands if r["media_id"] in in_shoot and r["media_id"] != anchor["media_id"]
             and r["kind"] == "photo" and r["list_cents"] <= anchor["list_cents"]]
    mates.sort(key=lambda r: r["media_id"])
    rng.shuffle(mates)
    locked = [anchor, *mates[:3]]
    preview = next((by_id[m] for m in in_shoot if m in by_id and by_id[m]["kind"] == "photo"
                    and by_id[m]["list_cents"] == 0 and _free_safe(by_id[m])), None)
    return _offer(locked, [preview] if preview else [], ask, free=False)
