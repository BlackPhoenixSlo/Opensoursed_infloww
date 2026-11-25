from __future__ import annotations

import contextlib
import contextvars
import json
import re
from typing import Any, Iterator

import vault_jev_rules

EXPLICITNESS_LADDER = ("sfw", "suggestive", "explicit", "hardcore")

_REVEAL_TENSION = {
    "dressed": "everything still to come",
    "lingerie_on": "everything still to come",
    "pulled_aside": "the almost-moment — covered, but not covering anything",
    "pulled_down": "mid-strip, caught halfway",
    "partially_off": "mid-strip, caught halfway",
    "fully_nude": "nothing left to reveal — sell the ACT, not the strip",
}

_PAYOFF_ACTS = {
    "fingering", "toy_insertion", "toy_on_clit", "riding_toy", "rubbing_clit",
    "masturbation_orgasm", "squirt", "blowjob", "handjob", "cumshot",
    "sex_missionary", "sex_doggy", "sex_riding",
}


# Enum, not booleans: not_in_frame is a stated answer so absence of evidence cannot read as safe; top state is bare (a "visible" label pulled the model to answer yes on tank tops).
VIS_STATES: tuple[str, ...] = ("not_in_frame", "covered", "bare")

_VIS_RANK = {s: i for i, s in enumerate(VIS_STATES)}

# anus is separate from the rest of the rear: a bare backside is fine in a mass send, an exposed anus is not.
VIS_REGIONS: tuple[str, ...] = ("vulva_vis", "breasts_vis", "anus_vis")

FLAG_KEYS: tuple[str, ...] = ("underwear_visible", *VIS_REGIONS)

FLAGS_VERSION = 3

OVER_KEYS: dict[str, str] = {"breasts_vis": "over_breasts",
                             "vulva_vis": "over_vulva",
                             "anus_vis": "over_anus"}


_IMPOSSIBLE_OVER: dict[str, frozenset[str]] = {
    "breasts_vis": frozenset({"thong", "panties", "panty", "knickers", "briefs",
                              "g-string", "gstring", "shorts", "skirt",
                              "stockings", "socks", "boots", "heels"}),
    "vulva_vis": frozenset({"bra", "bralette", "top", "tank", "t-shirt",
                            "tshirt", "blouse", "shirt", "necklace", "choker"}),
    "anus_vis": frozenset({"bra", "bralette", "top", "tank", "t-shirt",
                           "tshirt", "blouse", "shirt", "necklace", "choker"}),
}


def garment_over(fields: dict[str, Any] | None, region: str) -> str:
    if not isinstance(fields, dict):
        return ""
    v = fields.get(OVER_KEYS.get(region, ""))
    if not isinstance(v, str):
        return ""
    name = v.strip()
    impossible = _IMPOSSIBLE_OVER.get(region, frozenset())
    words = {w for w in re.split(r"[\s,./-]+", name.lower()) if w}
    return "" if words & impossible else name


_NOT_CLOTHING = frozenset({
    "hand", "hands", "finger", "fingers", "palm", "fist", "arm", "arms",
    "forearm", "elbow", "wrist", "thigh", "thighs", "leg", "legs", "knee",
    "knees", "hair", "shadow", "shadows", "angle", "pose", "body", "back",
    "sheet", "sheets", "bedsheet", "bedsheets", "bedding", "blanket", "duvet",
    "pillow", "pillows", "cushion", "mattress", "bed",
})

_FILLER = frozenset({"her", "his", "the", "a", "an", "own", "of", "and", "is",
                     "over", "on", "across", "left", "right", "both", "one"})


def is_clothing(name: str) -> bool:
    words = [w for w in re.split(r"[\s,./-]+", (name or "").lower()) if w]
    content = [w for w in words if w not in _FILLER]
    if not content:
        return False
    return not all(w in _NOT_CLOTHING or w.rstrip("s") in _NOT_CLOTHING
                   for w in content)


def wearing_something(fields: dict[str, Any] | None) -> bool:
    return any(is_clothing(garment_over(fields, r)) for r in OVER_KEYS)


def flags_known(fields: dict[str, Any] | None) -> bool:
    if not isinstance(fields, dict):
        return False
    if not isinstance(fields.get("underwear_visible"), bool):
        return False
    return all(fields.get(r) in _VIS_RANK for r in VIS_REGIONS)


def vis(fields: dict[str, Any] | None, region: str) -> str:
    if not isinstance(fields, dict):
        return ""
    v = fields.get(region)
    return v if v in _VIS_RANK else ""


def is_bare(fields: dict[str, Any] | None, region: str) -> bool:
    return vis(fields, region) == "bare"


def any_bare(fields: dict[str, Any] | None,
             regions: tuple[str, ...] = VIS_REGIONS) -> bool:
    return any(is_bare(fields, r) for r in regions)


def fold_vis(states: list[str]) -> str:
    ranked = [_VIS_RANK[s] for s in states if s in _VIS_RANK]
    return VIS_STATES[max(ranked)] if ranked else ""


CONTRADICTIONS: dict[str, str] = {
    "dressed_but_bare": "clothing_state=dressed, yet a bare region is visible",
    "sfw_but_bare": "explicitness=sfw, yet a bare region is visible",
    "nude_but_clothed": "clothing_state=fully_nude, yet a garment is visible",
    "lingerie_but_nothing_on": "clothing_state=lingerie_on, yet no garment is visible",
    "penetration_offscreen": "genital act recorded, yet neither vulva nor anus is in frame",
    "jev_review": "Jev read this clip off low-res, partial or poster frames, so its lane may be too low",
    "jev_bare_unflagged": "Jev reads a region bare or a paid lane (or its stored frames do not decode), yet the "
                          "stored flags / tier do not say so",
}

PENETRATING_ACTS: frozenset[str] = frozenset({
    "fingering", "toy_insertion", "riding_toy", "sex_missionary",
    "sex_doggy", "sex_riding",
})
GENITAL_ACTS: frozenset[str] = PENETRATING_ACTS | frozenset({
    "rubbing_clit", "toy_on_clit", "squirt",
})
_NO_PENETRATION: frozenset[str] = frozenset({"", "none", "unclear"})


def penetration_claimed(fields: dict[str, Any] | None) -> bool:
    if not isinstance(fields, dict):
        return False
    if _scalar(fields, "penetration").lower().strip() not in _NO_PENETRATION:
        return True
    return bool({a.lower() for a in _clean(fields.get("acts"))} & PENETRATING_ACTS)


def genital_act_claimed(fields: dict[str, Any] | None) -> bool:
    if penetration_claimed(fields):
        return True
    if not isinstance(fields, dict):
        return False
    return bool({a.lower() for a in _clean(fields.get("acts"))} & GENITAL_ACTS)


_MEMO: contextvars.ContextVar[dict | None] = contextvars.ContextVar("vault_ai_brief_memo", default=None)


@contextlib.contextmanager
def reading_memo() -> Iterator[None]:
    if _MEMO.get() is not None:
        yield
        return
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


def _memo(name: str, fields: Any, extra: Any, derive: Any) -> Any:
    memo = _MEMO.get()
    if memo is None:
        return derive()
    key = (name, id(fields), extra)
    hit = memo.get(key)
    if hit is None or hit[0] is not fields:
        hit = memo[key] = (fields, derive())
    return hit[1]


def contradictions(fields: dict[str, Any] | None) -> list[str]:
    return list(_memo("codes", fields, None, lambda: _contradictions(fields)))


def _contradictions(fields: dict[str, Any] | None) -> list[str]:
    if not isinstance(fields, dict):
        return []
    jev = fields.get(vault_jev_rules.JEV_KEY)
    review = ["jev_review"] if isinstance(jev, dict) and jev.get("review") else []
    if vault_jev_rules.current(fields):
        body = vault_jev_rules.body(jev)
        jev_bare = vault_jev_rules.bare_regions(jev, body)
        if jev_bare is not None and (
                vault_jev_rules.UNDECODED in body.values()
                or any(b and not is_bare(fields, r) for r, b in jev_bare.items())
                or (vault_jev_rules.read_lane(jev) in vault_jev_rules.PAID
                    and _scalar(fields, "explicitness").lower() in _FREE_TIERS)):
            review.append("jev_bare_unflagged")
    if not flags_known(fields):
        return review
    cl = _scalar(fields, "clothing_state").lower()
    tier = _scalar(fields, "explicitness").lower()
    garment = fields.get("underwear_visible")
    bare = any_bare(fields)
    out: list[str] = []

    if cl == "dressed" and bare:
        out.append("dressed_but_bare")
    if tier == "sfw" and bare:
        out.append("sfw_but_bare")
    if cl == "fully_nude" and garment is True:
        out.append("nude_but_clothed")
    if cl == "lingerie_on" and garment is False:
        out.append("lingerie_but_nothing_on")

    if genital_act_claimed(fields) \
            and vis(fields, "vulva_vis") == "not_in_frame" \
            and vis(fields, "anus_vis") == "not_in_frame":
        out.append("penetration_offscreen")
    return out + review



SETTLED_KEY = "_settled"

_PAID_TIERS = ("explicit", "hardcore")
_FREE_TIERS = ("sfw", "suggestive")

_CLOTHING_FOR = {
    (False, False): "lingerie_on",
    (True, False): "pulled_down",
    (False, True): "pulled_aside",
    (True, True): "partially_off",
}

_CLOTHING_WORN = {
    (True, True): "lingerie_on",
    (False, True): "pulled_down",
    (True, False): "pulled_aside",
    (False, False): "partially_off",
}

_HEDGE_NUDITY = frozenset({"dressed_but_bare", "sfw_but_bare"})


def _worn(fields: dict[str, Any], region: str) -> bool:
    return is_clothing(garment_over(fields, region))


def settled_reading(fields: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(fields, dict) or SETTLED_KEY in fields:
        return fields
    codes = contradictions(fields)
    if not codes:
        return fields
    out = dict(fields)
    out[SETTLED_KEY] = codes
    bare_b = is_bare(fields, "breasts_vis")
    bare_v = is_bare(fields, "vulva_vis")
    if "nude_but_clothed" in codes:
        out["clothing_state"] = _CLOTHING_WORN[
            (_worn(fields, "breasts_vis"), _worn(fields, "vulva_vis"))]
    if "lingerie_but_nothing_on" in codes:
        out["clothing_state"] = (_CLOTHING_FOR[(bare_b, bare_v)]
                                 if bare_b or bare_v else "dressed")
    if _HEDGE_NUDITY & set(codes) \
            and _scalar(fields, "explicitness").lower() not in _PAID_TIERS:
        out["explicitness"] = "explicit"
    return out


def settled_codes(fields: dict[str, Any] | None) -> list[str]:
    if not isinstance(fields, dict):
        return []
    marked = fields.get(SETTLED_KEY)
    return list(marked) if isinstance(marked, list) else contradictions(fields)


def is_disputed(fields: dict[str, Any] | None) -> bool:
    return bool(settled_codes(fields))


def free_vetoed(fields: dict[str, Any] | None) -> bool:
    return is_disputed(fields) or any_bare(fields)


def claimed_acts(fields: dict[str, Any] | None) -> list[str]:
    if not isinstance(fields, dict):
        return []
    acts = _clean(fields.get("acts"))
    if "penetration_offscreen" in settled_codes(fields):
        acts = [a for a in acts if a.lower() not in GENITAL_ACTS]
    return acts


def _copy_clothing(fields: dict[str, Any]) -> str:
    if _HEDGE_NUDITY & set(settled_codes(fields)):
        return "dressed"
    return _scalar(fields, "clothing_state").lower()


def settled_notes(fields: dict[str, Any] | None) -> list[str]:
    if not isinstance(fields, dict):
        return []
    codes = settled_codes(fields)
    s = settled_reading(fields) or {}
    how = {
        "nude_but_clothed": f"read as {s.get('clothing_state')}",
        "lingerie_but_nothing_on": f"read as {s.get('clothing_state')}",
        "dressed_but_bare": f"priced as {s.get('explicitness')}, copy claims no nudity",
        "sfw_but_bare": f"priced as {s.get('explicitness')}, copy claims no nudity",
        "penetration_offscreen": "copy claims no genital act",
        "jev_review": f"priced as {s.get('explicitness')}, describe hedged",
        "jev_bare_unflagged": ("never free until Jev re-reads it" if vault_jev_rules.undecoded(
            fields.get(vault_jev_rules.JEV_KEY)) else "never free until the flags re-stamp from Jev"),
    }
    out = [f"{CONTRADICTIONS[c]} → {how[c]}" for c in codes]
    if codes:
        out.append("never in a free lane")
    return out


def load_fields(raw: str | dict | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        out = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def _clean(v: Any) -> list[str]:
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v
            if str(x).strip() and str(x).strip().lower() not in ("none", "unclear")]


def _scalar(fields: dict, key: str) -> str:
    v = fields.get(key)
    s = str(v).strip() if v is not None else ""
    return "" if s.lower() in ("", "none", "unclear") else s


def sellability(fields: dict[str, Any], *, duration_seconds: int | None = None
                ) -> dict[str, Any]:
    got = _memo("sell", fields, duration_seconds, lambda: _sellability(fields, duration_seconds=duration_seconds))
    return {**got, "payoff_acts": list(got["payoff_acts"])}


def _sellability(fields: dict[str, Any], *, duration_seconds: int | None = None
                 ) -> dict[str, Any]:
    fields = settled_reading(fields) or {}
    acts = {a.lower() for a in claimed_acts(fields)}
    offscreen = "penetration_offscreen" in settled_codes(fields)
    tier = _scalar(fields, "explicitness").lower()
    people = fields.get("people_count")
    partner = fields.get("partner_visible")
    payoff = sorted(acts & _PAYOFF_ACTS)
    solo: bool | None
    if partner is True:
        solo = False
    elif isinstance(people, int):
        solo = people <= 1 and partner is not True
    else:
        solo = None
    return {
        "stands_alone": bool(payoff),
        "payoff_acts": payoff,
        "rung": EXPLICITNESS_LADDER.index(tier) if tier in EXPLICITNESS_LADDER else None,
        "tier": tier or "unknown",
        "solo": solo,
        "penetration": "" if offscreen else _scalar(fields, "penetration"),
        "clothing": _copy_clothing(fields),
        "reveal": _REVEAL_TENSION.get(_copy_clothing(fields), ""),
        "seconds": int(duration_seconds) if duration_seconds else None,
        "sellable_flag": fields.get("sellable"),
    }





def item_facts(fields: dict[str, Any], *, description: str = "",
               duration_seconds: int | None = None, kind: str = "") -> str:
    s = sellability(fields, duration_seconds=duration_seconds)
    lines: list[str] = []

    if description.strip():
        lines.append(f"WHAT IT IS: {description.strip()}")

    beats = _clean(fields.get("beats"))
    if beats:
        lines.append("SEQUENCE (in order — beat 1 is how it opens, the last beat "
                     "is the payoff):")
        lines += [f"  {i}. {b}" for i, b in enumerate(beats, 1)]

    def add(label: str, value: str) -> None:
        if value:
            lines.append(f"{label}: {value}")

    add("ACTS", ", ".join(_clean(fields.get("acts"))))
    add("PENETRATION", s["penetration"] + (
        f" ({_scalar(fields, 'insertion_depth')})" if _scalar(fields, "insertion_depth") else ""))
    cl = _scalar(fields, "clothing_state")
    if cl:
        add("CLOTHING", f"{cl}" + (f" — {s['reveal']}" if s["reveal"] else ""))
    add("WEARING", ", ".join(_clean(fields.get("clothing_items"))))
    add("TOYS", ", ".join(_clean(fields.get("toys"))))
    add("POSITION", _scalar(fields, "position"))
    add("SETTING", _scalar(fields, "setting"))
    add("SHOT", _scalar(fields, "camera"))

    who = []
    if s["solo"] is True:
        who.append("SOLO — she is alone")
    elif s["solo"] is False:
        who.append("PARTNER PRESENT — do NOT write this as solo")
    if fields.get("face_visible") is True:
        who.append("her face is visible (you may promise eye contact)")
    elif fields.get("face_visible") is False:
        who.append("her face is NOT visible (do not promise eye contact)")
    if who:
        lines.append("WHO: " + "; ".join(who))

    tier = s["tier"]
    rung = f" (rung {s['rung'] + 1} of {len(EXPLICITNESS_LADDER)})" if s["rung"] is not None else ""
    lines.append(f"HEAT: {tier}{rung}; "
                 + ("CLOSES ON ITS OWN — payoff: " + ", ".join(s["payoff_acts"])
                    if s["stands_alone"] else
                    "BUILD-UP ONLY — no payoff act, so it teases the next send"))
    if s["seconds"]:
        lines.append(f"LENGTH: {s['seconds']}s")
    if kind:
        lines.append(f"TYPE: {kind}")

    conf = fields.get("confidence")
    if isinstance(conf, int) and conf < 70:
        lines.append(f"⚠ LOW CONFIDENCE ({conf}) — the vision pass was unsure. "
                     "Stay general; do not promise specific details.")
    return "\n".join(lines)


SELLING_BRIEF = """\
HOW TO USE THE FACTS ABOVE

You are selling ONE piece of a creator's own content to a fan in DMs. The facts
block is what a vision model actually saw in the media — it is ground truth.
Everything you write must be true against it.

THE HARD RULE
  Never promise something the facts don't list. If PENETRATION is absent, she is
  not penetrated. If it says BUILD-UP ONLY, do not imply she finishes. If PARTNER
  PRESENT appears, never frame it as solo. Selling a thing that isn't in the
  media is what produces refunds and chargebacks — a vaguer line that is TRUE
  outsells a specific line that is false.

FINDING THE SELLABLE MOMENT
  SEQUENCE is the clip's actual progression. The sellable moment is almost never
  beat 1 — it is the beat where the state CHANGES (she pulls something aside, the
  toy goes in, she stops posing and starts doing). Find that beat and build the
  copy around it. The beats are also the honest source for "what happens next",
  which is the only tease that survives the fan actually watching.

  REVERSE ORDER — read the beats BACKWARD when the payoff is the better hook.
  Lead with the last beat's result, then withhold how she got there:
  "…by the end my [X] was [state]. want to see how I got there?" This works when
  the final beat is stronger than the opening one. Keep the forward order when
  the build-up is the appeal (a slow strip sells the anticipation, not the end).
  Either way the FACTS stay the same — you are choosing a narration order, not
  inventing a different clip.

CLOTHING is the tension axis
  pulled_aside / pulled_down are the highest-value states: still covered, not
  covering anything. Name the garment (WEARING) — the specific detail is what
  makes it read as a real memory instead of a template. When CLOTHING is
  fully_nude there is no reveal left to promise, so sell the ACT instead.

STANDS ALONE vs BUILD-UP
  "CLOSES ON ITS OWN" = this can be the ask by itself; write copy that lands a
  purchase now. "BUILD-UP ONLY" = this is a rung; write copy that makes the NEXT
  send inevitable, and do not over-promise a finish it does not contain.

HEAT is the ladder position
  sfw → suggestive → explicit → hardcore. Going UP across a night is escalation;
  each send should read one notch hotter than the last. Going DOWN is also a
  real move: for a fan who already bought the top rung, a lower-rung piece is
  sold as intimacy ("just me, no show") rather than as more.

CONCRETENESS THAT SELLS
  POSITION, SETTING, SHOT and TOYS are what stop copy sounding generic. A
  closeup promises detail; a mirror or pov shot promises "you're there"; a named
  toy is proof it's real. Use one or two, not all of them — a list is inventory,
  not seduction.

SOLO PIECES
  When WHO says SOLO, the strongest frame is that it was made alone and
  privately — "I was thinking about you" is available to you, and it is the
  highest-converting solo frame precisely because it is about HIM, not the media.
  That frame is a lie for partner content, so it is off the table there.
"""


def copy_brief(fields: dict[str, Any], *, description: str = "",
               duration_seconds: int | None = None, kind: str = "") -> str:
    facts = item_facts(fields, description=description,
                       duration_seconds=duration_seconds, kind=kind)
    return f"{facts}\n\n{SELLING_BRIEF}"
