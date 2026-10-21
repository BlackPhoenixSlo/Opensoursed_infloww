#!/usr/bin/env python3
"""mass-lifecycle — answered-once dedup + discovery-close (R1/R2/R4).

Covers the seams added for the funnel mass-message lifecycle feature:

  case_ledger_written_at_discovery:
      reply_mass_funnel writes a funnel_responders row when it discovers a
      replier (idempotent across ticks).
  case_funnel_responder_ids_union:
      the dedup helper returns the ledger ∪ funnel_state fans, per-funnel; a
      random inbound-only fan is NOT included, and another funnel's answerer
      is NOT included.
  case_resolver_drops_responders:
      resolve_mass_audience(exclude_funnel_responders=fid) removes responders
      from the include set and reports skipped (∩ includes) + total.
  case_close_by_mass_run_id / case_close_by_queue_id:
      close_funnel_discovery_for_queue stamps discovery_closed_at both ways.
  case_close_idempotent_and_unresolved:
      a second close is a no-op; an unknown queue resolves to None (no throw).
  case_discovery_closed_gates_enrollment:
      with discovery_closed_at set, a PRE-cutoff reply enrolls, a POST-cutoff
      reply is ledger'd but NOT enrolled, and an already-tracked fan still
      advances (walker never gated).

Run: ./venv/bin/python service/tests/test_mass_lifecycle.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402

a11._STEP_GAP_S = 0  # skip the human typing pause in tests
from audiences import (  # noqa: E402
    close_funnel_discovery_for_queue, funnel_responder_ids, resolve_mass_audience,
)
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, Fan, FunnelResponder, FunnelState, MassMessageFunnel, MassRun, Message,
)

# A pinned broadcast date ages out of reply_mass_funnel's discovery window
# (`_DISCOVERY_WINDOW_DAYS`, added in 945a9e0) and turns this file red on a day
# nobody touched it — the failure reads as a walker regression rather than as an
# expired fixture. Anchoring to `utcnow()` keeps every ORDERING the cases below
# depend on while staying inside the window forever. Same reasoning and same
# shape as test_reply_mass_funnel.py's clock.
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)  # broadcast time
# The fake stamps its sends two hours after T0, preserving the original fixture's
# ordering: every outbound lands after the replies seeded at T0 + minutes.
SEND_AT = (T0 + timedelta(hours=2)).isoformat() + "+00:00"


class FakeOF:
    def __init__(self, uid: str = "999"):
        self.user_id = uid
        self.sent: list[dict] = []
        self._n = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._n += 1
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {"id": self._n, "text": f"<p>{text}</p>",
                "createdAt": SEND_AT}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_funnel(name: str, steps: list[dict] | None = None) -> int:
    async with get_session() as s:
        f = MassMessageFunnel(
            name=name, opening_message="How many strokes? 😈",
            media_indices="[]",
            steps_json=json.dumps(steps or [
                {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["m1"]},
            ]),
        )
        s.add(f)
        await s.flush()
        return int(f.id)


async def _seed_run(aid: str, fid: int, *, queue_id: int | None = None,
                    discovery_closed_at: datetime | None = None) -> int:
    async with get_session() as s:
        mr = MassRun(account_id=aid, funnel_id=fid, status="ok", recipient_count=1,
                     started_at=T0, queue_id=queue_id,
                     discovery_closed_at=discovery_closed_at)
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _msg(aid, fan, mid, direction, at, *, mass_run_id=None, body="hi") -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction=direction,
                      body=body, created_at=at, mass_run_id=mass_run_id))


async def _broadcast(aid, mr, fan) -> None:
    await _msg(aid, fan, 5_000_000_000_000_000 + mr * 100 + fan % 100, "out", T0,
               mass_run_id=mr, body="How many strokes? 😈")


async def _responder(aid, fid, fan) -> FunnelResponder | None:
    async with get_session() as s:
        return await s.get(FunnelResponder, (aid, fid, fan))


async def _state(mr, fan) -> FunnelState | None:
    async with get_session() as s:
        return await s.get(FunnelState, (mr, fan))


async def _run_closed(mr) -> datetime | None:
    async with get_session() as s:
        return (await s.get(MassRun, mr)).discovery_closed_at


# ── Discovery writes the responder ledger ─────────────────────────────

async def case_ledger_written_at_discovery():
    aid = "ml_a"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f1")
    mr = await _seed_run(aid, fid)
    await _broadcast(aid, mr, 1001)
    await _msg(aid, 1001, 7001, "in", T0 + timedelta(minutes=5), body="haha")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["discovered"] == 1, res
    row = await _responder(aid, fid, 1001)
    assert row is not None and row.mass_run_id == mr, row

    # Idempotent — a second tick doesn't error / duplicate.
    await run_once(aid, "reply_mass_funnel", payload={})
    async with get_session() as s:
        n = len((await s.execute(
            select(FunnelResponder.fan_id).where(
                FunnelResponder.account_id == aid, FunnelResponder.funnel_id == fid)
        )).all())
    assert n == 1, n


# ── The dedup helper: ledger ∪ state, per-funnel ──────────────────────

async def case_funnel_responder_ids_union():
    aid = "ml_b"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f2")
    other = await _seed_funnel("ml_other")
    mr = await _seed_run(aid, fid)
    # 2001 via ledger, 2002 via funnel_state, 2003 answered a DIFFERENT funnel.
    async with get_session() as s:
        s.add(FunnelResponder(account_id=aid, funnel_id=fid, fan_id=2001,
                              mass_run_id=mr, first_replied_at=T0))
        s.add(FunnelState(mass_run_id=mr, fan_id=2002, current_step=1,
                          status="pending", updated_at=T0))
        omr = MassRun(account_id=aid, funnel_id=other, status="ok",
                      recipient_count=1, started_at=T0)
        s.add(omr)
        await s.flush()
        s.add(FunnelResponder(account_id=aid, funnel_id=other, fan_id=2003,
                              mass_run_id=int(omr.id), first_replied_at=T0))

    got = await funnel_responder_ids(aid, fid)
    assert got == {2001, 2002}, got  # 2003 (other funnel) excluded


# ── resolve_mass_audience subtracts responders + reports counts ───────

async def case_resolver_drops_responders():
    aid = "ml_c"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f3")
    mr = await _seed_run(aid, fid)
    async with get_session() as s:
        s.add(FunnelResponder(account_id=aid, funnel_id=fid, fan_id=3001,
                              mass_run_id=mr, first_replied_at=T0))

    r = await resolve_mass_audience(
        aid, included_users=[3001, 3002, 3003], exclude_funnel_responders=fid)
    assert 3001 not in r["included_users"], r
    assert set(r["included_users"]) == {3002, 3003}, r
    assert r["skipped_funnel_responders"] == [3001], r
    assert r["funnel_responders_total"] == 1, r
    # No funnel id → no dedup.
    r2 = await resolve_mass_audience(aid, included_users=[3001, 3002])
    assert set(r2["included_users"]) == {3001, 3002}, r2
    assert r2["skipped_funnel_responders"] == [], r2


# ── close_funnel_discovery_for_queue ──────────────────────────────────

async def case_close_by_mass_run_id():
    aid = "ml_d"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f4")
    mr = await _seed_run(aid, fid, queue_id=555)
    closed = await close_funnel_discovery_for_queue(aid, mass_run_id=mr)
    assert closed == mr, closed
    assert await _run_closed(mr) is not None


async def case_close_by_queue_id():
    aid = "ml_e"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f5")
    mr = await _seed_run(aid, fid, queue_id=777)
    closed = await close_funnel_discovery_for_queue(aid, queue_id=777)
    assert closed == mr, closed
    assert await _run_closed(mr) is not None


async def case_close_idempotent_and_unresolved():
    aid = "ml_f"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f6")
    mr = await _seed_run(aid, fid, queue_id=888)
    first = await close_funnel_discovery_for_queue(aid, queue_id=888)
    stamp1 = await _run_closed(mr)
    again = await close_funnel_discovery_for_queue(aid, queue_id=888)
    stamp2 = await _run_closed(mr)
    assert first == mr and again == mr, (first, again)
    assert stamp1 == stamp2, "idempotent — stamp unchanged"
    # Unknown queue → None, no throw.
    assert await close_funnel_discovery_for_queue(aid, queue_id=999999) is None


# ── discovery_closed_at gates NEW enrollment (not the walker) ─────────

async def case_discovery_closed_gates_enrollment():
    aid = "ml_g"
    await _seed_account(aid)
    fid = await _seed_funnel("ml_f7")
    cutoff = T0 + timedelta(minutes=30)          # first mass unsent at 10:30
    mr = await _seed_run(aid, fid, discovery_closed_at=cutoff)
    # PRE-cutoff replier (10:20) → enrolls; POST-cutoff replier (10:40) → not.
    await _broadcast(aid, mr, 4001)
    await _msg(aid, 4001, 7401, "in", T0 + timedelta(minutes=20), body="pre")
    await _broadcast(aid, mr, 4002)
    await _msg(aid, 4002, 7402, "in", T0 + timedelta(minutes=40), body="post")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["discovered"] == 1, res  # only the pre-cutoff fan enrolled

    assert await _state(mr, 4001) is not None, "pre-cutoff reply must enroll"
    assert await _state(mr, 4002) is None, "post-cutoff reply must NOT enroll"
    # BOTH answered → both are in the durable dedup ledger regardless of cutoff.
    assert await _responder(aid, fid, 4001) is not None, "pre-cutoff ledger'd"
    assert await _responder(aid, fid, 4002) is not None, "post-cutoff still ledger'd"


_harness.run(
    case_ledger_written_at_discovery,
    case_funnel_responder_ids_union,
    case_resolver_drops_responders,
    case_close_by_mass_run_id,
    case_close_by_queue_id,
    case_close_idempotent_and_unresolved,
    case_discovery_closed_gates_enrollment,
)
