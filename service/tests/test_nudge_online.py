#!/usr/bin/env python3
"""
nudge_online — automation tests (library/NUDGE_ONLINE_PLAN.md).

Covers the two-automation lifecycle through the real `run_once` dispatcher
against a fake OFClient (no network):

  case_warmup_seeds_no_send:
      first tick for an account seeds NudgeState.last_seen for the whole online
      set and sends/enqueues NOTHING (no cold-start stampede).
  case_newly_online_enqueues:
      a warmed account with a fresh online fan enqueues ONE nudge_online_fire job
      and latches NudgeState.pending_job_id.
  case_pending_dedup_skips:
      a newly-online fan that already has a pending fire-job is skipped.
  case_cap_defers_overflow:
      max_per_tick=1 over 2 newly-online fans handles 1, DEFERS 1 (its last_seen
      is left stale), and the deferred fan is picked up on the NEXT tick.
  case_fire_sends_when_valid:
      the enqueued job, claimed via run_once, re-validates + sends, writes the
      outbound row, bumps NudgeState, and clears pending.
  case_fire_skips_when_offline:
      fire re-validate cancels (no send) when the fan went offline during the
      delay; pending is cleared.
  case_fire_skips_when_convo_started:
      fire re-validate cancels when a real convo started (recent outbound).
  case_gate_not_welcomed:
      require_welcomed gate skips a fan we've never welcomed.
  case_no_cooldown_set:
      a confirmed nudge does NOT set fans.automation_paused_until (fully async).
  case_with_image_layers_the_payload_over_the_account_cfg:
      the TWO-LEVEL default (rule payload over account cfg) that the
      catalogued-bool seam check refuses to certify — all six cells.
  case_compose_helpers:
      _pick_pool day-bucket order, _choose_idx rotation, substitute_placeholders.

Run: ./venv/bin/python service/tests/test_nudge_online.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import nudge_online, nudge_online_fire  # noqa: E402
from automations._common import substitute_placeholders  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, Fan, Message, NudgeState, ScheduledJob,
    Transaction, WelcomeSent,
)

OWN_ID = "999"

# "not written at all", distinct from a stored False — see the with_image case.
_ABSENT = object()


# ── Fake OF (no network) ──────────────────────────────────────────────

class FakeOF:
    """Serves a canned online-subscribers list; records sends and echoes a
    real-looking OF message object."""

    def __init__(self, online: list[dict], user_id: str = OWN_ID):
        self.user_id = user_id
        self._online = online
        self.sent: list[tuple[int, str, list]] = []
        self._next_id = 8_000_000_000_000

    def iter_online_subscribers(self, *, type: str = "active", page_size: int = 20,
                                max_fans: int = 1000) -> list[dict]:
        return list(self._online[:max_fans])

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text, list(media_files or [])))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-05T12:00:00+00:00"}


def _use_fake(online: list[dict]) -> FakeOF:
    fake = FakeOF(online)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _online(uid: int, name: str | None = None, **extra) -> dict:
    return {"id": uid, "name": name, "username": name or f"u{uid}", **extra}


# ── Seeding ───────────────────────────────────────────────────────────

_BASE_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0,
    "gap_minutes": 5, "quiet_hours": [0, 0], "require_welcomed": False,
    "max_per_tick": 25, "online_recent_minutes": 5,
    "min_hours_between_nudges": 12, "max_no_reply": 3, "active_convo_hours": 6,
    # Default the tests to a text-only nudge line so send assertions are simple.
    "nudge_line_text": True, "nudge_line_image": False,
}


async def _seed_cfg(aid: str, **overrides) -> None:
    cfg = dict(_BASE_CFG)
    cfg.update(overrides)
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        row = await s.get(AccountAiConfig, aid)
        if row is None:
            s.add(AccountAiConfig(account_id=aid, utc_offset=0,
                                  nudge_config_json=json.dumps(cfg)))
        else:
            row.nudge_config_json = json.dumps(cfg)
        # The detector's rule is the other half of the switch: a fire job only
        # sends while an enabled nudge_online rule exists (nudge_online_fire.run).
        has_rule = (await s.execute(select(AutomationRule.id).where(
            AutomationRule.account_id == aid,
            AutomationRule.kind == "nudge_online"))).first()
        if has_rule is None:
            s.add(AutomationRule(account_id=aid, name="Nudge online", kind="nudge_online",
                                 trigger_json=json.dumps({"every_seconds": 60}),
                                 steps_json="{}", is_enabled=True))


async def _warm(aid: str) -> None:
    """Mark the account warmed by giving it one (unrelated) NudgeState row."""
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=1,
                         last_seen_online_at=datetime.utcnow() - timedelta(days=1)))


async def _seed_state(aid: str, fan_id: int, **cols) -> None:
    async with get_session() as s:
        s.add(NudgeState(account_id=aid, fan_id=fan_id, **cols))


async def _seed_msg(aid: str, fan_id: int, direction: str, when: datetime, mid: int) -> None:
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan_id, message_id=mid,
                      direction=direction, created_at=when, body="hi"))


async def _state(aid: str, fan_id: int) -> NudgeState | None:
    async with get_session() as s:
        return await s.get(NudgeState, (aid, fan_id))


async def _jobs(aid: str, kind: str) -> list[ScheduledJob]:
    async with get_session() as s:
        return (await s.execute(select(ScheduledJob).where(
            ScheduledJob.account_id == aid, ScheduledJob.kind == kind))).scalars().all()


# ── Warm-up: first tick seeds, sends nothing ──────────────────────────

async def case_warmup_seeds_no_send():
    aid = "n_warm"
    await _seed_cfg(aid)
    fake = _use_fake([_online(1001, "Bob"), _online(1002, "Cara")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res.get("warmup") is True, res
    assert res["seeded"] == 2 and res["enqueued"] == 0, res
    assert fake.sent == [], fake.sent
    assert await _jobs(aid, "nudge_online_fire") == [], "no fire jobs on warm-up"
    for fid in (1001, 1002):
        st = await _state(aid, fid)
        assert st is not None and st.last_seen_online_at is not None, fid
        assert st.pending_job_id is None, fid


# ── Newly-online fan enqueues exactly one fire-job ────────────────────

async def case_newly_online_enqueues():
    aid = "n_enq"
    await _seed_cfg(aid)
    await _warm(aid)
    _use_fake([_online(2001, "Dee")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 1, res
    jobs = await _jobs(aid, "nudge_online_fire")
    assert len(jobs) == 1, jobs
    assert json.loads(jobs[0].payload_json)["fan_id"] == 2001, jobs[0].payload_json
    st = await _state(aid, 2001)
    assert st.pending_job_id == jobs[0].id, st


# ── A newly-online fan already pending is deduped ─────────────────────

async def case_pending_dedup_skips():
    aid = "n_dedup"
    await _seed_cfg(aid)
    await _warm(aid)
    # stale last_seen (so it qualifies as newly-online) but a job already pending.
    await _seed_state(aid, 3001,
                      last_seen_online_at=datetime.utcnow() - timedelta(hours=1),
                      pending_job_id=777)
    _use_fake([_online(3001, "Eve")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 0, res
    assert res["skip_reasons"].get("pending") == 1, res
    assert await _jobs(aid, "nudge_online_fire") == [], "no new job while one pending"


# ── Cap defers overflow; deferred fan picked up next tick ─────────────

async def case_cap_defers_overflow():
    aid = "n_cap"
    await _seed_cfg(aid, max_per_tick=1)
    await _warm(aid)
    _use_fake([_online(4001, "Fay"), _online(4002, "Gus")])

    r1 = await run_once(aid, "nudge_online", payload={})
    assert r1["handled"] == 1 and r1["deferred"] == 1 and r1["enqueued"] == 1, r1
    # 4001 handled (last_seen touched + pending); 4002 deferred (no row / stale).
    st1 = await _state(aid, 4001)
    assert st1 is not None and st1.pending_job_id is not None, st1
    st2 = await _state(aid, 4002)
    assert st2 is None or st2.last_seen_online_at is None, "overflow left stale"

    # Next tick: 4001 is fresh (not newly), 4002 still qualifies → now handled.
    r2 = await run_once(aid, "nudge_online", payload={})
    assert r2["enqueued"] == 1, r2
    jobs = await _jobs(aid, "nudge_online_fire")
    fan_ids = {json.loads(j.payload_json)["fan_id"] for j in jobs}
    assert fan_ids == {4001, 4002}, fan_ids  # both eventually scheduled, none dropped


# ── Fire-job: re-validate + send (claimed via run_once) ───────────────

async def case_fire_sends_when_valid():
    aid = "n_fire"
    await _seed_cfg(aid)  # delay 0 → fire job is immediately due
    await _warm(aid)
    fake = _use_fake([_online(5001, "Hank")])

    await run_once(aid, "nudge_online", payload={})  # enqueues a due fire job
    res = await run_once(aid, "nudge_online_fire")   # claims + fires it
    assert res.get("sent") == 1, res
    assert len(fake.sent) == 1 and fake.sent[0][0] == 5001, fake.sent

    st = await _state(aid, 5001)
    assert st.last_nudged_at is not None and st.nudge_count == 1, st
    assert st.pending_job_id is None, "pending cleared after send"
    async with get_session() as s:
        msgs = (await s.execute(select(Message).where(
            Message.account_id == aid, Message.direction == "out"))).scalars().all()
    assert len(msgs) == 1 and msgs[0].fan_id == 5001, msgs


# ── Fire-job re-validate cancels when the fan went offline ────────────

async def case_fire_skips_when_offline():
    aid = "n_off"
    await _seed_cfg(aid)
    # last_seen is stale (> online_recent_minutes) by fire time.
    await _seed_state(aid, 6001,
                      last_seen_online_at=datetime.utcnow() - timedelta(minutes=30),
                      pending_job_id=42)
    fake = _use_fake([])

    res = await run_once(aid, "nudge_online_fire", payload={"fan_id": 6001})
    assert res["sent"] == 0 and res["skipped"] == "offline", res
    assert fake.sent == [], fake.sent
    st = await _state(aid, 6001)
    assert st.pending_job_id is None, "pending cleared on cancel"


# ── Fire-job cancels when a real convo started during the delay ───────

async def case_fire_skips_when_convo_started():
    aid = "n_convo"
    await _seed_cfg(aid)
    await _seed_state(aid, 7001,
                      last_seen_online_at=datetime.utcnow(), pending_job_id=43)
    # an outbound moments ago → active-convo gate (recent_outbound)
    await _seed_msg(aid, 7001, "out", datetime.utcnow() - timedelta(minutes=2), 70001)
    fake = _use_fake([])

    res = await run_once(aid, "nudge_online_fire", payload={"fan_id": 7001})
    assert res["sent"] == 0 and res["skipped"] == "recent_outbound", res
    assert fake.sent == [], fake.sent
    st = await _state(aid, 7001)
    assert st.pending_job_id is None, st


# ── require_welcomed gate ─────────────────────────────────────────────

async def case_gate_not_welcomed():
    aid = "n_welc"
    await _seed_cfg(aid, require_welcomed=True)
    await _warm(aid)
    # 8001 never welcomed → gated; 8002 welcomed 5h ago (past the grace) → qualifies.
    async with get_session() as s:
        s.add(WelcomeSent(account_id=aid, fan_id=8002,
                          sent_at=datetime.utcnow() - timedelta(hours=5)))
    _use_fake([_online(8001, "Ivy"), _online(8002, "Joe")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 1, res
    assert res["skip_reasons"].get("not_welcomed") == 1, res
    jobs = await _jobs(aid, "nudge_online_fire")
    assert {json.loads(j.payload_json)["fan_id"] for j in jobs} == {8002}, jobs


# ── Spend gates: lifetime + rolling window ────────────────────────────

async def case_spend_gate_lifetime():
    aid = "n_spend_life"
    await _seed_cfg(aid, max_lifetime_spend_cents=2000)  # only fans < $20 lifetime
    await _warm(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=8101, lifetime_spend_cents=500))    # qualifies
        s.add(Fan(account_id=aid, fan_id=8102, lifetime_spend_cents=5000))   # gated
    _use_fake([_online(8101, "Lo"), _online(8102, "Hi")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 1, res
    assert res["skip_reasons"].get("spend_above_max") == 1, res
    jobs = await _jobs(aid, "nudge_online_fire")
    assert {json.loads(j.payload_json)["fan_id"] for j in jobs} == {8101}, jobs


async def case_spend_gate_recent_window():
    aid = "n_spend_recent"
    await _seed_cfg(aid, max_recent_spend_cents=500, recent_spend_days=30)
    await _warm(aid)
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=8201, lifetime_spend_cents=0))
        s.add(Fan(account_id=aid, fan_id=8202, lifetime_spend_cents=0))
        # 8201 spent $10 five days ago → inside the 30d window → gated.
        s.add(Transaction(account_id=aid, fan_id=8201, kind="tip",
                          amount_cents=1000, occurred_at=now - timedelta(days=5)))
        # 8202 spent $10 sixty days ago → outside the window → qualifies.
        s.add(Transaction(account_id=aid, fan_id=8202, kind="tip",
                          amount_cents=1000, occurred_at=now - timedelta(days=60)))
    _use_fake([_online(8201, "Rec"), _online(8202, "Old")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 1, res
    assert res["skip_reasons"].get("recent_spend_above_max") == 1, res
    jobs = await _jobs(aid, "nudge_online_fire")
    assert {json.loads(j.payload_json)["fan_id"] for j in jobs} == {8202}, jobs


# ── Nudge is fully async: no shared cooldown set ──────────────────────

async def case_no_cooldown_set():
    aid = "n_async"
    await _seed_cfg(aid)
    await _warm(aid)
    _use_fake([_online(9001, "Jay")])

    await run_once(aid, "nudge_online", payload={})
    await run_once(aid, "nudge_online_fire")
    # The fan must NOT be on the shared automation cooldown (welcome_chatter_for_info stays free).
    assert await ax.fan_on_cooldown(aid, 9001) is False, "nudge must not set cooldown"


# ── Compose helpers (pure) ────────────────────────────────────────────

def case_compose_helpers():
    slots = nudge_online._DEFAULT_NUDGE_CONFIG["slots"]
    # Friday afternoon_2 → the friday-specific pool wins over default.
    fri = nudge_online._pick_pool(slots, "afternoon_2", "Friday")
    assert any("friday" in t.lower() for t in fri["text"]), fri
    # Saturday evening → weekend bucket.
    sat = nudge_online._pick_pool(slots, "evening", "Saturday")
    assert any("weekend" in t.lower() or "friday" in t.lower() for t in sat["text"]), sat
    # A weekday with no per-day/weekend override → default.
    wed = nudge_online._pick_pool(slots, "night", "Wednesday")
    assert wed is slots["default"]["night"], wed

    # Rotation: new advances, same holds, never-nudged seeds off fan id.
    class _St:
        def __init__(self, idx, slot): self.last_variation_idx = idx; self.last_slot = slot
    assert nudge_online._choose_idx(None, 7, 5, "new") == 7 % 5
    assert nudge_online._choose_idx(_St(2, "evening"), 7, 5, "new") == 3
    assert nudge_online._choose_idx(_St(4, "evening"), 7, 5, "new") == 0  # wraps
    assert nudge_online._choose_idx(_St(2, "evening"), 7, 5, "same") == 2

    # Placeholders: name override + empty-fact collapse.
    out = substitute_placeholders("hi {name} from {city} 💕", None, name="Tom")
    assert out == "hi Tom from 💕", out
    out2 = substitute_placeholders("hey {name}", None, name="")
    assert out2 == "hey babe", out2


# ── One message: the retired info line is ignored ─────────────────────

async def case_legacy_info_line_keys_ignored():
    """A config saved before the info line was dropped still carries
    send_info_line / info_line_mode / info_line_image / send_nudge_line=False.
    Those keys are ignored now: the nudge sends exactly ONE message — the greeting
    with its image — and never a profile Q&A (the fan's pet "Rex" stays unasked,
    nothing is written to questions_asked)."""
    aid = "n_legacy_info"
    slots = {"default": {k: {"text": ["hey {name} 👀"], "image": [555]} for k in
             ("morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")}}
    await _seed_cfg(aid, send_nudge_line=False, nudge_line_text=True, nudge_line_image=True,
                    send_info_line=True, info_line_mode="qa", info_line_image=True,
                    content_mode="qa", slots=slots)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=20001, real_name="Ed",
                  pets='[{"kind":"dog","name":"Rex"}]'))
    fake = _use_fake([_online(20001, "Ed")])

    await run_once(aid, "nudge_online", payload={"test_fan": 20001, "test_force": True})
    res = await run_once(aid, "nudge_online_fire")
    assert res["sent"] == 1, res
    [(_, text, media)] = fake.sent
    assert media == [555] and "Rex" not in text and "Ed" in text, fake.sent
    async with get_session() as s:
        fan = await s.get(Fan, (aid, 20001))
        assert not fan.questions_asked, fan.questions_asked

    # The preview agrees: one nudge-line message, no info line.
    cfg = await nudge_online._load_nudge_config(aid)
    prev = await nudge_online.preview_compose(aid, cfg, fan_id=20001)
    assert [m["kind"] for m in prev["messages"]] == ["nudge"], prev


# ── with_image: the rule payload layered over the account config ──────

async def case_with_image_layers_the_payload_over_the_account_cfg():
    """R3-7. `nudge_online` reads its ONE catalogued bool through a TWO-LEVEL
    default — `bool_knob(payload, "with_image", bool_knob(cfg, "with_image",
    True))` — so what a stored `null` means depends on the account row, not on a
    constant. `test_automation_rules_api`'s catalogued-bool walk therefore
    REFUSES to certify it (`_BOOL_READ_UNCLASSIFIABLE`): an earlier version of
    that check regexed out the innermost literal and certified "null ⇒ True",
    which is the answer only while the account cfg is silent. This case is what
    that refusal points at — all six cells, driven through the real `run`, read
    off the fire-job payload it enqueues.

    The knob is live at this end: `run` writes it into the `nudge_online_fire`
    job. (What the FIRE job then does with it is a separate, pre-existing
    matter — `nudge_online_fire.run` assigns it to a dead local and composes off
    `cfg` instead, ruff F841, reproducing at HEAD. Not this suite's claim.)"""
    async def enqueued_with_image(tag: str, *, cfg_value, payload: dict) -> bool:
        aid = f"n_wi_{tag}"
        overrides = {} if cfg_value is _ABSENT else {"with_image": cfg_value}
        await _seed_cfg(aid, **overrides)
        await _warm(aid)
        _use_fake([_online(4100, "Wi")])
        res = await run_once(aid, "nudge_online", payload=payload)
        assert res["enqueued"] == 1, (tag, res)
        jobs = await _jobs(aid, "nudge_online_fire")
        assert len(jobs) == 1, (tag, jobs)
        return json.loads(jobs[0].payload_json)["with_image"]

    # Both levels silent → the declared catalog default.
    assert await enqueued_with_image("aa", cfg_value=_ABSENT, payload={}) is True
    # The account config is the second level, and it is honoured.
    assert await enqueued_with_image("af", cfg_value=False, payload={}) is False
    # ⚠️ THE CELL THE SOURCE SCAN CANNOT NAME. A stored `null` says nothing, so
    # it falls through to the cfg — which here says off, while the catalog and
    # every UI surface show the knob ON. That disagreement is real and this is
    # where it is recorded; it is not a bug in `bool_knob`.
    assert await enqueued_with_image("nf", cfg_value=False, payload={"with_image": None}) is False
    assert await enqueued_with_image("na", cfg_value=_ABSENT, payload={"with_image": None}) is True
    # An explicit payload value wins over the cfg in BOTH directions.
    assert await enqueued_with_image("pf", cfg_value=True, payload={"with_image": False}) is False
    assert await enqueued_with_image("pt", cfg_value=False, payload={"with_image": True}) is True


_harness.run(
    case_warmup_seeds_no_send,
    case_newly_online_enqueues,
    case_pending_dedup_skips,
    case_cap_defers_overflow,
    case_fire_sends_when_valid,
    case_fire_skips_when_offline,
    case_fire_skips_when_convo_started,
    case_gate_not_welcomed,
    case_spend_gate_lifetime,
    case_spend_gate_recent_window,
    case_no_cooldown_set,
    case_with_image_layers_the_payload_over_the_account_cfg,
    case_compose_helpers,
    case_legacy_info_line_keys_ignored,
)
