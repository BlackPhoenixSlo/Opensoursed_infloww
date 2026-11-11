#!/usr/bin/env python3
"""The manual "Collect all" sweep (vault_ai_api._run_collect) makes the useful
items usable first.

Fake OF client at the client seam (`ax._make_client`), real DB, real mirror
upserts, real still stores in a temp dir (CDN fetch faked).

Covers: OF call order newest 100 (desc) → folder list → folder page 0s → asc walk
from offset 0; each page's thumbs + full stills are on disk before the next OF
call; nothing counted or downloaded twice; the run ends done + complete; the page
cap still ends capped (not complete); storyboards warm newest first.

Run: ./venv/bin/python service/tests/test_vault_manual_collect_order.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import automation_executor as ax  # noqa: E402
import vault_ai_api as api  # noqa: E402
import vault_frames  # noqa: E402
import vault_runs  # noqa: E402
import vault_stills  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, VaultCacheRun, VaultItem, VaultResponseCache  # noqa: E402

api.assert_account_owned = lambda _a: None
api._PAGE_SLEEP_S = 0.0
_tmp = Path(tempfile.mkdtemp(prefix="vmc_"))
vault_stills.THUMB_DIR, vault_stills.IMAGE_DIR, vault_stills.POSTER_DIR = (
    _tmp / "thumbs", _tmp / "images", _tmp / "posters")
_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
_fetches: list[str] = []
_warmed: list[str] = []
_FAIL_ONCE: set[str] = set()   # urls whose next fetch raises (a CDN blow-up mid-warm)


def _fake_fetch(client, url):
    _fetches.append(url)
    if url in _FAIL_ONCE:
        _FAIL_ONCE.discard(url)
        raise RuntimeError("cdn reset (fake)")
    return _JPEG


vault_stills.fetch_bytes_sync = _fake_fetch
vault_frames.warm_one_sync = lambda client, url, dur: _warmed.append(url)


class FakeOF:
    """Vault of ids 1..n, newer = higher id. Every 10th item is in folder 7 (custom,
    hasMedia); folder 8 is custom but empty. Ids in `videos` are clips."""

    def __init__(self, aid: str, n: int, videos: tuple[int, ...] = (), fail_lists: bool = False):
        self.aid, self.n, self.videos, self.fail_lists = aid, n, set(videos), fail_lists
        self.calls: list[tuple] = []
        self.on_disk_at_call: list[set[int]] = []   # media ids with thumb+image when each call began

    def _snap(self, kind: tuple) -> None:
        self.calls.append(kind)
        have = {i for i in range(1, self.n + 1)
                if vault_stills.thumb_path(self.aid, i).is_file()
                and vault_stills.image_path(self.aid, i).is_file()}
        self.on_disk_at_call.append(have)

    def _item(self, i: int) -> dict:
        m = {"id": i, "type": "video" if i in self.videos else "photo",
             "createdAt": (datetime(2026, 1, 1) + timedelta(hours=i)).isoformat() + "+00:00",
             "files": {"thumb": {"url": f"https://cdn.example/{self.aid}/t{i}.jpg"},
                       "preview": {"url": f"https://cdn.example/{self.aid}/p{i}.jpg"}},
             "listStates": [{"id": 7, "type": "custom", "hasMedia": True}] if i % 10 == 0 else []}
        if i in self.videos:
            m["videoSources"] = {"240": f"https://cdn.example/{self.aid}/v{i}.mp4"}
            m["duration"] = 10
        return m

    def vault_lists(self, *, view, limit, offset, query=None):
        self._snap(("lists", limit, offset))
        if self.fail_lists:
            raise RuntimeError("429 Too Many Requests (fake)")
        rows = [{"id": 7, "type": "custom", "hasMedia": True, "name": "seven"},
                {"id": 8, "type": "custom", "hasMedia": False, "name": "empty"},
                {"id": "posts", "type": "posts", "hasMedia": True}]
        return {"list": rows[offset:offset + limit], "hasMore": offset + limit < len(rows)}

    def vault_media(self, *, limit, offset, type="all", list_id=None, sort="desc",
                    field="recent", query=None, before_publish_date=None):
        self._snap(("media", limit, offset, list_id, sort))
        ids = list(range(1, self.n + 1))
        if list_id is not None:
            ids = [i for i in ids if i % 10 == 0]
        if sort == "desc":
            ids.reverse()
        page = ids[offset:offset + limit]
        return {"list": [self._item(i) for i in page], "hasMore": offset + limit < len(ids)}


_CLIENTS: dict[str, FakeOF] = {}
ax._make_client = lambda aid: _CLIENTS[aid]


async def _collect(aid: str, n: int, videos: tuple[int, ...] = (),
                   fail_lists: bool = False) -> tuple[FakeOF, VaultCacheRun]:
    _fetches.clear()
    _warmed.clear()
    async with get_session() as s:
        for t in (VaultCacheRun, VaultItem, VaultResponseCache):
            await s.execute(delete(t).where(t.account_id == aid))
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
    of = _CLIENTS[aid] = FakeOF(aid, n, videos, fail_lists)
    r = await api.start_collect(account_id=aid)
    for _ in range(500):
        if aid not in vault_runs.manual_running:
            break
        await asyncio.sleep(0.01)
    assert aid not in vault_runs.manual_running, "collect never finished"
    async with get_session() as s:
        run = await s.get(VaultCacheRun, r["run_id"])
    return of, run


async def case_call_order_newest_folders_then_asc_walk():
    of, run = await _collect("accO", 250)
    assert of.calls == [
        ("media", 100, 0, None, "desc"),   # 1. newest 100
        ("lists", 50, 0),                  # 2. folder list
        ("media", 24, 0, 7, "desc"),       #    folder 7 page 0 (8 empty, posts built-in)
        ("media", 100, 0, None, "asc"),    # 3. oldest 100
        ("media", 100, 100, None, "asc"),  # 4. the rest
        ("media", 100, 200, None, "asc"),
    ], of.calls
    assert (run.status, run.phase, run.error) == ("done", "done", None), (run.status, run.phase, run.error)
    assert (run.total_seen, run.upserted) == (250, 250), "an item counted twice"
    s = await api.cache_summary(account_id="accO")
    assert s["complete"] is True and s["count"] == 250, s
    assert len(_fetches) == len(set(_fetches)) == 500, "a still downloaded twice (or missed)"
    async with get_session() as ss:
        stamps = set((await ss.execute(select(VaultItem.last_seen_run_id).where(
            VaultItem.account_id == "accO"))).scalars())
    assert stamps == {run.id}, stamps


async def case_each_batch_on_disk_before_the_next_call():
    of, _ = await _collect("accB", 250)
    newest = set(range(151, 251))
    folder7 = set(range(20, 251, 10))   # folder 7's page 0: its newest 24
    assert of.on_disk_at_call[0] == set(), "stills before any page"
    assert of.on_disk_at_call[1] == newest, "newest 100 not usable before the folder list"
    assert of.on_disk_at_call[3] == newest | folder7, "folder page not warmed before the asc walk"
    assert of.on_disk_at_call[4] == newest | folder7 | set(range(1, 101)), (
        "oldest 100 not warmed before offset 100")


async def case_page_cap_is_not_a_full_walk():
    saved = api._MAX_PAGES
    api._MAX_PAGES = 2
    try:
        of, run = await _collect("accCap", 350)
    finally:
        api._MAX_PAGES = saved
    walk = [c[2] for c in of.calls if c[0] == "media" and c[4] == "asc"]
    assert walk == [0, 100], walk
    assert run.status == "done" and run.error == vault_runs.capped_error(2), run.error
    s = await api.cache_summary(account_id="accCap")
    assert s["complete"] is False, s


async def case_storyboards_warm_newest_first():
    _, run = await _collect("accV", 250, videos=(5, 120, 200))
    assert run.status == "done", run.error
    assert _warmed == [f"https://cdn.example/accV/v{i}.mp4" for i in (200, 120, 5)], _warmed


async def case_folder_list_failure_does_not_stop_the_walk():
    """One 429 on the folder list (no retry on the manual path) costs the folders'
    head start, never the Collect."""
    of, run = await _collect("accL", 250, fail_lists=True)
    assert of.calls == [("media", 100, 0, None, "desc"), ("lists", 50, 0)] + [
        ("media", 100, o, None, "asc") for o in (0, 100, 200)], of.calls
    assert (run.status, run.error, run.total_seen) == ("done", None, 250), (run.status, run.error)
    assert (await api.cache_summary(account_id="accL"))["complete"] is True


async def case_failed_warm_is_retried_by_the_walk():
    """A still whose download blew up on the folder page is fetched again when the
    asc walk meets that media, not skipped as already handled."""
    _FAIL_ONCE.add("https://cdn.example/accW/t20.jpg")   # 20: new on folder 7's page
    of, run = await _collect("accW", 250)
    assert run.status == "done" and run.total_seen == 250, (run.status, run.error)
    assert _fetches.count("https://cdn.example/accW/t20.jpg") == 2, "failed thumb never retried"
    assert vault_stills.thumb_path("accW", 20).is_file()
    assert ("media", 100, 0, None, "asc") in of.calls


_harness.run()
