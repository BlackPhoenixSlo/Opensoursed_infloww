#!/usr/bin/env python3
"""
A12 unsend_messages — MASS free-text cleanup policy (`policy.mass_text_hours`).

Cases:
  case_mass_text_sweep_unsends_only_free_textless_old:
      seed mass_broadcast_cache with 5 broadcasts — only the FREE + image-less +
      old + still-unsendable one is swept; priced, image-bearing, too-recent,
      and already-canceled rows are all left alone. cancel_scheduled is called
      once for the eligible queue_id and its cache row flips is_canceled=True.
  case_mass_text_default_8h:
      `policy.mass_text` (no hours) uses the 8h default — a 9h-old free blast is
      swept, a 7h-old one is not.
  case_mass_text_dry_run_previews:
      dry_run returns the would-unsend mass target and touches neither OF nor the
      cache row.

Run: ./venv/bin/python service/tests/test_unsend_mass_policy.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

import json  # noqa: E402
from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.unsend_messages as a12  # noqa: E402,F401 — module under test (registers)
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
import messages as messages_api  # noqa: E402 — the chat pane's DB seed
from db.models import (  # noqa: E402
    Account, MassBroadcastCache, MassRun, Message,
)

KIND = "unsend_messages"


class FakeClient:
    def __init__(self, user_id: str = "999"):
        self.user_id = user_id
        self.cancel_calls: list[int] = []

    def cancel_scheduled(self, queue_id):
        self.cancel_calls.append(int(queue_id))
        return {"success": True}


class PagingClient(FakeClient):
    """A client whose `mass_message_history` serves a FLAT broadcast timeline sliced
    by (offset, limit) exactly like OF, so the run's `_refresh_mass_cache`
    write-through + offset pagination is exercised end-to-end. `page_size` caps how
    many rows a page returns even when the caller asks for more — modeling OF
    returning a SHORT page with hasMore=True, which a pager that strode by the
    REQUESTED limit (rather than rows returned) would silently skip."""

    def __init__(self, items: list[dict], *, page_size: int = 100):
        super().__init__()
        self.items = items
        self.page_size = page_size
        self.history_offsets: list[int] = []

    def mass_message_history(self, *, start_date, end_date, limit, offset):
        self.history_offsets.append(offset)
        size = min(limit, self.page_size)
        page = self.items[offset:offset + size]
        return {"items": page, "hasMore": offset + size < len(self.items)}


def _use_fake() -> FakeClient:
    fake = FakeClient()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _of_item(qid: int, *, hours_old: float, is_free=True, media_count=0,
             is_tip=False) -> dict:
    """An OF /stats/messages/group item, as `upsert_many` consumes it."""
    sent = datetime.utcnow() - timedelta(hours=hours_old)
    return {
        "id": qid, "date": sent.isoformat() + "+00:00", "text": "hey babe",
        "isFree": is_free, "isTip": is_tip, "mediaCount": media_count,
        "isCanceled": False, "canUnsend": True,
    }


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_cast(aid: str, qid: int, *, hours_old: float, is_free=True,
                    media_count=0, is_tip=False, is_canceled=False,
                    can_unsend=True) -> None:
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=qid,
            sent_at=datetime.utcnow() - timedelta(hours=hours_old),
            body_text="hey babe 😘", is_free=is_free, is_tip=is_tip,
            media_count=media_count, is_canceled=is_canceled,
            can_unsend=can_unsend, fetched_at=datetime.utcnow(),
        ))


async def _is_canceled(aid: str, qid: int) -> bool:
    async with get_session() as s:
        row = await s.get(MassBroadcastCache, (aid, qid))
    return bool(row and row.is_canceled)


# ── case 1: only the free + image-less + old + actionable row sweeps ──
async def case_mass_text_sweep_unsends_only_free_textless_old():
    aid = "9101"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 1001, hours_old=10)                       # ✓ eligible
    await _add_cast(aid, 1002, hours_old=10, is_free=False)        # priced → skip
    await _add_cast(aid, 1003, hours_old=10, media_count=2)        # image → skip
    await _add_cast(aid, 1004, hours_old=2)                        # too recent → skip
    await _add_cast(aid, 1005, hours_old=10, is_canceled=True)     # already gone → skip

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [1001], fake.cancel_calls
    assert r["unsent"] == 1, r
    assert await _is_canceled(aid, 1001), "eligible cache row not flipped"
    assert not await _is_canceled(aid, 1002)
    print("[ok] case_mass_text_sweep_unsends_only_free_textless_old")


# ── case 2: policy.mass_text uses the 8h default ──────────────────────
async def case_mass_text_default_8h():
    aid = "9102"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 2001, hours_old=9)   # ✓ older than 8h default
    await _add_cast(aid, 2002, hours_old=7)   # younger than 8h → skip

    r = await run_once(aid, KIND, payload={"policy": {"mass_text": True}})

    assert fake.cancel_calls == [2001], fake.cancel_calls
    assert r["unsent"] == 1, r
    print("[ok] case_mass_text_default_8h")


# ── case 3: dry_run previews, no OF call, no cache flip ───────────────
async def case_mass_text_dry_run_previews():
    aid = "9103"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 3001, hours_old=10)

    r = await run_once(aid, KIND,
                       payload={"policy": {"mass_text_hours": 8}, "dry_run": True})

    assert r["dry_run"] is True, r
    assert r["targets"] == 1, r
    assert r["would_unsend"][0]["queue_id"] == 3001, r
    assert fake.cancel_calls == [], "dry_run must not call OF"
    assert not await _is_canceled(aid, 3001), "dry_run must not flip the cache"
    print("[ok] case_mass_text_dry_run_previews")


# ── case 4: a mass-only policy must NOT also sweep per-chat bubbles ───
async def case_mass_only_policy_skips_per_chat():
    """Regression (caught live): policy.mass_text_hours alone must unsend ONLY the
    mass broadcast, never the per-chat default text sweep. Seed an old outbound
    per-chat text bubble that the per-chat sweep WOULD grab, then assert a mass-only
    policy leaves it alone."""
    from db.models import Message
    aid = "9104"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 4001, hours_old=10)  # eligible mass broadcast
    # An old per-chat outbound text bubble (12h old, inside the 24h window) — the
    # per-chat default sweep (text_hours=9) would grab this if it ran.
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=777, message_id=88001, direction="out",
                      body="hey", media_count=0, is_unsent=False,
                      created_at=datetime.utcnow() - timedelta(hours=12)))

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [4001], fake.cancel_calls
    assert r["unsent"] == 1, r  # ONLY the mass broadcast, not the per-chat bubble
    async with get_session() as s:
        msg = await s.get(Message, (aid, 777, 88001))
    assert msg is not None and msg.is_unsent is False, "per-chat bubble wrongly unsent"
    print("[ok] case_mass_only_policy_skips_per_chat")


# ── case 5: image + price classes sweep independently of text ────────
async def case_priced_ppv_floor_protects_under_24h():
    """A priced PPV is NEVER auto-unsent before 24h, whatever the operator set. Measured:
    47% of mass-PPV revenue (68% first-ever buys) lands >4h after send; the curve knees
    at 24h. So mass_price_hours=4 is floored to 24h — a 12h-old PPV SURVIVES."""
    aid = "9109"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 6001, hours_old=12, is_free=False)   # PPV, 12h — under the floor
    await _add_cast(aid, 6002, hours_old=26, is_free=False)   # PPV, 26h — past the floor
    r = await run_once(aid, KIND, payload={"policy": {"mass_price_hours": 4}})
    assert fake.cancel_calls == [6002], fake.cancel_calls   # 6001 protected, 6002 swept
    assert r["unsent"] == 1, r
    print("[ok] case_priced_ppv_floor_protects_under_24h")


async def case_mass_media_and_price_classes():
    """mass_media_hours sweeps broadcasts WITH images; mass_price_hours sweeps PPV
    (priced) broadcasts — but a priced PPV has a HARD 24h floor (47% of its revenue,
    68% first-ever buys, lands >4h after send). So an 8h-old PPV is PROTECTED even with
    mass_price_hours=8; only a PPV past 24h sweeps. A free text-only blast is untouched."""
    aid = "9105"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 5001, hours_old=10, media_count=3)                 # image → media
    await _add_cast(aid, 5002, hours_old=26, is_free=False)                 # PPV text >24h → price
    await _add_cast(aid, 5003, hours_old=10, is_free=False, media_count=2)  # paid image, only 10h
    await _add_cast(aid, 5004, hours_old=10)                                # free text → skip

    r = await run_once(aid, KIND, payload={
        "policy": {"mass_media_hours": 8, "mass_price_hours": 8}})

    # 5001 (image, 10h > media 8h) and 5002 (PPV, 26h > the 24h price floor) unsend.
    # 5003 is a paid image only 10h old: the media class would take it at 8h, but the
    # PRICE floor protects a priced PPV to 24h, so it must SURVIVE. 5004 free text skips.
    assert sorted(fake.cancel_calls) == [5001, 5002], fake.cancel_calls
    assert r["unsent"] == 2, r
    print("[ok] case_mass_media_and_price_classes")


# ── case 6: the run refreshes the cache from OF and PAGINATES ────────
async def case_mass_refresh_paginates_then_sweeps():
    """The gap this fix closes: with NOTHING pre-seeded in the cache, a real run
    must pull broadcast history from OF (write-through) and PAGE past `hasMore`, so
    an old free-text blast beyond the first page still gets swept. OF returns SHORT
    pages here (page_size=2 while the run asks for limit=100), so a pager that strode
    by the requested limit would jump to offset 100 and miss everything past row 1 —
    proving the stride is by ROWS RETURNED. The priced/image blasts are skipped by
    the text class regardless of age; the eligible free text-only blast is last."""
    aid = "9106"
    await _seed_account(aid)
    fake = PagingClient(items=[
        _of_item(6001, hours_old=10, is_free=False),   # priced → text class skips
        _of_item(6002, hours_old=10, media_count=2),   # image  → text class skips
        _of_item(6003, hours_old=240),                 # free, image-less, old → swept
    ], page_size=2)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    # Strode by rows returned: offset 0 (got 2 rows) → offset 2 (got the last row),
    # then stopped. A limit-strided pager would have been [0, 100] and missed 6003.
    assert fake.history_offsets == [0, 2], fake.history_offsets
    # Only the trailing free text-only blast is unsent — pagination reached it.
    assert fake.cancel_calls == [6003], fake.cancel_calls
    assert r["unsent"] == 1, r
    # Write-through populated the cache for every pulled broadcast...
    async with get_session() as s:
        cached = (await s.execute(
            select(MassBroadcastCache.queue_id).where(MassBroadcastCache.account_id == aid)
        )).scalars().all()
    assert sorted(cached) == [6001, 6002, 6003], cached
    # ...and the swept row is flipped canceled.
    assert await _is_canceled(aid, 6003), "swept cache row not flipped"
    print("[ok] case_mass_refresh_paginates_then_sweeps")


# ── case 7: a refresh must NOT resurrect a broadcast we already unsent ─
async def case_refresh_keeps_local_cancel():
    """Regression: once a broadcast is canceled in our cache, a later refresh whose
    OF feed still reports `isCanceled:false` (eventual-consistency lag) must NOT
    flip it back to live and re-cancel it — `is_canceled` is monotonic in
    `upsert_many`, so the sweep skips it and only the genuinely-new blast is unsent."""
    aid = "9107"
    await _seed_account(aid)
    # We unsent 7001 on a prior run; OF's lagging history still lists it as live.
    await _add_cast(aid, 7001, hours_old=240, is_canceled=True, can_unsend=False)
    fake = PagingClient(items=[
        _of_item(7001, hours_old=240),   # OF (wrongly) reports isCanceled=False
        _of_item(7002, hours_old=240),   # a brand-new eligible free text blast
    ])
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [7002], fake.cancel_calls  # 7001 not re-canceled
    assert r["unsent"] == 1, r
    assert await _is_canceled(aid, 7001), "local cancel was resurrected by the refresh"
    assert r["mass_refresh_failed"] is False, r
    print("[ok] case_refresh_keeps_local_cancel")


# ── case 8: the mirror flip spares PURCHASED rows (fan keeps paid copy) ─
async def case_mass_flip_spares_purchased_rows():
    """Regression (caught live on fan 800000667): OF's queue cancel only pulls a
    broadcast from fans who did NOT buy it — a purchaser keeps their paid copy
    in-chat forever. `_flip_mass_unsent` used to stamp is_unsent=1 on the whole
    run, hiding a bought $3.99 PPV from the thread mirror while OF still showed
    it. Seed one unsendable PPV broadcast whose run has three mirror rows —
    plain recipient, purchaser (purchased_at set), funnel follow-up — and assert
    ONLY the plain recipient's row flips."""
    from db.models import MassRun, Message
    aid = "9108"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 8001, hours_old=26, is_free=False)  # PPV >24h → price class
    base = datetime.utcnow() - timedelta(hours=26)  # past the 24h priced-PPV floor
    async with get_session() as s:
        s.add(MassRun(id=81, account_id=aid, queue_id=8001, recipient_count=3))
        s.add(Message(account_id=aid, fan_id=701, message_id=5_000_000_000_000_701,
                      direction="out", body="ppv", media_count=1, price_cents=399,
                      mass_run_id=81, is_unsent=False, created_at=base))
        s.add(Message(account_id=aid, fan_id=702, message_id=5_000_000_000_000_702,
                      direction="out", body="ppv", media_count=1, price_cents=399,
                      mass_run_id=81, is_unsent=False, created_at=base,
                      purchased_at=base + timedelta(hours=1)))  # fan BOUGHT it
        s.add(Message(account_id=aid, fan_id=703, message_id=88003,
                      direction="out", body="step2", media_count=0,
                      mass_run_id=81, funnel_step=2, is_unsent=False,
                      created_at=base))

    r = await run_once(aid, KIND, payload={"policy": {"mass_price_hours": 8}})

    assert fake.cancel_calls == [8001], fake.cancel_calls
    assert r["unsent"] == 1, r
    async with get_session() as s:
        plain = await s.get(Message, (aid, 701, 5_000_000_000_000_701))
        bought = await s.get(Message, (aid, 702, 5_000_000_000_000_702))
        follow = await s.get(Message, (aid, 703, 88003))
    assert plain is not None and plain.is_unsent is True, \
        "plain recipient mirror row must flip is_unsent"
    assert bought is not None and bought.is_unsent is False, \
        "PURCHASED row must stay live — the fan keeps their paid copy on OF"
    assert follow is not None and follow.is_unsent is False, \
        "funnel follow-up row must stay live"
    print("[ok] case_mass_flip_spares_purchased_rows")



# ── plans/blast-splice Part B — the copies a list blast leaves behind ────────
#
# `_flip_mass_unsent` only ever reached rows carrying a `mass_run_id`, i.e. the
# placeholders an EXPLICIT audience writes. A list-audience blast writes none: its
# per-fan rows arrive later on the inbox poll (or a scrape), untagged. So after the
# 4h mass unsend the bubbles were gone on OF and still `is_unsent = 0` here — every
# untagged outbound row on these accounts was — and the chat pane's DB seed
# repainted a retired blast on every open, forever. That is the operator's "in the
# UI those mass messages are not deleted".

async def _add_copy(aid: str, fan_id: int, message_id: int, *, body: str,
                    minutes_after: float, sent_at: datetime,
                    raw_json: str | None = None, mass_run_id: int | None = None,
                    purchased_at: datetime | None = None,
                    funnel_step: int | None = None,
                    automation_kind: str | None = None) -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=message_id,
            direction="out", body=body, media_count=0, is_unsent=False,
            created_at=sent_at + timedelta(minutes=minutes_after),
            raw_json=raw_json, mass_run_id=mass_run_id,
            purchased_at=purchased_at, funnel_step=funnel_step,
            automation_kind=automation_kind))


async def _flipped(aid: str, fan_id: int, message_id: int) -> bool:
    async with get_session() as s:
        row = await s.get(Message, (aid, fan_id, message_id))
    return bool(row and row.is_unsent)


async def case_mass_unsend_flips_the_poll_copies():
    """The hourly sweep cancels a 4h-old text blast. Every copy of it in the mirror
    has to go with it, and nothing else may.

    Two matching rules, because neither covers the other: the normalized BODY inside
    ±30 min (the poll writes no `raw_json` at all, and OF echoes our `\\n` as
    `<br />`), and OF's own `queueId` off a scraped frame — exact, at ANY age, which
    is the only thing that can reach the copy delivered 40 minutes late. The id may
    arrive as an int or as a string; both are OF.

    Spared, each for its own reason: a PURCHASED copy (OF leaves a buyer his), a
    funnel follow-up (a separate live message that merely shares the run), a
    same-text row three hours later (a chatter typing), and another account's rows."""
    aid, other = "9201", "9202"
    await _seed_account(aid)
    await _seed_account(other)
    fake = _use_fake()
    qid = 46605849959
    sent_at = datetime.utcnow() - timedelta(hours=5)
    ours = "come see what i just shot\nits filthy"
    echo = "come see what i just shot<br />\nits filthy"
    async with get_session() as s:
        for _ in range(2):
            # TWO runs on one queue — a resend that reused the queue id. Both must
            # be stamped, or the unstamped one stays spliceable after the cancel.
            s.add(MassRun(account_id=aid, queue_id=qid, automation_kind="mass_premade",
                          audience_filter="{}", recipient_count=0, status="ok",
                          completed_at=sent_at, body=ours, sent_at=sent_at))
    await _add_cast(aid, qid, hours_old=5)

    await _add_copy(aid, 801, 80001, body=echo, minutes_after=6, sent_at=sent_at)
    await _add_copy(aid, 802, 80002, body=ours, minutes_after=0.5, sent_at=sent_at)
    # Reachable ONLY by the id branch — 40 minutes is past the ±30 min window.
    await _add_copy(aid, 803, 80003, body=echo, minutes_after=40, sent_at=sent_at,
                    raw_json=json.dumps({"id": 80003, "queueId": qid,
                                         "isFromQueue": True}))
    await _add_copy(aid, 804, 80004, body=echo, minutes_after=45, sent_at=sent_at,
                    raw_json=json.dumps({"id": 80004, "queueId": str(qid)}))
    # …and the ones that must survive.
    await _add_copy(aid, 805, 80005, body=ours, minutes_after=180, sent_at=sent_at)
    await _add_copy(aid, 806, 80006, body=ours, minutes_after=5, sent_at=sent_at,
                    purchased_at=sent_at + timedelta(minutes=20))
    await _add_copy(aid, 807, 80007, body=ours, minutes_after=5, sent_at=sent_at,
                    funnel_step=2)
    await _add_copy(other, 808, 80008, body=ours, minutes_after=5, sent_at=sent_at)

    res = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 4}})
    assert fake.cancel_calls == [qid], fake.cancel_calls
    stats = res
    assert stats["copies_flipped"] == 4, stats
    # `rows_flipped` keeps its old meaning — tagged mirror rows plus the cache
    # flip — so a dashboard reading it across the deploy is not lied to.
    assert stats["rows_flipped"] == 1, stats     # the cache row only

    for fan_id, mid in ((801, 80001), (802, 80002), (803, 80003), (804, 80004)):
        assert await _flipped(aid, fan_id, mid), (fan_id, mid, "copy left live")
    for fan_id, mid in ((805, 80005), (806, 80006), (807, 80007)):
        assert not await _flipped(aid, fan_id, mid), (fan_id, mid, "wrongly flipped")
    assert not await _flipped(other, 808, 80008), "another account's row flipped"

    # Both runs on the queue are stamped → no chat engine splices either.
    async with get_session() as s:
        runs = (await s.execute(
            select(MassRun).where(MassRun.account_id == aid,
                                  MassRun.queue_id == qid))).scalars().all()
        assert len(runs) == 2 and all(r.unsent_at is not None for r in runs), \
            [(r.id, r.unsent_at) for r in runs]

    # And the thing the operator actually sees: the pane's seed stops serving it.
    seeded = await messages_api.list_messages(aid, 801, limit=50, before_id=None)
    assert [m["message_id"] for m in seeded["messages"]] == [], seeded["messages"]
    print("[ok] case_mass_unsend_flips_the_poll_copies")


async def case_the_re_apply_repairs_a_late_copy():
    """A scrape response captured BEFORE the cancel is written afterwards, carrying
    OF's `isUnsent` as it was at capture time — so it can revert a flip, or land a
    fresh copy of an already-canceled blast, seconds after the sweep walked past.

    There is no lock that closes that without serialising the scrape against the
    unsend, so the next mass tick simply does it again for every run this account
    canceled in the last 24h. And it has to run on a tick with NO targets, because
    a queue is a target exactly once — the repair tick is by definition the quiet
    one."""
    aid = "9203"
    await _seed_account(aid)
    _use_fake()
    qid = 46605849970
    sent_at = datetime.utcnow() - timedelta(hours=5)
    async with get_session() as s:
        s.add(MassRun(account_id=aid, queue_id=qid, automation_kind="mass_premade",
                      audience_filter="{}", recipient_count=0, status="ok",
                      completed_at=sent_at, body="just say please", sent_at=sent_at,
                      unsent_at=datetime.utcnow() - timedelta(minutes=10)))
    await _add_copy(aid, 811, 81001, body="just say please",
                    minutes_after=3, sent_at=sent_at)
    # Nothing is due: the cache holds a blast far too young for the 4h policy, so
    # this tick resolves ZERO targets and still has to repair.
    await _add_cast(aid, 46605849971, hours_old=1)

    res = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 4}})
    assert res["targets"] == 0, res
    assert res["copies_flipped"] == 1, res
    assert await _flipped(aid, 811, 81001), "the late copy was never repaired"

    # Idempotent: the second tick finds nothing left to do.
    res2 = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 4}})
    assert res2["copies_flipped"] == 0, res2
    print("[ok] case_the_re_apply_repairs_a_late_copy")

async def _main():
    await case_mass_text_sweep_unsends_only_free_textless_old()
    await case_mass_text_default_8h()
    await case_mass_text_dry_run_previews()
    await case_mass_only_policy_skips_per_chat()
    await case_priced_ppv_floor_protects_under_24h()
    await case_mass_media_and_price_classes()
    await case_mass_refresh_paginates_then_sweeps()
    await case_refresh_keeps_local_cancel()
    await case_mass_flip_spares_purchased_rows()
    await case_mass_unsend_flips_the_poll_copies()
    await case_the_re_apply_repairs_a_late_copy()
    print("all cases passed")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
