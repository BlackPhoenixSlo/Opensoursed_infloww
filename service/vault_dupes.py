"""service/vault_dupes.py — duplicate / re-upload detection over the vault mirror.

Re-uploads pile up in a creator's vault: on Ava 706 of 2,309 items (30.6%) are
copies of something already there. Every copy costs a describe call, clutters the
picker, and splits a folder's ordering. This module finds them; hiding them is a
separate, operator-confirmed step (`vault_ai_api` → `of_client.hide_vault_media`).

Signals, all computed from the ALREADY-CACHED 300px thumbs on disk
(`vault_stills.thumb_path`) — no OF traffic, no LLM, ~2s for a 2.3k-item vault:

  md5    byte-identical thumb. Never a false positive.
  dHash  64-bit gradient hash — survives the re-encode OF applies to a re-upload.
  aHash  64-bit mean hash. Required to agree as well: dHash alone matches on
         layout, so two frames of one burst can collide; the second independent
         hash is what keeps them apart.

Clustering is SEED-BASED, never transitive. Items are walked oldest-first; each
unclaimed item becomes a seed (the ORIGINAL — earliest OF `createdAt`) and later
items join only if they are within threshold of THAT SEED. Union-find chaining
(a~b, b~c ⇒ a~c) would let a cluster drift away from its original, which is the
one failure that could hide a photo the operator meant to keep.

Threshold: default 2, and that is not a compromise. Measured on Ava, the match
curve is flat past 2 — ≤0 finds 644 copies, ≤2 finds 706, ≤8 finds only 737 — so
loosening buys ~4% more at the cost of dragging in every "same shoot, different
frame" near-miss. All 199 sets at ≤2 were operator-confirmed correct (2026-07-21).

Videos additionally require a duration match (±1s) before their thumbs are
compared at all: two clips can share a poster frame and be different edits.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from bisect import bisect_right
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

import vault_mirror
from db.engine import get_session
from db.models import VaultItem

log = logging.getLogger("of-relay.vault_dupes")

# Bands the review UI colour-codes. Distance 0 on BOTH hashes is visually
# indistinguishable at thumb resolution; the higher bands are where an operator
# actually has to look, which is why the confirm screen shows them separately.
BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "identical"),
    (1, 2, "near"),
    (3, 5, "similar"),
    (6, 8, "loose"),
)

DEFAULT_THRESHOLD = 2
MAX_THRESHOLD = 8
HASH_KIND = "thumb/md5+dhash8+ahash8"
# Videos whose durations differ by more than this are never compared.
_VIDEO_DUR_TOLERANCE_S = 1


def band_of(distance: int) -> str:
    for lo, hi, name in BANDS:
        if lo <= distance <= hi:
            return name
    return "far"


# ── Hashing ─────────────────────────────────────────────────────────
#
# Pillow is imported lazily, INSIDE the functions that need it. It is a
# capture-host dep that requirements.txt deliberately keeps out of the relay
# image, and a module-level `from PIL import Image` here crash-looped the whole
# relay on deploy — every send down because a duplicate-finder could not load an
# image library. A vault helper must never be able to do that: if Pillow is
# absent, `fingerprint_file` returns None and only dupe detection goes quiet.


def dhash(img: "Image.Image") -> int:
    """64-bit gradient hash: each bit = "is this pixel darker than its right
    neighbour". Insensitive to the brightness/contrast shift a re-encode adds."""
    from PIL import Image
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(8):
        row = px[r * 9:(r + 1) * 9]
        for c in range(8):
            bits = (bits << 1) | (1 if row[c] < row[c + 1] else 0)
    return bits


def ahash(img: "Image.Image") -> int:
    """64-bit mean hash: each bit = "is this pixel above the image mean"."""
    from PIL import Image
    g = img.convert("L").resize((8, 8), Image.LANCZOS)
    px = list(g.getdata())
    avg = sum(px) / 64.0
    bits = 0
    for p in px:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def pack_hash(md5: str, dh: int, ah: int) -> str:
    """The single `content_hash` string persisted on the row. Self-describing so
    a future hash version can be told apart (`content_hash_kind`)."""
    return f"{md5}:{dh:016x}:{ah:016x}"


def unpack_hash(packed: str | None) -> tuple[str, int, int] | None:
    if not packed:
        return None
    parts = packed.split(":")
    if len(parts) != 3:
        return None
    try:
        return parts[0], int(parts[1], 16), int(parts[2], 16)
    except ValueError:
        return None


def fingerprint_file(path: Path) -> tuple[str, int, int] | None:
    """(md5, dhash, ahash) for a cached thumb. None if missing/unreadable — a
    truncated cache file must not take down a whole scan."""
    try:
        from PIL import Image
        raw = path.read_bytes()
        with Image.open(path) as im:
            im.load()
            return hashlib.md5(raw).hexdigest(), dhash(im), ahash(im)
    except Exception:  # noqa: BLE001
        return None


# ── Persistence ─────────────────────────────────────────────────────

async def ensure_hashes(account_id: str, *, force: bool = False,
                        allowed: frozenset[int] | None = None) -> dict[str, int]:
    """Fill `content_hash` for every mirrored item whose thumb is cached.

    Incremental: rows that already carry a current-kind hash are skipped unless
    `force`, so a re-scan after a collect only hashes the NEW media. Runs the
    (CPU-bound, ~1ms/item) Pillow work in a thread so it can't stall the relay's
    event loop.
    """
    from vault_stills import thumb_path  # the permanent, signature-free store

    async with get_session() as s:
        q = (
            select(VaultItem.media_id, VaultItem.content_hash,
                   VaultItem.content_hash_kind)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None),
                   vault_mirror.visible_to(allowed))
        )
        rows = (await s.execute(q)).all()

    todo = [int(mid) for mid, h, kind in rows
            if force or not h or kind != HASH_KIND]
    if not todo:
        return {"hashed": 0, "skipped": len(rows), "missing_thumb": 0}

    def _work() -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for mid in todo:
            fp = fingerprint_file(thumb_path(account_id, mid))
            if fp is not None:
                out.append((mid, pack_hash(*fp)))
        return out

    computed = await asyncio.to_thread(_work)
    async with get_session() as s:
        for mid, packed in computed:
            await s.execute(
                update(VaultItem)
                .where(VaultItem.account_id == account_id,
                       VaultItem.media_id == mid)
                .values(content_hash=packed, content_hash_kind=HASH_KIND)
            )
        await s.commit()
    return {"hashed": len(computed), "skipped": len(rows) - len(todo),
            "missing_thumb": len(todo) - len(computed)}


# ── Clustering ──────────────────────────────────────────────────────

def cluster(items: list[dict], threshold: int) -> list[dict]:
    """Seed-based grouping, oldest-first. Returns sets of >= 2 where `original`
    is the earliest-uploaded item and `dupes` are the removable copies.

    A seed tests only the later items that share a bucket with it, not every
    later item: a pair within `threshold` on the 64-bit dhash agrees exactly on
    at least one of threshold+1 disjoint dhash bands (pigeonhole), and an exact
    copy shares its md5. Buckets are per kind and candidates are walked in
    sorted order, so the sets are the all-pairs walk's (test_vault_dupes)."""
    items = sorted(items, key=lambda r: (r["created_at"], r["media_id"]))
    n_bands = max(1, threshold + 1)   # threshold < 0: one band, still a superset
    edges = [64 * j // n_bands for j in range(n_bands + 1)]
    bands = [(j, edges[j], (1 << (edges[j + 1] - edges[j])) - 1)
             for j in range(n_bands)]

    keys = [[(r["kind"], "md5", r["md5"])] + [
        (r["kind"], j, (r["dhash"] >> lo) & mask) for j, lo, mask in bands]
        for r in items]
    buckets: dict[tuple, list[int]] = {}
    for pos, ks in enumerate(keys):
        for key in ks:
            buckets.setdefault(key, []).append(pos)

    claimed: set[int] = set()
    clusters: list[dict] = []

    for i, seed in enumerate(items):
        if seed["media_id"] in claimed:
            continue
        later: set[int] = set()
        for key in keys[i]:
            b = buckets[key]
            later.update(b[bisect_right(b, i):])
        dupes: list[dict] = []
        for pos in sorted(later):
            cand = items[pos]
            if cand["media_id"] in claimed:
                continue
            if seed["kind"] == "video":
                if abs((seed["duration"] or 0) - (cand["duration"] or 0)) > \
                        _VIDEO_DUR_TOLERANCE_S:
                    continue
            if cand["md5"] == seed["md5"]:
                dd = da = 0
                exact = True
            else:
                dd = hamming(seed["dhash"], cand["dhash"])
                if dd > threshold:
                    continue
                da = hamming(seed["ahash"], cand["ahash"])
                if da > threshold:
                    continue
                exact = False
            dupes.append({**cand, "dhash_dist": dd, "ahash_dist": da,
                          "exact": exact})
        if not dupes:
            continue
        claimed.add(seed["media_id"])
        claimed.update(d["media_id"] for d in dupes)
        worst = max(max(d["dhash_dist"], d["ahash_dist"]) for d in dupes)
        clusters.append({
            "original": seed, "dupes": dupes, "worst": worst,
            "band": band_of(worst),
            "all_exact": all(d["exact"] for d in dupes),
        })
    clusters.sort(key=lambda c: (-len(c["dupes"]), c["worst"]))
    return clusters


async def load_fingerprints(account_id: str, allowed: frozenset[int] | None = None) -> tuple[list[dict], int]:
    """Every mirrored item that carries a usable hash, + the count that doesn't
    (no cached thumb yet — those are simply not candidates)."""
    async with get_session() as s:
        q = (
            select(VaultItem.media_id, VaultItem.kind, VaultItem.created_at,
                   VaultItem.duration_seconds, VaultItem.content_hash,
                   VaultItem.send_count)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None),
                   vault_mirror.visible_to(allowed))
        )
        rows = (await s.execute(q)).all()
    items: list[dict] = []
    unhashed = 0
    for mid, kind, created, dur, packed, sends in rows:
        fp = unpack_hash(packed)
        if fp is None:
            unhashed += 1
            continue
        md5, dh, ah = fp
        items.append({"media_id": int(mid), "kind": kind, "created_at": created,
                      "duration": dur, "md5": md5, "dhash": dh, "ahash": ah,
                      "send_count": int(sends or 0)})
    return items, unhashed


async def find_duplicates(account_id: str, threshold: int = DEFAULT_THRESHOLD,
                          *, rehash: bool = True,
                          allowed: frozenset[int] | None = None) -> dict[str, Any]:
    """Full scan: (re)hash new media, then cluster. The result feeds the review
    UI — nothing is hidden here."""
    threshold = max(0, min(MAX_THRESHOLD, int(threshold)))
    hashed = await ensure_hashes(account_id, allowed=allowed) if rehash else {}
    items, unhashed = await load_fingerprints(account_id, allowed=allowed)
    clusters = await asyncio.to_thread(cluster, items, threshold)
    return {
        "threshold": threshold,
        "scanned": len(items),
        "unhashed": unhashed,
        "sets": len(clusters),
        "removable": sum(len(c["dupes"]) for c in clusters),
        "hashed": hashed,
        "clusters": clusters,
    }


# ── Answer reuse (the vision sweeps) ────────────────────────────────
#
# A thumb cluster above is good enough for an operator to confirm a hide; it is
# NOT good enough to hand one item's describe + flags answer to another. Thumbs
# are 300px centre crops and flags are judged on the FULL frame, so a cropped
# tease and a full nude can share a thumb — and even full-frame dHash+aHash
# equality missed two 60px censor stickers on a 960x1280 frame in 15/40 trials
# (review of 580c71166). So reuse is PHOTOS ONLY (a clip's describe reads many
# frames; one poster proves nothing about the rest) and needs the cached
# full-frame preview (`vault_stills.image_path`, warmed by every collect) to be
# byte-identical, or pixel-identical within `FRAME_MAX_DIFF`.
#
# The pixel test: same size, then the mean |RGB difference| over every 4x4
# block (`ImageChops.difference(...).reduce(4)`), max over blocks and channels.
# Measured 2026-11-10 on 15 real 960x1280 photo crops + 16 synthetic textured
# frames (sensor-like noise σ 8 and σ 24), saved q85; edits re-saved at q70/85/95:
#
#                                     max block diff
#     re-encode q85 / q90 / q95        <= 12 (real), <= 9 / 11 (synthetic)
#     re-encode q80                    <= 16  → over the limit: NOT reused
#     re-encode q70                    <= 26  → NOT reused
#     20-60px solid sticker (40/40)    >= 45
#     20-60px blur patch r4-8 (40/40)  >= 14 (patch placed on detail)
#     2-10% crop, rescaled (40/40)     >= 116
#
# A q70-80 re-encode overlaps a blur patch on this measure, and the brief is
# "unsure → no reuse", so those pay for their own call. The limit is 12.
FRAME_BLOCK = 4
FRAME_MAX_DIFF = 12


def load_frame(path: Path) -> dict | None:
    """One cached frame, read ONCE: {"md5", "size", "path"}. The RGB pixels are
    decoded lazily, at most once (`_rgb`), and only when a same-size, different-
    bytes partner needs them — so a cluster costs one read per member and one
    decode per member that is actually compared. None when missing/unreadable."""
    try:
        from PIL import Image
        raw = path.read_bytes()
        with Image.open(path) as im:
            size = im.size
        return {"md5": hashlib.md5(raw).hexdigest(), "size": size, "path": path}
    except Exception:  # noqa: BLE001
        return None


def _rgb(frame: dict):
    if "rgb" not in frame:
        from PIL import Image
        with Image.open(frame["path"]) as im:
            frame["rgb"] = im.convert("RGB")
    return frame["rgb"]


def frames_match(a: dict | None, b: dict | None) -> bool:
    """May two loaded frames share one vision answer? Identical bytes, or same
    size and a max 4x4-block mean |RGB difference| within `FRAME_MAX_DIFF`.
    The diff is taken at FULL resolution and then block-averaged — averaging
    first would hide a blur patch, which keeps its block means. Unreadable → no."""
    if a is None or b is None:
        return False
    if a["md5"] == b["md5"]:
        return True
    if a["size"] != b["size"]:
        return False
    try:
        from PIL import ImageChops
        d = ImageChops.difference(_rgb(a), _rgb(b))
        return max(hi for _lo, hi in d.reduce(FRAME_BLOCK).getextrema()) <= FRAME_MAX_DIFF
    except Exception:  # noqa: BLE001
        return False


def same_frame(a: Path, b: Path) -> bool:
    """`frames_match` for two paths (one-off comparisons and the tests)."""
    return frames_match(load_frame(a), load_frame(b))


def frame_groups(members: list[dict], same) -> list[list[int]]:
    """Split one thumb cluster (oldest first; each {"media_id", "width",
    "height"}) into groups whose members ALL pairwise share a full frame by
    `same(a, b)` — a member joins a group only if it matches every member
    already in it, so any two members of a group were compared directly and a
    copy's source is always an item it was checked against (never two hops,
    up to 2 x FRAME_MAX_DIFF apart). OF dims must agree whenever both rows carry
    them. Only groups of >= 2 are returned."""
    def dims_agree(a: dict, b: dict) -> bool:
        da, db = (a.get("width"), a.get("height")), (b.get("width"), b.get("height"))
        return not (all(da) and all(db)) or da == db

    groups: list[list[dict]] = []
    for m in members:
        for g in groups:
            if all(dims_agree(x, m) and same(x, m) for x in g):
                g.append(m)
                break
        else:
            groups.append([m])
    return [[m["media_id"] for m in g] for g in groups if len(g) > 1]


async def reuse_groups(account_id: str, want: frozenset[int] | set[int]) -> list[list[int]]:
    """The account's sets of PHOTOS that may share one vision answer, each as
    media ids oldest first: thumb clusters (`find_duplicates`, default
    threshold) that touch `want` (the sweep's set), re-checked on the full
    frame. Any failure — no Pillow, a broken store, a DB hiccup — logs and
    returns [] (= every item is unique): a sweep must never fail because
    duplicate detection did."""
    try:
        from vault_stills import image_path
        res = await find_duplicates(account_id)
        clusters = [[c["original"], *c["dupes"]] for c in res["clusters"]
                    if c["original"]["kind"] == "photo"]
        clusters = [cl for cl in clusters if any(int(m["media_id"]) in want for m in cl)]
        if not clusters:
            return []
        async with get_session() as s:
            dims = {int(mid): (w, h) for mid, w, h in (await s.execute(
                select(VaultItem.media_id, VaultItem.width, VaultItem.height)
                .where(VaultItem.account_id == account_id))).all()}

        def _same(a: dict, b: dict) -> bool:
            return frames_match(a["frame"], b["frame"])

        def _work() -> list[list[int]]:
            out: list[list[int]] = []
            for cl in clusters:  # each member's frame loaded once per cluster
                members = [{"media_id": int(m["media_id"]),
                            "width": dims.get(int(m["media_id"]), (None, None))[0],
                            "height": dims.get(int(m["media_id"]), (None, None))[1],
                            "frame": load_frame(image_path(account_id, int(m["media_id"])))}
                           for m in cl]
                out += frame_groups(members, _same)
            return out

        return await asyncio.to_thread(_work)
    except Exception:  # noqa: BLE001
        log.exception("reuse_groups failed account=%s — sweeping without reuse", account_id)
        return []
