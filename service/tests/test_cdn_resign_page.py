#!/usr/bin/env python3
from __future__ import annotations

import _harness
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

    def __init__(self, gone: set[int] = frozenset()):
        self.gone = set(gone)
        self.sig = "new"
        self.reads: list = []
        self.lock = threading.Lock()

    def vault_media(self, *, limit: int, offset: int, type: str, sort: str, **_kw):
        assert (limit, type, sort) == (100, "all", "asc"), (limit, type, sort)
        with self.lock:
            self.reads.append(f"p{offset}")
        live = [_media(i, self.sig) for i in range(N) if i not in self.gone]
        return {"list": live[offset:offset + limit], "hasMore": offset + limit < len(live)}

    def vault_media_by_id(self, media_id: int):
        with self.lock:
            self.reads.append(int(media_id))
        return _media(int(media_id) - 9_000_000, self.sig)


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
    return asyncio.run(cdn_resign.resign(AID, _mid(i), _url(_mid(i), "old"), of, "t"))


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
    assert _resign(of, 102) == _url(_mid(102), "new")
    assert of.reads == ["p0"], of.reads


def case_drift_reads_the_neighbour():
    _reset()
    of = _OF(gone=set(range(10)))
    assert _resign(of, 205) == _url(_mid(205), "new")
    assert of.reads == ["p200", "p100"], of.reads


def case_absent_falls_back_by_id():
    _reset()
    of = _OF(gone={50})
    assert _resign(of, 50) == _url(_mid(50), "new")
    assert of.reads == ["p0", _mid(50)], of.reads


def case_no_mirror_row_by_id():
    _reset()
    of = _OF()
    got = asyncio.run(cdn_resign.resign(AID, _mid(400), _url(_mid(400), "old"), of, "t"))
    assert got == _url(_mid(400), "new") and of.reads == [_mid(400)], of.reads


def case_herd_one_window_read():
    _reset()
    of = _OF()

    async def herd():
        return await asyncio.gather(*(cdn_resign.resign(AID, _mid(i), _url(_mid(i), "old"), of, "t")
                                      for i in range(200, 230)))
    assert asyncio.run(herd()) == [_url(_mid(i), "new") for i in range(200, 230)]
    assert of.reads == ["p200"], of.reads


def case_stale_window_rereads():
    _reset()
    of = _OF()
    of.sig = "ip1"
    assert _resign(of, 130) == _url(_mid(130), "ip1") and of.reads == ["p100"], of.reads
    of.sig = "ip2"
    # A cached window must not answer "hit" with a dead url, or every file in it falls to a by-id read.
    stale = cdn_resign.current(AID, _url(_mid(130), "old"))
    assert stale == _url(_mid(130), "ip1")
    got = asyncio.run(cdn_resign.resign(AID, _mid(130), stale, of, "t"))
    assert got == _url(_mid(130), "ip2"), got
    assert of.reads == ["p100", "p100"], ("one window re-read, no by-id", of.reads)
    assert cdn_resign.current(AID, _url(_mid(150), "ip1")) == _url(_mid(150), "ip2")
    assert _resign(of, 150) == _url(_mid(150), "ip2") and of.reads == ["p100", "p100"], of.reads

    _reset()
    of = _OF()
    assert _resign(of, 130) == _url(_mid(130), "new") and of.reads == ["p100"], of.reads
    for i in (130, 150):
        assert asyncio.run(cdn_resign.resign(AID, _mid(i), _url(_mid(i), "new"), of, "t")) is None
    assert of.reads == ["p100", "p100", _mid(130), _mid(150)], of.reads


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
