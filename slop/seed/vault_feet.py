from __future__ import annotations

import json
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_feet_items": (300, 2_000, 12_000)}
merge_sizes(SIZES)

MODEL, PROMPT_VERSION, FLAGS_VERSION = "qwen3-vl-30b", "v2", 3
MIX = (("tease", 0.04), ("bare", 0.04), ("ten", 0.025), ("fifty", 0.025), ("raw_nude", 0.02), ("raw_socks", 0.015),
       ("raw_bare", 0.015), ("measured", 0.015), ("jev_free", 0.015), ("jev_paid", 0.015),
       ("jev_unsure", 0.015), ("jev_review", 0.015), ("jev_soles", 0.015), ("jev_maybe", 0.015),
       ("jev_video", 0.015), ("bystander", 0.13), ("mention", 0.09), ("ambiguous", 0.05), ("measured_no", 0.015),
       ("jev_absent", 0.015), ("jev_floor", 0.015), ("jev_low", 0.015), ("filler", 0.415))
KEEPERS = {"measured": ("tease", 0), "jev_free": ("tease", 0), "jev_paid": ("nude-body", 50),
           "jev_unsure": (None, None), "jev_review": (None, None), "jev_soles": ("nude", 0)}
POSSIBLE = {"jev_maybe": ("tease", 0), "jev_floor": ("tease", 0)}
BELOW_FLOOR = ("jev_low", "measured_no")
NO_JEV = ("tease", "bare", "ten", "fifty", "raw_nude", "raw_socks", "raw_bare")
VIDEO = ("jev_video",)
PRESELECT = ("measured", "jev_free", "jev_paid", "jev_soles")
JEV_UNSAFE = ("jev_unsure", "jev_review")
JEV_V = "v8+nn.10"
FILED_P = 0.08
FILED_FOLDER = "feet-nude"
FREE_FOLDER = "feet-tease"
PRE_RULE = ("tease", "jev_video")

_COVERED = {"breasts_vis": "covered", "vulva_vis": "covered", "anus_vis": "not_in_frame"}
_OUT = {"breasts_vis": "not_in_frame", "vulva_vis": "not_in_frame", "anus_vis": "not_in_frame"}


def _jev(feet_subject: float, lane5: str = "free", detail: str = "socks", *, soles: float = 0.0, toes: float = 0.0,
         seen: str = "y", **body: str) -> dict:
    return {"v": JEV_V, "status": "ok", "lane5": lane5, "lane": lane5, "settled": False,
            **{"breasts_bare": "n", "crotch_bare": "n", "penetration": "n", **body},
            "feet_subject": feet_subject,
            "P": {"feet_focus": feet_subject, "soles_visible": soles, "bare_toes_visible": toes},
            "tags": {"feet_detail": detail, "feet_any": seen, "feet_focus": "y" if feet_subject >= 0.4 else "n",
                     "soles_visible": "y" if soles >= 0.4 else "n", "bare_toes_visible": "y" if toes >= 0.55 else "n"}}


def _fields(cls: str, k: int) -> dict:
    f: dict = {"_prompt_version": PROMPT_VERSION, "_frames": 1, "acts": [], "partner_visible": False}
    flags: dict | None = None
    if cls == "tease":
        f.update(primary_folder="feet", body_focus=["feet"], tags=["feet", "socks", "bed"],
                 clothing_items=["white socks", "hoodie"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Close-up of her soles in white socks on the bed ({k})")
        flags = {**_COVERED, "over_breasts": "grey hoodie", "over_vulva": "grey hoodie"}
    elif cls == "bare":
        f.update(primary_folder="legs", body_focus=["feet", "legs"], tags=["barefoot", "couch"],
                 clothing_items=["jeans", "t-shirt"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Bare feet with painted toes stretched out on the couch ({k})")
        flags = {**_COVERED, "over_breasts": "white t-shirt", "over_vulva": "blue jeans"}
    elif cls == "ten":
        f.update(primary_folder="topless", body_focus=["feet", "breasts"], tags=["soles", "topless"],
                 clothing_items=["panties"], clothing_state="partially_off", explicitness="explicit",
                 description=f"Soles up to the camera while lying topless ({k})")
        flags = {"breasts_vis": "bare", "vulva_vis": "covered", "anus_vis": "not_in_frame",
                 "over_vulva": "black panties", "underwear_visible": True}
    elif cls == "fifty":
        f.update(primary_folder="feet", body_focus=["feet", "vulva"], tags=["feet", "nude"],
                 clothing_items=[], clothing_state="fully_nude", explicitness="explicit",
                 description=f"Nude, soles and toes toward the lens on white sheets ({k})")
        flags = {"breasts_vis": "bare", "vulva_vis": "bare", "anus_vis": "bare"}
    elif cls == "raw_nude":
        f.update(primary_folder="feet", body_focus=["feet"], tags=["feet", "nude"],
                 clothing_items=[], clothing_state="fully_nude", explicitness="explicit",
                 description=f"Nude on the rug, toes pointed at the camera ({k})")
    elif cls == "raw_socks":
        f.update(primary_folder="feet", body_focus=["feet"], tags=["feet", "socks"],
                 clothing_items=["white socks", "hoodie"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Soles in white socks up on the desk ({k})")
    elif cls == "raw_bare":
        f.update(primary_folder="feet", body_focus=["feet", "legs"], tags=["feet", "barefoot"],
                 clothing_items=["lace thong"], clothing_state="lingerie_on", explicitness="suggestive",
                 description=f"Bare feet crossed on the bed in a lace thong ({k})")
    elif cls == "measured":
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "pantyhose"],
                 clothing_items=["black pantyhose", "skirt"], clothing_state="fully_clothed",
                 explicitness="suggestive", description=f"Legs crossed in black pantyhose on a chair ({k})",
                 _jev=_jev(0.95, detail="stockings_fishnets_nylons"))
        flags = {**_COVERED, "over_breasts": "white blouse", "over_vulva": "black skirt"}
    elif cls == "jev_free":
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "socks"],
                 clothing_items=["white socks", "shorts"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Legs up on the sofa in white socks ({k})", _jev=_jev(0.92))
    elif cls == "jev_paid":
        f.update(primary_folder="feet", body_focus=["feet"], tags=["feet", "socks"],
                 clothing_items=["white socks", "blanket"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Soles in white socks under a blanket ({k})",
                 _jev=_jev(0.9, "$50", soles=0.8, crotch_bare="y"))
        flags = {**_COVERED, "over_breasts": "grey blanket", "over_vulva": "grey blanket"}
    elif cls == "jev_unsure":
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "socks"],
                 clothing_items=["white socks", "shirt"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Legs up in white socks on the bed ({k})",
                 _jev=_jev(0.9, soles=0.7, breasts_bare="unsure"))
        flags = {**_COVERED, "over_breasts": "white shirt", "over_vulva": "white shirt"}
    elif cls == "jev_review":
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "socks"],
                 clothing_items=["black socks"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Legs crossed in black socks on the sofa ({k})", _jev=_jev(0.88, "review"))
    elif cls == "jev_soles":
        f.update(primary_folder="legs", body_focus=["legs"], tags=["legs", "bed"],
                 clothing_items=["shorts"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Lying on the bed with her legs up to the lens ({k})",
                 _jev=_jev(0.85, detail="bare", soles=0.9, toes=0.8))
        flags = {**_COVERED, "over_breasts": "grey top", "over_vulva": "grey shorts"}
    elif cls == "jev_maybe":
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "socks"],
                 clothing_items=["grey socks", "joggers"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Curled up on the sofa in grey socks ({k})", _jev=_jev(0.55))
        flags = {**_COVERED, "over_breasts": "grey hoodie", "over_vulva": "grey joggers"}
    elif cls in ("jev_floor", "jev_low"):
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "socks"],
                 clothing_items=["white socks", "shorts"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Sitting on the rug in white socks ({k})",
                 _jev=_jev(0.30 if cls == "jev_floor" else 0.29))
        flags = {**_COVERED, "over_breasts": "white tee", "over_vulva": "grey shorts"}
    elif cls == "jev_video":
        f.update(primary_folder="feet", body_focus=["feet"], tags=["feet", "socks", "video"],
                 clothing_items=["white socks"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Video: wiggling her toes in white socks on the bed ({k})",
                 _jev={**_jev(0.95, soles=0.8), "kind": "video", "vv": 1, "frame": 3, "frames": [], "src": "720",
                       "review": None})
        flags = {**_COVERED, "over_breasts": "grey hoodie", "over_vulva": "grey hoodie"}
    elif cls == "jev_absent":
        f.update(primary_folder="selfie", body_focus=["face", "feet"], tags=["kitchen", "selfie"],
                 clothing_items=["apron"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Back on her feet in the kitchen ({k})",
                 _jev=_jev(0.02, detail="not_in_picture", seen="n"))
        flags = {**_COVERED, "over_breasts": "apron", "over_vulva": "apron"}
    elif cls == "bystander":
        f.update(primary_folder="lingerie", body_focus=["face", "breasts", "legs", "feet"],
                 tags=["lingerie", "bed", "pink"], clothing_items=["pink lace bra", "pink lace thong"],
                 clothing_state="lingerie_on", explicitness="suggestive",
                 description=f"Lingerie pose on the bed, smiling over her shoulder ({k})")
        flags = {**_COVERED, "over_breasts": "pink lace bra", "over_vulva": "pink lace thong",
                 "underwear_visible": True}
    elif cls == "mention":
        f.update(primary_folder="selfie", body_focus=["face", "breasts"], tags=["kitchen", "selfie"],
                 clothing_items=["apron"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Standing on her feet in the kitchen with a coffee ({k})")
        flags = {**_COVERED, "over_breasts": "apron", "over_vulva": "apron"}
    elif cls == "ambiguous":
        f.update(primary_folder="toy", body_focus=["vulva", "feet"], tags=["toy", "nude"],
                 clothing_items=[], clothing_state="fully_nude", explicitness="explicit", acts=["riding_toy"],
                 penetration="toy", description=f"Riding a toy on the floor, soles to the camera ({k})")
        flags = {"breasts_vis": "bare", "vulva_vis": "bare", "anus_vis": "not_in_frame"}
    elif cls == "measured_no":
        f.update(primary_folder="feet", body_focus=["face", "feet"], tags=["feet", "mirror"],
                 clothing_items=["sneakers", "jeans"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Mirror selfie in jeans and sneakers ({k})", _jev=_jev(0.05, detail="other_shoes"))
        flags = {**_COVERED, "over_breasts": "black top", "over_vulva": "blue jeans"}
    else:
        f.update(primary_folder="selfie", body_focus=["face"], tags=["mirror", "dress"],
                 clothing_items=["black dress"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Mirror selfie in a black dress ({k})")
        flags = dict(_OUT)
    if flags is not None:
        f.update({"underwear_visible": False, **flags, "_flags_model": MODEL, "_flags_v": FLAGS_VERSION})
    return f


def _search_text(f: dict) -> str:
    return " ".join([f["description"], *f["tags"], f["clothing_state"]]).lower()


def _old_like(f: dict) -> bool:
    return "feet" in _search_text(f) or '"feet"' in json.dumps(f)


def seed(w: World, creator: dict, n: int) -> dict:
    rng = w.rng("vault_feet")
    aid = creator["id"]
    names, weights = zip(*MIX)
    classes = [rng.choices(names, weights)[0] for _ in range(n)]
    for i, c in enumerate(names):
        classes[3 * i:3 * i + 3] = [c, c, c]
    rng.shuffle(classes)
    ids = sorted(rng.sample(range(2_500_000_000, 4_200_000_000), n))
    t0 = w.now - timedelta(days=60)
    out: dict = {"account_id": aid, "classes": {c: [] for c in names}, "keepers": [], "unknown_tier": [], "expect": {}, "filed": {},
                 "free_unsafe": [], "free_safe": [], "pre_rule": [], "like_set": [], "preselect": {},
                 "possible": {}, "below_floor": []}
    rows = []
    for k, (mid, cls) in enumerate(zip(ids, classes)):
        fields = _fields(cls, k)
        at = t0 + timedelta(minutes=7 * k)
        kind = "video" if cls in VIDEO else "photo"
        raw = {"id": mid, "type": kind, "convertedToVideo": False, "canView": True, "hasError": False,
               "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "isReady": True, "listStates": []}
        rows.append({
            "account_id": aid, "media_id": mid, "kind": kind, "duration_seconds": 12 if kind == "video" else None,
            "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now),
            "of_folder_ids": "[]", "search_text": _search_text(fields),
            "tags": json.dumps(fields["tags"]), "last_seen_run_id": None, "content_hash": None,
            "content_hash_kind": None, "send_count": 0, "last_sent_at": None, "removed_at": None,
            "description": fields["description"], "video_description": None,
            "describe_status": "described", "describe_model": MODEL, "describe_generated_at": ts(w.now),
            "ai_fields_json": json.dumps(fields), "of_terms": None, "explicitness_tier": fields["explicitness"],
            "frames_sampled": None})
        out["classes"][cls].append(mid)
        if _old_like(fields):
            out["like_set"].append(mid)
        if cls in KEEPERS:
            out["keepers"].append(mid)
            if cls in JEV_UNSAFE:
                out["unknown_tier"].append(mid)
            rung, tier = KEEPERS[cls]
            out["expect"][mid] = {"suggested": rung, "tier": tier}
            if cls in PRESELECT:
                out["preselect"][mid] = rung
            if rng.random() < FILED_P:
                out["filed"][mid] = FILED_FOLDER.removeprefix("feet-")
        elif cls in POSSIBLE:  # never pre-filed: no rng draw, so every other pick is unchanged
            rung, tier = POSSIBLE[cls]
            out["possible"][mid] = {"suggested": rung, "tier": tier}
        elif cls in BELOW_FLOOR:
            out["below_floor"].append(mid)
    # After the loop (no rng draw): the first unfiled of each class, so every other pick is unchanged.
    for cls, key in (("jev_unsure", "free_unsafe"), ("jev_free", "free_safe")):
        mid = next((m for m in out["classes"][cls] if m not in out["filed"]), None)
        if mid is not None:
            out["filed"][mid] = FREE_FOLDER.removeprefix("feet-")
            out[key].append(mid)
    for cls in PRE_RULE:
        mid = next((m for m in out["classes"][cls] if m not in out["filed"]), None)
        if mid is not None:
            out["filed"][mid] = FILED_FOLDER.removeprefix("feet-")
            out["pre_rule"].append(mid)
    con = w.sql()
    with con:
        cols = list(rows[0])
        con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
        for rung in sorted(set(out["filed"].values())):
            fid = con.execute("INSERT INTO vault_folders(account_id, name, created_by, created_at) VALUES (?,?,?,?)",
                              (aid, f"feet-{rung}", "operator", ts(w.now - timedelta(days=1)))).lastrowid
            con.executemany("INSERT INTO vault_folder_items(account_id, folder_id, media_id, manual_order, added_at) "
                            "VALUES (?,?,?,?,?)",
                            [(aid, fid, m, None, ts(w.now - timedelta(days=1)))
                             for m, r in sorted(out["filed"].items()) if r == rung])
    con.close()
    w.data["vault_feet"] = out
    return out
