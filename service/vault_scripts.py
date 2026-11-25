from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable, Iterable

from sqlalchemy import select

import vault_ai_brief
import vault_dupes
import vault_topic_folders
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem

log = logging.getLogger("of-relay.vault_scripts")

# A script is a night's ladder: at least 10 pieces, at least 2 clips; a shoot that cannot fill it is not proposed.
MIN_SCRIPT_ITEMS = 10
MIN_SCRIPT_VIDEOS = 2



# Max over axes, not a blend (a blend re-normalises on missing axes, making items with different coverage incomparable); clothing tops out at 60, nude is mid-arc.
_CLOTHING: dict[str, int] = {
    "dressed": 0,
    "lingerie_on": 25,
    "partially_off": 40,
    "pulled_down": 50,
    "pulled_aside": 55,
    "fully_nude": 60,
}

# Gaps between rungs are intentional: the ordering of these numbers is the product decision.
_ACTS: dict[str, int] = {
    "none": 0,
    "talking_to_camera": 0,
    "posing": 5,
    "shower": 15,
    "bath": 15,
    "tease": 20,
    "strip": 30,
    "undress": 35,
    "ass_shaking": 40,
    "twerk": 40,
    "groping_own_breasts": 45,
    "spreading": 55,
    "rubbing_clit": 65,
    "fingering": 70,
    "toy_on_clit": 78,
    "toy_insertion": 85,
    "riding_toy": 88,
    "blowjob": 88,
    "handjob": 85,
    "sex_missionary": 90,
    "sex_doggy": 90,
    "sex_riding": 90,
    "masturbation_orgasm": 95,
    "squirt": 98,
    "cumshot": 98,
}

_PENETRATION: dict[str, int] = {
    "none": 0, "fingers": 70, "toy": 85, "penis": 95,
}

_EXPLICITNESS: dict[str, int] = {
    "sfw": 0, "suggestive": 25, "explicit": 55, "hardcore": 85,
}


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


# None is NOT zero: an unscoreable item must not be sorted to the front of a script as though it were the tame opener.
def escalation_score(fields: dict[str, Any]) -> int | None:
    if not isinstance(fields, dict):
        return None

    rungs: list[int] = []

    clothing = _CLOTHING.get(_norm(fields.get("clothing_state")))
    if clothing is not None:
        rungs.append(clothing)

    acts = fields.get("acts")
    # Highest act present: a clip that teases then ends in insertion belongs at the insertion end.
    act_rungs = []
    for raw_act in acts or []:
        a = _norm(raw_act)
        a = vault_topic_folders.ACT_ALIASES.get(a, a)
        if a in _ACTS:
            act_rungs.append(_ACTS[a])
    if act_rungs:
        rungs.append(max(act_rungs))

    pen = _PENETRATION.get(_norm(fields.get("penetration")))
    if pen:
        rungs.append(pen)

    explicit = _EXPLICITNESS.get(_norm(fields.get("explicitness")))
    if explicit is None:
        explicit = _EXPLICITNESS.get(_norm(fields.get("explicitness_tier")))
    if explicit is not None:
        rungs.append(explicit)

    return max(rungs) if rungs else None


async def _load_rows(account_id: str) -> list[dict[str, Any]]:
    async with get_session() as s:
        recs = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.created_at,
                   VaultItem.duration_seconds, VaultItem.ai_fields_json,
                   VaultItem.describe_status)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None))
            .order_by(VaultItem.created_at.asc(), VaultItem.media_id.asc())
        )).all()

    out: list[dict[str, Any]] = []
    for mid, kind, created, dur, fields_json, status in recs:
        # Every lane, price and copy reader below sees the least-harmful
        # reading of an item whose two passes disagree (`settled_reading`).
        fields = vault_ai_brief.settled_reading(
            vault_ai_brief.load_fields(fields_json))
        out.append({
            "media_id": int(mid), "kind": kind, "created_at": created,
            "duration_seconds": dur, "fields": fields, "describe_status": status,
            "score": escalation_score(fields),
        })
    return out




async def _dupe_groups(account_id: str) -> list[list[int]]:
    try:
        res = await vault_dupes.find_duplicates(account_id, rehash=False)
    except Exception:  # noqa: BLE001
        log.exception("dupe scan failed account=%s — planning without collapse", account_id)
        return []
    return [[int(m["media_id"]) for m in (c["original"], *c["dupes"])]
            for c in res["clusters"]]


def collapse_dupes(rows: list[dict[str, Any]], groups: list[list[int]],
                   ) -> tuple[list[dict[str, Any]], list[int]]:
    by_id = {r["media_id"]: r for r in rows}
    drop: set[int] = set()
    for group in groups:
        present = [m for m in group if m in by_id]
        if len(present) < 2:
            continue
        keeper = next((m for m in present if by_id[m].get("fields")
                       and by_id[m].get("describe_status") == "described"), present[0])
        drop.update(m for m in present if m != keeper)
    return [r for r in rows if r["media_id"] not in drop], sorted(drop)


async def _grouping_rows(account_id: str) -> tuple[list[dict[str, Any]], list[int]]:
    return collapse_dupes(await _load_rows(account_id), await _dupe_groups(account_id))



_CLOTHING_PROGRESS: dict[str, int] = {
    "dressed": 0, "lingerie_on": 1, "partially_off": 2,
    "pulled_down": 3, "pulled_aside": 4, "fully_nude": 5,
}

_UNKNOWN = 99

# Jev `outfit` is a clothing STATE (changes within a shoot), never a grouping key; stands in for a missing describe clothing_state.
_JEV_OUTFIT_PROGRESS: dict[str, int] = {
    "everyday_clothes": 0, "sheet_or_towel": 1, "swimwear": 1,
    "lingerie_or_bodysuit": 1, "topless_with_bottoms": 3, "nude": 5,
}

_REVEAL_REGIONS = (("breasts_vis", "breasts_bare"), ("vulva_vis", "crotch_bare"),
                   ("anus_vis", None))


def _jev_tag(fields: dict[str, Any], q: str) -> str:
    jev = vault_topic_folders.jev_of(fields)
    return _norm(vault_topic_folders.jev_tag(jev, q)) if jev else ""


def reveal_strength(fields: dict[str, Any]) -> int:
    jev = vault_topic_folders.jev_of(fields) or {}
    return sum(1 for flag, jkey in _REVEAL_REGIONS
               if (vault_ai_brief.is_bare(fields, flag) if vault_ai_brief.vis(fields, flag)
                   else bool(jkey and jev.get(jkey) == "y")))


def send_sort_key(fields: dict[str, Any], *, media_id: int = 0) -> tuple[int, ...]:
    sell = vault_ai_brief.sellability(fields)

    rung = sell["rung"] if sell["rung"] is not None else _UNKNOWN
    closes = 1 if sell["stands_alone"] else 0
    clothing = _CLOTHING_PROGRESS.get(_norm(fields.get("clothing_state")))
    if clothing is None:
        clothing = _JEV_OUTFIT_PROGRESS.get(_jev_tag(fields, "outfit"), _UNKNOWN)
    act = escalation_score(fields)
    return (rung, closes, clothing, act if act is not None else _UNKNOWN,
            reveal_strength(fields), media_id)


def send_order_reason(fields: dict[str, Any]) -> dict[str, Any]:
    sell = vault_ai_brief.sellability(fields)
    return {
        "tier": sell["tier"],
        "rung": sell["rung"],
        "closes": sell["stands_alone"],
        "payoff_acts": sell["payoff_acts"],
        "reveal": sell["reveal"],
        "clothing_state": sell["clothing"] or "unclear",
        "solo": sell["solo"],
        "beats": [] if vault_ai_brief.is_disputed(fields)
        else [b for b in (fields.get("beats") or []) if str(b).strip()],
        "acts": vault_ai_brief.claimed_acts(fields),
    }



# Multi-word colours FIRST — "dark blue" must win before "blue" matches inside it.
_COLOURS: tuple[str, ...] = (
    "dark blue", "light blue", "navy", "burgundy", "pink", "black", "white",
    "red", "blue", "green", "purple", "beige", "grey", "gray", "yellow",
    "orange", "brown", "silver", "gold", "cream", "lilac",
)

_MATERIALS: tuple[str, ...] = (
    "lace", "leather", "fishnet", "satin", "silk", "mesh", "denim", "velvet",
    "cotton",
)

_GARMENT_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bodysuit", ("bodysuit", "teddy", "leotard", "one-piece", "onepiece",
                  "corset", "bustier")),
    ("dress", ("dress", "gown", "robe")),
    ("swim", ("bikini", "swimsuit", "swimwear")),
    ("lingerie_set", ("bra", "bralette", "panties", "thong", "underwear",
                      "knickers", "briefs", "lingerie")),
    ("top", ("top", "shirt", "blouse", "crop", "tank", "halter", "sweater")),
    ("bottoms", ("skirt", "shorts", "pants", "jeans", "leggings", "bottoms")),
    ("outerwear", ("jacket", "coat", "hoodie", "cardigan")),
    ("hosiery", ("stockings", "fishnet", "tights", "socks")),
)

_GARMENT_CLASS_NAMES = frozenset(name for name, _ in _GARMENT_CLASSES)

# 48 h keeps a shoot's stills and clips uploaded on consecutive nights together while splitting a same-colour set shot a week later.
DEFAULT_OUTFIT_WINDOW_HOURS = 48

DEFAULT_KEEP_SCRIPTS = 10


def short_outfit(outfit: str) -> str:
    return str(outfit).replace("_set", "").replace("_", " ").strip()


def _clothing_text(fields: dict[str, Any]) -> str:
    return " ".join(str(x).lower() for x in (fields.get("clothing_items") or []))


def outfit_colour(fields: dict[str, Any]) -> str:
    if not isinstance(fields, dict):
        return ""
    text = _clothing_text(fields)
    if not text.strip():
        return ""
    for colour in _COLOURS:
        if re.search(rf"\b{re.escape(colour)}\b", text):
            return colour
    for material in _MATERIALS:
        if material in text:
            return material
    return ""


def garment_class(fields: dict[str, Any]) -> str:
    if not isinstance(fields, dict):
        return ""
    text = _clothing_text(fields)
    for name, words in _GARMENT_CLASSES:
        if any(w in text for w in words):
            return name
    return ""


_NO_SETTING = frozenset({"", "other", "unclear", "unknown", "none"})


def outfit_key(fields: dict[str, Any]) -> str:
    if not isinstance(fields, dict):
        return ""
    colour = outfit_colour(fields)
    kind = garment_class(fields)
    if colour:
        return f"{colour} {kind}".strip()
    setting = _norm(fields.get("setting"))
    if kind and setting not in _NO_SETTING:
        return f"{kind} {setting}"
    return ""


def _with_why(r: dict[str, Any]) -> dict[str, Any]:
    return {**r, "why": send_order_reason(r.get("fields") or {})}


_SUGGESTIVE = vault_ai_brief.EXPLICITNESS_LADDER.index("suggestive")
_EXPLICIT = vault_ai_brief.EXPLICITNESS_LADDER.index("explicit")


# Explicit/hardcore in a script needs her pussy on show or a real act in frame (live AE: 114 of 160 'explicit' items were a covered crotch).
def earns_paid_rung(fields: dict[str, Any]) -> bool:
    if vault_ai_brief.vis(fields, "vulva_vis"):
        bare = vault_ai_brief.is_bare(fields, "vulva_vis")
    else:
        bare = (vault_topic_folders.jev_of(fields) or {}).get("crotch_bare") == "y"
    return (bare or vault_ai_brief.genital_act_claimed(fields)
            or vault_ai_brief.sellability(fields)["stands_alone"])


def _with_script_why(r: dict[str, Any]) -> dict[str, Any]:
    out = _with_why(r)
    why = out["why"]
    if why["rung"] is not None and why["rung"] >= _EXPLICIT \
            and not earns_paid_rung(r.get("fields") or {}):
        out["why"] = {**why, "rung": _SUGGESTIVE, "tier": "suggestive",
                      "labelled": why["tier"]}
    return out


def _script_sort_key(r: dict[str, Any]) -> tuple[int, ...]:
    return (r["why"]["rung"], *send_sort_key(r["fields"], media_id=r["media_id"])[1:])


def _ordered_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "manual_order": i + 1} for i, r in enumerate(rows)]


def _tally(items: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int], int]:
    kinds: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for r in items:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        tiers[r["why"]["tier"]] = tiers.get(r["why"]["tier"], 0) + 1
    return kinds, tiers, sum(1 for r in items if r["why"]["closes"])


# A script is what an operator walks ONE fan through in a night, not the whole shoot (one held 93 items): per-band caps.
SCRIPT_OPENERS = 3
SCRIPT_MIDDLE = 4
SCRIPT_CLOSERS = 3
SCRIPT_SIZE = SCRIPT_OPENERS + SCRIPT_MIDDLE + SCRIPT_CLOSERS

# Looser than the Duplicates screen's re-upload match (2); only applied inside one rung of one script.
NEAR_DUPE_THRESHOLD = 5


def item_room(fields: dict[str, Any]) -> str:
    room = _jev_tag(fields, "setting") or _norm(fields.get("setting"))
    return "" if room in _NO_SETTING else room


def split_by_room(items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    roomed: dict[str, list[dict[str, Any]]] = {}
    for r in items:
        room = item_room(r.get("fields") or {})
        if room:
            roomed.setdefault(room, []).append(r)
    if not roomed:
        return [("", list(items))]
    sizes = {room: len(rs) for room, rs in roomed.items()}

    def _gap(a: dict[str, Any], b: dict[str, Any]) -> float:
        if a["created_at"] is None or b["created_at"] is None:
            return 0.0
        return abs((a["created_at"] - b["created_at"]).total_seconds())

    home: dict[int, str] = {}
    for r in items:
        room = item_room(r.get("fields") or {})
        if not room:
            room = min(roomed, key=lambda k: (min(_gap(r, x) for x in roomed[k]), -sizes[k], k))
        home[r["media_id"]] = room
    return [(room, [r for r in items if home[r["media_id"]] == room]) for room in sorted(roomed)]


async def _fingerprints(account_id: str) -> dict[int, dict[str, Any]]:
    try:
        items, _ = await vault_dupes.load_fingerprints(account_id)
    except Exception:  # noqa: BLE001
        log.exception("fingerprint load failed account=%s — no near-dupe collapse", account_id)
        return {}
    return {int(fp["media_id"]): fp for fp in items}


def collapse_near_dupes(items: list[dict[str, Any]], prints: dict[int, dict[str, Any]],
                        threshold: int = NEAR_DUPE_THRESHOLD,
                        ) -> tuple[list[dict[str, Any]], list[int]]:
    order = sorted(range(len(items)), key=lambda i: (
        vault_topic_folders.jev_of(items[i].get("fields")) is None, i))
    kept: list[int] = []
    dropped: list[int] = []
    for i in order:
        r = items[i]
        fp = prints.get(r["media_id"])
        if fp is not None and any(
                items[j]["why"]["rung"] == r["why"]["rung"]
                and vault_dupes.near(fp, prints.get(items[j]["media_id"]), threshold) for j in kept):
            dropped.append(r["media_id"])
            continue
        kept.append(i)
    return [items[i] for i in sorted(kept)], sorted(dropped)


def ladder_bands(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    closers = [r for r in items if r["why"]["closes"]]
    rest = [r for r in items if not r["why"]["closes"]]
    low = min((r["why"]["rung"] for r in rest), default=None)
    return {"opener": [r for r in rest if r["why"]["rung"] == low],
            "middle": [r for r in rest if r["why"]["rung"] != low],
            "closer": closers}


def _traits(r: dict[str, Any], *, kind: bool = True) -> set[tuple[str, Any]]:
    why = r["why"]
    out = {("rung", why["rung"]), ("clothing", why["clothing_state"]),
           ("acts", tuple(why["payoff_acts"]))}
    if kind:
        out.add(("kind", r["kind"]))
    return out


def _pick_varied(pool: list[dict[str, Any]], k: int, *, kind: bool = True) -> list[dict[str, Any]]:
    pool = list(pool)
    chosen: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    while pool and len(chosen) < k:
        i = min(range(len(pool)), key=lambda i: (len(_traits(pool[i], kind=kind) & seen), i))
        r = pool.pop(i)
        chosen.append(r)
        seen |= _traits(r, kind=kind)
    return chosen


def cap_ladder(items: list[dict[str, Any]], *, min_videos: int | None = None
               ) -> tuple[list[dict[str, Any]], list[int]]:
    bands = ladder_bands(items)
    pos = {r["media_id"]: i for i, r in enumerate(items)}
    closers = sorted(bands["closer"], key=lambda r: (
        r["kind"] != "video", -(r.get("score") or 0), pos[r["media_id"]]))
    keep = {r["media_id"] for r in (
        _pick_varied(bands["opener"], SCRIPT_OPENERS)
        + _pick_varied(bands["middle"], SCRIPT_MIDDLE)
        + _pick_varied(closers, SCRIPT_CLOSERS, kind=False))}
    left = [r for r in items if r["media_id"] not in keep]
    keep |= {r["media_id"] for r in _pick_varied(left, SCRIPT_SIZE - len(keep))}
    band_of = {r["media_id"]: b for b, rs in bands.items() for r in rs}
    want = MIN_SCRIPT_VIDEOS if min_videos is None else min_videos
    while sum(1 for r in items if r["media_id"] in keep and r["kind"] == "video") < want:
        swap = next(((v, p) for v in items if v["kind"] == "video" and v["media_id"] not in keep
                     for p in reversed(items) if p["kind"] == "photo" and p["media_id"] in keep
                     and band_of[p["media_id"]] == band_of[v["media_id"]]), None)
        if swap is None:
            swap = next(((v, p) for v in items if v["kind"] == "video" and v["media_id"] not in keep
                         for p in reversed(items) if p["kind"] == "photo" and p["media_id"] in keep
                         and not p["why"]["closes"]), None)
        if swap is None:
            break
        keep.discard(swap[1]["media_id"])
        keep.add(swap[0]["media_id"])
    return ([r for r in items if r["media_id"] in keep],
            [r["media_id"] for r in items if r["media_id"] not in keep])


def _band_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return {k: len(v) for k, v in ladder_bands(items).items()}


_RUNG_WORDS = ("sfw", "suggestive", "explicit", "hardcore")


def _rung_word(r: int) -> str:
    return _RUNG_WORDS[r] if 0 <= r < len(_RUNG_WORDS) else f"rung {r}"


def _rungs_label(rungs: list[int]) -> str:
    if len(rungs) > 1 and rungs[-1] - rungs[0] + 1 == len(rungs):
        return f"{_rung_word(rungs[0])} → {_rung_word(rungs[-1])}"
    return ", ".join(_rung_word(r) for r in rungs)


def _ladder_full(rungs: list[int]) -> bool:
    return len(rungs) >= 3 and rungs[-1] - rungs[0] + 1 == len(rungs)


def script_health(s: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if s.get("borrowed"):
        out.append("borrowed closer")
    elif not s["closes_on_own"]:
        out.append("no closer")
    kinds = s["kinds"]
    if set(kinds) == {"photo"}:
        out.append("photos only")
    elif set(kinds) == {"video"}:
        out.append("clips only")
    if not _ladder_full(s["rungs"]):
        out.append(_rungs_label(s["rungs"]))
    if s.get("capped_from"):
        out.append(f"capped from {s['capped_from']}")
    if s.get("near_dupes"):
        n = len(s["near_dupes"])
        out.append(f"{n} near-duplicate{'s' if n != 1 else ''} dropped")
    if s.get("unplaced"):
        out.append(f"{s['unplaced']} unrated at end")
    return out


def script_name(outfit: str, room: str, started: datetime | None) -> str:
    shown_room = room.replace("_", " ")
    head = outfit.split(" ", 1)[0]
    label = short_outfit(head if head in _GARMENT_CLASS_NAMES else outfit)
    date = f"{started:%b} {started.day}" if started else ""
    return ai_folder_name(" · ".join(p for p in (label, shown_room, date) if p))


def _shoot(outfit: str, room: str, part: list[dict[str, Any]], prints: dict[int, dict[str, Any]],
           *, min_items: int, require_escalation: bool,
           min_videos: int) -> dict[str, Any] | None:
    placed = sorted((r for r in part if r["why"]["rung"] is not None), key=_script_sort_key)
    unplaced = sorted((r for r in part if r["why"]["rung"] is None),
                      key=lambda r: r["media_id"])
    deduped, near = collapse_near_dupes(placed, prints)
    if len(deduped) < min_items:
        return None
    if require_escalation and len({r["why"]["rung"] for r in deduped}) < 2:
        return None
    ladder, overflow = cap_ladder(deduped, min_videos=min_videos)
    if len(ladder) < min_items or sum(1 for r in ladder if r["kind"] == "video") < min_videos:
        return None
    dated = [r["created_at"] for r in part if r["created_at"]]
    started = min(dated) if dated else None
    kinds, tiers, closes = _tally(ladder + unplaced)
    shoot = {
        "outfit": outfit, "room": room,
        "colour": outfit_colour(part[0].get("fields") or {}),
        "name": script_name(outfit, room, started),
        "size": len(ladder), "kinds": kinds, "tiers": tiers,
        "rungs": sorted({r["why"]["rung"] for r in ladder}),
        "bands": _band_counts(ladder),
        "mixed": len(kinds) > 1,
        "closes_on_own": closes,
        "started_at": started,
        "ended_at": max(dated) if dated else None,
        "capped_from": len(deduped) if overflow else None,
        "overflow": overflow, "near_dupes": near,
        "borrowed": None, "unplaced": len(unplaced),
        "items": _ordered_items(ladder + unplaced),
    }
    shoot["health"] = script_health(shoot)
    return shoot


async def collect_outfit_scripts(
    account_id: str, *, window_hours: int = DEFAULT_OUTFIT_WINDOW_HOURS,
    min_items: int | None = None, require_escalation: bool = True,
    min_videos: int | None = None,
    rows: list[dict[str, Any]] | None = None,
    prints: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    min_items = MIN_SCRIPT_ITEMS if min_items is None else min_items
    min_videos = MIN_SCRIPT_VIDEOS if min_videos is None else min_videos
    if rows is None:
        rows, _ = await _grouping_rows(account_id)
    if prints is None:
        prints = await _fingerprints(account_id)
    window = window_hours * 3600

    by_outfit: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = outfit_key(r.get("fields") or {})
        if key:
            by_outfit.setdefault(key, []).append(r)

    out: list[dict[str, Any]] = []
    for outfit, items in by_outfit.items():
        items.sort(key=lambda r: (r["created_at"] or datetime.min, r["media_id"]))
        segments: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = [items[0]]
        for prev, item in zip(items, items[1:]):
            gap = ((item["created_at"] - prev["created_at"]).total_seconds()
                   if item["created_at"] and prev["created_at"] else 0)
            if gap > window:
                segments.append(current)
                current = []
            current.append(item)
        segments.append(current)

        for seg in segments:
            enriched = [r for r in map(_with_script_why, seg) if not _unpriced_dispute(r)]
            kw = dict(min_items=min_items, require_escalation=require_escalation,
                      min_videos=min_videos)
            parts = [s for room, part in split_by_room(enriched)
                     if (s := _shoot(outfit, room, part, prints, **kw)) is not None]
            if not parts and (whole := _shoot(outfit, "", enriched, prints, **kw)):
                parts = [whole]
            out.extend(parts)

    out.sort(key=shoot_rank_key)
    return out


_PAID_DEPTH_CAP = 10


def ladder_completeness(s: dict[str, Any]) -> tuple[int, int]:
    bands = s.get("bands") or {}
    present = sum(1 for b in ("opener", "middle", "closer") if bands.get(b))
    rungs = sorted(s["rungs"])
    skipped = (rungs[-1] - rungs[0] + 1 - len(rungs)) if rungs else 0
    return present, len(rungs) - skipped


def shoot_rank_key(s: dict[str, Any]) -> tuple:
    tiers = s.get("tiers") or {}
    paid = min(_PAID_DEPTH_CAP, tiers.get("explicit", 0) + tiers.get("hardcore", 0))
    bands, rungs = ladder_completeness(s)
    return (s["closes_on_own"] == 0, -bands, -rungs, -paid, not s["mixed"], -s["size"])


def _span_gap(r: dict[str, Any], s: dict[str, Any]) -> float:
    at, lo, hi = r["created_at"], s["started_at"], s["ended_at"]
    if at is None or lo is None or hi is None:
        return float("inf")
    if lo <= at <= hi:
        return 0.0
    return min(abs((at - lo).total_seconds()), abs((at - hi).total_seconds()))


def borrow_closers(kept: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    taken = {r["media_id"] for s in kept for r in s["items"]}
    taken |= {int(m) for s in kept for m in s.get("near_dupes") or []}
    pool = [r for r in map(_with_script_why, rows)
            if r["why"]["closes"] and r["why"]["rung"] is not None
            and not _unpriced_dispute(r) and r["media_id"] not in taken]
    for s in kept:
        if s["closes_on_own"] or not s["items"]:
            continue
        top = max(s["rungs"])

        def _match(r: dict[str, Any]) -> int | None:
            fields = r.get("fields") or {}
            if s["colour"] and outfit_colour(fields) == s["colour"]:
                return 0
            if s["room"] and item_room(fields) == s["room"]:
                return 1
            return None

        cands = [(m, r) for r in pool if r["media_id"] not in taken
                 and r["why"]["rung"] >= top and (m := _match(r)) is not None]
        if not cands:
            continue
        _, pick = min(cands, key=lambda c: (c[0], c[1]["kind"] != "video",
                                            _span_gap(c[1], s), c[1]["media_id"]))
        taken.add(pick["media_id"])
        ladder = [r for r in s["items"] if r["why"]["rung"] is not None]
        tail = [r for r in s["items"] if r["why"]["rung"] is None]
        ladder.append({**pick, "borrowed": True})
        if len(ladder) > SCRIPT_SIZE:
            ladder, cut = cap_ladder(ladder)
            s["overflow"] = [*(s.get("overflow") or []), *cut]
        items = ladder + tail
        kinds, tiers, closes = _tally(items)
        s.update(items=_ordered_items(items), size=len(ladder), kinds=kinds, tiers=tiers,
                 closes_on_own=closes, mixed=len(kinds) > 1,
                 rungs=sorted({r["why"]["rung"] for r in ladder}),
                 bands=_band_counts(ladder), borrowed=pick["media_id"])
        s["health"] = script_health(s)


# Reuse and retire key on created_by (AI_FOLDER_CREATOR), so an operator's folder is never reached even if named AI-...
AI_FOLDER_PREFIX = "AI-"
AI_FOLDER_CREATOR = "vault_ai_script"
_FOLDER_NAME_MAX = 120


def ai_folder_name(name: str) -> str:
    clean = str(name).strip()
    if clean.startswith(AI_FOLDER_PREFIX):
        return clean[:_FOLDER_NAME_MAX]
    return f"{AI_FOLDER_PREFIX}{clean}"[:_FOLDER_NAME_MAX]


def _unique_name(name: str, used: set[str]) -> str:
    out, n = name, 1
    while out in used:
        n += 1
        tail = f" {n}"
        out = f"{name[:_FOLDER_NAME_MAX - len(tail)]}{tail}"
    return out


_PAID_TIERS = ("explicit", "hardcore")


def _focus(fields: dict) -> set[str]:
    return {_norm(x) for x in (fields.get("body_focus") or []) if _norm(x)}


def _shows_genitals(fields: dict) -> bool:
    return (vault_ai_brief.is_bare(fields, "vulva_vis")
            or vault_ai_brief.is_bare(fields, "anus_vis"))


def _shows_breasts_bare(fields: dict) -> bool:
    return vault_ai_brief.is_bare(fields, "breasts_vis")


# Flags beat the clothing_state enum (wrong on ~1 in 3 of the items the $50 tier is built from); a NAMED garment settles it before underwear_visible, which only asks about underwear.
def _is_nude(fields: dict) -> bool:
    if vault_ai_brief.wearing_something(fields):
        return False
    seen = fields.get("underwear_visible")
    if isinstance(seen, bool):
        return not seen
    return _norm(fields.get("clothing_state")) == "fully_nude"



_PARTNER_ACTS = frozenset({
    "blowjob", "handjob", "sex_missionary", "sex_doggy", "sex_riding", "cumshot",
})
_PARTNER_FOLDERS = frozenset({"blowjob", "sex_with_partner"})


# bool is an int in Python and `people_count: true` is not a count.
def _people_count(fields: dict) -> int | None:
    count = fields.get("people_count")
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def solo_known(fields: dict) -> bool:
    return (isinstance(fields.get("partner_visible"), bool)
            or _people_count(fields) is not None)


# Disjunction on purpose: the model often returns people_count 1 even after describing a partner act (it counts who the clip is ABOUT).
def _partner_evidence(fields: dict) -> bool:
    count = _people_count(fields)
    if fields.get("partner_visible") is True:
        return True
    if count is not None and count > 1:
        return True
    if {_norm(a) for a in (fields.get("acts") or [])} & _PARTNER_ACTS:
        return True
    if _norm(fields.get("primary_folder")) in _PARTNER_FOLDERS:
        return True
    jev = vault_topic_folders.jev_of(fields)
    if jev and vault_topic_folders.jev_tag(jev, "people_count") == "two_or_more":
        return True
    return _norm(fields.get("penetration")) == "penis"


# Errs toward NOT solo: a partner clip in a solo folder is the wrong thing sold under the wrong promise (has cost an unsubscribe).
def is_solo(fields: dict) -> bool:
    return solo_known(fields) and not _partner_evidence(fields)


def _has_payoff_act(fields: dict) -> bool:
    acts = {_norm(a) for a in (fields.get("acts") or []) if _norm(a)}
    if acts & vault_ai_brief._PAYOFF_ACTS:
        return True
    pen = _norm(fields.get("penetration"))
    return bool(pen) and pen not in ("none", "unclear")


def _lane_stories(why: dict, fields: dict, kind: str) -> bool:
    return (why["tier"] in ("sfw", "suggestive")
            and not vault_ai_brief.is_disputed(fields))


def _lane_mass(why: dict, fields: dict, kind: str) -> bool:
    return (why["tier"] == "suggestive"
            and not vault_ai_brief.is_disputed(fields))


# Requires the flags: this lane asserts safe-for-everyone and an unflagged item passes every 'no evidence of exposure' test vacuously.
def _lane_covered_explicit(why: dict, fields: dict, kind: str) -> bool:
    if not vault_ai_brief.flags_known(fields):
        return False
    if vault_ai_brief.is_disputed(fields):
        return False          # a free lane never takes a disputed item
    if _has_payoff_act(fields):
        return False
    if why["tier"] not in _PAID_TIERS:
        return False
    if vault_ai_brief.any_bare(fields):
        return False
    return _decently_covered(fields)


# Under-includes on purpose: 'covered' lumps a hand or sheet with fabric, so each region must be out of shot or behind NAMED clothing; a topless mass send is the worse mistake.
def _decently_covered(fields: dict) -> bool:
    for region in ("vulva_vis", "breasts_vis"):
        state = vault_ai_brief.vis(fields, region)
        if state == "not_in_frame":
            continue
        if state != "covered":
            return False
        if not vault_ai_brief.is_clothing(vault_ai_brief.garment_over(fields, region)):
            return False
    return True


# Unflagged stills are left out, never guessed (clothing_state is wrong on ~1 in 3); they join on a rebuild once flagged.
def _flag_lane_ok(why: dict, fields: dict, kind: str) -> bool:
    return (kind == "photo" and why["tier"] in _PAID_TIERS
            and vault_ai_brief.flags_known(fields))


# The two price tiers must not overlap: an item cannot carry two prices.
def _lane_tease_10(why: dict, fields: dict, kind: str) -> bool:
    if not _flag_lane_ok(why, fields, kind):
        return False
    if _is_nude(fields):
        return False
    if _lane_tease_50(why, fields, kind):
        return False
    return _shows_breasts_bare(fields) and not _shows_genitals(fields)


def _lane_tease_50(why: dict, fields: dict, kind: str) -> bool:
    if not _flag_lane_ok(why, fields, kind):
        return False
    if vault_ai_brief.vis(fields, "vulva_vis") == "covered":
        return False
    # lingerie_on + nude is usually a mislabel (panties pulled aside); trusting it would price a partial reveal at $50.
    if _norm(fields.get("clothing_state")) == "lingerie_on" and not _is_nude(fields):
        return False
    if not vault_ai_brief.any_bare(fields):
        return False
    return (_shows_genitals(fields)
            or "full_body" in _focus(fields)
            or _is_nude(fields))


def _lane_clips(why: dict, fields: dict, kind: str) -> bool:
    return kind == "video" and why["tier"] in _PAID_TIERS


def _unpriced_dispute(row: dict[str, Any]) -> bool:
    return (row["why"]["tier"] not in _PAID_TIERS
            and vault_ai_brief.is_disputed(row.get("fields") or {}))


def shelf_price(fields: dict, kind: str) -> int:
    fields = vault_ai_brief.settled_reading(fields) or {}
    why = send_order_reason(fields)
    if _lane_tease_50(why, fields, kind):
        return 50
    return 10 if _lane_tease_10(why, fields, kind) else 0


PURPOSE_LANES: tuple[tuple[str, str, str, Callable[[dict, dict, str], bool]], ...] = (
    ("stories", "stories",
     "sfw → suggestive — safe enough to post publicly", _lane_stories),
    ("mass", "mass",
     "suggestive only — mass messages and media", _lane_mass),
    ("covered_explicit", "safe explicit",
     "reads explicit, but nothing bare — each region out of shot or under "
     "named clothing, so it is safe to mass", _lane_covered_explicit),
    ("tease_10", "tease 10",
     "images — boobs out, pussy not on show, never fully nude (that is the $50)",
     _lane_tease_10),
    ("tease_50", "tease 50",
     "images — fully nude or pussy visible, never with lingerie still on",
     _lane_tease_50),
    ("clips", "clips",
     "explicit clips — the pool a 1:1 PPV is picked from", _lane_clips),
)

# Paid-tier items no other lane took (e.g. a fully covered explicit still) land here instead of being dropped.
_RESIDUAL_LANE = ("explicit_rest", "explicit 1:1",
                  "explicit, but not mass-safe and not a clean $10/$50 reveal — "
                  "sell these in conversation")


async def collect_purpose_folders(
    account_id: str, *, media_ids: Iterable[int] | None = None,
    solo: bool = False, unlaned: list[int] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if rows is None:
        rows, _ = await _grouping_rows(account_id)
    if media_ids is not None:
        wanted = {int(m) for m in media_ids}
        rows = [r for r in rows if r["media_id"] in wanted]

    enriched = [_with_why(r) for r in rows]

    def _folder(slug: str, name: str, purpose: str, picked: list[dict[str, Any]],
                *, solo_of: int | None = None) -> dict[str, Any]:
        picked.sort(key=lambda r: send_sort_key(r["fields"], media_id=r["media_id"]))
        kinds, tiers, closes = _tally(picked)
        return {
            "lane": slug, "name": ai_folder_name(name), "purpose": purpose,
            "size": len(picked), "kinds": kinds, "tiers": tiers,
            "closes_on_own": closes,
            "solo": solo_of is not None, "solo_of": solo_of,
            "items": _ordered_items(picked),
        }

    # Cut from the FINISHED lane so a solo folder is a subset of the lane it is named after.
    def _solo_cut(lane: dict[str, Any]) -> dict[str, Any] | None:
        picked = [r for r in lane["items"] if is_solo(r.get("fields") or {})]
        if not picked:
            return None
        return _folder(f"{lane['lane']}_solo", f"{lane['name']}-solo",
                       f"{lane['purpose']} — her alone, nobody else in frame",
                       picked, solo_of=lane["size"])

    out: list[dict[str, Any]] = []
    claimed: set[int] = set()
    for slug, name, purpose, matches in PURPOSE_LANES:
        picked = [r for r in enriched
                  if matches(r["why"], r.get("fields") or {}, r["kind"])]
        if not picked:
            continue
        claimed.update(r["media_id"] for r in picked)
        out.append(_folder(slug, name, purpose, picked))

    rest = [r for r in enriched
            if r["media_id"] not in claimed and r["why"]["tier"] in _PAID_TIERS]
    if rest:
        out.append(_folder(*_RESIDUAL_LANE, rest))
    if unlaned is not None:
        unlaned.extend(sorted(r["media_id"] for r in enriched
                              if r["media_id"] not in claimed and _unpriced_dispute(r)))

    if solo:
        cuts = [c for c in map(_solo_cut, out) if c is not None]
        out.extend(cuts)
    return out


def collect_topic_folders(rows: list[dict[str, Any]], topics: Iterable[str], *,
                          split: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for (slug, price), picked in vault_topic_folders.assign(rows, topics, by_price=split).items():
        topic = vault_topic_folders.BY_SLUG[slug]
        picked = sorted((_with_why(r) for r in picked),
                        key=lambda r: send_sort_key(r["fields"], media_id=r["media_id"]))
        kinds, tiers, closes = _tally(picked)
        out.append({
            "topic": slug, "price": price,
            "name": ai_folder_name(vault_topic_folders.folder_name(topic, price)),
            "purpose": topic.description if price is None else f"{topic.description} — {price}",
            "kinds": kinds, "tiers": tiers, "closes_on_own": closes,
            "items": _ordered_items(picked),
        })
    return out



async def flags_coverage(account_id: str) -> dict[str, Any]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.ai_fields_json).where(
                VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                VaultItem.kind == "photo")
        )).all()
    stills = len(rows)
    flagged = 0
    for (fj,) in rows:
        fields = vault_ai_brief.load_fields(fj)
        if vault_ai_brief.flags_known(fields):
            flagged += 1
    return {
        "stills": stills, "flagged": flagged,
        "missing": stills - flagged,
        "ready": stills > 0 and flagged == stills,
    }


async def solo_coverage(account_id: str) -> dict[str, Any]:
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.ai_fields_json).where(
                VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                VaultItem.describe_status == "described")
        )).all()
    known = solo = 0
    for (fj,) in rows:
        fields = vault_ai_brief.load_fields(fj)
        if not solo_known(fields):
            continue
        known += 1
        if is_solo(fields):
            solo += 1
    described = len(rows)
    return {"described": described, "known": known,
            "unknown": described - known, "solo": solo,
            "ready": described > 0 and known == described}


async def plan_ai_folders(
    account_id: str, *, keep: int = DEFAULT_KEEP_SCRIPTS,
    window_hours: int = DEFAULT_OUTFIT_WINDOW_HOURS,
    min_items: int | None = None,
    solo: bool = False,
    topics: Iterable[str] = (),
    split: bool = True,
) -> dict[str, Any]:
    topics = vault_topic_folders.parse_topics(topics)
    rows, dupes_dropped = await _grouping_rows(account_id)
    shoots = await collect_outfit_scripts(
        account_id, window_hours=window_hours, min_items=min_items, rows=rows,
        prints=await _fingerprints(account_id))
    settled_unlaned: list[int] = []
    lanes = await collect_purpose_folders(account_id, solo=solo, unlaned=settled_unlaned,
                                          rows=rows)

    def _folder(group: dict[str, Any], source: str, purpose: str,
                **extra: Any) -> dict[str, Any]:
        items = group["items"]
        return {
            "name": group["name"], "source": source, "purpose": purpose,
            "size": len(items), "kinds": group["kinds"], "tiers": group["tiers"],
            "closes_on_own": group["closes_on_own"],
            "solo": False, "solo_of": None,
            "items": [
                {"media_id": r["media_id"], "kind": r["kind"],
                 "manual_order": r["manual_order"], "score": r.get("score"),
                 "tier": r["why"]["tier"], "closes": r["why"]["closes"],
                 "clothing_state": r["why"]["clothing_state"],
                 **({"borrowed": True} if r.get("borrowed") else {})}
                for r in items
            ],
            **extra,
        }

    kept = shoots[:max(0, keep)]
    borrow_closers(kept, rows)
    folders = [
        _folder(s, "script", f"one shoot — {s['outfit']}",
                outfit=s["outfit"], mixed=s["mixed"], room=s["room"], health=s["health"])
        for s in kept
    ] + [
        _folder(f, "lane", f["purpose"], lane=f["lane"],
                solo=f["solo"], solo_of=f["solo_of"])
        for f in lanes
    ] + [
        _folder(f, "topic", f["purpose"], topic=f["topic"], price=f["price"])
        for f in collect_topic_folders(rows, topics, split=split)
    ]

    by_start = sorted(range(len(kept)), key=lambda i: (
        kept[i]["started_at"] or datetime.min, kept[i]["items"][0]["media_id"]))
    used: set[str] = set()
    for i in [*by_start, *range(len(kept), len(folders))]:
        folders[i]["name"] = _unique_name(folders[i]["name"], used)
        used.add(folders[i]["name"])

    unique = {r["media_id"] for f in folders for r in f["items"]}

    async with get_session() as s:
        owned = await _owned_ai_folders(s, account_id)
        reuse, stale = _assign_folders([ai_folder_name(f["name"]) for f in folders], owned)
        for f, existing in zip(folders, reuse):
            f["change"] = "new" if existing is None else "keep"
        retired = [{"folder_id": f.id, "name": f.name, "of_list_id": f.of_list_id}
                   for f in stale]
    changes = {
        "create": sum(1 for f in folders if f["change"] == "new"),
        "keep": sum(1 for f in folders if f["change"] == "keep"),
        "retire": len(retired),
        "retire_on_of": sum(1 for r in retired if r["of_list_id"] is not None),
        "retired": retired,
    }

    coverage = await flags_coverage(account_id)
    solo_cov = await solo_coverage(account_id) if solo else None
    jev = vault_topic_folders.coverage(rows)

    return {
        "account_id": account_id,
        "keep": keep,
        "solo": solo,
        "topics": topics,
        "split": split,
        "shoots_found": len(shoots),
        "flags": coverage,
        "solo_coverage": solo_cov,
        "jev": jev,
        "topic_catalogue": vault_topic_folders.catalogue(rows),
        "folders": folders,
        "changes": changes,
        "settled_unlaned": settled_unlaned,
        "dupes_collapsed": dupes_dropped,
        "summary": {
            "folders": len(folders),
            "scripts": sum(1 for f in folders if f["source"] == "script"),
            "lanes": sum(1 for f in folders
                         if f["source"] == "lane" and not f["solo"]),
            "solo_cuts": sum(1 for f in folders if f["solo"]),
            "topics": sum(1 for f in folders if f["source"] == "topic"),
            "unique_media": len(unique),
            "memberships": sum(f["size"] for f in folders),
            "settled_unlaned": len(settled_unlaned),
            "dupes_collapsed": len(dupes_dropped),
        },
    }


async def _owned_ai_folders(s, account_id: str) -> tuple[dict[str, list[VaultFolder]], dict[str, VaultFolder]]:
    live: dict[str, list[VaultFolder]] = {}
    retired: dict[str, VaultFolder] = {}
    for folder in (await s.execute(
        select(VaultFolder).where(
            VaultFolder.account_id == account_id,
            VaultFolder.created_by == AI_FOLDER_CREATOR,
        ).order_by(VaultFolder.id)
    )).scalars().all():
        if folder.deleted_at is None:
            live.setdefault(folder.name, []).append(folder)
        else:
            retired[folder.name] = folder
    return live, retired


def _assign_folders(names: list[str], owned: tuple[dict[str, list[VaultFolder]], dict[str, VaultFolder]],
                    ) -> tuple[list[VaultFolder | None], list[VaultFolder]]:
    live, retired = owned
    left = {name: list(rows) for name, rows in live.items()}
    reuse = [left[n].pop(0) if left.get(n) else retired.get(n) for n in names]
    stale = sorted((f for rows in left.values() for f in rows
                    if f.name.startswith(AI_FOLDER_PREFIX)), key=lambda f: f.id)
    return reuse, stale


# Its write holds the DB write lock to commit, so no operator adopt lands between the ownership re-check and the membership rewrite.
async def _set_deleted_if_ai(s, folder_id: int, deleted_at: datetime | None) -> bool:
    return (await s.execute(VaultFolder.__table__.update().where(
        (VaultFolder.id == folder_id) & (VaultFolder.created_by == AI_FOLDER_CREATOR)
    ).values(deleted_at=deleted_at))).rowcount == 1


# Re-derives the plan server-side, never trusts a posted media-id list: the previewed one may be minutes old.
async def apply_ai_folders(account_id: str, plan: dict[str, Any], *,
                           expected_retire: set[int] | None = None) -> dict[str, Any]:
    created: list[dict[str, Any]] = []
    adopted: list[dict[str, Any]] = []
    specs = plan.get("folders") or []
    async with get_session() as s:
        # Each spec takes at most one live generated folder of its name;
        # whatever is left over is stale (`_assign_folders`, as the preview).
        names = [ai_folder_name(spec["name"]) for spec in specs]
        reuse, stale = _assign_folders(names, await _owned_ai_folders(s, account_id))

        for spec, name, existing in zip(specs, names, reuse):
            if existing is not None:
                if not await _set_deleted_if_ai(s, existing.id, None):
                    adopted.append({"folder_id": existing.id, "name": existing.name,
                                    "of_list_id": existing.of_list_id})
                    continue
                folder_id = existing.id
                reused = True
                await s.execute(
                    VaultFolderItem.__table__.delete().where(
                        (VaultFolderItem.account_id == account_id)
                        & (VaultFolderItem.folder_id == folder_id)
                    )
                )
            else:
                folder = VaultFolder(account_id=account_id, name=name,
                                     created_by=AI_FOLDER_CREATOR)
                s.add(folder)
                await s.flush()
                folder_id = folder.id
                reused = False

            for entry in spec.get("items") or []:
                s.add(VaultFolderItem(
                    account_id=account_id, folder_id=folder_id,
                    media_id=int(entry["media_id"]),
                    manual_order=int(entry["manual_order"]),
                ))
            created.append({"folder_id": folder_id, "name": name,
                            "items": len(spec.get("items") or []),
                            "reused": reused, "source": spec.get("source")})

        retired: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for folder in stale:
            entry = {"folder_id": folder.id, "name": folder.name, "of_list_id": folder.of_list_id}
            if expected_retire is not None and folder.id not in expected_retire:
                skipped.append(entry)
                continue
            if not await _set_deleted_if_ai(s, folder.id, datetime.utcnow()):
                adopted.append(entry)
                continue
            retired.append(entry)
        await s.commit()

    log.info("AI folders applied account=%s folders=%d items=%d retired=%d",
             account_id, len(created), sum(c["items"] for c in created), len(retired))
    return {
        "created": created,
        "folders": len(created),
        "new": sum(1 for c in created if not c["reused"]),
        "reused": sum(1 for c in created if c["reused"]),
        "items": sum(c["items"] for c in created),
        "retired": retired,
        "skipped_retire": skipped,
        "skipped_adopted": adopted,
    }
