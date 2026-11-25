#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import io  # noqa: E402
import random  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

from PIL import Image  # noqa: E402
from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import vault_ai_api  # noqa: E402
import vault_dupes  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

_AID_N = 0


def _next_account() -> str:
    global _AID_N
    _AID_N += 1
    return f"dupe{_AID_N}"


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        await s.commit()


async def _seed_item(aid: str, media_id: int, *, packed: str, kind: str = "photo",
                     days_old: int = 0, duration: int | None = None,
                     send_count: int = 0) -> None:
    async with get_session() as s:
        s.add(VaultItem(
            account_id=aid, media_id=media_id, kind=kind,
            created_at=datetime.utcnow() - timedelta(days=days_old),
            duration_seconds=duration, tags="[]", send_count=send_count,
            content_hash=packed, content_hash_kind=vault_dupes.HASH_KIND,
        ))
        await s.commit()


def _packed(md5: str, dh: int, ah: int) -> str:
    return vault_dupes.pack_hash(md5, dh, ah)


class _FakeOF:
    def __init__(self, fail_from: int | None = None) -> None:
        self.hidden: list[list[int]] = []
        self.fail_from = fail_from

    def hide_vault_media(self, media_ids: list[int]) -> dict:
        if self.fail_from is not None and len(self.hidden) >= self.fail_from:
            raise RuntimeError("OF said no")
        self.hidden.append(list(media_ids))
        return {"success": True}


async def _hide(payload: dict, fake: _FakeOF | None = None) -> tuple[dict, _FakeOF]:
    fake = fake or _FakeOF()
    orig = ax._make_client
    ax._make_client = lambda *_a, **_k: fake
    try:
        out = await vault_ai_api.hide_duplicates(payload)
    finally:
        ax._make_client = orig
    return out, fake



async def case_hash_roundtrip() -> None:
    assert vault_dupes.unpack_hash(vault_dupes.pack_hash("ab" * 16, 5, 9)) == \
        ("ab" * 16, 5, 9)
    assert vault_dupes.unpack_hash(None) is None
    assert vault_dupes.unpack_hash("garbage") is None

    src = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            src.putpixel((x, y), (x * 4 % 256, y * 4 % 256, (x + y) % 256))
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=55)
    reencoded = Image.open(io.BytesIO(buf.getvalue()))
    d_src, d_re = vault_dupes.dhash(src), vault_dupes.dhash(reencoded)
    assert vault_dupes.hamming(d_src, d_re) <= 2, vault_dupes.hamming(d_src, d_re)

    other = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            other.putpixel((x, y), ((x * y) % 256, 255 - x * 3 % 256, y % 256))
    assert vault_dupes.hamming(d_src, vault_dupes.dhash(other)) > 8


async def case_original_is_earliest() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("f" * 32, 0b1010, 0b0101)
    await _seed_item(aid, 300, packed=same, days_old=1)
    await _seed_item(aid, 100, packed=same, days_old=30)
    await _seed_item(aid, 200, packed=same, days_old=10)

    res = await vault_dupes.find_duplicates(aid, 2, rehash=False)
    assert res["sets"] == 1, res
    c = res["clusters"][0]
    assert c["original"]["media_id"] == 100, c["original"]
    ids = sorted(d["media_id"] for d in c["dupes"])
    assert ids == [200, 300], ids
    assert 100 not in ids


async def case_no_transitive_chaining() -> None:
    aid = _next_account()
    await _seed_account(aid)
    a = 0b0000
    b = 0b0011
    c = 0b1111
    await _seed_item(aid, 1, packed=_packed("1" * 32, a, a), days_old=30)
    await _seed_item(aid, 2, packed=_packed("2" * 32, b, b), days_old=20)
    await _seed_item(aid, 3, packed=_packed("3" * 32, c, c), days_old=10)

    res = await vault_dupes.find_duplicates(aid, 2, rehash=False)
    seeded_at_1 = [x for x in res["clusters"] if x["original"]["media_id"] == 1]
    assert len(seeded_at_1) == 1, res["clusters"]
    assert [d["media_id"] for d in seeded_at_1[0]["dupes"]] == [2], seeded_at_1[0]


async def case_video_duration_gate() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("a" * 32, 0b1100, 0b1100)
    await _seed_item(aid, 10, packed=same, kind="video", duration=60, days_old=30)
    await _seed_item(aid, 11, packed=same, kind="video", duration=60, days_old=20)
    await _seed_item(aid, 12, packed=same, kind="video", duration=95, days_old=10)

    res = await vault_dupes.find_duplicates(aid, 2, rehash=False)
    assert res["sets"] == 1, res
    ids = [d["media_id"] for d in res["clusters"][0]["dupes"]]
    assert ids == [11], ids


def _cluster_allpairs(items: list[dict], threshold: int) -> list[dict]:
    items = sorted(items, key=lambda r: (r["created_at"], r["media_id"]))
    claimed: set[int] = set()
    clusters: list[dict] = []
    for i, seed in enumerate(items):
        if seed["media_id"] in claimed:
            continue
        dupes: list[dict] = []
        for cand in items[i + 1:]:
            if cand["media_id"] in claimed or cand["kind"] != seed["kind"]:
                continue
            if seed["kind"] == "video":
                if abs((seed["duration"] or 0) - (cand["duration"] or 0)) > \
                        vault_dupes._VIDEO_DUR_TOLERANCE_S:
                    continue
            if cand["md5"] == seed["md5"]:
                dd = da = 0
                exact = True
            else:
                dd = vault_dupes.hamming(seed["dhash"], cand["dhash"])
                if dd > threshold:
                    continue
                da = vault_dupes.hamming(seed["ahash"], cand["ahash"])
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
            "band": vault_dupes.band_of(worst),
            "all_exact": all(d["exact"] for d in dupes),
        })
    clusters.sort(key=lambda c: (-len(c["dupes"]), c["worst"]))
    return clusters


def _flip(h: int, rng: random.Random, k: int) -> int:
    for b in rng.sample(range(64), k):
        h ^= 1 << b
    return h


def _world(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    t0 = datetime(2026, 1, 1)
    out: list[dict] = []

    def add(kind, md5, dh, ah, dur=None):
        mid = len(out) + 1
        out.append({"media_id": mid, "kind": kind, "md5": md5, "dhash": dh,
                    "ahash": ah, "duration": dur, "send_count": 0,
                    "created_at": t0 + timedelta(hours=rng.randrange(n // 3 + 1))})

    while len(out) < n:
        kind = rng.choice(("photo", "photo", "video", "gif"))
        dur = rng.randrange(5, 60) if kind == "video" else None
        md5, dh, ah = f"{rng.getrandbits(128):032x}", rng.getrandbits(64), rng.getrandbits(64)
        add(kind, md5, dh, ah, dur)
        roll = rng.random()
        if roll < 0.3:
            for _ in range(rng.randrange(1, 4)):
                add(kind, f"{rng.getrandbits(128):032x}", _flip(dh, rng, rng.randrange(10)),
                    _flip(ah, rng, rng.randrange(10)),
                    None if dur is None else dur + rng.choice((-2, -1, 0, 1, 2)))
        elif roll < 0.4:
            add(kind, md5, rng.getrandbits(64), rng.getrandbits(64), dur)
        elif roll < 0.5:
            b_dh = _flip(dh, rng, 3)
            add(kind, f"{rng.getrandbits(128):032x}", b_dh, ah, dur)
            add(kind, f"{rng.getrandbits(128):032x}", _flip(b_dh, rng, 3), ah, dur)
        elif roll < 0.6:
            other = rng.choice([k for k in ("photo", "video", "gif") if k != kind])
            add(other, md5, dh, ah, rng.randrange(5, 60) if other == "video" else None)
        elif roll < 0.7:
            other = rng.choice([k for k in ("photo", "video", "gif") if k != kind])
            add(other, f"{rng.getrandbits(128):032x}", _flip(dh, rng, rng.randrange(3)),
                _flip(ah, rng, rng.randrange(3)), rng.randrange(5, 60) if other == "video" else None)
    return out[:n]


def case_cluster_matches_allpairs() -> None:
    worlds = [(n, s) for n in (0, 1, 50) for s in range(5)] + [(2000, 0)]
    for n, s in worlds:
        items = _world(n, s)
        for t in (-1, 0, 2, 4, 6, 8):
            got, want = vault_dupes.cluster(items, t), _cluster_allpairs(items, t)
            assert got == want, (n, s, t, len(got), len(want))
            if (n, t) == (2000, 6):
                planted = want
    assert len(planted) > 100 and any(not c["all_exact"] for c in planted), len(planted)


# OF hides via PUT /vault/media/hidden and has no unhide, so these guards are the safety net.
async def case_hide_refuses_original() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("b" * 32, 0b1, 0b1)
    await _seed_item(aid, 1, packed=same, days_old=30)
    await _seed_item(aid, 2, packed=same, days_old=10)

    out, fake = await _hide({"account_id": aid, "media_ids": [1, 2]})
    assert out["hidden"] == 1, out
    assert out["hidden_ids"] == [2], out
    assert out["refused"]["is_original"] == [1], out
    assert fake.hidden == [[2]], fake.hidden


async def case_hide_refuses_non_duplicate() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("c" * 32, 0b10, 0b10)
    await _seed_item(aid, 1, packed=same, days_old=30)
    await _seed_item(aid, 2, packed=same, days_old=10)
    await _seed_item(aid, 9, packed=_packed("d" * 32, 0xFFFF, 0xFFFF), days_old=5)

    out, fake = await _hide({"account_id": aid, "media_ids": [9]})
    assert out["hidden"] == 0, out
    assert out["refused"]["not_a_duplicate"] == [9], out
    assert fake.hidden == [], fake.hidden


async def case_hide_skips_sent_unless_allowed() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("e" * 32, 0b100, 0b100)
    await _seed_item(aid, 1, packed=same, days_old=30)
    await _seed_item(aid, 2, packed=same, days_old=10, send_count=4)

    out, fake = await _hide({"account_id": aid, "media_ids": [2]})
    assert out["hidden"] == 0, out
    assert out["refused"]["has_sends"] == [2], out
    assert fake.hidden == [], fake.hidden

    out2, fake2 = await _hide({"account_id": aid, "media_ids": [2],
                               "allow_sent": True})
    assert out2["hidden"] == 1 and fake2.hidden == [[2]], (out2, fake2.hidden)


async def case_hide_marks_mirror_removed() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("9" * 32, 0b1000, 0b1000)
    await _seed_item(aid, 1, packed=same, days_old=30)
    await _seed_item(aid, 2, packed=same, days_old=20)
    await _seed_item(aid, 3, packed=same, days_old=10)

    out, fake = await _hide({"account_id": aid, "media_ids": [2, 3]})
    assert out["hidden"] == 2, out
    assert fake.hidden == [[2, 3]], fake.hidden

    async with get_session() as s:
        rows = dict((await s.execute(
            select(VaultItem.media_id, VaultItem.removed_at)
            .where(VaultItem.account_id == aid)
        )).all())
    assert rows[1] is None, rows
    assert rows[2] is not None and rows[3] is not None, rows

    res = await vault_dupes.find_duplicates(aid, 2, rehash=False)
    assert res["sets"] == 0, res


async def case_hide_request_cap() -> None:
    aid = _next_account()
    await _seed_account(aid)
    over = list(range(1, vault_ai_api._MAX_HIDE_PER_CALL + 5))
    try:
        await _hide({"account_id": aid, "media_ids": over})
    except Exception as e:
        detail = getattr(e, "detail", {})
        assert detail.get("error") == "too_many", detail
        assert detail.get("max") == vault_ai_api._MAX_HIDE_PER_CALL, detail
        assert detail.get("got") == len(over), detail
    else:
        raise AssertionError("over-cap request was not refused")


async def case_hide_chunks_of_calls() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("7" * 32, 0b11, 0b11)
    n = vault_ai_api._OF_HIDE_CHUNK * 2 + 5
    await _seed_item(aid, 1, packed=same, days_old=999)
    for mid in range(2, n + 2):
        await _seed_item(aid, mid, packed=same, days_old=10)

    ids = list(range(2, n + 2))
    out, fake = await _hide({"account_id": aid, "media_ids": ids})
    assert out["hidden"] == len(ids), out["hidden"]
    assert len(fake.hidden) == 3, [len(c) for c in fake.hidden]
    assert all(len(c) <= vault_ai_api._OF_HIDE_CHUNK for c in fake.hidden), \
        [len(c) for c in fake.hidden]
    assert [m for c in fake.hidden for m in c] == ids


async def case_hide_partial_failure_is_recorded() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("6" * 32, 0b101, 0b101)
    n = vault_ai_api._OF_HIDE_CHUNK + 10
    await _seed_item(aid, 1, packed=same, days_old=999)
    for mid in range(2, n + 2):
        await _seed_item(aid, mid, packed=same, days_old=10)

    ids = list(range(2, n + 2))
    out, fake = await _hide({"account_id": aid, "media_ids": ids},
                            _FakeOF(fail_from=1))
    assert out["hidden"] == vault_ai_api._OF_HIDE_CHUNK, out["hidden"]
    assert out["of_error"], out
    assert len(out["not_hidden"]) == len(ids) - vault_ai_api._OF_HIDE_CHUNK, out

    async with get_session() as s:
        rows = dict((await s.execute(
            select(VaultItem.media_id, VaultItem.removed_at)
            .where(VaultItem.account_id == aid)
        )).all())
    assert rows[1] is None, "original must survive"
    for mid in out["hidden_ids"]:
        assert rows[mid] is not None, mid
    for mid in out["not_hidden"]:
        assert rows[mid] is None, mid


async def case_backfill_scans_unrendered_items() -> None:
    import asyncio
    import tempfile
    from pathlib import Path

    import vault_of_folders
    import vault_stills

    aid = _next_account()
    await _seed_account(aid)
    async with get_session() as s:
        for mid, kind, days in ((1, "photo", 30), (2, "photo", 5), (3, "photo", 1), (4, "audio", 1)):
            s.add(VaultItem(account_id=aid, media_id=mid, kind=kind, tags="[]",
                            created_at=datetime.utcnow() - timedelta(days=days)))
        await s.commit()
    await _seed_item(aid, 9, packed=_packed("9" * 32, 0xFFFF, 0xFFFF), days_old=2)

    img = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            img.putpixel((x, y), (x * 4 % 256, y * 4 % 256, (x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    asked: list[int] = []

    async def fake_bytes_for(account_id, media_id, path, pick):
        asked.append(media_id)
        if media_id == 3:
            return vault_stills.Still(None, "fetch_failed")
        vault_stills.write(path, buf.getvalue())
        return vault_stills.Still(buf.getvalue(), "ok")

    orig_dir, orig_bf = vault_stills.THUMB_DIR, vault_stills.bytes_for
    vault_stills.THUMB_DIR = Path(tempfile.mkdtemp())
    vault_stills.bytes_for = fake_bytes_for
    try:
        first = await vault_of_folders.list_duplicates(account_id=aid, threshold=2, limit=200)
        assert first["scanned"] == 1 and first["missing_thumbs"] == 3, first
        assert first["backfill"]["running"] and first["backfill"]["total"] == 3, first
        for _ in range(100):
            if not vault_dupes.backfill_status(aid)["running"]:
                break
            await asyncio.sleep(0.01)
        assert sorted(asked) == [1, 2, 3], asked

        second = await vault_of_folders.list_duplicates(account_id=aid, threshold=2, limit=200)
        assert second["scanned"] == 3, second
        assert second["missing_thumbs"] == 1, second
        assert second["backfill"] == {"total": 3, "done": 3, "failed": 1, "running": False}, second
        assert second["sets"] == 1 and second["clusters"][0]["original"]["media_id"] == 1, second
        assert sorted(asked) == [1, 2, 3], "cooldown: a finished pass is not relaunched"
    finally:
        vault_stills.THUMB_DIR, vault_stills.bytes_for = orig_dir, orig_bf


async def case_backfill_scope_and_mid_scan_finish() -> None:
    import asyncio
    import tempfile
    from pathlib import Path

    import vault_of_folders
    import vault_stills

    aid = _next_account()
    await _seed_account(aid)
    gate = asyncio.Event()
    asked: list[int] = []

    async def fake_bytes_for(account_id, media_id, path, pick):
        asked.append(media_id)
        await gate.wait()
        return vault_stills.Still(None, "fetch_failed")

    async def until_idle() -> None:
        for _ in range(200):
            if not vault_dupes.backfill_running(aid):
                return
            await asyncio.sleep(0.01)
        raise AssertionError("backfill never finished")

    orig = (vault_stills.THUMB_DIR, vault_stills.bytes_for, vault_dupes.find_duplicates,
            vault_dupes.missing_thumb_ids)
    vault_stills.THUMB_DIR = Path(tempfile.mkdtemp())
    vault_stills.bytes_for = fake_bytes_for
    try:
        gate.set()
        assert vault_dupes.start_thumb_backfill(aid, [1], frozenset({12}))
        await until_idle()
        assert vault_dupes.start_thumb_backfill(aid, [1, 2]), "restricted pass blocked the whole vault"
        await until_idle()
        assert not vault_dupes.start_thumb_backfill(aid, [1, 2]), "same scope: cooldown"

        gate.clear()
        assert vault_dupes.start_thumb_backfill(aid, [3], frozenset({13}))
        walked: list[str] = []
        real_find, real_missing = orig[2], orig[3]

        async def find_while_pass_ends(account_id, threshold, allowed=None):
            gate.set()
            await until_idle()
            return await real_find(account_id, threshold, allowed=allowed)

        async def missing(account_id, allowed=None):
            walked.append(account_id)
            return await real_missing(account_id, allowed)

        vault_dupes.find_duplicates, vault_dupes.missing_thumb_ids = find_while_pass_ends, missing
        r = await vault_of_folders.list_duplicates(account_id=aid, threshold=2, limit=200)
        assert r["backfill"]["running"], ("pass ended mid-scan, reply said done", r["backfill"])
        assert walked == [], "mirror re-walked while a pass ran"
    finally:
        (vault_stills.THUMB_DIR, vault_stills.bytes_for, vault_dupes.find_duplicates,
         vault_dupes.missing_thumb_ids) = orig


_harness.run(
    case_hash_roundtrip,
    case_original_is_earliest,
    case_no_transitive_chaining,
    case_video_duration_gate,
    case_cluster_matches_allpairs,
    case_backfill_scans_unrendered_items,
    case_backfill_scope_and_mid_scan_finish,
    case_hide_refuses_original,
    case_hide_refuses_non_duplicate,
    case_hide_skips_sent_unless_allowed,
    case_hide_marks_mirror_removed,
    case_hide_request_cap,
    case_hide_chunks_of_calls,
    case_hide_partial_failure_is_recorded,
)
