"""A tagged vault for the grid's tag chips (scenarios/2026-11-11-vault-tag-chips.py): `vault_items` rows by SQL for
one Creator (columns as seed/vault_items.py writes them), each planted in one class so "feet" AND "lace" has an exact
oracle across the three tag sources the relay reads (`vault_items.tags`, `ai_fields_json.tags`,
`ai_fields_json.primary_folder`):

  col_both   column ["feet", "lace"]                                   -> match
  ai_both    column ["bed"], ai tags ["Feet", " Lace "] (case, spaces) -> match (ai tags only)
  mixed      column ["feet"], ai tags ["lace"]                         -> match (needs ai tags)
  primary    column ["pink"], ai primary_folder "Feet", ai tags ["lace"] -> match (needs primary_folder + ai tags)
  broken_ai  column ["feet", "lace"], ai_fields_json not JSON          -> match (column; the bad JSON is skipped)
  feet_only  column ["feet", "bed"]                                    -> no
  lace_only  ai tags ["lace", "pink"]                                  -> no
  decoy      column ["feet_soles", "laced"] (substrings, not tags)     -> no
  removed    column ["feet", "lace"], removed_at set                   -> no (hidden from the vault)
  plain      column ["bed", "pink"]                                    -> no
Sizes: SIZES `vault_tag_items` (items per Creator), merged on import.

`seed(w, creator, n)` -> (and `w.data["vault_tag_chips"]`) {"account_id", "classes": {class: [media ids]},
"match": [ids, newest first], "live": [live ids], "facets": [{"tag", "count"}] (the relay's facet answer for the
unfiltered vault: per live item the set of its lowercased tags from all three sources, by count desc then tag)}.
Randomness only from `w.rng("vault_tag_chips")`."""
from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta

from . import World, merge_sizes, ts

SIZES = {"vault_tag_items": (80, 2_000, 12_000)}
merge_sizes(SIZES)

TAGS = ("feet", "lace")   # the chips the scenario picks, in pick order
MATCH = ("col_both", "ai_both", "mixed", "primary", "broken_ai")
MIX = (("col_both", 0.08), ("ai_both", 0.08), ("mixed", 0.08), ("primary", 0.06), ("broken_ai", 0.04),
       ("feet_only", 0.14), ("lace_only", 0.12), ("decoy", 0.08), ("removed", 0.04), ("plain", 0.28))
_COL = {"col_both": ["feet", "lace"], "ai_both": ["bed"], "mixed": ["feet"], "primary": ["pink"],
        "broken_ai": ["feet", "lace"], "feet_only": ["feet", "bed"], "lace_only": [],
        "decoy": ["feet_soles", "laced"], "removed": ["feet", "lace"], "plain": ["bed", "pink"]}
_AI_TAGS = {"ai_both": ["Feet", " Lace "], "mixed": ["lace"], "primary": ["lace"], "lace_only": ["lace", "pink"]}


def _ai(cls: str, k: int) -> str:
    if cls == "broken_ai":
        return '{"tags": ["feet", '   # cut off mid-write: json_valid() false
    fields: dict = {"description": f"Solo still {k}", "tags": _AI_TAGS.get(cls, ["solo"]), "explicitness": "suggestive"}
    if cls == "primary":
        fields["primary_folder"] = "Feet"
    return json.dumps(fields)


def _item_tags(col: list[str], ai_raw: str) -> set[str]:
    """What the relay reads off one item (vault_tags.count_facets): all three sources, trimmed, lowercased."""
    out = {t.strip().lower() for t in col}
    try:
        ai = json.loads(ai_raw)
    except ValueError:
        ai = {}
    out |= {str(t).strip().lower() for t in ai.get("tags") or []}
    if ai.get("primary_folder"):
        out.add(str(ai["primary_folder"]).strip().lower())
    return {t for t in out if t}


def seed(w: World, creator: dict, n: int) -> dict:
    rng = w.rng("vault_tag_chips")
    aid = creator["id"]
    names, weights = zip(*MIX)
    classes = [rng.choices(names, weights)[0] for _ in range(n)]
    for i, c in enumerate(names):   # every class at least twice
        classes[2 * i:2 * i + 2] = [c, c]
    rng.shuffle(classes)
    ids = sorted(rng.sample(range(2_500_000_000, 4_200_000_000), n))
    t0 = w.now - timedelta(days=30)
    out: dict = {"account_id": aid, "classes": {c: [] for c in names}, "match": [], "live": []}
    counts: Counter = Counter()
    rows = []
    for k, (mid, cls) in enumerate(zip(ids, classes)):
        at = t0 + timedelta(minutes=37 * k)
        created = at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        raw = {"id": mid, "type": "photo", "convertedToVideo": False, "canView": True, "hasError": False,
               "createdAt": created, "isReady": True, "listStates": []}
        col, ai = _COL[cls], _ai(cls, k)
        removed = cls == "removed"
        rows.append({
            "account_id": aid, "media_id": mid, "kind": "photo", "duration_seconds": None,
            "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now),
            "of_folder_ids": "[]", "search_text": f"solo still {k}", "tags": json.dumps(col),
            "last_seen_run_id": None, "content_hash": None, "content_hash_kind": None, "send_count": 0,
            "last_sent_at": None, "removed_at": ts(w.now) if removed else None,
            "description": f"Solo still {k}", "video_description": None, "describe_status": "described",
            "describe_model": "qwen3-vl-30b", "describe_generated_at": ts(w.now), "ai_fields_json": ai,
            "of_terms": None, "explicitness_tier": "suggestive", "frames_sampled": None})
        out["classes"][cls].append(mid)
        if removed:
            continue
        out["live"].append(mid)
        counts.update(_item_tags(col, ai))
        if cls in MATCH:
            out["match"].append(mid)
    out["match"].reverse()   # created_at ascends with the id: newest first, as the relay orders the folder
    out["facets"] = [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:30]
    con = w.sql()
    with con:
        cols = list(rows[0])
        con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
    con.close()
    w.data["vault_tag_chips"] = out
    return out
