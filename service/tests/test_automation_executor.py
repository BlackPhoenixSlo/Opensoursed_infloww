#!/usr/bin/env python3
"""
T-EXEC — automation executor harness tests (library/MASTER_PLAN §5).

The 🔴 CARRY requirement: enqueue a scrape job → the executor runs it → an
automation_runs row appears with status=ok AND the messages land in the DB.
Plus the harness primitives every P4 automation depends on:

  case_scrape_job_persists_both_directions (the 🔴 requirement):
      enqueue_job → run_once → automation_runs status=ok, 3 messages persisted
      (BOTH directions — scrape knows the chat partner, unlike the WS pump which
      defers outbound), fans/chats/scrape_history written, job marked done.
  case_scrape_fast_skip:
      a second run with the scrape_history cursor already at the newest id
      inserts 0 (no dupes) and still records an ok run.
  case_scrape_all_chats_sweep:
      no chat_ids in the payload → list_chats sweep; withUser supplies identity.
  case_fan_lease_acquire_block_steal:
      a live lease blocks a second automation; an expired one can be stolen;
      release frees it. The per-(account, fan) send guard (one send per cycle).
  case_unknown_kind_errors:
      run_once for an unregistered kind writes an error run.
  case_unknown_kind_consumes_ghost_job:
      a leftover pending job for a retired kind errors ONCE and stops —
      never a re-dispatch-every-tick loop.
  case_supervisor_drain_runs_due_job:
      _drain_due_jobs_once() (one supervisor tick, no infinite loop) consumes a
      due job end-to-end.
  case_rule_materializes_job:
      a due automation_rule materializes exactly one scheduled_jobs row and does
      not duplicate while one is pending (rules enqueue, never run inline).

Run: ./venv/bin/python service/tests/test_automation_executor.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — module under test
import client_pool  # noqa: E402 — the OFClient pool behind ax._make_client
from automation_executor import (  # noqa: E402
    acquire_fan_lease,
    enqueue_job,
    release_fan_lease,
    run_once,
)
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AccountAiConfig,
    AutomationRule,
    AutomationRun,
    Chat,
    Fan,
    Message,
    ScheduledJob,
    ScrapeHistory,
)

# Our account's own OF user id — a message whose fromUser.id matches this is
# OUTBOUND (we sent it); anything else is inbound.
OWN_ID = "999"


# ── Fakes (no network, no session files) ─────────────────────────────

def _of_msg(
    mid: int, from_fan: bool, text: str, created: str, *, fan_id: int,
    price: float = 0, is_opened=None, is_tip: bool = False, media_count: int = 0,
    media: list | None = None,
) -> dict:
    """One OF /chats/{id}/messages row, shaped like the real REST payload."""
    if from_fan:
        from_user = {
            "id": fan_id, "username": "bob_fan", "name": "Bob",
            "avatar": "http://a/bob.jpg", "subscribedOn": True,
        }
    else:
        from_user = {"id": int(OWN_ID), "username": "me", "name": "Me"}
    return {
        "id": mid,
        "text": f"<p>{text}</p>",
        "price": price,
        "isOpened": is_opened,
        "isTip": is_tip,
        "mediaCount": media_count,
        "media": media or [],
        "fromUser": from_user,
        "createdAt": created,
    }


class FakeClient:
    """Stand-in for OFClient: serves canned message pages from memory. Single
    page per chat (hasMore=False); an older-cursor request returns empty."""

    def __init__(self, chats: dict[int, list[dict]], user_id: str = OWN_ID):
        self.user_id = user_id
        self._chats = {int(k): v for k, v in chats.items()}

    def list_chats(self, *, limit: int = 10, offset: int = 0,
                   order: str = "recent", **kw) -> dict:
        return {
            "list": [
                {"withUser": {
                    "id": cid, "username": f"sweep_{cid}", "name": f"Sweep {cid}",
                    "avatar": "http://a/sw.jpg", "subscribedOn": True,
                }}
                for cid in self._chats
            ],
            "hasMore": False,
        }

    def get_messages(self, chat_id, *, limit: int = 10, order: str = "desc",
                     before_id=None, **kw) -> dict:
        msgs = self._chats.get(int(chat_id), [])
        if before_id is None:
            return {"list": list(msgs), "hasMore": False}
        return {"list": [], "hasMore": False}


class PagedFakeClient:
    """A long convo that paginates like the REAL OF endpoint (probed live):

    - `limit` is IGNORED — every page returns FEWER rows than asked (so the
      loops can't rely on page size == limit).
    - desc: `before_id` is an "older than id" upper bound; pages BACKWARD.
    - asc + `offset`: pages FORWARD from the convo START (offset=0 = first msgs).
    """

    def __init__(self, chat_id: int, msgs: list[dict], *, user_id: str = OWN_ID,
                 page_rows: int = 13):
        self.user_id = user_id
        self.chat_id = int(chat_id)
        # Keep an ascending (oldest→newest) copy; ids are monotonic.
        self._asc = sorted(msgs, key=lambda m: m["id"])
        self.page_rows = page_rows  # what OF actually hands back, < any sane limit
        self.calls: list[tuple] = []  # (order, before_id, offset) for assertions

    def list_chats(self, **kw) -> dict:
        return {"list": [], "hasMore": False}

    def get_messages(self, chat_id, *, limit: int = 10, order: str = "desc",
                     before_id=None, offset=None, **kw) -> dict:
        self.calls.append((order, before_id, offset))
        n = min(self.page_rows, limit)  # OF returns fewer than `limit`
        if order == "asc":
            start = int(offset or 0)
            window = self._asc[start:start + n]
            has_more = start + n < len(self._asc)
            return {"list": list(window), "hasMore": has_more}
        # desc: newest first; `before_id` is an exclusive older-than bound.
        pool = [m for m in reversed(self._asc)
                if before_id is None or m["id"] < int(before_id)]
        window = pool[:n]
        return {"list": list(window), "hasMore": len(pool) > n}


class PagedListClient:
    """list_chats returns ≤10 per page (OF's real cap) and paginates by `offset`;
    get_messages hands back one inbound message per chat. Used to prove the sweep
    pages through ALL chats, not just the first 10."""

    def __init__(self, chat_ids: list[int], user_id: str = OWN_ID, page: int = 10):
        self.user_id = user_id
        self._ids = [int(c) for c in chat_ids]
        self._page = page
        self.offsets_requested: list[int] = []

    def list_chats(self, *, limit: int = 10, offset: int = 0,
                   order: str = "recent", **kw) -> dict:
        self.offsets_requested.append(offset)
        window = self._ids[offset:offset + self._page]
        return {
            "list": [{"withUser": {"id": cid, "username": f"u{cid}",
                                   "name": f"N{cid}", "subscribedOn": True}}
                     for cid in window],
            "hasMore": offset + self._page < len(self._ids),
        }

    def get_messages(self, chat_id, *, limit: int = 10, order: str = "desc",
                     before_id=None, offset=None, **kw) -> dict:
        if order == "asc" or before_id is not None:
            return {"list": [], "hasMore": False}
        cid = int(chat_id)
        return {"list": [_of_msg(cid * 10 + 1, True, "hi", "2026-06-03T10:00:00+00:00",
                                 fan_id=cid)], "hasMore": False}


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


def _use_fake(chats: dict[int, list[dict]]) -> None:
    """Override the OFClient construction seam for the current case."""
    fake = FakeClient(chats)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]


# ── 🔴 The carry requirement ─────────────────────────────────────────

async def case_scrape_job_persists_both_directions():
    aid, fan = "acc_scrape1", 2001
    await _seed_account(aid)
    _use_fake({fan: [
        _of_msg(5003, True, "hey there", "2026-06-01T10:00:00+00:00", fan_id=fan),
        _of_msg(5002, False, "hello!", "2026-06-01T09:59:00+00:00", fan_id=fan),
        _of_msg(5001, True, "hi", "2026-06-01T09:58:00+00:00", fan_id=fan),
    ]})

    job_id = await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    res = await run_once(aid, "scrape_chats")

    assert res["status"] == "ok", res
    assert res["job_id"] == job_id, res
    assert res["messages_inserted"] == 3, res
    assert res["messages_seen"] == 3, res

    async with get_session() as s:
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1, f"one run row, got {len(runs)}"
        assert runs[0].status == "ok", runs[0].status
        assert runs[0].kind == "scrape_chats"
        assert runs[0].completed_at is not None, "completed_at stamped"
        stats = json.loads(runs[0].stats_json)
        assert stats["messages_inserted"] == 3 and stats["chats_scanned"] == 1, stats
        assert "duration_ms" in stats, "duration recorded"

        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all()
        assert len(msgs) == 3, f"three messages persisted, got {len(msgs)}"
        # Outbound is persisted too — the scrape knows the partner (fan_id=chat).
        assert sorted(m.direction for m in msgs) == ["in", "in", "out"], \
            [m.direction for m in msgs]

        job = await s.get(ScheduledJob, job_id)
        assert job.status == "done", f"job marked done, got {job.status}"

        chat = await s.get(Chat, (aid, fan))
        assert chat is not None and chat.last_message_id == 5003, chat
        assert "hey there" in (chat.last_message_preview or ""), chat.last_message_preview

        hist = await s.get(ScrapeHistory, (aid, fan))
        assert hist is not None and hist.last_message_id == 5003, "scrape cursor advanced"

        f = await s.get(Fan, (aid, fan))
        assert f is not None, "fan row created"
        assert f.of_username == "bob_fan" and f.of_display_name == "Bob", \
            (f.of_username, f.of_display_name)


# ── Fast-skip: second run inserts nothing ────────────────────────────

async def case_scrape_fast_skip():
    aid, fan = "acc_scrape2", 2002
    await _seed_account(aid)
    _use_fake({fan: [
        _of_msg(6002, True, "yo", "2026-06-02T10:00:00+00:00", fan_id=fan),
        _of_msg(6001, True, "sup", "2026-06-02T09:59:00+00:00", fan_id=fan),
    ]})

    await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    r1 = await run_once(aid, "scrape_chats")
    assert r1["messages_inserted"] == 2, r1

    # Second run: scrape_history cursor is at 6002, so nothing is newer.
    await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    r2 = await run_once(aid, "scrape_chats")
    assert r2["status"] == "ok", r2
    assert r2["messages_inserted"] == 0, r2
    assert r2["messages_seen"] == 0, r2

    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all()
        assert len(msgs) == 2, f"no duplicates, got {len(msgs)}"
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 2 and all(r.status == "ok" for r in runs), \
            [r.status for r in runs]


# ── All-chats sweep (list_chats path) ────────────────────────────────

async def case_scrape_all_chats_sweep():
    aid, fan_a, fan_b = "acc_scrape3", 3001, 3002
    await _seed_account(aid)
    _use_fake({
        fan_a: [_of_msg(7001, True, "from A", "2026-06-03T10:00:00+00:00", fan_id=fan_a)],
        fan_b: [_of_msg(7002, True, "from B", "2026-06-03T10:01:00+00:00", fan_id=fan_b)],
    })

    await enqueue_job(aid, "scrape_chats", payload={})  # no chat_ids → sweep
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["chats_scanned"] == 2, res
    assert res["messages_inserted"] == 2, res

    async with get_session() as s:
        fa = await s.get(Fan, (aid, fan_a))
        assert fa is not None and fa.of_username == "sweep_3001", \
            "identity lifted from withUser in the sweep"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 2, len(msgs)


# ── Sweep paginates list_chats (10/page) — covers ALL chats, not just 10 ──

async def case_scrape_sweep_paginates_all_chats():
    aid = "acc_scrape_pg"
    await _seed_account(aid)
    chat_ids = list(range(4001, 4024))  # 23 chats → 3 pages of 10/10/3
    fake = PagedListClient(chat_ids)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    await enqueue_job(aid, "scrape_chats", payload={})  # no ids → paginated sweep
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["chats_scanned"] == 23, res            # all three pages, not just 10
    assert fake.offsets_requested == [0, 10, 20], fake.offsets_requested
    async with get_session() as s:
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid)
        )).scalars().all()
        assert len(msgs) == 23, len(msgs)


# ── Long convo: both ends (asc-forward + desc-backward), never the middle ──

async def case_scrape_long_convo_both_ends():
    """First scrape of a 200-message convo grabs the OLDEST end (asc/offset
    forward from the start) AND the RECENT end (desc/before_id backward), skips
    the bounded middle, and persists ~100 — never thousands."""
    aid, fan = "acc_long", 5100
    await _seed_account(aid)
    # ids 1..200 ascending; even ids inbound (from fan), odd outbound.
    msgs = [
        _of_msg(i, from_fan=(i % 2 == 0), text=f"m{i}",
                created=f"2026-06-01T00:{i // 60:02d}:{i % 60:02d}+00:00", fan_id=fan)
        for i in range(1, 201)
    ]
    fake = PagedFakeClient(fan, msgs)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    await enqueue_job(aid, "scrape_chats",
                      payload={"chat_ids": [fan], "recent_cap": 50, "oldest_cap": 50})
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    # Bounded: ~recent_cap + oldest_cap, with a small page-overshoot — NOT 200.
    assert res["messages_inserted"] <= 110, res
    assert res["messages_inserted"] >= 90, res

    # Both paging directions were exercised.
    orders = {o for (o, _bid, _off) in fake.calls}
    assert orders == {"desc", "asc"}, fake.calls
    assert any(off == 0 for (_o, _bid, off) in fake.calls if _o == "asc"), \
        "oldest end started at offset=0"

    async with get_session() as s:
        ids = sorted(m.message_id for m in (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all())
        assert ids[0] == 1, f"convo START (id 1) persisted, got {ids[0]}"
        assert ids[-1] == 200, f"convo END (id 200) persisted, got {ids[-1]}"
        assert 100 not in ids, "the middle is intentionally skipped"
        assert len(ids) <= 110, f"never thousands, got {len(ids)}"

        hist = await s.get(ScrapeHistory, (aid, fan))
        assert hist.last_message_id == 200, "fast-skip cursor at the newest id"


async def case_scrape_desc_catch_up_no_refetch_start():
    """A SUBSEQUENT scrape (history cursor already set) only pages the recent
    end BACKWARD until it meets the cursor — it does NOT re-pull the convo
    start, even though the convo is long."""
    aid, fan = "acc_catchup", 5200
    await _seed_account(aid)
    msgs = [
        _of_msg(i, from_fan=(i % 2 == 0), text=f"m{i}",
                created=f"2026-06-02T00:{i // 60:02d}:{i % 60:02d}+00:00", fan_id=fan)
        for i in range(1, 201)
    ]
    fake = PagedFakeClient(fan, msgs)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    # Pretend we already scraped up to id 180.
    async with get_session() as s:
        s.add(ScrapeHistory(account_id=aid, fan_id=fan, last_message_id=180,
                            last_message_text="m180"))

    await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    res = await run_once(aid, "scrape_chats")
    assert res["status"] == "ok", res
    assert res["messages_inserted"] == 20, res  # ids 181..200 only

    # Pure desc catch-up — the asc/offset start-pull never fired.
    assert all(o == "desc" for (o, _bid, _off) in fake.calls), fake.calls

    async with get_session() as s:
        ids = sorted(m.message_id for m in (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all())
        assert ids == list(range(181, 201)), ids
        assert 1 not in ids, "convo start was NOT re-fetched on a catch-up"


# ── Per-(account, fan) lease primitive ───────────────────────────────

async def case_fan_lease_acquire_block_steal():
    aid = "acc_lease"

    # Fresh fan: first acquire wins.
    assert await acquire_fan_lease(aid, 7777, "welcome_chatter_for_info", ttl_s=60) is True, "fresh acquire"
    # A live lease blocks a different automation.
    assert await acquire_fan_lease(aid, 7777, "send_followup", ttl_s=60) is False, \
        "live lease blocks a second automation"
    # Releasing frees it.
    await release_fan_lease(aid, 7777)
    assert await acquire_fan_lease(aid, 7777, "send_followup", ttl_s=60) is True, \
        "acquire after release"

    # Expired-lease steal path: a TTL in the past is immediately stealable.
    assert await acquire_fan_lease(aid, 8888, "welcome_chatter_for_info", ttl_s=-5) is True, "insert expired"
    assert await acquire_fan_lease(aid, 8888, "reply_mass_funnel", ttl_s=60) is True, \
        "steal an expired lease"
    assert await acquire_fan_lease(aid, 8888, "send_welcome", ttl_s=60) is False, \
        "the freshly-stolen lease is now live and blocks"


# ── W3: per-fan post-send cooldown ───────────────────────────────────

async def case_fan_cooldown_set_check_expire():
    aid = "acc_cooldown"
    await _seed_account(aid)

    # No fans row yet → start_fan_cooldown UPSERTs one and the fan reads paused.
    assert await ax.fan_on_cooldown(aid, 5101) is False, "no row → not on cooldown"
    until = await ax.start_fan_cooldown(aid, 5101)
    assert await ax.fan_on_cooldown(aid, 5101) is True, "fresh cooldown is active"
    async with get_session() as s:
        f = await s.get(Fan, (aid, 5101))
        assert f is not None and f.automation_paused_until == until, "upserted the pause"

    # A cooldown that already lapsed reads as not-on-cooldown (no negative latch).
    await ax.start_fan_cooldown(aid, 5101, cooldown_s=-5)
    assert await ax.fan_on_cooldown(aid, 5101) is False, "expired cooldown clears"


# ── W3: dispatch priority ranking ────────────────────────────────────

async def case_kind_priority_ordering():
    order = [
        "send_welcome", "welcome_chatter_for_info",
        "send_followup", "reply_mass_funnel", "send_mass_message",
    ]
    ranks = [ax.kind_priority(k) for k in order]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks), ranks
    # Unknown kinds sort AFTER every ranked sender (lower priority).
    assert ax.kind_priority("totally_unknown") > ranks[-1], ax.kind_priority("totally_unknown")


async def case_supervisor_dispatches_high_priority_first():
    """A due welcome + followup for one account in one tick must DISPATCH welcome
    first (so on the rare fan overlap the new sub gets welcomed, not followed-up)."""
    aid = "acc_prio"
    await _seed_account(aid)
    # Enqueue lowest→highest on purpose; the supervisor must reorder by priority.
    await enqueue_job(aid, "send_followup", payload={})
    await enqueue_job(aid, "welcome_chatter_for_info", payload={})
    await enqueue_job(aid, "send_welcome", payload={})

    dispatched: list[str] = []
    orig = ax.run_once

    async def _record(account_id, kind, **kw):
        dispatched.append(kind)  # recorded at task start, before any await → creation order
        return {"status": "ok"}

    ax.run_once = _record  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()  # drain now spawns detached tasks — await them
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]

    assert dispatched[:3] == ["send_welcome", "welcome_chatter_for_info", "send_followup"], dispatched


async def case_supervisor_dispatches_least_recently_served_account_first():
    """Within one priority rank, the account that won a run slot longest ago is
    dispatched first — not account-id order, which put the same high-id
    creators last on every busy tick at 20 accounts."""
    a_low, z_high = "acc_lrs_a", "acc_lrs_z"
    for aid in (a_low, z_high):
        await _seed_account(aid)
        await enqueue_job(aid, "send_followup", payload={})
    # `a` was served just now, `z` never: `z` goes first despite sorting after.
    ax._last_served[a_low] = asyncio.get_running_loop().time()
    ax._last_served.pop(z_high, None)

    dispatched: list[str] = []
    orig = ax.run_once

    async def _record(account_id, kind, **kw):
        if account_id in (a_low, z_high):
            dispatched.append(account_id)
        return {"status": "ok"}

    ax.run_once = _record  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]

    assert dispatched == [z_high, a_low], dispatched
    assert ax._last_served[z_high] <= ax._last_served[a_low], (
        "winning a slot must stamp the account as served")


async def _employees() -> tuple[int, int]:
    """(an operator's employee id, the system Automation employee's id)."""
    from db.models import Employee
    from employees import get_automation_employee_id
    async with get_session() as s:
        op = Employee(display_name="op_tier")
        s.add(op)
        await s.flush()
        op_id = op.id
    try:
        auto_id = await get_automation_employee_id()
    except LookupError:
        async with get_session() as s:
            auto = Employee(display_name="Automation", is_active=False)
            s.add(auto)
            await s.flush()
            auto_id = auto.id
    return op_id, auto_id


async def case_an_operators_job_dispatches_first_in_the_operator_tier():
    """ADR 0025 fix 2: a job the app stamped with the acting employee (Run now,
    a premade mass, a scheduled send, an unsend) is an operator's. Its run is
    spawned before every automation run, whatever the kind priority, and takes
    its slot in the operator tier. A job automation stamped with the Automation
    employee (auto_posts' delete) is still automation."""
    op_id, auto_id = await _employees()
    a_op, a_auto, a_sys = "acc_tier_op", "acc_tier_auto", "acc_tier_sys"
    for a in (a_op, a_auto, a_sys):
        await _seed_account(a)
    await enqueue_job(a_auto, "send_welcome", payload={})                 # top kind priority
    await enqueue_job(a_sys, "unsend_messages", payload={}, created_by_employee_id=auto_id)
    await enqueue_job(a_op, "unsend_messages", payload={}, created_by_employee_id=op_id)

    pairs = {(a, k): op for a, k, op in await ax._due_job_pairs()}
    assert pairs[(a_op, "unsend_messages")] is True, pairs
    assert pairs[(a_auto, "send_welcome")] is False, pairs
    assert pairs[(a_sys, "unsend_messages")] is False, ("the Automation employee is not an operator", pairs)

    seen: list[tuple[str, bool]] = []
    orig = ax.run_once

    async def _record(account_id, kind, **kw):
        if account_id.startswith("acc_tier_"):
            seen.append((account_id, ax.run_slot.current().operator))
        return {"status": "ok"}

    ax.run_once = _record  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]
    assert seen[0] == (a_op, True), seen
    assert dict(seen) == {a_op: True, a_auto: False, a_sys: False}, seen
    async with get_session() as s:   # the fake never claimed them: no later drain runs them
        await s.execute(ScheduledJob.__table__.update()
                        .where(ScheduledJob.account_id.in_([a_op, a_auto, a_sys]))
                        .values(status="done"))


async def case_run_now_on_an_automation_kind_is_rate_limited_as_automation():
    """Review fix 4: the tier is the run's KIND, not who clicked. An operator's
    Run now on autoreply (stamped with his employee, like every
    session-enqueued one-shot) is automation's work: its pair is not the
    operator tier, and its run's DMs queue for the account's DM rate (limit 1:
    the second waits) while an operator kind's (an unsend he started) pass."""
    import dm_rate
    import os
    op_id, _auto_id = await _employees()
    a_ar, a_uns = "acc_tier_runnow", "acc_tier_runnow_uns"
    for a in (a_ar, a_uns):
        await _seed_account(a)
    await enqueue_job(a_ar, "autoreply", payload={}, created_by_employee_id=op_id)
    await enqueue_job(a_uns, "unsend_messages", payload={}, created_by_employee_id=op_id)
    pairs = {(a, k): op for a, k, op in await ax._due_job_pairs()}
    assert pairs[(a_ar, "autoreply")] is False, ("Run now made autoreply an operator run", pairs)
    assert pairs[(a_uns, "unsend_messages")] is True, pairs

    saved_env, saved_w, saved_s = os.environ.get(dm_rate.KNOB), dm_rate.WINDOW_S, dm_rate.SLACK_S
    os.environ[dm_rate.KNOB] = "1"
    dm_rate.WINDOW_S, dm_rate.SLACK_S = 0.2, 0.0
    dm_rate._reset()
    waited: dict[str, list[float]] = {}
    orig = ax.run_once

    async def _run(account_id, kind, **kw):        # two DMs of the run, each a turn then the send
        if account_id in (a_ar, a_uns):
            for _ in range(2):
                waited.setdefault(account_id, []).append(await dm_rate.turn(account_id))
                dm_rate.record(account_id)
        return {"status": "ok"}
    ax.run_once = _run  # type: ignore[attr-defined]
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax.run_once = orig  # type: ignore[attr-defined]
        dm_rate.WINDOW_S, dm_rate.SLACK_S = saved_w, saved_s
        dm_rate._reset()
        if saved_env is None:
            os.environ.pop(dm_rate.KNOB, None)
        else:
            os.environ[dm_rate.KNOB] = saved_env
        async with get_session() as s:
            await s.execute(ScheduledJob.__table__.update()
                            .where(ScheduledJob.account_id.in_([a_ar, a_uns])).values(status="done"))
    assert waited[a_ar][0] == 0.0 and waited[a_ar][1] > 0, ("Run now's DMs bypassed the limiter", waited)
    assert waited[a_uns] == [0.0, 0.0], ("an operator kind's DMs waited", waited)


async def case_the_claim_takes_the_operators_job_first():
    """Two due jobs of one (account, kind): the run claims the operator's even
    though automation's has waited longer — the slot was taken for it."""
    op_id, auto_id = await _employees()
    aid = "acc_tier_claim"
    await _seed_account(aid)
    old = datetime.utcnow() - timedelta(minutes=5)
    j_auto = await enqueue_job(aid, "unsend_messages", payload={}, run_at=old,
                               created_by_employee_id=auto_id)
    j_bare = await enqueue_job(aid, "unsend_messages", payload={}, run_at=old)
    j_op = await enqueue_job(aid, "unsend_messages", payload={}, created_by_employee_id=op_id)
    order = [(await ax._claim_due_job(aid, "unsend_messages")).id for _ in range(3)]
    assert order[0] == j_op, (order, j_op)
    assert set(order[1:]) == {j_auto, j_bare}, order


async def case_the_run_slots_size_from_the_active_creators():
    """ADR 0025 fix 4: with no override the pool follows run_slot.auto_runs of
    the active Creators, live: 30 more Creators grow it, deactivating them
    shrinks it back; the panel's row shows the size as default and live, not
    a pending restart. The env (or a stored panel value) pins it."""
    import os
    import account_health
    import lane_config
    import run_slot
    knob = "AUTOMATION_MAX_CONCURRENT_RUNS"
    assert not lane_config.overridden(knob)
    pool = run_slot.SlotPool(4)
    await ax._size_run_slots(pool)
    base = await ax._active_models()
    assert pool.n == run_slot.auto_runs(base), (pool.n, base)
    extra = [f"acc_size_{i}" for i in range(max(0, 51 - base))]
    for a in extra:
        await _seed_account(a)
    await ax._size_run_slots(pool)
    assert pool.n == run_slot.auto_runs(base + len(extra)) == 7, (pool.n, base, len(extra))
    row = next(r for r in lane_config.describe() if r["name"] == knob)
    assert row["live"] == row["value"] == row["default"] == 7 and not row["pending"], row
    for a in extra[:20]:
        await account_health.deactivate(a)
    await ax._size_run_slots(pool)
    assert pool.n == run_slot.auto_runs(base + len(extra) - 20), (pool.n, base)
    os.environ[knob] = "9"
    try:
        for a in extra[20:]:
            await account_health.deactivate(a)
        n_before = pool.n
        await ax._size_run_slots(pool)
        assert pool.n == n_before, ("an env-pinned pool was resized", pool.n)
    finally:
        del os.environ[knob]
    await ax._size_run_slots(pool)
    assert pool.n == run_slot.auto_runs(base), (pool.n, base)


# ── Client pool: one client per account, evictable ───────────────────
#
# Tested against client_pool directly, not through ax._make_client — the seam
# is a one-line delegate now, and the cases above rebind it to a fake without
# restoring it.

async def case_client_pool_reuses_and_evicts():
    """A client per call leaked a curl fd per call → EMFILE in prod. Pin it,
    but keep it evictable: the dead-session probe depends on eviction to pick
    up a re-captured session, and a proxy edit depends on it to stop dialing
    the old host."""
    class _StubClient:
        user_id = "u1"
        x_of_rev = "rev1"

    class _Stub:
        @staticmethod
        def from_account(account_id: str):
            return _StubClient()

    real_of_client, client_pool.OFClient = client_pool.OFClient, _Stub  # type: ignore[assignment]
    try:
        client_pool.evict()
        first = client_pool.get("acc_pool")
        assert client_pool.get("acc_pool") is first, "same account → same client"
        assert client_pool.get("acc_other") is not first, "pool is per account"
        client_pool.evict("acc_pool")
        assert client_pool.get("acc_pool") is not first, "evict → rebuilt from disk"
        client_pool.evict()
        assert client_pool.get("acc_other") is not first, "evict(None) → all accounts"
    finally:
        client_pool.OFClient = real_of_client  # type: ignore[assignment]
        client_pool.evict()


# ── Unknown kind → error run, and the bound job is CONSUMED ──────────

async def case_unknown_kind_errors():
    res = await run_once("acc_unknown", "does_not_exist")
    assert res["status"] == "error", res
    assert res["reason"] == "unknown_kind", res
    async with get_session() as s:
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == "acc_unknown")
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "error", runs
        assert runs[0].error_text and "unknown" in runs[0].error_text.lower()


async def case_unknown_kind_consumes_ghost_job():
    """A leftover pending job for a retired kind must error ONCE and stop —
    left pending, the supervisor re-dispatches it every 30s tick forever
    (error-run noise + automation_runs bloat on a DB with bloat guards)."""
    aid = "acc_ghost_job"
    await _seed_account(aid)
    job_id = await enqueue_job(aid, "retired_ghost_kind", payload={})
    res = await run_once(aid, "retired_ghost_kind")
    assert res["status"] == "error" and res["reason"] == "unknown_kind", res
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.status == "error", f"ghost job must be consumed, got {job.status}"
        assert "unknown" in (job.last_error or "").lower(), job.last_error
    # And a second dispatch finds nothing to do — no error-run-per-tick loop.
    res2 = await run_once(aid, "retired_ghost_kind")
    async with get_session() as s:
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
    assert len(runs) == 2, runs  # each explicit call errs, but no job re-loops
    async with get_session() as s:
        pending = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid,
                                       ScheduledJob.status == "pending")
        )).scalars().all()
    assert not pending, pending


# ── Supervisor tick consumes a due job (no infinite loop) ────────────

async def case_supervisor_drain_runs_due_job():
    aid, fan = "acc_super", 4001
    await _seed_account(aid)
    _use_fake({fan: [_of_msg(8001, True, "drained", "2026-06-04T10:00:00+00:00", fan_id=fan)]})

    job_id = await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [fan]})
    await ax._drain_due_jobs_once()
    await ax._join_inflight_runs()  # drain now spawns detached tasks — await them

    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.status == "done", f"drain consumed the job, got {job.status}"
        msgs = (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan)
        )).scalars().all()
        assert len(msgs) == 1, len(msgs)
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert len(runs) == 1 and runs[0].status == "ok", runs


# ── automation_rules → scheduled_jobs materialization ────────────────

async def case_rule_materializes_job():
    aid = "acc_rule"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="periodic scrape", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [5555]}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"a due rule materialized at least one job, got {n}"

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "scrape_chats",
                ScheduledJob.status == "pending",
            )
        )).scalars().all()
        assert len(jobs) == 1, f"exactly one job, got {len(jobs)}"
        assert json.loads(jobs[0].payload_json) == {"chat_ids": [5555]}, jobs[0].payload_json
        assert jobs[0].rule_id is not None, "job links back to the rule"

    # A second pass must not pile on while a job is still pending.
    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending"
            )
        )).scalars().all()
        assert len(jobs) == 1, "no duplicate while a pending job exists"


async def case_rule_with_unregistered_kind_stays_inert():
    """A rule whose kind has no registered runner must NOT materialize a job —
    it could only ever produce an unknown-kind ERROR run every tick. This is
    the guard that lets a retired engine's leftover prod rules sit inert until
    they are deleted, instead of forcing rules-then-code deploy ordering.
    Checked against the runner REGISTRY, never a hand-kept kind list."""
    aid = "acc_rule_ghost"
    await _seed_account(aid)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="retired engine", kind="ghost_kind",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({}),
            is_enabled=True,
        ))

    await ax._materialize_due_rules()

    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(ScheduledJob.account_id == aid)
        )).scalars().all()
        assert jobs == [], f"unregistered kind must not enqueue, got {jobs}"
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()
        assert runs == [], f"and no error runs either, got {runs}"


async def case_future_oneshot_does_not_starve_rule():
    """Regression: a future-dated one-shot of the SAME (account, kind) — e.g.
    auto_stories' delete-later cleanup, which rides on `unsend_messages` — must
    NOT block a recurring rule from materializing. Before the fix the
    (account, kind) pending-guard counted the future cleanup and starved the
    rule indefinitely."""
    aid = "acc_starve"
    await _seed_account(aid)
    # A future-dated one-shot cleanup (rule_id=None), due in 6h.
    await enqueue_job(
        aid, "unsend_messages",
        payload={"targets": [{"story_id": 42}]},
        run_at=datetime.utcnow() + timedelta(hours=6),
    )
    # An enabled hourly mass-unsend RULE for the same (account, kind).
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="auto-unsend mass", kind="unsend_messages",
            trigger_json=json.dumps({"every_seconds": 3600}),
            steps_json=json.dumps({"policy": {"mass_text_hours": 4}}),
            is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule must materialize despite the future cleanup, got {n}"

    async with get_session() as s:
        due = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.status == "pending",
                ScheduledJob.run_at <= datetime.utcnow(),
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(due) == 1, f"the rule's own due job exists, got {len(due)}"

    # The rule's own due job now blocks a second pass (anti-pile still works).
    await ax._materialize_due_rules()
    async with get_session() as s:
        rule_jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(rule_jobs) == 1, "no duplicate of the rule's due job"


async def case_rule_quiet_hours_holds_job():
    """A due rule whose creator-local quiet band covers NOW does not enqueue. The
    band is built around the account's LOCAL hour so the test is deterministic.

    The clock is +3 here, and it is stored as a real one — the band is creator-local,
    so a test that leaves the account clockless is not testing the feature. That is
    what this used to do: no AccountAiConfig at all, the executor read the raw column,
    the missing value became 0, and the band was evaluated in UTC. It passed because
    the server clock stood in for hers."""
    aid = "acc_quiet_in"
    await _seed_account(aid)
    off = 3
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=off))
    h = (datetime.utcnow().hour + off) % 24          # HER hour, not the server's
    band = [(h - 1) % 24, (h + 2) % 24]   # 3h window that includes h (wrap-safe)
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="quiet scrape", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [1]}),
            quiet_hours_json=json.dumps(band), is_enabled=True,
        ))

    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
        )).scalars().all()
    assert jobs == [], f"quiet-hours rule must NOT enqueue, got {len(jobs)}"


async def case_rule_quiet_hours_outside_band_materializes():
    """The gate is conditional: a quiet band that does NOT cover now still lets the
    rule materialize (and proves quiet hours don't break normal scheduling)."""
    aid = "acc_quiet_out"
    await _seed_account(aid)
    off = 3
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=off))
    h = (datetime.utcnow().hour + off) % 24          # HER hour, not the server's
    band = [(h + 3) % 24, (h + 5) % 24]   # 2h window that excludes h
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="awake scrape", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [2]}),
            quiet_hours_json=json.dumps(band), is_enabled=True,
        ))

    n = await ax._materialize_due_rules()
    assert n >= 1, "rule outside its quiet band must still materialize"
    async with get_session() as s:
        jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending")
        )).scalars().all()
    assert len(jobs) == 1, f"exactly one job, got {len(jobs)}"


async def case_quiet_hours_never_run_on_the_server_clock():
    """Two properties of the ONE clock, both of which used to fail silently.

    1. An account with NO clock cannot have a creator-local band evaluated. It used
       to get one anyway: the raw column read as 0 and the band ran on UTC — the
       VPS's own time, presented as hers. It now does not apply (and logs).
    2. An account carrying BOTH clock columns uses the offset, the value the Brain
       dropdown writes — not the IANA zone sitting next to it. Here the two are 9h
       apart, so a band built around the OFFSET's hour would be outside the zone's.
    """
    # 1 — no clock at all → the band cannot hold the job.
    aid = "acc_quiet_noclock"
    await _seed_account(aid)
    h = datetime.utcnow().hour
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="clockless", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [3]}),
            quiet_hours_json=json.dumps([(h - 1) % 24, (h + 2) % 24]),
            is_enabled=True))
    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.status == "pending"))).scalars().all()
    assert len(jobs) == 1, "a clockless account has no local band to be inside"

    # 2 — both columns → the OFFSET is the clock.
    aid2 = "acc_quiet_bothclocks"
    await _seed_account(aid2)
    off = 3
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid2, utc_offset=off,
                              timezone="America/Los_Angeles"))   # ~10h from +3
    her_h = (datetime.utcnow().hour + off) % 24
    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid2, name="two clocks", kind="scrape_chats",
            trigger_json=json.dumps({"every_seconds": 1}),
            steps_json=json.dumps({"chat_ids": [4]}),
            quiet_hours_json=json.dumps([(her_h - 1) % 24, (her_h + 2) % 24]),
            is_enabled=True))
    await ax._materialize_due_rules()
    async with get_session() as s:
        jobs = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid2, ScheduledJob.status == "pending"))).scalars().all()
    assert jobs == [], "the band around the OFFSET's hour must hold the job"


async def case_oneshot_runs_dont_reset_rule_cadence():
    """Regression: frequent one-shot RUNS of the same (account, kind) — manual
    "Unsend this" clicks, auto_stories cleanups, test drivers — must NOT keep a
    recurring interval rule perpetually "not due." The cadence anchors on the
    rule's OWN enqueues (rule_id), not on the last AutomationRun of the kind.
    Before the fix the rule never fired once because a one-shot ran more often
    than the rule's interval, resetting last_started every time."""
    aid = "acc_cadence"
    await _seed_account(aid)
    # Simulate a one-shot run of the SAME kind that just finished (≠ this rule).
    await ax._open_run(aid, "unsend_messages")  # writes an AutomationRun started "now"

    async with get_session() as s:
        s.add(AutomationRule(
            account_id=aid, name="auto-unsend mass", kind="unsend_messages",
            trigger_json=json.dumps({"every_seconds": 3600}),
            steps_json=json.dumps({"policy": {"mass_text_hours": 4}}),
            is_enabled=True,
        ))

    # Even though an unsend_messages run happened seconds ago, the rule has never
    # enqueued its OWN job, so it is due now.
    n = await ax._materialize_due_rules()
    assert n >= 1, f"rule must materialize despite a recent one-shot run, got {n}"
    async with get_session() as s:
        rule_jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(rule_jobs) == 1, f"the rule enqueued its own job, got {len(rule_jobs)}"

    # A second pass right away must NOT re-enqueue (its own job anchors cadence).
    await ax._materialize_due_rules()
    async with get_session() as s:
        rule_jobs = (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid,
                ScheduledJob.kind == "unsend_messages",
                ScheduledJob.rule_id.isnot(None),
            )
        )).scalars().all()
        assert len(rule_jobs) == 1, "interval holds — no duplicate within the window"


async def case_clock_rule_not_starved_by_same_kind_run():
    """Regression (clock trigger): a daily_at ("HH:MM") rule must fire its slot
    even when an unrelated one-shot RUN of the same (account, kind) happened AFTER
    that slot. Before the fix the clock path anchored on the kind's last
    AutomationRun, so a manual / cleanup / test run after the slot marked it
    "already ran" and the scheduled rule was silently skipped — the same footgun
    the interval path already guards. The anchor is now the rule's OWN enqueues."""
    aid = "acc_clock_cadence"
    await _seed_account(aid)

    # Freeze the executor clock so the slot math is midnight-safe and independent
    # of when the suite runs. A PAST date keeps real ScheduledJob.created_at well
    # after the slot, so the no-duplicate second pass is deterministic too.
    fixed_now = datetime(2020, 1, 1, 12, 0, 0)
    real_dt = ax.datetime

    class _Frozen(real_dt):  # type: ignore[misc, valid-type]
        @classmethod
        def utcnow(cls):
            return fixed_now

    # A same-kind one-shot that RAN at 11:30 — AFTER the 11:00 slot. Under the old
    # (buggy) anchor this run alone suppressed the rule for the whole day.
    async with get_session() as s:
        s.add(AutomationRun(
            account_id=aid, kind="auto_stories",
            started_at=datetime(2020, 1, 1, 11, 30, 0),
            completed_at=datetime(2020, 1, 1, 11, 30, 5),
            status="ok",
        ))
        s.add(AutomationRule(
            account_id=aid, name="daily story", kind="auto_stories",
            trigger_json=json.dumps({"daily_at": ["11:00"], "tz_offset_minutes": 0}),
            steps_json=json.dumps({}),
            is_enabled=True,
        ))

    ax.datetime = _Frozen  # type: ignore[assignment]
    try:
        n = await ax._materialize_due_rules()
        assert n >= 1, f"daily_at slot must fire despite a later same-kind run, got {n}"
        async with get_session() as s:
            jobs = (await s.execute(
                select(ScheduledJob).where(
                    ScheduledJob.account_id == aid,
                    ScheduledJob.kind == "auto_stories",
                    ScheduledJob.rule_id.isnot(None),
                )
            )).scalars().all()
            assert len(jobs) == 1, f"exactly one job from the slot, got {len(jobs)}"

        # Same slot, immediately again → no duplicate (its own pending job holds it).
        await ax._materialize_due_rules()
        async with get_session() as s:
            jobs = (await s.execute(
                select(ScheduledJob).where(
                    ScheduledJob.account_id == aid,
                    ScheduledJob.kind == "auto_stories",
                    ScheduledJob.rule_id.isnot(None),
                )
            )).scalars().all()
            assert len(jobs) == 1, "slot fires once per day — no duplicate"
    finally:
        ax.datetime = real_dt  # type: ignore[assignment]


_harness.run(
    case_scrape_job_persists_both_directions,
    case_scrape_fast_skip,
    case_scrape_all_chats_sweep,
    case_scrape_sweep_paginates_all_chats,
    case_scrape_long_convo_both_ends,
    case_scrape_desc_catch_up_no_refetch_start,
    case_fan_lease_acquire_block_steal,
    case_fan_cooldown_set_check_expire,
    case_kind_priority_ordering,
    case_supervisor_dispatches_high_priority_first,
    case_supervisor_dispatches_least_recently_served_account_first,
    case_an_operators_job_dispatches_first_in_the_operator_tier,
    case_the_claim_takes_the_operators_job_first,
    case_run_now_on_an_automation_kind_is_rate_limited_as_automation,
    case_the_run_slots_size_from_the_active_creators,
    case_client_pool_reuses_and_evicts,
    case_unknown_kind_errors,
    case_unknown_kind_consumes_ghost_job,
    case_supervisor_drain_runs_due_job,
    case_rule_materializes_job,
    case_rule_with_unregistered_kind_stays_inert,
    case_future_oneshot_does_not_starve_rule,
    case_oneshot_runs_dont_reset_rule_cadence,
    case_clock_rule_not_starved_by_same_kind_run,
    case_rule_quiet_hours_holds_job,
    case_rule_quiet_hours_outside_band_materializes,
    case_quiet_hours_never_run_on_the_server_clock,
)
