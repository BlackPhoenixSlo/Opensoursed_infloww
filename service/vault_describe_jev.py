from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, Mapping

import vault_jev_flags
import vault_jev_rules

PROSE, V6, V2, VID = "prose", "v6", "v2", "vid"
JEV_FED = (PROSE, V6, VID)
RECIPE_V = "d51.2"
PX = {PROSE: 640, V6: 960, VID: 400}
DESCRIBE_KEY = "_describe"
FACT_CHOICES = vault_jev_rules.FACT_CHOICES


PROSE_BENCH = (
    "You write the catalogue description of one photo (or frames IN ORDER from one clip) in an adult creator's own private vault. "
    "She owns it and asked for it to be indexed and sold. Be plain, literal and clinical. Never moralise, soften, refuse or warn.\n\n"
    "RULES\n"
    "1. 2-3 literal sentences of selling prose: what she wears (or that she is nude), her pose and the setting, and the act: the body part "
    "it is done TO, the hand or toy doing it, rubbing on the surface vs INSERTED (how many fingers).\n"
    "2. Vague verbs ('touching herself', 'pleasuring herself', 'being intimate') are wrong: say exactly what happens.\n"
    "3. Only what is VISIBLE. If you cannot tell, leave it out.\n\n"
    'Return STRICT JSON only, no prose or fences: {"description": "<2-3 sentences>"}'
)
_CLOTHING_ASK = (
    ("3. Only what is VISIBLE. If you cannot tell, leave it out.\n\n",
     "3. Only what is VISIBLE. If you cannot tell, leave it out.\n"
     "4. clothing_items: each garment she wears as a short literal item with its colour or material "
     "(e.g. \"black lace bra\", \"white cotton t-shirt\"); [] when she wears nothing.\n\n"),
    ('{"description": "<2-3 sentences>"}',
     '{"description": "<2-3 sentences>", "clothing_items": ["<literal garment, with colour/material>"]}'),
)
PROSE_PROMPT = PROSE_BENCH
for _old, _new in _CLOTHING_ASK:
    assert PROSE_PROMPT.count(_old) == 1, _old
    PROSE_PROMPT = PROSE_PROMPT.replace(_old, _new)



def lane0(jev: Mapping[str, Any]) -> str:
    return "review" if jev.get("settled") else str(jev.get("lane"))


def feedable(jev: Any) -> bool:
    return (vault_jev_rules.ai_read({vault_jev_rules.JEV_KEY: jev})
            and isinstance(jev.get("C"), dict) and all(isinstance(jev["C"].get(q), dict) for q in FACT_CHOICES)
            and isinstance(jev.get("P"), dict) and isinstance(jev.get("tags"), dict)
            and jev.get("lane") is not None)


def review_lane(jev: Mapping[str, Any]) -> bool:
    return lane0(jev) == "review"


def _path(kind: str | None, jev: Mapping[str, Any]) -> str:
    return VID if kind == "video" else V6 if review_lane(jev) else PROSE


def route(*, kind: str | None, fields: Mapping[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    if kind not in vault_jev_rules.JEV_KINDS:
        return V2, None
    try:
        jev = (fields or {}).get(vault_jev_rules.JEV_KEY)
        if (not feedable(jev) or (jev.get("kind") == "video") != (kind == "video")
                or vault_jev_flags.reading(jev) is None):
            return None, None
        path = _path(kind, jev)
        # A blob the answer cannot be built from is a skip, not a crash after a paid call.
        answer(path, {}, jev)
        return path, jev
    except Exception:  # noqa: BLE001 — a malformed blob is a skip, never a crash
        return None, None


def meta(path: str, jev: Mapping[str, Any] | None, model: str) -> dict[str, Any]:
    fed = path in JEV_FED
    return {"path": path, "v": RECIPE_V, "jev_v": (jev or {}).get("v") if fed else None,
            "jev_at": (jev or {}).get("at") if fed else None, "model": model, "px": PX.get(path)}


def reusable(fields: Mapping[str, Any] | None, kind: str | None) -> bool:
    if kind not in vault_jev_rules.JEV_KINDS:
        return True
    f = fields or {}
    d = f.get(DESCRIBE_KEY)
    if not isinstance(d, dict) or d.get("path") not in JEV_FED:
        return False
    jev = f.get(vault_jev_rules.JEV_KEY)
    return (feedable(jev) and jev.get("v") == d.get("jev_v") and jev.get("at") == d.get("jev_at")
            and _path(kind, jev) == d.get("path"))



CUT, SETTING_CUT = .7, .8
SETTING = {"bedroom": "bedroom", "bathroom": "bathroom", "kitchen": "kitchen", "outdoors": "outdoor", "car": "car"}
OUTFIT = {"topless_with_bottoms": "no top, only bottoms (panties/thong/shorts/skirt)", "lingerie_or_bodysuit": "lingerie or a bodysuit",
          "swimwear": "a bikini or swimsuit", "everyday_clothes": "everyday clothes", "sheet_or_towel": "only a sheet or towel"}
TXT = {("nipple", "y"): "A bare nipple or areola IS visible.",
       ("nipple", "n"): "NO bare nipple or areola is visible (breasts are covered, hidden or out of frame): do not put nipples in body_focus or say nipples/breasts are bare.",
       ("vulva", "y"): "Her bare vulva / labia (pussy) IS visible.",
       ("vulva", "n"): "Her vulva / pussy is NOT visible (covered, hidden or out of frame): do not put pussy or clit in body_focus or describe her pussy as visible.",
       ("pen", "y"): "Something (finger or toy) IS inserted into her vagina or anus.",
       ("pen", "n"): "Nothing is inserted into her vagina or anus: penetration = none."}
HEDGE = ("Nipples, genitals and penetration are uncertain in this photo: do not mention them unless unmistakable; "
         "prefer neutral wording (e.g. 'nude', 'topless pose').")
HEAD = ("VERIFIED FACTS about this image, from a separate high-accuracy detector. Treat them as ground truth: every JSON field and the "
        "description MUST agree with them. Do not mention this list.\n")

Fact = tuple[str, str, str]


def final_lane_facts(d: Mapping[str, Any]) -> list[Fact]:
    lane = d["lane"]; F = {}
    if lane == "review": return []
    m = {"y": "y", "n": "n"}
    for f, k in (("nipple", "breasts_bare"), ("vulva", "crotch_bare"), ("pen", "penetration")):
        if d.get(k) in m: F[f] = m[d[k]]
    if lane == "$100": F["pen"] = "y"
    elif lane == "$50": F["vulva"] = "y"; F.pop("pen", None) if F.get("pen") == "y" else None
    elif lane == "$10":
        F["nipple"] = "y"
        if F.get("vulva") == "y": F.pop("vulva")
        if F.get("pen") == "y": F.pop("pen")
    else:
        for f in ("nipple", "vulva", "pen"):
            if F.get(f) == "y": F.pop(f)
    return [(f, v, TXT[(f, v)]) for f, v in F.items()]


def _d(jev: Mapping[str, Any]) -> dict[str, Any]:
    return {"lane": lane0(jev), "breasts_bare": jev.get("breasts_bare"), "crotch_bare": jev.get("crotch_bare"),
            "penetration": jev.get("penetration"), "toy_any": (jev.get("tags") or {}).get("toy_any")}


def facts(jev: Mapping[str, Any]) -> list[Fact]:
    hi, lo = CUT, 1 - CUT; d = _d(jev); C = jev["C"]
    F = final_lane_facts(d)
    if d["lane"] == "review": F.append(("hedge", "u", HEDGE))
    t = C["toy"]
    if t["no_toy"] >= hi: F.append(("toy", "n", "There is NO sex toy in the picture: toys = []."))
    elif t["no_toy"] <= lo:
        F.append(("toy", "y", "A sex toy IS in the picture" + (", touching or inserted into her" if t["toy_touching_or_inserted"] >= hi else "") + "."))
    o = C["outfit"]; top = max(o, key=o.get)
    if o["nude"] >= hi: F.append(("nude", "y", "She is fully nude: nothing covers her breasts or genitals."))
    elif o[top] >= hi: F.append(("nude", "n", f"She is wearing {OUTFIT[top]}, so she is NOT fully_nude."))
    pc = C["people_count"]
    if pc["one"] >= hi: F.append(("people", "one", "Exactly one person is in the picture: people_count = 1, partner_visible = false."))
    fv = C["face_visible"]
    if fv["full_face"] >= hi: F.append(("face", "y", "Her face is visible: face_visible = true."))
    elif fv["no_face"] >= hi: F.append(("face", "n", "Her face is NOT in the picture: face_visible = false."))
    st = C["setting"]; s = max(st, key=st.get)
    if st[s] >= SETTING_CUT and s in SETTING: F.append(("setting", SETTING[s], f"Setting: {SETTING[s]}."))
    if jev["P"].get("mirror_selfie", 0) >= hi: F.append(("mirror", "y", "It is a mirror selfie: camera = mirror."))
    return F


def build_prompt(base: str, F: list[Fact], head: str = HEAD) -> str:
    if not F: return base
    block = head + "".join(f"- {s}\n" for _, _, s in F) + "\n"
    i = base.index("RULES\n"); return base[:i] + block + base[i:]


def enforce(q: Mapping[str, Any] | None, F: list[Fact]) -> dict[str, Any]:
    q = json.loads(json.dumps(q or {})); F = {f: v for f, v, _ in F}
    bf = [x for x in q.get("body_focus") or [] if isinstance(x, str)]
    if F.get("nipple") == "y" and "nipples" not in bf: bf.append("nipples")
    if F.get("nipple") == "n": bf = [x for x in bf if x.lower() != "nipples"]
    if F.get("vulva") == "y" and "pussy" not in bf: bf.append("pussy")
    if F.get("vulva") == "n": bf = [x for x in bf if x.lower() not in ("pussy", "clit")]
    q["body_focus"] = bf
    if F.get("pen") == "n": q["penetration"] = "none"; q["insertion_depth"] = "none"
    if F.get("pen") == "y" and str(q.get("penetration", "none")).lower() in ("none", "unclear", ""):
        q["penetration"] = "toy" if F.get("toy") == "y" else "fingers"
    if F.get("toy") == "n": q["toys"] = []
    if F.get("toy") == "y" and not q.get("toys"): q["toys"] = ["sex toy"]
    if F.get("people") == "one": q["people_count"] = 1; q["partner_visible"] = False
    if F.get("face") in ("y", "n"): q["face_visible"] = F["face"] == "y"
    return q


def jev_struct(jev: Mapping[str, Any], F: list[Fact]) -> dict[str, Any]:
    d = _d(jev)
    q = enforce({}, F); have = {f for f, _, _ in F}; bf = q["body_focus"]
    if "nipple" not in have and d.get("breasts_bare") == "y": bf.append("nipples")
    if "vulva" not in have and d.get("crotch_bare") == "y": bf.append("pussy")
    if "pen" not in have:
        p = d.get("penetration"); q["penetration"] = {"y": "toy" if d.get("toy_any") == "y" else "fingers", "unsure": "unclear"}.get(p, "none")
    if "toy" not in have: q["toys"] = ["sex toy"] if d.get("toy_any") == "y" else []
    return q


_ACTS = {"fingers": ["fingering"], "toy": ["toy_insertion"]}
_TAG_CHOICES = ("outfit", "setting", "pose", "framing")
LANE_FIELDS = ("clothing_state", "underwear_visible", "genitals_covered", "explicitness")
_POSITION = {"standing": "standing", "sitting": "sitting", "kneeling": "kneeling", "lying_on_back": "lying_on_back",
             "lying_on_stomach": "lying_on_stomach", "all_fours_or_bent_over": "on_all_fours"}
_PEOPLE = {"one": 1, "two_or_more": 2, "none": 0}
_SETTING_ALL = {**SETTING, "living_room": "other", "gym": "other", "other": "other"}
_SAFE_OUTFITS = ("everyday_clothes", "swimwear")
# V2 keys the prose path leaves out: nothing reads them and Jev cannot answer them.
PROSE_ABSENT = {"camera": "selfie vs tripod is not a Jev question; only `mirror` is written, when Jev says so",
                "confidence": "no consumer reads it; Jev gives no per-item figure"}


def _top(C: Mapping[str, Any], q: str) -> str:
    p = C.get(q) or {}
    return max(p, key=p.get) if p else ""


def prose_fields(jev: Mapping[str, Any], F: list[Fact], q: Mapping[str, Any]) -> dict[str, Any]:
    tags, C = jev.get("tags") or {}, jev.get("C") or {}
    fv = {f: v for f, v, _ in F}
    r = vault_jev_flags.reading(jev)
    bare = any(r[k] == "bare" for k in ("breasts_vis", "vulva_vis", "anus_vis"))
    outfit = _top(C, "outfit")
    lane = str(jev.get("lane"))
    paid = lane in vault_jev_flags.EXPLICITNESS
    pen = str(q.get("penetration") or "none")
    people = _PEOPLE.get(_top(C, "people_count"), 1)
    if tags.get("feet_focus") == "y":
        folder = "feet"
    elif people >= 2:
        folder = "sex_with_partner"
    elif pen in ("toy", "fingers"):
        folder = "solo_toy" if pen == "toy" else "solo_fingering"
    elif lane == "$50":
        folder = "nude_stills"
    elif lane == "$10":
        folder = "boobs"
    elif outfit in ("lingerie_or_bodysuit", "swimwear", "topless_with_bottoms"):
        folder = "lingerie"
    elif outfit == "everyday_clothes":
        folder = "sfw_selfie"
    else:
        folder = "solo_tease"
    words = [str(tags[k]) for k in _TAG_CHOICES if tags.get(k) not in (None, "", "other")]
    words += [k for k in (jev.get("P") or {}) if tags.get(k) == "y"]
    out: dict[str, Any] = {
        "beats": [],
        "acts": list(_ACTS.get(pen, [])) or ["posing"],
        "penetration": pen,
        "insertion_depth": "none" if pen == "none" else "unclear",
        **{k: r[k] for k in LANE_FIELDS},
        "clothing_items": [],
        "position": _POSITION.get(str(tags.get("pose")), "unclear"),
        "setting": fv.get("setting") or _SETTING_ALL.get(_top(C, "setting"), "other"),
        "people_count": people,
        "partner_visible": people >= 2,
        "face_visible": _top(C, "face_visible") != "no_face",
        "nsfw": paid or bare or outfit not in _SAFE_OUTFITS,
        "sellable": True,
        "primary_folder": folder,
        "tags": [w.replace("_", " ") for w in words],
    }
    if fv.get("mirror") == "y":
        out["camera"] = "mirror"
    return out



NEG = re.compile(r"\b(no|not|n't|never|without|covered|covering|covers|cover|hidden|hides|hiding|obscur\w*|conceal\w*|block\w*|cropped|out of (the )?frame|under(neath)?|beneath|behind|through (the|her|a)|sheer|see-through|outline)\b", re.I)
NIP = re.compile(r"\b(nipples?|areolae?|areolas?)\b", re.I)
BREAST_BARE = re.compile(r"\b(bare|exposed?|exposing|naked|uncovered|reveal\w*)\b[^.;,]{0,25}\b(breasts?|boobs?|chest)\b|\b(breasts?|boobs?)\b[^.;,]{0,15}\b(are |is )?(bare|exposed|naked|uncovered|out)\b", re.I)
VUL = re.compile(r"\b(pussy|vulva|labia|clit|clitoris|genitals?|vagina)\b", re.I)
VUL_NEG = re.compile(r"\b(no|not|n't|never|without|covered|covering|covers|hidden|hides|obscur\w*|conceal\w*|cropped|out of (the )?frame|through (her|the|a)|over (her|the)|under(neath)?|beneath|outline)\b", re.I)
EXPOSED = [r"\b(not|no longer|isn't|aren't) (covered|concealed|hidden)\b", r"\bno (clothing|fabric|garments?|underwear|panties)( is| are)? (covering|covers|on)\b",
           r"\bwith nothing (covering|on)\b", r"\bwithout (any )?(clothing|underwear|panties)\b"]
INS = re.compile(r"\b(insert\w*|inside (of )?her (vagina|pussy|anus|ass)|penetrat\w*|fingering|thrust\w*)\b", re.I)
NEGP = re.compile(r"\b(no|not|n't|never|without|nothing|neither|nor)\b", re.I)
ORAL = re.compile(r"\b(mouth|lips|tongue|sucks?|sucking)\b", re.I)
NEG_STRICT = re.compile(r"\b(no|not|n't|never|without|covered|covering|hidden|hides|obscured|concealed|out of (the )?frame)\b", re.I)
VISW = re.compile(r"\b(visible|visibility|exposed|shown|seen|bare|covered|covering|hidden|hides|obscured|concealed|frame)\b", re.I)


def clauses(s: str) -> list[str]:
    for p in EXPOSED: s = re.sub(p, "exposed", s or "", flags=re.I)
    return [c for c in re.split(r"[.;!?]|,\s*but\b|\bbut\b", s) if c.strip()]


def desc_nipple(d: str) -> bool:
    for c in clauses(d):
        if (NIP.search(c) or BREAST_BARE.search(c)) and not NEG.search(c): return True
    return False


def desc_vulva(d: str) -> bool:
    for c in clauses(d):
        if VUL.search(c) and not VUL_NEG.search(c): return True
    return False


def desc_hit(d: str, rx: re.Pattern) -> bool:
    return any(rx.search(c) and not NEGP.search(c) and not (rx is INS and ORAL.search(c)) for c in clauses(d))


def _pos(f: str, s: str) -> bool:
    return desc_nipple(s) if f == "nipple" else desc_vulva(s) if f == "vulva" else desc_hit(s, INS)


def _neg(f: str, s: str) -> bool:
    if f == "pen": return any(INS.search(c) and NEGP.search(c) for c in clauses(s))
    rx = NIP if f == "nipple" else VUL
    return any(rx.search(c) and NEG_STRICT.search(c) and VISW.search(c) and not INS.search(c) for c in clauses(s))


def struct_lane(q: Mapping[str, Any]) -> dict[str, str | None]:
    bf = {str(x).lower() for x in q.get("body_focus") or []}; pen = str(q.get("penetration", "")).lower()
    return {"nipple": "y" if "nipples" in bf else "n", "vulva": "y" if bf & {"pussy", "clit"} else "n",
            "pen": None if pen == "unclear" else ("n" if pen in ("none", "") else "y")}


def add_clause(f: str, q: Mapping[str, Any]) -> str:
    if f == "nipple": return "Her nipples are visible."
    if f == "vulva": return "Her pussy is visible."
    pen = str(q.get("penetration", "")).lower()
    return ("A toy is" if "toy" in pen else "Her fingers are" if "finger" in pen else "Something is") + " inserted into her."


def scrub(desc: str | None, q: Mapping[str, Any], F: list[Fact]) -> tuple[str, dict[str, int]]:
    want = struct_lane(q); hard_y = {f for f, v, _ in F if v == "y" and f in want}; log = Counter(); out = []
    for s in re.split(r"(?<=[.!?])\s+", (desc or "").strip()):
        bad = lambda g: any((want[f] == "n" and _pos(f, g)) or (f in hard_y and _neg(f, g)) for f in want)  # noqa: E731
        if not s or not bad(s): out.append(s); continue
        segs = re.split(r",\s*", s); keep = [g for g in segs if not bad(g)]
        if not keep or keep[0] != segs[0] or len(keep) == len(segs): log["drop_sentence"] += 1; continue
        ns = ", ".join(keep).rstrip(",;: ."); ns += "."
        if bad(ns): log["drop_sentence"] += 1; continue
        out.append(ns); log["drop_clause"] += 1
    text = " ".join(out)
    for f in ("nipple", "vulva", "pen"):
        if f in hard_y and want[f] == "y" and not _pos(f, text): text = (text + " " + add_clause(f, q)).strip(); log["append"] += 1
    return text, dict(log)




def prompt_for(path: str, jev: Mapping[str, Any], v2_prompt: str) -> str:
    if path == VID:
        return build_prompt(v2_prompt, video_facts(jev), VIDEO_HEAD)
    return build_prompt(PROSE_PROMPT if path == PROSE else v2_prompt, facts(jev))



VIDEO_HEAD = HEAD.replace("about this image", "about this clip").replace(
    "a separate high-accuracy detector", "a separate high-accuracy detector that read 12 frames of it")
VIDEO_HEDGE = HEDGE.replace("in this photo", "in this clip")


def video_review(jev: Mapping[str, Any]) -> bool:
    return review_lane(jev) or bool(jev.get("review"))


def video_facts(jev: Mapping[str, Any]) -> list[Fact]:
    if video_review(jev):
        return [("hedge", "u", VIDEO_HEDGE)]
    return final_lane_facts(_d(jev))


def video_answer(parsed: Mapping[str, Any], jev: Mapping[str, Any]) -> dict[str, Any]:
    return _enforced(parsed, jev, video_facts(jev))


def answered(path: str, parsed: Mapping[str, Any]) -> bool:
    if not isinstance(parsed, Mapping):
        return False
    if path == PROSE:
        return isinstance(parsed.get("description"), str) and bool(parsed["description"].strip())
    return bool(parsed.get("description") or parsed.get("tags"))


def garments(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [s.strip()[:80] for s in raw if isinstance(s, str) and s.strip()][:12]


def prose_answer(parsed: Mapping[str, Any], jev: Mapping[str, Any]) -> dict[str, Any]:
    F = facts(jev); q = jev_struct(jev, F)
    out = {**prose_fields(jev, F, q), **q}
    out["clothing_items"] = garments((parsed or {}).get("clothing_items"))
    out["description"], _ = scrub(str((parsed or {}).get("description") or ""), out, F)
    return out


def v6_answer(parsed: Mapping[str, Any], jev: Mapping[str, Any]) -> dict[str, Any]:
    return _enforced(parsed, jev, facts(jev))


def _enforced(parsed: Mapping[str, Any], jev: Mapping[str, Any], F: list[Fact]) -> dict[str, Any]:
    q = enforce(parsed, F)
    desc = (parsed or {}).get("description", "")
    q["description"], _ = scrub(desc if isinstance(desc, str) else str(desc or ""), q, F)
    r = vault_jev_flags.reading(jev)
    q.update({k: r[k] for k in LANE_FIELDS})
    return q


_ANSWER = {PROSE: prose_answer, V6: v6_answer, VID: video_answer}


def answer(path: str | None, data: Mapping[str, Any], jev: Mapping[str, Any] | None) -> Mapping[str, Any]:
    build = _ANSWER.get(path)
    return build(data, jev) if build else data
