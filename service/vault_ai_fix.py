from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select, update

import vault_ai_brief
from db.engine import get_session
from db.models import VaultItem
from vault_mirror import visible_to

log = logging.getLogger("of-relay.vault_ai_fix")


FIXABLE: tuple[str, ...] = (
    "clothing_state", "explicitness",
    *vault_ai_brief.VIS_REGIONS,
    *vault_ai_brief.OVER_KEYS.values(),
    "underwear_visible",
    "penetration", "acts",
)

_PENETRATION_STATES = frozenset({"none", "fingers", "toy", "penis", "unclear"})

def _s(v: Any) -> str:
    return str(v or "").strip().lower()


def _fields(item: VaultItem) -> dict[str, Any]:
    return vault_ai_brief.load_fields(item.ai_fields_json)


def _locked(raw: str | None) -> set[str]:
    try:
        got = json.loads(raw or "[]")
    except ValueError:
        return set()
    return set(got) if isinstance(got, (list, tuple, set)) else set()


async def apply_fix(account_id: str, media_id: int,
                    values: dict[str, Any]) -> dict[str, Any]:
    # A correction goes to ai_fields_json, operator_overrides_json and locked_fields_json: one a re-run silently reverts is worse than none.
    edits = {k: v for k, v in (values or {}).items() if k in FIXABLE}
    if not edits:
        return {"ok": False, "error": "no_fixable_fields"}

    bad = [k for k, v in edits.items()
           if k in vault_ai_brief.VIS_REGIONS and v not in vault_ai_brief.VIS_STATES]
    if bad:
        return {"ok": False, "error": "bad_region_state", "fields": bad}

    if "penetration" in edits and _s(edits["penetration"]) not in _PENETRATION_STATES:
        return {"ok": False, "error": "bad_penetration_state",
                "value": edits["penetration"]}
    if "acts" in edits:
        acts = edits["acts"]
        if not isinstance(acts, list) or not all(isinstance(a, str) for a in acts):
            return {"ok": False, "error": "bad_acts", "value": acts}
        edits["acts"] = [a.strip().lower() for a in acts if a.strip()]

    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is None:
            return {"ok": False, "error": "not_in_mirror", "media_id": media_id}

        fields = _fields(item)
        overrides = vault_ai_brief.load_fields(item.operator_overrides_json)
        locked = _locked(item.locked_fields_json)

        for key, val in edits.items():
            if val is None:
                fields.pop(key, None)
            else:
                fields[key] = val
            overrides[key] = val
            locked.add(key)

        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
            .values(ai_fields_json=json.dumps(fields, ensure_ascii=False, default=str),
                    operator_overrides_json=json.dumps(overrides, ensure_ascii=False,
                                                       default=str),
                    locked_fields_json=json.dumps(sorted(locked))))
        await s.commit()

    log.info("vault_ai_fix account=%s media=%s fixed=%s",
             account_id, media_id, sorted(edits))
    return {"ok": True, "media_id": media_id, "applied": edits,
            "locked": sorted(locked),
            "still_disagrees": vault_ai_brief.contradictions(fields)}


GRADE_KEY = "_graded"


def grade_of(fields: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(fields, dict):
        return {}
    g = fields.get(GRADE_KEY)
    return g if isinstance(g, dict) else {}


def _priority(fields: dict[str, Any], lanes: list[str], version: int,
              reasons: list[str], price: int = 0) -> tuple:
    g = grade_of(fields)
    graded_this_version = int(g.get("v") or 0) >= version
    paid = any(ln in ("tease 10", "tease 50", "safe explicit") for ln in lanes)
    disputed = vault_ai_brief.is_disputed(fields)
    return (graded_this_version, -len(reasons), not disputed,
            -price if disputed else 0,
            not paid, not vault_ai_brief.any_bare(fields))


async def review_queue(account_id: str, *, limit: int = 60,
                       version: int = 0, only_iffy: bool = False,
                       allowed: frozenset[int] | None = None) -> dict[str, Any]:
    import vault_scripts

    stmt = (select(VaultItem.media_id, VaultItem.kind, VaultItem.ai_fields_json,
                   VaultItem.locked_fields_json)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None),
                   VaultItem.kind.in_(("photo", "video")))
            .order_by(VaultItem.media_id.asc()))
    async with get_session() as s:
        rows = (await s.execute(stmt.where(visible_to(allowed)))).all()

    plan = await vault_scripts.plan_ai_folders(account_id, keep=2)
    lanes: dict[int, list[str]] = {}
    for fold in plan["folders"]:
        for it in fold["items"]:
            lanes.setdefault(int(it["media_id"]), []).append(
                fold["name"].removeprefix("AI-"))

    out: list[dict[str, Any]] = []
    graded = 0
    for mid, kind, fj, lj in rows:
        fields = vault_ai_brief.load_fields(fj)
        if not vault_ai_brief.flags_known(fields):
            continue
        g = grade_of(fields)
        if int(g.get("v") or 0) >= version:
            graded += 1
        locked = _locked(lj)
        why = iffy_reasons(fields, locked & set(vault_ai_brief.VIS_REGIONS))
        if only_iffy and not why:
            continue
        disputed = vault_ai_brief.is_disputed(fields)
        price = vault_scripts.shelf_price(fields, kind) if disputed else 0
        out.append({
            "media_id": int(mid), "kind": kind,
            "iffy": why,
            "iffy_why": [IFFY_REASONS[r] for r in why],
            "lanes": lanes.get(int(mid), []),
            "regions": {r: vault_ai_brief.vis(fields, r)
                        for r in vault_ai_brief.VIS_REGIONS},
            "over": {r: vault_ai_brief.garment_over(fields, r)
                     for r in vault_ai_brief.OVER_KEYS},
            "description": str(fields.get("description") or "")[:280],
            "clothing_state": _s(fields.get("clothing_state")),
            "explicitness": _s(fields.get("explicitness")),
            "codes": vault_ai_brief.contradictions(fields),
            "settled": vault_ai_brief.settled_notes(fields),
            "settled_price": price,
            "locked": sorted(locked & set(vault_ai_brief.VIS_REGIONS)),
            "graded": g,
            "_sort": _priority(fields, lanes.get(int(mid), []), version, why,
                               price),
        })

    out.sort(key=lambda r: r["_sort"])
    for r in out:
        r.pop("_sort")
    return {"account_id": account_id, "prompt_version": version,
            "total": len(out), "graded": graded,
            "iffy": sum(1 for r in out if r["iffy"]),
            "only_iffy": bool(only_iffy),
            "items": out[:max(1, int(limit))]}


async def record_grade(account_id: str, media_id: int, *,
                       corrections: dict[str, Any] | None = None,
                       version: int = 0, note: str = "") -> dict[str, Any]:
    corrections = {k: v for k, v in (corrections or {}).items() if k in FIXABLE}
    applied: dict[str, Any] = {}
    if corrections:
        res = await apply_fix(account_id, media_id, corrections)
        if not res.get("ok"):
            return res
        applied = res["applied"]

    async with get_session() as s:
        item = await s.get(VaultItem, (account_id, media_id))
        if item is None:
            return {"ok": False, "error": "not_in_mirror", "media_id": media_id}
        fields = _fields(item)
        confirmed = {r: vault_ai_brief.vis(fields, r)
                     for r in vault_ai_brief.VIS_REGIONS
                     if r not in applied}
        fields[GRADE_KEY] = {"v": int(version), "confirmed": confirmed,
                             "corrected": sorted(applied), **({"note": note[:200]}
                                                              if note.strip() else {})}
        await s.execute(
            update(VaultItem)
            .where(VaultItem.account_id == account_id, VaultItem.media_id == media_id)
            .values(ai_fields_json=json.dumps(fields, ensure_ascii=False, default=str)))
        await s.commit()

    return {"ok": True, "media_id": media_id, "corrected": sorted(applied),
            "confirmed": sorted(confirmed)}


async def flags_accuracy(account_id: str, version: int = 0, *,
                         allowed: frozenset[int] | None = None) -> dict[str, Any]:
    stmt = (select(VaultItem.media_id, VaultItem.ai_fields_json)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None)))
    async with get_session() as s:
        rows = (await s.execute(stmt.where(visible_to(allowed)))).all()

    per = {r: {"ok": 0, "n": 0} for r in vault_ai_brief.VIS_REGIONS}
    graded = stale = 0
    for _mid, fj in rows:
        fields = vault_ai_brief.load_fields(fj)
        g = grade_of(fields)
        if not g:
            continue
        if int(g.get("v") or 0) != int(version):
            stale += 1
            continue
        graded += 1
        corrected = set(g.get("corrected") or [])
        for region in vault_ai_brief.VIS_REGIONS:
            if region in corrected:
                per[region]["n"] += 1
            elif region in (g.get("confirmed") or {}):
                per[region]["n"] += 1
                per[region]["ok"] += 1
    tot_ok = sum(v["ok"] for v in per.values())
    tot_n = sum(v["n"] for v in per.values())
    return {"account_id": account_id, "prompt_version": version,
            "graded_items": graded, "graded_other_versions": stale,
            "per_region": per,
            "accuracy": round(tot_ok / tot_n, 4) if tot_n else None,
            "answers": tot_n}


IFFY_REASONS: dict[str, str] = {
    "unexplained_cover": "says covered but cannot say what is covering her",
    "act_vs_covered": "something is inside her, yet the region reads covered",
    "passes_disagree": "the two passes disagree — auto-settled to the least-harmful reading below",
    "prose_vs_flags": "the written description does not match the flags",
    "blind": "explicit, but nothing at all is in frame",
}

_PROSE_REGION: dict[str, tuple[str, ...]] = {
    "vulva_vis": ("pussy", "vulva", "clit", "clitoris", "vagina", "labia"),
    "breasts_vis": ("breast", "breasts", "tits", "boobs", "nipple", "nipples"),
    "anus_vis": ("anus", "asshole", "butthole"),
}
_PROSE_BARE = ("exposed", "bare", "uncovered", "on show", "visible", "spread open")


def _prose_says_bare(text: str, region: str) -> bool:
    low = text.lower()
    for part in _PROSE_REGION.get(region, ()):
        for m in re.finditer(r"\b" + re.escape(part) + r"\b", low):
            window = low[max(0, m.start() - 40):m.end() + 40]
            if any(w in window for w in _PROSE_BARE):
                return True
    return False


def iffy_reasons(fields: dict[str, Any], locked: set[str]) -> list[str]:
    out: list[str] = []

    for region in vault_ai_brief.VIS_REGIONS:
        if region in locked:
            continue
        state = vault_ai_brief.vis(fields, region)
        over = vault_ai_brief.garment_over(fields, region)
        if state == "covered" and not over:
            out.append("unexplained_cover")

    acts = {str(a).strip().lower() for a in (fields.get("acts") or [])}
    pen = _s(fields.get("penetration"))
    if (acts & {"fingering", "toy_insertion", "riding_toy"}
            or pen in ("fingers", "toy", "penis")):
        if any(vault_ai_brief.vis(fields, r) == "covered"
               for r in ("vulva_vis", "anus_vis")):
            out.append("act_vs_covered")

    if vault_ai_brief.contradictions(fields):
        out.append("passes_disagree")

    if _s(fields.get("explicitness")) in ("explicit", "hardcore") and all(
            vault_ai_brief.vis(fields, r) == "not_in_frame"
            for r in vault_ai_brief.VIS_REGIONS):
        out.append("blind")

    text = str(fields.get("description") or "")
    if text:
        for region in vault_ai_brief.VIS_REGIONS:
            if region in locked:
                continue
            if (_prose_says_bare(text, region)
                    and vault_ai_brief.vis(fields, region) != "bare"):
                out.append("prose_vs_flags")
                break

    seen: set[str] = set()
    return [r for r in out if not (r in seen or seen.add(r))]
