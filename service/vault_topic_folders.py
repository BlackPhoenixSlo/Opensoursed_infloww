"""service/vault_topic_folders.py — the pure half of the opt-in "Topic folders (Jev)" in Build AI folders.

`vault_scripts.plan_ai_folders(topics=[...])` adds one folder per (ticked topic, price split) on top of the
scripts and lanes; an item may sit in a lane AND a topic folder. Everything is read from the Jev v8 blob
(`ai_fields_json["_jev"]`, `vault_jev_rules.blob`): photos whose `_jev` is current (`vault_jev_rules.current`)
only. Items without it (Jev off, not run yet, failed, older version) are in no topic folder; the plan counts
the coverage so the modal says "N of M photos have Jev data".

What the rules read (all already in the blob, no new Jev question):
  `tags[q]` for Choice questions = the argmax (people_count, added_text, toy, outfit, setting, pose, framing,
            face_visible, facing).
  `tags[q]` for Noul questions = "y" / "n" at the bench-calibrated per-tag cut (`vault_jev_rules.CUTS`, D23;
            .5 where uncalibrated) — the same y/n the vault search chips use. `_yes` falls back to `P[q]` at
            that cut when a tag is missing. `butt_bare` is max(butt_state_a bare, butt_cheeks_bare) at .35.
  `lane5` "free" | "$10" | "$50" | "$100" | "review" and `breasts_bare` / `crotch_bare` / `penetration`
            y / n / unsure for the price split and the free guard.

Price split (`split`): every topic folder is ONE price, named `AI-<name> <price>`:
  "split" topics → free / $10 / $50 / $100 by `lane5` ($100 kept apart rather than folded into $50: it is the
            penetration tier, and pricing it as $50 undersells it). Empty splits are not made.
  "paid"  topics (toy play) → $10 / $50 / $100 only; never free.
  "free"  topics (good morning, clean for promo) → free only.
`lane5` "review" or anything unknown → in NO topic folder. FREE GUARD (`free_ok`): a free split never holds an
item whose `breasts_bare`, `crotch_bare` or `penetration` is "y" or "unsure", whatever `lane5` says (settle nn.10
can call a coin-flip nipple free when NudeNet saw nothing; a topic folder must not).

Feet (`feet`, group "feet"): "rung" topic, ONE slug making up to three folders, `AI-feet tease` / `AI-feet nude` /
`AI-feet nude-body`, named by the feet ladder's rung instead of a price. Membership and rung are the pack picker's
preselect, imported, never re-derived (`vault_pack_picker.jev_pick`: feet seen, score >=
`vault_pack_picker.FEET_PRESELECT_SCORE`, rung from the body's Jev tier + `feet_detail`). AI-feet tease is the free
preview rung, so it obeys the FREE GUARD here too (`free_ok`), on top of the picker's own tier-0 rule.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, NamedTuple

import vault_jev_rules
import vault_pack_picker

PRICES = ("free", "$10", "$50", "$100")
_PAID = ("$10", "$50", "$100")


class Topic(NamedTuple):
    slug: str
    name: str
    description: str
    price: str                       # "split" | "paid" | "free" | "rung" (feet: by the pack picker's rung)
    rule: Callable[[dict[str, Any]], bool]
    group: str = "topics"            # the modal's checklist group


def _tag(jev: dict[str, Any], q: str) -> Any:
    return (jev.get("tags") or {}).get(q)


def _yes(jev: dict[str, Any], q: str) -> bool:
    """A Noul question answered yes at its calibrated cut (the stored y/n tag; `P` at the same cut if absent)."""
    t = _tag(jev, q)
    if t in ("y", "n"):
        return t == "y"
    p = (jev.get("P") or {}).get(q)
    return isinstance(p, (int, float)) and p >= vault_jev_rules.CUTS.get(q, .5)


def _butt_shown(j: dict[str, Any]) -> bool:
    return (_yes(j, "butt_focus") or _tag(j, "facing") == "away"
            or _tag(j, "pose") in ("all_fours_or_bent_over", "lying_on_stomach"))


TOPICS: tuple[Topic, ...] = (
    Topic("heels_stockings", "heels & stockings", "wearing heels, stockings or fishnets", "split",
          lambda j: _yes(j, "wears_heels") or _yes(j, "wears_stockings_or_fishnets")),
    Topic("butt_tease", "butt tease", "her butt is the subject, still covered", "split",
          lambda j: _yes(j, "butt_focus") and not _yes(j, "butt_bare")),
    Topic("butt_bare", "butt bare", "bare butt cheeks on show (the subject, turned away or bent over)", "split",
          lambda j: _yes(j, "butt_bare") and _butt_shown(j)),
    Topic("boobs_closeup", "boobs close-up", "breasts are the subject, framed close", "split",
          lambda j: _yes(j, "breasts_focus") and _tag(j, "framing") in ("body_part_close_up", "face_and_chest")),
    Topic("see_through", "see-through", "sheer fabric or a nipple showing through it", "split",
          lambda j: _yes(j, "see_through") or _yes(j, "nipple_through_fabric")),
    Topic("spread", "spread", "legs spread", "split", lambda j: _yes(j, "legs_spread")),
    Topic("bent_over", "bent over", "on all fours or bent over", "split",
          lambda j: _tag(j, "pose") == "all_fours_or_bent_over"),
    Topic("toy_tease", "toy tease", "a toy in shot, not in use", "split",
          lambda j: _tag(j, "toy") == "toy_visible_not_in_use"),
    Topic("toy_play", "toy play", "a toy touching or inserted (paid only)", "paid",
          lambda j: _tag(j, "toy") == "toy_touching_or_inserted"),
    Topic("with_partner", "with partner", "two or more people in shot", "split",
          lambda j: _tag(j, "people_count") == "two_or_more"),
    Topic("faceless", "faceless", "no face in shot", "split", lambda j: _tag(j, "face_visible") == "no_face"),
    Topic("mirror_selfies", "mirror selfies", "mirror selfies", "split", lambda j: _yes(j, "mirror_selfie")),
    Topic("good_morning", "good morning", "smiling at the camera, casual or in bed (free only)", "free",
          lambda j: _yes(j, "smiling") and _yes(j, "looking_at_camera")
          and (_tag(j, "outfit") == "everyday_clothes" or _tag(j, "setting") == "bedroom")),
    Topic("bikini", "bikini", "in swimwear", "split", lambda j: _tag(j, "outfit") == "swimwear"),
    Topic("shower_bath", "shower & bath", "in the bathroom or in water", "split",
          lambda j: _tag(j, "setting") == "bathroom" or _yes(j, "feet_in_water")),
    Topic("outdoors_car", "outdoors & car", "outdoors or in a car", "split",
          lambda j: _tag(j, "setting") in ("outdoors", "car")),
    Topic("lips_tongue", "lips & tongue", "a lip bite, pout or tongue out", "split",
          lambda j: _yes(j, "mouth_tease") or _yes(j, "tongue_out")),
    Topic("clean_promo", "clean for promo", "no text, watermark, censor, phone or collage (free only)", "free",
          lambda j: _tag(j, "added_text") == "nothing_added" and not any(
              _yes(j, q) for q in ("watermark", "censor_edit", "phone_visible", "multi_panel"))),
)
FEET = vault_pack_picker.category("feet")
TOPICS += (
    Topic("feet", "feet", "feet the subject (Jev feet score >= .6): tease / nude / nude-body", "rung",
          lambda j: feet_rung(j) is not None, group="feet"),
)
BY_SLUG: dict[str, Topic] = {t.slug: t for t in TOPICS}
SLUGS: tuple[str, ...] = tuple(BY_SLUG)


def parse_topics(raw: str | Iterable[Any] | None) -> list[str]:
    """Requested topic slugs, de-duplicated, in catalogue order (so preview and apply agree however the client
    ordered them). A comma string (the GET) or a list (the apply body). Raises ValueError(unknown slugs)."""
    if raw is None:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    want = {str(x).strip() for x in items if str(x).strip()}
    unknown = sorted(want - BY_SLUG.keys())
    if unknown:
        raise ValueError(unknown)
    return [s for s in SLUGS if s in want]


def jev_of(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    """The item's current, successful `_jev` (this VERSION, status ok), else None."""
    return fields["_jev"] if vault_jev_rules.current(fields) else None


def free_ok(jev: dict[str, Any]) -> bool:
    """FREE GUARD: nothing Jev saw or half-saw bare. Every one of the three must be a plain "n"."""
    return all(jev.get(k) == "n" for k in ("breasts_bare", "crotch_bare", "penetration"))


def feet_rung(jev: dict[str, Any]) -> str | None:
    """The AI-feet rung: the pack picker's preselect (`vault_pack_picker.jev_pick`), the free rung only past
    `free_ok` as well."""
    rung = vault_pack_picker.jev_pick(FEET, jev)
    if rung == FEET.free_rung and not free_ok(jev):
        return None
    return rung


def splits(topic: Topic) -> tuple[str, ...]:
    """The folders a topic can make, in send order: the feet rungs for a "rung" topic, else PRICES."""
    return FEET.rungs if topic.price == "rung" else PRICES


def split(topic: Topic, jev: dict[str, Any]) -> str | None:
    """The price (or, "rung" topics, feet rung) folder this item goes to for `topic`, or None (not in the topic,
    review, guarded, wrong price)."""
    if topic.price == "rung":
        return feet_rung(jev)
    lane5 = jev.get("lane5")
    if lane5 not in PRICES or not topic.rule(jev):
        return None
    if lane5 == "free":
        return "free" if topic.price != "paid" and free_ok(jev) else None
    return lane5 if topic.price != "free" else None


def folder_name(topic: Topic, price: str) -> str:
    """`<name> <price>`, before the `AI-` prefix (`vault_scripts.ai_folder_name`)."""
    return f"{topic.name} {price}"


def assign(rows: Iterable[dict[str, Any]], slugs: Iterable[str]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """{(slug, price): rows} for the requested topics over photo rows with a current `_jev`. Insertion order:
    catalogue order, then `splits`; empty splits absent."""
    jevs = [(r, jev_of(r.get("fields"))) for r in rows if r.get("kind") == "photo"]
    jevs = [(r, j) for r, j in jevs if j is not None]
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for slug in slugs:
        t = BY_SLUG[slug]
        got: dict[str, list[dict[str, Any]]] = {}
        for r, j in jevs:
            p = split(t, j)
            if p is not None:
                got.setdefault(p, []).append(r)
        for p in splits(t):
            if got.get(p):
                out[(slug, p)] = got[p]
    return out


def catalogue(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every topic with how many photos it would hold (all splits) — shown beside each checkbox, so it is
    counted for ticked and unticked topics alike."""
    placed = assign(rows, SLUGS)
    out = []
    for t in TOPICS:
        ids = {r["media_id"] for (s, _), rs in placed.items() if s == t.slug for r in rs}
        out.append({"slug": t.slug, "name": t.name, "description": t.description, "price": t.price,
                    "group": t.group, "count": len(ids)})
    return out


def coverage(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """{photos, with_jev}: how many of the planned photos carry a current `_jev`."""
    photos = [r for r in rows if r.get("kind") == "photo"]
    return {"photos": len(photos), "with_jev": sum(1 for r in photos if jev_of(r.get("fields")) is not None)}
