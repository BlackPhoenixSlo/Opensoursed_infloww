"""vault_jev_rules.py — the pure half of the Jev v8 vault flags pass: answers in, lane out.

A port of the owner-accepted bench config (D48, `.scratch/jev-vault-bench/`: frozen flags8c +
`score8.py --veto --promote` + `settle.py nn.10`, CONFIG_HASH 708e26853eaff5a2). Every rule here is a
copy of the bench function named beside it, with the same thresholds, in the same order; only imports
and names moved. `tests/test_vault_jev.py` replays the bench's own records through it and asserts the
bench's lanes on every dev image. Do NOT tune here: a rule change is a new bench session, not an edit.

  derive8(rec)           score8.derive8 with score8.CFG (base_cfg() for flags8*): pass 1 → lane, pass 2
                         overlay when `need2`, pass L (lower crop) when `needL`. `rec` is the bench record
                         shape: {"resp": {"answers": ...}, "resp2"?: ..., "respL"?: ...}.
  nn_veto(d, scores)     score8.nn_veto for ONE image, NN_D34 (veto t .35 + promote tG .50 / tB .40 / gmax .30).
  settle(d)              settle.py MODE "nn.10" (D42: no human review queue; `review` settles itself).
  blob(...)              the stored `ai_fields_json["_jev"]` (storage contract, `vault_jev`).

Videos (D53 hr12 maxF, D54; bench `jv-jev.py` / `jv-score.py`): `final` per frame, pass 2 / L only on the top-3
frames derive8 asks for (`video_targets`), lane = the max frame's (`video_final`); `video_blob` stores the max
frame's photo-shaped blob plus every frame's answers (`pack`, so the rules re-derive without a refetch).

Not ported (bench decisions): toy pass T (D37, cfg "toy2" off), pass S (D46, rejected).
"""
from __future__ import annotations

from typing import Any

# The stored blob's version: the question set + rules + settle mode it was made with.
VERSION = "v8+nn.10"
# Where the blob lives in `ai_fields_json` (the one definition; every vault module reads it from here).
JEV_KEY = "_jev"
# The kinds Jev reads (photos: one still; videos: 12 frames, `video_blob`) — the only kinds with flags.
JEV_KINDS = ("photo", "video")
# A video blob's frame source + combine (12 frames @720p, top-3 escalation, max lane): `current` needs it too.
VIDEO_VERSION = "jv1"

# ── score7 (helpers + tag lists) ────────────────────────────────────


def P(a, q):
    x = a[q]
    return x["noul"] if x["type"] == "noul" else x["probabilities"]


def avgp(a, qs):
    ps = [P(a, q) for q in qs if q in a]
    if isinstance(ps[0], float):
        return sum(ps) / len(ps)
    return {k: sum(p.get(k, 0) for p in ps) / len(ps) for k in ps[0]}


NOUL_OF = {"breasts": ["nipple_visible_a", "nipple_visible_b"],
           "crotch": ["vulva_visible_a", "vulva_visible_b"], "butt": ["butt_cheeks_bare"]}
NOULS = ["person_present", "watermark", "clothing_print_text", "censor_edit", "self_touch", "legs_spread",
         "mouth_tease", "feet_focus", "nipple_through_fabric", "butt_cheeks_bare", "topless", "see_through",
         "pulling_clothes", "tongue_out", "smiling", "jewelry", "phone_visible", "looking_at_camera",
         "breasts_focus", "butt_focus", "crotch_focus", "face_focus", "wears_heels",
         "wears_stockings_or_fishnets", "wears_socks", "bare_toes_visible", "soles_visible", "feet_in_water",
         "multi_panel", "sharp_and_well_lit", "mirror_selfie"]
CHOICES = ["people_count", "added_text", "toy", "outfit", "outfit_color", "setting", "hair", "pose", "framing",
           "face_visible", "facing"]
PAID = ("$10", "$50", "$100")

# ── score8 ──────────────────────────────────────────────────────────

FREE = ("mass", "implied", "lingerie")
CFG = dict(pen_y=.70, pen_n=.62, topless_vote=True, nude_rule="residual", nude_t=.2, resid_t=.10, probe_twb=9,
           prec="pen", crotch_pb=.5, low_trig=True, low_y=.5, low_rev=.35, band=0, avg2=False, breasts_nn=.35,
           crotch_nn=.35, clothes_v=None)
COVERED = ("sexy_covered", "normal_covered", "sheer_covered")
NN_D33 = {"t": .35, "cls": ["FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED"]}
NN_D34 = {**NN_D33, "promote": {"tG": .50, "tB": .40, "gmax": .30}}
# per-tag Noul cut (D23 calibrated on set2-4); missing → .5
CUTS = {'butt_bare': 0.35, 'nipple_through_fabric': 0.8, 'topless': 0.65, 'see_through': 0.5, 'watermark': 0.5,
        'censor_edit': 0.75, 'multi_panel': 0.5, 'wears_heels': 0.5, 'wears_stockings_or_fishnets': 0.85,
        'wears_socks': 0.6, 'bare_toes_visible': 0.55, 'soles_visible': 0.4, 'feet_in_water': 0.7,
        'feet_focus': 0.4, 'looking_at_camera': 0.4, 'smiling': 0.6, 'tongue_out': 0.6, 'mouth_tease': 0.45,
        'breasts_focus': 0.8, 'butt_focus': 0.85, 'crotch_focus': 0.7, 'self_touch': 0.4, 'legs_spread': 0.65,
        'pulling_clothes': 0.65, 'jewelry': 0.55, 'phone_visible': 0.75, 'mirror_selfie': 0.9,
        'person_present': 0.5}


def lane_rule(a, d, cfg, p1=False):
    """Lane from answers `a` (pass 1, or pass 1 overlaid with pass 2). Writes lane-critical fields into d, returns lane."""
    band = cfg.get("band", 0) if p1 else 0
    for r in ("breasts", "crotch"):
        st = avgp(a, [f"{r}_state_a", f"{r}_state_b"]); n = avgp(a, NOUL_OF[r]); pb = st["bare"]
        d[r] = max(st, key=st.get)
        v = "y" if (pb >= (cfg["crotch_pb"] if r == "crotch" else .5) + band or n >= .65 + band) else ("n" if (pb <= .2 and n <= cfg.get(r + "_nn", .35)) else "unsure")
        if v == "y" and r == "crotch" and cfg.get("clothes_v") and a["outfit"]["choice"] == "everyday_clothes" \
                and not (max(st, key=st.get) == "bare" and n >= cfg["clothes_v"]): v = "unsure"
        if v == "unsure" and r == "breasts" and cfg["topless_vote"]:
            t = P(a, "topless")
            if t <= .10 and n <= .45 and pb <= .25: v = "n"
        d[r + "_bare"] = v; d[r + "_pb"], d[r + "_n"] = round(pb, 2), round(n, 2)
    pp = avgp(a, [q for q in ("penetration", "penetration_b") if q in a]); d["penetration_p"] = round(pp, 2)
    d["penetration"] = "y" if pp >= cfg["pen_y"] + band else ("n" if pp <= cfg["pen_n"] - band else "unsure")
    nf, cen = P(a, "nipple_through_fabric"), P(a, "censor_edit")
    if d["penetration"] == "y": lane = "$100"
    elif cfg["prec"] in (True, "pen") and d["penetration"] == "unsure": lane = "review"
    elif d["crotch_bare"] == "y": lane = "$50"
    elif cfg["prec"] in (True, "crotch") and d["crotch_bare"] == "unsure": lane = "review"
    elif d["breasts_bare"] == "y": lane = "$10"
    elif "unsure" in (d["breasts_bare"], d["crotch_bare"], d["penetration"]): lane = "review"
    elif "hidden_not_worn" in (d["breasts"], d["crotch"], d["butt"]) or cen >= .65: lane = "implied"
    elif {"sexy_covered", "sheer_covered"} & {d["breasts"], d["crotch"], d["butt"]} or nf >= .65: lane = "lingerie"
    else: lane = "mass"
    if lane == "mass" and (nf > .35 or a["toy"]["choice"] != "no_toy"): lane = "review"
    return lane


def mix(x, y):
    """D26 avg2: mean of two answers (Noul p / Choice probabilities). Unused by CFG (avg2 False); kept for derive8."""
    if "noul" in x: return {**y, "noul": (x["noul"] + y["noul"]) / 2}
    pr = {k: (x["probabilities"][k] + y["probabilities"][k]) / 2 for k in y["probabilities"]}
    return {**y, "probabilities": pr, "choice": max(pr, key=pr.get)}


def derive8(rec, cfg=None):
    cfg = {**CFG, **(cfg or {})}
    a = rec["resp"]["answers"]; d = {}
    st = avgp(a, ["butt_state_a"]); d["butt"] = max(st, key=st.get)
    nb = P(a, "butt_cheeks_bare") if "butt_cheeks_bare" in a else 0; pbb = st["bare"]
    d["butt_bare"] = "y" if (pbb >= .5 or nb >= .65) else ("n" if (pbb <= .2 and nb <= .35) else "unsure")
    nude = a["outfit"]["probabilities"]["nude"]
    lane = lane_rule(a, d, cfg, p1=True)
    if lane in FREE and nude >= cfg["nude_t"]: lane = "review"
    d["lane1"] = lane; d["pass2"] = False
    d["need2"] = lane == "review" or (lane in FREE and a["outfit"]["probabilities"]["topless_with_bottoms"] >= cfg["probe_twb"])
    if d["need2"] and "resp2" in rec:
        a2 = rec["resp2"]["answers"]; a2 = {q: mix(a[q], x) for q, x in a2.items()} if cfg.get("avg2") else a2
        d2 = {"butt": d["butt"]}; lane = lane_rule({**a, **a2}, d2, cfg)
        if lane in FREE and nude >= cfg["nude_t"] and (cfg["nude_rule"] == "always" or d2["crotch_n"] >= cfg["resid_t"]): lane = "review"
        d.update(d2); d["pass2"] = True
    d["needL"] = bool(cfg["low_trig"]) and lane == "$10" and (d["crotch"] not in COVERED or d["crotch_n"] >= .3)
    d["passL"] = False
    if d["needL"] and "respL" in rec:
        al = rec["respL"]["answers"]; v = (al["vulva_visible_a"]["noul"] + al["vulva_visible_b"]["noul"]) / 2; d["low_v"] = round(v, 2); d["passL"] = True
        if v >= cfg["low_y"]: lane = "$50"
        elif v >= cfg["low_rev"]: lane = "review"
    d["lane"] = lane; d["lane5"] = lane if lane in PAID or lane == "review" else "free"
    for q in CHOICES:
        if q in a: d[q] = a[q]["choice"]
    d["needT"] = bool(cfg.get("toy2")) and a["toy"]["probabilities"]["no_toy"] < cfg["toy2"]
    if d["needT"] and "respT" in rec: d["toy"] = rec["respT"]["answers"]["toy"]["choice"]
    d["P"] = {q: P(a, q) for q in NOULS if q in a}; d["P"]["butt_bare"] = max(pbb, nb)
    for q, p in d["P"].items(): d[q] = "y" if p >= cfg.get("cuts", CUTS).get(q, .5) else "n"
    fd = avgp(a, ["feet_detail_a", "feet_detail_b"]); d["feet_detail"] = max(fd, key=fd.get)
    d["text_any"] = "y" if d["added_text"] != "nothing_added" else "n"
    d["toy_any"] = "y" if d["toy"] != "no_toy" else "n"
    d["feet_any"] = "y" if d["feet_detail"] != "not_in_picture" else "n"
    collapse(d)
    return d


COLLAPSE = {
    "face_in_photo": ("face_visible", {"full_face": "y", "partial_face": "y", "no_face": "n"}),
    "framing3": ("framing", {"face_close_up": "face_upper", "face_and_chest": "face_upper", "upper_body": "face_upper", "most_of_body": "wide",
                             "full_body": "wide", "body_part_close_up": "no_face_body", "body_no_face": "no_face_body"}),
    "setting_bathroom": ("setting", {"bathroom": "y", "bedroom": "n", "living_room": "n", "kitchen": "n", "outdoors": "n", "car": "n", "gym": "n", "other": "n"}),
    "back_to_camera": ("facing", {"away": "y", "side": "n", "toward_camera": "n"}),
    "feet_detail5": ("feet_detail", {"heels": "shoes", "other_shoes": "shoes"}),
    "pose4": ("pose", {"sitting": "sitting_or_kneeling", "kneeling": "sitting_or_kneeling", "lying_on_back": "lying_or_all_fours",
                       "lying_on_stomach": "lying_or_all_fours", "lying_on_side": "lying_or_all_fours", "all_fours_or_bent_over": "lying_or_all_fours"}),
    "hair3": ("hair", {"ponytail_or_bun": "up", "braids": "up"}),
    "toy_on_genitals": ("toy", {"toy_touching_or_inserted": "y", "toy_visible_not_in_use": "n", "no_toy": "n"}),
}


def collapse(x):
    for new, (src, m) in COLLAPSE.items():
        v = x.get(src)
        if v not in (None, "?", "na"): x[new] = m.get(v, v)


def nn_veto(d, x, nn=NN_D34):
    """score8.nn_veto for one derived image `d`; `x` = NudeNet {class: max score} (None = no detection run)."""
    if x is None: d["nn"] = None; return
    d["nn"] = max(x.get(c, 0) for c in nn["cls"]); d["nnB"] = x.get("FEMALE_BREAST_EXPOSED", 0); d["nnG"] = x.get("FEMALE_GENITALIA_EXPOSED", 0)
    if d["lane5"] == "free" and d["nn"] >= nn["t"]: d["lane"] = d["lane5"] = "review"; d["nn_veto"] = True
    pr = nn.get("promote")
    if pr and d["lane"] == "review" and d.get("penetration") != "unsure":
        if d["nnG"] >= pr["tG"]: d["lane"] = d["lane5"] = "$50"; d["nn_promote"] = True
        elif d["nnB"] >= pr["tB"] and d["nnG"] < pr.get("gmax", .30): d["lane"] = d["lane5"] = "$10"; d["nn_promote"] = True


# ── settle.py, MODE "nn.10" ─────────────────────────────────────────

SETTLE_MODE = "nn.10"


def settle(d, mode=SETTLE_MODE):
    """D42: review → pen unsure $100; else NudeNet both < .10 → free; else crotch y/unsure or nnG ≥ .5 → $50; else $10."""
    if d["lane"] != "review": return
    g = (d.get("nnG") or 0) >= .5
    t = float(mode[2:])
    if d.get("nn") is not None and (d.get("nnB") or 0) < t and (d.get("nnG") or 0) < t and d.get("penetration") != "unsure":
        d["lane"] = "lingerie"; d["lane5"] = "free"; d["settled"] = mode; return
    t = "$100" if d.get("penetration") == "unsure" else ("$50" if (d.get("crotch_bare") in ("y", "unsure") or g) else "$10")
    d["lane"] = d["lane5"] = t; d["settled"] = mode


def final(rec: dict[str, Any], scores: dict[str, float] | None) -> dict[str, Any]:
    """The whole frozen config over one image: derive8 → NN_D34 veto/promote → settle nn.10."""
    d = derive8(rec)
    nn_veto(d, scores)
    settle(d)
    return d


# ── The stored blob (`ai_fields_json["_jev"]`) ──────────────────────

# Search tags the blob carries: the choice argmaxes, their collapsed classes, and the binary Noul tags
# (derive8's `P` keys at CUTS).
_TAG_KEYS = (*[q for q in CHOICES], "feet_detail", "text_any", "toy_any", "feet_any", *COLLAPSE)
# Choice questions whose full probabilities the blob keeps (`C`) for the Jev-fed describe's facts block
# (vault_describe_jev.facts). None is in Q2, so pass 1's answer is the pass1+pass2 overlay's.
FACT_CHOICES = ("toy", "outfit", "people_count", "face_visible", "setting")


def overlay(rec: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
    """Pass 1's answers with pass 2's on top where derive8 asked for it (the bench's describe input)."""
    a = rec["resp"]["answers"]
    return {**a, **rec["resp2"]["answers"]} if "resp2" in rec and d.get("need2") else a


def blob(d: dict[str, Any], scores: dict[str, float], *, passes: list[str], tok: int,
         px: list[int], at: str, answers: dict[str, Any]) -> dict[str, Any]:
    tags = {k: d[k] for k in _TAG_KEYS if k in d}
    tags.update({q: d[q] for q in d["P"]})
    return {
        "v": VERSION, "status": "ok",
        "lane5": d["lane5"], "lane": d["lane"], "settled": d.get("settled") or False,
        "breasts_bare": d["breasts_bare"], "crotch_bare": d["crotch_bare"], "penetration": d["penetration"],
        # each region's state argmax (bare / *_covered / hidden_not_worn / not_visible): vault_jev_flags reads it
        "state": {r: d[r] for r in ("breasts", "crotch", "butt") if r in d},
        "nn":{"B": scores.get("FEMALE_BREAST_EXPOSED", 0), "G": scores.get("FEMALE_GENITALIA_EXPOSED", 0)},
        "feet_subject": d["P"].get("feet_focus"),
        "tags": tags, "P": dict(d["P"]), "passes": list(passes), "tok": int(tok), "px": list(px), "at": at,
        "C": {q: dict(P(answers, q)) for q in FACT_CHOICES
              if q in answers and answers[q].get("type") == "choice"},
    }


def current(fields: dict[str, Any] | None) -> bool:
    """The row carries a successful `_jev` of this VERSION (nothing for a sweep to do). A blob without `state` (made
    before the region states were stored, same VERSION) is not current: the flags mapper needs it to tell a region
    out of frame from a covered one, so the photo re-runs (no such reading ever reached prod). A video blob also
    needs this VIDEO_VERSION and its frames."""
    j = (fields or {}).get(JEV_KEY)
    return (isinstance(j, dict) and j.get("v") == VERSION and j.get("status") == "ok" and "lane5" in j
            and isinstance(j.get("state"), dict)
            and (j.get("kind") != "video" or (j.get("vv") == VIDEO_VERSION and isinstance(j.get("frames"), list))))


# ── Videos (jv-jev.py / jv-score.py, hr12 maxF) ─────────────────────

TOP_K = 3
RANK = {"free": 0, "$10": 1, "$50": 2, "$100": 3}


def max_rec(recs):
    """jv-jev.max_rec: per-question max over frames (Noul: max p; Choice: per-option max, not renormalized; choice = argmax)."""
    out = {}
    for q in recs[0]:
        xs = [r[q] for r in recs if q in r]
        if xs[0]["type"] == "noul": out[q] = {**xs[0], "noul": max(x["noul"] for x in xs)}
        else:
            pr = {o: max(x["probabilities"].get(o, 0) for x in xs) for o in xs[0]["probabilities"]}; out[q] = {**xs[0], "probabilities": pr, "choice": max(pr, key=pr.get)}
    return out


def sev(d): return max(d.get("penetration_p", 0), d.get("crotch_pb", 0), d.get("crotch_n", 0), d.get("breasts_pb", 0), d.get("breasts_n", 0))


def video_targets(recs: list[dict[str, Any]], need: str, k: int = TOP_K) -> list[int]:
    """jv-jev.targets over one video's frame records: the top-`k` frames by `sev` among those derive8 asks `need`
    ("need2" / "needL") for; none asking but the pass-1 per-question max record asking → the top-`k` overall."""
    if not recs:
        return []
    D = [derive8(r) for r in recs]
    comb = derive8({"resp": {"answers": max_rec([r["resp"]["answers"] for r in recs])}})
    pool = [i for i in range(len(recs)) if D[i][need]] or (list(range(len(recs))) if comb.get(need) else [])
    return sorted(pool, key=lambda i: -sev(D[i]))[:k]


def video_final(recs: list[dict[str, Any]], scores: list[dict[str, float]]) -> tuple[list[dict[str, Any]], int]:
    """`final` per frame, and the frame whose lane the video takes (maxF): the highest lane, ties to the higher
    `sev`, then the earlier frame."""
    ds = [final(r, s) for r, s in zip(recs, scores)]
    return ds, max(range(len(ds)), key=lambda i: (RANK[ds[i]["lane5"]], sev(ds[i]), -i))


Order = "list[tuple[str, list[str] | None]]"   # (question, its Choice options in spec order | None for a Noul)


def pack(answers: dict[str, Any], order: Order) -> list[Any]:
    """One pass's answers, positional: a Noul → p, a Choice → [chosen option's index, p per option], 4 dp."""
    out: list[Any] = []
    for q, opts in order:
        x = answers[q]
        if opts is None:
            out.append(round(float(x["noul"]), 4))
        else:
            pr = x["probabilities"]
            out.append([opts.index(x["choice"]), *(round(float(pr.get(o, 0)), 4) for o in opts)])
    return out


def unpack(vals: list[Any], order: Order) -> dict[str, Any]:
    """`pack`'s inverse: the answers shape derive8 reads."""
    out: dict[str, Any] = {}
    for (q, opts), v in zip(order, vals):
        if opts is None:
            out[q] = {"type": "noul", "noul": v}
        else:
            out[q] = {"type": "choice", "choice": opts[v[0]], "probabilities": dict(zip(opts, v[1:]))}
    return out


def video_blob(ds: list[dict[str, Any]], top: int, recs: list[dict[str, Any]], scores: list[dict[str, float]], *,
               frames: list[dict[str, Any]], passes: list[str], tok: int, px: list[list[int]], at: str, src: str,
               review: str | None, nbytes: int) -> dict[str, Any]:
    """A video's `_jev`: the max frame's photo-shaped `blob` (the flags mapper and the describe facts read it
    unchanged) + `kind` video, `vv`, the max `frame`, every frame's packed answers (`frames`), the frame source
    (`src` 720 | 240 | full | poster), `review` (why the reading may be too low: no_720 | over_cap | poster_only |
    few_frames; `vault_ai_brief` keeps such a video out of every free lane) and the downloaded `bytes`. A review
    reading under $100 is `lane5` "review" (an unknown tier: `vault_pack_picker` never prefills it free), its own
    lane kept as `read_lane5` (`read_lane`, what the flags mapper reads); a $100 one cannot be priced too low."""
    b = blob(ds[top], scores[top], passes=passes, tok=tok, px=px[top], at=at, answers=overlay(recs[top], ds[top]))
    b.update(kind="video", vv=VIDEO_VERSION, frame=top, frames=frames, src=src, review=review or None,
             bytes=int(nbytes))
    if review and b["lane5"] != "$100":
        b.update(lane5="review", read_lane5=b["lane5"])
    return b


def read_lane(jev: Any) -> Any:
    """The lane a `_jev` READ: its `lane5`, or a review clip's `read_lane5` (`video_blob`)."""
    lane = (jev or {}).get("lane5")
    return (jev or {}).get("read_lane5") if lane == "review" else lane
