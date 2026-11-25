from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, NamedTuple

from sqlalchemy import and_, func
from sqlalchemy.sql.elements import ColumnElement

import vault_ai_brief
import vault_collect_plan
import vault_describe_jev
import vault_jev_flags
import vault_jev_manual
import vault_jev_rules
from db.models import VaultItem
from vault_of_folders_decide import parse_folder_ids


# Measured: 3->6 frames is a real jump, 6->9 flat, 9->12 adds ~8pp coverage; 12 = server._STORYBOARD_FRAMES ceiling (already extracted).
_FRAME_LADDER: tuple[tuple[int, int], ...] = (
    (30, 6),
    (180, 9),
)
_FRAME_LADDER_MAX = 12


def _frames_for_duration(seconds: int | None) -> int:
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


ESCALATION_MODEL = "qwen3-vl-235b"


def next_attempt(model: str, refused_or_blank: bool) -> str | None:
    """The model to try next after one describe attempt on `model`, or None.

    Try the asked model; on a refusal or a blank answer escalate ONCE to 235b
    (never overwrite a good existing description with a blank). An answer, or a
    refusal from 235b itself, ends it."""
    if not refused_or_blank or model == ESCALATION_MODEL:
        return None
    return ESCALATION_MODEL


# An audio file has no frame: sweeping it failed every pass, and its MP3 bytes were posted to a vision endpoint as an image.
_DESCRIBABLE_KINDS = vault_jev_rules.JEV_KINDS

DescribeMode = Literal["force", "restage", "undescribed"]


def live_describable(account_id: str) -> ColumnElement[bool]:
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
                      starting over. A photo / clip whose describe was not
                      Jev-fed is stale whatever its version.
      "undescribed" — only items not yet successfully described.
    """
    base = live_describable(account_id)
    if mode == "force":
        return base
    if mode == "restage":
        # `_prompt_version` is stamped into ai_fields_json by _describe_one.
        # A row that predates the stamp has no marker at all, so it counts
        # as stale and gets re-scanned. So does a photo / clip whose describe
        # is not Jev-fed (`_describe.path`, the meta's first key, not in
        # JEV_FED): a v2 / pre-Jev describe, whatever its prompt version.
        # Read with json_extract (SQLite JSON1, as `vault_jev_rules.current_sql`), not LIKE on key order and
        # spacing (W30 F18); an invalid / NULL blob reads as no marker (stale).
        ok = vault_jev_rules.json_or_empty(VaultItem.ai_fields_json)
        key = lambda path: func.coalesce(func.json_extract(ok, path), "")  # noqa: E731
        jev_fed = key(f"$.{vault_describe_jev.DESCRIBE_KEY}.path").in_(vault_describe_jev.JEV_FED)
        return and_(base,
                    (VaultItem.describe_status != "described")
                    | (VaultItem.describe_status.is_(None))
                    | (VaultItem.ai_fields_json.is_(None))
                    | (key("$._prompt_version") != pv)
                    | (VaultItem.kind.in_(JEV_KINDS) & ~jev_fed))
    if mode == "undescribed":
        # Includes blocked_drm with no cool-off: a button pressed on a shown count must attempt what that count promised.
        return and_(base, VaultItem.describe_status.isnot("described"))
    raise ValueError(f"unknown describe mode: {mode!r}")



DESCRIBE_TARGET = 1000

TERMINAL_STATUSES = frozenset({"refused", "blocked_drm", "gone"})


def is_terminal(describe_status: str | None, fields: Mapping[str, Any] | None) -> bool:
    if describe_status == "described":
        return False
    if describe_status in TERMINAL_STATUSES:
        return True
    return vault_jev_rules.retries_spent(dict(fields or {}))


def coverage(rows: Iterable[tuple[str | None, Mapping[str, Any] | None]], target: int) -> dict[str, int]:
    describable = described = terminal = 0
    for status, fields in rows:
        describable += 1
        if status == "described":
            described += 1
        elif is_terminal(status, fields):
            terminal += 1
    # A terminal (skipped) item fills its slot, owner decision.
    goal = max(0, min(int(target), describable) - terminal)
    return {"target": int(target), "describable": describable, "described": described,
            "terminal": terminal, "goal": goal, "remaining": max(0, goal - described)}


def describe_answer(data: Mapping[str, Any]) -> dict[str, Any]:
    tier = data.get("explicitness")
    return {
        "description": str(data.get("description") or ""),
        "tags": [str(t).lower().strip() for t in (data.get("tags") or [])
                 if str(t).strip()][:12],
        "explicitness_tier": str(tier) if tier else None,
        "nsfw": bool(data.get("nsfw")) if data.get("nsfw") is not None else None,
        "sellable": bool(data.get("sellable")) if data.get("sellable") is not None else None,
    }


def with_jev(res: Mapping[str, Any], jev_res: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(res)
    if not jev_res:
        return out
    jc = int(jev_res.get("cost_millicents") or 0)
    out["cost_millicents"] = int(out.get("cost_millicents") or 0) + jc
    out["jev_status"] = jev_res.get("status")
    out["jev_cost_millicents"] = jc
    if jev_res.get("lane5"):
        out["jev_lane5"] = jev_res["lane5"]
    if jev_res.get("notice"):
        out["notice"] = jev_res["notice"]
    return out


def prompt_variant(prompt_version: Any) -> str:
    return "v1" if str(prompt_version) == "v1" else "v2"


def build_describe_update(is_video: bool, data: Mapping[str, Any], *,
                          prev_ai: Mapping[str, Any], locked: Collection[str],
                          overrides: Mapping[str, Any], used_model: str,
                          n_frames: int, pv: str, fixable: Collection[str],
                          call_id: int | None, now: datetime) -> dict[str, Any]:
    ans = describe_answer(data)
    desc, tags, sellable = ans["description"], ans["tags"], ans["sellable"]
    v2_terms: list[str] = []
    for key in ("acts", "body_focus", "toys", "clothing_items", "beats"):
        v2_terms += [str(x) for x in (data.get(key) or []) if str(x).strip()]
    for key in ("clothing_state", "penetration", "position", "setting",
                "camera", "primary_folder"):
        if data.get(key):
            v2_terms.append(str(data[key]))
    search_text = " ".join([desc, *tags, *v2_terms]).lower()

    out = {**data, "_prompt_version": prompt_variant(pv),
           "_frames": n_frames}

    carry_flags(out, prev_ai, exact=False)
    # ai_fields_json is written whole from `data` (describe answers only): re-describe must carry the flags, _jev and FIXABLE dispute fixes or they vanish; edit_item overrides win at read time instead.
    _put_jev(out, prev_ai.get(JEV_KEY))
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
        vault_jev_flags.TIER_COLUMN: vault_jev_flags.column_tier(out, ans["explicitness_tier"], locked),
        ("video_description" if is_video else "description"): desc,
        "search_text": search_text})
    return vals



COPY_MARK = "_copied_from"
FLAGS_COPY_MARK = "_flags_copied_from"

FLAGS_BLOB_KEYS: tuple[str, ...] = (
    *vault_ai_brief.FLAG_KEYS, *vault_ai_brief.OVER_KEYS.values(),
    "_flags_v", "_flags_model", "_flags_frames", "_flags_arc",
    "_flags_status", "_flags_failed_at", "_flags_error", FLAGS_COPY_MARK)

JEV_KEY = vault_jev_rules.JEV_KEY
JEV_KINDS = vault_jev_rules.JEV_KINDS


# An exact flags copy from a source with no `_jev` must not wipe the copy's own paid answer.
def jev_for_copy(src_ai: Mapping[str, Any], own_ai: Mapping[str, Any],
                 picks: Mapping[str, Any] | None = None) -> Any:
    src = src_ai.get(JEV_KEY)
    if isinstance(src, dict) and src.get("status") == "ok" and not vault_jev_rules.retries_spent({JEV_KEY: src}):
        return vault_jev_manual.overlay(src, picks or {}, vault_jev_manual.kind_of(src))
    return own_ai.get(JEV_KEY)


def _put_jev(out: dict[str, Any], jev: Any) -> None:
    if jev is None:
        out.pop(JEV_KEY, None)
    else:
        out[JEV_KEY] = jev


ROW_OWN_KEYS: tuple[str, ...] = ("_graded",)


def carry_flags(dst: dict[str, Any], src: Mapping[str, Any], *,
                locked: Collection[str] = (), exact: bool) -> dict[str, Any]:
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
    for key, val in overrides.items():
        if key not in locked or key not in fixable:
            continue
        if val is None:
            out.pop(key, None)
        else:
            out[key] = val


_COLUMN_LOCK = {"tip_vault_flag": "tip_vault_flag", "tags": "tags",
                "explicitness_tier": "explicitness_tier", "description": "description",
                "video_description": "description", "search_text": "search_text"}


def _put_unlocked(vals: dict[str, Any], locked: Collection[str],
                  cols: Mapping[str, Any]) -> None:
    for col, v in cols.items():
        if _COLUMN_LOCK[col] not in locked:
            vals[col] = v



# Collect's round, in items: one source so Describe's order cannot drift from it.
PRIORITY_FOLD = vault_collect_plan.FOLD
PRIORITY_TOP = vault_collect_plan.TOP_PAGES * vault_collect_plan.PAGE
PRIORITY_BOTTOM = vault_collect_plan.BOTTOM_PAGES * vault_collect_plan.PAGE


def rail_folder_ids(pages: Iterable[Mapping[str, Any] | None]) -> list[int]:
    out: list[int] = []
    for page in pages:
        for f in (page or {}).get("list") or []:
            if not isinstance(f, Mapping) or f.get("type") != "custom" or not f.get("hasMedia"):
                continue
            try:
                fid = int(f["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if fid not in out:
                out.append(fid)
    return out


def priority_order(rows: Iterable[tuple[int, datetime | None, str | None]],
                   folder_rank: Sequence[int] = (), *,
                   fold: int = PRIORITY_FOLD, top: int = PRIORITY_TOP,
                   bottom: int = PRIORITY_BOTTOM) -> list[int]:
    newest = sorted(list(rows), key=lambda r: (r[1] is not None, r[1] or datetime.min,
                                               int(r[0])), reverse=True)
    by_folder: dict[int, list[int]] = {}
    for r in newest:
        for fid in parse_folder_ids(r[2]):
            items = by_folder.setdefault(fid, [])
            if not items or items[-1] != int(r[0]):
                items.append(int(r[0]))
    ranked = [f for f in dict.fromkeys(int(f) for f in folder_rank) if f in by_folder]
    cached = set(ranked)
    ranked += [f for f in by_folder if f not in cached]
    ids = [int(r[0]) for r in newest]
    out: list[int] = []
    seen: set[int] = set()

    def take(mid: int) -> bool:
        if mid in seen:
            return False
        seen.add(mid)
        out.append(mid)
        return True

    lo, hi = 0, len(ids) - 1
    k = 1
    while len(out) < len(ids):
        if fold > 0:
            for f in ranked[(k - 1) * fold:k * fold]:
                for mid in by_folder[f]:
                    take(mid)
        if top <= 0 and bottom <= 0:
            if fold <= 0 or k * fold >= len(ranked):
                for mid in ids:
                    take(mid)
        else:
            n = 0
            while n < top and lo < len(ids):
                n += take(ids[lo])
                lo += 1
            n = 0
            while n < bottom and hi >= 0:
                n += take(ids[hi])
                hi -= 1
        k += 1
    return out



# Followers are copied right after the leader's own call succeeds (never at the end), so a cap mid-sweep keeps every copy whose leader made it.
class ReusePlan(NamedTuple):

    copy_now: dict[int, int]
    followers: dict[int, list[int]]

    def riders(self) -> set[int]:
        return {m for ms in self.followers.values() for m in ms}


def reuse_plan(groups: Iterable[Sequence[int]], order: Sequence[int],
               done: Collection[int], bad: Collection[int] = ()) -> ReusePlan:
    rank = {int(m): i for i, m in enumerate(order)}
    copy_now: dict[int, int] = {}
    followers: dict[int, list[int]] = {}
    for g in groups:
        walked = sorted((int(m) for m in g if int(m) in rank),
                        key=lambda m: (m not in done, m in bad, rank[m]))
        if not walked:
            continue
        src = next((int(m) for m in g if int(m) not in rank and int(m) in done), None)
        if src is not None:
            for m in walked:
                copy_now[m] = src
        elif len(walked) > 1:
            followers[walked[0]] = walked[1:]
    return ReusePlan(copy_now, followers)


def lead_plan(groups: Iterable[Sequence[int]], leads: Sequence[int]) -> ReusePlan:
    want = list(dict.fromkeys(int(m) for m in leads))
    named = set(want)
    followers: dict[int, list[int]] = {}
    for g in groups:
        members = [int(m) for m in g]
        first = next((m for m in want if m in members), None)
        rest = [m for m in members if m not in named]
        if first is not None and rest:
            followers.setdefault(first, []).extend(rest)
    return ReusePlan({}, followers)


def build_flags_copy(prev: Mapping[str, Any], src_ai: Mapping[str, Any], *,
                     locked: Collection[str], src_id: int,
                     picks: Mapping[str, Any] | None = None) -> dict[str, Any]:
    fields = carry_flags(dict(prev), src_ai, locked=locked, exact=True)
    for dead in ("genitals_covered", "pussy_covered", "breasts_covered"):
        fields.pop(dead, None)
    _put_jev(fields, jev_for_copy(src_ai, prev, picks))
    fields = vault_jev_flags.apply(fields, fields.get(JEV_KEY), locked)
    fields[FLAGS_COPY_MARK] = int(src_id)
    return fields


_COPY_COLUMNS = ("tip_vault_flag", "tags", "explicitness_tier", "description",
                 "video_description", "search_text")


def build_copy_update(src: Mapping[str, Any], *, prev_ai: Mapping[str, Any],
                      locked: Collection[str], overrides: Mapping[str, Any],
                      fixable: Collection[str], src_id: int,
                      now: datetime) -> dict[str, Any]:
    src_ai = json.loads(src.get("ai_fields_json") or "{}") or {}
    skip = {*FLAGS_BLOB_KEYS, *ROW_OWN_KEYS, COPY_MARK, JEV_KEY}
    out = {k: v for k, v in src_ai.items() if k not in skip}
    out.update({k: prev_ai[k] for k in ROW_OWN_KEYS if k in prev_ai})
    carry_flags(out, prev_ai, exact=False)
    _put_jev(out, jev_for_copy(src_ai, prev_ai, vault_jev_manual.stored(overrides)))
    # The source's own flags marker names some other item: reuse is never transitive, so it must not ride along.
    if "_flags_v" in src_ai:
        carry_flags(out, src_ai, locked=locked, exact=True)
        out.pop(FLAGS_COPY_MARK, None)
    out = vault_jev_flags.apply(out, out.get(JEV_KEY), locked)
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
    if vault_jev_flags.TIER_COLUMN not in locked:
        vals[vault_jev_flags.TIER_COLUMN] = vault_jev_flags.column_tier(
            out, vals.get(vault_jev_flags.TIER_COLUMN), locked)
    return vals


def flags_current(fields: Mapping[str, Any], version: int) -> bool:
    return (int(fields.get("_flags_v") or 0) >= version
            and vault_ai_brief.flags_known(dict(fields)))


_DESCRIBE_FAILED = frozenset({"failed", "refused", "blocked_drm", "fetch_failed", "gone"})


def _jev_failed(f: Mapping[str, Any]) -> bool:
    j = f.get(JEV_KEY)
    return isinstance(j, dict) and j.get("status") not in (None, "ok")


def reuse_state(rows: Iterable[tuple[int, str | None, Mapping[str, Any], str | None, Any, Any]], *,
                flags: bool, flags_version: int) -> tuple[set[int], set[int]]:
    """(done, bad) over (media_id, describe_status, ai_fields, kind, locked_fields_json, explicitness_tier) rows, for
    `reuse_plan`: done = its answer may be copied (described / current flags);
    bad = its last attempt failed. A photo's or clip's flags are a source only when they
    are its current `_jev`'s (`vault_jev_flags.row_in_sync`, locks and tier column included); its describe
    only when Jev-fed and its row still holds the `_jev` it was fed
    (`vault_describe_jev.reusable`): the copy takes that `_jev` along
    (`jev_for_copy`), so the pair agrees."""
    done: set[int] = set()
    bad: set[int] = set()
    for mid, status, f, kind, locked, tier in rows:
        if flags:
            ok = flags_current(f, flags_version) and (
                kind not in JEV_KINDS or (vault_jev_rules.ai_read(dict(f))
                                          and vault_jev_flags.row_in_sync(f, locked, tier=tier)))
            failed = "_flags_status" in f or (kind in JEV_KINDS and _jev_failed(f))
        else:
            ok = status == "described" and vault_describe_jev.reusable(f, kind)
            failed = status in _DESCRIBE_FAILED
        if ok:
            done.add(int(mid))
        elif failed:
            bad.add(int(mid))
    return done, bad
