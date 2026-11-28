#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import nudge_online, nudge_online_fire  # noqa: E402
from automations._fan_notes import substitute_placeholders  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AutomationRule, AutomationRun, Fan, Message, NudgeState, ScheduledJob,
    Transaction, WelcomeSent,
)

OWN_ID = "999"

_ABSENT = object()



class FakeOF:

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



_BASE_CFG = {
    "enabled": True, "delay_minutes": 0, "jitter_minutes": 0,
    "gap_minutes": 5, "quiet_hours": [0, 0], "require_welcomed": False,
    "max_per_tick": 25, "online_recent_minutes": 5,
    "min_hours_between_nudges": 12, "max_no_reply": 3, "active_convo_hours": 6,
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
        has_rule = (await s.execute(select(AutomationRule.id).where(
            AutomationRule.account_id == aid,
            AutomationRule.kind == "nudge_online"))).first()
        if has_rule is None:
            s.add(AutomationRule(account_id=aid, name="Nudge online", kind="nudge_online",
                                 trigger_json=json.dumps({"every_seconds": 60}),
                                 steps_json="{}", is_enabled=True))


async def _warm(aid: str) -> None:
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



async def case_pending_dedup_skips():
    aid = "n_dedup"
    await _seed_cfg(aid)
    await _warm(aid)
    await _seed_state(aid, 3001,
                      last_seen_online_at=datetime.utcnow() - timedelta(hours=1),
                      pending_job_id=777)
    _use_fake([_online(3001, "Eve")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 0, res
    assert res["skip_reasons"].get("pending") == 1, res
    assert await _jobs(aid, "nudge_online_fire") == [], "no new job while one pending"



async def case_cap_defers_overflow():
    aid = "n_cap"
    await _seed_cfg(aid, max_per_tick=1)
    await _warm(aid)
    _use_fake([_online(4001, "Fay"), _online(4002, "Gus")])

    r1 = await run_once(aid, "nudge_online", payload={})
    assert r1["handled"] == 1 and r1["deferred"] == 1 and r1["enqueued"] == 1, r1
    st1 = await _state(aid, 4001)
    assert st1 is not None and st1.pending_job_id is not None, st1
    st2 = await _state(aid, 4002)
    assert st2 is None or st2.last_seen_online_at is None, "overflow left stale"

    r2 = await run_once(aid, "nudge_online", payload={})
    assert r2["enqueued"] == 1, r2
    jobs = await _jobs(aid, "nudge_online_fire")
    fan_ids = {json.loads(j.payload_json)["fan_id"] for j in jobs}
    assert fan_ids == {4001, 4002}, fan_ids



async def case_fire_sends_when_valid():
    aid = "n_fire"
    await _seed_cfg(aid)
    await _warm(aid)
    fake = _use_fake([_online(5001, "Hank")])

    await run_once(aid, "nudge_online", payload={})
    res = await run_once(aid, "nudge_online_fire")
    assert res.get("sent") == 1, res
    assert len(fake.sent) == 1 and fake.sent[0][0] == 5001, fake.sent

    st = await _state(aid, 5001)
    assert st.last_nudged_at is not None and st.nudge_count == 1, st
    assert st.pending_job_id is None, "pending cleared after send"
    async with get_session() as s:
        msgs = (await s.execute(select(Message).where(
            Message.account_id == aid, Message.direction == "out"))).scalars().all()
    assert len(msgs) == 1 and msgs[0].fan_id == 5001, msgs



async def case_fire_skips_when_offline():
    aid = "n_off"
    await _seed_cfg(aid)
    await _seed_state(aid, 6001,
                      last_seen_online_at=datetime.utcnow() - timedelta(minutes=30),
                      pending_job_id=42)
    fake = _use_fake([])

    res = await run_once(aid, "nudge_online_fire", payload={"fan_id": 6001})
    assert res["sent"] == 0 and res["skipped"] == "offline", res
    assert fake.sent == [], fake.sent
    st = await _state(aid, 6001)
    assert st.pending_job_id is None, "pending cleared on cancel"



async def case_fire_skips_when_convo_started():
    aid = "n_convo"
    await _seed_cfg(aid)
    await _seed_state(aid, 7001,
                      last_seen_online_at=datetime.utcnow(), pending_job_id=43)
    await _seed_msg(aid, 7001, "out", datetime.utcnow() - timedelta(minutes=2), 70001)
    fake = _use_fake([])

    res = await run_once(aid, "nudge_online_fire", payload={"fan_id": 7001})
    assert res["sent"] == 0 and res["skipped"] == "recent_outbound", res
    assert fake.sent == [], fake.sent
    st = await _state(aid, 7001)
    assert st.pending_job_id is None, st



async def _welcome_rule(aid: str, on: bool) -> None:
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="Welcome", kind="send_welcome",
                             trigger_json=json.dumps({"every_seconds": 60}),
                             steps_json="{}", is_enabled=on))


async def case_gate_not_welcomed():
    aid = "n_welc"
    await _seed_cfg(aid, require_welcomed=True)
    await _welcome_rule(aid, True)
    await _warm(aid)
    async with get_session() as s:
        s.add(WelcomeSent(account_id=aid, fan_id=8002,
                          sent_at=datetime.utcnow() - timedelta(hours=5)))
    _use_fake([_online(8001, "Ivy"), _online(8002, "Joe")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 1, res
    assert res["skip_reasons"].get("not_welcomed") == 1, res
    jobs = await _jobs(aid, "nudge_online_fire")
    assert {json.loads(j.payload_json)["fan_id"] for j in jobs} == {8002}, jobs


async def case_gate_welcomed_ignored_while_welcome_off():
    for aid, rule in (("n_welc_off", False), ("n_welc_none", None)):
        await _seed_cfg(aid, require_welcomed=True)
        if rule is not None:
            await _welcome_rule(aid, rule)
        await _warm(aid)
        _use_fake([_online(8101, "Ivy")])
        res = await run_once(aid, "nudge_online", payload={})
        assert res["enqueued"] == 1 and "not_welcomed" not in res["skip_reasons"], (aid, res)



async def case_spend_gate_lifetime():
    aid = "n_spend_life"
    await _seed_cfg(aid, max_lifetime_spend_cents=2000)
    await _warm(aid)
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=8101, lifetime_spend_cents=500))
        s.add(Fan(account_id=aid, fan_id=8102, lifetime_spend_cents=5000))
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
        s.add(Transaction(account_id=aid, fan_id=8201, kind="tip",
                          amount_cents=1000, occurred_at=now - timedelta(days=5)))
        s.add(Transaction(account_id=aid, fan_id=8202, kind="tip",
                          amount_cents=1000, occurred_at=now - timedelta(days=60)))
    _use_fake([_online(8201, "Rec"), _online(8202, "Old")])

    res = await run_once(aid, "nudge_online", payload={})
    assert res["enqueued"] == 1, res
    assert res["skip_reasons"].get("recent_spend_above_max") == 1, res
    jobs = await _jobs(aid, "nudge_online_fire")
    assert {json.loads(j.payload_json)["fan_id"] for j in jobs} == {8202}, jobs



async def case_no_cooldown_set():
    aid = "n_async"
    await _seed_cfg(aid)
    await _warm(aid)
    _use_fake([_online(9001, "Jay")])

    await run_once(aid, "nudge_online", payload={})
    await run_once(aid, "nudge_online_fire")
    assert await ax.fan_on_cooldown(aid, 9001) is False, "nudge must not set cooldown"



def case_compose_helpers():
    slots = nudge_online._DEFAULT_NUDGE_CONFIG["slots"]
    fri = nudge_online._pick_pool(slots, "afternoon_2", "Friday")
    assert any("friday" in t.lower() for t in fri["text"]), fri
    sat = nudge_online._pick_pool(slots, "evening", "Saturday")
    assert any("weekend" in t.lower() or "friday" in t.lower() for t in sat["text"]), sat
    wed = nudge_online._pick_pool(slots, "night", "Wednesday")
    assert wed == slots["default"]["night"], wed
    mixed = {"default": {"night": {"text": ["d"], "image": [1]}},
             "weekend": {"night": {"text": ["w"], "image": []}},
             "saturday": {"night": {"text": [], "image": [7]}}}
    assert nudge_online._pick_pool(mixed, "night", "Saturday") == {"text": ["w"], "image": [7]}
    assert nudge_online._pick_pool(mixed, "night", "Sunday") == {"text": ["w"], "image": [1]}
    assert nudge_online._pick_pool(mixed, "night", "Monday") == {"text": ["d"], "image": [1]}
    assert nudge_online._pick_pool({}, "night", "Monday")["text"], "generic fallback line"

    class _St:
        def __init__(self, idx, slot): self.last_variation_idx = idx; self.last_slot = slot
    assert nudge_online._choose_idx(None, 7, 5, "new") == 7 % 5
    assert nudge_online._choose_idx(_St(2, "evening"), 7, 5, "new") == 3
    assert nudge_online._choose_idx(_St(4, "evening"), 7, 5, "new") == 0
    assert nudge_online._choose_idx(_St(2, "evening"), 7, 5, "same") == 2

    out = substitute_placeholders("hi {name} from {city} 💕", None, name="Tom")
    assert out == "hi Tom from 💕", out
    out2 = substitute_placeholders("hey {name}", None, name="")
    assert out2 == "hey babe", out2


async def case_images_rotate_on_their_own_when_the_counts_differ():
    cfg = {"repeat_mode": "new", "nudge_line_image": True, "slots": {
        "default": {"evening": {"text": ["hi"], "image": []}},
        "friday": {"evening": {"text": [], "image": [11, 12, 13]}}}}

    class _St:
        def __init__(self, n, idx=0):
            self.nudge_count, self.last_variation_idx, self.last_slot = n, idx, "evening"

    async def _media(c, st):
        msgs, _ = await nudge_online._compose_messages("n_img_rot", None, c, None, st,
                                                       hour=19, weekday="friday")
        return msgs[0]["media"]
    got = [await _media(cfg, st) for st in (None, _St(1), _St(2), _St(3))]
    assert got == [[11], [12], [13], [11]], got
    same = {**cfg, "repeat_mode": "same"}
    assert [await _media(same, st) for st in (None, _St(1), _St(2))] == [[11]] * 3
    paired = {**cfg, "slots": {"default": {"evening": {"text": ["a", "b"], "image": [21, 22]}}}}
    assert await _media(paired, _St(5, idx=0)) == [22], "line 1 rides with image 1"


async def case_small_hours_of_the_night_slot_read_the_evening_before():
    cfg = {"nudge_line_image": False, "slots": {
        "thursday": {"night": {"text": ["thu night"]}},
        "friday": {"night": {"text": ["fri night"]}}}}
    for hour, want in ((2, "thu night"), (23, "fri night")):
        msgs, slot = await nudge_online._compose_messages("n_night", None, cfg, None, None,
                                                          hour=hour, weekday="friday")
        assert slot == "night" and msgs[0]["text"] == want, (hour, msgs)
    res = await nudge_online.preview_compose("n_night", cfg, hour=2, weekday="friday")
    assert res["messages"][0]["text"] == "thu night", res



async def case_legacy_info_line_keys_ignored():
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

    cfg = await nudge_online._load_nudge_config(aid)
    prev = await nudge_online.preview_compose(aid, cfg, fan_id=20001)
    assert [m["kind"] for m in prev["messages"]] == ["nudge"], prev


async def case_preview_picks_the_asked_day():
    slots = {"default": {"afternoon_2": {"text": ["hey {name}"], "image": [11]}},
             "friday": {"afternoon_2": {"text": [], "image": [77]}}}
    cfg = {**nudge_online._DEFAULT_NUDGE_CONFIG, "slots": slots, "utc_offset": 0, "time_images": {}}
    fri = await nudge_online.preview_compose("n_prev_day", cfg, hour=16, weekday="friday")
    mon = await nudge_online.preview_compose("n_prev_day", cfg, hour=16, weekday="monday")
    assert [(m["text"], m["media"]) for m in fri["messages"]] == [("hey Jack", [77])], fri
    assert [(m["text"], m["media"]) for m in mon["messages"]] == [("hey Jack", [11])], mon



async def case_with_image_layers_the_payload_over_the_account_cfg():
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

    assert await enqueued_with_image("aa", cfg_value=_ABSENT, payload={}) is True
    assert await enqueued_with_image("af", cfg_value=False, payload={}) is False
        # A stored null falls through to the account cfg, so it can read off while the catalog default is on.
    assert await enqueued_with_image("nf", cfg_value=False, payload={"with_image": None}) is False
    assert await enqueued_with_image("na", cfg_value=_ABSENT, payload={"with_image": None}) is True
    assert await enqueued_with_image("pf", cfg_value=True, payload={"with_image": False}) is False
    assert await enqueued_with_image("pt", cfg_value=False, payload={"with_image": True}) is True



class _RosterRefused(RuntimeError):
    reason = "platform_lacks:subscribers:incomplete"


async def _roster_refused_run(aid: str, error: Exception) -> tuple[dict, list, list]:
    await _seed_cfg(aid)
    await _warm(aid)
    fake = _use_fake([_online(3001, "Eve")])

    def refuse(**_kw):
        raise error
    fake.iter_online_subscribers = refuse
    res = await run_once(aid, "nudge_online", payload={})
    async with get_session() as s:
        states = (await s.execute(select(NudgeState.fan_id, NudgeState.last_seen_online_at).where(
            NudgeState.account_id == aid))).all()
    return res, states, await _jobs(aid, "nudge_online_fire")


async def case_incomplete_roster_skips_before_any_last_seen_or_enqueue():
    res, states, jobs = await _roster_refused_run("n_incomplete", _RosterRefused("short roster"))
    assert res["status"] == "skipped" and res["reason"] == "platform_lacks:subscribers:incomplete", res
    async with get_session() as s:
        assert (await s.get(AutomationRun, res["run_id"])).status == "skipped"
    assert [fid for fid, _seen in states] == [1] and jobs == [], (states, jobs)


async def case_a_roster_read_error_without_a_lack_is_still_an_error():
    res, states, jobs = await _roster_refused_run("n_read_error", RuntimeError("network"))
    assert res["status"] == "error", res
    assert [fid for fid, _seen in states] == [1] and jobs == [], (states, jobs)


_harness.run(
    case_warmup_seeds_no_send,
    case_newly_online_enqueues,
    case_pending_dedup_skips,
    case_cap_defers_overflow,
    case_fire_sends_when_valid,
    case_fire_skips_when_offline,
    case_fire_skips_when_convo_started,
    case_gate_not_welcomed,
    case_gate_welcomed_ignored_while_welcome_off,
    case_spend_gate_lifetime,
    case_spend_gate_recent_window,
    case_no_cooldown_set,
    case_with_image_layers_the_payload_over_the_account_cfg,
    case_compose_helpers,
    case_images_rotate_on_their_own_when_the_counts_differ,
    case_small_hours_of_the_night_slot_read_the_evening_before,
    case_legacy_info_line_keys_ignored,
    case_preview_picks_the_asked_day,
    case_incomplete_roster_skips_before_any_last_seen_or_enqueue,
    case_a_roster_read_error_without_a_lack_is_still_an_error,
)
