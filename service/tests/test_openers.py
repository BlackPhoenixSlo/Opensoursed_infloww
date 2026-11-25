from __future__ import annotations

import _harness  # MUST be first: binds temp DB

from datetime import datetime

from db.engine import get_session
import json

from db.models import Account, Fan, SkipList
from automations import _openers as op
from automations.fan_state import fan_state, put_fan_state, set_fan_state

_harness.bootstrap()

_GEN = datetime(2026, 7, 26, 12, 0, 0)
_GEN2 = datetime(2026, 7, 27, 12, 0, 0)


class _P:

    def __init__(self, *, generated_at=_GEN, **slots):
        self.last_generated_at = generated_at
        for s in op.ALL_SLOTS:
            setattr(self, s, slots.get(s))



class _F:

    def __init__(self, state=None):
        self.custom_fields = (json.dumps({op.STATE_KEY: state})
                              if state is not None else None)


def _next(profile, state=None):
    return op._next_opener(profile, fan_state(_F(state), op.STATE_KEY))

def _deepen(state=None) -> dict:
    return dict(state or {})


def case_corrupt_or_absent_state_is_handled_not_trusted():
    p = _P(q1="what got you into welding?")
    for junk in ({}, None, "not a dict", {"used": "q1"}, {"used": [7, "nope"]},
                 {"gen": None, "used": ["q1"]}):
        o = _next(p, junk)
        assert o is not None and o.slot == "q1", (junk, o)


def case_questions_before_teases_skipping_blank_slots():
    p = _P(q2="hows the new job treating you?", tease3="still thinking about that photo")
    o = _next(p)
    assert (o.cls, o.slot) == ("q", "q2")
    assert o.text == "hows the new job treating you?"
    assert o.text in o.instruction

    st = op.mark_used(_deepen(), p, "q2")
    o2 = _next(p, st)
    assert (o2.cls, o2.slot) == ("tease", "tease3")
    assert "NOT an opener" in o2.instruction

    assert _next(_P()) is None
    assert _next(None) is None


def case_each_opener_is_offered_once_and_the_text_survives():
    p = _P(q1="a", q2="b", q3="c", tease1="d", tease2="e", tease3="f")
    st, seen = _deepen(), []
    while (o := _next(p, st)) is not None:
        seen.append(o.slot)
        st = op.mark_used(st, p, o.slot)
        assert len(seen) <= len(op.ALL_SLOTS) + 1, "pool never drained — offering a repeat"
    assert seen == ["q1", "q2", "q3", "tease1", "tease2", "tease3"]
    assert [getattr(p, s) for s in op.ALL_SLOTS] == ["a", "b", "c", "d", "e", "f"]


def case_a_refill_restocks_the_pool_with_no_clearing_step():
    p = _P(q1="old question")
    st = op.mark_used(_deepen(), p, "q1")
    assert _next(p, st) is None

    refilled = _P(generated_at=_GEN2, q1="new question")
    o = _next(refilled, st)
    assert o is not None and o.text == "new question"

    assert _next(_P(generated_at=None, q1="x"),
                 op.mark_used(_deepen(), _P(generated_at=None), "q1")) is None


def case_need_block_is_the_only_door_a_tease_can_walk_through():
    from automations import welcome_chatter_for_info

    class _Rich:
        last_generated_at = _GEN
        q1 = q2 = q3 = None
        tease1, tease2, tease3 = "that photo you sent", "your hands", "friday night"
        short_bio, bullet_points = "a welder from Calgary", "likes trucks"

    f, p = _EngineFan(), _Rich()
    for build, cand in ((welcome_chatter_for_info._build_messages, _OfCand()),):
        msgs, _ = build("persona", f, cand, set(), profile=p, opener=None)
        blob = "\n".join(m["content"] for m in msgs)
        for t in (p.tease1, p.tease2, p.tease3):
            assert t not in blob, (build.__module__, f"tease menu still in the prompt: {t}")
        assert "a welder from Calgary" in blob, build.__module__

        o = op.Opener("tease", "tease1", p.tease1,
                      op._T_INSTRUCTION.format(line=p.tease1))
        msgs, _ = build("persona", f, cand, set(), profile=p, opener=o)
        blob = "\n".join(m["content"] for m in msgs)
        assert blob.count(p.tease1) == 1, (build.__module__, "tease delivered twice")
        assert p.tease2 not in blob and p.tease3 not in blob, \
            (build.__module__, "the siblings rode along unmetered")


def case_the_regen_gate_has_no_lines_exemption():
    import inspect
    from automations.gen_info import profile_is_stale, _MIN_NEW_MSGS
    params = inspect.signature(profile_is_stale).parameters
    assert "lines_empty" not in params and "class_spent" not in params, list(params)
    assert not hasattr(op, "class_spent"), "the spent-class refill trigger is gone"

    now = datetime(2026, 7, 27, 12, 0)
    gen = datetime(2026, 7, 27, 11, 0)
    assert not profile_is_stale(100, gen, 100 + 1, now)
    assert not profile_is_stale(100, gen, 100 + _MIN_NEW_MSGS - 1, now)


async def case_the_refresh_hook_ignores_lines():
    from automations.welcome_chatter_for_info import _maybe_refresh_profile

    aid, fid = "op_row", 5108
    await _seed(aid, fid, profile={})
    assert await _maybe_refresh_profile(aid, fid, 1, datetime.utcnow()) is False, \
        "a line-less profile skipped the new-message gate"
    assert await _maybe_refresh_profile(aid, 999_111, 1, datetime.utcnow()) is False, \
        "a never-profiled fan skipped the new-message gate"


def case_mark_used_rejects_an_unknown_slot():
    try:
        op.mark_used({}, _P(), "not_a_slot")
        assert False, "expected ValueError"
    except ValueError:
        pass


async def case_state_round_trips_without_clobbering_a_sibling():
    aid, fid = "op_acct", 4242
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid))
        await s.commit()

    await set_fan_state(aid, fid, "_tip_request", {"at": "2026-07-26T10:00:00"})

    p = _P(q1="hows the welding going?")
    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        st = fan_state(fan, op.STATE_KEY)
        assert st == {}
        o = _next(p, _deepen(st))
        put_fan_state(fan, op.STATE_KEY, op.mark_used(_deepen(st), p, o.slot))
        await s.commit()

    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        st = fan_state(fan, op.STATE_KEY)
        assert st["used"] == ["q1"]
        assert _next(p, st) is None
        assert fan_state(fan, "_tip_request") == {"at": "2026-07-26T10:00:00"}



_COMPLETE = dict(his_age="31", home_country="Canada", home_city="Calgary",
                 hobbies="welding", occupation="welder", real_name="Jack",
                 recent_events='["started a new job"]', likes_boobs=True)


async def _seed(aid: str, fid: int, *, profile: dict | None = None,
                msgs: int = 1, **fan_kw):
    from datetime import timedelta
    from db.models import Account, FanProfile, Message
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        if await s.get(Fan, (aid, fid)) is None:
            s.add(Fan(account_id=aid, fan_id=fid, **{**_COMPLETE, **fan_kw}))
        for i in range(msgs):
            s.add(Message(account_id=aid, fan_id=fid, message_id=fid * 1000 + i,
                          direction="in", body="hey you",
                          created_at=_GEN + timedelta(minutes=i)))
        if profile is not None and await s.get(FanProfile, (aid, fid)) is None:
            s.add(FanProfile(account_id=aid, fan_id=fid, message_count_at_gen=0,
                             total_spend_at_gen_cents=0,
                             notes_applied_successfully=False,
                             last_generated_at=_GEN, **profile))
        await s.commit()


def _fake_of():
    import automation_executor as ax
    import llm_client
    from types import SimpleNamespace

    class _OF:
        def __init__(self):
            self.sent = []

        def send_message(self, chat_id, text, **kw):
            self.sent.append((int(chat_id), text))
            return {"id": 9_000_000_000_000 + len(self.sent), "text": text,
                    "createdAt": "2026-07-26T12:30:00+00:00"}

        def set_fan_custom_name(self, *a, **k): return {"success": True}
        def set_fan_note(self, *a, **k): return {"success": True}
        def mark_chat_read(self, *a, **k): return {"success": True}
        def me(self, *a, **k): return {"id": 1}

    of, prompts = _OF(), []

    async def _chat(**kw):
        prompts.append(kw.get("messages"))
        return SimpleNamespace(content="so hows the welding going", call_id=1)

    ax._make_client = lambda account_id: of      # type: ignore[attr-defined]
    llm_client.chat = _chat                      # type: ignore[attr-defined]
    return of, prompts


async def case_welcome_chatter_for_info_uses_an_opener_instead_of_graduating():
    from automation_executor import run_once
    aid, fid = "op_wire1", 5101
    await _seed(aid, fid, profile={"q1": "hows the welding apprenticeship going?"})
    of, prompts = _fake_of()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, res
    assert res["newly_skiplisted"] == 0, ("finished the gather but was graduated", res)
    assert of.sent, "no reply sent"

    system = "\n".join(m["content"] for m in prompts[-1] if m["role"] == "system")
    assert "welding apprenticeship" in system, "the opener never reached the prompt"

    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        assert fan_state(fan, op.STATE_KEY).get("used") == ["q1"], "slot not marked used"
        assert (await s.get(SkipList, (aid, fid))) is None, "fan was skip-listed"


async def case_welcome_chatter_for_info_graduates_only_once_the_pool_is_dry():
    from automation_executor import run_once
    aid, fid = "op_wire2", 5102
    await _seed(aid, fid, profile={"q1": "used up"})
    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        put_fan_state(fan, op.STATE_KEY, {"gen": _GEN.isoformat(), "used": ["q1"]})
        await s.commit()
    of, _ = _fake_of()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0 and res["newly_skiplisted"] == 1, res
    assert of.sent == [], "graduating fan must not also be replied to"
    async with get_session() as s:
        row = await s.get(SkipList, (aid, fid))
        assert row is not None and row.reason == "info", row


async def case_finishing_the_gather_survives_the_too_long_cutoff():
    from automation_executor import run_once
    from automations.welcome_chatter_for_info import _MAX_FAN_MESSAGES
    aid, fid = "op_wire3", 5103
    await _seed(aid, fid, profile={"q1": "hows the welding going?"},
                msgs=_MAX_FAN_MESSAGES + 2)
    of, _ = _fake_of()

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 1, ("cut by too_long after finishing the gather", res)
    async with get_session() as s:
        assert (await s.get(SkipList, (aid, fid))) is None


async def case_welcome_chatter_for_info_finishes_after_one_pass_even_though_gen_info_restocks():
    from automation_executor import run_once
    aid, fid = "op_wire6", 5107
    await _seed(aid, fid, profile={"q1": "a", "q2": "b", "tease1": "c", "tease2": "d"})
    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        put_fan_state(fan, op.STATE_KEY,
                      {"gen": "an-older-generation", "used": [],
                       "classes_done": ["q", "tease"]})
        await s.commit()
    of, _ = _fake_of()

    done = {"classes_done": ["q", "tease"]}
    full = _P(q1="a", tease1="b")
    assert op.next_for(_F(done), full) is None
    assert _next(full, done) is not None
    assert op.next_for(_F({"classes_done": ["q"]}), full) is not None

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0 and res["newly_skiplisted"] == 1, \
        ("a restocked pool kept the fan in welcome_chatter_for_info for ever", res)
    async with get_session() as s:
        row = await s.get(SkipList, (aid, fid))
        assert row is not None and row.reason == "info", row


async def case_a_failed_send_does_not_burn_the_opener():
    from automation_executor import run_once
    aid, fid = "op_wire4", 5105
    await _seed(aid, fid, profile={"q1": "hows the welding going?"})
    of, _ = _fake_of()

    def _boom(chat_id, text, **kw):
        raise RuntimeError("OF 500")
    of.send_message = _boom

    res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["replies_sent"] == 0 and res["errors"] >= 1, res
    async with get_session() as s:
        fan = await s.get(Fan, (aid, fid))
        assert fan_state(fan, op.STATE_KEY).get("used") in (None, []), \
            "a failed send burned the opener"


class _OfCand:
    fan_id = 5104
    messages = [("in", "hey you")]
    last_body = "hey you"
    fan_msg_n = 1
    last_in_at = None
    session_out_n = 0
    last_in_text = "hey you"
    last_dir = "in"
    msg_ids: list[int] = []
    reply_ctx = None


class _EngineFan:
    real_name, custom_nickname = "Jack", "Jack"
    his_age, home_country, home_city = "31", "Canada", "Calgary"
    occupation, hobbies = "welder", "welding"
    fetishes, recent_events = None, '["started a new job"]'
    likes_boobs = likes_ass = True
    questions_asked = None
    persona_claims_json = None
    of_display_name = generated_nickname = None
    custom_fields = None


if __name__ == "__main__":
    _harness.run(
        case_corrupt_or_absent_state_is_handled_not_trusted,
        case_questions_before_teases_skipping_blank_slots,
        case_each_opener_is_offered_once_and_the_text_survives,
        case_a_refill_restocks_the_pool_with_no_clearing_step,
        case_need_block_is_the_only_door_a_tease_can_walk_through,
        case_the_regen_gate_has_no_lines_exemption,
        case_the_refresh_hook_ignores_lines,
        case_mark_used_rejects_an_unknown_slot,
        case_state_round_trips_without_clobbering_a_sibling,
        case_welcome_chatter_for_info_uses_an_opener_instead_of_graduating,
        case_welcome_chatter_for_info_graduates_only_once_the_pool_is_dry,
        case_welcome_chatter_for_info_finishes_after_one_pass_even_though_gen_info_restocks,
        case_a_failed_send_does_not_burn_the_opener,
        case_finishing_the_gather_survives_the_too_long_cutoff,
    )
