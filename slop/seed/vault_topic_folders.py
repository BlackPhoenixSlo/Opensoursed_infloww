from __future__ import annotations

import json
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_topic_items": (150, 600, 2_000)}
merge_sizes(SIZES)

MODEL, PROMPT_VERSION = "qwen3-vl-30b", "v2"
JEV_V = "v8+nn.10"  # service/vault_jev_rules.VERSION
JEV_VV = "jv1"

# G/G and butt plug are not offered (no signal).
TOPICS = {
    "heels_stockings": ("heels & stockings", "split", {"wears_heels": "y"}, {}),
    "butt_tease": ("butt tease", "split", {"butt_focus": "y"}, {}),
    "butt_bare": ("butt bare", "split", {"butt_bare": "y", "facing": "away"}, {}),
    "boobs_closeup": ("boobs close-up", "split", {"breasts_focus": "y", "framing": "body_part_close_up"}, {}),
    "see_through": ("see-through", "split", {"see_through": "y"}, {}),
    "spread": ("spread", "split", {"legs_spread": "y"}, {}),
    "bent_over": ("bent over", "split", {"pose": "all_fours_or_bent_over"}, {}),
    "toy_tease": ("toy tease", "split", {"toy": "toy_visible_not_in_use"}, {}),
    "toy_play": ("toy play", "explicit", {"toy": "toy_touching_or_inserted"}, {}),
    "with_partner": ("with partner", "split", {"people_count": "two_or_more"}, {}),
    "faceless": ("faceless", "split", {"face_visible": "no_face"}, {}),
    "mirror_selfies": ("mirror selfies", "split", {"mirror_selfie": "y"}, {}),
    "good_morning": ("good morning", "free",
                     {"smiling": "y", "looking_at_camera": "y", "outfit": "everyday_clothes"}, {}),
    "bikini": ("bikini", "split", {"outfit": "swimwear"}, {}),
    "shower_bath": ("shower & bath", "split", {"setting": "bathroom"}, {}),
    "outdoors_car": ("outdoors & car", "split", {"setting": "outdoors"}, {}),
    "lips_tongue": ("lips & tongue", "split", {"tongue_out": "y"}, {}),
    "clean_promo": ("clean for promo", "free", {"added_text": "nothing_added"}, {}),
    "nude": ("nudes", "split", {"outfit": "nude"}, {}),
    "tits": ("tits", "split", {"topless": "y"}, {}),
    "pussy": ("pussy", "split", {}, {}),
    "masturbation": ("masturbation", "explicit", {}, {"acts": ["fingering"]}),
    "blowjob": ("blowjob", "explicit", {}, {"acts": ["blowjob"]}),
    "sex": ("sex", "explicit", {}, {"primary_folder": "sex_with_partner"}),
    "clothed_tease": ("clothed tease", "free", {"outfit": "lingerie_or_bodysuit"}, {}),
    "dance_strip": ("dance & strip", "split", {}, {"acts": ["twerking"]}),
    "gym_yoga": ("gym & yoga", "split", {"setting": "gym"}, {}),
}
NOUL = ("wears_heels", "wears_stockings_or_fishnets", "butt_focus", "butt_bare", "breasts_focus", "see_through",
        "nipple_through_fabric", "legs_spread", "mirror_selfie", "smiling", "looking_at_camera", "feet_in_water",
        "mouth_tease", "tongue_out", "watermark", "censor_edit", "phone_visible", "multi_panel", "topless",
        "self_touch")
BASE_CHOICE = {"people_count": "one", "added_text": "caption", "toy": "no_toy", "outfit": "lingerie",
               "setting": "living_room", "pose": "standing", "framing": "full_body", "face_visible": "face_visible",
               "facing": "toward"}
PRICES = ("free", "$10", "$50", "$100")
EXPLICIT_OF = {"$10": "$50", "$50": "$100", "$100": "$150"}
CLOTHED = ("everyday_clothes", "lingerie_or_bodysuit", "swimwear")
BARE = {"free": ("n", "n", "n"), "$10": ("y", "n", "n"), "$50": ("y", "y", "n"), "$100": ("y", "y", "y"),
        "review": ("unsure", "n", "n")}
GUARD = (("unsure", "n", "n"), ("n", "unsure", "n"), ("n", "n", "unsure"), ("y", "n", "n"))
# No topic folder for any feet class: feet live in the vault's Feet pack only.
FEET_CLASSES = {
    "tease": (0.8, "socks", "free", BARE["free"]),
    "nude": (0.8, "bare", "free", BARE["free"]),
    "body": (0.8, "socks", "$10", BARE["$10"]),
    "edge": (0.6, "socks", "free", BARE["free"]),
    "low": (0.59, "socks", "free", BARE["free"]),
    "unsafe": (0.9, "socks", "free", ("unsure", "n", "n")),
    "unsafe_y": (0.9, "socks", "free", ("y", "n", "n")),
}
LANES = {"tits": ("$10", "$50", "$100"), "pussy": ("$50", "$100")}


def allowed(slug: str) -> tuple[str, ...]:
    kind = TOPICS[slug][1]
    return LANES.get(slug) or {"split": PRICES, "explicit": PRICES[1:], "free": PRICES[:1]}[kind]


def price(slug: str, lane: str) -> str:
    return EXPLICIT_OF[lane] if TOPICS[slug][1] == "explicit" else lane


def _body(tags: dict, lane: str, bare: tuple[str, str, str], review_clip: bool,
          partner_fields: bool = False) -> set[tuple[str, str]]:
    bb, cb, pen = bare
    if lane == "free":
        ok = bare == BARE["free"] and not review_clip and tags.get("outfit") in CLOTHED
        return {("clothed_tease", "free")} if ok else set()
    out = set()
    if bb == "y" and "y" in (tags.get("breasts_focus"), tags.get("topless")):
        out.add(("tits", lane))
    if cb == "y":
        out.add(("pussy", lane))
    partner = tags.get("people_count") == "two_or_more" or partner_fields
    if pen == "y" and tags.get("toy") == "no_toy" and not partner:
        out.add(("masturbation", EXPLICIT_OF[lane]))
    return out


def _tags(slug: str) -> dict:
    return {**BASE_CHOICE, **{q: "n" for q in NOUL}, **TOPICS[slug][2]}


def _jev(slug: str, lane5: str, bare: tuple[str, str, str], v: str = JEV_V, status: str = "ok") -> dict:
    tags = _tags(slug)
    bb, cb, pen = bare
    return {"v": v, "status": status, "state": {}, "lane5": lane5, "lane": lane5, "breasts_bare": bb, "crotch_bare": cb,
            "penetration": pen, "nn": {}, "tags": tags, "P": {q: (0.95 if tags[q] == "y" else 0.02) for q in NOUL}}


def _clip_jev(slug: str, lane: str, bare: tuple[str, str, str], review: bool) -> dict:
    j = {**_jev(slug, lane, bare), "kind": "video", "vv": JEV_VV, "frame": 0, "frames": [], "src": "720",
         "review": "few_frames" if review else None, "bytes": 0}
    if review:
        j.update(lane5="review", read_lane5=lane)
    return j


def _feet_jev(feet_subject: float, detail: str, lane5: str, bare: tuple[str, str, str]) -> dict:
    tags = {**BASE_CHOICE, **{q: "n" for q in NOUL}, "feet_any": "y", "feet_focus": "y", "feet_detail": detail}
    bb, cb, pen = bare
    return {"v": JEV_V, "status": "ok", "state": {}, "lane5": lane5, "lane": lane5, "breasts_bare": bb,
            "crotch_bare": cb, "penetration": pen, "nn": {}, "feet_subject": feet_subject, "tags": tags,
            "P": {**{q: 0.02 for q in NOUL}, "feet_focus": feet_subject, "soles_visible": 0.0,
                  "bare_toes_visible": 0.0}}


CLIPS = {"clip": False, "clip_review_paid": True, "clip_review_free": True}


def _classes() -> list[tuple]:
    split = [s for s, t in TOPICS.items() if t[1] == "split"]
    out: list[tuple] = [("hit", s, p, BARE[p], None) for s in TOPICS for p in allowed(s)]
    out += [("guard", split[k % len(split)], "free", g, None) for k, g in enumerate(GUARD)]
    out += [("guard", s, "free", GUARD[k % len(GUARD)], None) for k, s in enumerate(("bikini", "spread"))]
    out += [("wrong", "good_morning", "$10", BARE["$10"], None), ("wrong", "clean_promo", "$10", BARE["$10"], None),
            ("wrong", "clothed_tease", "$10", BARE["$10"], None), ("wrong", "toy_play", "free", BARE["free"], None),
            ("wrong", "blowjob", "free", BARE["free"], None)]
    out += [("review", s, "review", BARE["review"], None) for s in ("bikini", "spread", "faceless")]
    out += [("stale", "bikini", "free", BARE["free"], "v7"), ("stale", "spread", "$10", BARE["$10"], "failed")]
    out += [("nojev", None, None, None, None), ("clip", "spread", "$50", BARE["$50"], None),
            ("clip_review_paid", "bikini", "$10", BARE["$10"], None),
            ("clip_review_free", "bikini", "free", BARE["free"], None)]
    out += [("feet", None, None, None, k) for k in FEET_CLASSES]
    return out


def seed(w: World, creator: dict, n: int) -> dict:
    rng = w.rng("vault_topic_folders")
    aid = creator["id"]
    base = _classes()
    n = max(n, len(base))
    classes = base + [rng.choice(base) for _ in range(n - len(base))]
    rng.shuffle(classes)
    ids = sorted(rng.sample(range(4_300_000_000, 5_900_000_000), n))
    t0 = w.now - timedelta(days=20)
    out: dict = {"account_id": aid, "want": {}, "want_unsplit": {}, "none": {}, "bare": [], "items": 0,
                 "with_jev": 0}
    rows = []
    for k, (mid, (cls, slug, lane5, bare, extra)) in enumerate(zip(ids, classes)):
        video = cls in CLIPS
        explicit = lane5 in ("$10", "$50", "$100")
        fields: dict = {"description": f"Solo still {k}", "tags": ["bed", "tease"], "_prompt_version": PROMPT_VERSION,
                        "_frames": 6 if video else 1, "explicitness": "explicit" if explicit else "suggestive",
                        "clothing_state": "fully_nude" if explicit else "lingerie_on"}
        if cls == "feet":
            fs, detail, lane5, bare = FEET_CLASSES[extra]
            fields["_jev"] = _feet_jev(fs, detail, lane5, bare)
            explicit = lane5 != "free"
            fields.update(explicitness="explicit" if explicit else "suggestive",
                          clothing_state="fully_nude" if explicit else "lingerie_on")
        elif slug is not None:
            fields.update(TOPICS[slug][3])
            if video:
                j = _clip_jev(slug, lane5, bare, CLIPS[cls])
            else:
                j = _jev(slug, lane5, bare)
            if extra == "v7":
                j["v"] = "v7+nn.9"
            elif extra == "failed":
                j["status"] = "failed"
            fields["_jev"] = j
        out["items"] += 1
        out["with_jev"] += cls not in ("nojev", "stale")
        if bare and bare != ("n", "n", "n"):
            out["bare"].append(mid)
        placed: set[tuple[str, str]] = set()
        if cls in ("hit", "clip", "clip_review_paid"):
            placed = {(slug, price(slug, lane5))} | _body(_tags(slug), lane5, bare, cls == "clip_review_paid", slug == "sex")
        elif cls in ("wrong", "guard", "clip_review_free"):
            placed = _body(_tags(slug), lane5, bare, cls == "clip_review_free", slug == "sex")
        if placed:
            out["want"][mid] = sorted(f"AI-{TOPICS[s][0]} {p}" for s, p in placed)
            out["want_unsplit"][mid] = sorted({f"AI-{TOPICS[s][0]}" for s, _ in placed})
        else:
            out["none"].setdefault(cls, []).append(mid)
        at = t0 + timedelta(minutes=41 * k)
        raw = {"id": mid, "type": "video" if video else "photo", "convertedToVideo": False, "canView": True,
               "hasError": False, "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "isReady": True,
               **({"duration": 30} if video else {}), "listStates": []}
        desc = fields["description"]
        rows.append({
            "account_id": aid, "media_id": mid, "kind": raw["type"], "duration_seconds": 30 if video else None,
            "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now),
            "of_folder_ids": "[]", "search_text": " ".join([desc, *fields["tags"]]).lower(),
            "tags": json.dumps(fields["tags"]), "last_seen_run_id": None, "content_hash": None,
            "content_hash_kind": None, "send_count": 0, "last_sent_at": None, "removed_at": None,
            "description": None if video else desc, "video_description": desc if video else None,
            "describe_status": "described", "describe_model": MODEL, "describe_generated_at": ts(w.now),
            "ai_fields_json": json.dumps(fields), "of_terms": None, "explicitness_tier": fields["explicitness"],
            "frames_sampled": 6 if video else None})
    con = w.sql()
    with con:
        cols = list(rows[0])
        con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
        con.execute("INSERT OR IGNORE INTO account_ai_config (account_id, utc_offset, daily_cost_cap_cents)"
                    " VALUES (?, 0, 100)", (aid,))
    con.close()
    out["want_names"] = sorted({n for ns in out["want"].values() for n in ns})
    out["want_unsplit_names"] = sorted({n for ns in out["want_unsplit"].values() for n in ns})
    w.data["vault_topic_folders"] = out
    return out
