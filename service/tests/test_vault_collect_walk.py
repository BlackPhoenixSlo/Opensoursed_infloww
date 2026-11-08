#!/usr/bin/env python3
"""vault_collect — the background vault week-cache collector.

Fake OF client at the client seam (`ax._make_client`), real DB, real
vault_cache, real mirror upserts, real route bodies for the key check.

Covers: pacing (≥GAP_S between OF calls), one account at a time, skip a busy
account + bounded starvation, dead-session accounts never called, resume of an
errored / interrupted walk at its cursor (a "restart"), a stale account gets the
hot set + thumbs without a second full walk, the pages it caches are the ones
the picker routes read (same keys), thumbs only for the newest 100. Interruptions
(manual Collect, a person mid-walk, a proxy change) pause at the cursor without an
error; the page cap is not a full walk; one bad folder page does not stop the walk;
thumb workers stop together; old auto rows are pruned; every OF call is inside an
of_pacing walk.

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
import of_pacing  # noqa: E402
import vault_ai_api  # noqa: E402
import vault_cache  # noqa: E402
import vault_collect as vc  # noqa: E402
import vault_runs  # noqa: E402
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
_THUMB_DELAY = [0.0]
_THUMB_HOLD_AT = [0]               # this fetch (1-based) waits for _THUMB_GATE
_THUMB_GATE = threading.Event()


def _fake_fetch(client, url):
    _thumb_fetches.append(url)
    if len(_thumb_fetches) == _THUMB_HOLD_AT[0]:
        _THUMB_GATE.wait(5)
    time.sleep(_THUMB_DELAY[0])
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
    walks: list[str | None] = []                      # of_pacing walk kind per call
    _inflight = 0
    peak = 0
    _lock = threading.Lock()

    def __init__(self, aid: str, n: int = 250, fail_at_offset: int | None = None,
                 list_states: bool = True, fail_folder: bool = False):
        self.aid, self.n, self.fail_at_offset = aid, n, fail_at_offset
        self.list_states, self.fail_folder = list_states, fail_folder

    def _enter(self, name, kw):
        w = of_pacing._WALK.get()
        with FakeOF._lock:
            FakeOF.calls.append((time.monotonic(), self.aid, name, kw))
            FakeOF.walks.append(w.kind if w else None)
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
            if self.fail_folder and list_id is not None:
                raise RuntimeError("folder page 500 (fake)")
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
    FakeOF.walks.clear()
    FakeOF.peak = 0
    _THUMB_DELAY[0] = 0.0
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
        vault_runs.manual_running.add("accBusy")              # manual Collect running
        await asyncio.sleep(0.45)
        await vc.tick()
        assert FakeOF.calls == [], "walked an account under a manual Collect"
        vault_runs.manual_running.discard("accBusy")
        await vc.tick()                                    # skipped > MAX_SKIP_S → walks anyway
        assert FakeOF.calls, "starved past MAX_SKIP_S"
        assert "accBusy" not in vault_runs.manual_running
        (run,) = await _runs("accBusy")                    # the forced walk does not yield
        assert (run.status, run.phase) == ("done", "auto:done"), (run.status, run.phase)
    finally:
        vc.MAX_SKIP_S = 1800
        vault_runs.manual_running.discard("accBusy")


async def case_bursty_person_cannot_starve_past_max_skip():
    """Quiet at every pick, busy again mid-walk: MAX_SKIP_S counts from the first
    yield (a quiet pick does not restart it), so the walk is eventually forced."""
    await _reset("accBurst")
    vc.MAX_SKIP_S = 0.4
    t0 = time.monotonic()
    try:
        yields = 0
        while time.monotonic() - t0 < 4:
            _ACTIVE.clear()                                 # quiet when the tick picks
            n = len(FakeOF.calls)
            walk = asyncio.create_task(vc.tick())
            await _until(lambda: len(FakeOF.calls) > n or walk.done())
            _ACTIVE["accBurst"] = time.monotonic()          # …and back mid-walk
            await asyncio.wait_for(walk, 5)
            (run,) = await _runs("accBurst")
            if run.status == "done":
                break
            yields += 1
        assert run.status == "done", f"still {run.status}/{run.phase} after {yields} yields"
        assert yields >= 1, yields
        assert "accBurst" not in vc._skipped_since, "a finished walk left its streak"
    finally:
        vc.MAX_SKIP_S = 1800


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
    """The button never 409s behind the collector: it stops the walk (no error,
    the row stays running at its cursor, released within one gap) and runs its
    own sweep."""
    await _reset("accM", n=350)
    vc.GAP_S = 0.5
    try:
        walk = asyncio.create_task(vc.tick())
        while not FakeOF.calls:
            await asyncio.sleep(0.01)
        assert "accM" in vc._auto_running and "accM" not in vault_runs.manual_running
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
        while "accM" in vault_runs.manual_running:
            await asyncio.sleep(0.05)
        assert time.monotonic() - t0 < 0.5 + 2, "collector held on past one gap"
    finally:
        vc.GAP_S = GAP
    auto = [r for r in await _runs("accM") if (r.phase or "").startswith("auto:")]
    assert len(auto) == 1 and auto[0].status == "running" and auto[0].error is None, (
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


async def case_legacy_abandoned_row_starts_fresh():
    """A row left `abandoned` by the old attempt cap is not terminal: a fresh walk starts."""
    await _reset("accE")
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accE", status="abandoned", phase="auto:all:200",
                            error="[3] boom", pages_done=2,
                            started_at=datetime.utcnow() - timedelta(hours=3),
                            finished_at=datetime.utcnow() - timedelta(hours=2)))
    await vc.tick()
    assert FakeOF.calls[0][2] == "lists", "an abandoned row blocked the account"
    runs = await _runs("accE")
    assert [(r.status, r.phase) for r in runs] == [("abandoned", "auto:all:200"),
                                                   ("done", "auto:done")], runs


async def case_error_is_plain_and_retried_at_cursor():
    """No attempt counter in the error text; past the 1 h backoff the walk resumes at its cursor."""
    await _reset("accE2", fail_at_offset=0)
    await vc.tick()
    async with get_session() as s:
        r = (await s.execute(select(VaultCacheRun))).scalar_one()
        assert (r.status, r.phase, r.error) == ("error", "auto:all:0", "session dead (fake 401)"), (
            r.status, r.phase, r.error)
        r.finished_at = datetime.utcnow() - timedelta(hours=2)
    FakeOF.calls.clear()
    await vc.tick()
    assert [c[3].get("offset") for c in FakeOF.calls] == [0], FakeOF.calls
    (r,) = await _runs("accE2")
    assert (r.status, r.error) == ("error", "session dead (fake 401)"), (r.status, r.error)


async def _until(pred, timeout: float = 5.0) -> None:
    t = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < t, "timed out"
        await asyncio.sleep(0.01)


async def case_person_mid_walk_pauses_at_cursor():
    """A person on the account mid-walk: the walk stops before its next OF call,
    no error, row running at its cursor; nothing while they stay; resumed there."""
    await _reset("accY", n=350)
    walk = asyncio.create_task(vc.tick())
    await _until(lambda: any(c[3].get("limit") == 100 for c in FakeOF.calls))
    _ACTIVE["accY"] = time.monotonic()
    await asyncio.wait_for(walk, 5)
    (run,) = await _runs("accY")
    assert run.status == "running" and run.error is None and run.phase.startswith("auto:all:"), (
        run.status, run.phase, run.error)
    cursor = int(run.phase.rsplit(":", 1)[1])
    assert cursor < 300, cursor
    assert "accY" not in vc._auto_running
    FakeOF.calls.clear()
    await vc.tick()
    assert FakeOF.calls == [], "walked while the person was still there"
    _ACTIVE.clear()
    await vc.tick()
    assert FakeOF.calls[0][3]["offset"] == cursor, FakeOF.calls[0]
    (run,) = await _runs("accY")
    assert (run.status, run.phase, run.total_seen) == ("done", "auto:done", 350), (
        run.status, run.phase, run.total_seen)


async def case_proxy_switch_stops_the_walk():
    """server._on_proxy_switched stops the walk on its old-IP client (cursor kept,
    no error); the next tick resumes it with a fresh client."""
    await _reset("accX", n=350)
    made: list[str] = []
    real_make = ax._make_client

    def _make(aid):
        made.append(aid)
        return real_make(aid)
    ax._make_client = _make
    try:
        walk = asyncio.create_task(vc.tick())
        await _until(lambda: any(c[3].get("limit") == 100 for c in FakeOF.calls))
        server._on_proxy_switched(["accX"])
        await asyncio.wait_for(walk, 2)
        n = len(FakeOF.calls)
        (run,) = await _runs("accX")
        assert run.status == "running" and run.error is None and run.phase.startswith("auto:all:"), (
            run.status, run.phase, run.error)
        assert sum(1 for c in FakeOF.calls if c[3].get("limit") == 100) < 4, "walk ran on after the switch"
        await asyncio.sleep(0.3)
        assert len(FakeOF.calls) == n, "old client kept calling OF"
        await vc.tick()
        assert made == ["accX", "accX"], made
        (run,) = await _runs("accX")
        assert (run.status, run.phase) == ("done", "auto:done"), (run.status, run.phase)
    finally:
        ax._make_client = real_make


async def case_page_cap_is_not_a_full_walk():
    await _reset("accCap", n=350)
    vc.WALK_MAX_PAGES = 2
    try:
        await vc.tick()
    finally:
        vc.WALK_MAX_PAGES = 200
    (run,) = await _runs("accCap")
    assert (run.status, run.phase, run.pages_done) == ("done", "auto:done", 2), (
        run.status, run.phase, run.pages_done)
    assert "capped" in (run.error or ""), run.error
    s = await vault_ai_api.cache_summary(account_id="accCap")
    assert s["complete"] is False, "a capped walk reported the vault complete"


async def case_capped_walk_after_full_walk_is_not_complete():
    """The vault outgrew the cap: an older uncapped walk (manual here) must not keep
    `complete` true once the newest walk was capped."""
    await _reset("accGrow", n=350)
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accGrow", status="done", phase="done", pages_done=3,
                            finished_at=datetime.utcnow() - timedelta(seconds=vc.FULL_S + 60)))
    assert (await vault_ai_api.cache_summary(account_id="accGrow"))["complete"] is True
    vc.WALK_MAX_PAGES = 2
    try:
        await vc.tick()
    finally:
        vc.WALK_MAX_PAGES = 200
    run = (await _runs("accGrow"))[-1]
    assert run.error == vault_runs.capped_error(2), run.error
    s = await vault_ai_api.cache_summary(account_id="accGrow")
    assert s["complete"] is False, "an older full walk kept a capped vault complete"


async def case_resume_after_capped_manual_walk_is_not_complete():
    """An auto row preempted mid-All by a manual Collect that ended capped: the resume
    skips All (walked recently) but did not walk the vault, so it must not end as the
    newest uncapped walk and turn `complete` back on."""
    await _reset("accPC", n=350)
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accPC", status="running", phase="auto:all:200",
                            pages_done=2, total_seen=200, upserted=200,
                            started_at=now - timedelta(minutes=10)))
        s.add(VaultCacheRun(account_id="accPC", status="done", phase="done", pages_done=200,
                            error=vault_runs.capped_error(200),
                            started_at=now - timedelta(minutes=5), finished_at=now - timedelta(minutes=1)))
    await vc.tick()
    assert not any(c[3].get("limit") == 100 for c in FakeOF.calls), "re-walked All"
    auto = [r for r in await _runs("accPC") if r.phase.startswith("auto:")]
    assert [(r.status, r.phase, r.pages_done) for r in auto] == [("done", "auto:done", 0)], (
        [(r.status, r.phase, r.pages_done) for r in auto])
    s = await vault_ai_api.cache_summary(account_id="accPC")
    assert s["complete"] is False, "a resume that skipped All made a capped vault complete"


async def case_error_or_preempt_clears_the_skip_streak():
    """Only a yield to a person keeps the MAX_SKIP_S streak; a walk that errors or is
    preempted (proxy switch / manual Collect) drops it, so the next retry is not forced."""
    await _reset("accSt", n=350, fail_at_offset=100)
    vc._skipped_since["accSt"] = time.monotonic() - 3600
    await vc.tick()
    (run,) = await _runs("accSt")
    assert run.status == "error", (run.status, run.phase)
    assert "accSt" not in vc._skipped_since, "an errored walk kept a stale streak"
    await _reset("accSt2", n=350)
    vc._skipped_since["accSt2"] = time.monotonic() - 3600
    walk = asyncio.create_task(vc.tick())
    await _until(lambda: any(c[3].get("limit") == 100 for c in FakeOF.calls))
    server._on_proxy_switched(["accSt2"])
    await asyncio.wait_for(walk, 2)
    (run,) = await _runs("accSt2")
    assert run.status == "running", (run.status, run.phase)
    assert "accSt2" not in vc._skipped_since, "a proxy-switch preempt kept a stale streak"


async def case_capped_walk_paused_in_thumbs_stays_capped():
    """The cap survives a pause in the thumbs phase (resume must not turn it into a
    full walk), and a capped vault is not re-walked from 0 every STALE_S."""
    await _reset("accCap2", n=350)
    vc.WALK_MAX_PAGES = 2
    try:
        walk = asyncio.create_task(vc.tick())
        await _until(lambda: len(_thumb_fetches) >= 1)
        _ACTIVE["accCap2"] = time.monotonic()        # a person arrives mid-thumbs
        await asyncio.wait_for(walk, 5)
        (run,) = await _runs("accCap2")
        assert (run.status, run.phase) == ("running", "auto:thumbs:capped"), (run.status, run.phase)
        _ACTIVE.clear()
        await vc.tick()                               # resumes the thumbs
        (run,) = await _runs("accCap2")
        assert (run.status, run.phase) == ("done", "auto:done") and "capped" in (run.error or ""), (
            run.status, run.phase, run.error)
        s = await vault_ai_api.cache_summary(account_id="accCap2")
        assert s["complete"] is False, "a capped walk resumed in thumbs reported the vault complete"
        async with get_session() as s:                # stale (6 h+) but within FULL_S
            r = await s.get(VaultCacheRun, run.id)
            r.finished_at = datetime.utcnow() - timedelta(seconds=vc.STALE_S + 60)
            await s.commit()
        FakeOF.calls.clear()
        await vc.tick()
        assert FakeOF.calls, "the stale hot set was not refreshed"
        assert not any(c[3].get("limit") == 100 for c in FakeOF.calls), "capped vault re-walked from 0"
    finally:
        vc.WALK_MAX_PAGES = 200


async def case_bad_folder_page_does_not_stop_the_walk():
    await _reset("accF")
    _CLIENTS["accF"] = FakeOF("accF", fail_folder=True)
    await vc.tick()
    (run,) = await _runs("accF")
    assert (run.status, run.phase, run.error, run.pages_done) == ("done", "auto:done", None, 3), (
        run.status, run.phase, run.error, run.pages_done)
    assert await _mirror_count("accF") == 250


async def case_thumb_workers_stop_together():
    """One worker's Preempted stops its sibling too: a sibling mid-fetch when the
    walk stops fetches nothing more after it returns (the walk drops its abort flag)."""
    await _reset("accTh")
    vc.THUMB_CONCURRENCY = 2
    _THUMB_DELAY[0] = 0.02
    _THUMB_HOLD_AT[0] = 2          # the second worker's first fetch hangs
    _THUMB_GATE.clear()
    try:
        walk = asyncio.create_task(vc.tick())
        await _until(lambda: len(_thumb_fetches) >= 4)
        vc._abort["accTh"].set()
        await asyncio.wait_for(walk, 2)
        n = len(_thumb_fetches)
        _THUMB_GATE.set()          # the held fetch returns after the walk is over
        await asyncio.sleep(0.3)
        assert len(_thumb_fetches) == n and n < 100, f"thumbs fetched on after the walk: {n} → {len(_thumb_fetches)}"
    finally:
        vc.THUMB_CONCURRENCY = 2
        _THUMB_DELAY[0] = 0.0
        _THUMB_HOLD_AT[0] = 0
        _THUMB_GATE.set()
    (run,) = await _runs("accTh")
    assert (run.status, run.phase) == ("running", "auto:thumbs"), (run.status, run.phase)


async def case_old_auto_runs_pruned():
    """A new auto run prunes the account's older ones past AUTO_RUNS_KEPT, never
    the newest full walk; `complete` and the weekly re-walk still see it."""
    await _reset("accPr")
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(VaultCacheRun(account_id="accPr", status="done", phase="auto:done", pages_done=3,
                            started_at=now - timedelta(days=3, minutes=1), finished_at=now - timedelta(days=3)))
        for i in range(15):
            t = now - timedelta(days=2) + timedelta(minutes=i)
            s.add(VaultCacheRun(account_id="accPr", status="done", phase="auto:done", pages_done=0,
                                started_at=t, finished_at=t))
        s.add(VaultCacheRun(account_id="accPr", status="done", phase="done", pages_done=3,
                            started_at=now - timedelta(days=9), finished_at=now - timedelta(days=9)))
    await vc.tick()
    runs = await _runs("accPr")
    auto = [r for r in runs if r.phase.startswith("auto:")]
    assert len(auto) == vault_runs.AUTO_RUNS_KEPT + 1, len(auto)
    assert any(r.pages_done == 3 for r in auto), "the newest full walk was pruned"
    assert any(r.phase == "done" for r in runs), "a manual run was pruned"
    assert not any(c[3].get("limit") == 100 for c in FakeOF.calls), "prune made the full walk look stale"
    s = await vault_ai_api.cache_summary(account_id="accPr")
    assert s["complete"] is True, s


async def case_calls_run_inside_an_of_pacing_walk():
    await _reset("accPace")
    await vc.tick()
    assert FakeOF.walks and set(FakeOF.walks) == {"vault_collect"}, set(FakeOF.walks)


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
