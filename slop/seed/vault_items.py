"""Vault Pro's mirror: `vault_items` rows per Creator as the product leaves them after Collect sweeps
(`vault_mirror.row_values`: raw_json in OF's media shape with `listStates`, `of_folder_ids`, kind, duration,
created_at = OF's second-precision `createdAt`, `search_text` = kind, `last_seen_run_id`), then the passes that
layer on top: the thumb hash (`vault_dupes.pack_hash` / `HASH_KIND`; none for audio, which has no still, and
none for a few rows whose thumb is not cached yet), the describe pass (`describe_status` 'described',
`describe_model` its default, the prose in `description` (photo) or `video_description` (video), tags,
`explicitness_tier`, `frames_sampled` (video), `ai_fields_json` with `_prompt_version` / `_frames`,
`search_text` as `vault_ai_vision_decide.build_describe_update` folds it), the flags pass on most described
rows (the retired qwen flags pass's shape, gone since D52/D54: the regions, `underwear_visible`, an `over_*` garment only where one was named over
a covered region, `_flags_frames` on video, `_flags_model`, `_flags_v`), an operator grade on some (`_graded`, as
`vault_ai_fix.record_grade`), OF's search harvest on a few (`of_terms` + the term appended to `search_text`),
sends (`send_count`, `last_sent_at`) and earlier hides (`removed_at`). Two finished `vault_cache_runs` per
Creator: an earlier sweep that saw every row then uploaded, and the latest that saw every row not hidden since
(hidden rows keep the earlier sweep as `last_seen_run_id`, hidden between the two: a sweep that sees a row
clears `removed_at`, `vault_mirror.MIRROR_REFRESH_FIELDS`). AI folders (`vault_folders` created_by
'vault_ai_script' + `vault_folder_items` with an int `manual_order`, as `vault_scripts.apply_ai_folders` writes).

Uploads come in sessions (several media within seconds, some in the same second: OF's createdAt has no
finer grain), media ids rise with time as OF's do. About a fifth of the hashed media are re-uploads planted in
groups of 2 to 5: each copy is the original's bytes (same md5 and hashes), or a re-encode whose dHash / aHash
differ from the original's by 0 to 7 bits, each copy flipping bits no other copy of its group flips (so a
copy is d1 + d2 bits from another copy), cross-group hashes random 64-bit values (never within 8 bits in
practice). At most one video copy per group is a different edit (a decoy: duration 2 to 5 s off); the other
video copies are within 1 s. An original that has copies is never hidden. Planted flags: a covered region
with no garment named (`unexplained_cover`) or a dressed item with a bare region (`dressed_but_bare`); every
other flagged row is coherent (no `vault_ai_fix.IFFY_REASONS` fires).

`seed(w, creators, n)`: `n` = {account_id: item count}. Randomness only from `w.rng("vault_items")`.
Returns (and stores in `w.data["vault_items"]`) {account_id: {"of_folders": [{id, name}], "folders": [{id,
name}], "copies": {copy media_id: {"original", "dd", "da", "exact", "decoy"}} (planted distances to its
group's original), "iffy": {media_id} (the planted suspects)}}."""
from __future__ import annotations

import json
import math
from datetime import timedelta

from . import World, ts

HASH_KIND = "thumb/md5+dhash8+ahash8"   # vault_dupes.HASH_KIND
FLAGS_VERSION = 3                       # vault_ai_vision._FLAGS_VERSION
FLAGS_VIDEO_FRAMES = 4                  # the retired qwen flags pass's clip frames (D52/D54)
FRAME_LADDER = ((30, 6), (180, 9))      # vault_ai_vision_decide._FRAME_LADDER: describe stills by duration
FRAME_LADDER_MAX = 12                   # vault_ai_vision_decide._FRAME_LADDER_MAX
PROMPT_VERSION = "v2"                   # vault_ai_vision's default describe prompt
MODEL = "qwen3-vl-30b"                  # vault_ai_vision's default describe / flags model
OF_PAGE = 100                           # vault_ai_api._PAGE: a sweep's OF page
COLLECT_CAP = 200 * OF_PAGE             # vault_ai_api._MAX_PAGES x _PAGE: the most one Collect sweep mirrors
KINDS = (("photo", 0.60), ("video", 0.28), ("gif", 0.04), ("audio", 0.08))
VIS = ("not_in_frame", "covered", "bare")          # vault_ai_brief.VIS_STATES
REGIONS = ("vulva_vis", "breasts_vis", "anus_vis")  # vault_ai_brief.VIS_REGIONS
OVER = {"vulva_vis": ("over_vulva", "pink lace thong"), "breasts_vis": ("over_breasts", "black lace bra"),
        "anus_vis": ("over_anus", "denim shorts")}  # vault_ai_brief.OVER_KEYS + a garment it allows there
CLOTHING = ("dressed", "lingerie_on", "pulled_aside", "pulled_down", "partially_off", "fully_nude", "unclear")
OF_FOLDER_NAMES = ("Slop beach set", "Slop lingerie", "Slop shower clips", "Slop customs", "Slop teasers",
                   "Slop VIP")
AI_FOLDER_NAMES = ("AI-tease 10", "AI-safe explicit", "AI-mirror selfies")
WORDS = ("lingerie", "shower", "beach", "mirror", "selfie", "bed", "pool", "heels", "bikini", "outfit",
         "tease", "closeup", "pink", "red", "black", "stockings", "gym", "car", "outdoor", "pov")
HARVEST = ("feet", "cosplay", "travel")
UNHASHED_P = 0.02      # a photo / video / gif whose thumb is not cached yet (no hash)
COPY_P = 0.22          # a hashed photo / video / gif is a re-upload of an earlier one
EXACT_P = 0.35         # a copy that is the original's bytes
DECOY_P = 0.15         # a video copy that is another edit (duration off by 2-5 s), one per group at most
DESCRIBED_P = 0.55     # a photo / video the describe pass has done
FLAGGED_P = 0.85       # a described item the flags pass has done
GRADED_P = 0.12        # a flagged item an operator graded
UNDERWEAR_P = 0.5      # underwear_visible where the clothing does not decide it
UNNAMED_P = 0.10       # a covered region with no garment named
CONTRA_P = 0.04        # a flagged item called dressed with a bare region
HARVEST_P = 0.06       # an item OF's search harvest tagged with a term
HIDDEN_P = 0.03        # an item uploaded before the earlier sweep, hidden since
SENT_P = 0.12          # an item sent at least once
AI_FOLDER_P = (0.02, 0.08)   # the share of live items an AI folder holds


def _flip(rng, value: int, used: set[int], k: int) -> int:
    bits = rng.sample([b for b in range(64) if b not in used], k)
    used.update(bits)
    for b in bits:
        value ^= 1 << b
    return value


def seed(w: World, creators: list[dict], n: dict[str, int]) -> dict:
    rng = w.rng("vault_items")
    total = sum(n[c["id"]] for c in creators)
    ids = iter(sorted(rng.sample(range(2_500_000_000, 4_200_000_000), total)))
    of_ids = iter(rng.sample(range(10_000_000, 99_999_999), len(OF_FOLDER_NAMES) * len(creators)))
    out: dict = {}
    con = w.sql()
    with con:
        for c in creators:
            aid, cnt = c["id"], n[c["id"]]
            of_folders = [{"id": next(of_ids), "name": nm} for nm in OF_FOLDER_NAMES]
            of_p = [rng.uniform(0.03, 0.25) for _ in of_folders]
            first, started = w.now - timedelta(days=70), w.now - timedelta(hours=2)
            runs = [con.execute(
                "INSERT INTO vault_cache_runs(account_id, status, phase, total_seen, upserted, pages_done, "
                "started_at, finished_at) VALUES (?,?,?,?,?,?,?,?)",
                (aid, "done", "done", 0, 0, 0, ts(at), ts(at + timedelta(minutes=6)))).lastrowid
                for at in (first, started)]
            times = _timeline(rng, w.now, cnt)
            rows, copies, iffy, kept = _rows(rng, aid, times, ids, of_folders, of_p, runs[1], started)
            _hide_and_send(rng, rows, w.now, first, kept, runs[0])
            rows = [r for _, r in rows]
            cols = list(rows[0])
            con.executemany(f"INSERT INTO vault_items({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [tuple(r[k] for k in cols) for r in rows])
            for run, seen in zip(runs, (sum(1 for at in times if at < first),
                                        sum(1 for r in rows if r["removed_at"] is None))):
                con.execute("UPDATE vault_cache_runs SET total_seen=?, upserted=?, pages_done=? WHERE id=?",
                            (seen, seen, math.ceil(seen / OF_PAGE), run))
            folders = _ai_folders(rng, con, aid, rows, started)
            out[aid] = {"of_folders": of_folders, "folders": folders, "copies": copies, "iffy": iffy}
    con.close()
    w.data["vault_items"] = out
    return out


def _timeline(rng, now, cnt: int) -> list:
    """The upload timeline: sessions over two years, items 0-3 s apart (0: the same second)."""
    times = []
    t = now - timedelta(days=730)
    while len(times) < cnt:
        t += timedelta(seconds=rng.randint(600, 2 * 86400))
        at = t
        for _ in range(min(cnt - len(times), rng.randint(1, 40))):
            times.append(at)
            at += timedelta(seconds=rng.choice((0, 0, 1, 1, 2, 3)))
    times.sort()
    return times


def _rows(rng, aid, times, ids, of_folders, of_p, run_id, started):
    """One row per upload as the latest sweep left it, with its planted hash, describe / flags and harvest.
    Returns ([(at, row)], copies, iffy, the originals that have copies)."""
    kinds, weights = zip(*KINDS)
    rows, copies, iffy = [], {}, set()
    groups = []   # [{original, kind, dur, md5, dh, ah, used_d, used_a, n, decoy}]
    for at in times:
        mid = next(ids)
        kind = rng.choices(kinds, weights)[0]
        dur = rng.randint(5, 600) if kind == "video" else rng.randint(3, 60) if kind == "audio" else None
        hashed = kind != "audio" and rng.random() >= UNHASHED_P
        md5 = dh = ah = None
        if hashed:
            md5, dh, ah, dur = _plant_hash(rng, mid, kind, dur, groups, copies)
        member = [rng.random() < p for p in of_p]
        created = at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        raw = {"id": mid, "type": kind, "convertedToVideo": False, "canView": True, "hasError": False,
               "createdAt": created, "isReady": True,
               **({"duration": dur} if dur else {}),
               "listStates": [{"id": f["id"], "type": "custom", "name": f["name"], "hasMedia": m,
                               "canAddMedia": True} for f, m in zip(of_folders, member)]}
        row = {"account_id": aid, "media_id": mid, "kind": kind, "duration_seconds": dur,
               "raw_json": json.dumps(raw), "created_at": ts(at), "updated_at": ts(started),
               "of_folder_ids": json.dumps([f["id"] for f, m in zip(of_folders, member) if m]),
               "search_text": kind, "tags": "[]", "last_seen_run_id": run_id,
               "content_hash": f"{md5}:{dh:016x}:{ah:016x}" if hashed else None,
               "content_hash_kind": HASH_KIND if hashed else None,
               "send_count": 0, "last_sent_at": None, "removed_at": None, "description": None,
               "video_description": None, "describe_status": None, "describe_model": None,
               "describe_generated_at": None, "ai_fields_json": None, "of_terms": None,
               "explicitness_tier": None, "frames_sampled": None}
        if kind in ("photo", "video") and rng.random() < DESCRIBED_P:
            if _describe(rng, row):
                iffy.add(mid)
        if rng.random() < HARVEST_P:
            term = rng.choice(HARVEST)
            row["of_terms"] = json.dumps([term])
            row["search_text"] = f"{row['search_text']} {term}".strip().lower()
        rows.append((at, row))
    return rows, copies, iffy, {g["original"] for g in groups if g["n"] > 1}


def _plant_hash(rng, mid, kind, dur, groups, copies):
    """(md5, dHash, aHash, duration) for a hashed upload: a copy of a recent group's original (recorded in
    `copies`) or a new original (appended to `groups`)."""
    pool = [g for g in groups[-400:] if g["n"] < 5 and g["kind"] == kind]
    if not (pool and rng.random() < COPY_P):
        md5, dh, ah = "%032x" % rng.getrandbits(128), rng.getrandbits(64), rng.getrandbits(64)
        groups.append({"original": mid, "kind": kind, "dur": dur, "md5": md5, "dh": dh, "ah": ah,
                       "used_d": set(), "used_a": set(), "n": 1, "decoy": False})
        return md5, dh, ah, dur
    gi = rng.choice(pool)
    gi["n"] += 1
    exact = rng.random() < EXACT_P
    if exact:
        md5, dh, ah, dd, da = gi["md5"], gi["dh"], gi["ah"], 0, 0
    else:
        dd = rng.randint(0, 7)
        da = rng.choice((dd, max(0, dd - 1)))
        md5 = "%032x" % rng.getrandbits(128)
        dh = _flip(rng, gi["dh"], gi["used_d"], dd)
        ah = _flip(rng, gi["ah"], gi["used_a"], da)
    decoy = kind == "video" and not gi["decoy"] and rng.random() < DECOY_P
    if kind == "video":
        gi["decoy"] |= decoy
        dur = gi["dur"] + (rng.randint(2, 5) if decoy else rng.choice((0, 0, 1)))
    copies[mid] = {"original": gi["original"], "dd": dd, "da": da, "exact": exact, "decoy": decoy}
    return md5, dh, ah, dur


def _hide_and_send(rng, rows, now, first, kept, early_run) -> None:
    """Earlier hides: uploaded before the earlier sweep, hidden between the two sweeps; never an original that
    has copies (`kept`). Sends and the describe end by the hide."""
    for at, row in rows:
        end = now
        if at < first and row["media_id"] not in kept and rng.random() < HIDDEN_P:
            end = now - timedelta(days=rng.randint(1, 60))
            row.update(removed_at=ts(end), last_seen_run_id=early_run, updated_at=ts(first),
                       describe_generated_at=row["describe_generated_at"] and ts(first))
        if rng.random() < SENT_P:
            row["send_count"] = rng.randint(1, 20)
            row["last_sent_at"] = ts(at + (end - at) * rng.random())


def _ai_folders(rng, con, aid, rows, started) -> list[dict]:
    """AI folders over live items, as `vault_scripts.apply_ai_folders` writes them."""
    folders = []
    live = [r["media_id"] for r in rows if r["removed_at"] is None]
    for nm in AI_FOLDER_NAMES:
        fid = con.execute("INSERT INTO vault_folders(account_id, name, created_by, created_at) "
                          "VALUES (?,?,?,?)", (aid, nm, "vault_ai_script", ts(started))).lastrowid
        picks = rng.sample(live, max(1, int(len(live) * rng.uniform(*AI_FOLDER_P))))
        orders = list(range(len(picks)))
        for k in range(min(3, len(picks) // 4)):   # the tail pinned last (-1, -2, ...), as reorder allows
            orders[-1 - k] = -1 - k
        con.executemany("INSERT INTO vault_folder_items(account_id, folder_id, media_id, manual_order, "
                        "added_at) VALUES (?,?,?,?,?)",
                        [(aid, fid, m, o, ts(started)) for m, o in zip(picks, orders)])
        folders.append({"id": fid, "name": nm})
    return folders


def _describe_frames(row: dict) -> int:
    """Stills the describe sent: 1 for a photo, the duration ladder for a clip (`_frames_for_duration`)."""
    if row["kind"] != "video":
        return 1
    return next((n for limit, n in FRAME_LADDER if (row["duration_seconds"] or 0) < limit), FRAME_LADDER_MAX)


def _describe(rng, row: dict) -> bool:
    """The describe pass's columns (vault_ai_vision_decide.build_describe_update), the flags pass's on most
    (the retired qwen flags shape), an operator grade on some. True when the flags planted a suspect."""
    tags = rng.sample(WORDS, rng.randint(2, 5))
    desc = f"{rng.choice(('Solo', 'Close', 'Playful', 'Soft'))} {row['kind']} with {tags[0]} and {tags[1]}"
    cl = rng.choice(CLOTHING)
    video = row["kind"] == "video"
    frames = _describe_frames(row)
    fields: dict = {"description": desc, "tags": tags, "clothing_state": cl,
                    "_prompt_version": PROMPT_VERSION, "_frames": frames}
    iffy = False
    if rng.random() < FLAGGED_P:
        regions = {r: rng.choice(VIS) for r in REGIONS}
        if cl == "dressed":
            regions = {r: "covered" if v == "bare" else v for r, v in regions.items()}
        unnamed = {r for r, v in regions.items() if v == "covered" and rng.random() < UNNAMED_P}
        if rng.random() < CONTRA_P:    # dressed_but_bare
            cl = fields["clothing_state"] = "dressed"
            bare = rng.choice(REGIONS)
            regions[bare] = "bare"
            unnamed.discard(bare)
        iffy = bool(unnamed) or (cl == "dressed" and "bare" in regions.values())
        states = set(regions.values())
        tier = (("suggestive", "explicit") if "bare" in states else ("sfw", "suggestive") if states == {"not_in_frame"}
                else ("sfw", "suggestive", "explicit"))
        fields["explicitness"] = rng.choice(tier)
        fields["underwear_visible"] = (True if cl == "lingerie_on" else False if cl == "fully_nude"
                                       else rng.random() < UNDERWEAR_P)
        fields.update(regions)
        for r, v in regions.items():
            if v == "covered" and r not in unnamed:
                fields[OVER[r][0]] = OVER[r][1]
        if video:
            fields["_flags_frames"] = FLAGS_VIDEO_FRAMES
        fields.update(_flags_model=MODEL, _flags_v=FLAGS_VERSION)
        if rng.random() < GRADED_P:
            fields["_graded"] = {"v": rng.choice((FLAGS_VERSION, FLAGS_VERSION - 1)),
                                 "confirmed": {r: fields[r] for r in REGIONS}, "corrected": []}
    else:
        fields["explicitness"] = rng.choice(("sfw", "suggestive", "explicit"))
    row.update(describe_status="described", tags=json.dumps(tags), ai_fields_json=json.dumps(fields),
               describe_model=MODEL, describe_generated_at=row["updated_at"],
               explicitness_tier=fields["explicitness"], frames_sampled=frames if video else None,
               search_text=" ".join([desc, *tags, cl]).lower(),
               description=None if video else desc, video_description=desc if video else None)
    return iffy
