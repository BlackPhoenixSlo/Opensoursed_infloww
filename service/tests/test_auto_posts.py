#!/usr/bin/env python3
"""
P1/P2 auto_posts — self-cleaning / drip feed.

Cases:
  case_post_and_schedule_delete (the acceptance):
      a 1-post queue with hours_to_live → create_post called, a posts row is
      written (status='posted', of_post_id), and a one-shot `unsend_messages`
      job is enqueued at ~now+hours_to_live carrying a {post_id} target.
  case_keep_no_delete:
      a post WITHOUT hours_to_live posts but enqueues NO delete job (P2 "keep").
  case_drip_reenqueues_rest:
      a 2-post queue posts the first AND re-enqueues `auto_posts` with the
      remaining 1 item (the drip), at now+delay_minutes.
  case_dry_run_plans_nothing:
      dry_run returns the full plan, calls create_post 0 times, enqueues nothing.
  case_empty_post_skips_but_drains:
      an item with no text/media is skipped but the rest still drip forward.
  case_post_with_price:
      a priced post (e.g. $19.99) passes price→create_post AND stores it as
      price_cents (1999); a free post (price 0/absent) stores price_cents=0; the
      dry_run plan echoes each item's price.
  case_paid_no_media_skips:
      a priced text-only item is skipped (reason paid_no_media) yet the queue
      drains; a free text-only post is still allowed.
  case_previews_free_teaser:
      a paid post's preview_media_* pool is unioned into media_files and passed
      to create_post as `previews` (⊆ mediaFiles); a free post ignores it.
  case_media_order_consistent:
      the shuffled attach order handed to create_post equals the stored media_ids.

Run: ./venv/bin/python service/tests/test_auto_posts.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.auto_posts as ap  # noqa: E402,F401 — module under test (registers)
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Post, ScheduledJob  # noqa: E402

KIND = "auto_posts"


class FakeClient:
    """Records create_post calls, hands back an incrementing OF post id."""

    def __init__(self, start_id: int = 50000):
        self.user_id = "999"
        self.create_calls: list[dict] = []
        self._next = start_id

    def create_post(self, text, media_files=None, price=0, previews=None):
        self._next += 1
        self.create_calls.append(
            {"text": text, "media_files": list(media_files or []), "price": price,
             "previews": list(previews or [])}
        )
        return {"id": self._next, "text": text}


def _use_fake(**kw) -> FakeClient:
    fake = FakeClient(**kw)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return (await s.execute(
            select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == kind
            )
        )).scalars().all()


# ── Acceptance: post + schedule the auto-delete ──────────────────────

async def case_post_and_schedule_delete():
    aid = "acc_ap_one"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={
        "posts": [{"text": "self-cleaning", "media_files": [11], "hours_to_live": 6}],
    })

    assert res["status"] == "ok" and res["posted"] == 1, res
    assert len(fake.create_calls) == 1, fake.create_calls
    assert fake.create_calls[0]["media_files"] == [11]
    of_post_id = res["of_post_id"]

    async with get_session() as s:
        rows = (await s.execute(select(Post).where(Post.account_id == aid))).scalars().all()
        assert len(rows) == 1, rows
        assert rows[0].status == "posted" and rows[0].of_post_id == of_post_id

    # A delete job was enqueued against unsend_messages, with a {post_id} target.
    dels = await _jobs(aid, "unsend_messages")
    assert len(dels) == 1, dels
    import json
    payload = json.loads(dels[0].payload_json)
    tgt = payload["targets"][0]
    assert tgt["post_id"] == of_post_id and tgt["local_post_id"] == res["local_post_id"], tgt
    # ~6h out (allow a wide slop for clock + test runtime).
    delta_h = (dels[0].run_at - datetime.utcnow()).total_seconds() / 3600
    assert 5.5 < delta_h < 6.5, delta_h
    # Single-item queue → nothing dripped forward.
    assert res["remaining"] == 0 and await _jobs(aid, KIND) == []


# ── P2 "keep": no hours_to_live → no delete job ──────────────────────

async def case_keep_no_delete():
    aid = "acc_ap_keep"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"posts": [{"text": "keep me forever"}]})

    assert res["status"] == "ok" and res["posted"] == 1, res
    assert res["delete_job_id"] is None and res["delete_at"] is None, res
    assert len(fake.create_calls) == 1
    assert await _jobs(aid, "unsend_messages") == [], "kept post must not schedule a delete"


# ── Drip: a multi-item queue re-enqueues the remainder ───────────────

async def case_drip_reenqueues_rest():
    aid = "acc_ap_drip"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"posts": [
        {"text": "post 1", "hours_to_live": 2},
        {"text": "post 2", "delay_minutes": 30, "hours_to_live": 2},
    ]})

    assert res["status"] == "ok" and res["posted"] == 1, res
    assert res["remaining"] == 1, res
    assert len(fake.create_calls) == 1, "only the FIRST post fires this run"

    # The remainder was handed forward as a fresh auto_posts job ~30 min out.
    drips = await _jobs(aid, KIND)
    assert len(drips) == 1, drips
    import json
    rest = json.loads(drips[0].payload_json)["posts"]
    assert len(rest) == 1 and rest[0]["text"] == "post 2", rest
    delta_min = (drips[0].run_at - datetime.utcnow()).total_seconds() / 60
    assert 28 < delta_min < 32, delta_min


# ── dry_run: full plan, zero side effects ────────────────────────────

async def case_dry_run_plans_nothing():
    aid = "acc_ap_dry"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={
        "dry_run": True,
        "posts": [
            {"text": "a", "hours_to_live": 6},
            {"text": "b", "delay_minutes": 10},
        ],
    })

    assert res["dry_run"] is True and res["posts"] == 2 and res["posted"] == 0, res
    assert len(res["plan"]) == 2 and res["plan"][1]["delay_minutes"] == 10, res["plan"]
    assert fake.create_calls == [], "dry_run must not post"
    async with get_session() as s:
        assert (await s.execute(select(Post).where(Post.account_id == aid))).scalars().all() == []
    assert await _jobs(aid, KIND) == [] and await _jobs(aid, "unsend_messages") == []


# ── An empty item is skipped but the queue still drains ──────────────

async def case_empty_post_skips_but_drains():
    aid = "acc_ap_empty"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"posts": [
        {"text": "", "media_files": []},           # empty → skipped
        {"text": "real one", "hours_to_live": 1},   # still gets dripped forward
    ]})

    assert res["status"] == "skipped" and res["reason"] == "empty_post", res
    assert res["remaining"] == 1, res
    assert fake.create_calls == [], "empty item posts nothing"
    drips = await _jobs(aid, KIND)
    assert len(drips) == 1, "the rest drips forward despite the bad head"


# ── Randomiser: pick 1 text from the pool + sample media_count images ─

async def case_randomizer_text_and_media():
    aid = "acc_ap_rand"
    await _seed_account(aid)
    fake = _use_fake()

    texts = ["variant A", "variant B", "variant C"]
    pool = [101, 102, 103, 104, 105]
    res = await run_once(aid, KIND, payload={"posts": [{
        "texts": texts, "media_files": pool, "media_count": 2,
    }]})

    assert res["status"] == "ok" and res["posted"] == 1, res
    call = fake.create_calls[0]
    # Text is one of the variants.
    assert call["text"] in texts, call["text"]
    # Media is 2 DISTINCT ids drawn from the pool.
    assert len(call["media_files"]) == 2, call["media_files"]
    assert len(set(call["media_files"])) == 2, "no duplicate picks"
    assert set(call["media_files"]) <= set(pool), call["media_files"]


async def case_resend_cycle_restarts():
    """A single-post list with resend_count=2 posts once, then enqueues a FRESH
    auto_posts cycle ~resend_after_hours out carrying the pristine list +
    resend_count-1 + _original_posts."""
    import json
    aid = "acc_ap_resend"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={
        "posts": [{"text": "loop me", "hours_to_live": 6}],
        "resend_after_hours": 24,
        "resend_count": 2,
    })

    assert res["status"] == "ok" and res["posted"] == 1, res
    assert res["remaining"] == 0, "single-post list finishes this run"
    assert res["resend_job_id"] is not None and res["resends_left"] == 1, res

    # The restart is an auto_posts job ~24h out with count-1 + the original list.
    cycles = await _jobs(aid, KIND)
    assert len(cycles) == 1, cycles
    pl = json.loads(cycles[0].payload_json)
    assert pl["resend_count"] == 1, pl
    assert pl["_original_posts"][0]["text"] == "loop me", pl
    assert pl["posts"][0]["text"] == "loop me", pl
    delta_h = (cycles[0].run_at - datetime.utcnow()).total_seconds() / 3600
    assert 23.5 < delta_h < 24.5, delta_h


async def case_resend_count_exhausts():
    """resend_count=0 (or absent) posts the list once and enqueues NO cycle."""
    aid = "acc_ap_noresend"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={
        "posts": [{"text": "once"}],
        "resend_after_hours": 24,
        "resend_count": 0,        # no cycles → behaves like before
    })

    assert res["status"] == "ok" and res["resend_job_id"] is None, res
    assert res["resends_left"] == 0, res
    assert await _jobs(aid, KIND) == [], "no resend job when count exhausted"


async def case_resend_cycle_threads_through_drip():
    """A 2-post list with a cycle drips post-2 carrying the cycle fields (so the
    pristine list survives), and only restarts from the TERMINAL post."""
    import json
    aid = "acc_ap_resend_drip"
    await _seed_account(aid)
    fake = _use_fake()

    # Run 1: posts post-1, drips post-2 with the cycle threaded; NO restart yet.
    res1 = await run_once(aid, KIND, payload={
        "posts": [{"text": "p1"}, {"text": "p2", "delay_minutes": 5}],
        "resend_after_hours": 12,
        "resend_count": 1,
    })
    assert res1["remaining"] == 1 and res1["resend_job_id"] is None, res1
    drips = await _jobs(aid, KIND)
    assert len(drips) == 1, drips
    dp = json.loads(drips[0].payload_json)
    assert dp["posts"][0]["text"] == "p2", dp
    assert dp["resend_count"] == 1 and len(dp["_original_posts"]) == 2, dp

    # Run 2 (the dripped job): posts post-2, list now empty → restart fires.
    res2 = await run_once(aid, KIND, payload=dp)
    assert res2["remaining"] == 0 and res2["resend_job_id"] is not None, res2
    # The table now holds run1's drip (count 1) + run2's restart (count 0). Find
    # the restart by its decremented count (no order_by on _jobs).
    all_jobs = [json.loads(j.payload_json) for j in await _jobs(aid, KIND)]
    restarts = [p for p in all_jobs if p.get("resend_count") == 0]
    assert len(restarts) == 1 and len(restarts[0]["posts"]) == 2, all_jobs


# ── PPV price: passed to create_post + stored as price_cents ─────────

async def case_post_with_price():
    """A priced post forwards `price` (dollars) to create_post and persists it as
    price_cents (19.99 → 1999); a free post stores 0; the dry_run plan echoes the
    price for each item."""
    aid = "acc_ap_price"
    await _seed_account(aid)
    fake = _use_fake()

    # Paid post — price reaches OF as dollars, stored as cents.
    res = await run_once(aid, KIND, payload={
        "posts": [{"text": "🔒 paid", "media_files": [21], "price": 19.99}],
    })
    assert res["status"] == "ok" and res["posted"] == 1, res
    assert len(fake.create_calls) == 1, fake.create_calls
    assert fake.create_calls[0]["price"] == 19.99, fake.create_calls[0]
    async with get_session() as s:
        row = (await s.execute(select(Post).where(Post.account_id == aid))).scalars().one()
        assert row.price_cents == 1999, row.price_cents

    # Free post — price 0 (and the default-absent path) both store price_cents=0.
    aid2 = "acc_ap_free"
    await _seed_account(aid2)
    fake2 = _use_fake()
    res2 = await run_once(aid2, KIND, payload={
        "posts": [{"text": "free", "media_files": [22], "price": 0}],
    })
    assert res2["status"] == "ok", res2
    assert fake2.create_calls[0]["price"] == 0, fake2.create_calls[0]
    async with get_session() as s:
        row2 = (await s.execute(select(Post).where(Post.account_id == aid2))).scalars().one()
        assert row2.price_cents == 0, row2.price_cents

    # dry_run plan echoes each item's price (paid + free), posts nothing.
    aid3 = "acc_ap_price_dry"
    await _seed_account(aid3)
    fake3 = _use_fake()
    res3 = await run_once(aid3, KIND, payload={
        "dry_run": True,
        "posts": [
            {"text": "a", "price": 12.5},
            {"text": "b"},                 # no price → 0 in the plan
        ],
    })
    assert res3["dry_run"] is True and res3["posted"] == 0, res3
    assert res3["plan"][0]["price"] == 12.5, res3["plan"]
    assert res3["plan"][1]["price"] == 0, res3["plan"]
    assert fake3.create_calls == [], "dry_run must not post"


async def case_randomizer_default_count_one():
    aid = "acc_ap_rand1"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"posts": [{
        "text": "hi", "media_files": [7, 8, 9],  # no media_count → default 1
    }]})

    assert res["status"] == "ok", res
    assert len(fake.create_calls[0]["media_files"]) == 1, "default count is 1"
    assert fake.create_calls[0]["media_files"][0] in (7, 8, 9)


# ── item 3: a PAID post with no media is skipped (mirror of client guard) ─

async def case_paid_no_media_skips():
    """A priced item that resolves to NO media is skipped (OF rejects a priced
    text-only post) — but the queue still drains forward."""
    aid = "acc_ap_paidnomedia"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"posts": [
        {"text": "buy me", "price": 15},                    # priced, no media → skip
        {"text": "next", "media_files": [9], "price": 0},   # still drips forward
    ]})

    assert res["status"] == "skipped" and res["reason"] == "paid_no_media", res
    assert res["remaining"] == 1, res
    assert fake.create_calls == [], "a paid text-only post must not hit OF"
    drips = await _jobs(aid, KIND)
    assert len(drips) == 1, "the rest drips forward despite the bad head"

    # A FREE text-only post is still allowed (no image forced).
    aid2 = "acc_ap_freetext"
    await _seed_account(aid2)
    fake2 = _use_fake()
    res2 = await run_once(aid2, KIND, payload={"posts": [{"text": "free words only"}]})
    assert res2["status"] == "ok" and res2["posted"] == 1, res2
    assert fake2.create_calls[0]["media_files"] == [], fake2.create_calls[0]


# ── item 4: a paid post can carry a FREE-preview subset ──────────────────

async def case_previews_free_teaser():
    """A paid post's `preview_media_*` pool is sampled, UNIONed into media_files
    (so previews ⊆ mediaFiles), and passed to create_post as `previews`."""
    import json
    aid = "acc_ap_prev"
    await _seed_account(aid)
    fake = _use_fake()

    res = await run_once(aid, KIND, payload={"posts": [{
        "text": "paid w/ teaser", "media_files": [201, 202, 203], "media_count": 3,
        "price": 20, "preview_media_files": [301, 302], "preview_media_count": 2,
    }]})

    assert res["status"] == "ok" and res["posted"] == 1, res
    call = fake.create_calls[0]
    # previews are exactly the two teaser ids, and a subset of media_files.
    assert set(call["previews"]) == {301, 302}, call["previews"]
    assert set(call["previews"]) <= set(call["media_files"]), call
    # media_files = main pool ∪ preview pool, nothing lost.
    assert set(call["media_files"]) == {201, 202, 203, 301, 302}, call["media_files"]
    # The stored posts row mirrors exactly what OF received (shuffle consistency).
    async with get_session() as s:
        row = (await s.execute(select(Post).where(Post.account_id == aid))).scalars().one()
        assert json.loads(row.media_ids) == call["media_files"], (row.media_ids, call)

    # A FREE post ignores the preview pool entirely (previews are a PPV concept).
    aid2 = "acc_ap_prev_free"
    await _seed_account(aid2)
    fake2 = _use_fake()
    res2 = await run_once(aid2, KIND, payload={"posts": [{
        "text": "free", "media_files": [401], "price": 0,
        "preview_media_files": [402], "preview_media_count": 1,
    }]})
    assert res2["status"] == "ok", res2
    assert fake2.create_calls[0]["previews"] == [], fake2.create_calls[0]
    assert fake2.create_calls[0]["media_files"] == [401], fake2.create_calls[0]


# ── item 35: the shuffled attach order is identical in OF + our record ────

async def case_media_order_consistent():
    """The order handed to create_post is the SAME order stored on the posts row,
    so OF's gallery display and our record never diverge."""
    import json
    aid = "acc_ap_shuf"
    await _seed_account(aid)
    fake = _use_fake()

    pool = [401, 402, 403, 404, 405, 406]
    res = await run_once(aid, KIND, payload={"posts": [{
        "text": "gallery", "media_files": pool, "media_count": 6,
    }]})

    assert res["status"] == "ok", res
    call = fake.create_calls[0]
    assert sorted(call["media_files"]) == sorted(pool), call["media_files"]
    async with get_session() as s:
        row = (await s.execute(select(Post).where(Post.account_id == aid))).scalars().one()
        assert json.loads(row.media_ids) == call["media_files"], (row.media_ids, call)


_harness.run(
    case_post_and_schedule_delete,
    case_keep_no_delete,
    case_drip_reenqueues_rest,
    case_dry_run_plans_nothing,
    case_empty_post_skips_but_drains,
    case_randomizer_text_and_media,
    case_post_with_price,
    case_randomizer_default_count_one,
    case_paid_no_media_skips,
    case_previews_free_teaser,
    case_media_order_consistent,
    case_resend_cycle_restarts,
    case_resend_count_exhausts,
    case_resend_cycle_threads_through_drip,
)
