#!/usr/bin/env python3
"""`cdn_resign` re-signs by LISTING WINDOW: one OF `vault/media?sort=asc&limit=100` read re-signs the 100 media around
the one asked for, at the offset the mirror counts for it. Plain-assert, no pytest (repo convention).

Why: a download of N expired files was N by-id reads (AE 2026-11-10: 118 files, 118 reads, 429 at file 92). The
same selection spans 6 listing windows.

  case_window_resigns_its_neighbours — the media at mirror offset 130: one read at offset 100; every other media
                                       of that window then re-signs with no OF call, and its mirror row carries
                                       the fresh url; offset 5 reads window 0.
  case_removed_rows_not_counted      — a mirror row stamped removed is not counted toward the offset.
  case_drift_reads_the_neighbour     — the mirror still lists 10 media OF deleted: the window misses, its range
                                       says "earlier", the neighbour holds it: 2 reads, no by-id.
  case_absent_falls_back_by_id       — inside its window's range but not listed: one by-id read.
  case_no_mirror_row_by_id           — no mirror row: by-id, no listing read.
  case_herd_one_window_read          — 30 media of one window at once: one read.
  case_eviction_keeps_newest         — past _CAP the OLDEST remembered urls go, not all of them.

OF is faked: no request leaves the process.
Run: ./venv/bin/python service/tests/test_cdn_resign_page.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import cdn_resign  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultItem  # noqa: E402

AID = "accP"
T0 = datetime(2026, 1, 1)
N = 250
HOST = "https://cdn2.onlyfans.com"


def _mid(i: int) -> int:
    return 9_000_000 + i


def _url(mid: int, sig: str) -> str:
    return f"{HOST}/files/x/{mid}/full.jpg?Policy={sig}&Signature=s&Key-Pair-Id=K"


def _media(i: int, sig: str = "new") -> dict:
    mid = _mid(i)
    return {"id": mid, "type": "photo", "createdAt": (T0 + timedelta(minutes=i)).isoformat() + "+00:00",
            "files": {"full": {"url": _url(mid, sig)}, "thumb": {"url": f"{HOST}/files/x/{mid}/t.jpg?Policy={sig}"}}}


class _OF:
    """OF's listing in (createdAt, id) asc order; `gone` = media OF deleted (the mirror may not know)."""

    def __init__(self, gone: set[int] = frozenset()):
        self.gone = set(gone)
        self.reads: list = []
        self.lock = threading.Lock()

    def vault_media(self, *, limit: int, offset: int, type: str, sort: str, **_kw):
        assert (limit, type, sort) == (100, "all", "asc"), (limit, type, sort)
        with self.lock:
            self.reads.append(f"p{offset}")
        live = [_media(i) for i in range(N) if i not in self.gone]
        return {"list": live[offset:offset + limit], "hasMore": offset + limit < len(live)}

    def vault_media_by_id(self, media_id: int):
        with self.lock:
            self.reads.append(int(media_id))
        return _media(int(media_id) - 9_000_000)


async def _seed(removed: set[int] = frozenset()) -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID, nickname="P"))
            await s.flush()
        for i in range(N):
            m = _media(i, sig="old")
            row = await s.get(VaultItem, (AID, _mid(i)))
            if row is None:
                row = VaultItem(account_id=AID, media_id=_mid(i), kind="photo", search_text="", tags="[]",
                                created_at=T0 + timedelta(minutes=i))
                s.add(row)
            row.raw_json, row.full_url = json.dumps(m), m["files"]["full"]["url"]
            row.removed_at = T0 if i in removed else None
        await s.commit()


def _reset(removed: set[int] = frozenset()) -> None:
    cdn_resign._fresh.clear()
    cdn_resign._failed.clear()
    cdn_resign._pages.clear()
    asyncio.run(_seed(removed))


def _resign(of: _OF, i: int) -> str | None:
    return asyncio.run(cdn_resign.resign(AID, _mid(i), _url(_mid(i), "old"), of))


def case_window_resigns_its_neighbours():
    _reset()
    of = _OF()
    assert _resign(of, 130) == _url(_mid(130), "new")
    assert of.reads == ["p100"], of.reads
    for i in (100, 150, 199):
        assert cdn_resign.current(AID, _url(_mid(i), "old")) == _url(_mid(i), "new"), i
        assert _resign(of, i) == _url(_mid(i), "new")
    assert of.reads == ["p100"], ("the window's other media cost no OF call", of.reads)

    async def row(i):
        async with get_session() as s:
            return (await s.get(VaultItem, (AID, _mid(i)))).full_url
    assert asyncio.run(row(177)) == _url(_mid(177), "new"), "the window is written over the mirror"
    assert asyncio.run(row(99)) == _url(_mid(99), "old")
    assert _resign(of, 5) == _url(_mid(5), "new") and of.reads == ["p100", "p0"], of.reads


def case_removed_rows_not_counted():
    _reset(removed={1, 2, 3})
    of = _OF(gone={1, 2, 3})
    assert _resign(of, 102) == _url(_mid(102), "new")   # live offset 99: window 0
    assert of.reads == ["p0"], of.reads


def case_drift_reads_the_neighbour():
    _reset()
    of = _OF(gone=set(range(10)))       # the mirror still has them live
    assert _resign(of, 205) == _url(_mid(205), "new")   # mirror offset 205, OF index 195
    assert of.reads == ["p200", "p100"], of.reads


def case_absent_falls_back_by_id():
    _reset()
    of = _OF(gone={50})
    assert _resign(of, 50) == _url(_mid(50), "new")     # by id (this fake still answers it)
    assert of.reads == ["p0", _mid(50)], of.reads


def case_no_mirror_row_by_id():
    _reset()
    of = _OF()
    got = asyncio.run(cdn_resign.resign(AID, _mid(400), _url(_mid(400), "old"), of))
    assert got == _url(_mid(400), "new") and of.reads == [_mid(400)], of.reads


def case_herd_one_window_read():
    _reset()
    of = _OF()

    async def herd():
        return await asyncio.gather(*(cdn_resign.resign(AID, _mid(i), _url(_mid(i), "old"), of)
                                      for i in range(200, 230)))
    assert asyncio.run(herd()) == [_url(_mid(i), "new") for i in range(200, 230)]
    assert of.reads == ["p200"], of.reads


def case_eviction_keeps_newest():
    cap = cdn_resign._CAP
    cdn_resign._CAP = 4
    try:
        cdn_resign._fresh.clear()
        for i in range(6):
            cdn_resign._remember(AID, {"files": {"full": {"url": _url(_mid(i), "new")}}})
        assert cdn_resign.current(AID, _url(_mid(5), "old")) == _url(_mid(5), "new")
        assert cdn_resign.current(AID, _url(_mid(0), "old")) == _url(_mid(0), "old")
        assert len(cdn_resign._fresh) == 4
    finally:
        cdn_resign._CAP = cap


_harness.run()
