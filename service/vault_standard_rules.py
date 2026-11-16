"""Standard vault categories, derived from saved effective analysis. No model calls.

Categories are multi-label references, never copies of media. This module does
not change Jev, descriptions, tags, prices, or the existing AI folder builder.
"""
from __future__ import annotations

import re
from typing import Any

from jsonsafe import load_json
from vault_ai_effective import effective_value

PREFIX = "vault_standard:"
REVIEW = "uncategorised"
CATEGORIES = (
    ("casual", "Casual / SFW"), ("selfie", "Selfie"),
    ("mirror_selfie", "Mirror Selfie"), ("cosplay", "Cosplay / Costume"),
    ("bikini", "Bikini"), ("lingerie", "Lingerie"), ("see_through", "See-Through"),
    ("topless", "Topless"), ("tits", "Tits"), ("full_nude", "Full Nude"),
    ("ass_covered", "Ass - Covered"), ("ass_bare", "Ass - Bare"),
    ("feet", "Feet"), ("pussy", "Pussy"), ("solo_play", "Solo Play"),
    ("toy_play", "Toy Play"), ("blowjob", "Blowjob"), ("handjob", "Handjob"),
    ("receiving_oral", "Receiving Oral"), ("partner_sex", "Partner Sex"),
    ("anal_display", "Anal Display"), ("anal_play", "Anal Play"),
    ("bed", "Bed"), ("shower", "Shower"), ("bath", "Bath"),
    ("beach", "Beach"), ("pool", "Pool"), ("outdoors", "Outdoors"),
    ("gym", "Gym / Fitness"), ("car", "Car"),
)
VIDEO_CATEGORIES = (("striptease", "Striptease"), ("dancing", "Dancing"),
                    ("twerking", "Twerking"), ("talking", "Talking to Camera"))


def categories(kind: str) -> tuple:
    return CATEGORIES + (VIDEO_CATEGORIES if kind == "video" else ()) + ((REVIEW, "Uncategorised / Needs Review"),)


def key(kind: str, slug: str) -> str:
    return f"{PREFIX}{kind}:{slug}"


def parse_key(value: str) -> tuple[str, str] | None:
    if not value.startswith(PREFIX):
        return None
    parts = value[len(PREFIX):].split(":")
    if len(parts) != 2 or parts[0] not in ("photo", "video"):
        return None
    return tuple(parts) if parts[1] in dict(categories(parts[0])) else None


def _words(value: Any) -> set[str]:
    if isinstance(value, str):
        parsed = load_json(value, None)
        value = parsed if isinstance(parsed, list) else re.split(r"[,\n]", value)
    return {str(v).strip().lower().replace("-", "_").replace(" ", "_")
            for v in value} if isinstance(value, (list, tuple)) else set()


def classify(item: Any) -> set[str]:
    """No guesses from filenames, absence of flags, or mere body-part presence.

Structured fields carry the strong evidence. Prose only refines settings absent
from the existing fixed menu, and is ignored in negated/uncertain clauses.
Manual folder decisions always win, including after Describe All is repeated.
"""
    kind = getattr(item, "kind", "")
    if kind not in ("photo", "video") or getattr(item, "removed_at", None):
        return set()
    value = lambda name, default=None: effective_value(item, name, default=default)
    manual = value("_standard_folders", {})
    manual = manual if isinstance(manual, dict) else {}
    described = getattr(item, "describe_status", None) == "described"
    out: set[str] = set()
    if described:
        j = value("_jev", {})
        j = j if isinstance(j, dict) else {}
        jt = j.get("tags") or {}
        yes = lambda name: jt.get(name) == "y"
        acts = _words(value("acts", []))
        focus = _words(value("body_focus", []))
        tags = _words(value("tags", []))
        camera, setting = value("camera"), value("setting")
        outfit, clothing = jt.get("outfit"), value("clothing_state")
        raw = " ".join(str(value(n, "") or "") for n in ("description", "video_description"))
        clauses = re.split(r"[.!?;\n]|\bbut\b", raw.lower())
        positive = " ".join(c for c in clauses if not re.search(
            r"\b(no|not|without|isn't|aren't|unclear|possibly|maybe|might|could|appears|seems)\b", c))
        has = lambda pattern: re.search(pattern, positive) is not None
        def add(slug: str, condition: Any) -> None:
            if condition:
                out.add(slug)

        add("mirror_selfie", camera == "mirror" or yes("mirror_selfie") or "mirror_selfie" in tags)
        add("selfie", "mirror_selfie" not in out and (camera == "handheld_selfie" or "selfie" in tags))
        add("cosplay", bool(tags & {"cosplay", "costume"}) or has(r"\b(?:cosplay|costume)\b"))
        add("bikini", "bikini" in tags or has(r"\b(?:wearing|in|wears) (?:a |an |\w+ ){0,3}bikini\b"))
        add("lingerie", clothing == "lingerie_on" or outfit == "lingerie_or_bodysuit" or "lingerie" in tags)
        add("see_through", yes("see_through") or "see_through" in tags)
        add("full_nude", clothing == "fully_nude" or outfit == "nude")
        bare_breasts = j.get("breasts_bare") == "y"
        add("topless", yes("topless") or bare_breasts or "topless" in tags)
        add("tits", bare_breasts and (yes("breasts_focus") or bool(focus & {"breasts", "nipples"})))
        butt_focus = yes("butt_focus") or "ass" in focus
        add("ass_bare", butt_focus and yes("butt_bare"))
        add("ass_covered", butt_focus and jt.get("butt_bare") == "n")
        add("feet", yes("feet_focus") or "feet" in focus or value("primary_folder") == "feet")
        add("pussy", j.get("crotch_bare") == "y" and (yes("crotch_focus") or bool(focus & {"pussy", "clit"})))
        add("toy_play", jt.get("toy") == "toy_touching_or_inserted" or bool(acts & {"toy_insertion", "toy_on_clit", "riding_toy"}))
        add("blowjob", "blowjob" in acts)
        add("handjob", "handjob" in acts)
        add("receiving_oral", bool(acts & {"receiving_oral", "cunnilingus"}) or bool(tags & {"receiving_oral", "cunnilingus"}))
        add("partner_sex", any(a.startswith("sex_") for a in acts) or value("penetration") == "penis")
        add("anal_play", bool(acts & {"anal", "anal_sex", "anal_play", "anal_insertion"}) or bool(tags & {"anal_play", "anal_sex", "anal_insertion"}))
        add("anal_display", "anus" in focus or "anal_display" in tags)
        solo = (value("people_count") == 1 or jt.get("people_count") == "one") and not value("partner_visible", False)
        add("solo_play", solo and not (out & {"partner_sex", "blowjob", "handjob", "receiving_oral"})
            and ("toy_play" in out or bool(acts & {"rubbing_clit", "fingering", "masturbation_orgasm", "squirt"})))
        add("bed", has(r"\b(?:on|in|across) (?:a |the |her )?bed\b") or "on_bed" in tags)
        add("shower", setting == "shower" or "shower" in acts or "shower" in tags)
        add("bath", "bath" in acts or bool(tags & {"bath", "bathtub"}) or has(r"\bin (?:a |the )?(?:bath|bathtub)\b"))
        add("beach", "beach" in tags or has(r"\b(?:at|on|along) (?:a |the )?beach\b"))
        add("pool", bool(tags & {"pool", "poolside", "swimming_pool"}) or has(r"\b(?:in|by|beside|at) (?:a |the )?(?:swimming )?pool\b"))
        add("outdoors", setting in ("outdoor", "outdoors") or jt.get("setting") == "outdoors")
        add("gym", jt.get("setting") == "gym" or bool(tags & {"gym", "fitness", "workout"}))
        add("car", setting == "car" or jt.get("setting") == "car")
        if kind == "video":
            add("striptease", bool(acts & {"strip", "undress"}))
            add("dancing", "dance" in acts or "dancing" in tags)
            add("twerking", bool(acts & {"twerk", "ass_shaking"}))
            add("talking", "talking_to_camera" in acts or value("primary_folder") == "talking_head")
        # SFW requires affirmative evidence; never infer it from missing analysis.
        add("casual", value("explicitness") == "sfw" and clothing == "dressed"
            and value("nsfw") is False and not (out & {"full_nude", "topless", "tits", "pussy", "toy_play", "partner_sex", "anal_play", "solo_play", "blowjob", "handjob", "receiving_oral", "ass_bare"}))
        confidence = value("confidence")
        if isinstance(confidence, (int, float)) and confidence < 70:
            out.clear()
        if j.get("lane5") == "review" or getattr(item, "review_state", None) == "rejected":
            out.clear()
    for slug, _ in categories(kind):
        decision = manual.get(key(kind, slug))
        if decision is True:
            out.add(slug)
        elif decision is False:
            out.discard(slug)
    if manual.get(key(kind, REVIEW)) is True:
        return {REVIEW}
    out.discard(REVIEW)
    # Pending media are not labelled at all until analysed or manually filed.
    return out or ({REVIEW} if described and manual.get(key(kind, REVIEW)) is not False else set())
