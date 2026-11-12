"""A described, flagged vault for the feet pack picker (scenarios/2026-11-11-vault-feet-picker.py): `vault_items`
rows by SQL for one Creator, as Collect + the describe pass + the flags pass leave them (columns as
seed/vault_items.py writes them), plus a few keepers already on `feet-nude` (an operator folder, as
vault_pack_picker.triage writes it). Each photo is planted in one class, so ranking and prefill have an exact oracle
written here, never read off the service:

  keepers (feet are the subject)                                   suggested   tier
    tease     soles in socks, flagged, body covered                tease       0
    bare      bare feet, flagged, body covered                     nude        0
    ten       feet up while topless, flagged breasts bare          nude-body   10
    fifty     feet up, flagged vulva bare                          nude-body   50
    raw_nude  feet, NO flags, clothing_state fully_nude             nude-body   None
    raw_socks soles in socks, NO flags, fully_clothed             -           None   (unknown tier: never free)
    raw_bare  bare feet, NO flags, lingerie_on                    -           None   (unknown tier: never free)
    measured  weak describe (legs in pantyhose), _jev.feet_subject 0.95, flagged covered   tease  0
    jev_free  weak describe, socks, NO qwen flags, _jev lane5 free       tease       0
    jev_paid  soles in socks, qwen flags covered, _jev lane5 $50         nude-body   50  (Jev overrides qwen)
  not keepers (the old LIKE set still returns them)
    bystander lingerie pose, feet one of four body_focus parts
    mention   "standing on her feet" in the description only
    ambiguous soles in frame, but riding a toy (a payoff act)
    measured_no  tagged feet / primary_folder feet, but _jev.feet_subject 0.05
  filler     nothing about feet (outside the LIKE set)
`_jev` rows follow the Jev storage contract (`ai_fields_json["_jev"]`: v, lane5, lane, settled, feet_subject).

Sizes: SIZES `vault_feet_items` (items per Creator), merged on import.

`seed(w, creator, n)` -> (and `w.data["vault_feet"]`) {"account_id", "classes": {cls: [media ids]},
"keepers": [ids], "unknown_tier": [keeper ids with no flags and no _jev lane5], "expect": {id: {"suggested",
"tier"}}, "filed": {id: "nude"}, "like_set": [ids the pre-change query matched, by media_id]}. Randomness only
from `w.rng("vault_feet")`; media ids shuffled across classes so media_id order is the base rate. Like prod
(primary_folder "feet" is rare: VaultPackPickerModal's header), bare and $10 keepers carry no feet folder: their
rank comes from tags, body_focus and the description."""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_feet_items": (300, 2_000, 12_000)}
merge_sizes(SIZES)

MODEL, PROMPT_VERSION, FLAGS_VERSION = "qwen3-vl-30b", "v2", 3   # as seed/vault_items.py
MIX = (("tease", 0.04), ("bare", 0.04), ("ten", 0.025), ("fifty", 0.025), ("raw_nude", 0.02), ("raw_socks", 0.015),
       ("raw_bare", 0.015), ("measured", 0.015), ("jev_free", 0.015), ("jev_paid", 0.015),
       ("bystander", 0.13), ("mention", 0.09), ("ambiguous", 0.05), ("measured_no", 0.015), ("filler", 0.52))
KEEPERS = {"tease": ("tease", 0), "bare": ("nude", 0), "ten": ("nude-body", 10), "fifty": ("nude-body", 50),
           "raw_nude": ("nude-body", None), "raw_socks": (None, None), "raw_bare": (None, None),
           "measured": ("tease", 0), "jev_free": ("tease", 0), "jev_paid": ("nude-body", 50)}
JEV_V = "v8+nn.10"   # the Jev storage contract's version string
FILED_P = 0.08   # keepers already on feet-nude before the run (the queue must leave them out)
FILED_FOLDER = "feet-nude"

_COVERED = {"breasts_vis": "covered", "vulva_vis": "covered", "anus_vis": "not_in_frame"}
_OUT = {"breasts_vis": "not_in_frame", "vulva_vis": "not_in_frame", "anus_vis": "not_in_frame"}


def _jev(feet_subject: float, lane5: str | None = None) -> dict:
    """An `ai_fields_json["_jev"]` block as the Jev pass stores it (only the keys the picker reads + identity)."""
    j: dict = {"v": JEV_V, "settled": True, "feet_subject": feet_subject}
    if lane5:
        j.update(lane5=lane5, lane=lane5)
    return j


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
                 _jev=_jev(0.95))
        flags = {**_COVERED, "over_breasts": "white blouse", "over_vulva": "black skirt"}
    elif cls == "jev_free":
        f.update(primary_folder="legs", body_focus=["legs", "feet"], tags=["legs", "socks"],
                 clothing_items=["white socks", "shorts"], clothing_state="fully_clothed", explicitness="safe",
                 description=f"Legs up on the sofa in white socks ({k})", _jev=_jev(0.92, "free"))
    elif cls == "jev_paid":
        f.update(primary_folder="feet", body_focus=["feet"], tags=["feet", "socks"],
                 clothing_items=["white socks", "blanket"], clothing_state="fully_clothed", explicitness="suggestive",
                 description=f"Soles in white socks under a blanket ({k})", _jev=_jev(0.9, "$50"))
        flags = {**_COVERED, "over_breasts": "grey blanket", "over_vulva": "grey blanket"}
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
                 description=f"Mirror selfie in jeans and sneakers ({k})", _jev=_jev(0.05, "free"))
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
                 "like_set": []}
    rows = []
    for k, (mid, cls) in enumerate(zip(ids, classes)):
        fields = _fields(cls, k)
        at = t0 + timedelta(minutes=7 * k)
        raw = {"id": mid, "type": "photo", "convertedToVideo": False, "canView": True, "hasError": False,
               "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "isReady": True, "listStates": []}
        rows.append({
            "account_id": aid, "media_id": mid, "kind": "photo", "duration_seconds": None,
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
            if cls.startswith("raw_"):
                out["unknown_tier"].append(mid)
            rung, tier = KEEPERS[cls]
            out["expect"][mid] = {"suggested": rung, "tier": tier}
            if rng.random() < FILED_P:
                out["filed"][mid] = FILED_FOLDER.removeprefix("feet-")
    con = w.sql()
    with con:
        cols = list(rows[0])
        con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
        if out["filed"]:
            fid = con.execute("INSERT INTO vault_folders(account_id, name, created_by, created_at) VALUES (?,?,?,?)",
                              (aid, FILED_FOLDER, "operator", ts(w.now - timedelta(days=1)))).lastrowid
            con.executemany("INSERT INTO vault_folder_items(account_id, folder_id, media_id, manual_order, added_at) "
                            "VALUES (?,?,?,?,?)",
                            [(aid, fid, m, None, ts(w.now - timedelta(days=1))) for m in sorted(out["filed"])])
    con.close()
    w.data["vault_feet"] = out
    return out
