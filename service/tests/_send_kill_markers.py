from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from _send_kill import Driver, Wire, WireOF, db_row, seed_account

_mids = iter(range(6_600_000_000_001, 6_700_000_000_000))


@contextmanager
def _stubbed():
    import llm_client
    import automations.reply_mass_funnel as a11

    async def _chat(**kw):
        return SimpleNamespace(content="hey you, been thinking about you today", call_id=1)
    real_chat, real_gap = llm_client.chat, a11._STEP_GAP_S
    llm_client.chat, a11._STEP_GAP_S = _chat, 0
    try:
        yield
    finally:
        llm_client.chat, a11._STEP_GAP_S = real_chat, real_gap


async def _run(aid: str, kind: str, payload: dict | None) -> None:
    from automation_executor import run_once
    with _stubbed():
        await run_once(aid, kind, payload=payload)


async def _funnel_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import FunnelAccountMedia, MassMessageFunnel, MassRun, Message
    await seed_account(aid)
    t0 = datetime.utcnow().replace(microsecond=0) - timedelta(days=1)
    fan = 72001
    async with get_session() as s:
        f = MassMessageFunnel(name=f"sk_{aid}", opening_message="hey", media_indices="[]",
                              steps_json=json.dumps([{"step": 1, "messages": ["m1"]}]))
        s.add(f)
        await s.flush()
        s.add(FunnelAccountMedia(funnel_id=int(f.id), account_id=aid, opening_media_ids="[]",
                                 steps_media_json=json.dumps({"1": {"media_files": [111]}})))
        mr = MassRun(account_id=aid, funnel_id=int(f.id), status="ok", recipient_count=1,
                     started_at=t0)
        s.add(mr)
        await s.flush()
        mr_id = int(mr.id)
        s.add(Message(account_id=aid, fan_id=fan, message_id=next(_mids), direction="out",
                      body="hey", created_at=t0, mass_run_id=mr_id))
        s.add(Message(account_id=aid, fan_id=fan, message_id=next(_mids), direction="in",
                      body="haha a lot", created_at=t0 + timedelta(minutes=5)))
    return {"aid": aid, "of": WireOF(wire, aid), "fan": fan, "mr": mr_id}


async def _funnel_tick(ctx):
    await _run(ctx["aid"], "reply_mass_funnel", {})


def _funnel_marked(ctx) -> bool:
    row = db_row("SELECT sending_at FROM funnel_state WHERE mass_run_id=? AND fan_id=?",
                 (ctx["mr"], ctx["fan"]))
    return bool(row and row[0])


def _funnel_advanced(ctx) -> bool:
    row = db_row("SELECT current_step, sending_at FROM funnel_state"
                 " WHERE mass_run_id=? AND fan_id=?", (ctx["mr"], ctx["fan"]))
    return bool(row and row[0] == 1 and row[1] is None)


async def _followup_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import Fan, Message
    await seed_account(aid)
    fan = 72002
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Bob", lifetime_spend_cents=500))
        s.add(Message(account_id=aid, fan_id=fan, message_id=next(_mids), direction="out",
                      body="hi", created_at=datetime.utcnow() - timedelta(hours=48)))
    return {"aid": aid, "of": WireOF(wire, aid), "fan": fan}


async def _followup_tick(ctx):
    await _run(ctx["aid"], "send_followup", {"with_image": False})


def _followup_marked(ctx) -> bool:
    row = db_row("SELECT sending_at FROM followup_state WHERE account_id=? AND fan_id=?",
                 (ctx["aid"], ctx["fan"]))
    return bool(row and row[0])


def _followup_advanced(ctx) -> bool:
    row = db_row("SELECT messages_sent, sending_at FROM followup_state"
                 " WHERE account_id=? AND fan_id=?", (ctx["aid"], ctx["fan"]))
    return bool(row and row[1] is None and "1" in json.loads(row[0] or "{}"))


async def _purchase_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import AutomationRule, Fan, Message
    await seed_account(aid)
    fan, bought, now = 72003, next(_mids), datetime.utcnow()
    steps = {"enabled": True, "text": "thank you for unlocking that",
             "enabled_at": (now - timedelta(minutes=30)).isoformat()}
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="Purchase follow-up", kind="purchase_followup",
                             trigger_json=json.dumps({"every_seconds": 60}),
                             steps_json=json.dumps(steps), is_enabled=True))
        s.add(Fan(account_id=aid, fan_id=fan))
        s.add(Message(account_id=aid, fan_id=fan, message_id=bought, direction="out",
                      body="a locked set", price_cents=1000, is_paid=True,
                      purchased_at=now - timedelta(minutes=2),
                      created_at=now - timedelta(minutes=10)))
    return {"aid": aid, "of": WireOF(wire, aid), "fan": fan, "bought": bought}


async def _purchase_tick(ctx):
    await _run(ctx["aid"], "purchase_followup", {})


def _purchase_claimed(ctx) -> bool:
    return bool(db_row("SELECT 1 FROM purchase_followup_claims WHERE account_id=? AND fan_id=?"
                       " AND purchased_message_id=?", (ctx["aid"], ctx["fan"], ctx["bought"])))


def _purchase_recorded(ctx) -> bool:
    return bool(db_row("SELECT 1 FROM messages WHERE account_id=? AND fan_id=?"
                       " AND automation_kind='purchase_followup'", (ctx["aid"], ctx["fan"])))


_NUDGE_SLOTS = ("morning_1", "morning_2", "afternoon_1", "afternoon_2", "evening", "night")
_NUDGE_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0, "gap_minutes": 5,
    "quiet_hours": [0, 0], "require_welcomed": False, "online_recent_minutes": 5,
    "min_hours_between_nudges": 12, "max_no_reply": 3, "active_convo_hours": 6,
    "nudge_line_text": True, "nudge_line_image": False, "repeat_mode": "new",
    "slots": {"default": {k: {"text": ["hey {name} a"], "image": []} for k in _NUDGE_SLOTS}},
}


class _OnlineWireOF(WireOF):
    def __init__(self, wire: Wire, account_id: str, fan: int):
        super().__init__(wire, account_id)
        self.fan = fan

    def iter_online_subscribers(self, max_fans=None, **kw):
        return [{"id": self.fan}]


async def _nudge_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import AccountAiConfig, AutomationRule, Fan, NudgeState
    await seed_account(aid)
    fan, now = 72004, datetime.utcnow()
    async with get_session() as s:
        s.add(AccountAiConfig(account_id=aid, utc_offset=0,
                              nudge_config_json=json.dumps(_NUDGE_CFG)))
        s.add(AutomationRule(account_id=aid, name="Nudge online", kind="nudge_online",
                             trigger_json=json.dumps({"every_seconds": 60}),
                             steps_json="{}", is_enabled=True))
        s.add(Fan(account_id=aid, fan_id=fan, real_name="Ed"))
        s.add(NudgeState(account_id=aid, fan_id=fan,
                         last_seen_online_at=now - timedelta(minutes=30),
                         last_nudged_at=now - timedelta(days=2), nudge_count=2,
                         no_reply_streak=1, last_variation_idx=0, last_slot="evening"))
    return {"aid": aid, "of": _OnlineWireOF(wire, aid, fan), "fan": fan}


async def _nudge_tick(ctx):
    await _run(ctx["aid"], "nudge_online", {})
    await _run(ctx["aid"], "nudge_online_fire", None)


def _nudge_claimed(ctx) -> bool:
    row = db_row("SELECT n.pending_job_id, j.status FROM nudge_state n JOIN scheduled_jobs j"
                 " ON j.id = n.pending_job_id WHERE n.account_id=? AND n.fan_id=?",
                 (ctx["aid"], ctx["fan"]))
    return bool(row and row[1] == "running")


def _nudge_bumped(ctx) -> bool:
    row = db_row("SELECT nudge_count, pending_job_id FROM nudge_state"
                 " WHERE account_id=? AND fan_id=?", (ctx["aid"], ctx["fan"]))
    return bool(row and row[0] == 3 and row[1] is None)


DRIVERS = [
    Driver(kind="funnel", setup=_funnel_setup, first=_funnel_tick, tick=_funnel_tick,
           resend=None, pre_write=_funnel_marked, post_update=_funnel_advanced),
    Driver(kind="followup", setup=_followup_setup, first=_followup_tick, tick=_followup_tick,
           resend=None, pre_write=_followup_marked, post_update=_followup_advanced),
    Driver(kind="purchase_followup", setup=_purchase_setup, first=_purchase_tick,
           tick=_purchase_tick, resend=None, pre_write=_purchase_claimed,
           post_update=_purchase_recorded),
    Driver(kind="nudge", setup=_nudge_setup, first=_nudge_tick, tick=_nudge_tick,
           resend=None, pre_write=_nudge_claimed, post_update=_nudge_bumped),
]
