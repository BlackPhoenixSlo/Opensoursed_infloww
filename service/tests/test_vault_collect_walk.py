#!/usr/bin/env python3
"""vault_collect — the background vault week-cache collector.

Fake OF client at the client seam (`ax._make_client`), real DB, real
vault_cache, real mirror upserts, real route bodies for the key check.

Covers: pacing (≥GAP_S between OF calls), one account at a time, skip a busy
account + bounded starvation, dead-session accounts never called, resume of an
errored / interrupted walk at its cursor (a "restart"), a stale account gets the
hot set + thumbs without a second full walk, the pages it caches are the ones
the picker routes read (same keys), thumbs only for the newest 100.

Run: ./venv/bin/python service/tests/test_vault_collect_walk.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB
_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
import contextlib  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

import server  # noqa: E402  — the routes whose keys the collector must match
import accounts as account_registry  # noqa: E402
import automation_executor as ax  # noqa: E402
import vault_ai_api  # noqa: E402
import vault_cache  # noqa: E402
import vault_collect as vc  # noqa: E402
import vault_stills  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountHealth, VaultCacheRun, VaultItem, VaultResponseCache,
)

GAP = 0.15
vc.GAP_S = GAP
vc.THUMB_GAP_S = 0.0
vc._lane = lambda aid: contextlib.nullcontext()
vault_ai_api.assert_account_owned = lambda _a: None
vault_stills.THUMB_DIR = Path(tempfile.mkdtemp(prefix="vc_thumbs_"))
_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
_thumb_fetches: list[str] = []


def _fake_fetch(client, url):
    _thumb_fetches.append(url)
    return _JPEG


vault_stills.fetch_bytes_sync = _fake_fetch

_LIVE: list[str] = []
account_registry.list_accounts = lambda include_watchers=False: [
    {"id": a, "has_session": True, "platform": "onlyfans"} for a in _LIVE]
_ACTIVE: dict[str, float] = {}
vc._user_active_at = lambda aid: _ACTIVE.get(aid)


class FakeOF:
    """Vault of `n` items; ids 1..n, newer = higher id. Every 10th item is in
    folder 7 (custom, hasMedia); folder 8 is custom but empty; 'posts' is built-in."""

    calls: list[tuple[float, str, str, dict]] = []   # shared across accounts
    _inflight = 0
    peak = 0
    _lock = threading.Lock()

    def __init__(self, aid: str, n: int = 250, fail_at_offset: int | None = None,
                 list_states: bool = True):
        self.aid, self.n, self.fail_at_offset = aid, n, fail_at_offset
        self.list_states = list_states

    def _enter(self, name, kw):
        with FakeOF._lock:
            FakeOF.calls.append((time.monotonic(), self.aid, name, kw))
            FakeOF._inflight += 1
            FakeOF.peak = max(FakeOF.peak, FakeOF._inflight)
        time.sleep(0.01)

    def _exit(self):
        with FakeOF._lock:
            FakeOF._inflight -= 1

    def _item(self, i):
        base = datetime(2026, 1, 1) + timedelta(hours=i)
        return {"id": i, "type": "photo", "createdAt": base.isoformat() + "+00:00",
                "files": {"thumb": {"url": f"https://cdn.example/{self.aid}/{i}.jpg"}},
                **({"listStates": [{"id": 7, "type": "custom", "hasMedia": True}] if i % 10 == 0 else []}
                   if self.list_states else {})}

    def vault_lists(self, *, view, limit, offset, query=None):
        self._enter("lists", dict(view=view, limit=limit, offset=offset))
        try:
            rows = [{"id": 7, "type": "custom", "hasMedia": True, "name": "seven"},
                    {"id": 8, "type": "custom", "hasMedia": False, "name": "empty"},
                    {"id": "posts", "type": "posts", "hasMedia": True}]
            return {"list": rows[offset:offset + limit], "hasMore": offset + limit < len(rows)}
        finally:
            self._exit()

    def vault_media(self, *, limit, offset, type="all", list_id=None, sort="desc",
                    field="recent", query=None, before_publish_date=None):
        self._enter("media", dict(limit=limit, offset=offset, list_id=list_id, sort=sort))
        try:
            if self.fail_at_offset is not None and limit == 100 and offset >= self.fail_at_offset:
                raise RuntimeError("session dead (fake 401)")
            ids = list(range(1, self.n + 1))
            if list_id is not None:
                ids = [i for i in ids if i % 10 == 0]
            if sort == "desc":
                ids.reverse()
            page = ids[offset:offset + limit]
            return {"list": [self._item(i) for i in page], "hasMore": offset + limit < len(ids)}
        finally:
            self._exit()


_CLIENTS: dict[str, FakeOF] = {}
ax._make_client = lambda aid: _CLIENTS[aid]


async def _reset(*aids: str, n: int = 250, fail_at_offset: int | None = None) -> None:
    FakeOF.calls.clear()
    FakeOF.peak = 0
    _LIVE[:] = list(aids)
    _ACTIVE.clear()
    vc._skipped_since.clear()
    _thumb_fetches.clear()
    async with get_session() as s:
        for t in (VaultCacheRun, VaultItem, VaultResponseCache, AccountHealth):
            await s.execute(delete(t))
        for a in aids:
            if await s.get(Account, a) is None:
                s.add(Account(id=a))
    for a in aids:
        _CLIENTS[a] = FakeOF(a, n=n, fail_at_offset=fail_at_offset)


async def _runs(aid: str) -> list[VaultCacheRun]:
    async with get_session() as s:
        return list((await s.execute(select(VaultCacheRun).where(
            VaultCacheRun.account_id == aid).order_by(VaultCacheRun.id))).scalars())


async def _mirror_count(aid: str) -> int:
    async with get_session() as s:
        return len((await s.execute(select(VaultItem.media_id).where(
            VaultItem.account_id == aid))).all())


async def case_pacing_gap_between_every_of_call():
    await _reset("accP")
    await vc.tick()
    starts = [c[0] for c in FakeOF.calls]
    assert len(starts) == 7, f"expected lists + folder + 2 All pages + 3 walk pages, got {len(starts)}"
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert min(gaps) >= GAP, f"min gap {min(gaps):.3f}s < GAP_S {GAP}s: {gaps}"
    runs = await _runs("accP")
    assert [(r.status, r.phase) for r in runs] == [("done", "auto:done")], runs
    assert runs[0].total_seen == 250 and runs[0].pages_done == 3, (runs[0].total_seen, runs[0].pages_done)
    assert await _mirror_count("accP") == 250
    # Picker shapes: lists at 50/page, dropdown folder 7 only (8 empty, posts built-in),
    # All page 0 + offset 24 at limit 24 desc, then the walk at 100 asc.
    kinds = [(c[2], c[3].get("limit"), c[3].get("offset"), c[3].get("list_id"), c[3].get("sort"))
             for c in FakeOF.calls]
    assert kinds[:4] == [("lists", 50, 0, None, None), ("media", 24, 0, 7, "desc"),
                         ("media", 24, 0, None, "desc"), ("media", 24, 24, None, "desc")], kinds[:4]
    assert kinds[4:] == [("media", 100, o, None, "asc") for o in (0, 100, 200)], kinds[4:]


async def case_cached_pages_are_what_the_picker_routes_read():
    """Real route bodies, client that would blow up: every answer must come
    from what the collector cached, under the route's own keys."""
    await _reset("accK")
    await vc.tick()
    real_aid, real_gate, real_client = server._current_aid, server._allowed_folder_ids_for_chatter, server._get_client

    async def _no_gate(_aid):
        return None

    def _boom(*_a, **_k):
        raise AssertionError("route went to OF — collector key mismatch")
    server._current_aid = lambda: "accK"
    server._allowed_folder_ids_for_chatter = _no_gate
    server._get_client = _boom
    try:
        lists = await server.of_vault_lists(view="main", limit=50, offset=0, query=None, refresh=False)
        assert [f["id"] for f in lists["list"]] == [7, 8, "posts"], lists
        for list_id, off in ((None, 0), (None, 24), (7, 0)):
            page = await server.of_vault_media(limit=24, offset=off, type="all", list_id=list_id,
                                               sort="desc", field="recent", query=None,
                                               before_publish_date=None, refresh=False)
            assert len(page["list"]) == 24 and page["list"][0]["id"] == (
                (250 - off) if list_id is None else 250), (list_id, off, page["list"][0])
    finally:
        server._current_aid, server._allowed_folder_ids_for_chatter, server._get_client = (
            real_aid, real_gate, real_client)


async def case_thumbs_newest_100_only():
    await _reset("accT")
    await vc.tick()
    files = sorted(int(p.stem) for p in (vault_stills.THUMB_DIR / "accT").glob("*.jpg"))
    assert files == list(range(151, 251)), (len(files), files[:3], files[-3:])
    assert len(_thumb_fetches) == 100


async def case_one_account_at_a_time():
    await _reset("accA", "accB")
    await asyncio.gather(vc.tick(), vc.tick())   # second tick finds the lock held
    walked = {c[1] for c in FakeOF.calls}
    assert len(walked) == 1, f"two accounts walked at once: {walked}"
    assert FakeOF.peak == 1, f"peak concurrent OF calls {FakeOF.peak}"
    await vc.tick()
    assert {c[1] for c in FakeOF.calls} == {"accA", "accB"}
    await vc.tick()   # both fresh now → nothing due
    n = len(FakeOF.calls)
    await vc.tick()
    assert len(FakeOF.calls) == n, "a fresh account was walked again"


async def case_skip_busy_then_bounded_starvation():
    await _reset("accBusy")
    vc.MAX_SKIP_S = 0.4
    try:
        _ACTIVE["accBusy"] = time.monotonic() + 3600      # someone is always clicking
        await vc.tick()
        assert FakeOF.calls == [], "walked an account in use"
        vault_ai_api._running.add("accBusy")              # manual Collect running
        await asyncio.sleep(0.45)
        await vc.tick()
        assert FakeOF.calls == [], "walked an account under a manual Collect"
        vault_ai_api._running.discard("accBusy")
        await vc.tick()                                    # skipped > MAX_SKIP_S → walks anyway
        assert FakeOF.calls, "starved past MAX_SKIP_S"
        assert "accBusy" not in vault_ai_api._running
    finally:
        vc.MAX_SKIP_S = 1800
        vault_ai_api._running.discard("accBusy")


async def case_dead_session_never_called():
    await _reset("accDead")
    async with get_session() as s:
        s.add(AccountHealth(account_id="accDead", session_dead_at=datetime.utcnow(),
                            session_dead_reason="otp_required"))
    await vc.tick()
    assert FakeOF.calls == [] and await _runs("accDead") == []


async def case_error_backoff_then_resume_at_cursor():
    await _reset("accR", n=350, fail_at_offset=200)
    await vc.tick()
    (run,) = await _runs("accR")
    assert (run.status, run.phase, run.pages_done) == ("error", "auto:all:200", 2), (
        run.status, run.phase, run.pages_done)
    assert "session dead" in (run.error or "")
    # Inside the 1 h backoff: not retried.
    FakeOF.calls.clear()
    await vc.tick()
    assert FakeOF.calls == [], "retried inside the error backoff"
    # "Restart": the process is gone, the row is what is left. Session healed, backoff over.
    _CLIENTS["accR"] = FakeOF("accR", n=350)
    async with get_session() as s:
        r = await s.get(VaultCacheRun, run.id)
        r.finished_at = datetime.utcnow() - timedelta(hours=2)
    await vc.tick()
    first = FakeOF.calls[0][3]
    assert (first["limit"], first["offset"], first["sort"]) == (100, 200, "asc"), first
    assert not any(c[2] == "lists" for c in FakeOF.calls), "resume redid the hot set"
    (run,) = await _runs("accR")
    assert (run.status, run.phase, run.total_seen) == ("done", "auto:done", 350), (
        run.status, run.phase, run.total_seen)
    assert await _mirror_count("accR") == 350


async def case_interrupted_running_row_resumes_first():
    await _reset("accI", "accNew", n=150)
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accI", status="running", phase="auto:all:100",
                            pages_done=1, total_seen=100, upserted=100))
    await vc.tick()
    assert {c[1] for c in FakeOF.calls} == {"accI"}, "interrupted walk not resumed first"
    assert FakeOF.calls[0][3]["offset"] == 100


async def case_stale_account_gets_hot_set_not_full_walk():
    await _reset("accS")
    await vc.tick()
    async with get_session() as s:
        for r in (await s.execute(select(VaultCacheRun))).scalars():
            r.finished_at = datetime.utcnow() - timedelta(seconds=vc.STALE_S + 60)
    FakeOF.calls.clear()
    await vc.tick()
    assert not any(c[3].get("limit") == 100 for c in FakeOF.calls), "stale refresh re-walked All"
    assert [c[2] for c in FakeOF.calls] == ["lists", "media", "media", "media"], FakeOF.calls
    runs = await _runs("accS")
    assert [(r.status, r.phase) for r in runs] == [("done", "auto:done")] * 2
    summary = await vault_ai_api.cache_summary(account_id="accS")
    assert summary["complete"] is True and summary["last_run"] is None, summary


async def case_weekly_full_rewalk():
    """Hot-only refreshes keep the latest auto:done fresh; the full walk still
    comes back once the last FULL one is older than FULL_S."""
    await _reset("accW")
    await vc.tick()                                   # full walk (pages_done 3)
    async with get_session() as s:
        for r in (await s.execute(select(VaultCacheRun))).scalars():
            r.finished_at = datetime.utcnow() - timedelta(seconds=vc.FULL_S + 60)
        s.add(VaultCacheRun(account_id="accW", status="done", phase="auto:done", pages_done=0,
                            started_at=datetime.utcnow() - timedelta(seconds=vc.STALE_S + 120),
                            finished_at=datetime.utcnow() - timedelta(seconds=vc.STALE_S + 60)))
    FakeOF.calls.clear()
    await vc.tick()
    walk = [c[3]["offset"] for c in FakeOF.calls if c[3].get("limit") == 100]
    assert walk == [0, 100, 200], f"no weekly full re-walk: {walk}"
    assert FakeOF.calls[0][2] == "lists", "re-walk skipped the hot set"
    runs = await _runs("accW")
    assert (runs[-1].status, runs[-1].phase, runs[-1].pages_done) == ("done", "auto:done", 3)


async def case_manual_collect_preempts_the_collector():
    """The button never 409s behind the collector: it stops the walk (run marked
    `preempted`, cursor kept, released within one gap) and runs its own sweep."""
    await _reset("accM", n=350)
    vc.GAP_S = 0.5
    try:
        walk = asyncio.create_task(vc.tick())
        while not FakeOF.calls:
            await asyncio.sleep(0.01)
        assert "accM" in vc._auto_running and "accM" not in vault_ai_api._running
        s = await vault_ai_api.cache_summary(account_id="accM")
        assert s["running"] is False, "summary.running reports the collector"
        overlap: list[bool] = []
        real_make = ax._make_client

        def _make(aid):   # the manual sweep's first step after `preempt`
            overlap.append(aid in vc._auto_running)
            return real_make(aid)
        ax._make_client = _make
        t0 = time.monotonic()
        try:
            r = await vault_ai_api.start_collect(account_id="accM")   # would 409 if shared
            assert r["status"] == "running", r
            await asyncio.wait_for(walk, 5)
            while not overlap:
                await asyncio.sleep(0.01)
        finally:
            ax._make_client = real_make
        assert overlap == [False], "manual sweep started while the collector still held the account"
        assert "accM" not in vc._auto_running
        while "accM" in vault_ai_api._running:
            await asyncio.sleep(0.05)
        assert time.monotonic() - t0 < 0.5 + 2, "collector held on past one gap"
    finally:
        vc.GAP_S = GAP
    auto = [r for r in await _runs("accM") if (r.phase or "").startswith("auto:")]
    assert len(auto) == 1 and auto[0].status == "error" and auto[0].error == "[1] preempted", (
        [(r.status, r.phase, r.error) for r in auto])
    assert auto[0].phase == "auto:hot", auto[0].phase       # cursor kept, not reset
    s = await vault_ai_api.cache_summary(account_id="accM")
    assert s["complete"] is True and s["last_run"]["status"] == "done", s
    # Next resume: the manual sweep already walked All → straight to thumbs.
    async with get_session() as ss:
        row = await ss.get(VaultCacheRun, auto[0].id)
        row.phase, row.finished_at = "auto:all:200", datetime.utcnow() - timedelta(hours=2)
    FakeOF.calls.clear()
    await vc.tick()
    assert FakeOF.calls == [], "re-walked All right after a manual Collect"


async def case_three_errors_then_fresh_walk():
    await _reset("accE")
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accE", status="error", phase="auto:all:200",
                            error="[3] boom", pages_done=2,
                            started_at=datetime.utcnow() - timedelta(hours=3),
                            finished_at=datetime.utcnow() - timedelta(hours=2)))
    await vc.tick()
    assert FakeOF.calls[0][2] == "lists", "kept resuming a thrice-failed cursor"
    runs = await _runs("accE")
    assert [(r.status, r.phase) for r in runs] == [("abandoned", "auto:all:200"),
                                                   ("done", "auto:done")], runs


async def case_error_count_increments_on_resume():
    await _reset("accE2", fail_at_offset=0)
    await vc.tick()
    async with get_session() as s:
        r = (await s.execute(select(VaultCacheRun))).scalar_one()
        assert r.error.startswith("[1] "), r.error
        r.finished_at = datetime.utcnow() - timedelta(hours=2)
    await vc.tick()
    (r,) = await _runs("accE2")
    assert r.error.startswith("[2] "), r.error


async def case_folder_page_without_list_states_keeps_membership():
    await _reset("accU")
    _CLIENTS["accU"] = FakeOF("accU", list_states=False)
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accU", status="done", phase="done",
                            finished_at=datetime.utcnow()))           # full walk fresh
        s.add(VaultItem(account_id="accU", media_id=250, kind="photo", of_folder_ids="[5]",
                        created_at=datetime(2026, 1, 1)))
    await vc.tick()
    assert not any(c[3].get("limit") == 100 for c in FakeOF.calls)
    async with get_session() as s:
        a = await s.get(VaultItem, ("accU", 250))   # in folder 7's page AND All's
        b = await s.get(VaultItem, ("accU", 240))   # folder 7's page only
    assert json.loads(a.of_folder_ids) == [5, 7], a.of_folder_ids   # All's page kept it
    assert json.loads(b.of_folder_ids) == [7], b.of_folder_ids
    async with get_session() as s:
        c = await s.get(VaultItem, ("accU", 249))   # All's page only, unknown folders
    assert json.loads(c.of_folder_ids) == [], c.of_folder_ids


async def case_summary_incomplete_until_full_walk():
    await _reset("accC", n=350, fail_at_offset=100)
    await vc.tick()
    s = await vault_ai_api.cache_summary(account_id="accC")
    assert s["count"] > 0 and s["complete"] is False, s


_harness.run()
