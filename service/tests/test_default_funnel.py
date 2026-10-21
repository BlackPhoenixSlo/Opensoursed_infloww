#!/usr/bin/env python3
"""
The DEFAULT "strokes" funnel — pre-added on every box, and walked end to end.

  case_seed_matches_canonical_json:
      seeds/funnels.py's "strokes" entry IS the canonical funnel JSON, minus step
      4's `media_files` (vault ids are per model → funnel_account_media).
  case_seed_defaults_once_idempotent:
      seed_defaults_once adds exactly "strokes" (not the French variant) on the
      first boot and nothing on every later boot — one row, no duplicates.
  case_seed_deleted_default_stays_deleted:
      a default the operator deleted does not come back on the next boot (only
      a box without the marker re-adds a missing one).
  case_seed_never_clobbers_an_edit:
      even with the marker gone, an existing "strokes" row is left as edited.
  case_strokes_walk_end_to_end:
      the SEEDED funnel walked through the real run_once: a replier gets step 1;
      with no reply the checks land +2, +6, +16 after the send, then every 10;
      each fresh reply advances 1→2→3→4; step 4 is a $24 PPV carrying THIS
      model's five bound vault ids, and finishes the fan.
  case_funnel_send_turns_the_walker_on:
      a funnel-linked send needs the periodic reply_mass_funnel rule: created ON
      at 120 s when missing (once), a parked one is woken, a cadence-less Reply
      Instant row gets a cadence, an operator-tuned cadence is kept.
  case_strokes_ppv_waits_for_media:
      a model that never bound PPV media is held at step 4 (pre-send guard) —
      nothing is sent, the fan stays pending — instead of a blank paywall.

Run: ./venv/bin/python service/tests/test_default_funnel.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select, text, update  # noqa: E402

import automation_executor as ax  # noqa: E402
import automations.reply_mass_funnel as a11  # noqa: E402 — module under test

a11._STEP_GAP_S = 0  # skip the human typing-pause sleep in tests
from automation_executor import run_once  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AutomationRule, Fan, FunnelAccountMedia, FunnelState, MassMessageFunnel,
    MassRun, Message,
)
from funnels_api import ensure_funnel_walker  # noqa: E402
from seeds.funnels import DEFAULTS_MARKER, FUNNELS, seed_defaults_once  # noqa: E402

# The funnel as the operator wrote it (verbatim, including the media ids that
# belong to ONE model's vault).
CANONICAL = {
    "name": "strokes",
    "opening_message": "How many strokes does it take to get you off? 😈",
    "description": "Strokes engagement funnel — opens with a spicy question, warms up "
                   "with 3 reply steps, closes with paid PPV content.",
    "steps": [
        {"step": 1, "check_intervals_min": [2, 4, 10],
         "messages": ["bet you lose count once it starts getting slopyyy",
                      "or do you stay focused even with all that pressure building? c:"]},
        {"step": 2, "check_intervals_min": [2, 4, 10],
         "messages": ["i can feel you pulsating just thinking about it...",
                      "so tell me would you explode fast or last if I were the one "
                      "dictating the tempo?"]},
        {"step": 3, "check_intervals_min": [2, 4, 10],
         "messages": ["how about you pull your friend out, and we find out how many "
                      "strokes it will take you to bust?",
                      "if you last long enough, I promise to praise you and reward "
                      "your hard work"]},
        {"media_files": [4513355224, 4513355887, 4513359784, 4513360058, 4513360609],
         "step": 4, "type": "paid_ppv", "price": 24,
         "messages": ["if it wasn't obvious already, i love to be in control. not just "
                      "of you, but your every thought, action & desire. open this & "
                      "show me how obedient ure going to be, taking out ur cock & "
                      "slowly moving it up and down the shaft while i spread my legs "
                      "infront of your face showing just how pink it is"]},
    ],
}
PPV_MEDIA = CANONICAL["steps"][3]["media_files"]

T0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)  # broadcast time


class FakeOF:
    """Records sends; stamps each echo at `clock` so every step's funnel-out lands
    at a time the test controls (a reply must come AFTER it to count)."""

    def __init__(self):
        self.user_id = "999"
        self.sent: list[dict] = []
        self.clock = T0
        self._next_id = 9_100_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append({"fan_id": int(chat_id), "text": text, **kw})
        return {"id": self._next_id, "text": text,
                "createdAt": self.clock.isoformat() + "+00:00"}


def _use_fake() -> FakeOF:
    fake = FakeOF()
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


async def _strokes() -> MassMessageFunnel | None:
    async with get_session() as s:
        return (await s.execute(select(MassMessageFunnel)
                                .where(MassMessageFunnel.name == "strokes"))).scalar_one_or_none()


async def _funnel_names() -> list[str]:
    async with get_session() as s:
        return list((await s.execute(select(MassMessageFunnel.name))).scalars())


async def _setup_run(aid: str, fan_id: int, *, media: list[int] | None) -> int:
    """Account + (optional) per-model PPV media + a funnel broadcast to `fan_id`
    that the fan answered 5 min later."""
    fid = (await _strokes()).id
    async with get_session() as s:
        s.add(Account(id=aid))
        if media is not None:
            s.add(FunnelAccountMedia(
                funnel_id=fid, account_id=aid, opening_media_ids="[]",
                steps_media_json=json.dumps({"4": {"media_files": media}})))
        mr = MassRun(account_id=aid, funnel_id=fid, status="ok",
                     recipient_count=1, started_at=T0)
        s.add(mr)
        await s.flush()
        mr_id = int(mr.id)
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=5_000_000 + mr_id,
                      direction="out", body=CANONICAL["opening_message"],
                      created_at=T0, mass_run_id=mr_id))
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=7_000_000 + mr_id,
                      direction="in", body="like 100", created_at=T0 + timedelta(minutes=5)))
    return mr_id


async def _reply(aid: str, fan_id: int, mid: int, at: datetime) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=mid, direction="in",
                      body="mm keep going", created_at=at))


async def _state(mr: int, fan_id: int) -> FunnelState:
    async with get_session() as s:
        return await s.get(FunnelState, (mr, fan_id))


async def _make_due(aid: str, mr: int, fan_id: int) -> None:
    """Time passes: the check is due and the 60 s post-send rest is over."""
    async with get_session() as s:
        await s.execute(update(FunnelState)
                        .where(FunnelState.mass_run_id == mr, FunnelState.fan_id == fan_id)
                        .values(next_check_at=datetime.utcnow() - timedelta(seconds=1)))
        await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == fan_id)
                        .values(automation_paused_until=None))
    await ax.release_fan_lease(aid, fan_id)


def _gap_min(st: FunnelState) -> float:
    """Minutes from the tick that saved this state to its next reply-check (both
    stamps come from the walker's one `now`, so this is exact)."""
    return (st.next_check_at - st.updated_at).total_seconds() / 60


# ── Content ───────────────────────────────────────────────────────────

def case_seed_matches_canonical_json():
    seeded = next(f for f in FUNNELS if f["name"] == "strokes")
    want = json.loads(json.dumps(CANONICAL))
    want["steps"][3].pop("media_files")  # per model, never on the shared text
    got = {k: seeded[k] for k in ("name", "opening_message", "description", "steps")}
    assert got == want, json.dumps(got, ensure_ascii=False, indent=1)
    assert set(seeded) == {"name", "opening_message", "description", "steps"}, \
        f"no legacy keys on the default: {sorted(seeded)}"


# ── Seeding ───────────────────────────────────────────────────────────

async def case_seed_defaults_once_idempotent():
    assert await _funnel_names() == [], "fresh test DB starts empty"
    assert await seed_defaults_once() == ["strokes"]
    assert await seed_defaults_once() == [], "second boot adds nothing"
    assert await seed_defaults_once() == []
    assert await _funnel_names() == ["strokes"], "exactly one default, no strokes_fr"

    row = await _strokes()
    assert row.opening_message == CANONICAL["opening_message"], row.opening_message
    steps = json.loads(row.steps_json)
    assert [s["step"] for s in steps] == [1, 2, 3, 4], steps
    assert "media_files" not in steps[3], "no model's vault ids on the shared funnel"


async def case_seed_never_clobbers_an_edit():
    async with get_session() as s:
        await s.execute(update(MassMessageFunnel).where(MassMessageFunnel.name == "strokes")
                        .values(opening_message="my own opener"))
        # Even if the one-shot marker were lost, insert-if-missing keeps the edit.
        await s.execute(text("DELETE FROM data_migrations WHERE name = :n"),
                        {"n": DEFAULTS_MARKER})
    assert await seed_defaults_once() == []
    assert (await _strokes()).opening_message == "my own opener"
    assert await _funnel_names() == ["strokes"]
    async with get_session() as s:  # put the canonical opener back for the walk
        await s.execute(update(MassMessageFunnel).where(MassMessageFunnel.name == "strokes")
                        .values(opening_message=CANONICAL["opening_message"]))


async def case_seed_deleted_default_stays_deleted():
    async with get_session() as s:
        await s.execute(delete(MassMessageFunnel).where(MassMessageFunnel.name == "strokes"))
    assert await seed_defaults_once() == [], "marker present → never resurrected"
    assert await _strokes() is None
    # A box that never got the default (no marker) gets it back: insert-if-missing.
    async with get_session() as s:
        await s.execute(text("DELETE FROM data_migrations WHERE name = :n"),
                        {"n": DEFAULTS_MARKER})
    assert await seed_defaults_once() == ["strokes"]
    assert await _funnel_names() == ["strokes"]


# ── The walk ──────────────────────────────────────────────────────────

async def case_strokes_walk_end_to_end():
    aid, fan = "acc_strokes", 61001
    mr = await _setup_run(aid, fan, media=PPV_MEDIA)
    fake = _use_fake()
    steps = CANONICAL["steps"]

    # Discovery + step 1 (he answered the opener).
    fake.clock = T0 + timedelta(hours=1)
    r = await run_once(aid, "reply_mass_funnel", payload={})
    assert (r["discovered"], r["advanced"]) == (1, 1), r
    assert [m["text"] for m in fake.sent] == steps[0]["messages"], fake.sent
    assert all("price" not in m for m in fake.sent), "reply steps are free"
    st = await _state(mr, fan)
    assert (st.current_step, st.check_count, st.status) == (1, 0, "pending"), st
    assert _gap_min(st) == 2, _gap_min(st)

    # Silence: each due check reschedules on the NEXT gap — +2, +6, +16 after the
    # send, then every 10 — and sends nothing.
    for want_count, want_gap in ((1, 4), (2, 10), (3, 10), (4, 10)):
        await _make_due(aid, mr, fan)
        r = await run_once(aid, "reply_mass_funnel", payload={})
        assert (r["waiting"], r["advanced"]) == (1, 0), r
        st = await _state(mr, fan)
        assert (st.current_step, st.check_count) == (1, want_count), st
        assert _gap_min(st) == want_gap, (want_count, _gap_min(st))
    assert len(fake.sent) == 2, "no send while he's quiet"

    # Each fresh reply advances one step and restarts the [2,4,10] poll.
    for n, step in ((2, steps[1]), (3, steps[2])):
        await _reply(aid, fan, 7_100 + n, fake.clock + timedelta(minutes=30))
        fake.clock += timedelta(hours=1)
        await _make_due(aid, mr, fan)
        before = len(fake.sent)
        r = await run_once(aid, "reply_mass_funnel", payload={})
        assert r["advanced"] == 1, r
        assert [m["text"] for m in fake.sent[before:]] == step["messages"], fake.sent
        st = await _state(mr, fan)
        assert (st.current_step, st.check_count, st.status) == (n, 0, "pending"), st
        assert _gap_min(st) == 2, _gap_min(st)

    # A reply after step 3 → the $24 PPV with this model's five vault ids, then done.
    await _reply(aid, fan, 7_104, fake.clock + timedelta(minutes=30))
    fake.clock += timedelta(hours=1)
    await _make_due(aid, mr, fan)
    before = len(fake.sent)
    r = await run_once(aid, "reply_mass_funnel", payload={})
    assert (r["advanced"], r["completed"]) == (1, 1), r
    ppv = fake.sent[before:]
    assert len(ppv) == 1, ppv
    assert ppv[0]["text"] == steps[3]["messages"][0], ppv
    assert ppv[0]["price"] == 24, ppv
    assert ppv[0]["media_files"] == PPV_MEDIA, ppv
    assert ppv[0]["locked_text"] is False, "pitch stays readable, only media is locked"
    st = await _state(mr, fan)
    assert (st.current_step, st.status) == (4, "done"), st

    async with get_session() as s:
        out = (await s.execute(select(Message.funnel_step, Message.price_cents).where(
            Message.account_id == aid, Message.fan_id == fan,
            Message.funnel_step.is_not(None)).order_by(Message.message_id))).all()
    assert [r[0] for r in out] == [1, 1, 2, 2, 3, 3, 4], out
    assert out[-1][1] == 2400, out

    # Done means done: a later reply does not restart the walk.
    await _reply(aid, fan, 7_105, fake.clock + timedelta(minutes=30))
    await _make_due(aid, mr, fan)
    before = len(fake.sent)
    await run_once(aid, "reply_mass_funnel", payload={})
    assert len(fake.sent) == before, fake.sent[before:]


async def case_strokes_ppv_waits_for_media():
    aid, fan = "acc_strokes_nomedia", 62001
    mr = await _setup_run(aid, fan, media=None)  # this model bound no PPV media
    fake = _use_fake()
    async with get_session() as s:  # he's at step 4 and has just answered step 3
        s.add(FunnelState(mass_run_id=mr, fan_id=fan, current_step=3, check_count=0,
                          status="pending",
                          next_check_at=datetime.utcnow() - timedelta(seconds=1)))

    r = await run_once(aid, "reply_mass_funnel", payload={})
    assert (r["blocked"], r["advanced"]) == (1, 0), r
    assert fake.sent == [], "never a blank paywall"
    st = await _state(mr, fan)
    assert (st.current_step, st.status) == (3, "pending"), st
    assert st.last_error == "blocked:ppv_without_media", st.last_error


async def _walker_rules(aid: str) -> list[tuple[bool, dict]]:
    async with get_session() as s:
        rows = (await s.execute(select(AutomationRule).where(
            AutomationRule.account_id == aid,
            AutomationRule.kind == "reply_mass_funnel").order_by(AutomationRule.id))).scalars()
        return [(bool(r.is_enabled), json.loads(r.trigger_json or "{}")) for r in rows]


async def _add_walker(aid: str, *, enabled: bool, trigger: dict) -> None:
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AutomationRule(account_id=aid, name="walker", kind="reply_mass_funnel",
                             trigger_json=json.dumps(trigger), steps_json="{}",
                             is_enabled=enabled))


async def case_funnel_send_turns_the_walker_on():
    # None yet → created ON at the catalog's 2-min cadence; a second send is a no-op.
    async with get_session() as s:
        s.add(Account(id="acc_w_none"))
    assert await ensure_funnel_walker("acc_w_none") == "created"
    assert await ensure_funnel_walker("acc_w_none") == "unchanged"
    assert await _walker_rules("acc_w_none") == [(True, {"every_seconds": 120})]

    # Parked by the operator → the funnel pick wakes it, cadence untouched.
    await _add_walker("acc_w_off", enabled=False, trigger={"every_seconds": 180})
    assert await ensure_funnel_walker("acc_w_off") != "unchanged"
    assert await _walker_rules("acc_w_off") == [(True, {"every_seconds": 180})]

    # Reply Instant's cadence-less switch never ticks → it gets a cadence.
    await _add_walker("acc_w_w7", enabled=True, trigger={})
    assert await ensure_funnel_walker("acc_w_w7") == "cadence"
    assert await _walker_rules("acc_w_w7") == [(True, {"every_seconds": 120})]

    # Already walking at a tuned cadence → left exactly as it is.
    await _add_walker("acc_w_tuned", enabled=True, trigger={"every_seconds": 300})
    assert await ensure_funnel_walker("acc_w_tuned") == "unchanged"
    assert await _walker_rules("acc_w_tuned") == [(True, {"every_seconds": 300})]


_harness.run(
    case_seed_matches_canonical_json,
    case_seed_defaults_once_idempotent,
    case_seed_deleted_default_stays_deleted,
    case_seed_never_clobbers_an_edit,
    case_strokes_walk_end_to_end,
    case_strokes_ppv_waits_for_media,
    case_funnel_send_turns_the_walker_on,
)
