"""Set-gathering extras for the AI folders scenario (scenarios/2026-11-10-vault-ai-folders-partial-flags.py), on top
of seed/vault_flags_partial.py's vault. All by SQL, as the product leaves them:

  copies      re-uploads of `soft` stills and of videos: the original's row with a new media id, uploaded later, and
              the SAME stored `content_hash` on both (as vault_dupes.ensure_hashes leaves it, HASH_KIND) -> each set
              plans as its original only. Copies of soft / video only, so the paid-lane oracles are untouched.
  colourless  one shoot whose `clothing_items` name no colour: bra + thong, `setting` bedroom; 3 sfw stills ->
              4 suggestive (1 clip) -> 3 explicit fingering (2 clips), unflagged -> script
              `AI-lingerie · bedroom · <Mon D>` (a script needs >= 10 pieces with >= 2 clips).
  big shoot   one black lace set, every item in ONE upload second (as OF's created_at leaves a bulk upload), two
              rooms by the describe's `setting`: bedroom BIG_BEDROOM items (sfw / suggestive build-up / explicit
              fingering closers, stills and clips) -> capped to a sendable ladder; bathroom BIG_BATHROOM items (sfw +
              suggestive incl. clips, nothing that closes) -> borrows one bedroom overflow closer. Unflagged, unhashed.
  folders     an earlier build's generated folders (created_by vault_ai_script): `AI-stories` (the plan makes it:
              kept) and `AI-old lane` bound to OF list OLD_LIST (the plan does not: retired, unlinked on OF).

`seed(w, creator, truth)` extends `truth` (vault_flags_partial's) in place and returns it: "copies" {copy: original},
"colourless" [ids, send order], "colourless_name", "big_shoot" {"bedroom": ids, "bathroom": ids, "names": {room:
script name}}, "kept_folder" {name: id}, "retired_folder" {name: id}; "stills" / "flagged" count the new stills. Randomness only from `w.rng("vault_ai_sets")`."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

from . import World, ts

HASH_KIND = "thumb/md5+dhash8+ahash8"   # vault_dupes.HASH_KIND
AI_CREATOR = "vault_ai_script"           # vault_scripts.AI_FOLDER_CREATOR
OLD_LIST = 5_551_001
# The big shoot's parts (vault_scripts caps a script at 3 openers + 4 middle + 3 closers = 10).
BIG_BEDROOM = 26
BIG_BATHROOM = 10


def script_name(label: str, room: str, at) -> str:
    """vault_scripts.script_name: `AI-<label> · <room> · <Mon D>` (the part's first upload)."""
    return f"AI-{label} · {room} · {at:%b} {at.day}"


def _packed(rng) -> str:
    """One content_hash (md5:dhash:ahash); random 64-bit hashes sit ~32 bits apart, far past threshold 2."""
    return f"{rng.getrandbits(128):032x}:{rng.getrandbits(64):016x}:{rng.getrandbits(64):016x}"


def _item(w: World, aid: str, mid: int, kind: str, at, fields: dict, words: str) -> dict:
    """A vault_items row as seed/vault_flags_partial.py writes them (described, unhashed)."""
    video = kind == "video"
    raw = {"id": mid, "type": kind, "convertedToVideo": False, "canView": True, "hasError": False,
           "createdAt": at.strftime("%Y-%m-%dT%H:%M:%S+00:00"), "isReady": True,
           **({"duration": 30} if video else {}), "listStates": []}
    desc = fields["description"]
    return {
        "account_id": aid, "media_id": mid, "kind": kind, "duration_seconds": 30 if video else None,
        "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(w.now), "of_folder_ids": "[]",
        "search_text": f"{desc} {words}".lower(), "tags": json.dumps(fields["tags"]),
        "last_seen_run_id": None, "content_hash": None, "content_hash_kind": None, "send_count": 0,
        "last_sent_at": None, "removed_at": None, "description": None if video else desc,
        "video_description": desc if video else None, "describe_status": "described",
        "describe_model": "qwen3-vl-30b", "describe_generated_at": ts(w.now),
        "ai_fields_json": json.dumps(fields), "of_terms": None, "explicitness_tier": fields["explicitness"],
        "frames_sampled": 6 if video else None}


def _insert(con, row: dict) -> None:
    con.execute(f"INSERT INTO vault_items({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()))


# (kind, describe fields) cycles per band; explicit fingering closes on its own (vault_ai_brief.stands_alone).
_OPEN = (("photo", {"explicitness": "sfw", "clothing_state": "dressed", "acts": ["posing"]}),
         ("photo", {"explicitness": "sfw", "clothing_state": "lingerie_on", "acts": ["posing"]}))
_BUILD = (("photo", {"explicitness": "suggestive", "clothing_state": "lingerie_on", "acts": ["tease"]}),
          ("video", {"explicitness": "suggestive", "clothing_state": "lingerie_on", "acts": ["tease"]}),
          ("photo", {"explicitness": "suggestive", "clothing_state": "lingerie_on", "acts": ["posing"]}))
_CLOSE = (("video", {"explicitness": "explicit", "clothing_state": "fully_nude", "acts": ["fingering"]}),
          ("photo", {"explicitness": "explicit", "clothing_state": "fully_nude", "acts": ["fingering"]}))


def _big_shoot(w: World, con, aid: str, next_id: int, truth: dict) -> int:
    """The big shoot (module doc); returns the next free media id."""
    at = w.now - timedelta(days=1)
    garb = {"clothing_items": ["black lace bra", "black thong"], "_prompt_version": "v2", "_frames": 1}
    plan = {"bedroom": [_OPEN[k % 2] for k in range(8)] + [_BUILD[k % 3] for k in range(10)]
            + [_CLOSE[k % 2] for k in range(BIG_BEDROOM - 18)],
            "bathroom": [_OPEN[k % 2] for k in range(3)] + [_BUILD[k % 3] for k in range(BIG_BATHROOM - 3)]}
    out: dict = {"names": {}}
    for room, shots in plan.items():
        ids = []
        for kind, extra in shots:
            fields = {**garb, **extra, "setting": room, "description": f"Black set {room} {next_id}",
                      "tags": [room], **({"_frames": 6} if kind == "video" else {})}
            _insert(con, _item(w, aid, next_id, kind, at, fields, f"black lace bra thong {room}"))
            ids.append(next_id)
            truth["stills"] += kind == "photo"
            next_id += 1
        out[room] = ids
        out["names"][room] = script_name("black lingerie", room, at)
    truth["big_shoot"] = out
    return next_id


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
        sfw = ("photo", {"explicitness": "sfw", "clothing_state": "dressed", "acts": ["posing"]})
        sug = {"explicitness": "suggestive", "clothing_state": "lingerie_on", "acts": ["tease"]}
        xp = {"explicitness": "explicit", "clothing_state": "fully_nude", "acts": ["fingering"]}
        shoot = (sfw, sfw, sfw, ("photo", sug), ("video", {**sug, "_frames": 6}), ("photo", sug), ("photo", sug),
                 ("video", {**xp, "_frames": 6}), ("photo", xp), ("video", {**xp, "_frames": 6}))
        colourless = []
        for k, (kind, extra) in enumerate(shoot):
            mid, at = next_id + k, t0 + timedelta(minutes=10 * k)
            fields = {**garb, **extra, "description": f"Colourless set {k}", "tags": ["bed"]}
            _insert(con, _item(w, aid, mid, kind, at, fields, "bra thong bedroom"))
            colourless.append(mid)
            truth["stills"] += kind == "photo"
        next_id += len(shoot)
        # A colourless key carries its room, which the name shows once.
        truth["colourless_name"] = script_name("lingerie", "bedroom", t0)
        next_id = _big_shoot(w, con, aid, next_id, truth)

        folders = {}
        for name, list_id in (("AI-stories", None), ("AI-old lane", OLD_LIST)):
            cur = con.execute("INSERT INTO vault_folders(account_id, name, of_list_id, created_by, created_at)"
                              " VALUES (?,?,?,?,?)", (aid, name, list_id, AI_CREATOR, ts(w.now - timedelta(days=3))))
            folders[name] = int(cur.lastrowid)
    con.close()
    truth.update(copies=copies, colourless=colourless, kept_folder={"AI-stories": folders["AI-stories"]},
                 retired_folder={"AI-old lane": folders["AI-old lane"]})
    return truth
