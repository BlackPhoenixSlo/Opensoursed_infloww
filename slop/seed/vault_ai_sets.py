"""Set-gathering extras for the AI folders scenario (scenarios/2026-11-10-vault-ai-folders-partial-flags.py), on top
of seed/vault_flags_partial.py's vault. All by SQL, as the product leaves them:

  copies      re-uploads of `soft` stills and of videos: the original's row with a new media id, uploaded later, and
              the SAME stored `content_hash` on both (as vault_dupes.ensure_hashes leaves it, HASH_KIND) -> each set
              plans as its original only. Copies of soft / video only, so the paid-lane oracles are untouched.
  colourless  one shoot whose `clothing_items` name no colour: bra + thong, `setting` bedroom; sfw still ->
              suggestive still -> explicit clip (unflagged stills) -> script `AI-lingerie bedroom`.
  folders     an earlier build's generated folders (created_by vault_ai_script): `AI-stories` (the plan makes it:
              kept) and `AI-old lane` bound to OF list OLD_LIST (the plan does not: retired, unlinked on OF).

`seed(w, creator, truth)` extends `truth` (vault_flags_partial's) in place and returns it: "copies" {copy: original},
"colourless" [ids, send order], "kept_folder" {name: id}, "retired_folder" {name: id}; "stills" / "flagged" count the
new stills. Randomness only from `w.rng("vault_ai_sets")`."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from . import World, ts

HASH_KIND = "thumb/md5+dhash8+ahash8"   # vault_dupes.HASH_KIND
AI_CREATOR = "vault_ai_script"           # vault_scripts.AI_FOLDER_CREATOR
OLD_LIST = 5_551_001
COLOURLESS_NAME = "AI-lingerie bedroom"


def _packed(rng) -> str:
    """One content_hash (md5:dhash:ahash); random 64-bit hashes sit ~32 bits apart, far past threshold 2."""
    return f"{rng.getrandbits(128):032x}:{rng.getrandbits(64):016x}:{rng.getrandbits(64):016x}"


def seed(w: World, creator: dict, truth: dict) -> dict:
    rng = w.rng("vault_ai_sets")
    aid = creator["id"]
    n_copies = max(2, len(truth["soft"]) // 8)
    originals = rng.sample(truth["soft"], min(n_copies, len(truth["soft"]))) + \
        rng.sample(truth["videos"], min(n_copies, len(truth["videos"])))
    next_id = max(m for cls in ("ten", "fifty", "ten_raw", "fifty_raw", "soft", "videos") for m in truth[cls]) + 1
    con = w.sql()
    con.row_factory = sqlite3.Row
    copies: dict[int, int] = {}
    with con:
        for orig in sorted(originals):
            row = dict(con.execute("SELECT * FROM vault_items WHERE account_id=? AND media_id=?",
                                   (aid, orig)).fetchone())
            h = _packed(rng)
            con.execute("UPDATE vault_items SET content_hash=?, content_hash_kind=? WHERE account_id=? AND media_id=?",
                        (h, HASH_KIND, aid, orig))
            row.update(media_id=next_id, content_hash=h, content_hash_kind=HASH_KIND,
                       raw_json=json.dumps({**json.loads(row["raw_json"]), "id": next_id}))
            con.execute(f"INSERT INTO vault_items({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                        tuple(row.values()))
            copies[next_id] = orig
            if row["kind"] == "photo":
                truth["stills"] += 1
                truth["flagged"] += "breasts_vis" in json.loads(row["ai_fields_json"])
            next_id += 1

        t0 = w.now - timedelta(days=2)
        garb = {"clothing_items": ["bra", "thong"], "setting": "bedroom", "_prompt_version": "v2", "_frames": 1}
        shoot = (("photo", {"explicitness": "sfw", "clothing_state": "dressed", "acts": ["posing"]}),
                 ("photo", {"explicitness": "suggestive", "clothing_state": "lingerie_on", "acts": ["tease"]}),
                 ("video", {"explicitness": "explicit", "clothing_state": "fully_nude", "acts": ["fingering"],
                            "_frames": 6}))
        colourless = []
        for k, (kind, extra) in enumerate(shoot):
            mid, at = next_id + k, t0 + timedelta(minutes=10 * k)
            fields = {**garb, **extra, "description": f"Colourless set {k}", "tags": ["bed"]}
            video = kind == "video"
            raw = {"id": mid, "type": kind, "convertedToVideo": False, "canView": True, "hasError": False,
                   "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "isReady": True,
                   **({"duration": 30} if video else {}), "listStates": []}
            desc = fields["description"]
            row = {   # columns as seed/vault_flags_partial.py writes them
                "account_id": aid, "media_id": mid, "kind": kind, "duration_seconds": 30 if video else None,
                "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now), "of_folder_ids": "[]",
                "search_text": f"{desc} bra thong bedroom".lower(), "tags": json.dumps(fields["tags"]),
                "last_seen_run_id": None, "content_hash": None, "content_hash_kind": None, "send_count": 0,
                "last_sent_at": None, "removed_at": None, "description": None if video else desc,
                "video_description": desc if video else None, "describe_status": "described",
                "describe_model": "qwen3-vl-30b", "describe_generated_at": ts(w.now),
                "ai_fields_json": json.dumps(fields), "of_terms": None, "explicitness_tier": fields["explicitness"],
                "frames_sampled": 6 if video else None}
            con.execute(f"INSERT INTO vault_items({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                        tuple(row.values()))
            colourless.append(mid)
            truth["stills"] += not video
        next_id += len(shoot)

        folders = {}
        for name, list_id in (("AI-stories", None), ("AI-old lane", OLD_LIST)):
            cur = con.execute("INSERT INTO vault_folders(account_id, name, of_list_id, created_by, created_at)"
                              " VALUES (?,?,?,?,?)", (aid, name, list_id, AI_CREATOR, ts(w.now - timedelta(days=3))))
            folders[name] = int(cur.lastrowid)
    con.close()
    truth.update(copies=copies, colourless=colourless, kept_folder={"AI-stories": folders["AI-stories"]},
                 retired_folder={"AI-old lane": folders["AI-old lane"]})
    return truth
