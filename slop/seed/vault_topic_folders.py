"""A Jev-classified vault for Build AI folders' "Topic folders (Jev)" (scenarios/2026-11-12-vault-topic-folders.py):
`vault_items` rows by SQL for one Creator (columns as seed/vault_flags_partial.py writes them), each photo's
`ai_fields_json["_jev"]` a Jev v8 blob as `vault_jev_rules.blob` stores it (v, status, lane5, lane, the three
bare answers, `tags`, `P`) (Jev is on for every Creator since #511). Every photo is planted in one class, so the topic folders have an exact oracle written from the planted
answers, not from the product's rules:

  hit       one topic's answers only (BASE hits no topic), at one lane5 the topic allows:
            free (all three "n") / $10 (breasts y) / $50 (crotch y) / $100 (penetration y)   -> AI-<name> <lane5>
  guard     lane5 free but breasts / crotch / penetration "unsure" or breasts "y", on a split topic -> no topic folder
  wrong     a free-only topic (good morning, clean for promo) at a paid lane5, toy play at free  -> no topic folder
  review    lane5 "review" on a split topic                                                         -> none
  stale     an older Jev version / a failed Jev, on a split topic                                   -> none
  nojev     no `_jev` at all                                                                        -> none
  video     a clip carrying a hit's `_jev` (topic folders are photos only)                         -> none
  feet      the "Feet" group (its own slug `feet`, not in TOPICS): Jev feet answers on a BASE photo (hits no other
            topic); the folder is the feet pack's preselect rung (feet score >= .6, written here, not imported):
              tease     feet_subject .8, socks, lane5 free, body "n"                   -> AI-feet tease
              nude      feet_subject .8, bare, lane5 free, body "n"                    -> AI-feet nude
              body      feet_subject .8, socks, lane5 $50 (breasts + crotch y)         -> AI-feet nude-body
              edge      feet_subject .6 exactly (the gate), socks, free                -> AI-feet tease
              low       feet_subject .59, socks, free                                  -> none (below .6)
              unsafe    feet_subject .9, socks, lane5 free BUT breasts unsure / y      -> none (free guard)
Every (topic, allowed price) hit and every other class is planted at least once; the rest is random.
Sizes: SIZES `vault_topic_items` (items per Creator), merged on import.

`seed(w, creator, n)` -> (and `w.data["vault_topic_folders"]`) {"account_id", "want": {media_id: folder name}
for hits, "none": {class: [ids]}, "bare": [ids whose bare answers are not all "n"], "photos", "with_jev",
"feet": {media_id: AI-feet folder name or None}, "feet_unsafe": [ids]}.
Randomness only from `w.rng("vault_topic_folders")`.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_topic_items": (150, 600, 2_000)}
merge_sizes(SIZES)

MODEL, PROMPT_VERSION = "qwen3-vl-30b", "v2"   # as seed/vault_items.py
JEV_V = "v8+nn.10"                             # service/vault_jev_rules.VERSION

# Topic slug -> (folder name, price kind, the answers that make it a hit). Written from the spec, not imported.
TOPICS = {
    "heels_stockings": ("heels & stockings", "split", {"wears_heels": "y"}),
    "butt_tease": ("butt tease", "split", {"butt_focus": "y"}),
    "butt_bare": ("butt bare", "split", {"butt_bare": "y", "facing": "away"}),
    "boobs_closeup": ("boobs close-up", "split", {"breasts_focus": "y", "framing": "body_part_close_up"}),
    "see_through": ("see-through", "split", {"see_through": "y"}),
    "spread": ("spread", "split", {"legs_spread": "y"}),
    "bent_over": ("bent over", "split", {"pose": "all_fours_or_bent_over"}),
    "toy_tease": ("toy tease", "split", {"toy": "toy_visible_not_in_use"}),
    "toy_play": ("toy play", "paid", {"toy": "toy_touching_or_inserted"}),
    "with_partner": ("with partner", "split", {"people_count": "two_or_more"}),
    "faceless": ("faceless", "split", {"face_visible": "no_face"}),
    "mirror_selfies": ("mirror selfies", "split", {"mirror_selfie": "y"}),
    "good_morning": ("good morning", "free", {"smiling": "y", "looking_at_camera": "y", "outfit": "everyday_clothes"}),
    "bikini": ("bikini", "split", {"outfit": "swimwear"}),
    "shower_bath": ("shower & bath", "split", {"setting": "bathroom"}),
    "outdoors_car": ("outdoors & car", "split", {"setting": "outdoors"}),
    "lips_tongue": ("lips & tongue", "split", {"tongue_out": "y"}),
    "clean_promo": ("clean for promo", "free", {"added_text": "nothing_added"}),
}
NOUL = ("wears_heels", "wears_stockings_or_fishnets", "butt_focus", "butt_bare", "breasts_focus", "see_through",
        "nipple_through_fabric", "legs_spread", "mirror_selfie", "smiling", "looking_at_camera", "feet_in_water",
        "mouth_tease", "tongue_out", "watermark", "censor_edit", "phone_visible", "multi_panel")
# Hits no topic: one person, face shown, facing the camera, standing, no toy, lingerie in the living room, a caption.
BASE_CHOICE = {"people_count": "one", "added_text": "caption", "toy": "no_toy", "outfit": "lingerie",
               "setting": "living_room", "pose": "standing", "framing": "full_body", "face_visible": "face_visible",
               "facing": "toward"}
PRICES = ("free", "$10", "$50", "$100")
BARE = {"free": ("n", "n", "n"), "$10": ("y", "n", "n"), "$50": ("y", "y", "n"), "$100": ("y", "y", "y"),
        "review": ("unsure", "n", "n")}
GUARD = (("unsure", "n", "n"), ("n", "unsure", "n"), ("n", "n", "unsure"), ("y", "n", "n"))
FEET = "feet"   # the Feet group's slug (service/vault_topic_folders.py), apart from TOPICS
# feet class -> (feet_subject, feet_detail, lane5, bare answers, the folder). Gate .6: the pack picker's preselect.
FEET_CLASSES = {
    "tease": (0.8, "socks", "free", BARE["free"], "AI-feet tease"),
    "nude": (0.8, "bare", "free", BARE["free"], "AI-feet nude"),
    "body": (0.8, "socks", "$50", BARE["$50"], "AI-feet nude-body"),
    "edge": (0.6, "socks", "free", BARE["free"], "AI-feet tease"),
    "low": (0.59, "socks", "free", BARE["free"], None),
    "unsafe": (0.9, "socks", "free", ("unsure", "n", "n"), None),
    "unsafe_y": (0.9, "socks", "free", ("y", "n", "n"), None),
}
FEET_NAMES = ("AI-feet tease", "AI-feet nude", "AI-feet nude-body")


def allowed(kind: str) -> tuple[str, ...]:
    return {"split": PRICES, "paid": PRICES[1:], "free": PRICES[:1]}[kind]


def _jev(slug: str, lane5: str, bare: tuple[str, str, str], v: str = JEV_V, status: str = "ok") -> dict:
    tags = {**BASE_CHOICE, **{q: "n" for q in NOUL}, **TOPICS[slug][2]}
    bb, cb, pen = bare
    return {"v": v, "status": status, "state": {}, "lane5": lane5, "lane": lane5, "breasts_bare": bb, "crotch_bare": cb,
            "penetration": pen, "nn": {}, "tags": tags, "P": {q: (0.95 if tags[q] == "y" else 0.02) for q in NOUL}}


def _feet_jev(feet_subject: float, detail: str, lane5: str, bare: tuple[str, str, str]) -> dict:
    """A BASE photo (no other topic) with Jev's feet answers (`vault_jev_rules.blob`: feet_subject, P, tags)."""
    tags = {**BASE_CHOICE, **{q: "n" for q in NOUL}, "feet_any": "y", "feet_focus": "y", "feet_detail": detail}
    bb, cb, pen = bare
    return {"v": JEV_V, "status": "ok", "state": {}, "lane5": lane5, "lane": lane5, "breasts_bare": bb,
            "crotch_bare": cb, "penetration": pen, "nn": {}, "feet_subject": feet_subject, "tags": tags,
            "P": {**{q: 0.02 for q in NOUL}, "feet_focus": feet_subject, "soles_visible": 0.0,
                  "bare_toes_visible": 0.0}}


def _classes() -> list[tuple]:
    """Every planted class once: (class, slug, lane5, bare, extra)."""
    split = [s for s, t in TOPICS.items() if t[1] == "split"]
    out: list[tuple] = [("hit", s, p, BARE[p], None) for s, t in TOPICS.items() for p in allowed(t[1])]
    out += [("guard", split[k % len(split)], "free", g, None) for k, g in enumerate(GUARD)]
    out += [("guard", s, "free", GUARD[k % len(GUARD)], None) for k, s in enumerate(("bikini", "spread"))]
    out += [("wrong", "good_morning", "$10", BARE["$10"], None), ("wrong", "clean_promo", "$50", BARE["$50"], None),
            ("wrong", "toy_play", "free", BARE["free"], None)]
    out += [("review", s, "review", BARE["review"], None) for s in ("bikini", "spread", "faceless")]
    out += [("stale", "bikini", "free", BARE["free"], "v7"), ("stale", "spread", "$10", BARE["$10"], "failed")]
    out += [("nojev", None, None, None, None), ("video", "spread", "$50", BARE["$50"], None)]
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
    out: dict = {"account_id": aid, "want": {}, "none": {}, "bare": [], "photos": 0, "with_jev": 0, "feet": {},
                 "feet_unsafe": []}
    rows = []
    for k, (mid, (cls, slug, lane5, bare, extra)) in enumerate(zip(ids, classes)):
        video = cls == "video"
        explicit = lane5 in ("$10", "$50", "$100")
        fields: dict = {"description": f"Solo still {k}", "tags": ["bed", "tease"], "_prompt_version": PROMPT_VERSION,
                        "_frames": 6 if video else 1, "explicitness": "explicit" if explicit else "suggestive",
                        "clothing_state": "fully_nude" if explicit else "lingerie_on"}
        if cls == "feet":
            fs, detail, lane5, bare, folder = FEET_CLASSES[extra]
            fields["_jev"] = _feet_jev(fs, detail, lane5, bare)
            out["feet"][mid] = folder
            if extra.startswith("unsafe"):
                out["feet_unsafe"].append(mid)
            explicit = lane5 != "free"
            fields.update(explicitness="explicit" if explicit else "suggestive",
                          clothing_state="fully_nude" if explicit else "lingerie_on")
        elif slug is not None:
            j = _jev(slug, lane5, bare)
            if extra == "v7":
                j["v"] = "v7+nn.9"
            elif extra == "failed":
                j["status"] = "failed"
            fields["_jev"] = j
        if not video:
            out["photos"] += 1
            out["with_jev"] += cls not in ("nojev", "stale")
            if bare and bare != ("n", "n", "n"):
                out["bare"].append(mid)
        if cls == "hit":
            name, kind, _ = TOPICS[slug]
            out["want"][mid] = f"AI-{name} {lane5}"
        elif cls != "feet":
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
    out["want_names"] = sorted(set(out["want"].values()))
    w.data["vault_topic_folders"] = out
    return out
