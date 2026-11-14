#!/usr/bin/env python3
"""The manual "Collect all" sweep (vault_ai_api._run_collect) walks OF in the
describe sweep's priority order and asks the operator every 2000 new items.

Fake OF client at the client seam (`ax._make_client`), real DB, real mirror
upserts, real still stores in a temp dir (CDN fetch faked).

Covers: OF call order folder list → rail folders paged whole → 5 newest pages →
1 oldest page → … until the cursors meet (vault_collect_plan); each page's thumbs +
full stills are on disk before the next OF call; a folder's page 0 refills the
picker cache; nothing counted or downloaded twice; the run ends done + complete;
the page cap still ends capped (not complete); storyboards warm newest first;
pause after COLLECT_PAUSE_EVERY new items (status "paused", OF idle), continue
resumes, stop → storyboards warmed + done, not complete; an unanswered pause
auto-stops; continue/stop 409 when nothing is paused; prepare content's harvest
never pauses.

Run: ./venv/bin/python service/tests/test_vault_manual_collect_order.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import tempfile  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

import automation_executor as ax  # noqa: E402
import full_ai_prepare  # noqa: E402
import vault_ai_api as api  # noqa: E402
import vault_cache  # noqa: E402
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
async def _reset(aid: str, n: int, videos: tuple[int, ...] = (), fail_lists: bool = False) -> FakeOF:
    _fetches.clear()
    _warmed.clear()
    async with get_session() as s:
        for t in (VaultCacheRun, VaultItem, VaultResponseCache):
            await s.execute(delete(t).where(t.account_id == aid))
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
    of = _CLIENTS[aid] = FakeOF(aid, n, videos, fail_lists)
    return of


async def _until(pred, what: str, tries: int = 3000) -> None:
    for _ in range(tries):
        if await pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


async def _finished(aid: str) -> bool:
    return aid not in vault_runs.manual_running


async def _run(run_id: int) -> VaultCacheRun:
    async with get_session() as s:
        return await s.get(VaultCacheRun, run_id)


async def _collect(aid: str, n: int, videos: tuple[int, ...] = (),
                   fail_lists: bool = False) -> tuple[FakeOF, VaultCacheRun]:
    of = await _reset(aid, n, videos, fail_lists)
    r = await api.start_collect(account_id=aid)
    await _until(lambda: _finished(aid), "collect to finish")
    return of, await _run(r["run_id"])


async def _paused(aid: str) -> dict:
    async def is_paused() -> bool:
        return aid in api._paused and (await api.collect_status(account_id=aid))["run"]["status"] == "paused"
    await _until(is_paused, "the pause")
    return (await api.collect_status(account_id=aid))["run"]


def _all_calls(of: FakeOF) -> list[tuple]:
    return [(c[4], c[2]) for c in of.calls if c[0] == "media" and c[3] is None]


async def case_call_order_folders_then_newest_until_met():
    of, run = await _collect("accO", 250)
    assert of.calls == [
        ("lists", 50, 0),                   # folder list
        ("media", 100, 0, 7, "desc"),       # folder 7 whole (25 items; 8 empty, posts built-in)
        ("media", 100, 0, None, "desc"),    # newest pages … OF says no more on the third
        ("media", 100, 100, None, "desc"),
        ("media", 100, 200, None, "desc"),
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
    # Folder 7's page 0 refills the picker's cache (its limit-24 slot, sliced from the 100).
    body = await vault_cache.get("accO", vault_cache.vault_media_cache_key(
        type="all", list_id=7, offset=0, limit=24, sort="desc", field="recent", q_norm=""))
    assert body is not None, "folder page 0 not cached for the picker"
    assert [m["id"] for m in body["list"]] == list(range(250, 0, -10))[:24] and body["hasMore"], body


async def case_rounds_interleave_and_cursors_meet():
    """1300 items, folder 7 = 130 (two pages): folder whole → desc 0-400 → asc 0 →
    desc 500-900 → asc 100 → desc 1000 → desc 1100 (ids 200..101) meets asc."""
    of, run = await _collect("accR", 1300)
    assert [c[2] for c in of.calls if c[0] == "media" and c[3] == 7] == [0, 100], of.calls
    assert of.calls.index(("media", 100, 100, 7, "desc")) < of.calls.index(("media", 100, 0, None, "desc"))
    want = ([("desc", o) for o in range(0, 500, 100)] + [("asc", 0)]
            + [("desc", o) for o in range(500, 1000, 100)] + [("asc", 100)]
            + [("desc", 1000), ("desc", 1100)])
    assert _all_calls(of) == want, _all_calls(of)
    assert (run.status, run.error, run.total_seen) == ("done", None, 1300), (run.status, run.error)
    assert (await api.cache_summary(account_id="accR"))["complete"] is True


async def case_each_batch_on_disk_before_the_next_call():
    of, _ = await _collect("accB", 250)
    folder7 = set(range(10, 251, 10))
    assert of.on_disk_at_call[1] == set(), "stills before any media page"
    assert of.on_disk_at_call[2] == folder7, "folder not usable before the newest pages"
    assert of.on_disk_at_call[3] == folder7 | set(range(151, 251)), "newest 100 not warmed before the next"
    assert of.on_disk_at_call[4] == folder7 | set(range(51, 251)), "second page not warmed before the third"


async def case_page_cap_is_not_a_full_walk():
    saved = api._MAX_PAGES
    api._MAX_PAGES = 2
    try:
        of, run = await _collect("accCap", 350)
    finally:
        api._MAX_PAGES = saved
    assert _all_calls(of) == [("desc", 0), ("desc", 100)], _all_calls(of)
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
    assert of.calls == [("lists", 50, 0)] + [
        ("media", 100, o, None, "desc") for o in (0, 100, 200)], of.calls
    assert (run.status, run.error, run.total_seen) == ("done", None, 250), (run.status, run.error)
    assert (await api.cache_summary(account_id="accL"))["complete"] is True


async def case_failed_warm_is_retried_by_the_walk():
    """A still whose download blew up on the folder page is fetched again when the
    newest walk meets that media, not skipped as already handled."""
    _FAIL_ONCE.add("https://cdn.example/accW/t20.jpg")   # 20: new on folder 7's page
    of, run = await _collect("accW", 250)
    assert run.status == "done" and run.total_seen == 250, (run.status, run.error)
    assert _fetches.count("https://cdn.example/accW/t20.jpg") == 2, "failed thumb never retried"
    assert vault_stills.thumb_path("accW", 20).is_file()
    assert ("media", 100, 200, None, "desc") in of.calls


async def case_pause_every_2000_then_continue():
    """2300 items: the walk pauses on the first page that takes it to ≥2000 new,
    OF stays idle while paused, the status says so (not interrupted), continue walks
    to the end (the counter restarts: no second ask for the last 270)."""
    assert api.COLLECT_PAUSE_EVERY == 2000
    aid = "accP"
    of = await _reset(aid, 2300)
    r = await api.start_collect(account_id=aid)
    st = await _paused(aid)
    assert st["running"] is True and 2000 <= st["total_seen"] < 2100, st
    summary = await api.cache_summary(account_id=aid)
    assert summary["running"] and summary["last_run"]["status"] == "paused", summary
    n_calls = len(of.calls)
    await asyncio.sleep(0.1)
    assert len(of.calls) == n_calls, "OF called while paused"
    assert await api.continue_collect(account_id=aid) == {"account_id": aid, "status": "continue"}
    await _until(lambda: _finished(aid), "collect to finish")
    run = await _run(r["run_id"])
    assert (run.status, run.phase, run.error, run.total_seen) == ("done", "done", None, 2300), (
        run.status, run.error, run.total_seen)
    assert len(of.calls) > n_calls
    assert (await api.cache_summary(account_id=aid))["complete"] is True


async def case_stop_warms_and_is_not_a_full_walk():
    saved = api.COLLECT_PAUSE_EVERY
    api.COLLECT_PAUSE_EVERY = 300
    aid = "accS"
    try:
        of = await _reset(aid, 1000, videos=(1000, 995, 3))
        r = await api.start_collect(account_id=aid)
        st = await _paused(aid)
        n_calls = len(of.calls)
        assert await api.stop_collect(account_id=aid) == {"account_id": aid, "status": "stop"}
        await _until(lambda: _finished(aid), "collect to finish")
    finally:
        api.COLLECT_PAUSE_EVERY = saved
    run = await _run(r["run_id"])
    assert len(of.calls) == n_calls, "OF called after stop"
    assert (run.status, run.phase) == ("done", "done"), (run.status, run.phase)
    assert run.error == f"stopped by operator at {st['total_seen']} items", run.error
    # Folder 7 (100) + desc 0-200 (1000..701) → 370 new at the pause: clips 1000 and 995, not 3.
    assert _warmed == [f"https://cdn.example/{aid}/v{i}.mp4" for i in (1000, 995)], _warmed
    s = await api.cache_summary(account_id=aid)
    assert s["complete"] is False and s["last_run"]["status"] == "done", s


async def case_unanswered_pause_auto_stops():
    saved = api.COLLECT_PAUSE_EVERY, api.COLLECT_PAUSE_TIMEOUT_S
    api.COLLECT_PAUSE_EVERY, api.COLLECT_PAUSE_TIMEOUT_S = 300, 0.2
    aid = "accT"
    try:
        await _reset(aid, 1000)
        r = await api.start_collect(account_id=aid)
        await _until(lambda: _finished(aid), "collect to auto-stop")
    finally:
        api.COLLECT_PAUSE_EVERY, api.COLLECT_PAUSE_TIMEOUT_S = saved
    run = await _run(r["run_id"])
    assert run.status == "done" and run.error and run.error.startswith("stopped at "), run.error
    assert aid not in api._paused
    assert (await api.cache_summary(account_id=aid))["complete"] is False


async def case_answer_without_a_pause_is_409():
    for fn in (api.continue_collect, api.stop_collect):
        try:
            await fn(account_id="accNone")
        except HTTPException as e:
            assert e.status_code == 409 and e.detail == {"error": "collect_not_paused"}, e.detail
        else:
            raise AssertionError(f"{fn.__name__} without a pause did not 409")


async def case_prepare_harvest_never_pauses():
    saved = api.COLLECT_PAUSE_EVERY
    api.COLLECT_PAUSE_EVERY = 100
    aid = "accH"
    try:
        await _reset(aid, 1000)
        step = await asyncio.wait_for(full_ai_prepare._harvest(aid, {}), 30)
    finally:
        api.COLLECT_PAUSE_EVERY = saved
    assert step["state"] == "done" and step["counts"]["seen"] == 1000, step
    assert aid not in api._paused


_harness.run()
