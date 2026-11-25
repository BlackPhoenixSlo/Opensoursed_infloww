from __future__ import annotations

from typing import Any, Callable, Iterable, NamedTuple

import vault_ai_brief
import vault_jev_rules

PRICES = ("free", "$10", "$50", "$100")
EXPLICIT = ("$50", "$100", "$150")
_EXPLICIT_OF = {"$10": "$50", "$50": "$100", "$100": "$150"}


class Topic(NamedTuple):
    slug: str
    name: str
    description: str
    price: str
    rule: Callable[[dict[str, Any], dict[str, Any]], bool]


def jev_tag(jev: dict[str, Any], q: str) -> Any:
    return (jev.get("tags") or {}).get(q)


def _yes(jev: dict[str, Any], q: str) -> bool:
    t = jev_tag(jev, q)
    if t in ("y", "n"):
        return t == "y"
    p = (jev.get("P") or {}).get(q)
    return isinstance(p, (int, float)) and p >= vault_jev_rules.CUTS.get(q, .5)


def _butt_shown(j: dict[str, Any]) -> bool:
    return (_yes(j, "butt_focus") or jev_tag(j, "facing") == "away"
            or jev_tag(j, "pose") in ("all_fours_or_bent_over", "lying_on_stomach"))


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()

# Unknown acts are ignored, so these are spellings the model actually returned.

# Spellings the model actually returned (`stripping` for strip, `rubbing_breasts`); unknown acts are ignored, not guessed.
ACT_ALIASES: dict[str, str] = {
    "stripping": "strip",
    "undressing": "undress",
    "rubbing_breasts": "groping_own_breasts",
    "groping_breasts": "groping_own_breasts",
    "twerking": "twerk",
    "teasing": "tease",
    "posing_for_camera": "posing",
    "masturbation": "masturbation_orgasm",
    "orgasm": "masturbation_orgasm",
    "squirting": "squirt",
}


def acts(fields: dict[str, Any]) -> set[str]:
    raw = fields.get("acts")
    return {ACT_ALIASES.get(_norm(a), _norm(a)) for a in raw} if isinstance(raw, (list, tuple)) else set()


_MASTURBATION = frozenset({"rubbing_clit", "fingering", "masturbation_orgasm", "squirt"})
_DANCE_STRIP = frozenset({"twerk", "ass_shaking", "strip", "undress"})


def _masturbation(j: dict[str, Any], f: dict[str, Any]) -> bool:
    if jev_tag(j, "people_count") == "two_or_more" or _sex(j, f):
        return False
    return (bool(acts(f) & _MASTURBATION)
            or (_yes(j, "self_touch") and j.get("crotch_bare") == "y")
            or (j.get("penetration") == "y" and jev_tag(j, "toy") == "no_toy"))


def _sex(j: dict[str, Any], f: dict[str, Any]) -> bool:
    return (any(a.startswith("sex_") for a in acts(f)) or _norm(f.get("penetration")) == "penis"
            or _norm(f.get("primary_folder")) == "sex_with_partner")


def _explicit(j: dict[str, Any], f: dict[str, Any]) -> bool:
    return (bool(acts(f) & (_MASTURBATION | {"blowjob", "handjob"})) or _sex(j, f) or _masturbation(j, f)
            or _norm(f.get("primary_folder")) == "blowjob" or jev_tag(j, "toy") == "toy_touching_or_inserted")


TOPICS: tuple[Topic, ...] = (
    Topic("heels_stockings", "heels & stockings", "wearing heels, stockings or fishnets", "split",
          lambda j, f: _yes(j, "wears_heels") or _yes(j, "wears_stockings_or_fishnets")),
    Topic("butt_tease", "butt tease", "her butt is the subject, still covered", "split",
          lambda j, f: _yes(j, "butt_focus") and not _yes(j, "butt_bare")),
    Topic("butt_bare", "butt bare", "bare butt cheeks on show (the subject, turned away or bent over)", "split",
          lambda j, f: _yes(j, "butt_bare") and _butt_shown(j)),
    Topic("boobs_closeup", "boobs close-up", "breasts are the subject, framed close", "split",
          lambda j, f: _yes(j, "breasts_focus") and jev_tag(j, "framing") in ("body_part_close_up", "face_and_chest")),
    Topic("see_through", "see-through", "sheer fabric or a nipple showing through it", "split",
          lambda j, f: _yes(j, "see_through") or _yes(j, "nipple_through_fabric")),
    Topic("spread", "spread", "legs spread", "split", lambda j, f: _yes(j, "legs_spread")),
    Topic("bent_over", "bent over", "on all fours or bent over", "split",
          lambda j, f: jev_tag(j, "pose") == "all_fours_or_bent_over"),
    Topic("toy_tease", "toy tease", "a toy in shot, not in use", "split",
          lambda j, f: jev_tag(j, "toy") == "toy_visible_not_in_use"),
    Topic("toy_play", "toy play", "a toy touching or inserted ($50 / $100 / $150)", "explicit",
          lambda j, f: jev_tag(j, "toy") == "toy_touching_or_inserted"),
    Topic("with_partner", "with partner", "two or more people in shot", "split",
          lambda j, f: jev_tag(j, "people_count") == "two_or_more"),
    Topic("faceless", "faceless", "no face in shot", "split", lambda j, f: jev_tag(j, "face_visible") == "no_face"),
    Topic("mirror_selfies", "mirror selfies", "mirror selfies", "split", lambda j, f: _yes(j, "mirror_selfie")),
    Topic("good_morning", "good morning", "smiling at the camera, casual or in bed (free only)", "free",
          lambda j, f: _yes(j, "smiling") and _yes(j, "looking_at_camera")
          and (jev_tag(j, "outfit") == "everyday_clothes" or jev_tag(j, "setting") == "bedroom")),
    Topic("bikini", "bikini", "in swimwear", "split", lambda j, f: jev_tag(j, "outfit") == "swimwear"),
    Topic("shower_bath", "shower & bath", "in the bathroom or in water", "split",
          lambda j, f: jev_tag(j, "setting") == "bathroom" or _yes(j, "feet_in_water")),
    Topic("outdoors_car", "outdoors & car", "outdoors or in a car", "split",
          lambda j, f: jev_tag(j, "setting") in ("outdoors", "car")),
    Topic("lips_tongue", "lips & tongue", "a lip bite, pout or tongue out", "split",
          lambda j, f: _yes(j, "mouth_tease") or _yes(j, "tongue_out")),
    Topic("clean_promo", "clean for promo", "no text, watermark, censor, phone or collage (free only)", "free",
          lambda j, f: jev_tag(j, "added_text") == "nothing_added" and not any(
              _yes(j, q) for q in ("watermark", "censor_edit", "phone_visible", "multi_panel"))),
    Topic("nude", "nudes", "fully nude", "split", lambda j, f: jev_tag(j, "outfit") == "nude"),
    Topic("tits", "tits", "bare breasts, the subject or topless", "split",
          lambda j, f: j.get("breasts_bare") == "y" and (_yes(j, "breasts_focus") or _yes(j, "topless"))),
    Topic("pussy", "pussy", "pussy on show", "split", lambda j, f: j.get("crotch_bare") == "y"),
    Topic("masturbation", "masturbation", "rubbing, fingering or coming ($50 / $100 / $150)", "explicit",
          _masturbation),
    Topic("blowjob", "blowjob", "a blowjob or handjob, a dildo too ($50 / $100 / $150)", "explicit",
          lambda j, f: bool(acts(f) & {"blowjob", "handjob"}) or _norm(f.get("primary_folder")) == "blowjob"),
    Topic("sex", "sex", "sex with a partner ($50 / $100 / $150)", "explicit", _sex),
    Topic("clothed_tease", "clothed tease", "dressed, in lingerie or swimwear, nothing bare (free only)", "free",
          lambda j, f: jev_tag(j, "outfit") in ("everyday_clothes", "lingerie_or_bodysuit", "swimwear")),
    Topic("dance_strip", "dance & strip", "twerking, shaking or stripping (mostly clips)", "split",
          lambda j, f: bool(acts(f) & _DANCE_STRIP)),
    Topic("gym_yoga", "gym & yoga", "at the gym", "split", lambda j, f: jev_tag(j, "setting") == "gym"),
)
BY_SLUG: dict[str, Topic] = {t.slug: t for t in TOPICS}
SLUGS: tuple[str, ...] = tuple(BY_SLUG)


def parse_topics(raw: str | Iterable[Any] | None) -> list[str]:
    if raw is None:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    want = {str(x).strip() for x in items if str(x).strip()}
    unknown = sorted(want - BY_SLUG.keys())
    if unknown:
        raise ValueError(unknown)
    return [s for s in SLUGS if s in want]


def jev_of(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    return fields["_jev"] if vault_jev_rules.current(fields) else None


def free_ok(jev: dict[str, Any]) -> bool:
    return vault_jev_rules.body_free(jev)


def splits(topic: Topic) -> tuple[str, ...]:
    return EXPLICIT if topic.price == "explicit" else PRICES


def lane_of(jev: dict[str, Any]) -> Any:
    return vault_jev_rules.read_lane(jev) if jev.get("kind") == "video" else jev.get("lane5")


def split(topic: Topic, jev: dict[str, Any], fields: dict[str, Any] | None = None) -> str | None:
    video = jev.get("kind") == "video"
    lane = lane_of(jev)
    if lane not in PRICES or not topic.rule(jev, fields or {}):
        return None
    # A review clip's free read may be too low: never free; the describe/flags side vetoes too.
    if lane == "free":
        ok = (topic.price in ("split", "free") and free_ok(jev) and not (video and jev.get("lane5") == "review")
              and not _explicit(jev, fields or {}) and not vault_ai_brief.free_vetoed(fields))
        return "free" if ok else None
    if topic.price == "free":
        return None
    return _EXPLICIT_OF[lane] if topic.price == "explicit" else lane


def folder_name(topic: Topic, price: str | None) -> str:
    return topic.name if price is None else f"{topic.name} {price}"


def _jev_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("kind") in vault_jev_rules.JEV_KINDS]


def assign(rows: Iterable[dict[str, Any]], slugs: Iterable[str], *, by_price: bool = True,
           ) -> dict[tuple[str, str | None], list[dict[str, Any]]]:
    jevs = [(r, jev_of(r.get("fields"))) for r in _jev_rows(rows)]
    jevs = [(r, j) for r, j in jevs if j is not None]
    out: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for slug in slugs:
        t = BY_SLUG[slug]
        got: dict[str, list[dict[str, Any]]] = {}
        for r, j in jevs:
            p = split(t, j, r.get("fields"))
            if p is not None:
                got.setdefault(p, []).append(r)
        if by_price:
            for p in splits(t):
                if got.get(p):
                    out[(slug, p)] = got[p]
        else:
            union = [r for p in splits(t) for r in got.get(p, [])]
            if union:
                out[(slug, None)] = union
    return out


def catalogue(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    placed = assign(rows, SLUGS)
    out = []
    for t in TOPICS:
        ids = {r["media_id"] for (s, _), rs in placed.items() if s == t.slug for r in rs}
        out.append({"slug": t.slug, "name": t.name, "description": t.description, "price": t.price,
                    "count": len(ids)})
    return out


def coverage(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    items = _jev_rows(rows)
    return {"items": len(items), "with_jev": sum(1 for r in items if jev_of(r.get("fields")) is not None)}
