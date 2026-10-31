#!/usr/bin/env python3
"""
A11 reply_mass_funnel — automation tests (spec 11_reply_mass_funnel.md + 15).

Acceptance the prompt calls out: a funnel advances ONE step per eligible reply,
and RESUMES from `funnel_state` after a restart. These cases drive the automation
through the real `run_once` dispatcher (registry wiring + automation_runs are
exercised) against a fake OFClient — no network, no DOM. Reply detection is
DB-first (the WS pump writes inbound), so we seed `messages` rows directly.

  case_discover_and_advance:
      a broadcast recipient who replied is discovered (funnel_state step 0) and
      advanced one step — the step's two messages are sent + persisted (out,
      mass_run_id + funnel_step), funnel_state.current_step → 1.
  case_resume_after_restart:
      run_once advances 0→1; then a SECOND run_once (a "restart" — no in-memory
      carry-over) reads funnel_state from the DB and advances 1→2 on a fresh
      reply. Proves resume.
  case_no_new_reply_reschedules:
      a tracked state that's due but whose fan hasn't replied since our last
      funnel message does NOT advance — check_count bumps, next_check_at is
      pushed out (the [2,4,10] schedule).
  case_ppv_step_is_terminal:
      a paid_ppv step sends with a price + this model's per-account media and
      marks the state `done`.
  case_ppv_media_is_per_account:
      the SAME funnel sends each model its OWN vault media (per-account binding),
      and clamps `previews` to the bound set.
  case_ppv_media_legacy_fallback:
      a funnel with no per-account media row still sends its legacy in-step
      `media_files` (the rollout fallback).
  case_generated_step_uses_llm:
      a step with a `prompt` (no static messages) is composed via llm_client and
      that generated text is what gets sent.
  case_dry_run_sends_nothing:
      dry_run resolves text but neither sends nor advances the state machine.
  case_non_replier_not_discovered:
      a recipient who never replied stays out of the funnel entirely.
  case_blank_ppv_blocked:
      #1 pre-send guard — a paid_ppv step with no resolved media never sends a
      blank paywall; `blocked` bumps, the state backs off and stays pending.
  case_offer_taken_halts:
      #30 offer-taken — a fan who unlocked a PPV since the broadcast halts the
      funnel (done, `converted`) with no further send.
  case_offer_not_taken_still_walks:
      #30 control — an OLD purchase (predating the broadcast) is not a conversion;
      the funnel still advances.

Run: ./venv/bin/python service/tests/test_reply_mass_funnel.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402 — module under test

a11._STEP_GAP_S = 0  # skip the human typing-pause sleep in tests (kept for prod)
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account,
    AutomationRun,
    Fan,
    FanLease,
    FunnelAccountMedia,
    FunnelResponder,
    FunnelState,
    MassMessageFunnel,
    MassRun,
    Message,
    SkipList,
)

OWN_ID = "999"
# ⚠️ The clock is RELATIVE, not a literal calendar date. reply_mass_funnel bounds
# discovery to broadcasts younger than `_DISCOVERY_WINDOW_DAYS`, so a fixture
# pinned to a fixed date would quietly age out of that window and turn this whole
# file red on a day nobody touched it — the failure would look like a regression
# in the walker rather than an expired fixture. Anchoring to `utcnow()` keeps the
# ORDERING every case here depends on while staying inside the window forever.
# Everything below is expressed as an offset from T0 for the same reason.
T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)   # broadcast time
T_REPLY1 = T0 + timedelta(minutes=5)           # fan's first reply (to the opener)
# The fake stamps its sends well after the seeded replies so "last funnel out"
# always lands after the reply that triggered it.
SEND_AT = (T0 + timedelta(hours=2)).isoformat() + "+00:00"


# ── Fakes (no network) ────────────────────────────────────────────────

class FakeOF:
    """Records sends (with kwargs, so PPV price/media is assertable) and echoes a
    real-looking OF message object with a unique id + a late createdAt."""

    def __init__(self, user_id: str = OWN_ID):
        self.user_id = user_id
        self.sent: list[dict] = []
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {"id": self._next_id, "text": f"<p>{text}</p>", "createdAt": SEND_AT}


def _strip(s: str) -> str:
    return (s or "").replace("<p>", "").replace("</p>", "").strip()


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "generated nudge 💕") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]


# ── Seed helpers ──────────────────────────────────────────────────────

async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_funnel(name: str, steps: list[dict]) -> int:
    async with get_session() as s:
        f = MassMessageFunnel(
            name=name, opening_message="How many strokes? 😈",
            media_indices="[]", steps_json=json.dumps(steps),
        )
        s.add(f)
        await s.flush()
        return int(f.id)


async def _seed_account_media(aid: str, funnel_id: int, *,
                              opening: list[int] | None = None,
                              steps_media: dict | None = None) -> None:
    """Bind this model's per-account funnel MEDIA (FunnelAccountMedia). Funnel TEXT
    is shared; vault ids are per-account, so the PPV media lives here, not on the
    step. steps_media is keyed by step NUMBER → {media_files, previews}."""
    async with get_session() as s:
        s.add(FunnelAccountMedia(
            funnel_id=funnel_id, account_id=aid,
            opening_media_ids=json.dumps(opening or []),
            steps_media_json=json.dumps(steps_media or {}),
        ))


async def _seed_mass_run(aid: str, funnel_id: int, status: str = "ok",
                         started_at: datetime | None = None) -> int:
    async with get_session() as s:
        mr = MassRun(account_id=aid, funnel_id=funnel_id, status=status,
                     recipient_count=1, started_at=started_at or T0)
        s.add(mr)
        await s.flush()
        return int(mr.id)


async def _seed_msg(aid: str, fan_id: int, mid: int, direction: str,
                    created_at: datetime, *, mass_run_id: int | None = None,
                    body: str = "hi") -> None:
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=mid, direction=direction,
            body=body, created_at=created_at, mass_run_id=mass_run_id,
        ))


async def _broadcast(aid: str, mass_run_id: int, fan_id: int) -> None:
    """The optimistic outbound row A10 writes per recipient (mass_run_id-tagged)."""
    await _seed_msg(aid, fan_id, 5_000_000_000_000_000 + mass_run_id, "out", T0,
                    mass_run_id=mass_run_id, body="How many strokes? 😈")


async def _seed_paid_ppv(aid: str, fan_id: int, mid: int, *,
                         purchased_at: datetime) -> None:
    """An outbound PPV the fan UNLOCKED (is_paid=True). Untagged (mass_run_id
    None) so it doesn't count as a funnel-out — it's the 'offer taken' signal the
    #30 halt reads (their own funnel PPV or another automation's)."""
    async with get_session() as s:
        s.add(Message(
            account_id=aid, fan_id=fan_id, message_id=mid, direction="out",
            body="unlock me", price_cents=2000, is_paid=True,
            purchased_at=purchased_at, created_at=purchased_at,
        ))


async def _state(mass_run_id: int, fan_id: int) -> FunnelState | None:
    async with get_session() as s:
        return await s.get(FunnelState, (mass_run_id, fan_id))


async def _seed_state(mass_run_id: int, fan_id: int, *, current_step: int,
                      check_count: int = 0, hops: int = 0, status: str = "pending",
                      next_check_at: datetime | None = None) -> None:
    """Directly seed a funnel_state row (skips discovery) so a branching case can
    start a fan mid-storyline at a chosen step/check_count/hops."""
    async with get_session() as s:
        s.add(FunnelState(
            mass_run_id=mass_run_id, fan_id=fan_id, current_step=current_step,
            check_count=check_count, hops=hops, status=status,
            next_check_at=next_check_at or (datetime.utcnow() - timedelta(minutes=1)),
        ))


async def _force_due(aid: str, mass_run_id: int, fan_id: int) -> None:
    """Simulate time passing: pull next_check_at into the past so the state is due,
    AND expire the W3 post-send cooldown the previous step set (30 min would have
    elapsed in a real run) — else the next tick skips the fan as still resting."""
    async with get_session() as s:
        await s.execute(
            update(FunnelState)
            .where(FunnelState.mass_run_id == mass_run_id, FunnelState.fan_id == fan_id)
            .values(next_check_at=datetime.utcnow() - timedelta(minutes=1))
        )
        await s.execute(
            update(Fan)
            .where(Fan.account_id == aid, Fan.fan_id == fan_id)
            .values(automation_paused_until=None)
        )
    # The previous step KEPT its fan-lease (W3: released only by TTL); 15 min of
    # the simulated gap clears it too, so the next tick can re-acquire.
    await ax.release_fan_lease(aid, fan_id)


async def _funnel_out_msgs(aid: str, fan_id: int) -> list[Message]:
    async with get_session() as s:
        return (await s.execute(
            select(Message).where(
                Message.account_id == aid, Message.fan_id == fan_id,
                Message.direction == "out", Message.funnel_step.is_not(None),
            ).order_by(Message.message_id)
        )).scalars().all()


# Steps are TEXT-ONLY now — the PPV step carries copy + price but NO media_files
# (vault ids are per-account, bound via FunnelAccountMedia / _seed_account_media).
_TWO_STEP = [
    {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["m1a", "m1b"]},
    {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["m2a"]},
    {"step": 3, "type": "paid_ppv", "price": 24, "messages": ["open this 😈"]},
]


# ── 🔴 Acceptance: discover a replier and advance one step ────────────

async def case_discover_and_advance():
    aid = "acc_f1"
    await _seed_account(aid)
    fid = await _seed_funnel("f1", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 1001)
    await _seed_msg(aid, 1001, 7001, "in", T_REPLY1, body="haha a lot")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert res["discovered"] == 1, res
    assert res["advanced"] == 1, res

    st = await _state(mr, 1001)
    assert st is not None and st.current_step == 1, st
    assert st.status == "pending", st

    # Step 1's two messages were sent + persisted (out, mass_run + funnel_step).
    out = await _funnel_out_msgs(aid, 1001)
    assert len(out) == 2, [m.body for m in out]
    assert all(m.mass_run_id == mr and m.funnel_step == 1 for m in out), out
    # OF echoes bodies wrapped in <p>…</p> (the fake mirrors that); persisted as-is.
    assert {_strip(m.body) for m in out} == {"m1a", "m1b"}, [m.body for m in out]

    runs = await _runs(aid)
    assert len(runs) == 1 and runs[0].status == "ok", runs

    # W3 cadence guard: a confirmed step RELEASES the lease and sets only a SHORT
    # cooldown (< the 2-min smallest step interval), so the next step due via
    # next_check_at isn't clobbered by the generic 30-min rest / 900s lease.
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 1001)) is None, "lease released after step"
        until = (await s.get(Fan, (aid, 1001))).automation_paused_until
    assert until is not None and until < datetime.utcnow() + timedelta(minutes=2), until


async def _runs(aid: str) -> list[AutomationRun]:
    async with get_session() as s:
        return (await s.execute(
            select(AutomationRun).where(AutomationRun.account_id == aid)
        )).scalars().all()


# ── W3: a fan on post-send cooldown is skipped (before the lease) ─────

async def case_cooldown_skips_funnel():
    aid = "acc_f1b"
    await _seed_account(aid)
    fid = await _seed_funnel("f1b", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 1101)
    await _seed_msg(aid, 1101, 7011, "in", T_REPLY1, body="haha a lot")
    fake = _use_fake()

    # Another automation messaged 1101 moments ago → it's resting; even though the
    # funnel discovers it as a replier, the step send must be held off this tick.
    await ax.start_fan_cooldown(aid, 1101)

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["skipped_cooldown"] == 1, res
    assert res["advanced"] == 0, res
    assert fake.sent == [], fake.sent


# ── 🔴 Acceptance: resume from funnel_state after restart ─────────────

async def case_resume_after_restart():
    aid = "acc_f2"
    await _seed_account(aid)
    fid = await _seed_funnel("f2", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 2001)
    await _seed_msg(aid, 2001, 7101, "in", T_REPLY1, body="reply 1")
    _use_fake()

    r1 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r1["advanced"] == 1, r1
    assert (await _state(mr, 2001)).current_step == 1, "step 0→1"

    # Restart + a new reply AFTER our step-1 messages (SEND_AT = 12:00).
    await _seed_msg(aid, 2001, 7102, "in", T0 + timedelta(hours=3), body="reply 2")
    await _force_due(aid, mr, 2001)

    r2 = await run_once(aid, "reply_mass_funnel", payload={})  # the "restart" sweep
    assert r2["advanced"] == 1, r2
    st = await _state(mr, 2001)
    assert st.current_step == 2, f"resumed 1→2 from DB, got {st.current_step}"


# ── No new reply → reschedule, don't advance ──────────────────────────

async def case_no_new_reply_reschedules():
    aid = "acc_f3"
    await _seed_account(aid)
    fid = await _seed_funnel("f3", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 3001)
    await _seed_msg(aid, 3001, 7201, "in", T_REPLY1, body="reply 1")
    _use_fake()

    await run_once(aid, "reply_mass_funnel", payload={})  # advances 0→1
    assert (await _state(mr, 3001)).current_step == 1

    # No reply after the step-1 messages; make it due again.
    await _force_due(aid, mr, 3001)
    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["waiting"] == 1, res
    assert res["advanced"] == 0, res

    st = await _state(mr, 3001)
    assert st.current_step == 1, "no advance without a fresh reply"
    assert st.check_count >= 1, st
    assert st.next_check_at is not None and st.next_check_at > datetime.utcnow(), st


# ── PPV step is terminal ──────────────────────────────────────────────

async def case_ppv_step_is_terminal():
    aid = "acc_f4"
    await _seed_account(aid)
    # Single PPV step (text-only) so one advance lands on the terminal step; the
    # MEDIA is bound per-account, keyed by the step number.
    fid = await _seed_funnel("f4", [
        {"step": 1, "type": "paid_ppv", "price": 30, "messages": ["unlock me"]},
    ])
    await _seed_account_media(aid, fid, steps_media={"1": {"media_files": [888]}})
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 4001)
    await _seed_msg(aid, 4001, 7301, "in", T_REPLY1, body="yes")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1 and res["completed"] == 1, res

    st = await _state(mr, 4001)
    assert st.current_step == 1 and st.status == "done", st

    # The send carried price (shared step) + this model's per-account media.
    assert fake.sent and fake.sent[0]["price"] == 30, fake.sent
    assert fake.sent[0]["media_files"] == [888], fake.sent
    out = await _funnel_out_msgs(aid, 4001)
    assert len(out) == 1 and out[0].price_cents == 3000, out


# ── Per-account media: two models, same funnel, different vault ids ───

async def case_ppv_media_is_per_account():
    """Same funnel TEXT, two models → each PPV send carries that MODEL's own vault
    media (the whole point: a media id from model A is meaningless in model B).
    Also clamps `previews` to the bound media set."""
    fid = await _seed_funnel("f_per_acct", [
        {"step": 1, "type": "paid_ppv", "price": 20, "messages": ["unlock me"]},
    ])
    for aid, mid, fan, msg in (
        ("acc_fa", 1111, 41001, 7411),
        ("acc_fb", 2222, 42001, 7421),
    ):
        await _seed_account(aid)
        await _seed_account_media(
            aid, fid, steps_media={"1": {"media_files": [mid, 3333], "previews": [mid]}})
        mr = await _seed_mass_run(aid, fid)
        await _broadcast(aid, mr, fan)
        await _seed_msg(aid, fan, msg, "in", T_REPLY1, body="yes")
        fake = _use_fake()

        res = await run_once(aid, "reply_mass_funnel", payload={})
        assert res["advanced"] == 1, (aid, res)
        assert fake.sent[0]["media_files"] == [mid, 3333], (aid, fake.sent)
        assert fake.sent[0]["previews"] == [mid], (aid, fake.sent)


# ── Back-compat: legacy in-step media still sends when no per-account row ──

async def case_ppv_media_legacy_fallback():
    """A funnel not yet seeded into funnel_account_media still sends its legacy
    in-step `media_files` (the rollout fallback)."""
    aid = "acc_f_legacy"
    await _seed_account(aid)
    fid = await _seed_funnel("f_legacy", [
        {"step": 1, "type": "paid_ppv", "price": 15, "media_files": [555],
         "messages": ["unlock me"]},
    ])  # NO _seed_account_media → fall back to the step's own media
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 43001)
    await _seed_msg(aid, 43001, 7431, "in", T_REPLY1, body="yes")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1, res
    assert fake.sent[0]["media_files"] == [555], fake.sent


# ── Generated step composes via llm_client ────────────────────────────

async def case_generated_step_uses_llm():
    aid = "acc_f5"
    await _seed_account(aid)
    fid = await _seed_funnel("f5", [
        {"step": 1, "prompt": "tease him about losing count"},  # no static messages
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 5001)
    await _seed_msg(aid, 5001, 7401, "in", T_REPLY1, body="lots")
    fake = _use_fake()
    _patch_llm("bet you lose count fast 😏")

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1, res
    assert fake.sent and fake.sent[0]["text"] == "bet you lose count fast 😏", fake.sent

    out = await _funnel_out_msgs(aid, 5001)
    assert len(out) == 1 and _strip(out[0].body) == "bet you lose count fast 😏", out


# ── dry_run: resolve but neither send nor advance ─────────────────────

async def case_dry_run_sends_nothing():
    aid = "acc_f6"
    await _seed_account(aid)
    fid = await _seed_funnel("f6", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 6001)
    await _seed_msg(aid, 6001, 7501, "in", T_REPLY1, body="hey")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={"dry_run": True})
    assert res["discovered"] == 1, res
    assert res["advanced"] == 1, res  # counted as would-send
    assert fake.sent == [], "dry run must not send"

    # wave6 B2: discovery writes nothing either — the responder ledger would
    # drop the fan from every later send of this funnel, for good.
    assert await _state(mr, 6001) is None, "dry run must not enroll the fan"
    async with get_session() as s:
        ledger = (await s.execute(select(FunnelResponder).where(
            FunnelResponder.account_id == aid))).scalars().all()
    assert ledger == [], "dry run must not write the responder ledger"
    assert (await _funnel_out_msgs(aid, 6001)) == [], "dry run writes no message row"

    # An enrolled fan who hasn't replied again is walked but not rescheduled.
    await _seed_state(mr, 6002, current_step=1, check_count=0)
    await _seed_msg(aid, 6002, 7502, "out", T_REPLY1, mass_run_id=mr, body="m1a")
    before = await _state(mr, 6002)
    res = await run_once(aid, "reply_mass_funnel", payload={"dry_run": True})
    assert res["waiting"] == 1, res
    after = await _state(mr, 6002)
    assert (after.check_count, after.next_check_at) == (
        before.check_count, before.next_check_at), "dry run moved a state"


# ── A recipient who never replied never enters the funnel ─────────────

async def case_non_replier_not_discovered():
    aid = "acc_f7"
    await _seed_account(aid)
    fid = await _seed_funnel("f7", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 7001)  # got the broadcast, never replied
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["discovered"] == 0, res
    assert res["advanced"] == 0, res
    assert await _state(mr, 7001) is None, "non-replier must not be tracked"


async def case_unreachable_fan_ends_state():
    """A deleted/blocked fan (step send 404s 'User not found') must not stay due
    forever — that would regenerate the step texts (an LLM call on generated
    steps) every tick. The failure quarantines the fan (skip_list 'unreachable')
    AND marks THIS funnel state done, so the next tick processes nothing."""
    aid = "acc_f_unreach"
    await _seed_account(aid)
    fid = await _seed_funnel("f_unreach", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 8101)
    await _seed_msg(aid, 8101, 7081, "in", T_REPLY1, body="haha a lot")
    fake = _use_fake()
    def _raise(chat_id, text, **kw):
        raise Exception(
            f"404 for https://onlyfans.com/api2/v2/chats/{chat_id}/messages\n"
            '{"error":{"code":0,"message":"User not found"}}'
        )
    fake.send_message = _raise
    calls: list[int] = []
    async def _fake_chat(**kw):
        calls.append(kw.get("fan_id"))
        return SimpleNamespace(content="generated nudge 💕")
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]

    r1 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r1["errors"] == 1 and r1["advanced"] == 0, r1
    st = await _state(mr, 8101)
    assert st is not None and st.status == "done", st
    async with get_session() as s:
        row = await s.get(SkipList, (aid, 8101))
        assert row is not None and row.reason == "unreachable", row

    r2 = await run_once(aid, "reply_mass_funnel", payload={})
    assert r2["errors"] == 0 and r2["advanced"] == 0 and r2["discovered"] == 0, r2
    assert calls == [], ("verbatim steps never hit the LLM; none after quarantine", calls)


async def case_list_audience_adoption():
    """A `user_lists` broadcast writes NO tagged per-fan rows (OF resolves the
    list server-side; the WS pump skips outbound). The scrape pump later
    backfills the opener into each fan's chat UNTAGGED. The sweep must ADOPT
    those rows (normalized body == opener within the started_at window), then
    discover + advance repliers — honouring the run's excluded_users."""
    aid = "acc_f_adopt"
    await _seed_account(aid)
    fid = await _seed_funnel("f_adopt", _TWO_STEP)
    async with get_session() as s:
        mr_row = MassRun(
            account_id=aid, funnel_id=fid, status="ok", recipient_count=0,
            started_at=T0,
            audience_filter=json.dumps({"user_lists": ["fans"],
                                        "excluded_users": [9203]}),
        )
        s.add(mr_row)
        await s.flush()
        mr = int(mr_row.id)
    t_out = T0 + timedelta(minutes=1)
    # 9201: scraped opener (with OF's <p> wrap) + replied → adopt + advance.
    await _seed_msg(aid, 9201, 9_001, "out", t_out, body="<p>How many strokes? 😈</p>")
    await _seed_msg(aid, 9201, 9_002, "in", T_REPLY1, body="haha a lot")
    # 9202: replied, but their outbound is some other text → NOT adopted.
    await _seed_msg(aid, 9202, 9_003, "out", t_out, body="hey you 💕")
    await _seed_msg(aid, 9202, 9_004, "in", T_REPLY1, body="hi")
    # 9203: opener + reply, but excluded from the broadcast → NOT adopted.
    await _seed_msg(aid, 9203, 9_005, "out", t_out, body="How many strokes? 😈")
    await _seed_msg(aid, 9203, 9_006, "in", T_REPLY1, body="yo")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert res["discovered"] == 1, res
    assert res["advanced"] == 1, res

    st = await _state(mr, 9201)
    assert st is not None and st.current_step == 1, st
    assert await _state(mr, 9202) is None, "non-opener outbound must not be adopted"
    assert await _state(mr, 9203) is None, "excluded fan must not be adopted"

    # The scraped opener row is now tagged to the run (the adoption write).
    async with get_session() as s:
        m = await s.get(Message, (aid, 9201, 9_001))
        assert m is not None and m.mass_run_id == mr, m
    # Idempotent: a second sweep adopts/discovers nothing new.
    res2 = await run_once(aid, "reply_mass_funnel", payload={})
    assert res2["discovered"] == 0, res2


# ── #1 Pre-send guard: a PPV with no resolved media never sends a blank paywall ──

async def case_blank_ppv_blocked():
    """A paid_ppv step with NO media bound for this account (and no legacy in-step
    media) must NOT send a blank paywall. The pre-send guard blocks it: `blocked`
    bumps, nothing is sent, and the state stays pending (backed off) so a later
    media fix can resume it."""
    aid = "acc_f_blank"
    await _seed_account(aid)
    fid = await _seed_funnel("f_blank", [
        {"step": 1, "type": "paid_ppv", "price": 20, "messages": ["unlock me"]},
    ])  # no _seed_account_media + no in-step media_files → nothing to attach
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 44001)
    await _seed_msg(aid, 44001, 7441, "in", T_REPLY1, body="yes")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["blocked"] == 1, res
    assert res["advanced"] == 0, res
    assert fake.sent == [], "blank PPV must not send a blank paywall"

    st = await _state(mr, 44001)
    assert st is not None and st.current_step == 0 and st.status == "pending", st
    assert st.last_error and "ppv_without_media" in st.last_error, st
    assert st.next_check_at is not None and st.next_check_at > datetime.utcnow(), st


# ── #30 Offer taken: a fan who bought halts the funnel (no more nudges) ──

async def case_offer_taken_halts():
    """A recipient who UNLOCKED a PPV since the broadcast has converted — the
    funnel halts (done) and sends NOTHING this tick, even though they replied and
    are otherwise due to advance. Prevents nudging someone who already bought."""
    aid = "acc_f_taken"
    await _seed_account(aid)
    fid = await _seed_funnel("f_taken", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 45001)
    await _seed_msg(aid, 45001, 7451, "in", T_REPLY1, body="omg yes")
    # Bought a PPV after the broadcast (T0=10:00). Their own funnel offer OR
    # another automation's — either way, stop the funnel.
    await _seed_paid_ppv(aid, 45001, 7452, purchased_at=T0 + timedelta(minutes=10))
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["converted"] == 1, res
    assert res["advanced"] == 0, res
    assert fake.sent == [], "a converted fan gets no funnel step"

    st = await _state(mr, 45001)
    assert st is not None and st.status == "done", st
    assert st.current_step == 0, "halted before advancing"
    assert st.last_error == "offer_taken", st


async def case_offer_not_taken_still_walks():
    """Control for #30: a fan whose only paid PPV predates the broadcast (an OLD
    purchase) is NOT treated as 'offer taken' — the funnel still advances."""
    aid = "acc_f_oldbuy"
    await _seed_account(aid)
    fid = await _seed_funnel("f_oldbuy", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 46001)
    await _seed_msg(aid, 46001, 7461, "in", T_REPLY1, body="hey")
    # Purchase BEFORE the broadcast → not counted (baseline is started_at=T0).
    await _seed_paid_ppv(aid, 46001, 7462, purchased_at=T0 - timedelta(hours=25))
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["converted"] == 0, res
    assert res["advanced"] == 1, res
    st = await _state(mr, 46001)
    assert st is not None and st.current_step == 1 and st.status == "pending", st


# ══════════════════════════════════════════════════════════════════════
# Branching storylines (wf/storyline): a step's optional `next` map chooses
# the next step from the fan's reply instead of always advancing +1.
# ══════════════════════════════════════════════════════════════════════

# A 5-step funnel where step 1 branches to step 5 on purchase (else falls +1).
_BOUGHT_BRANCH = [
    {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"],
     "next": {"bought": 5}},
    {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"]},
    {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    {"step": 4, "check_intervals_min": [2, 4, 10], "messages": ["s4"]},
    {"step": 5, "check_intervals_min": [2, 4, 10], "messages": ["s5"]},
]


async def case_next_bought_jumps_else_falls_through():
    """next={"bought":5}: a fan who UNLOCKED a PPV since the broadcast is routed
    to step 5 (index 4) with NO step sent (branched); a fan who did NOT buy just
    falls through to the linear +1 (step sent, current_step→1)."""
    aid = "acc_br_bought"
    await _seed_account(aid)
    fid = await _seed_funnel("br_bought", _BOUGHT_BRANCH)
    mr = await _seed_mass_run(aid, fid)
    # Fan A bought after the broadcast; Fan B replied but never bought.
    await _broadcast(aid, mr, 51001)
    await _seed_msg(aid, 51001, 7601, "in", T_REPLY1, body="omg yes")
    await _seed_paid_ppv(aid, 51001, 7602, purchased_at=T0 + timedelta(minutes=10))
    await _broadcast(aid, mr, 51002)
    await _seed_msg(aid, 51002, 7603, "in", T_REPLY1, body="haha maybe")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["branched"] == 1, res     # fan A jumped on purchase
    assert res["advanced"] == 1, res     # fan B walked linearly
    assert res["converted"] == 0, res    # NOT the legacy halt — it branched

    # Fan A: routed to step 5 (index 4), still pending, and NOTHING sent.
    a = await _state(mr, 51001)
    assert a is not None and a.current_step == 4 and a.status == "pending", a
    assert await _funnel_out_msgs(aid, 51001) == [], "bought-branch sends no step"
    # Fan B: no bought target hit → linear +1, step 1's copy sent.
    b = await _state(mr, 51002)
    assert b is not None and b.current_step == 1, b
    out_b = await _funnel_out_msgs(aid, 51002)
    assert len(out_b) == 1 and _strip(out_b[0].body) == "s1", out_b
    assert {m["fan_id"] for m in fake.sent} == {51002}, fake.sent


async def case_next_ignored_branch_on_no_reply():
    """next={"ignored":3}: once the reply WINDOW is exhausted (the check at the end
    of the last interval, check_count >= len-1) with no fresh reply, the fan is
    routed to the ignored target — not rescheduled forever."""
    aid = "acc_br_ignored"
    await _seed_account(aid)
    fid = await _seed_funnel("br_ignored", [
        {"step": 1, "check_intervals_min": [2], "messages": ["s1"]},
        {"step": 2, "check_intervals_min": [2], "messages": ["s2"],
         "next": {"ignored": 3}},
        {"step": 3, "check_intervals_min": [2], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 52001)  # last funnel-out = broadcast (10:00)
    # Mid-storyline at step 2 (index 1), window already exhausted (len[2]==1).
    await _seed_state(mr, 52001, current_step=1, check_count=1)
    fake = _use_fake()  # no inbound after the broadcast → the fan is "ignoring"

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["branched"] == 1, res
    assert res["waiting"] == 0, res      # took the branch, did NOT reschedule
    assert fake.sent == [], "ignored branch sends nothing"

    st = await _state(mr, 52001)
    assert st is not None and st.current_step == 2, st  # step 3 = index 2
    assert st.status == "pending", st


async def case_next_ignored_waits_inside_window():
    """Control for the ignored branch: while STILL inside the reply window
    (check_count < len(intervals) - 1) a non-replier is rescheduled as before —
    the branch must not fire prematurely."""
    aid = "acc_br_ignored_wait"
    await _seed_account(aid)
    fid = await _seed_funnel("br_ignored_wait", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"]},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"],
         "next": {"ignored": 3}},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 52101)
    # Window = step-1 intervals [2,4,10] (len 3); check_count 0 → not exhausted.
    await _seed_state(mr, 52101, current_step=1, check_count=0)
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["waiting"] == 1 and res["branched"] == 0, res
    st = await _state(mr, 52101)
    assert st is not None and st.current_step == 1, st  # did NOT branch
    assert st.check_count == 1, st


async def case_next_keyword_branch_on_reply():
    """next.keyword: a matching WORD in the fan's reply routes past the default.
    Fan K says 'more' → jump to step 3; Fan D says something else → default step 2.
    Both get the current step's copy first (they replied)."""
    aid = "acc_br_kw"
    await _seed_account(aid)
    fid = await _seed_funnel("br_kw", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"],
         "next": {"keyword": {"more": 3}, "default": 2}},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"]},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 53001)
    await _seed_msg(aid, 53001, 7701, "in", T_REPLY1, body="give me MORE please")
    await _broadcast(aid, mr, 53002)
    await _seed_msg(aid, 53002, 7702, "in", T_REPLY1, body="meh idk")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 2, res  # both replied → both sent step 1

    k = await _state(mr, 53001)
    assert k is not None and k.current_step == 2, ("keyword→step3(index2)", k)
    d = await _state(mr, 53002)
    assert d is not None and d.current_step == 1, ("default→step2(index1)", d)
    # The SENT step (index 0) is persisted: the reply-wait paces on it, not on c-1.
    assert (k.last_sent_step, d.last_sent_step) == (0, 0), (k.last_sent_step, d.last_sent_step)
    # Both received step 1's copy before the branch.
    assert _strip((await _funnel_out_msgs(aid, 53001))[0].body) == "s1"
    assert _strip((await _funnel_out_msgs(aid, 53002))[0].body) == "s1"


async def case_next_keyword_ignores_bare_reaction():
    """A lone reaction ('🔥') is NOT substantive, so it can't trip a keyword branch
    even if the emoji happened to be a keyword-ish token — it falls to default."""
    aid = "acc_br_kw_react"
    await _seed_account(aid)
    fid = await _seed_funnel("br_kw_react", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["s1"],
         "next": {"keyword": {"more": 3}, "default": 2}},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["s2"]},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["s3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 53101)
    await _seed_msg(aid, 53101, 7711, "in", T_REPLY1, body="🔥")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["advanced"] == 1, res
    st = await _state(mr, 53101)
    assert st is not None and st.current_step == 1, ("bare reaction → default", st)


async def case_loop_guard_halts_self_reference():
    """A self-referential `next` (step 1 → step 1) forms a cycle. The hop counter
    halts the fan past _MAX_HOPS (done + 'loop_guard') so it can't spin forever."""
    aid = "acc_br_loop"
    await _seed_account(aid)
    fid = await _seed_funnel("br_loop", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["loop"],
         "next": {"default": 1}},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 54001)
    await _seed_msg(aid, 54001, 7801, "in", T_REPLY1, body="reply 1")
    _use_fake()

    prev = a11._MAX_HOPS
    a11._MAX_HOPS = 3  # trip the guard fast (else 20 real ticks)
    try:
        r1 = await run_once(aid, "reply_mass_funnel", payload={})
        assert r1["advanced"] == 1, r1
        st = await _state(mr, 54001)
        assert st.current_step == 0 and st.hops == 1, ("self-loop, 1 hop", st)
        # A reply AFTER the send (12:00) so each later tick re-fires the loop.
        await _seed_msg(aid, 54001, 7802, "in", T0 + timedelta(hours=3),
                        body="again")
        for _ in range(10):
            st = await _state(mr, 54001)
            if st.status == "done":
                break
            await _force_due(aid, mr, 54001)
            await run_once(aid, "reply_mass_funnel", payload={})
        st = await _state(mr, 54001)
        assert st.status == "done", ("loop guard must halt the fan", st)
        assert st.last_error == "loop_guard", st
        assert st.hops >= 3, st
    finally:
        a11._MAX_HOPS = prev


async def case_no_next_walks_linearly():
    """BACK-COMPAT: a funnel with NO `next` walks 1→2→3 exactly as before, one
    step per fresh reply, and NEVER bumps the loop-guard hop counter."""
    aid = "acc_br_linear"
    await _seed_account(aid)
    fid = await _seed_funnel("br_linear", [
        {"step": 1, "check_intervals_min": [2, 4, 10], "messages": ["m1"]},
        {"step": 2, "check_intervals_min": [2, 4, 10], "messages": ["m2"]},
        {"step": 3, "check_intervals_min": [2, 4, 10], "messages": ["m3"]},
    ])
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 55001)
    await _seed_msg(aid, 55001, 7901, "in", T_REPLY1, body="reply 1")
    _use_fake()

    await run_once(aid, "reply_mass_funnel", payload={})     # 0→1
    assert (await _state(mr, 55001)).current_step == 1

    # reply 2 lands after the step-1 send (SEND_AT = 12:00).
    await _seed_msg(aid, 55001, 7902, "in", T0 + timedelta(hours=3), body="r2")
    await _force_due(aid, mr, 55001)
    await run_once(aid, "reply_mass_funnel", payload={})     # 1→2
    assert (await _state(mr, 55001)).current_step == 2

    # reply 3 → 2→3 (== len) → done.
    await _seed_msg(aid, 55001, 7903, "in", T0 + timedelta(hours=4), body="r3")
    await _force_due(aid, mr, 55001)
    await run_once(aid, "reply_mass_funnel", payload={})     # 2→3, terminal
    st = await _state(mr, 55001)
    assert st.current_step == 3 and st.status == "done", st
    # Linear walk never touches the branching loop guard.
    assert not st.hops, ("linear funnel must not bump hops", st.hops)

    out = await _funnel_out_msgs(aid, 55001)
    assert [_strip(m.body) for m in out] == ["m1", "m2", "m3"], out


async def case_aged_broadcast_stops_discovering():
    """A broadcast older than _DISCOVERY_WINDOW_DAYS with nobody mid-funnel is
    FINISHED: it must drop out of the anchor set entirely, so discovery never
    re-scans its recipients again.

    This is the leak that made reply_mass_funnel the most expensive automation on
    the box — `_active_mass_runs` had no time bound, so every broadcast an account
    had ever sent kept re-asking all ~1,600 of its recipients "replied yet?" every
    120s forever. The fan here HAS replied and would have been discovered under the
    old code; past the window we deliberately leave him to the chat engines,
    which answer ordinary inbound anyway."""
    aid = "acc_f_aged"
    await _seed_account(aid)
    fid = await _seed_funnel("f_aged", _TWO_STEP)
    old = T0 - timedelta(days=a11._DISCOVERY_WINDOW_DAYS + 1)
    mr = await _seed_mass_run(aid, fid, started_at=old)
    await _seed_msg(aid, 8201, 5_900_000 + mr, "out", old, mass_run_id=mr,
                    body="How many strokes? 😈")
    await _seed_msg(aid, 8201, 7_201, "in", old + timedelta(minutes=5), body="a lot")
    _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res.get("reason") == "no_active_funnel_runs", res
    assert await _state(mr, 8201) is None, "aged-out run must not enrol anyone"


async def case_aged_broadcast_still_walks_pending_fan():
    """…but the bound must never STRAND a fan. An aged-out broadcast that still
    holds a `pending` funnel_state stays an anchor and keeps walking that fan —
    it just stops scanning for new ones. That is the OR arm in `_active_mass_runs`,
    and it is why the window can be short without losing anybody mid-storyline."""
    aid = "acc_f_aged_live"
    await _seed_account(aid)
    fid = await _seed_funnel("f_aged_live", _TWO_STEP)
    old = T0 - timedelta(days=a11._DISCOVERY_WINDOW_DAYS + 1)
    mr = await _seed_mass_run(aid, fid, started_at=old)
    await _seed_msg(aid, 8301, 5_910_000 + mr, "out", old, mass_run_id=mr,
                    body="How many strokes? 😈")
    # Mid-funnel already, and he has answered our last funnel-out → step is due.
    await _seed_state(mr, 8301, current_step=1)
    await _seed_msg(aid, 8301, 7_301, "in", datetime.utcnow(), body="yes please")
    # A second recipient who replied but was never enrolled must STAY unenrolled:
    # walking is open, discovery is not.
    await _seed_msg(aid, 8302, 5_920_000 + mr, "out", old, mass_run_id=mr,
                    body="How many strokes? 😈")
    await _seed_msg(aid, 8302, 7_302, "in", old + timedelta(minutes=5), body="a lot")
    fake = _use_fake()

    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["runs"] == 1, res
    assert res["discovery_skipped"] == 1, res
    assert res["discovered"] == 0, res
    assert res["advanced"] == 1, res
    assert fake.sent, "the pending fan must still receive his step"
    assert await _state(mr, 8302) is None, "discovery stays closed past the window"


async def case_slot_lost_mid_step_records_the_step_and_never_resends_it():
    """The run loses its slot after m1a landed (run_slot.SlotLost at m1b's
    hold): m1b is not sent, but the step counts as sent (advanced, rested) and
    the next run, with no new reply, sends nothing again."""
    aid = "acc_slot_lost"
    await _seed_account(aid)
    fid = await _seed_funnel("slot_lost", _TWO_STEP)
    mr = await _seed_mass_run(aid, fid)
    await _broadcast(aid, mr, 66001)
    await _seed_msg(aid, 66001, 7951, "in", T_REPLY1, body="haha a lot")
    fake = _use_fake()
    with _harness.slot_lost_at_hold(a11, 2):
        res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "error", res
    assert [_strip(m["text"]) for m in fake.sent] == ["m1a"], fake.sent
    st = await _state(mr, 66001)
    assert st.current_step == 1 and st.status == "pending", st
    async with get_session() as s:
        assert await s.get(FanLease, (aid, 66001)) is None
        assert (await s.get(Fan, (aid, 66001))).automation_paused_until is not None
        await s.execute(update(Fan).where(Fan.account_id == aid).values(automation_paused_until=None))
        await s.commit()
    await _force_due(aid, mr, 66001)
    res = await run_once(aid, "reply_mass_funnel", payload={})
    assert res["status"] == "ok", res
    assert [_strip(m["text"]) for m in fake.sent] == ["m1a"], fake.sent


_harness.run(
    case_discover_and_advance,
    case_slot_lost_mid_step_records_the_step_and_never_resends_it,
    case_cooldown_skips_funnel,
    case_resume_after_restart,
    case_no_new_reply_reschedules,
    case_ppv_step_is_terminal,
    case_ppv_media_is_per_account,
    case_ppv_media_legacy_fallback,
    case_generated_step_uses_llm,
    case_dry_run_sends_nothing,
    case_non_replier_not_discovered,
    case_unreachable_fan_ends_state,
    case_list_audience_adoption,
    case_blank_ppv_blocked,
    case_offer_taken_halts,
    case_offer_not_taken_still_walks,
    case_next_bought_jumps_else_falls_through,
    case_next_ignored_branch_on_no_reply,
    case_next_ignored_waits_inside_window,
    case_next_keyword_branch_on_reply,
    case_next_keyword_ignores_bare_reaction,
    case_loop_guard_halts_self_reference,
    case_no_next_walks_linearly,
    case_aged_broadcast_stops_discovering,
    case_aged_broadcast_still_walks_pending_fan,
)
