#!/usr/bin/env python3
"""
Stale mass-placeholder rows — the "long-unsent ppv_send blasts haunt the chat
pane" bug (notification-open path). Two backend halves:

  case_mass_sweep_flips_placeholder_rows:
      The mass cache sweep now recovers OUR mass_run_id via the
      mass_broadcast_cache.queue_id → mass_runs.queue_id join, so after OF
      cancels the broadcast `_flip_mass_unsent` mirrors is_unsent onto the
      per-recipient 5e15-band placeholder rows. Pre-fix the sweep hardcoded
      mass_run_id=None and the rows stayed "sent" locally forever.
  case_mass_sweep_without_run_still_unsends:
      A cache row with NO matching mass_runs row (manual OF-web blast) still
      sweeps — mass_run_id stays None, nothing to flip, no crash.
  case_seed_endpoint_filters_stale_placeholders:
      GET /admin/messages/{aid}/{fid} (the chat pane's DB seed) serves a
      placeholder only while fresh (≤1h). Stale placeholders are excluded;
      real rows of any age still page through.
  case_sweep_spares_funnel_step_messages:
      Canceling the broadcast queue must flip ONLY the broadcast rows —
      reply_mass_funnel step sends share the mass_run_id but are per-chat
      messages still live on OF (funnel_step guard).
  case_seed_endpoint_keeps_ledger_tips:
      The 6e15 ledger-tip band (transaction_ingest._TIP_MSG_ID_BASE) is
      PERMANENT synthetic history — exempt from the 1h bridge cutoff.

Run: ./venv/bin/python service/tests/test_mass_placeholder_staleness.py  (exit 0 = pass)
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

import automation_executor as ax  # noqa: E402 — shared _make_client seam
import automations.unsend_messages as a12  # noqa: E402,F401 — module under test (registers)
import messages as messages_api  # noqa: E402 — seed endpoint under test
from attribution import mass_placeholder_message_id  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, MassBroadcastCache, MassRun, Message  # noqa: E402

KIND = "unsend_messages"


class FakeClient:
    def __init__(self, user_id: str = "999"):
        self.user_id = user_id
        self.cancel_calls: list[int] = []

    def cancel_scheduled(self, queue_id):
        self.cancel_calls.append(int(queue_id))
        return {"success": True}


def _use_fake() -> FakeClient:
    fake = FakeClient()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _add_cast(aid: str, qid: int, *, hours_old: float) -> None:
    """An old, free, image-less broadcast — eligible for the mass_text sweep."""
    async with get_session() as s:
        s.add(MassBroadcastCache(
            account_id=aid, queue_id=qid,
            sent_at=datetime.utcnow() - timedelta(hours=hours_old),
            body_text="flash deal just for u", is_free=True, is_tip=False,
            media_count=0, is_canceled=False, can_unsend=True,
            fetched_at=datetime.utcnow(),
        ))


async def _add_run(aid: str, qid: int) -> int:
    async with get_session() as s:
        mr = MassRun(account_id=aid, queue_id=qid,
                     automation_kind="ppv_send", status="ok",
                     completed_at=datetime.utcnow())
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _add_placeholder(aid: str, fan_id: int, run_id: int, *,
                           hours_old: float, price_cents: int = 999) -> int:
    """A per-recipient optimistic row exactly as write_mass_optimistic_rows
    persists it: synthetic 5e15-band id, mass_run_id set, is_unsent False."""
    mid = mass_placeholder_message_id(run_id)
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=mid, direction="out",
            body="stop bein shy n open it already", media_count=0,
            price_cents=price_cents, is_unsent=False, mass_run_id=run_id,
            temp_id=f"mass:{run_id}:{fan_id}",
            created_at=datetime.utcnow() - timedelta(hours=hours_old),
        ))
    return mid


async def _msg(aid: str, fan_id: int, mid: int) -> Message | None:
    async with get_session() as s:
        return await s.get(Message, (aid, fan_id, mid))


# ── case 1: sweep resolves mass_run_id and flips the placeholder rows ──
async def case_mass_sweep_flips_placeholder_rows():
    aid = "9301"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 1001, hours_old=10)
    run_id = await _add_run(aid, 1001)
    mid = await _add_placeholder(aid, 111, run_id, hours_old=10)
    await _add_placeholder(aid, 222, run_id, hours_old=10)

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [1001], fake.cancel_calls
    assert r["unsent"] == 1, r
    for fan in (111, 222):
        row = await _msg(aid, fan, mid)
        assert row is not None and row.is_unsent is True, (
            f"placeholder for fan {fan} not flipped — the seed will keep "
            f"resurrecting this unsent broadcast in the chat pane"
        )
        assert row.unsent_reason == "automation:unsend_messages", row.unsent_reason
    print("[ok] case_mass_sweep_flips_placeholder_rows")


# ── case 2: no mass_runs row → still unsends on OF, flips nothing, no crash ──
async def case_mass_sweep_without_run_still_unsends():
    aid = "9302"
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 2001, hours_old=10)  # manual OF-web blast: no MassRun

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [2001], fake.cancel_calls
    assert r["unsent"] == 1, r
    print("[ok] case_mass_sweep_without_run_still_unsends")


# ── case 3: the chat-pane DB seed serves only FRESH placeholders ──────
async def case_seed_endpoint_filters_stale_placeholders():
    aid, fan = "9303", 777
    await _seed_account(aid)
    run_fresh = await _add_run(aid, 3001)
    run_stale = await _add_run(aid, 3002)
    mid_fresh = await _add_placeholder(aid, fan, run_fresh, hours_old=0.5)
    mid_stale = await _add_placeholder(aid, fan, run_stale, hours_old=48)
    # A real (non-band) outbound row, much older than the 1h bridge window —
    # the cutoff must apply ONLY to the placeholder band.
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=88001,
                      direction="out", body="hey", media_count=0,
                      is_unsent=False,
                      created_at=datetime.utcnow() - timedelta(days=30)))

    resp = await messages_api.list_messages(aid, fan, limit=50, before_id=None)
    got = {m["message_id"] for m in resp["messages"]}

    assert mid_fresh in got, "fresh placeholder (live send bridge) must seed"
    assert mid_stale not in got, "stale placeholder leaked into the chat seed"
    assert 88001 in got, "real old row wrongly caught by the placeholder cutoff"
    print("[ok] case_seed_endpoint_filters_stale_placeholders")


# ── case 4: funnel step sends share mass_run_id but must NOT be flipped ──
async def case_sweep_spares_funnel_step_messages():
    aid, fan = "9304", 555
    await _seed_account(aid)
    fake = _use_fake()
    await _add_cast(aid, 4001, hours_old=10)
    run_id = await _add_run(aid, 4001)
    mid_ph = await _add_placeholder(aid, fan, run_id, hours_old=10)
    # A walker step-2 send: REAL per-chat message id, same mass_run_id,
    # funnel_step stamped — still live on OF after the queue cancel.
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=77002,
                      direction="out", body="step 2 tease", media_count=0,
                      is_unsent=False, mass_run_id=run_id, funnel_step=2,
                      created_at=datetime.utcnow() - timedelta(hours=9)))

    r = await run_once(aid, KIND, payload={"policy": {"mass_text_hours": 8}})

    assert fake.cancel_calls == [4001], fake.cancel_calls
    assert r["unsent"] == 1, r
    ph = await _msg(aid, fan, mid_ph)
    assert ph is not None and ph.is_unsent is True, "broadcast placeholder must flip"
    step = await _msg(aid, fan, 77002)
    assert step is not None and step.is_unsent is False, (
        "funnel step message wrongly flipped — it's still live on OF"
    )
    print("[ok] case_sweep_spares_funnel_step_messages")


# ── case 5: 6e15 ledger-tip band is exempt from the seed's 1h cutoff ──
async def case_seed_endpoint_keeps_ledger_tips():
    from transaction_ingest import _TIP_MSG_ID_BASE
    aid, fan = "9305", 888
    await _seed_account(aid)
    tip_mid = _TIP_MSG_ID_BASE + 42
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=tip_mid,
                      direction="in", body="tipped you $8", media_count=0,
                      is_tip=True, is_unsent=False,
                      created_at=datetime.utcnow() - timedelta(days=90)))

    resp = await messages_api.list_messages(aid, fan, limit=50, before_id=None)
    got = {m["message_id"] for m in resp["messages"]}
    assert tip_mid in got, (
        "90d-old ledger tip aged out of the seed — inline tip history is "
        "seed-only and must be permanent"
    )
    print("[ok] case_seed_endpoint_keeps_ledger_tips")


async def _main():
    await case_mass_sweep_flips_placeholder_rows()
    await case_mass_sweep_without_run_still_unsends()
    await case_seed_endpoint_filters_stale_placeholders()
    await case_sweep_spares_funnel_step_messages()
    await case_seed_endpoint_keeps_ledger_tips()
    print("all cases passed")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
