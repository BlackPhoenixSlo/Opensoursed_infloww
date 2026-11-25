from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Literal, NamedTuple

from sqlalchemy import select

import vault_ai_brief
import vault_dupes
import vault_folder_prices
import vault_pack_picker
import vault_scripts
import vault_settings
import vault_topic_folders as vtf
from db.engine import get_session
from db.models import VaultFolder, VaultFolderItem, VaultItem

log = logging.getLogger("of-relay.automation.full_ai_sell")

Subject = Literal["feet", "butt", "tits", "pussy", "nude", "lingerie", "bikini", "shower", "toy",
                  "masturbation", "blowjob", "sex", "anything"]
Format = Literal["photo", "video", "any"]
Reason = Literal["sell_off", "inventory_unknown", "no_priced_items", "no_match", "all_owned", "offer_open"]

MIN_CENTS = vault_folder_prices.MIN_CENTS  # $10
MAX_CENTS = vault_folder_prices.MAX_CENTS  # $200
_LANE_CENTS = {"free": 0, "$10": 1000, "$50": 5000, "$100": 10000, "$150": 15000}


@dataclass(frozen=True)
class Ask:
    subject: Subject
    format: Format
    intensity: int
    count: int | None = None


@dataclass(frozen=True)
class Pick:
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


_LINGERIE = vtf.Topic("lingerie", "lingerie", "in lingerie or a bodysuit", "split",
                      lambda j, f: vtf.jev_tag(j, "outfit") == "lingerie_or_bodysuit")
_TOPICS: dict[str, tuple[vtf.Topic, ...]] = {
    subject: tuple(vtf.BY_SLUG[s] for s in slugs) for subject, slugs in {
        "butt": ("butt_tease", "butt_bare"), "tits": ("tits", "boobs_closeup"),
        "pussy": ("pussy", "spread"), "nude": ("nude",), "bikini": ("bikini",),
        "shower": ("shower_bath",), "toy": ("toy_tease", "toy_play"),
        "masturbation": ("masturbation",), "blowjob": ("blowjob",), "sex": ("sex", "with_partner"),
    }.items()}
_TOPICS["lingerie"] = (_LINGERIE,)
FEET_PACK = "feet"

_PARTNER_OK = frozenset({"sex", "blowjob"})


def in_folders(refs: Iterable[str], include: Iterable[str], exclude: Iterable[str]) -> bool:
    refs = set(refs)
    if refs & set(exclude):
        return False
    include = set(include)
    return not include or bool(refs & include)


def seed_for(account_id: str, fan_id: str, trigger_key: str) -> str:
    return f"pick:{account_id}:{fan_id}:{trigger_key}"


def clamp_cents(cents: int) -> int:
    return max(MIN_CENTS, min(MAX_CENTS, int(cents)))


def list_price_cents(jev: dict[str, Any] | None, fields: dict[str, Any], kind: str,
                     folder_cents: int | None = None) -> int | None:
    fields = fields or {}
    if jev is not None:
        if jev.get("lane5") == "review":
            return None
    # Folder price is the LIST price, replacing the lane price; a review item stays not for sale.
    if folder_cents is not None:
        return clamp_cents(folder_cents)
    if jev is not None:
        lane = vtf.lane_of(jev)
    else:
        lane = {50: "$50", 10: "$10"}.get(vault_scripts.shelf_price(fields, kind))
    if lane not in vtf.PRICES:
        return None
    if vtf._explicit(jev or {}, fields):
        if lane == "free":
            return None
        lane = vtf._EXPLICIT_OF[lane]
    # Free lane prices 0 (a preview/gift, never a locked paid item); 0 is not clamped up.
    cents = _LANE_CENTS[lane]
    return cents and clamp_cents(cents)


# A bad stored value raises (fail closed -> inventory_unknown): [] would read as unfiled, inside an empty include.
def _of_refs(raw: str | None) -> set[str]:
    ids = json.loads(raw) if raw else []
    if not isinstance(ids, list):
        raise ValueError(f"of_folder_ids not a list: {raw!r}")
    return {f"of:{x}" for x in ids if x is not None}


async def load_rows(account_id: str) -> tuple[list[dict[str, Any]], list[list[int]],
                                              dict[int, dict[str, Any]]] | Refusal:
    try:
        rows = await vault_scripts._load_rows(account_id)
        async with get_session() as s:
            of_raw = dict((await s.execute(
                select(VaultItem.media_id, VaultItem.of_folder_ids)
                .where(VaultItem.account_id == account_id, VaultItem.removed_at.is_(None)))).all())
            members = (await s.execute(
                select(VaultFolderItem.media_id, VaultFolder.id, VaultFolder.name, VaultFolder.created_by)
                .join(VaultFolder, VaultFolder.id == VaultFolderItem.folder_id)
                .where(VaultFolderItem.account_id == account_id, VaultFolder.account_id == account_id,
                       VaultFolder.deleted_at.is_(None)))).all()
        opts = await vault_settings.load(account_id)
        refs: dict[int, set[str]] = {}
        packs: dict[int, set[str]] = {}
        for mid, raw in of_raw.items():
            refs.setdefault(int(mid), set()).update(_of_refs(raw))
        from vault_standard_rules import parse_key, REVIEW
        needs_review: set[int] = set()
        for mid, fid, name, creator in members:
            standard = parse_key(str(creator or ""))
            if standard and not opts["standard_folders"]:
                continue
            if standard and standard[1] == REVIEW:
                needs_review.add(int(mid))
            refs.setdefault(int(mid), set()).add(f"vf:{fid}")
            if (cat := vault_pack_picker.pack_rung_category(name)) is not None:
                packs.setdefault(int(mid), set()).add(cat.name)
        prices = await vault_folder_prices.load(account_id)
        res = await vault_dupes.find_duplicates(account_id, rehash=False)
        groups = [[int(m["media_id"]) for m in (c["original"], *c["dupes"])] for c in res["clusters"]]
    except Exception:  # noqa: BLE001 — fail closed, never an un-expanded owned set
        log.exception("sell inventory unreadable account=%s", account_id)
        return Refusal("inventory_unknown")
    prints = await vault_scripts._fingerprints(account_id)
    out = []
    final = {"folder_final": True} if opts["folder_price_final"] else {}
    for r in rows:
        if r["media_id"] in needs_review:
            continue
        rr = refs.get(r["media_id"], set())
        out.append({**r, "refs": rr, "packs": packs.get(r["media_id"], set()),
                    "folder_cents": vault_folder_prices.highest(rr, prices), **final})
    return out, groups, prints


def expand_owned(owned: Iterable[int], dupe_groups: list[list[int]]) -> set[int]:
    out = {int(m) for m in owned}
    for group in dupe_groups:
        if out.intersection(group):
            out.update(int(m) for m in group)
    return out


def pool(rows: list[dict[str, Any]], dupe_groups: list[list[int]], owned: Iterable[int],
         folders: dict[str, Any], ask: Ask) -> list[dict[str, Any]] | Refusal:
    include, exclude = folders.get("include") or [], folders.get("exclude") or []
    # r["refs"], never a default: a row without refs would read as unfiled and slip past exclude.
    chosen = [r for r in rows if in_folders(r["refs"], include, exclude)]
    chosen, _ = vault_scripts.collapse_dupes(chosen, dupe_groups)
    if not chosen:
        return Refusal("no_match")
    priced = []
    for r in map(vault_scripts._with_script_why, chosen):
        fields = r.get("fields") or {}
        cents = list_price_cents(vtf.jev_of(fields), fields, r["kind"], r.get("folder_cents"))
        if cents is not None and not vault_scripts._unpriced_dispute(r):
            priced.append({**r, "list_cents": cents})
    if not priced:
        return Refusal("no_priced_items")
    if ask.subject not in _PARTNER_OK:
        priced = [r for r in priced if vault_ai_brief.sellability(r.get("fields") or {})["solo"] is True]
        if not priced:
            return Refusal("no_match")
    # No offer history is read: an unbought item stays sellable however often it was offered.
    gone = expand_owned(owned, dupe_groups)
    left = [r for r in priced if r["media_id"] not in gone]
    return left or Refusal("all_owned")


async def shoots_for(account_id: str, pool: list[dict[str, Any]],
                     prints: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    return await vault_scripts.collect_outfit_scripts(
        account_id, rows=pool, prints=prints, min_items=1, min_videos=0, require_escalation=False)


LEVEL_CENTS = {"soft": 1000, "nude": 5000, "explicit": 10000}


def target_cents(intensity: int) -> int:
    return 1000 if intensity <= 2 else 5000 if intensity == 3 else 10000


def _lane(cents: int) -> str:
    return next((lane for lane, c in _LANE_CENTS.items() if c == cents), None) or _money(cents)


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
    jev = vtf.jev_of(row.get("fields") or {})
    return jev is not None and vtf.free_ok(jev)


def _draw(rows: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    return rng.choice(sorted(rows, key=lambda r: r["media_id"]))


def _facts(locked: list[dict[str, Any]], previews: list[dict[str, Any]] = ()) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    for r in locked:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    shown = dict(kinds)
    for r in previews:
        shown[r["kind"]] = shown.get(r["kind"], 0) + 1
    folder = [r["folder_cents"] for r in locked if r.get("folder_cents") is not None]
    return {"kinds": kinds,
            "shown_kinds": shown,
            "items": [vault_ai_brief.sellability(r.get("fields") or {},
                                                 duration_seconds=r.get("duration_seconds"))
                      for r in locked],
            "description": str((locked[0].get("fields") or {}).get("description") or ""),
            "descriptions": [str((r.get("fields") or {}).get("description") or "") for r in locked],
            "hero": next(({"media_id": r["media_id"], "kind": r["kind"],
                           "seconds": r.get("duration_seconds"), "fields": r.get("fields") or {}}
                          for r in locked
                          if str((r.get("fields") or {}).get("description") or "").strip()), None),
            "media": [{"id": r["media_id"], "kind": r["kind"], "seconds": r.get("duration_seconds") or None}
                      for r in [*locked, *previews]],
            **({"folder_cents": max(folder)} if folder else {}),
            **({"folder_final": True} if folder and any(r.get("folder_final") for r in locked) else {})}


def _offer(locked: list[dict[str, Any]], previews: list[dict[str, Any]], ask: Ask, *,
           free: bool, subject: str | None = None, price: Literal["highest", "sum"] = "highest") -> Pick:
    top = max(r["list_cents"] for r in locked)
    cents = min(MAX_CENTS, sum(r["list_cents"] for r in locked)) if price == "sum" else top
    facts = _facts(locked, previews)
    if not free and facts.get("folder_final"):
        facts["folder_price_cents"] = cents
    return Pick(ref=locked[0]["media_id"], media=tuple(r["media_id"] for r in locked),
                previews=tuple(r["media_id"] for r in previews), price_cents=0 if free else cents,
                list_cents=cents, subject=subject or ask.subject, format=locked[0]["kind"], lane=_lane(top),
                facts=facts)


def folder_price(pick: Pick) -> int | None:
    return vault_folder_prices.parse_cents((pick.facts or {}).get("folder_price_cents"))


def hold_folder_price(got: Pick | Refusal) -> Pick | Refusal:
    if isinstance(got, Pick) and (saved := folder_price(got)) is not None:
        return replace(got, price_cents=saved, list_cents=saved)
    return got


def tease_price(pick: Pick, cents: int) -> Pick:
    return replace(pick, price_cents=cents, list_cents=cents or pick.list_cents,
                   facts={**pick.facts, "vault_list_cents": pick.list_cents})


def _nearest(pool: list[dict[str, Any]], ask: Ask) -> tuple[list[dict[str, Any]], str, str] | None:
    steps = (("format", replace(ask, format="any"), ask.subject),
             ("subject", replace(ask, subject="anything"), "anything"),
             ("any", replace(ask, subject="anything", format="any"), "anything"))
    for step, relaxed, subject in steps:
        if relaxed == ask:
            continue
        rows = [r for r in pool if _matches(r, relaxed)]
        if rows:
            return rows, subject, step
    return None


TEASE_PHOTO_CENTS = 500  # one photo per $5 of its price


def tease_photos(cents: int) -> int:
    return max(1, cents // TEASE_PHOTO_CENTS)


def pick(pool: list[dict[str, Any]], shoots: list[dict[str, Any]], ask: Ask, *,
         seed: str, free: bool = False, target: int | None = None,
         nearest: bool = False, bundle: str = "shoot", ride: bool = False,
         ride_max: int = 2) -> Pick | Refusal:
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

    if ride:
        ask = replace(ask, format="photo")
        pool = [r for r in pool if r["kind"] == "photo"]
    matching = [r for r in pool if _matches(r, ask)]
    subject, miss = None, None
    if not matching and nearest and (got := _nearest(pool, ask)) is not None:
        matching, subject, step = got
        miss = {"asked": {"subject": ask.subject, "format": ask.format}, "nearest": step}
    if not matching:
        return Refusal("no_match")
    cands = [r for r in matching if r["list_cents"] > 0]
    if not cands:
        return Refusal("no_priced_items")
    lanes = sorted({r["list_cents"] for r in cands})
    goal = target_cents(ask.intensity) if target is None else target
    lane = next((c for c in lanes if c >= goal), lanes[0])
    anchor = _draw([r for r in cands if r["list_cents"] == lane], rng)
    count = None if ride or not ask.count else min(COUNT_MAX, ask.count)
    if anchor["kind"] == "video":
        if not count:
            return _missed(_offer([anchor], [], ask, free=False, subject=subject), miss)
        more = sorted((r for r in cands if r["kind"] == "video" and r["media_id"] != anchor["media_id"]
                       and r["list_cents"] <= anchor["list_cents"]), key=lambda r: r["media_id"])
        rng.shuffle(more)
        p = _offer([anchor, *more[:count - 1]], [], ask, free=False, subject=subject, price="sum")
        return _missed(replace(p, facts={**p.facts, "asked_count": count}), miss)

    shoot = next((s for s in shoots if anchor["media_id"] in {i["media_id"] for i in s["items"]}), None)
    in_shoot = [i["media_id"] for i in shoot["items"]] if shoot else []
    by_id = {r["media_id"]: r for r in pool}
    mates = [r for r in cands if r["media_id"] in in_shoot and r["media_id"] != anchor["media_id"]
             and r["kind"] == "photo" and r["list_cents"] <= anchor["list_cents"]]
    mates.sort(key=lambda r: r["media_id"])
    rng.shuffle(mates)
    counted = bool(count) and bundle == "fill"
    size = ride_max if ride else min(COUNT_MAX, max(3, count)) if counted else 3
    locked = [anchor, *mates[:ride_max - 1 if ride else 4 if bundle == "fill" else 3]]
    if bundle == "fill" and len(locked) < size:
        have = {r["media_id"] for r in locked}
        same_lane = (subject or ask.subject) == "anything"
        fill = sorted((r for r in cands if r["kind"] == "photo" and r["media_id"] not in have
                       and (r["list_cents"] == anchor["list_cents"] if same_lane
                            else r["list_cents"] <= anchor["list_cents"])), key=lambda r: r["media_id"])
        rng.shuffle(fill)
        locked += fill[:size - len(locked)]
    if ride:
        p = _offer(locked, [], ask, free=False, subject=subject)
        return _missed(replace(p, facts={**p.facts, "ride": True}), miss)
    preview = next((by_id[m] for m in in_shoot if m in by_id and by_id[m]["kind"] == "photo"
                    and by_id[m]["list_cents"] == 0 and _free_safe(by_id[m])), None)
    p = _offer(locked, [preview] if preview else [], ask, free=False, subject=subject)
    if counted:
        p = replace(p, facts={**p.facts, "asked_count": count})
    return _missed(p, miss)


def _missed(p: Pick, miss: dict[str, Any] | None) -> Pick:
    return p if miss is None else replace(p, facts={**p.facts, **miss})


_MEDIA_NOUNS = frozenset({
    "video", "videos", "vid", "vids", "clip", "clips",
    "pic", "pics", "picture", "pictures", "photo", "photos", "image", "images",
    "content", "stuff", "set", "sets", "media",
})
MOVING_KINDS = ("video", "gif")
AUDIO_KINDS = ("audio",)
_VID_NOUNS = frozenset(w for w in _MEDIA_NOUNS if w.startswith(("vid", "clip")))
_PIC_NOUNS = frozenset(w for w in _MEDIA_NOUNS if w.startswith(("pic", "photo", "image")))
_KIND_NOUNS = _VID_NOUNS | _PIC_NOUNS


def _buckets(kinds: dict[str, int]) -> tuple[int, int, int]:
    vids = sum(n for k, n in kinds.items() if str(k).lower() in MOVING_KINDS)
    auds = sum(n for k, n in kinds.items() if str(k).lower() in AUDIO_KINDS)
    return sum(kinds.values()) - vids - auds, vids, auds


def kind_of(fmt: str) -> str:
    k = str(fmt).lower()
    return "video" if k in MOVING_KINDS else "audio" if k in AUDIO_KINDS else "photo"


def _media_phrase(kinds: dict[str, int]) -> str:
    pics, vids, auds = _buckets(kinds)
    parts = [f"{n} {word}{'s' * (n > 1)}" for n, word in ((pics, "pic"), (vids, "vid"), (auds, "voice note")) if n]
    return " + ".join(parts) if parts else "0 pics"


_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_NOT_A_COUNT = frozenset({"sec", "secs", "second", "seconds", "min", "mins", "minute", "minutes",
                          "hour", "hours", "few", "couple", "lot", "lots", "bunch", "ton", "tons",
                          "handful", "pair"})
_TOKEN = re.compile(r"[$€£]?\d+(?:[.,]\d+)?[$€£]?|[a-z]+")
_SUBJECT_WORDS: dict[str, frozenset[str]] = {k: frozenset(v) for k, v in {
    "feet": ("feet", "foot", "toes", "soles"), "butt": ("butt", "ass", "booty"),
    "tits": ("tits", "titties", "boobs", "breasts", "nipples"), "pussy": ("pussy",),
    "nude": ("nude", "nudes", "naked"), "lingerie": ("lingerie", "bodysuit"), "bikini": ("bikini",),
    "shower": ("shower", "bath"), "toy": ("toy", "dildo", "vibrator"),
    "masturbation": ("masturbating", "masturbation"), "blowjob": ("blowjob", "bj"),
    "sex": ("sex", "sextape"),
}.items()}


COUNT_MAX = 5
_PRICE_AGE = frozenset({"dollar", "dollars", "buck", "bucks", "usd", "euro", "euros", "cent", "cents",
                        "year", "years", "yr", "yrs", "yo", "old"})
_GAP_STOP = _PRICE_AGE | frozenset({"and", "or", "but", "so", "then", "i", "im", "me", "my", "you", "u",
                                    "ur", "your", "is", "am", "are", "was", "want", "wanna", "need",
                                    "send", "get", "buy", "have", "got", "give", "for", "to", "of",
                                    "the", "with", "in", "on", "at", "from", "if"})
_BUNDLE_WORDS = frozenset({"bundle", "pack", "set"})


def _count_word(tok: str) -> int | None:
    return int(tok) if tok.isdigit() else None if tok in ("a", "an") else _NUMBER_WORDS.get(tok)


def asked_count(text: str) -> int | None:
    toks = _TOKEN.findall(text.lower())
    found = []
    for i, tok in enumerate(toks):
        n = _count_word(tok)
        if n is None:
            continue
        if i >= 2 and toks[i - 1] == "of" and toks[i - 2] in _BUNDLE_WORDS:
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if nxt not in _NOT_A_COUNT and nxt not in _PRICE_AGE:
                found.append(n)
                continue
        for gap in range(3):
            j = i + 1 + gap
            if j >= len(toks):
                break
            if toks[j] in _KIND_NOUNS:
                found.append(n)
                break
            w = toks[j]
            if not w.isalpha() or w in _NOT_A_COUNT or w in _GAP_STOP or w in _NUMBER_WORDS:
                break
    top = max(found, default=0)
    return min(COUNT_MAX, top) if top > 1 else None


# The describer writes 'vulva', never 'pussy': without these, 'my pussy' over such a clip false-failed the audit.
_DESCRIBE_WORDS: dict[str, frozenset[str]] = {k: frozenset(v) for k, v in {
    "pussy": ("vulva", "vagina", "labia", "genitals"), "butt": ("buttocks",),
    "tits": ("breast", "nipple", "topless"), "nude": ("unclothed", "undressed"),
    "toy": ("toys", "dildos"), "masturbation": ("masturbates", "masturbate", "fingering"),
}.items()}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


# 'watch'/'shot' excluded (photos are watched and shot too), as are 'movie'/'film'.
_CLIP_WORDS = frozenset({"filmed", "filming", "recorded", "recording", "footage"})
_PLAY = re.compile(r"\b(?:press|hit)\s+play\b")


def claims_clip(text: str) -> bool:
    return bool(_CLIP_WORDS & set(_words(text))) or bool(_PLAY.search(text.lower()))
_NT = re.compile(r"n['’]t\b")
_NEG_CUES = frozenset({"not", "no", "without", "instead", "rather", "never", "nt", "dont", "doesnt",
                       "didnt", "isnt", "arent", "wasnt", "werent", "cant", "cannot", "wont",
                       "wouldnt", "couldnt", "shouldnt", "aint", "havent", "hasnt", "hadnt"})


def _neg_words(text: str) -> list[str]:
    return _words(_NT.sub("nt", text.lower()))


_EXCUSE_WINDOW, _DISCLOSE_WINDOW = 3, 4
_DISCLOSE = re.compile(r"\b(?:not what|not exactly|not quite|instead|rather than|different|closest|only got"
                       r"|only have|dont have (?:that|it|one|any)|havent got)\b")


_AFFIRMS = frozenset({"just", "only"})


def _negated(words: list[str], i: int, window: int) -> bool:
    lo = max(0, i - window)
    return any(w in _NEG_CUES and words[j + 1] not in _AFFIRMS for j, w in enumerate(words[lo:i], lo))


_LINKS = frozenset({"of", "my", "ur", "your"})


def _continues(words: list[str], i: int, excused: set[int]) -> bool:
    j = i - 1
    while j >= 0 and words[j] in _LINKS:
        j -= 1
    return j in excused


_CLAUSE = re.compile(r"[.!?;:,\n]+|(?=\b(?:but|though|tho|although|however)\b)")


def _clauses(text: str) -> list[list[str]]:
    return [_words(c) for c in _CLAUSE.split(_NT.sub("nt", text.lower()))]


class _Count(NamedTuple):
    n: int
    article: bool
    noun: str
    at: int


def _counts(low: str) -> list[_Count]:
    toks = _TOKEN.findall(low)
    at, words = [], 0
    for t in toks:
        at.append(words)
        words += t.isalpha()
    out = []
    for i, tok in enumerate(toks):
        n = int(tok) if tok.isdigit() else _NUMBER_WORDS.get(tok)
        nxt = toks[i + 1:i + 3]
        if n is None or not nxt:
            continue
        if nxt[0] in _KIND_NOUNS:
            j = i + 1
        elif (len(nxt) == 2 and nxt[1] in _KIND_NOUNS and nxt[0].isalpha()
              and nxt[0] not in _NOT_A_COUNT and nxt[0] not in _NUMBER_WORDS):
            j = i + 2
        else:
            continue
        out.append(_Count(n, tok in ("a", "an"), toks[j], at[j]))
    return out


def _excused(clauses: list[list[str]], mask: frozenset[str]) -> set[int]:
    out: set[int] = set()
    at = 0
    for words in clauses:
        local: set[int] = set()
        for i, w in enumerate(words):
            if w in mask and (_negated(words, i, _EXCUSE_WINDOW) or _continues(words, i, local)):
                local.add(i)
        out |= {at + i for i in local}
        at += len(words)
    return out


def _asked_mask(asked: dict) -> frozenset[str]:
    fmt = asked.get("format")
    nouns = _VID_NOUNS | _CLIP_WORDS if fmt == "video" else _PIC_NOUNS if fmt == "photo" else frozenset()
    return nouns | _SUBJECT_WORDS.get(asked.get("subject"), frozenset())


def real_formats(pick: Pick) -> set[str]:
    pics, vids, _auds = _buckets(pick.facts.get("kinds") or {pick.format: len(pick.media) or 1})
    return {f for f, n in (("photo", pics), ("video", vids)) if n}


def claim_ok(text: str, pick: Pick) -> bool:
    low = text.lower()
    pics, vids, _auds = _buckets(pick.facts["kinds"])
    seen_pics, seen_vids, _ = _buckets(pick.facts.get("shown_kinds", pick.facts["kinds"]))
    asked = pick.facts.get("asked")
    said = _neg_words(low) if asked else _words(low)
    excused = _excused(_clauses(low), _asked_mask(asked)) if asked else set()
    for i, w in enumerate(said):
        have = seen_vids if w in _VID_NOUNS or w in _CLIP_WORDS else seen_pics if w in _PIC_NOUNS else None
        if i not in excused and have is not None and (have == 0 or (w.endswith("s") and have == 1)):
            return False
    if not seen_vids and _PLAY.search(low):
        return False
    for c in _counts(low):
        if not c.article and c.n not in ((vids, seen_vids) if c.noun in _VID_NOUNS else (pics, seen_pics)):
            return False
    desc = set(_words(" ".join(pick.facts.get("descriptions", [pick.facts["description"]]))))
    allowed = set(_SUBJECT_WORDS.get(pick.subject, ()))
    for subject, words in _SUBJECT_WORDS.items():
        if desc & (words | _DESCRIBE_WORDS.get(subject, frozenset())):
            allowed |= words
    named = {w for i, w in enumerate(said) if i not in excused} & frozenset().union(*_SUBJECT_WORDS.values())
    return named <= allowed


def discloses(text: str, pick: Pick) -> bool:
    asked = pick.facts.get("asked")
    if not asked:
        return True
    words = _neg_words(text)
    mask = _asked_mask(asked)
    if not any(any(w in mask and _negated(c, i, _DISCLOSE_WINDOW) for i, w in enumerate(c))
               or _DISCLOSE.search(" ".join(c)) for c in _clauses(text)):
        return False
    real = real_formats(pick)
    if asked.get("format") in ("photo", "video") and asked["format"] not in real and real:
        nouns = (_VID_NOUNS if "video" in real else frozenset()) | (_PIC_NOUNS if "photo" in real else frozenset())
        return bool(set(words) & nouns)
    return True


def _affirmed_amount(text: str) -> bool:
    for m in _AMOUNT.finditer(text):
        words = _clauses(text[:m.start()])[-1]
        if not _negated([*words, ""], len(words), _EXCUSE_WINDOW):
            return True
    return False


def states_terms(text: str, pick: Pick, price_cents: int | None) -> bool:
    if price_cents and not _affirmed_amount(text):
        return False
    pics, vids, _auds = _buckets(pick.facts["kinds"])
    asked = pick.facts.get("asked")
    clauses = _clauses(text)
    excused = _excused(clauses, _asked_mask(asked)) if asked else set()
    negated = _excused(clauses, _KIND_NOUNS)
    counted: set[str] = set()
    for c in _counts(_NT.sub("nt", text.lower())):
        if c.at in excused:
            continue
        kind = "video" if c.noun in _VID_NOUNS else "photo"
        if c.n != (vids if kind == "video" else pics):
            return False
        if c.at not in negated:
            counted.add(kind)
    return {k for k, held in (("photo", pics), ("video", vids)) if held} <= counted


def caption_fails(text: str, pick: Pick, price_cents: int | None, *, differs: bool) -> list[str]:
    return [c for c, good in (("claim", claim_ok(text, pick)), ("price", price_ok(text, price_cents)),
                              ("disclose", discloses(text, pick)),
                              ("terms", not differs or states_terms(text, pick, price_cents))) if not good]


def _amount_re(signs: str, words: str) -> re.Pattern:
    num = r"(\d+(?:\.\d{1,2})?)"
    return re.compile(rf"[{signs}]\s?{num}|{num}\s?(?:[{signs}]|(?:{words})\b)", re.I)


_AMOUNT = _amount_re("$€£", "dollars?|bucks?|usd|euros?")


_FREE = re.compile(r"\bfree\b", re.I)


# A priced PPV is never called free; any whole word 'free' fails (one rewrite, then the fallback caption).
def price_ok(text: str, price_cents: int | None) -> bool:
    named = {round(float(a or b) * 100) for a, b in _AMOUNT.findall(text)}
    if not price_cents:
        return not named
    return named <= {price_cents} and not _FREE.search(text)


_QUOTE = _amount_re("$", "dollars?|bucks?|usd")


def _next_to_tip(text: str, m: re.Match) -> bool:
    near = _words(text[:m.start()])[-2:] + _words(text[m.end():])[:1]
    return any(w.startswith("tip") for w in near)


def quoted_cents(text: str) -> int | None:
    found = list(_QUOTE.finditer(text))
    if len(found) != 1 or _next_to_tip(text, found[0]):
        return None
    m = found[0]
    return round(float(m.group(1) or m.group(2)) * 100)


def _ceil_dollar(cents: int) -> int:
    return -(-cents // 100) * 100


# Always against the row's list price, never an earlier quote, so discounts never compound; integer math (0.67 * 10000 drifts to $68).
def clamp_quote(list_cents: int, asked_cents: int | None) -> int:
    floor = max(MIN_CENTS, _ceil_dollar(-(-67 * list_cents // 100)))
    if asked_cents is None:
        return floor
    return min(list_cents, max(floor, _ceil_dollar(asked_cents)))


def _money(cents: int) -> str:
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def fallback_caption(pick: Pick, kind: Literal["offer", "tease", "free"]) -> str:
    if pick.facts.get("asked"):
        phrase = f"not what u asked for babe, this one's {_media_phrase(pick.facts['kinds'])}"
    else:
        phrase = _media_phrase(pick.facts.get("shown_kinds", pick.facts["kinds"]))
    return f"{phrase}, {_money(pick.price_cents)} to unlock" if kind == "offer" else phrase


@dataclass(frozen=True)
class Teased:
    subject: str
    format: str
    locked: tuple[int, ...]
    previews: tuple[int, ...]
    list_cents: int
    row_id: int | None = None


def same_piece(pool: list[dict[str, Any]], locked: Iterable[int], previews: Iterable[int],
               ask: Ask) -> Pick | None:
    by_id = {r["media_id"]: r for r in pool}
    locked = list(locked)
    if not locked or any(m not in by_id or by_id[m]["list_cents"] <= 0 for m in locked):
        return None
    keep = [by_id[m] for m in previews
            if m in by_id and by_id[m]["list_cents"] == 0 and _free_safe(by_id[m])]
    rows = [by_id[m] for m in locked]
    bundle = len(rows) > 1 and all(r["kind"] == "video" for r in rows)
    return _offer(rows, keep, ask, free=False, price="sum" if bundle else "highest")
