#!/usr/bin/env python3
"""
paid-messages — mass-summary row tests (Messages → All/PPV tab).

Covers the two bugs fixed in `messages.py` _collapsed_mass_rows + the
`/admin/paid-messages` keyset:

  case_counts_come_from_cache:
      a broadcast with mass_broadcast_cache sent=126/viewed=21 surfaces those
      numbers on the summary row — NOT the optimistic placeholder count (1).
  case_no_cache_falls_back_to_placeholder:
      a broadcast with no cache row (stats poll hasn't run) falls back through
      MassRun.recipient_count → distinct-fan placeholder count; never crashes,
      viewed_count = 0.
  case_mass_interleaves_by_time:
      a 6d-old broadcast sorts BELOW a 2h-old normal row and ABOVE an 8d-old
      normal row — it interleaves by send time instead of pinning to page 1
      (the old synthetic-5e15-id-as-sort-key bug).
  case_time_keyset_paginates:
      the (sent_at, message_id) cursor walks pages correctly across the
      interleaved set — no dupes, no gaps, mass row appears exactly once.

Run: ./venv/bin/python service/tests/test_paid_messages_mass.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

from datetime import datetime, timedelta  # noqa: E402

from attribution import mass_placeholder_message_id  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, MassBroadcastCache, MassRun, Message,
)
from messages import list_paid_messages  # noqa: E402

_NOW = datetime(2026, 6, 12, 12, 0, 0)
_FROM = (_NOW - timedelta(days=60)).isoformat()
_TO = (_NOW + timedelta(days=1)).isoformat()


# ── seed helpers ──────────────────────────────────────────────────────
async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_normal(aid: str, *, fan_id: int, msg_id: int, age: timedelta) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=msg_id,
            direction="out", body="hey", created_at=_NOW - age,
        ))


async def _add_broadcast(
    aid: str, *, run_id: int, queue_id: int, age: timedelta,
    cache_sent: int | None, cache_viewed: int | None,
    run_recipient: int = 0, placeholder_fans: list[int] | None = None,
) -> int:
    """Create a mass_run, its per-fan placeholder Message rows, and (optionally)
    a mass_broadcast_cache row. Returns the synthetic summary message_id."""
    placeholder_fans = placeholder_fans or [1]
    synth = mass_placeholder_message_id(run_id)
    async with get_session() as s:
        s.add(MassRun(
            id=run_id, account_id=aid, queue_id=queue_id,
            audience_filter="{}", recipient_count=run_recipient,
            automation_kind="send_mass_message",
        ))
        for i, fid in enumerate(placeholder_fans):
            s.add(Message(
                account_id=aid, fan_id=fid, message_id=synth + i,
                direction="out", body="campaign blast 😘",
                created_at=_NOW - age, mass_run_id=run_id,
                automation_kind="send_mass_message",
            ))
        if cache_sent is not None:
            s.add(MassBroadcastCache(
                account_id=aid, queue_id=queue_id,
                sent_at=_NOW - age, body_text="campaign blast 😘",
                sent_count=cache_sent, viewed_count=cache_viewed or 0,
                fetched_at=_NOW,
            ))
    return synth


async def _fetch(aid: str, *, limit: int = 50,
                 before_sent_at: str | None = None, before_id: int | None = None):
    return await list_paid_messages(
        request=None,  # type: ignore[arg-type]  # only used for _parse_date(request=...)
        from_=_FROM, to=_TO, account_id=aid,
        employee_id=None, status="all", type_="all", direction="any",
        fan_id=None, fan_query=None, collapse_mass=True, format="json",
        limit=limit, before_sent_at=before_sent_at, before_id=before_id,
    )


def _mass_row(rows: list[dict]) -> dict:
    return next(r for r in rows if r.get("is_mass_summary"))


# ── BUG 2: counts from cache ──────────────────────────────────────────
async def case_counts_come_from_cache():
    aid = "pm_cache"
    await _seed_account(aid)
    # 126 sent / 21 viewed lives in the cache; only ONE optimistic placeholder
    # Message row persisted (the explicit-userIds case).
    await _add_broadcast(
        aid, run_id=101, queue_id=9001, age=timedelta(days=6),
        cache_sent=126, cache_viewed=21, placeholder_fans=[1],
    )
    res = await _fetch(aid)
    m = _mass_row(res["rows"])
    assert m["recipient_count"] == 126, f"want 126, got {m['recipient_count']}"
    assert m["viewed_count"] == 21, f"want 21, got {m['viewed_count']}"
    assert m["recipient_count"] != 1, "placeholder count leaked instead of cache"


# ── BUG 2 fallback: no cache yet ──────────────────────────────────────
async def case_no_cache_falls_back_to_placeholder():
    aid = "pm_nocache"
    await _seed_account(aid)
    # No cache row, MassRun.recipient_count=0 → falls to distinct-fan count (2).
    await _add_broadcast(
        aid, run_id=201, queue_id=9101, age=timedelta(days=2),
        cache_sent=None, cache_viewed=None, run_recipient=0,
        placeholder_fans=[10, 11],
    )
    res = await _fetch(aid)
    m = _mass_row(res["rows"])
    assert m["recipient_count"] == 2, f"want 2 (placeholder), got {m['recipient_count']}"
    assert m["viewed_count"] == 0, f"want 0 viewed, got {m['viewed_count']}"


# ── BUG 1: time interleave ────────────────────────────────────────────
async def case_mass_interleaves_by_time():
    aid = "pm_sort"
    await _seed_account(aid)
    await _add_normal(aid, fan_id=20, msg_id=5001, age=timedelta(hours=2))
    await _add_normal(aid, fan_id=21, msg_id=5002, age=timedelta(days=8))
    await _add_broadcast(
        aid, run_id=301, queue_id=9201, age=timedelta(days=6),
        cache_sent=126, cache_viewed=21,
    )
    rows = (await _fetch(aid))["rows"]
    assert len(rows) == 3, f"want 3 rows, got {len(rows)}"
    # newest first by TIME: 2h normal, then 6d mass, then 8d normal.
    assert not rows[0]["is_mass_summary"], "2h normal row should be first, not the 6d mass row"
    assert rows[1]["is_mass_summary"], "6d mass row should interleave in the middle slot"
    assert rows[2]["message_id"] == 5002, "8d normal row should sort last"


# ── BUG 1: cursor walks the interleaved pages ─────────────────────────
async def case_time_keyset_paginates():
    aid = "pm_page"
    await _seed_account(aid)
    await _add_normal(aid, fan_id=30, msg_id=6001, age=timedelta(hours=2))
    await _add_normal(aid, fan_id=31, msg_id=6002, age=timedelta(days=8))
    synth = await _add_broadcast(
        aid, run_id=401, queue_id=9301, age=timedelta(days=6),
        cache_sent=50, cache_viewed=5,
    )

    page1 = await _fetch(aid, limit=2)
    ids1 = [r["message_id"] for r in page1["rows"]]
    assert ids1 == [6001, synth], f"page1 should be [2h normal, 6d mass], got {ids1}"
    assert page1["next_before_sent_at"] is not None
    assert page1["next_before_id"] == synth

    page2 = await _fetch(
        aid, limit=2,
        before_sent_at=page1["next_before_sent_at"],
        before_id=page1["next_before_id"],
    )
    ids2 = [r["message_id"] for r in page2["rows"]]
    assert ids2 == [6002], f"page2 should be just the 8d normal row, got {ids2}"
    # No dupes across the seam.
    assert synth not in ids2, "mass row duplicated onto page 2"
    assert page2["next_before_id"] is None, "short page → cursor exhausted"


async def case_cache_is_stale_once_a_mass_run_is_newer():
    """The Mass messages tab refetches after our own sends: a cache fetched
    before the account's latest mass_runs row (minted at send, `started_at`, or
    stamped with OF's `sent_at` at close) is stale; a refetch makes it fresh."""
    import mass_broadcast_cache as cache
    aid = "pm_stale"
    await _seed_account(aid)
    now = datetime.utcnow()

    async def run(**kw):
        async with get_session() as s:
            s.add(MassRun(account_id=aid, audience_filter="{}", recipient_count=0, **kw))
    async with get_session() as s:
        s.add(MassBroadcastCache(account_id=aid, queue_id=91, sent_at=now - timedelta(hours=2),
                                 sent_count=1, fetched_at=now - timedelta(minutes=10)))
    assert not await cache.is_stale(aid), "no run at all"
    await run(started_at=now - timedelta(hours=1))
    assert not await cache.is_stale(aid), "a run older than the fetch"
    await run(started_at=now - timedelta(hours=3), sent_at=now - timedelta(minutes=5))
    assert await cache.is_stale(aid), "OF's send stamp is after the fetch"
    await cache.upsert_many(aid, [{"id": 91, "date": (now - timedelta(hours=2)).isoformat() + "+00:00"}])
    assert not await cache.is_stale(aid), "the refetch caught up"
    await run(started_at=datetime.utcnow() + timedelta(seconds=1))
    assert await cache.is_stale(aid), "a run minted after the fetch"


_harness.run(
    case_counts_come_from_cache,
    case_no_cache_falls_back_to_placeholder,
    case_mass_interleaves_by_time,
    case_time_keyset_paginates,
    case_cache_is_stale_once_a_mass_run_is_newer,
)
