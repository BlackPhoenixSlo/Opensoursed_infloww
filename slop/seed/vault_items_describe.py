"""Vault mirrors ready for a describe sweep (scenarios/2026-11-01-vault-describe-sweep.py), in two steps around the
scenario's arm of lib/vault_describe_relay.py (which needs the planned items for its outcomes file and answers the
still stores' dirs and the clips' storyboard hashes this writes into):

  plan(w, creators, n)   per Creator its share of `n` items (photos, clips of 10 / 60 / 400 s: 6, 9 or 12 frames,
                         and a few audio files; OF's own createdAt spread over a year). CACHE_FRAC of the photos and
                         clips were described by an earlier sweep (`cached`); of the rest a deterministic REFUSE_FRAC
                         (M30 refuses, M235 answers) and BLANK_FRAC (both blank), the rest `ok`. Every Creator gets
                         at least one cached, ok, refuse and blank item (raises if its share has < MIN_VISUAL photos
                         and clips: raise `--set items=`). Then per Creator the planted re-upload sets (`DUPE_SETS`,
                         own rng stream so the rest of the plan is unchanged): members share one thumb (byte-
                         identical, or `near`: one pixel edited, other bytes, hash distance <= 1 measured over 400
                         sets), clips of one set one duration; a set's members are `ok` (and one `cached` where the
                         recipe says so). A recipe the Creator's share cannot fill is skipped.
  seed(w, items, armed)  writes them:
    rows      `vault_items` (SQL): `raw_json` in OF's vault shape (a clip's `videoSources["240"]`), no AI fields;
              a cached row carries the columns `build_describe_update` writes (description or video_description,
              tags, tier, `describe_call_id` -> its own `grok_calls` audit row, `ai_fields_json` stamped
              `_prompt_version: v2`, `_frames` by the duration ladder, flagged at `_flags_v` 3, a clip's
              `_flags_frames` 4 / `_flags_arc` as the retired qwen flags pass left them).
    stills    each photo's `IMAGE_DIR/<acct>/<id>.jpg` and each clip's `armed["frames"]` storyboard frames under its
              url's hash (what `vault_frames.collect` reads; none for a clip the scenario marked `storyboard`
              False: the product writes them, scenarios/2026-11-11-vault-jev-flags.py), and for every photo/clip a
              300px stand-in
              `THUMB_DIR/<acct>/<id>.jpg` (the grid tile: Vault Pro's `_thumb`, `/admin/vault-ai/thumb`, read by the
              UI run, and what `vault_dupes` hashes; audio has no still, `vault_mirror.has_still`): a 9x8 grey grid
              from its own seed, so unrelated thumbs sit >= 16 bits apart on dHash/aHash (measured over 2000) and
              only the planted sets cluster at threshold 2. Each item's picture has its own pixel size (`size`), so
              the fake can tell which item a call is about.

Randomness only from `w.rng("vault_items_describe")`. Output `w.data["vault_items_describe"]`: one dict per item:
key ("acct:id"), account_id, media_id, kind, duration, size, url (a clip's 240p url, else None), created_at, of_at,
cached, outcome (None for audio), seeded_description (a cached row's, else None), dupe_set (its planted set's id,
else None), thumb ([seed, tweak]: tweak > 0 = a near copy's edited pixel).
"""
from __future__ import annotations

import io
import json
import random
from datetime import timedelta
from pathlib import Path

from slop.lib.vault_describe_relay import M30

from . import World, ts

ID_BASE = 5_500_000_000
VIDEO_FRAC, AUDIO_FRAC = 0.25, 0.03
CACHE_FRAC, REFUSE_FRAC, BLANK_FRAC = 0.15, 0.08, 0.04
# Clip duration -> describe frames (service/vault_ai_vision_decide.py `_FRAME_LADDER`: <30 s 6, <180 s 9, else 12).
FRAMES = {10: 6, 60: 9, 400: 12}
FLAGS_CLIP_FRAMES = 4  # the retired qwen flags pass's clip frames (D52/D54)
MIN_VISUAL = 4  # one cached, ok, refuse and blank per Creator
# Planted re-upload sets per Creator: (name, kind, uncached ok members, + one cached member, near copies).
DUPE_SETS = (("photo-pair", "photo", 2, False, False), ("photo-triple-near", "photo", 3, False, True),
             ("photo-of-cached", "photo", 1, True, False), ("clip-pair-near", "video", 2, False, True))


def key(account_id, media_id) -> str:
    """An item's key ("acct:id"), the seeder's and the scenario's one spelling."""
    return f"{account_id}:{media_id}"


def _cdn(aid: str, mid: int) -> str:
    return f"https://cdn2.onlyfans.com/files/slop/{aid}/{mid}"


def size(i: int) -> tuple[int, int]:
    """Item i's (global index) picture size: unique, both edges <= 448 (`vision.MAX_EDGE_DEFAULT`, never enlarged)."""
    return 16 + i % 256, 16 + i // 256


def _jpeg(wh: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", wh, rgb).save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _thumb(seed: str, tweak: int = 0) -> bytes:
    """A 300px grid tile: 9x8 grey cells from `seed` (dHash reads 9x8, so its bits are the cells' order). tweak > 0
    sets pixel (0, 0) apart: other bytes, same hashes."""
    from PIL import Image
    rng = random.Random(seed)
    g = Image.new("L", (9, 8))
    g.putdata([rng.randrange(256) for _ in range(72)])
    im = g.resize((300, 300), Image.NEAREST).convert("RGB")
    if tweak:
        v = (im.getpixel((0, 0))[0] + 80 * tweak) % 256
        im.putpixel((0, 0), (v, v, v))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _plant(rng, aid: str, mine: list[dict]) -> None:
    """`DUPE_SETS` into one Creator's planned items (module docstring)."""
    free = [it for it in mine if it["kind"] != "audio"]
    for name, kind, n_ok, with_cached, near in DUPE_SETS:
        oks = [it for it in free if it["kind"] == kind and it["outcome"] == "ok" and not it["cached"]]
        cached = [it for it in free if it["kind"] == kind and it["cached"]] if with_cached else []
        if len(oks) < n_ok or (with_cached and not cached):
            continue
        members = rng.sample(cached, 1) + rng.sample(oks, n_ok) if with_cached else rng.sample(oks, n_ok)
        sid = f"{aid}:{name}"
        for j, it in enumerate(members):
            it["dupe_set"], it["thumb"] = sid, [sid, j if near else 0]
            if kind == "video":
                it["duration"] = members[0]["duration"]  # the finder compares clips of one duration only
            free.remove(it)


def plan(w: World, creators: list[dict], n: int) -> list[dict]:
    rng = w.rng("vault_items_describe")
    dupes_rng = w.rng("vault_items_describe.dupes")
    items: list[dict] = []
    for ci, c in enumerate(creators):
        k_n = n // len(creators) + (1 if ci < n % len(creators) else 0)
        mine = []
        for k in range(k_n):
            r = rng.random()
            kind = "audio" if r < AUDIO_FRAC else "video" if r < AUDIO_FRAC + VIDEO_FRAC else "photo"
            aid, mid = c["id"], ID_BASE + ci * 100_000 + k
            duration = rng.choice(tuple(FRAMES)) if kind != "photo" else None
            created = w.now - timedelta(minutes=rng.randrange(0, 365 * 24 * 60))
            mine.append({"key": key(aid, mid), "account_id": aid, "media_id": mid, "kind": kind,
                         "duration": duration, "size": size(len(items) + k),
                         "url": f"{_cdn(aid, mid)}_240.mp4?Policy=slop" if kind == "video" else None,
                         "created_at": ts(created), "of_at": created.isoformat() + "+00:00",
                         "cached": False, "outcome": None, "seeded_description": None,
                         "dupe_set": None, "thumb": [key(aid, mid), 0]})
        vis = [it for it in mine if it["kind"] != "audio"]
        if len(vis) < MIN_VISUAL:
            raise ValueError(f"slop: vault_items_describe: Creator {c['id']} got {len(vis)} photos/clips "
                             f"(< {MIN_VISUAL}); raise --set items= (now {n} over {len(creators)} Creators)")
        for it in rng.sample(vis, max(1, round(CACHE_FRAC * len(vis)))):
            it["cached"], it["outcome"] = True, "ok"
            it["seeded_description"] = f"seeded earlier description {it['key']}"
        todo = [it for it in vis if not it["cached"]]
        n_ref, n_blank = max(1, round(REFUSE_FRAC * len(todo))), max(1, round(BLANK_FRAC * len(todo)))
        for j, it in enumerate(rng.sample(todo, n_ref + n_blank)):  # < len(todo): one ok at least
            it["outcome"] = "refuse" if j < n_ref else "blank"
        for it in todo:
            it["outcome"] = it["outcome"] or "ok"
        _plant(dupes_rng, c["id"], mine)
        items += mine
    return items


async def seed(w: World, items: list[dict], armed: dict) -> list[dict]:
    dirs = {k: Path(v) for k, v in armed["dirs"].items()}
    con = w.sql()
    with con:
        for it in items:
            aid, mid, kind = it["account_id"], it["media_id"], it["kind"]
            pic = _jpeg(it["size"], (mid % 200 + 30, (mid // 7) % 200 + 30, 120))
            if kind != "audio":
                (dirs["thumbs"] / aid).mkdir(parents=True, exist_ok=True)
                (dirs["thumbs"] / aid / f"{mid}.jpg").write_bytes(_thumb(*it["thumb"]))
            if kind == "photo":
                (dirs["images"] / aid).mkdir(parents=True, exist_ok=True)
                (dirs["images"] / aid / f"{mid}.jpg").write_bytes(pic)
            elif kind == "video" and it.get("storyboard", True):
                sb = dirs["storyboard"] / armed["hashes"][it["url"]]
                sb.mkdir(parents=True, exist_ok=True)
                for f in range(armed["frames"]):
                    (sb / f"{f}.jpg").write_bytes(pic)
            cdn = _cdn(aid, mid)
            raw = {"id": mid, "type": kind, "createdAt": it["of_at"], "isReady": True, "hasError": False,
                   "canView": True, "duration": it["duration"] or 0,
                   "files": {"thumb": {"url": f"{cdn}_thumb.jpg"}, "preview": {"url": f"{cdn}_preview.jpg"}}}
            if kind == "video":
                raw["videoSources"] = {"240": it["url"], "720": None}
            cols = {"account_id": aid, "media_id": mid, "kind": kind, "duration_seconds": it["duration"],
                    "width": it["size"][0], "height": it["size"][1], "thumb_url": f"{cdn}_thumb.jpg",
                    "tags": "[]", "send_count": 0, "raw_json": json.dumps(raw), "created_at": it["created_at"],
                    "updated_at_of": it["of_at"], "updated_at": ts(w.now)}
            if it["cached"]:
                desc, tags, when = it["seeded_description"], ["seeded", kind], ts(w.now - timedelta(days=3))
                frames = FRAMES[it["duration"]] if kind == "video" else 1
                ai = {"description": desc, "tags": tags, "explicitness": "suggestive", "nsfw": True,
                      "sellable": True, "_prompt_version": "v2", "_frames": frames,
                      "underwear_visible": False, "breasts_vis": "covered", "vulva_vis": "not_in_frame",
                      "anus_vis": "not_in_frame", "over_breasts": "black top", "_flags_model": M30, "_flags_v": 3}
                if kind == "video":
                    ai.update(_flags_frames=FLAGS_CLIP_FRAMES, _flags_arc="flat")  # same state first to last frame
                call_id = con.execute(  # llm_client's audit row for the describe call (finalized, cost not counted)
                    "INSERT INTO grok_calls (purpose, provider, status, account_id, model, endpoint, temperature, "
                    "prompt_json, was_dry_run, called_at) VALUES ('describe_media', 'deepinfra', 'done', ?, ?, "
                    "'/v1/openai/chat/completions', 0.1, '{}', 0, ?)", (aid, M30, when)).lastrowid
                cols.update({"describe_status": "described", "describe_model": M30, "describe_call_id": call_id,
                             "describe_generated_at": when, "tags": json.dumps(tags),
                             "explicitness_tier": "suggestive", "tip_vault_flag": 1,
                             "search_text": " ".join([desc, *tags]).lower(),
                             "ai_fields_json": json.dumps(ai),
                             "frames_sampled": frames if kind == "video" else None,
                             ("video_description" if kind == "video" else "description"): desc})
            con.execute(f"INSERT INTO vault_items ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        tuple(cols.values()))
    con.close()
    w.data["vault_items_describe"] = items
    return items
