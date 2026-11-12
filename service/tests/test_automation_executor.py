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
  case_scrape_full_sweep_mark_only_on_empty_payload:
      only a `{}` run stamps full_sweep (sweep_cadence's anchor), not fan_ids or
      {"limit": 50}; unread chats are read like any other.
  case_scrape_sweep_stops_after_five_systemic_failures_in_a_row /
  case_scrape_sweep_fail_fast_counts_only_in_a_row /
  case_scrape_sweep_fail_fast_before_first_scan_and_knob:
      a `{}` sweep stops after SCRAPE_SWEEP_FAIL_FAST (5) systemic failures in a row
      (429, OF 5xx, proxy, timeout) anywhere, raises (no full_sweep) and keeps what it
      scraped; a scraped chat or a parse failure resets the count, a 404 never counts;
      the before-first-scan stop is unchanged; the Knob is read at call time.
  case_scrape_silent_mass_only_chat_costs_one_page_and_defers /
  case_scrape_not_silent_chats_are_backfilled_as_today /
  case_scrape_cursor_write_clears_the_deferred_mark /
  case_scrape_eager_history_knob_restores_todays_calls /
  case_history_deferred_at_self_heals_on_init_db /
  case_scrape_deferred_backfill_counts_under_its_own_caller_kind:
      a `{}` sweep's first scrape of a Silent mass-only chat reads page 1 only, keeps
      rows / identity / mute / preview, adopts placeholders, leaves history_deferred_at
      with a NULL cursor; a fan reply on OF or in the DB, a ledger purchase, own non-queue rows or a short
      convo get today's calls; an explicit or post-reply scrape pulls both ends and
      clears the mark; SCRAPE_EAGER_HISTORY=1 restores today; init_db self-heals the column;
      a `deferred_history` backfill's OF calls count as `auto:scrape_chats:deferred_history`.
  case_fan_lease_acquire_block_steal:
      a live lease blocks a second automation; an expired one can be stolen;
      release frees it. The per-(account, fan) send guard (one send per cycle).
  case_unknown_kind_errors:
      run_once for an unregistered kind writes an error run.
  case_unknown_kind_consumes_ghost_job:
      a leftover pending job for a retired kind errors ONCE and stops —
      never a re-dispatch-every-tick loop.
  case_a_failed_run_retries_unless_its_rule_went_off_mid_run:
      a rule's failed run requeues its job with the backoff; switched off
      mid-run, the job ends cancelled (RULE_OFF_REASON), never requeued.
  case_a_refused_one_shot_waits_out_the_proxy_unless_a_write_may_have_landed:
      a one-shot run the proxy refused before any write reached OF requeues
      PROXY_RETRY_MINUTES out ("proxy_retry:<n> (...)") for PROXY_RETRIES
      retries, then ends 'error' "proxy_refused (...)"; one whose earlier write
      OF accepted keeps today's park ('error', "may have sent"), never resent.
  case_orphaned_one_shot_parks_sweep_requeues:
      the boot heal: orphaned running one-shots (scheduled_send, mass_premade,
      send_mass_message) end 'error' ("interrupted, may have sent"), an
      orphaned auto-reply goes back to pending, their runs end interrupted; a
      second pass changes nothing.
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
    MassRun,
    Message,
    ScheduledJob,
    ScrapeHistory,
    Transaction,
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


# ── Only a `{}` sweep is a full sweep (sweep_cadence's anchor); unread chats are read too ──

async def case_scrape_full_sweep_mark_only_on_empty_payload():
    aid, read, unread = "acc_scrape_unread", 4101, 4102
    await _seed_account(aid)
    chats = {c: [_of_msg(c * 10, True, "hi", "2026-06-04T10:00:00+00:00", fan_id=c)]
             for c in (read, unread)}
    fetched: list[int] = []

    class UnreadClient(FakeClient):
        def list_chats(self, **kw) -> dict:
            page = super().list_chats(**kw)
            for row in page["list"]:
                row["unreadMessagesCount"] = 2 if row["withUser"]["id"] == unread else 0
            return page

        def get_messages(self, chat_id, **kw) -> dict:
            fetched.append(int(chat_id))
            return super().get_messages(chat_id, **kw)

    ax._make_client = lambda account_id: UnreadClient(chats)  # type: ignore[attr-defined]
    for payload, want_fetched, full in (({}, {read, unread}, True),
                                        ({"fan_ids": [unread]}, {unread}, False),
                                        ({"limit": 50}, {read, unread}, False)):
        fetched.clear()
        await enqueue_job(aid, "scrape_chats", payload=payload)
        res = await run_once(aid, "scrape_chats")
        assert res["status"] == "ok" and set(fetched) == want_fetched, (payload, res, fetched)
        assert res.get("full_sweep", False) is full, (payload, res)


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


# ── A full sweep stops after SCRAPE_SWEEP_FAIL_FAST systemic failures in a row ──

class ScriptedSweepClient(FakeClient):
    """A `{}` sweep over `script` (chat id -> "ok" | "429" | "503" | "proxy" | "timeout" |
    "404" | "parse"), in that order. "ok" serves one inbound message; the rest raise what
    of_client raises for that OF answer. `tried` records each chat's page-1 read."""

    def __init__(self, script: list[tuple[int, str]]):
        from curl_cffi import requests as cc
        self._cc = cc
        self.script = dict(script)
        super().__init__({c: [_of_msg(c * 10 + 1, True, "hi", "2026-06-05T10:00:00+00:00", fan_id=c)]
                          for c, _ in script})
        self.tried: list[int] = []

    def get_messages(self, chat_id, **kw) -> dict:
        cid = int(chat_id)
        if kw.get("before_id") is None and kw.get("order", "desc") == "desc":
            self.tried.append(cid)
        how = self.script[cid]
        exc = self._cc.exceptions
        if how in ("429", "503", "404"):
            from of_client import OFAPIError
            raise OFAPIError(how, response=type("R", (), {"status_code": int(how)})())
        if how == "proxy":
            raise exc.ProxyError("proxy refused")
        if how == "timeout":
            raise exc.Timeout("timed out")
        if how == "parse":
            raise json.JSONDecodeError("Expecting value", "<html>", 0)
        return super().get_messages(chat_id, **kw)


async def _sweep(aid: str, script: list[tuple[int, str]]):
    """One `{}` scrape_chats run over `script`: (result or the raised error, client)."""
    from automations import scrape_chats as sc
    await _seed_account(aid)
    fake = ScriptedSweepClient(script)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    real_sleep, sc._PAGE_SLEEP_S = sc._PAGE_SLEEP_S, 0
    try:
        return await sc._automation_scrape_chats(aid, {}, run_id=0), fake
    except RuntimeError as e:
        return e, fake
    finally:
        sc._PAGE_SLEEP_S = real_sleep


async def case_scrape_sweep_stops_after_five_systemic_failures_in_a_row():
    """A good chat, then a 429 burst (and, separately, a dead proxy): the sweep stops at
    the 5th failed read, raises (no full_sweep), and keeps the chat it scraped."""
    for aid, how in (("acc_ff_429", "429"), ("acc_ff_proxy", "proxy")):
        base = 6000 if how == "429" else 6100
        script = [(base, "ok")] + [(base + i, how) for i in range(1, 20)]
        res, fake = await _sweep(aid, script)
        assert isinstance(res, RuntimeError), (how, res)
        assert fake.tried == [base] + [base + i for i in range(1, 6)], (how, fake.tried)
        async with get_session() as s:
            assert await s.get(ScrapeHistory, (aid, base)) is not None, "the good chat is kept"
            n = len((await s.execute(select(Message).where(Message.account_id == aid))).scalars().all())
            assert n == 1, (how, n)
    # OF 5xx and timeouts are systemic too (mixed, still in a row).
    script = [(6200, "ok"), (6201, "503"), (6202, "timeout"), (6203, "429"), (6204, "proxy"),
              (6205, "503"), (6206, "ok")]
    res, fake = await _sweep("acc_ff_mix", script)
    assert isinstance(res, RuntimeError) and fake.tried == [6200 + i for i in range(6)], (res, fake.tried)


async def case_scrape_sweep_fail_fast_counts_only_in_a_row():
    """A scraped chat or a non-systemic failure resets the count; a 404 never counts
    (and never resets); five parse failures between good chats finish the sweep."""
    s429 = [(6300, "ok")] + [(6300 + i, "429") for i in range(1, 5)] + [(6305, "ok")] + \
        [(6305 + i, "429") for i in range(1, 5)] + [(6310, "ok")]
    res, fake = await _sweep("acc_ff_reset", s429)
    assert isinstance(res, dict) and res["full_sweep"] is True and res["chats_scanned"] == 3, res
    assert len(fake.tried) == 11, fake.tried
    parse = [(6400, "ok")] + [(6400 + i, "parse") for i in range(1, 6)] + [(6406, "ok")]
    res, fake = await _sweep("acc_ff_parse", parse)
    assert isinstance(res, dict) and res["full_sweep"] is True and res["chats_scanned"] == 2, res
    assert len(fake.tried) == 7, fake.tried
    # four 429s, a parse failure (resets), four 429s, a good chat: no stop.
    mixed = [(6500, "ok")] + [(6500 + i, "429") for i in range(1, 5)] + [(6505, "parse")] + \
        [(6505 + i, "429") for i in range(1, 5)] + [(6510, "ok")]
    res, fake = await _sweep("acc_ff_nonsys", mixed)
    assert isinstance(res, dict) and res["full_sweep"] is True and len(fake.tried) == 11, (res, fake.tried)
    # 404s between 429s neither count nor reset: 2 x 429, 3 x 404, 3 x 429 stops at the 5th 429.
    gone = [(6600, "ok"), (6601, "429"), (6602, "429"), (6603, "404"), (6604, "404"), (6605, "404"),
            (6606, "429"), (6607, "429"), (6608, "429"), (6609, "ok")]
    res, fake = await _sweep("acc_ff_gone", gone)
    assert isinstance(res, RuntimeError) and fake.tried == [6600 + i for i in range(9)], (res, fake.tried)
    # Ten 404s after a good chat: a healthy sweep.
    res, fake = await _sweep("acc_ff_allgone", [(6700, "ok")] + [(6700 + i, "404") for i in range(1, 11)])
    assert isinstance(res, dict) and res["full_sweep"] is True and len(fake.tried) == 11, res


async def case_scrape_sweep_fail_fast_before_first_scan_and_knob():
    """Today's stop before the first scraped chat (any non-404 failure) still fires at
    5; SCRAPE_SWEEP_FAIL_FAST is read at call time (3 stops at the 3rd systemic failure)."""
    import os
    res, fake = await _sweep("acc_ff_first", [(6800 + i, "parse") for i in range(20)])
    assert isinstance(res, RuntimeError) and "0 of 20" in str(res), res
    assert len(fake.tried) == 5, fake.tried
    os.environ["SCRAPE_SWEEP_FAIL_FAST"] = "3"
    try:
        res, fake = await _sweep("acc_ff_knob", [(6900, "ok")] + [(6900 + i, "429") for i in range(1, 10)])
        assert isinstance(res, RuntimeError) and len(fake.tried) == 4, (res, fake.tried)
    finally:
        del os.environ["SCRAPE_SWEEP_FAIL_FAST"]


# ── A `{}` sweep defers a Silent mass-only chat's deep history (SCRAPE_EAGER_HISTORY) ──

def _mass_msg(mid: int, *, fan_id: int, text: str | None = None, queued: bool = True) -> dict:
    """One of OUR mass rows as OF lists it in a chat (`isFromQueue`: sent from the queue)."""
    m = _of_msg(mid, False, text or f"mass {mid}",
                f"2026-06-06T{mid // 60 % 24:02d}:{mid % 60:02d}:00+00:00", fan_id=fan_id)
    if queued:
        m["isFromQueue"] = True
    return m


class DeepSweepClient(PagedFakeClient):
    """PagedFakeClient (13 rows a page, desc by `id`, asc by `offset`) whose chat list
    holds its one chat, muted on OF, so a `{}` sweep reaches it."""

    def list_chats(self, **kw) -> dict:
        return {"list": [{"withUser": {"id": self.chat_id, "username": f"deep_{self.chat_id}",
                                       "name": "Deep", "subscribedOn": True},
                          "isMutedNotifications": True}], "hasMore": False}


async def _scrape(aid: str, fake, payload: dict) -> dict:
    """One scrape_chats run on `fake`, no page sleeps."""
    from automations import scrape_chats as sc
    await _seed_account(aid)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    real_sleep, sc._PAGE_SLEEP_S = sc._PAGE_SLEEP_S, 0
    try:
        return await sc._automation_scrape_chats(aid, payload, run_id=0)
    finally:
        sc._PAGE_SLEEP_S = real_sleep


async def _thread(aid: str, fan: int) -> tuple:
    """(message ids ascending, ScrapeHistory row, Chat row, Fan row)."""
    async with get_session() as s:
        ids = sorted(m.message_id for m in (await s.execute(
            select(Message).where(Message.account_id == aid, Message.fan_id == fan))).scalars().all())
        return ids, await s.get(ScrapeHistory, (aid, fan)), await s.get(Chat, (aid, fan)), \
            await s.get(Fan, (aid, fan))


async def case_scrape_silent_mass_only_chat_costs_one_page_and_defers():
    """150 of our queued mass rows, no fan message anywhere: the `{}` sweep reads page 1
    only, keeps its rows, identity, mute and preview, adopts the thread's placeholder, and
    leaves a deferred row with a NULL cursor. A second silent sweep costs the same page."""
    aid, fan = "acc_defer", 5300
    msgs = [_mass_msg(i, fan_id=fan) for i in range(1, 151)]
    fake = DeepSweepClient(fan, msgs)
    await _seed_account(aid)
    # The optimistic stub `write_mass_optimistic_rows` left for the newest send (OF echoed no ids).
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=5_000_000_000_000_150, direction="out",
                      sender_name="", body="mass 150", media_ids="[]", media_count=0, price_cents=0,
                      is_tip=False, is_unsent=False, is_promise=False, automation_kind="mass_message",
                      created_at=datetime(2026, 6, 6, 2, 30)))

    res = await _scrape(aid, fake, {})
    assert res["full_sweep"] is True and res["chats_scanned"] == 1, res
    assert fake.calls == [("desc", None, None)], fake.calls
    ids, hist, chat, f = await _thread(aid, fan)
    assert ids == list(range(138, 151)), ids                      # page 1's 13 rows; the stub folded in
    assert hist.last_message_id is None and hist.history_deferred_at is not None, \
        (hist.last_message_id, hist.history_deferred_at)
    assert hist.last_scrape_at is not None
    assert chat.last_message_id == 150 and "mass 150" in chat.last_message_preview, chat.last_message_id
    assert f.of_username == "deep_5300" and f.is_muted is True, (f.of_username, f.is_muted)
    async with get_session() as s:
        real = await s.get(Message, (aid, fan, 150))
        assert real.automation_kind == "mass_message", real.automation_kind

    res = await _scrape(aid, fake, {})
    assert res["full_sweep"] is True and fake.calls == [("desc", None, None)] * 2, fake.calls
    _, hist, _, _ = await _thread(aid, fan)
    assert hist.last_message_id is None and hist.history_deferred_at is not None


async def case_scrape_not_silent_chats_are_backfilled_as_today():
    """A fan message on OF page 1, a fan message in the DB, a ledger purchase by the fan
    (a PPV buyer or out-of-chat tipper on a silent page), our own non-queue rows, or a
    short convo (no hasMore): the `{}` sweep makes exactly the calls an explicit scrape of
    the same thread makes (today's both-ends pull) and writes the cursor, no mark."""
    def reply_on_page1(fan):
        msgs = [_mass_msg(i, fan_id=fan) for i in range(1, 151)]
        msgs[145] = _of_msg(146, True, "hey", "2026-06-06T02:26:00+00:00", fan_id=fan)
        return msgs

    variants = (
        ("reply", reply_on_page1, False, 150),
        ("dbin", lambda fan: [_mass_msg(i, fan_id=fan) for i in range(1, 151)], "in", 150),
        ("manual", lambda fan: [_mass_msg(i, fan_id=fan, queued=False) for i in range(1, 151)], False, 150),
        ("short", lambda fan: [_mass_msg(i, fan_id=fan) for i in range(1, 11)], False, 10),
        ("paid", lambda fan: [_mass_msg(i, fan_id=fan) for i in range(1, 151)], "tx", 150),
    )
    for k, (name, build, db_seed, newest) in enumerate(variants):
        fan, aid = 5400 + k, "acc_defer"
        today = DeepSweepClient(fan + 50, build(fan + 50))
        await _scrape(aid, today, {"fan_ids": [fan + 50]})
        fake = DeepSweepClient(fan, build(fan))
        if db_seed == "in":   # the transcoder kept a fan DM OF no longer lists on page 1
            async with get_session() as s:
                s.add(Message(account_id=aid, fan_id=fan, message_id=9999, direction="in", sender_name="",
                              body="old dm", media_ids="[]", media_count=0, price_cents=0, is_tip=False,
                              is_unsent=False, is_promise=False, created_at=datetime(2026, 5, 1)))
        if db_seed == "tx":   # the ledger holds his PPV unlock; no fan message anywhere
            async with get_session() as s:
                s.add(Transaction(account_id=aid, fan_id=fan, kind="ppv_message", amount_cents=1500,
                                  occurred_at=datetime(2026, 5, 1), provider_transaction_id=f"tx{fan}",
                                  source="ingest"))
        res = await _scrape(aid, fake, {})
        assert res["full_sweep"] is True, (name, res)
        assert fake.calls == today.calls, (name, fake.calls, today.calls)
        if name != "short":
            assert {o for o, _b, _off in fake.calls} == {"desc", "asc"}, (name, fake.calls)
        _, hist, _, _ = await _thread(aid, fan)
        assert hist.last_message_id == newest and hist.history_deferred_at is None, \
            (name, hist.last_message_id, hist.history_deferred_at)


async def case_scrape_cursor_write_clears_the_deferred_mark():
    """A deferred chat: an explicit `fan_ids` scrape pulls both ends and clears the mark;
    a later `{}` sweep after the fan replied on OF does the same."""
    for aid, fan, how in (("acc_defer", 5500, "explicit"), ("acc_defer", 5501, "reply")):
        msgs = [_mass_msg(i, fan_id=fan) for i in range(1, 151)]
        fake = DeepSweepClient(fan, msgs)
        await _scrape(aid, fake, {})
        _, hist, _, _ = await _thread(aid, fan)
        assert hist.history_deferred_at is not None, how
        fake.calls.clear()
        if how == "reply":
            fake._asc.append(_of_msg(151, True, "finally", "2026-06-06T03:00:00+00:00", fan_id=fan))
        await _scrape(aid, fake, {"fan_ids": [fan]} if how == "explicit" else {})
        assert {o for o, _b, _off in fake.calls} == {"desc", "asc"}, (how, fake.calls)
        assert ("asc", None, 0) in fake.calls, (how, fake.calls)
        ids, hist, _, _ = await _thread(aid, fan)
        want = 151 if how == "reply" else 150
        assert hist.last_message_id == want and hist.history_deferred_at is None, \
            (how, hist.last_message_id, hist.history_deferred_at)
        assert ids[0] == 1 and ids[-1] == want, (how, ids[:3], ids[-3:])


async def case_scrape_eager_history_knob_restores_todays_calls():
    """SCRAPE_EAGER_HISTORY=1 (read at call time): a silent mass-only chat gets today's
    both-ends pull on the sweep, the same calls an explicit scrape makes, and no mark."""
    import os
    fan = 5600
    today = DeepSweepClient(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)])
    await _scrape("acc_defer", today, {"fan_ids": [fan]})
    fan += 1
    fake = DeepSweepClient(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)])
    os.environ["SCRAPE_EAGER_HISTORY"] = "1"
    try:
        await _scrape("acc_defer", fake, {})
    finally:
        del os.environ["SCRAPE_EAGER_HISTORY"]
    assert fake.calls == today.calls and len(fake.calls) > 1, (fake.calls, today.calls)
    _, hist, _, _ = await _thread("acc_defer", fan)
    assert hist.last_message_id == 150 and hist.history_deferred_at is None


async def case_scrape_deferred_backfill_counts_under_its_own_caller_kind():
    """Through the executor (which labels a run `auto:scrape_chats`): an explicit scrape of a
    chat deferred at job start counts its OF reads under `auto:scrape_chats:deferred_history`,
    whichever trigger won the claim (a blast reply too); one of a chat not deferred stays
    `auto:scrape_chats`."""
    import of_call_counter

    class Labelled(DeepSweepClient):
        def get_messages(self, chat_id, **kw):
            self.kinds.append(of_call_counter.caller_kind())
            return super().get_messages(chat_id, **kw)

    got = {}
    for fan, source, deferred in ((5700, "deferred_history", True), (5701, "blast_reply", True),
                                  (5702, "blast_reply", False)):
        fake = Labelled(fan, [_mass_msg(i, fan_id=fan) for i in range(1, 151)])
        fake.kinds = []
        await _seed_account("acc_defer")
        if deferred:
            async with get_session() as s:
                s.add(ScrapeHistory(account_id="acc_defer", fan_id=fan, last_message_id=None,
                                    last_scrape_at=datetime.utcnow(),
                                    history_deferred_at=datetime.utcnow()))
        ax._make_client = lambda account_id, f=fake: f  # type: ignore[attr-defined]
        res = await ax.run_once("acc_defer", "scrape_chats", payload={"fan_ids": [fan], "source": source})
        assert res["status"] == "ok", res
        got[fan] = set(fake.kinds)
        assert len(fake.kinds) > 1, fake.kinds
    assert got == {5700: {"auto:scrape_chats:deferred_history"},
                   5701: {"auto:scrape_chats:deferred_history"},
                   5702: {"auto:scrape_chats"}}, got


async def case_history_deferred_at_self_heals_on_init_db():
    """`scrape_history.history_deferred_at` is on a fresh DB and is ALTERed onto an old one
    by init_db; an old row reads NULL (not deferred), no backfill."""
    import importlib
    import os
    import sqlite3
    import tempfile
    from pathlib import Path

    import sqlalchemy as sa
    import sqlalchemy.dialects.sqlite  # noqa: F401
    from sqlalchemy.schema import CreateTable

    db_engine = importlib.import_module("db.engine")
    tmp = Path(tempfile.gettempdir())
    old, fresh = tmp / f"sh_old_{os.getpid()}.db", tmp / f"sh_fresh_{os.getpid()}.db"
    for p in (old, fresh):
        p.unlink(missing_ok=True)
    ddl = str(CreateTable(ScrapeHistory.__table__).compile(dialect=sa.dialects.sqlite.dialect()))
    con = sqlite3.connect(old)
    con.executescript(f"""
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version VALUES ('0108_tracking_link_bot_check');
        {ddl};
        ALTER TABLE scrape_history DROP COLUMN history_deferred_at;
        INSERT INTO scrape_history (account_id, fan_id, last_message_id, last_scrape_at)
            VALUES ('legacy1', 1, 42, '2026-06-01 00:00:00');
    """)
    con.commit()
    con.close()
    prev = db_engine.DATABASE_URL
    try:
        for p in (old, fresh):
            db_engine.DATABASE_URL = f"sqlite+aiosqlite:///{p}"
            await db_engine.init_db()
    finally:
        db_engine.DATABASE_URL = prev
    for p in (old, fresh):
        con = sqlite3.connect(p)
        cols = {r[1] for r in con.execute("PRAGMA table_info(scrape_history)")}
        rows = con.execute("SELECT account_id, last_message_id, history_deferred_at FROM scrape_history").fetchall()
        con.close()
        p.unlink(missing_ok=True)
        assert "history_deferred_at" in cols, (p.name, sorted(cols))
        assert rows == ([("legacy1", 42, None)] if p == old else []), (p.name, rows)


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


async def case_due_pairs_carry_their_oldest_due_run_at():
    """_due_job_pairs hands plan_dispatch each pair's oldest due run_at (epoch s),
    the bulk lane's order."""
    old, new = "acc_due_old", "acc_due_new"
    now = datetime.utcnow()
    for aid in (old, new):
        await _seed_account(aid)
    await enqueue_job(old, "scrape_chats", payload={}, run_at=now - timedelta(hours=3))
    await enqueue_job(old, "scrape_chats", payload={}, run_at=now - timedelta(hours=1))
    await enqueue_job(new, "scrape_chats", payload={}, run_at=now - timedelta(minutes=5))
    due = {p.account_id: p.due_at for p in await ax._due_job_pairs() if p.account_id in (old, new)}
    want = (now - timedelta(hours=3) - datetime(1970, 1, 1)).total_seconds()
    assert abs(due[old] - want) < 1 and due[old] < due[new], due
    async with get_session() as s:   # leave no due scrape for later cases' drains
        for j in (await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id.in_((old, new))))).scalars():
            j.status = "done"


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

    pairs = {(a, k): op for a, k, op, _due in await ax._due_job_pairs()}
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
    pairs = {(a, k): op for a, k, op, _due in await ax._due_job_pairs()}
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

        def close_signed_sessions(self) -> None:  # client_pool.evict retires it
            pass

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


async def case_a_failed_run_retries_unless_its_rule_went_off_mid_run():
    """A rule's run that raises parks its job (job_queue._park_failed_job ->
    run_decide.park): back to pending with the backoff while the rule is on,
    `cancelled` (RULE_OFF_REASON, the error kept) when the operator switched the
    rule off while the attempt ran — the rules API leaves a running job alone."""
    from automation_registry import register
    from run_decide import JOB_RETRY_BACKOFF_S
    aid, kind = "acc_park_rule_off", "park_probe_kind"
    await _seed_account(aid)
    switch_off: dict[str, int | None] = {"rule": None}

    @register(kind)
    async def _failing(account_id, payload, *, run_id):
        if switch_off["rule"] is not None:   # the operator's PATCH lands mid-run
            async with get_session() as s:
                (await s.get(AutomationRule, switch_off["rule"])).is_enabled = False
        raise RuntimeError("OF refused the write")

    async def _rule(name: str) -> int:
        async with get_session() as s:
            rule = AutomationRule(account_id=aid, name=name, kind=kind,
                                  trigger_json=json.dumps({"every_seconds": 3600}),
                                  steps_json="{}", is_enabled=True)
            s.add(rule)
            await s.flush()
            return rule.id

    # Rule stays on: the job is requeued with the backoff.
    job_id = await enqueue_job(aid, kind, payload={}, rule_id=await _rule("on"))
    t0 = datetime.utcnow()
    res = await run_once(aid, kind)
    assert res["status"] == "error" and res["job_id"] == job_id, res
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.attempts == 1, job.attempts
        assert job.status == "pending", job.status
        assert job.run_at >= t0 + timedelta(seconds=JOB_RETRY_BACKOFF_S - 1), job.run_at
        assert "OF refused the write" in job.last_error, job.last_error
        job.status = "done"   # out of the next claim's way

    # Rule switched off mid-run: the job ends cancelled, never requeued.
    switch_off["rule"] = await _rule("off")
    job_id = await enqueue_job(aid, kind, payload={}, rule_id=switch_off["rule"])
    res = await run_once(aid, kind)
    assert res["status"] == "error" and res["job_id"] == job_id, res
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.attempts == 1, job.attempts
        assert job.status == "cancelled", job.status
        assert job.last_error.startswith(f"{ax.RULE_OFF_REASON} ("), job.last_error
        assert "OF refused the write" in job.last_error, job.last_error


async def case_a_refused_one_shot_waits_out_the_proxy_unless_a_write_may_have_landed():
    """job_queue._park_failed_job's `refused` path (run_decide.defers_refusal), on the real
    kinds: a refused broadcast (send_mass_message) with nothing sent is retried after the refusal
    wait, its refusals counted apart from an earlier other failure; a composer
    scheduled_send (a chatter's DM) keeps the 60 s retry; once a write was accepted, the
    send-once park wins."""
    from curl_cffi.requests.exceptions import ProxyError
    from automation_registry import _REGISTRY
    import run_decide
    aid = "acc_refused_one_shot"
    await _seed_account(aid)
    mode = {"accept_first": False, "other_first": False}

    def _refuse():
        raise ProxyError("CONNECT tunnel failed, response 403")

    async def _send(account_id, payload, *, run_id):
        if mode.pop("other_first", False):
            raise RuntimeError("OF answered garbage")   # not a refusal: the plain retry
        if mode["accept_first"]:
            await ax.of_write_paced(account_id, lambda: {"id": 1}, min_gap_s=0,
                                    send_purpose="not_fan_dm")
        await ax.of_write_paced(account_id, _refuse, min_gap_s=0, send_purpose="not_fan_dm")

    saved = {k: _REGISTRY[k] for k in ("send_mass_message", "scheduled_send")}
    _REGISTRY.update({k: _send for k in saved})
    payload = {"fan_id": 1, "text": "hi"}
    try:
        kind = "send_mass_message"
        mode["other_first"] = True
        job_id = await enqueue_job(aid, kind, payload=payload)
        res = await run_once(aid, kind)
        async with get_session() as s:
            job = await s.get(ScheduledJob, job_id)
            assert job.status == "pending" and not job.last_error.startswith(run_decide.PROXY_RETRY), job.last_error
            job.run_at = datetime.utcnow()
        for n in range(1, run_decide.PROXY_RETRIES + 2):
            t0 = datetime.utcnow()
            res = await run_once(aid, kind)
            assert res["status"] == "error" and res["job_id"] == job_id, res
            async with get_session() as s:
                job = await s.get(ScheduledJob, job_id)
                assert job.attempts == n + 1, (n, job.attempts)
                if n <= run_decide.PROXY_RETRIES:
                    assert job.status == "pending", (n, job.status)
                    assert job.run_at >= t0 + timedelta(minutes=run_decide.PROXY_RETRY_MINUTES) - timedelta(seconds=1), job.run_at
                    assert job.last_error.startswith(f"{run_decide.PROXY_RETRY}:{n} ("), job.last_error
                    job.run_at = datetime.utcnow()   # due again: the next claim takes it
                else:   # 4 refusals after the other failure: its attempt ate none of them
                    assert job.status == "error", job.status
                    assert job.last_error.startswith(f"{run_decide.PROXY_REFUSED} ("), job.last_error
                    assert "403" in job.last_error, job.last_error

        kind = "scheduled_send"   # a chatter's DM: the plain retry, never the long wait
        job_id = await enqueue_job(aid, kind, payload=payload)
        t0 = datetime.utcnow()
        res = await run_once(aid, kind)
        assert res["status"] == "error" and res["job_id"] == job_id, res
        async with get_session() as s:
            job = await s.get(ScheduledJob, job_id)
            assert job.status == "pending" and not job.last_error.startswith(run_decide.PROXY_RETRY), job.last_error
            assert job.run_at <= t0 + timedelta(seconds=run_decide.JOB_RETRY_BACKOFF_S + 5), job.run_at

        mode["accept_first"] = True   # OF took a write, then the proxy refused: send once
        job_id = await enqueue_job(aid, "send_mass_message", payload=payload)
        res = await run_once(aid, "send_mass_message")
        assert res["status"] == "error" and res["job_id"] == job_id, res
        async with get_session() as s:
            job = await s.get(ScheduledJob, job_id)
            assert job.status == "error", job.status
            assert job.last_error.startswith(run_decide.MAY_HAVE_SENT), job.last_error
    finally:
        _REGISTRY.update(saved)


async def case_orphaned_one_shot_parks_sweep_requeues():
    """_reconcile_orphans (boot heal), run_decide.one_shot_family: a one-shot send a
    dead process left running may already be on OF, so it is parked, never
    requeued; a sweep is requeued as before. Runs end interrupted. Idempotent."""
    aid = "acc_orphans"
    await _seed_account(aid)
    send_id = await enqueue_job(aid, "scheduled_send", payload={"fan_id": 1, "text": "hi"})
    others = [await enqueue_job(aid, k, payload={}) for k in ("mass_premade", "send_mass_message")]
    reply_id = await enqueue_job(aid, "auto_reply", payload={})
    async with get_session() as s:
        for jid in (send_id, reply_id, *others):
            (await s.get(ScheduledJob, jid)).status = "running"
        run = AutomationRun(account_id=aid, kind="scheduled_send",
                            started_at=datetime.utcnow(), status="running")
        s.add(run)
        await s.flush()
        run_id = run.id
    for _ in range(2):   # idempotent: a second pass changes nothing
        await ax._reconcile_orphans()
        async with get_session() as s:
            send = await s.get(ScheduledJob, send_id)
            reply = await s.get(ScheduledJob, reply_id)
            run = await s.get(AutomationRun, run_id)
            assert send.status == "error", f"orphaned scheduled_send {send.status}: may have sent"
            assert send.last_error == "interrupted, may have sent", send.last_error
            assert reply.status == "pending", f"orphaned sweep {reply.status}"
            for jid in others:
                job = await s.get(ScheduledJob, jid)
                assert job.status == "error" and job.last_error == "interrupted, may have sent", (
                    job.kind, job.status, job.last_error)
            assert run.status == "error" and "interrupted" in (run.error_text or ""), run.status


async def case_orphaned_mass_run_ends_interrupted_never_resent():
    """_reconcile_orphans: a mass run a dead process left `running` (minted, never
    closed: AE 2026-11-07 run 1545) ends MASS_RUN_INTERRUPTED with completed_at; a
    closed run is untouched; nothing is enqueued (never resent). Idempotent."""
    aid = "acc_mass_orphan"
    await _seed_account(aid)
    async with get_session() as s:
        orphan = MassRun(account_id=aid, automation_kind="mass_premade", status="running")
        closed = MassRun(account_id=aid, automation_kind="mass_premade", status="ok", queue_id=7)
        s.add_all([orphan, closed])
        await s.flush()
        orphan_id, closed_id = orphan.id, closed.id
        jobs_before = len((await s.execute(select(ScheduledJob.id))).all())
    for _ in range(2):
        await ax._reconcile_orphans()
        async with get_session() as s:
            o, c = await s.get(MassRun, orphan_id), await s.get(MassRun, closed_id)
            assert o.status == ax.MASS_RUN_INTERRUPTED == "interrupted", o.status
            assert o.completed_at is not None and o.queue_id is None
            assert c.status == "ok" and c.queue_id == 7, (c.status, c.queue_id)
            assert len((await s.execute(select(ScheduledJob.id))).all()) == jobs_before


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


# ── shutdown drain ───────────────────────────────────────────────────

async def case_drain_waits_for_a_run_that_claimed_a_send_then_refuses_new_claims():
    finished = []

    async def sending_run():
        assert ax.begin_send()
        await asyncio.sleep(0.3)
        finished.append(True)

    async def planning_run():   # never reached its claim: not waited for
        await asyncio.sleep(5)

    sender = asyncio.create_task(sending_run())
    planner = asyncio.create_task(planning_run())
    await asyncio.sleep(0)
    try:
        out = await ax.drain(timeout_s=5)
        assert out["waited"] == 1 and out["left"] == 0, out
        assert finished == [True] and sender.done() and not planner.done()
        assert ax.begin_send() is False, "a pass must not claim while the relay drains"
    finally:
        planner.cancel()
        ax._draining = False


async def case_drain_stops_waiting_once_the_send_is_settled():
    # What a pass does after its send is recorded (the free stream's follow-up
    # script, an LLM call) is not worth holding a deploy for.
    async def run_with_a_slow_tail():
        assert ax.begin_send()
        await asyncio.sleep(0.2)
        ax.end_send()
        await asyncio.sleep(30)

    t = asyncio.create_task(run_with_a_slow_tail())
    await asyncio.sleep(0)
    try:
        out = await ax.drain(timeout_s=10)
        assert out["waited"] == 1 and out["left"] == 0 and out["s"] < 2, out
        assert not t.done()
    finally:
        t.cancel()
        ax._draining = False


async def case_drain_is_bounded_by_its_timeout():
    async def stuck_run():
        assert ax.begin_send()
        await asyncio.sleep(30)

    t = asyncio.create_task(stuck_run())
    await asyncio.sleep(0)
    try:
        out = await ax.drain(timeout_s=0.2)
        assert out["waited"] == 1 and out["left"] == 1 and out["s"] < 2, out
    finally:
        t.cancel()
        ax._draining = False


async def case_a_draining_supervisor_starts_no_run_and_leaves_the_job_pending():
    aid = "acc_draining"
    await _seed_account(aid)
    _use_fake({})
    job_id = await enqueue_job(aid, "scrape_chats", payload={"chat_ids": [4002]})
    ax._draining = True
    try:
        await ax._drain_due_jobs_once()
        await ax._join_inflight_runs()
    finally:
        ax._draining = False
    async with get_session() as s:
        job = await s.get(ScheduledJob, job_id)
        assert job.status == "pending", job.status
        runs = (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid))).scalars().all()
        assert runs == [], runs


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


async def case_quiet_band_clock_read_only_for_due_free_rules():
    """The account clock is read only for a rule that passed busy / run limit / due and has
    a band (dispatch_plan.CheckQuiet): a busy or not-yet-due banded rule never reads it (so
    a bad-zone account is not re-resolved, and re-warned by the resolver, every pass). A
    clockless account with two due banded rules warns once."""
    import logging
    now = datetime.utcnow()
    band = json.dumps([0, 23])
    busy, notdue, noclk = "acc_clk_busy", "acc_clk_notdue", "acc_clk_noclock"
    for aid in (busy, notdue, noclk):
        await _seed_account(aid)
    hourly = json.dumps({"every_seconds": 3600})
    async with get_session() as s:
        s.add(ScheduledJob(account_id=busy, kind="scrape_chats", payload_json="{}",
                           run_at=now - timedelta(seconds=5), status="pending"))
        s.add(AutomationRule(account_id=busy, name="busy", kind="scrape_chats",
                             trigger_json=hourly, steps_json="{}",
                             quiet_hours_json=band, is_enabled=True))
        nd = AutomationRule(account_id=notdue, name="not due", kind="scrape_chats",
                            trigger_json=hourly, steps_json="{}",
                            quiet_hours_json=band, is_enabled=True)
        s.add(nd)
        for kind in ("scrape_chats", "send_welcome"):
            s.add(AutomationRule(account_id=noclk, name=f"noclock {kind}", kind=kind,
                                 trigger_json=hourly, steps_json="{}",
                                 quiet_hours_json=band, is_enabled=True))
        await s.flush()
        s.add(ScheduledJob(account_id=notdue, kind="scrape_chats", payload_json="{}",
                           run_at=now, status="done", rule_id=nd.id, created_at=now))

    reads: list[str] = []
    real = ax._account_clock

    async def counting(s, account_id, offsets, now):
        reads.append(account_id)
        return await real(s, account_id, offsets, now)

    warned: list[str] = []

    class _H(logging.Handler):
        def emit(self, rec):
            if "quiet_hours_no_clock" in rec.getMessage():
                warned.append(rec.getMessage())

    h = _H()
    ax.log.addHandler(h)
    ax._account_clock = counting
    try:
        await ax._materialize_due_rules()
    finally:
        ax._account_clock = real
        ax.log.removeHandler(h)
    assert busy not in reads and notdue not in reads, reads
    assert reads.count(noclk) == 2, reads      # both due rules ask; the pass cache answers the 2nd
    assert len([w for w in warned if noclk in w]) == 1, warned
    async with get_session() as s:
        jobs = (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == noclk, ScheduledJob.status == "pending"))).scalars().all()
        assert len(jobs) == 2, "clockless: the band cannot apply, both rules fire"
        for r in (await s.execute(select(AutomationRule).where(
                AutomationRule.account_id.in_((busy, notdue, noclk))))).scalars():
            r.is_enabled = False


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
    case_scrape_full_sweep_mark_only_on_empty_payload,
    case_scrape_long_convo_both_ends,
    case_scrape_desc_catch_up_no_refetch_start,
    case_scrape_sweep_stops_after_five_systemic_failures_in_a_row,
    case_scrape_sweep_fail_fast_counts_only_in_a_row,
    case_scrape_sweep_fail_fast_before_first_scan_and_knob,
    case_scrape_silent_mass_only_chat_costs_one_page_and_defers,
    case_scrape_not_silent_chats_are_backfilled_as_today,
    case_scrape_cursor_write_clears_the_deferred_mark,
    case_scrape_eager_history_knob_restores_todays_calls,
    case_scrape_deferred_backfill_counts_under_its_own_caller_kind,
    case_history_deferred_at_self_heals_on_init_db,
    case_fan_lease_acquire_block_steal,
    case_fan_cooldown_set_check_expire,
    case_kind_priority_ordering,
    case_supervisor_dispatches_high_priority_first,
    case_supervisor_dispatches_least_recently_served_account_first,
    case_due_pairs_carry_their_oldest_due_run_at,
    case_an_operators_job_dispatches_first_in_the_operator_tier,
    case_the_claim_takes_the_operators_job_first,
    case_run_now_on_an_automation_kind_is_rate_limited_as_automation,
    case_the_run_slots_size_from_the_active_creators,
    case_client_pool_reuses_and_evicts,
    case_unknown_kind_errors,
    case_unknown_kind_consumes_ghost_job,
    case_a_failed_run_retries_unless_its_rule_went_off_mid_run,
    case_a_refused_one_shot_waits_out_the_proxy_unless_a_write_may_have_landed,
    case_orphaned_one_shot_parks_sweep_requeues,
    case_orphaned_mass_run_ends_interrupted_never_resent,
    case_supervisor_drain_runs_due_job,
    case_rule_materializes_job,
    case_rule_with_unregistered_kind_stays_inert,
    case_future_oneshot_does_not_starve_rule,
    case_oneshot_runs_dont_reset_rule_cadence,
    case_clock_rule_not_starved_by_same_kind_run,
    case_rule_quiet_hours_holds_job,
    case_rule_quiet_hours_outside_band_materializes,
    case_quiet_hours_never_run_on_the_server_clock,
    case_quiet_band_clock_read_only_for_due_free_rules,
    case_drain_waits_for_a_run_that_claimed_a_send_then_refuses_new_claims,
    case_drain_stops_waiting_once_the_send_is_settled,
    case_drain_is_bounded_by_its_timeout,
    case_a_draining_supervisor_starts_no_run_and_leaves_the_job_pending,
)
