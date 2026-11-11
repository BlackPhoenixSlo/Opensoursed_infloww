"""A described vault the flags pass reached only part of (scenarios/2026-11-10-vault-ai-folders-partial-flags.py):
`vault_items` rows by SQL for one Creator, as Collect + the describe pass (+ the flags pass on some) leave them
(columns as seed/vault_items.py writes them). Each photo is planted in one class, so the AI folder plan's paid
lanes have an exact oracle:

  ten        explicit, flagged: breasts bare, vulva / anus not in frame, underwear on    -> AI-tease 10
  fifty      explicit, flagged: vulva + breasts bare, no underwear, fully_nude          -> AI-tease 50
  ten_raw    explicit, NO flags, clothing_state partially_off (a $10 by its describe)    -> explicit 1:1 only
  fifty_raw  explicit, NO flags, clothing_state fully_nude (a $50 by its describe)       -> explicit 1:1 only
  soft       suggestive, flagged on half (all covered / out of frame)                    -> stories / mass
plus explicit videos (-> clips). Sizes: SIZES `vault_ai_items` (photos + videos per Creator), merged on import.

`seed(w, creator, n)` -> (and `w.data["vault_flags_partial"]`) {"account_id", "ten", "fifty", "ten_raw",
"fifty_raw", "soft", "videos": [media ids], "stills": photos, "flagged": flagged photos}. Randomness only from
`w.rng("vault_flags_partial")`."""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_ai_items": (60, 400, 2_000)}
merge_sizes(SIZES)

MODEL, PROMPT_VERSION, FLAGS_VERSION = "qwen3-vl-30b", "v2", 3   # as seed/vault_items.py
MIX = (("ten", 0.15), ("fifty", 0.15), ("ten_raw", 0.12), ("fifty_raw", 0.12), ("soft", 0.26), ("video", 0.20))


def _fields(cls: str, flag: bool, k: int) -> dict:
    tags = ["bed", "pink", "tease"]
    base = {"description": f"Solo {cls} still {k}", "tags": tags, "_prompt_version": PROMPT_VERSION, "_frames": 1}
    if cls in ("ten", "ten_raw"):
        base.update(explicitness="explicit", clothing_state="partially_off")
    elif cls in ("fifty", "fifty_raw"):
        base.update(explicitness="explicit", clothing_state="fully_nude")
    elif cls == "soft":
        base.update(explicitness="suggestive", clothing_state="lingerie_on")
    else:
        base.update(explicitness="explicit", clothing_state="fully_nude", _frames=6)
    if not flag:
        return base
    regions = {"ten": {"breasts_vis": "bare", "vulva_vis": "not_in_frame", "anus_vis": "not_in_frame"},
               "fifty": {"breasts_vis": "bare", "vulva_vis": "bare", "anus_vis": "not_in_frame"},
               "soft": {"breasts_vis": "covered", "vulva_vis": "covered", "anus_vis": "not_in_frame"},
               "video": {"breasts_vis": "bare", "vulva_vis": "bare", "anus_vis": "not_in_frame"}}[cls]
    base.update(regions, underwear_visible=cls in ("ten", "soft"), _flags_model=MODEL, _flags_v=FLAGS_VERSION)
    if cls == "soft":
        base.update(over_breasts="black lace bra", over_vulva="pink lace thong")
    return base


def seed(w: World, creator: dict, n: int) -> dict:
    rng = w.rng("vault_flags_partial")
    aid = creator["id"]
    names, weights = zip(*MIX)
    classes = [rng.choices(names, weights)[0] for _ in range(n)]
    for i, c in enumerate(names):   # every class at least twice
        classes[2 * i:2 * i + 2] = [c, c]
    rng.shuffle(classes)
    ids = sorted(rng.sample(range(2_500_000_000, 4_200_000_000), n))
    t0 = w.now - timedelta(days=30)
    out: dict = {"account_id": aid, "ten": [], "fifty": [], "ten_raw": [], "fifty_raw": [], "soft": [],
                 "videos": [], "stills": 0, "flagged": 0}
    rows = []
    for k, (mid, cls) in enumerate(zip(ids, classes)):
        video = cls == "video"
        flag = cls in ("ten", "fifty") or (cls == "soft" and rng.random() < 0.5) or video
        fields = _fields(cls, flag, k)
        at = t0 + timedelta(minutes=37 * k)
        created = at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        raw = {"id": mid, "type": "video" if video else "photo", "convertedToVideo": False, "canView": True,
               "hasError": False, "createdAt": created, "isReady": True, **({"duration": 30} if video else {}),
               "listStates": []}
        desc = fields["description"]
        rows.append({
            "account_id": aid, "media_id": mid, "kind": raw["type"], "duration_seconds": 30 if video else None,
            "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now),
            "of_folder_ids": "[]", "search_text": " ".join([desc, *fields["tags"], fields["clothing_state"]]).lower(),
            "tags": json.dumps(fields["tags"]), "last_seen_run_id": None, "content_hash": None,
            "content_hash_kind": None, "send_count": 0, "last_sent_at": None, "removed_at": None,
            "description": None if video else desc, "video_description": desc if video else None,
            "describe_status": "described", "describe_model": MODEL, "describe_generated_at": ts(w.now),
            "ai_fields_json": json.dumps(fields), "of_terms": None, "explicitness_tier": fields["explicitness"],
            "frames_sampled": 6 if video else None})
        if video:
            out["videos"].append(mid)
        else:
            out[cls].append(mid)
            out["stills"] += 1
            out["flagged"] += flag
    con = w.sql()
    with con:
        cols = list(rows[0])
        con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
    con.close()
    w.data["vault_flags_partial"] = out
    return out
