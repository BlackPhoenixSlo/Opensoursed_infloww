#!/usr/bin/env python3
"""
Vault duplicate detection (`vault_dupes`) + the operator-confirmed removal
endpoint (`vault_ai_api.hide_duplicates`). Durable regression suite
(plain-assert, no pytest — repo convention).

Removal calls OF's own "Remove selected items from vault"
(`PUT /vault/media/hidden`), which HIDES rather than destroys — but OF has no
unhide, so the guards are the safety net and they are what this suite pins.

Cases:
  case_hash_roundtrip:
      pack/unpack of `content_hash`; a re-encoded copy of the same image keeps a
      near-zero hash distance while a genuinely different image does not.
  case_original_is_earliest:
      the ORIGINAL of a set is the earliest-uploaded item, whatever order the
      rows come out of the DB in, and it is never listed among its own dupes.
  case_no_transitive_chaining:
      a chain A~B~C where A and C are FAR apart must not land C in A's set —
      the seed-based grouping is what stops a cluster drifting off its original.
  case_video_duration_gate:
      two clips that share a poster frame but differ in length are NOT grouped.
  case_hide_refuses_original:
      asking to hide an id that is the original of its set is refused, and the
      OF call never receives it — the keeper cannot be removed by a stale UI.
  case_hide_refuses_non_duplicate:
      an id that isn't in any duplicate set is refused.
  case_hide_skips_sent_unless_allowed:
      a copy with send_count > 0 is skipped by default and only goes through
      with allow_sent.
  case_hide_marks_mirror_removed:
      a successful hide sends exactly the approved ids to OF and soft-deletes
      those mirror rows so the grid/picker/automations stop seeing them.

Run: cd service/tests && \
  PYTHONPATH=$(cd .. && pwd) ../../venv/bin/python test_vault_dupes.py
Exit 0 = all cases passed. Temp DB bound by _harness (never prod). No OF and no
network: the OF client is faked at the `automation_executor._make_client` seam.
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import io  # noqa: E402
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
    """One mirrored item carrying a pre-computed hash. `days_old` drives upload
    order (larger = older = the original)."""
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
    """Records what `hide_vault_media` was asked to remove, one entry per call
    so chunking is observable. `fail_from` makes the Nth call onwards raise, to
    exercise the partial-success path."""
    def __init__(self, fail_from: int | None = None) -> None:
        self.hidden: list[list[int]] = []
        self.fail_from = fail_from

    def hide_vault_media(self, media_ids: list[int]) -> dict:
        if self.fail_from is not None and len(self.hidden) >= self.fail_from:
            raise RuntimeError("OF said no")
        self.hidden.append(list(media_ids))
        return {"success": True}


async def _hide(payload: dict, fake: _FakeOF | None = None) -> tuple[dict, _FakeOF]:
    """Call the endpoint with the OF client faked at the _make_client seam."""
    fake = fake or _FakeOF()
    orig = ax._make_client
    ax._make_client = lambda *_a, **_k: fake
    try:
        out = await vault_ai_api.hide_duplicates(payload)
    finally:
        ax._make_client = orig
    return out, fake


# ── Cases ────────────────────────────────────────────────────────────

async def case_hash_roundtrip() -> None:
    assert vault_dupes.unpack_hash(vault_dupes.pack_hash("ab" * 16, 5, 9)) == \
        ("ab" * 16, 5, 9)
    assert vault_dupes.unpack_hash(None) is None
    assert vault_dupes.unpack_hash("garbage") is None

    # A real re-encode of the same pixels must stay close; a different image
    # must not. This is the property the whole detector rests on.
    src = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            src.putpixel((x, y), (x * 4 % 256, y * 4 % 256, (x + y) % 256))
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=55)          # lossy re-encode, as OF does
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
    # Insert NEWEST first so "original" can't accidentally be insertion order.
    await _seed_item(aid, 300, packed=same, days_old=1)
    await _seed_item(aid, 100, packed=same, days_old=30)     # ← the original
    await _seed_item(aid, 200, packed=same, days_old=10)

    res = await vault_dupes.find_duplicates(aid, 2, rehash=False)
    assert res["sets"] == 1, res
    c = res["clusters"][0]
    assert c["original"]["media_id"] == 100, c["original"]
    ids = sorted(d["media_id"] for d in c["dupes"])
    assert ids == [200, 300], ids
    assert 100 not in ids


async def case_no_transitive_chaining() -> None:
    """A~B (dist 2) and B~C (dist 2) but A~C (dist 4): with threshold 2 the set
    seeded at A must contain B only. Chaining would swallow C and drift the
    cluster away from the original it is supposed to represent."""
    aid = _next_account()
    await _seed_account(aid)
    a = 0b0000
    b = 0b0011          # 2 bits from a
    c = 0b1111          # 2 bits from b, 4 from a
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
    assert ids == [11], ids          # the 95s clip is a different edit


async def case_hide_refuses_original() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("b" * 32, 0b1, 0b1)
    await _seed_item(aid, 1, packed=same, days_old=30)        # original
    await _seed_item(aid, 2, packed=same, days_old=10)

    out, fake = await _hide({"account_id": aid, "media_ids": [1, 2]})
    assert out["hidden"] == 1, out
    assert out["hidden_ids"] == [2], out
    assert out["refused"]["is_original"] == [1], out
    assert fake.hidden == [[2]], fake.hidden   # OF never saw the keeper


async def case_hide_refuses_non_duplicate() -> None:
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("c" * 32, 0b10, 0b10)
    await _seed_item(aid, 1, packed=same, days_old=30)
    await _seed_item(aid, 2, packed=same, days_old=10)
    # A lone item, in no set at all.
    await _seed_item(aid, 9, packed=_packed("d" * 32, 0xFFFF, 0xFFFF), days_old=5)

    out, fake = await _hide({"account_id": aid, "media_ids": [9]})
    assert out["hidden"] == 0, out
    assert out["refused"]["not_a_duplicate"] == [9], out
    assert fake.hidden == [], fake.hidden      # no OF call at all


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
    assert rows[1] is None, rows          # original untouched
    assert rows[2] is not None and rows[3] is not None, rows

    # And they're gone from the next scan — no set left to act on.
    res = await vault_dupes.find_duplicates(aid, 2, rehash=False)
    assert res["sets"] == 0, res


async def case_hide_request_cap() -> None:
    """One request can't sweep the vault: over the cap is a 400 telling the
    client how far over it is, which is what drives client-side batching.
    (Live 2026-07-21: a 644-copy Ava selection hit exactly this.)"""
    aid = _next_account()
    await _seed_account(aid)
    over = list(range(1, vault_ai_api._MAX_HIDE_PER_CALL + 5))
    try:
        await _hide({"account_id": aid, "media_ids": over})
    except Exception as e:  # HTTPException
        detail = getattr(e, "detail", {})
        assert detail.get("error") == "too_many", detail
        assert detail.get("max") == vault_ai_api._MAX_HIDE_PER_CALL, detail
        assert detail.get("got") == len(over), detail
    else:
        raise AssertionError("over-cap request was not refused")


async def case_hide_chunks_of_calls() -> None:
    """A big approved batch reaches OF as bounded chunks, never one giant body,
    and every id still lands."""
    aid = _next_account()
    await _seed_account(aid)
    same = _packed("7" * 32, 0b11, 0b11)
    n = vault_ai_api._OF_HIDE_CHUNK * 2 + 5
    await _seed_item(aid, 1, packed=same, days_old=999)          # original
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
    """If OF takes chunk 1 then rejects chunk 2, the media OF actually hid must
    still be marked gone locally and reported — dropping it would leave the
    mirror advertising media that no longer exists in her vault."""
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


_harness.run(
    case_hash_roundtrip,
    case_original_is_earliest,
    case_no_transitive_chaining,
    case_video_duration_gate,
    case_hide_refuses_original,
    case_hide_refuses_non_duplicate,
    case_hide_skips_sent_unless_allowed,
    case_hide_marks_mirror_removed,
    case_hide_request_cap,
    case_hide_chunks_of_calls,
    case_hide_partial_failure_is_recorded,
)
