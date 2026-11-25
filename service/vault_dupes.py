# aHash must agree too: dHash alone matches on layout, so two frames of one burst can collide.
# Threshold 2 is not a compromise: measured on one vault the match curve is flat past 2 (<=0: 644, <=2: 706, <=8: 737), so loosening drags in "same shoot, different frame" near-misses.
# Videos also need a duration match (±1 s) first: two clips can share a poster frame and be different edits.
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from bisect import bisect_right
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

import vault_mirror
from db.engine import get_session
from db.models import VaultItem

log = logging.getLogger("of-relay.vault_dupes")

BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "identical"),
    (1, 2, "near"),
    (3, 5, "similar"),
    (6, 8, "loose"),
)

DEFAULT_THRESHOLD = 2
MAX_THRESHOLD = 8
HASH_KIND = "thumb/md5+dhash8+ahash8"
_VIDEO_DUR_TOLERANCE_S = 1


def band_of(distance: int) -> str:
    for lo, hi, name in BANDS:
        if lo <= distance <= hi:
            return name
    return "far"




# Pillow is imported lazily inside functions: it is kept out of the relay image, and a module-level import crash-looped the whole relay on deploy. Absent Pillow only silences dupe detection.
def dhash(img: "Image.Image") -> int:
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
    try:
        from PIL import Image
        raw = path.read_bytes()
        with Image.open(path) as im:
            im.load()
            return hashlib.md5(raw).hexdigest(), dhash(im), ahash(im)
    except Exception:  # noqa: BLE001
        return None



async def ensure_hashes(account_id: str, *, force: bool = False,
                        allowed: frozenset[int] | None = None) -> dict[str, int]:
    from vault_stills import thumb_path

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



def _pair(a: dict, b: dict, threshold: int) -> tuple[int, int, bool] | None:
    if a["kind"] != b["kind"]:
        return None
    if a["kind"] == "video" and abs((a.get("duration") or 0) - (b.get("duration") or 0)) > \
            _VIDEO_DUR_TOLERANCE_S:
        return None
    if a["md5"] == b["md5"]:
        return 0, 0, True
    dd = hamming(a["dhash"], b["dhash"])
    if dd > threshold:
        return None
    da = hamming(a["ahash"], b["ahash"])
    if da > threshold:
        return None
    return dd, da, False


def near(a: dict | None, b: dict | None, threshold: int) -> bool:
    return bool(a and b) and _pair(a, b, threshold) is not None


# Seed-based, never transitive: union-find chaining would let a cluster drift away from its original.
def cluster(items: list[dict], threshold: int) -> list[dict]:
    items = sorted(items, key=lambda r: (r["created_at"], r["media_id"]))
    n_bands = max(1, threshold + 1)
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
            pair = _pair(seed, cand, threshold)
            if pair is None:
                continue
            dd, da, exact = pair
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


# Hashes come from cached thumbs, cached only when something renders or describes them, so a scan saw only what the operator had scrolled past; Duplicates now backfills every missing thumb in the background.
_BACKFILL_CONCURRENCY = 2
_backfill: dict[str, dict[str, int]] = {}
_backfill_running: set[str] = set()
_backfill_finished: dict[tuple[str, frozenset[int] | None], float] = {}
# After a pass, what is still missing is media OF would not give us: don't re-ask on every poll. Per scope: a folder-restricted chatter's pass covered only its folders.
_BACKFILL_COOLDOWN_S = 600.0


async def missing_thumb_ids(account_id: str, allowed: frozenset[int] | None = None) -> list[int]:
    from vault_stills import thumb_path
    async with get_session() as s:
        rows = (await s.execute(
            select(VaultItem.media_id, VaultItem.kind, VaultItem.content_hash_kind)
            .where(VaultItem.account_id == account_id,
                   VaultItem.removed_at.is_(None),
                   vault_mirror.visible_to(allowed))
            .order_by(VaultItem.created_at.desc())
        )).all()
    return [int(mid) for mid, kind, hk in rows
            if hk != HASH_KIND and vault_mirror.has_still(kind)
            and not thumb_path(account_id, int(mid)).is_file()]


async def _run_backfill(account_id: str, ids: list[int], allowed: frozenset[int] | None) -> None:
    import vault_frames
    import vault_stills
    queue: asyncio.Queue[int] = asyncio.Queue()
    for mid in ids:
        queue.put_nowait(mid)
    st = _backfill[account_id]

    async def _worker() -> None:
        while not queue.empty():
            mid = queue.get_nowait()
            try:
                still = await vault_stills.bytes_for(
                    account_id, mid, vault_stills.thumb_path(account_id, mid),
                    vault_frames.pick_thumb)
                ok = still.data is not None
            except Exception:  # noqa: BLE001 — one bad media must not stop the rest
                log.warning("thumb backfill failed account=%s media=%s", account_id, mid, exc_info=True)
                ok = False
            st["done"] += 1
            st["failed"] += 0 if ok else 1

    try:
        await asyncio.gather(*(_worker() for _ in range(min(_BACKFILL_CONCURRENCY, len(ids)))))
        log.info("thumb backfill done account=%s %s", account_id, st)
    finally:
        _backfill_finished[(account_id, allowed)] = time.monotonic()
        _backfill_running.discard(account_id)


def start_thumb_backfill(account_id: str, ids: list[int], allowed: frozenset[int] | None = None) -> bool:
    if account_id in _backfill_running or not ids:
        return False
    last = _backfill_finished.get((account_id, allowed))
    if last is not None and time.monotonic() - last < _BACKFILL_COOLDOWN_S:
        return False
    _backfill_running.add(account_id)
    _backfill[account_id] = {"total": len(ids), "done": 0, "failed": 0}
    asyncio.create_task(_run_backfill(account_id, ids, allowed))
    return True


def backfill_running(account_id: str) -> bool:
    return account_id in _backfill_running


def backfill_status(account_id: str) -> dict[str, Any] | None:
    st = _backfill.get(account_id)
    return None if st is None else {**st, "running": account_id in _backfill_running}




# One describe + flags answer is shared across every set shown at "2 · recommended" (find_duplicates at DEFAULT_THRESHOLD): never looser, no extra full-frame check (owner decision). Accepted risk: a set can hold different frames of one shoot burst.
async def reuse_groups(account_id: str, want: frozenset[int] | set[int]) -> list[list[int]]:
    # A sweep must never fail because duplicate detection did: any failure logs and returns [] (every item unique).
    try:
        res = await find_duplicates(account_id)
        groups = [[int(m["media_id"]) for m in (c["original"], *c["dupes"])]
                  for c in res["clusters"]]
        return [g for g in groups if any(m in want for m in g)]
    except Exception:  # noqa: BLE001
        log.exception("reuse_groups failed account=%s — sweeping without reuse", account_id)
        return []
