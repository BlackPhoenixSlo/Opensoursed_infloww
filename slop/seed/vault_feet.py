"""A described, flagged, Jev-classified vault for the feet pack picker (scenarios/2026-11-11-vault-feet-picker.py):
`vault_items` rows by SQL for one Creator, as Collect + the describe pass + the flags pass + Jev v8 leave them
(columns as seed/vault_items.py writes them), plus a few keepers already on `feet-nude` (an operator folder, as
vault_pack_picker.triage writes it). Each item is planted in one class, so the candidate set, ranking and prefill
have an exact oracle written here, never read off the service.

PRECISION ONLY (vault_pack_picker): a candidate is a Jev photo that sees the feet at score >= .6. Below the gate, a
Jev photo that sees the feet at score >= .3 (FEET_POSSIBLE_MIN) is POSSIBLE: queued after every candidate, `possible`
true, never preselected, `suggested` its rung without the gate (tier + covering). Below .3: no candidate. Nothing else.

  keepers = the candidates (Jev photos, `_jev.status` ok, feet seen, score >= .6)        suggested   tier
    measured   weak describe (legs in pantyhose), Jev feet_subject 0.95, stockings, free  tease       0
    jev_free   weak describe, Jev socks, NO qwen flags, lane5 free                        tease       0
    jev_paid   soles in socks, qwen flags covered, Jev lane5 $50                          nude-body   50
    jev_unsure Jev lane5 free BUT breasts_bare unsure, socks; qwen flags covered          -           None  (free guard)
    jev_review Jev lane5 review, socks                                                     -           None  (free guard)
    jev_soles  no feet word anywhere (outside the LIKE set); Jev soles + bare             nude        0   (Jev finds it)
  PRESELECTED (arrive ticked): the keepers with a suggestion (measured, jev_free, jev_paid, jev_soles).
  possible (seen, .3 <= score < the gate; after the candidates, unticked)              suggested   tier
    jev_maybe  Jev feet_subject 0.55 (< FEET_PRESELECT_SCORE .6), socks, lane5 free, body "n"  tease       0
    jev_floor  Jev feet_subject 0.30 (== FEET_POSSIBLE_MIN), socks, lane5 free, body "n"       tease       0
  below the floor (seen, score < .3): not candidates (BELOW_FLOOR)
    jev_low      Jev feet_subject 0.29, socks, lane5 free, body "n"
    measured_no  tagged feet / primary_folder feet, but Jev feet_subject 0.05, other shoes
  not candidates
    tease / bare / ten / fifty / raw_nude / raw_socks / raw_bare   feet photos by every describe word and flag, but
               Jev has not classified them (no `_jev`): they wait for Jev
    jev_video  a CLIP: Jev max frame feet .95 socks free, feet words (no videos in feet)
    jev_absent   body_focus feet + "on her feet", but Jev: feet not in the picture
    bystander lingerie pose, feet one of four body_focus parts
    mention   "standing on her feet" in the description only
    ambiguous soles in frame, but riding a toy (a payoff act)
  filler     nothing about feet (outside the LIKE set)
Pre-guard free rung: one `jev_unsure` and one `jev_free` keeper on `feet-tease` (as the old prefill could file
them before the free guard): the unsafe one must come back `unsafe_on_free` and never reach OF's free list.
Pre-rule rows: one `tease` (no Jev) and one `jev_video` on `feet-nude` (filed before precision-only): they come back
on their rung, never in the queue.
`_jev` rows follow the Jev storage contract (`vault_jev_rules.blob` / `video_blob`: v, status, lane5, breasts_bare /
crotch_bare / penetration, feet_subject, P, tags; a clip's adds kind "video").

Sizes: SIZES `vault_feet_items` (items per Creator), merged on import.

`seed(w, creator, n)` -> (and `w.data["vault_feet"]`) {"account_id", "classes": {cls: [media ids]},
"keepers": [ids], "unknown_tier": [keeper ids with an unknown Jev tier (JEV_UNSAFE)], "expect": {id: {"suggested",
"tier"}}, "preselect": {id: rung} (PRESELECT keepers, pre-filed ones included), "possible": {id: {"suggested",
"tier"}} (POSSIBLE rows), "below_floor": [ids of BELOW_FLOOR rows], "filed": {id: rung},
"free_unsafe": [the jev_unsure id on feet-tease], "free_safe": [the jev_free id on feet-tease], "pre_rule": [the
tease + jev_video ids on feet-nude], "like_set": [ids the pre-change query matched, by media_id]}. Randomness only
from `w.rng("vault_feet")`; media ids shuffled across classes so media_id order is the base rate."""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_feet_items": (300, 2_000, 12_000)}
merge_sizes(SIZES)

MODEL, PROMPT_VERSION, FLAGS_VERSION = "qwen3-vl-30b", "v2", 3   # as seed/vault_items.py
MIX = (("tease", 0.04), ("bare", 0.04), ("ten", 0.025), ("fifty", 0.025), ("raw_nude", 0.02), ("raw_socks", 0.015),
       ("raw_bare", 0.015), ("measured", 0.015), ("jev_free", 0.015), ("jev_paid", 0.015),
       ("jev_unsure", 0.015), ("jev_review", 0.015), ("jev_soles", 0.015), ("jev_maybe", 0.015),
       ("jev_video", 0.015), ("bystander", 0.13), ("mention", 0.09), ("ambiguous", 0.05), ("measured_no", 0.015),
       ("jev_absent", 0.015), ("jev_floor", 0.015), ("jev_low", 0.015), ("filler", 0.415))
# The candidates (confident Jev photos) and their (suggested, tier): written from the spec, not the service.
KEEPERS = {"measured": ("tease", 0), "jev_free": ("tease", 0), "jev_paid": ("nude-body", 50),
           "jev_unsure": (None, None), "jev_review": (None, None), "jev_soles": ("nude", 0)}
# Jev photos that see the feet at .3 <= score < the gate: POSSIBLE, (suggested, tier) without the gate. From the spec.
POSSIBLE = {"jev_maybe": ("tease", 0), "jev_floor": ("tease", 0)}
# Jev photos that see the feet below FEET_POSSIBLE_MIN (.3): no candidate at all (unless filed).
BELOW_FLOOR = ("jev_low", "measured_no")
# Feet by every describe word / flag, no `_jev`: no candidate until Jev classifies them.
NO_JEV = ("tease", "bare", "ten", "fifty", "raw_nude", "raw_socks", "raw_bare")
VIDEO = ("jev_video",)
# Keepers that arrive PRESELECTED (a known, safe suggestion): written from the spec, not the service.
PRESELECT = ("measured", "jev_free", "jev_paid", "jev_soles")
# Jev rows whose body is not free-safe: never prefilled, free rung refused (`feet_jev_free_guard`).
JEV_UNSAFE = ("jev_unsure", "jev_review")
JEV_V = "v8+nn.10"   # the Jev storage contract's version string
FILED_P = 0.08   # keepers already on feet-nude before the run (the queue must leave them out)
FILED_FOLDER = "feet-nude"
FREE_FOLDER = "feet-tease"   # the free rung: one unsafe + one safe Jev keeper pre-filed (pre-guard)
PRE_RULE = ("tease", "jev_video")   # one of each on feet-nude, filed before precision-only

_COVERED = {"breasts_vis": "covered", "vulva_vis": "covered", "anus_vis": "not_in_frame"}
_OUT = {"breasts_vis": "not_in_frame", "vulva_vis": "not_in_frame", "anus_vis": "not_in_frame"}


def _jev(feet_subject: float, lane5: str = "free", detail: str = "socks", *, soles: float = 0.0, toes: float = 0.0,
         seen: str = "y", **body: str) -> dict:
    """An `ai_fields_json["_jev"]` block as `vault_jev_rules.blob` stores it (the keys the picker reads + identity).
    Body answers default "n"; `seen` is tags.feet_any (feet in the picture)."""
    return {"v": JEV_V, "status": "ok", "lane5": lane5, "lane": lane5, "settled": False,
            **{"breasts_bare": "n", "crotch_bare": "n", "penetration": "n", **body},
            "feet_subject": feet_subject,
            "P": {"feet_focus": feet_subject, "soles_visible": soles, "bare_toes_visible": toes},
            "tags": {"feet_detail": detail, "feet_any": seen, "feet_focus": "y" if feet_subject >= 0.4 else "n",
                     "soles_visible": "y" if soles >= 0.4 else "n", "bare_toes_visible": "y" if toes >= 0.55 else "n"}}


def _fields(cls: str, k: int) -> dict:
    """The stored describe (+ flags) for a class. Filler and non-feet words never contain the LIKE terms
    (feet / soles / toes / barefoot / bare feet)."""
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
    elif cls in ("jev_floor", "jev_low"):   # at / just below FEET_POSSIBLE_MIN
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
    """The pre-change candidate query: search_text LIKE %feet% OR ai_fields_json LIKE %"feet"%."""
    return "feet" in _search_text(f) or '"feet"' in json.dumps(f)


def seed(w: World, creator: dict, n: int) -> dict:
    rng = w.rng("vault_feet")
    aid = creator["id"]
    names, weights = zip(*MIX)
    classes = [rng.choices(names, weights)[0] for _ in range(n)]
    for i, c in enumerate(names):   # every class at least three times
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
        elif cls in POSSIBLE:   # never pre-filed: no rng draw, so every other pick is unchanged
            rung, tier = POSSIBLE[cls]
            out["possible"][mid] = {"suggested": rung, "tier": tier}
        elif cls in BELOW_FLOOR:
            out["below_floor"].append(mid)
    # After the loop (no rng draw): the first unfiled of each class, so every other pick is unchanged.
    for cls, key in (("jev_unsure", "free_unsafe"), ("jev_free", "free_safe")):
        mid = next((m for m in out["classes"][cls] if m not in out["filed"]), None)
        if mid is not None:   # none left: the scenario's check goes red on the empty list
            out["filed"][mid] = FREE_FOLDER.removeprefix("feet-")
            out[key].append(mid)
    for cls in PRE_RULE:   # filed before precision-only: back on their rung, never in the queue
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
