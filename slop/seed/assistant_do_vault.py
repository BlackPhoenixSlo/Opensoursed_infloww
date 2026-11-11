"""The help bot's "Do it for me" vault (scenarios/2026-11-11-assistant-do-auto-mass.py): `vault_items` rows by SQL
for one Creator, as Collect + the describe pass leave them (columns as seed/vault_flags_partial.py writes them), in
three OF vault folders (`raw_json.listStates`, `of_folder_ids`) whose per-photo `explicitness_tier` is the draft's
folder oracle (service/assistant_draft.py `folder_stats` / `rank_sfw`):

  SFW teasers  every photo flagged, sfw or suggestive, none explicit           -> the SFW pick
  Spicy        MORE sfw photos than SFW teasers, but a few explicit            -> a "most sfw photos" pick lands here
  Unflagged    the MOST photos, none flagged (tier NULL, never described)     -> a "biggest / no explicit" pick lands here
plus a few videos in SFW teasers (only photos join an Auto mass from a folder, so they never count).

Fixed shape, not a volume path: the counts ARE the oracle, so no `w.size` key. Media ids and the tier order inside a
folder come from `w.rng("assistant_do_vault")`.

`seed(w, creator)` -> (and `w.data["assistant_do_vault"]`) {"account_id", "sfw_id", "folders": {name: {"id",
"photos", "videos", "tiers": {tier: n}}}, "of_lists": [OF's /vault/lists items, for lib/of_wire.py's
`vault_lists`]}."""
from __future__ import annotations

import json
from datetime import timedelta

from . import World, ts

MODEL, PROMPT_VERSION = "qwen3-vl-30b", "v2"   # as seed/vault_items.py
# (OF folder id, name, photo tiers in order (None = not flagged), videos)
FOLDERS = (
    (5_301, "SFW teasers", ("sfw",) * 7 + ("suggestive",) * 3, 2),
    (5_302, "Spicy", ("sfw",) * 20 + ("suggestive",) * 2 + ("explicit",) * 2, 0),
    (5_303, "Unflagged", (None,) * 40, 0),
)
SFW_ID = FOLDERS[0][0]


def _of_list(fid: int, name: str, photos: int, videos: int) -> dict:
    """One custom vault folder as OF's GET /api2/v2/vault/lists items read (the editor's folder select)."""
    return {"id": fid, "type": "custom", "name": name, "hasMedia": True, "canUpdate": True, "canDelete": True,
            "photosCount": photos, "videosCount": videos, "gifsCount": 0, "audiosCount": 0, "medias": []}


def seed(w: World, creator: dict) -> dict:
    rng = w.rng("assistant_do_vault")
    aid = creator["id"]
    t0 = w.now - timedelta(days=20)
    n_all = sum(len(t) + v for _f, _n, t, v in FOLDERS)
    ids = iter(sorted(rng.sample(range(4_300_000_000, 4_400_000_000), n_all)))
    out: dict = {"account_id": aid, "sfw_id": SFW_ID, "folders": {}, "of_lists": []}
    rows, k = [], 0
    for fid, name, tiers, videos in FOLDERS:
        kinds = [("photo", t) for t in tiers] + [("video", "sfw")] * videos
        rng.shuffle(kinds)
        for kind, tier in kinds:
            mid, at = next(ids), t0 + timedelta(minutes=41 * k)
            k += 1
            raw = {"id": mid, "type": kind, "convertedToVideo": False, "canView": True, "hasError": False,
                   "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "isReady": True,
                   **({"duration": 20} if kind == "video" else {}),
                   "listStates": [{"id": fid, "type": "custom", "name": name, "hasMedia": True, "canAddMedia": True}]}
            desc = f"{name} {kind} {k}" if tier else None
            fields = ({"description": desc, "tags": ["tease"], "explicitness": tier,
                       "_prompt_version": PROMPT_VERSION, "_frames": 1} if tier else None)
            rows.append({
                "account_id": aid, "media_id": mid, "kind": kind, "duration_seconds": 20 if kind == "video" else None,
                "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now),
                "of_folder_ids": json.dumps([fid]), "search_text": (desc or kind).lower(),
                "tags": json.dumps(["tease"] if tier else []), "last_seen_run_id": None, "content_hash": None,
                "content_hash_kind": None, "send_count": 0, "last_sent_at": None, "removed_at": None,
                "description": desc if kind == "photo" else None,
                "video_description": desc if kind == "video" else None,
                "describe_status": "described" if tier else None, "describe_model": MODEL if tier else None,
                "describe_generated_at": ts(w.now) if tier else None,
                "ai_fields_json": json.dumps(fields) if fields else None, "of_terms": None,
                "explicitness_tier": tier, "frames_sampled": 6 if kind == "video" and tier else None})
        counts: dict = {}
        for t in tiers:
            counts[t or "unknown"] = counts.get(t or "unknown", 0) + 1
        out["folders"][name] = {"id": fid, "photos": len(tiers), "videos": videos, "tiers": counts}
        out["of_lists"].append(_of_list(fid, name, len(tiers), videos))
    con = w.sql()
    with con:
        cols = list(rows[0])
        con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
    con.close()
    w.data["assistant_do_vault"] = out
    return out
