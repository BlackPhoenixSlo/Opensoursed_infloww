"""service/vault_ai_vision_decide.py — the pure decisions of the vision passes.

No DB, no IO, no LLM: what `vault_ai_vision` hands a model answer / a row to and
gets a verdict back. Table-tested in tests/test_vault_ai_vision_decide.py.

  flags fold        _garment_over, _ground_in_named_garment, _reconcile_with_acts,
                    _fold_clip_flags, _clip_arc
  describe          _frames_for_duration, _parse_describe, next_attempt,
                    describe_answer, prompt_variant, build_describe_update,
                    with_flags_cost
  flags merge       build_flags_fields — the row's ai_fields after a flags run.
  selection         live_describable (the base every vision sweep walks) and
                    describe_selection — the ONE predicate both the describe-all
                    sweep and its plan count read, so the two cannot drift.
  order             priority_order — the ONE walk order of both sweeps.
  reuse             reuse_plan, build_copy_update, build_flags_copy — one
                    vision answer shared across a duplicate set.
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, NamedTuple

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

import vault_ai_brief
import vault_describe_jev
from db.models import VaultItem
from vault_of_folders_decide import parse_folder_ids


# What the model writes in an `over_` field when it means "nothing there". It
# is told to use null; it also says these.
_NOTHING_OVER = frozenset({"", "null", "none", "nothing", "n/a", "na", "nil",
                           "not_in_frame", "not in frame", "nude", "naked",
                           "no clothing", "no garment", "uncovered", "exposed"})

# The model is told to answer null and mostly does, but it also narrates the
# absence — "nothing, bare skin", "no clothing - she is bare". Any answer whose
# words are only about there being nothing there is nothing there. Matched on
# words rather than on the whole string so the phrasings do not have to be
# enumerated: a real garment always contributes a word that is not in this set.
_ABSENCE_WORDS = frozenset({"bare", "skin", "nothing", "no", "not", "none",
                            "null", "n/a", "visible", "is", "she", "her",
                            "exposed", "uncovered", "nude", "naked", "at",
                            "all", "and", "the", "a", "-", "—", ","})


def _garment_over(answer: dict[str, Any], key: str) -> str:
    """The named garment/object over a region, or "" for nothing.

    Errs toward "nothing": a false garment silently marks an exposed region
    covered, which is the direction that puts explicit material in a mass send.
    A false absence only costs the override, and the state field still stands.
    """
    v = answer.get(key)
    if not isinstance(v, str):
        return ""
    s = v.strip()
    if s.lower().strip(".") in _NOTHING_OVER:
        return ""
    words = [w for w in re.split(r"[\s,./-]+", s.lower()) if w]
    return "" if words and all(w in _ABSENCE_WORDS for w in words) else s


def _ground_in_named_garment(answer: dict[str, Any]) -> dict[str, Any]:
    """Let what the model NAMED overrule what it CLASSIFIED.

    Asking for a state directly ("is her chest bare?") measured badly in both
    polarities: `covered` pulled toward false on anything racy, and `bare` came
    back on a white tank top and a black halter top, because a one-word verdict
    invites the model to answer the vibe of the picture. Naming the garment is
    a much easier question and the describe pass already answers it correctly —
    the same model wrote "wearing a white tank top" in prose about the same
    photo it then called bare.

    So the naming is made LOAD-BEARING rather than advisory: name something over
    a region and the region is covered, whatever the state field said. Only
    `bare` is overridden — `not_in_frame` is left alone, because a garment can
    be named on a body part that is genuinely out of shot.
    """
    out = dict(answer)
    for region, over in vault_ai_brief.OVER_KEYS.items():
        if out.get(region) == "bare" and _garment_over(out, over):
            out[region] = "covered"
        elif out.get(region) == "not_in_frame":
            # Nothing can be over a part of her that is not in the picture.
            # The model still names the one garment it can see for EVERY
            # region — a woman face down in a bodystocking came back with
            # "black lace bodysuit" over her anus. Left in place that name
            # reads downstream as evidence she is dressed there.
            out.pop(over, None)
    return out


# Acts that cannot happen through fabric. Insertion only — `rubbing_clit` and
# `groping_own_breasts` are both perfectly possible over underwear, so they are
# deliberately absent: this list has to be airtight or it manufactures exposure
# rather than detecting it.
_INSERTION_ACTS = frozenset({
    "fingering", "toy_insertion", "riding_toy",
    "sex_missionary", "sex_doggy", "sex_riding",
})
_REAL_PENETRATION = frozenset({"fingers", "toy", "penis"})


def _reconcile_with_acts(fields: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Let what is HAPPENING overrule what the flags pass thought it saw.

    The flags pass looks at one frame and names the garment nearest the action,
    then calls the region covered. On this vault that produced, verbatim: "A
    hand is inserting two fingers into the vagina" with `vulva_vis: covered,
    over_vulva: 'pink lace thong'`. Fingers do not go through a thong. Four of
    the operator's fourteen round-2 corrections were this exact shape, and all
    four were on the most explicit — which is to say most valuable — items in
    the vault.

    Deliberately narrow. Only INSERTION counts, because insertion is physically
    incompatible with a covered region; rubbing and groping happen over
    underwear all the time and would turn this into a machine for inventing
    exposure. A rule that gates money and mass sends has to be right in the
    direction it fires, not merely often right.
    """
    acts = {str(a).strip().lower() for a in (fields.get("acts") or [])}
    pen = str(fields.get("penetration") or "").strip().lower()
    if not (acts & _INSERTION_ACTS or pen in _REAL_PENETRATION):
        return data
    focus = {str(x).strip().lower() for x in (fields.get("body_focus") or [])}
    out = dict(data)
    # Anal only when the row actually says so; otherwise insertion means vulva.
    region = "anus_vis" if (focus & {"anus"}) and "pussy" not in focus else "vulva_vis"
    if out.get(region) == "covered":
        out[region] = "bare"
        out.pop(vault_ai_brief.OVER_KEYS[region], None)
    return out


def _fold_clip_flags(per_frame: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold per-frame answers into one verdict for the whole clip.

    Regions fold by MAX exposure (`vault_ai_brief.fold_vis`) and
    `underwear_visible` by `any()` — both conservative, which is the right
    default for flags that gate what may be shown publicly and what is priced
    as a full reveal.

    The v1 fold was `all()` over "covered" booleans, and it collapsed: a frame
    that could not see the region answered `covered=False`, indistinguishable
    from a frame where she was bare, so ANY frame that simply missed the region
    marked the whole clip uncovered. 20 of 21 the graded vault clips folded to
    uncovered, which is no signal at all. With `not_in_frame` as its own state
    those frames fold away instead of voting for exposure.

    Deliberately folded HERE rather than asked of the model. The reason this
    pass exists at all is that the model got `fully_nude` wrong; making it also
    reason across frames would add a second thing it can get wrong, on top of a
    question it has already been measured good at one image at a time.
    """
    out: dict[str, Any] = {}
    seen = [bool(f["underwear_visible"]) for f in per_frame
            if isinstance(f.get("underwear_visible"), bool)]
    if seen:
        out["underwear_visible"] = any(seen)
    for region in vault_ai_brief.VIS_REGIONS:
        folded = vault_ai_brief.fold_vis([str(f.get(region) or "") for f in per_frame])
        if folded:
            out[region] = folded
    return out


def _clip_arc(per_frame: list[dict[str, Any]]) -> str | None:
    """Which way the clip escalates, from the frames already paid for.

    Compares how much is on show in the first frame against the last. A clip
    that opens covered and ends bare is a build-up; the reverse is a payoff
    that was uploaded (or shot) back to front. `vault_scripts` currently infers
    this direction with a rank correlation across SEPARATE items, which is a
    far weaker signal than watching one clip change — so this is recorded now
    even though nothing reads it yet.
    """
    if len(per_frame) < 2:
        return None
    def heat(f: dict[str, Any]) -> int:
        ranks = [vault_ai_brief.VIS_STATES.index(f[r]) for r in vault_ai_brief.VIS_REGIONS
                 if f.get(r) in vault_ai_brief.VIS_STATES]
        return max(ranks) if ranks else -1
    first, last = heat(per_frame[0]), heat(per_frame[-1])
    if first < 0 or last < 0 or first == last:
        return "flat"
    return "escalates" if last > first else "reverses"


def build_flags_fields(prev: Mapping[str, Any], per_frame: list[dict[str, Any]], *,
                       locked: Collection[str], is_video: bool, model: str,
                       version: int) -> dict[str, Any]:
    """The row's `ai_fields_json` after a flags run: `prev` (its current blob)
    with the folded, act-reconciled flags MERGED in. Never touches the
    description, tags or taxonomy — enrichment only. `per_frame` is non-empty
    (each entry already `_ground_in_named_garment`-ed); `version` is the flags
    prompt version stamped as `_flags_v`."""
    fields = dict(prev)
    data = _reconcile_with_acts(fields, _fold_clip_flags(per_frame))
    # An operator correction outranks the model, and must survive a forced
    # re-run — otherwise the next `flags-all --force` silently reverts it and
    # the operator has no reason to look at the item again. Same override+lock
    # contract `vault_ai_effective` defines for `description`; `vault_ai_fix`
    # writes the lock.
    for key in vault_ai_brief.FLAG_KEYS:
        if key in data and key not in locked:
            fields[key] = data[key]
    # Persisted, not merely used and discarded. Two jobs: when a region says
    # `covered` this is WHY in the model's own words (a wrong flag is far
    # cheaper to diagnose from "white tank top" than from "covered"), and
    # `vault_scripts._is_nude` reads it as the direct evidence that she is
    # dressed. Taken from the FIRST frame, which is where a clip starts out.
    for over in vault_ai_brief.OVER_KEYS.values():
        if over in locked:
            continue
        named = _garment_over(per_frame[0], over)
        if named:
            fields[over] = named[:60]
        else:
            fields.pop(over, None)
    if is_video:
        fields["_flags_frames"] = len(per_frame)
        arc = _clip_arc(per_frame)
        if arc:
            fields["_flags_arc"] = arc
    # Superseded shapes, dropped rather than left to rot: `genitals_covered`
    # conflated vulva and breasts, and the `*_covered` pair asked two opposite
    # questions under one name. Leaving either behind would let a caller that
    # was never updated keep reading a stale answer that looks current.
    for dead in ("genitals_covered", "pussy_covered", "breasts_covered"):
        fields.pop(dead, None)
    fields["_flags_model"] = model
    fields["_flags_v"] = version
    # A recovered item must stop reporting the failure it recovered from, and
    # flags of its OWN are no longer a copy of anyone's.
    for stale in ("_flags_status", "_flags_failed_at", "_flags_error", FLAGS_COPY_MARK):
        fields.pop(stale, None)
    return fields


# Frames per clip. V1 shipped a hardcoded 3 for a clip of ANY length (a 17-minute
# video was summarised from 3 stills); the bake-off's other real lever was
# raising this to 9 (`vault_frames.DESCRIBE_FRAMES`). Photos always send 1.
#
# …but a flat count is wrong in both directions: 12 stills of a 3-second clip is
# 4× the tokens for the same one moment, and 9 stills of a 17-minute session
# still misses most of it. Measured 2026-07-21 (`_probe_frames_vs_duration.py`,
# 6 long clips × 4 counts × 3 repeats, scored as coverage of the pooled union of
# every finding across all runs — NOT against one reference run, which is
# noise):
#
#     frames    coverage    mean beats
#          3         38%           1.9
#          6         49%           2.7
#          9         47%           2.9
#         12         55%           3.7
#
# 3→6 is a real jump; 6→9 is flat (inside run-to-run variance); 9→12 gains ~8pp
# and 27% more `beats`, which IS the progression a long clip needs. `beats` is
# the cleanest signal because it rises monotonically with frame count.
#
# 12 is the ceiling: `server._STORYBOARD_FRAMES = 12`, already extracted and
# cached, so using all of them costs nothing but vision tokens.
#
# CAVEAT worth remembering: no frame count exceeds ~55% coverage, and two
# IDENTICAL 12-frame runs agree only ~75% with each other. A single describe
# pass on a long clip is inherently lossy — for `epic` clips, two passes unioned
# would gain more than any frame-count change.
_FRAME_LADDER: tuple[tuple[int, int], ...] = (
    (30, 6),      # < 30s   — one moment; more stills just re-see it
    (180, 9),     # < 3min
)
_FRAME_LADDER_MAX = 12  # >= 3min, and the storyboard ceiling


def _frames_for_duration(seconds: int | None) -> int:
    """How many stills a clip of this length gets (see `_FRAME_LADDER`)."""
    s = int(seconds or 0)
    for limit, n in _FRAME_LADDER:
        if s < limit:
            return n
    return _FRAME_LADDER_MAX


def _parse_describe(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


# The model a refused/blank describe escalates to — once.
ESCALATION_MODEL = "qwen3-vl-235b"


def next_attempt(model: str, refused_or_blank: bool) -> str | None:
    """The model to try next after one describe attempt on `model`, or None.

    Try the asked model; on a refusal or a blank answer escalate ONCE to 235b
    (never overwrite a good existing description with a blank). An answer, or a
    refusal from 235b itself, ends it."""
    if not refused_or_blank or model == ESCALATION_MODEL:
        return None
    return ESCALATION_MODEL


# What a vision model can be shown. An audio file has no frame, so sweeping it is
# not thoroughness — it is a row of guaranteed failure per pass (591 of them on
# two accounts), and the 45 whose signatures were still valid had their MP3 bytes
# posted to a vision endpoint as an image, which is what `describe_status =
# 'failed'` recorded. The flags sweep has always filtered this way; the describe
# sweep and its cost estimate never did, so the estimate quoted a total the sweep
# could not meet.
_DESCRIBABLE_KINDS = ("photo", "video")

DescribeMode = Literal["force", "restage", "undescribed"]


def live_describable(account_id: str) -> ColumnElement[bool]:
    """The rows of `account_id` any vision sweep (describe AND flags) may visit:
    still on OF and a kind a vision model can be shown."""
    return and_(VaultItem.account_id == account_id,
                VaultItem.removed_at.is_(None),
                VaultItem.kind.in_(_DESCRIBABLE_KINDS))


def describe_selection(account_id: str, mode: DescribeMode,
                       pv: str) -> ColumnElement[bool]:
    """Which rows a describe sweep in `mode` visits — the WHOLE where clause,
    read by BOTH `_run_describe_all` and `describe_all_plan`, so the count on
    the button is the set the sweep walks.

      "force"       — every live, describable row, regardless.
      "restage"     — items described by a DIFFERENT prompt version, i.e. the
                      "we have a better prompt now, re-scan the old rows" pass.
                      Cheaper than force: rows already on this version are left
                      alone, so an interrupted re-scan resumes instead of
                      starting over.
      "undescribed" — only items not yet successfully described.
    """
    base = live_describable(account_id)
    if mode == "force":
        return base
    if mode == "restage":
        # `_prompt_version` is stamped into ai_fields_json by _describe_one.
        # A row that predates the stamp has no marker at all, so it counts
        # as stale and gets re-scanned.
        return and_(base,
                    (VaultItem.describe_status != "described")
                    | (VaultItem.describe_status.is_(None))
                    | (VaultItem.ai_fields_json.is_(None))
                    | (~VaultItem.ai_fields_json.like(f'%"_prompt_version": "{pv}"%')))
    if mode == "undescribed":
        # Everything not already described — INCLUDING blocked_drm, with
        # no cool-off. This is a button a person pressed, having just read the
        # count on it, and the one thing it must do is attempt what that
        # count promised. Honouring the cooldown made it silently skip
        # 1,777 of the 1,777 items it offered to describe — the operator
        # clicks, watches nothing happen, and has no way to find out why.
        # A wasted fetch is cheaper than a control nobody can trust.
        return and_(base, VaultItem.describe_status.isnot("described"))
    raise ValueError(f"unknown describe mode: {mode!r}")


def describe_answer(data: Mapping[str, Any]) -> dict[str, Any]:
    """The headline fields of one describe answer, as stored and as returned."""
    tier = data.get("explicitness")  # sfw|suggestive|explicit|hardcore
    return {
        "description": str(data.get("description") or ""),
        "tags": [str(t).lower().strip() for t in (data.get("tags") or [])
                 if str(t).strip()][:12],
        "explicitness_tier": str(tier) if tier else None,
        "nsfw": bool(data.get("nsfw")) if data.get("nsfw") is not None else None,
        "sellable": bool(data.get("sellable")) if data.get("sellable") is not None else None,
    }


def with_flags_cost(describe_res: Mapping[str, Any],
                    flags_res: Mapping[str, Any] | None) -> dict[str, Any]:
    """Describe's result with the auto-flag call's cost added: describe-and-flag
    bills both, and the sweep reports what its items' results carry. No flags
    result (it raised / never ran) or no cost on it: describe's cost unchanged —
    an unparsed flags answer carries none, so that billed call is not reported."""
    out = dict(describe_res)
    if flags_res and "cost_millicents" in flags_res:
        out["cost_millicents"] = (int(out.get("cost_millicents") or 0)
                                  + int(flags_res.get("cost_millicents") or 0))
    return out


def with_jev(res: Mapping[str, Any], jev_res: Mapping[str, Any] | None) -> dict[str, Any]:
    """`res` (a describe / flags result) with the Jev pass that ran before it
    folded in: its spend added to `cost_millicents` (the sweep sums it) and its
    outcome as `jev_status` / `jev_lane5` / `jev_cost_millicents`. No Jev
    result (setting off, not a photo): `res` unchanged."""
    out = dict(res)
    if not jev_res:
        return out
    jc = int(jev_res.get("cost_millicents") or 0)
    out["cost_millicents"] = int(out.get("cost_millicents") or 0) + jc
    out["jev_status"] = jev_res.get("status")
    out["jev_cost_millicents"] = jc
    if jev_res.get("lane5"):
        out["jev_lane5"] = jev_res["lane5"]
    if jev_res.get("detail") and not jev_res.get("ok"):
        out["jev_detail"] = str(jev_res["detail"])[:200]
    return out


def prompt_variant(prompt_version: Any) -> str:
    """The describe prompt variant: "v1" only when asked for exactly, else "v2"."""
    return "v1" if str(prompt_version) == "v1" else "v2"


def build_describe_update(is_video: bool, data: Mapping[str, Any], *,
                          prev_ai: Mapping[str, Any], locked: Collection[str],
                          overrides: Mapping[str, Any], used_model: str,
                          n_frames: int, pv: str, fixable: Collection[str],
                          call_id: int | None, now: datetime) -> dict[str, Any]:
    """The `VaultItem` column values a successful describe writes.

    `prev_ai` / `overrides` are the row's current `ai_fields_json` /
    `operator_overrides_json`; `fixable` is `vault_ai_fix.FIXABLE`."""
    ans = describe_answer(data)
    desc, tags, sellable = ans["description"], ans["tags"], ans["sellable"]
    # Fold the V2 taxonomy into the local search blob too, so a search for
    # "pulled_aside" or "solo_toy" hits even though those never appear in the
    # prose. `beats` carries the clip's progression, which is often the only
    # place a mid-clip act is named at all.
    v2_terms: list[str] = []
    for key in ("acts", "body_focus", "toys", "clothing_items", "beats"):
        v2_terms += [str(x) for x in (data.get(key) or []) if str(x).strip()]
    for key in ("clothing_state", "penetration", "position", "setting",
                "camera", "primary_folder"):
        if data.get(key):
            v2_terms.append(str(data[key]))
    search_text = " ".join([desc, *tags, *v2_terms]).lower()

    # Stamp WHICH variant produced this row: a v1 row is a candidate for a later
    # v2 re-scan, and without the stamp "already described" is ambiguous.
    out = {**data, "_prompt_version": prompt_variant(pv),
           "_frames": n_frames}

    # `ai_fields_json` is written whole from `data`, which holds ONLY what the
    # describe prompt answers — so re-describing an item used to silently drop
    # everything the OTHER passes had put in the same column:
    #
    #   * the exposure flags. A described item came back with no `_flags_v` at
    #     all, the gated lanes emptied, and the flags pass had to be run again.
    #   * the dispute corrections. There are TWO override mechanisms and they
    #     differ: `edit_item` leaves this blob as the model's raw answer and
    #     wins at READ time through `effective_value` (which is why the fresh
    #     description below is expected to land here), while `vault_ai_fix`
    #     writes INTO the blob — its readers, the lanes and `contradictions`,
    #     go straight to `ai_fields_json` and never call `effective_value`. So
    #     only the `FIXABLE` half is restored here; carrying the rest would
    #     overwrite the model's answer with the operator's and erase the
    #     evidence that a re-run happened at all.
    #
    # The flags are a different reading of the SAME image, so they stay valid
    # across a re-describe. A locked dispute fix outranks model and carried alike.
    # `data` is fresh, so a `_copied_from` marker is gone with it: the
    # description is this row's own now.
    carry_flags(out, prev_ai, exact=False)
    _put_jev(out, prev_ai.get(JEV_KEY))  # Jev read the same image too
    _apply_locked_fixes(out, overrides, locked, fixable)
    vals: dict[str, Any] = {
        "describe_status": "described",
        "describe_model": used_model,
        "describe_call_id": call_id,
        "describe_generated_at": now,
        "ai_fields_json": json.dumps(out, ensure_ascii=False, default=str),
        "frames_sampled": n_frames if is_video else None,
    }
    _put_unlocked(vals, locked, {
        "tip_vault_flag": sellable, "tags": json.dumps(tags),
        "explicitness_tier": ans["explicitness_tier"],
        ("video_description" if is_video else "description"): desc,
        "search_text": search_text})
    return vals


# ── The flags blob + locked columns (describe, flags, copies) ───────

COPY_MARK = "_copied_from"          # describe + flags copied from that media
FLAGS_COPY_MARK = "_flags_copied_from"  # flags only copied from that media

# Everything in `ai_fields_json` that belongs to the FLAGS pass rather than to
# describe: the answers, the garments, its stamps, its failure record and the
# provenance of a copied blob. One list, so a describe re-run, a flags copy and
# a describe copy carry exactly the same thing — `_flags_status` means the same
# on every row however the row got its flags.
FLAGS_BLOB_KEYS: tuple[str, ...] = (
    *vault_ai_brief.FLAG_KEYS, *vault_ai_brief.OVER_KEYS.values(),
    "_flags_v", "_flags_model", "_flags_frames", "_flags_arc",
    "_flags_status", "_flags_failed_at", "_flags_error", FLAGS_COPY_MARK)

# The Jev v8 answer (`vault_jev`): its own pass, carried by hand rather than
# through `FLAGS_BLOB_KEYS` — an exact flags copy from a source that has no
# `_jev` must not wipe the copy's own paid answer.
JEV_KEY = "_jev"


def jev_for_copy(src_ai: Mapping[str, Any], own_ai: Mapping[str, Any]) -> Any:
    """The `_jev` a duplicate should carry: the source's when it is a good
    answer (`status == "ok"`), else the copy's own (or None: none at all)."""
    src = src_ai.get(JEV_KEY)
    if isinstance(src, dict) and src.get("status") == "ok":
        return src
    return own_ai.get(JEV_KEY)


def _put_jev(out: dict[str, Any], jev: Any) -> None:
    if jev is None:
        out.pop(JEV_KEY, None)
    else:
        out[JEV_KEY] = jev


# Keys in `ai_fields_json` that are about the ROW, not the picture — an
# operator's grading verdict (`vault_ai_fix.GRADE_KEY`) was given on this item.
ROW_OWN_KEYS: tuple[str, ...] = ("_graded",)


def carry_flags(dst: dict[str, Any], src: Mapping[str, Any], *,
                locked: Collection[str] = (), exact: bool) -> dict[str, Any]:
    """Put `src`'s flags blob (`FLAGS_BLOB_KEYS`) on `dst`, in place.

    `exact`: `dst`'s flags become exactly `src`'s (a key `src` lacks is
    dropped) — a copy. Not exact: only keys `src` has are written — a
    describe re-run keeping the row's own earlier flags. A `locked` key (an
    operator fix) keeps `dst`'s value either way."""
    for key in FLAGS_BLOB_KEYS:
        if key in locked:
            continue
        if key in src:
            dst[key] = src[key]
        elif exact:
            dst.pop(key, None)
    return dst


def _apply_locked_fixes(out: dict[str, Any], overrides: Mapping[str, Any],
                        locked: Collection[str], fixable: Collection[str]) -> None:
    """Restore the row's locked dispute fixes (`vault_ai_fix` writes INTO the
    blob, see `build_describe_update`) onto a freshly-written blob."""
    for key, val in overrides.items():
        if key not in locked or key not in fixable:
            continue
        if val is None:
            out.pop(key, None)
        else:
            out[key] = val


# Column → the lock that guards it (`locked_fields_json` names effective fields).
_COLUMN_LOCK = {"tip_vault_flag": "tip_vault_flag", "tags": "tags",
                "explicitness_tier": "explicitness_tier", "description": "description",
                "video_description": "description", "search_text": "search_text"}


def _put_unlocked(vals: dict[str, Any], locked: Collection[str],
                  cols: Mapping[str, Any]) -> None:
    """Human edits win: write each of `cols` unless the operator locked it."""
    for col, v in cols.items():
        if _COLUMN_LOCK[col] not in locked:
            vals[col] = v


# ── Walk order ──────────────────────────────────────────────────────

PRIORITY_HEAD = 100


def priority_order(rows: Iterable[tuple[int, datetime | None, str | None]],
                   head: int = PRIORITY_HEAD) -> list[int]:
    """The order every vision sweep walks a vault, over (media_id, created_at,
    of_folder_ids) rows — the account's WHOLE live describable set, so a rank is
    a property of the item, not of what one sweep still has to do (a capped run
    must not promote items 101-200 over the folders on the next press).

      1. the newest `head` (created_at desc, media_id desc)
      2. anything in an OF folder (`of_folder_ids` non-empty), newest first
      3. the oldest `head` (created_at asc)
      4. the rest, newest first

    Order decides what a cap or a restart cuts off, so the tail is what nobody
    is sending. Each id appears once, at its best rank."""
    rows = list(rows)
    newest = sorted(rows, key=lambda r: (r[1] is not None, r[1] or datetime.min,
                                         int(r[0])), reverse=True)
    out: list[int] = []
    seen: set[int] = set()

    def take(seq: Iterable[tuple]) -> None:
        for r in seq:
            mid = int(r[0])
            if mid not in seen:
                seen.add(mid)
                out.append(mid)

    take(newest[:head])
    take(r for r in newest if parse_folder_ids(r[2]))
    take(reversed(newest[-head:] if head else []))
    take(newest)
    return out


# ── Answer reuse across a duplicate set ─────────────────────────────

class ReusePlan(NamedTuple):
    """How one sweep spends calls on duplicate sets (`vault_dupes.reuse_groups`).

    copy_now   target -> a member already done before this sweep: copied at
               the start, no call.
    followers  leader -> the walked members copied right after the leader's
               own call succeeds (never at the end, so a cap mid-sweep keeps
               every copy whose leader made it)."""

    copy_now: dict[int, int]
    followers: dict[int, list[int]]

    def riders(self) -> set[int]:
        return {m for ms in self.followers.values() for m in ms}


def reuse_plan(groups: Iterable[Sequence[int]], order: Sequence[int],
               done: Collection[int], bad: Collection[int] = ()) -> ReusePlan:
    """`order` is the sweep's walk (priority order); `done` the members whose
    answer is already current and may be copied from; `bad` members whose last
    attempt failed (picked as leader last, so one broken media does not starve
    its whole set on every press).

    A set with a done member outside the walk copies from it. Otherwise the
    walked member ranked best in `order` (good before bad) is the ONE call and
    the rest follow it. Not the oldest — which member is the cluster's seed
    shifts with collect order, the priority does not."""
    rank = {int(m): i for i, m in enumerate(order)}
    copy_now: dict[int, int] = {}
    followers: dict[int, list[int]] = {}
    for g in groups:
        walked = sorted((int(m) for m in g if int(m) in rank),
                        key=lambda m: (m in bad, rank[m]))
        if not walked:
            continue
        src = next((int(m) for m in g if int(m) not in rank and int(m) in done), None)
        if src is not None:
            for m in walked:
                copy_now[m] = src
        elif len(walked) > 1:
            followers[walked[0]] = walked[1:]
    return ReusePlan(copy_now, followers)


def build_flags_copy(prev: Mapping[str, Any], src_ai: Mapping[str, Any], *,
                     locked: Collection[str], src_id: int) -> dict[str, Any]:
    """`prev` (the copy's ai_fields) with its flags blob replaced by the
    source's, stamped `FLAGS_COPY_MARK`. Enrichment only, like a flags run;
    an operator-locked flag or garment stays the copy's own."""
    fields = carry_flags(dict(prev), src_ai, locked=locked, exact=True)
    for dead in ("genitals_covered", "pussy_covered", "breasts_covered"):
        fields.pop(dead, None)  # what a flags run drops (`build_flags_fields`)
    _put_jev(fields, jev_for_copy(src_ai, prev))
    fields[FLAGS_COPY_MARK] = int(src_id)
    return fields


_COPY_COLUMNS = ("tip_vault_flag", "tags", "explicitness_tier", "description",
                 "video_description", "search_text")


def build_copy_update(src: Mapping[str, Any], *, prev_ai: Mapping[str, Any],
                      locked: Collection[str], overrides: Mapping[str, Any],
                      fixable: Collection[str], src_id: int,
                      now: datetime) -> dict[str, Any]:
    """The `VaultItem` column values that make a duplicate carry its source's
    describe + flags answer without a call: the columns `build_describe_update`
    writes, taken from `src` (the source row's columns), under the copy's OWN
    locks and locked dispute fixes. The source's row-own keys (`ROW_OWN_KEYS`)
    are not the copy's; the copy keeps its own. A source never flagged leaves
    the copy's own flags. Stamped `COPY_MARK` — how a later re-describe of the
    source finds its copies."""
    src_ai = json.loads(src.get("ai_fields_json") or "{}") or {}
    skip = {*FLAGS_BLOB_KEYS, *ROW_OWN_KEYS, COPY_MARK, JEV_KEY}
    out = {k: v for k, v in src_ai.items() if k not in skip}
    out.update({k: prev_ai[k] for k in ROW_OWN_KEYS if k in prev_ai})
    carry_flags(out, prev_ai, exact=False)
    _put_jev(out, jev_for_copy(src_ai, prev_ai))
    if "_flags_v" in src_ai:
        carry_flags(out, src_ai, locked=locked, exact=True)
        # The flags came from `src_id` itself, which COPY_MARK names. The
        # source's own flags marker names some other item, so it must not
        # ride along (reuse is never transitive).
        out.pop(FLAGS_COPY_MARK, None)
    out[COPY_MARK] = int(src_id)
    _apply_locked_fixes(out, overrides, locked, fixable)
    vals: dict[str, Any] = {
        "describe_status": "described",
        "describe_model": src.get("describe_model"),
        "describe_call_id": src.get("describe_call_id"),
        "describe_generated_at": now,
        "ai_fields_json": json.dumps(out, ensure_ascii=False, default=str),
        "frames_sampled": src.get("frames_sampled"),
    }
    _put_unlocked(vals, locked, {c: src.get(c) for c in _COPY_COLUMNS})
    return vals


def flags_current(fields: Mapping[str, Any], version: int) -> bool:
    """Flags on this blob answer prompt `version` — nothing for a sweep to do."""
    return (int(fields.get("_flags_v") or 0) >= version
            and vault_ai_brief.flags_known(dict(fields)))


_DESCRIBE_FAILED = frozenset({"failed", "refused", "blocked_drm", "fetch_failed", "gone"})


def reuse_state(rows: Iterable[tuple[int, str | None, Mapping[str, Any]]], *,
                flags: bool, flags_version: int) -> tuple[set[int], set[int]]:
    """(done, bad) over (media_id, describe_status, ai_fields) rows, for
    `reuse_plan`: done = its answer may be copied (described / current flags);
    bad = its last attempt failed. A Jev-fed describe is a source only while
    its row still holds the `_jev` it was fed (`vault_describe_jev.reusable`):
    the copy takes that `_jev` along (`jev_for_copy`), so the pair agrees."""
    done: set[int] = set()
    bad: set[int] = set()
    for mid, status, f in rows:
        if flags:
            ok, failed = flags_current(f, flags_version), "_flags_status" in f
        else:
            ok = status == "described" and vault_describe_jev.reusable(f)
            failed = status in _DESCRIBE_FAILED
        if ok:
            done.add(int(mid))
        elif failed:
            bad.add(int(mid))
    return done, bad
