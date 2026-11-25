#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import update  # noqa: E402

from _full_ai_live_helpers import (  # noqa: E402
    DEEPSEEK, LINE, NANO, QUIET, FakeInfoJev, dm_turn, extract_says, fan_row, get_fan, her_reply,
    live_rows, reply, seed_live,
)
from automations import _info_jev, full_ai_live, full_ai_test  # noqa: E402
from automations.full_ai_config import DEFAULTS  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AiDecision, Fan  # noqa: E402

NO_LEAD = {"lead_in": False}


def _writer_text(fw) -> str:
    return json.dumps([x["body"]["messages"] for x in fw.requests if x["host"] == NANO])


def _offered(info: FakeInfoJev) -> list[str]:
    q = info.calls[-1]["questions"].get("next_question")
    return [k for k in (q.criteria if q is not None else {}) if k != "none"]


async def case_fans_row_reaches_writer():
    aid, fan = "fa_facts_writer", 601
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan, real_name="Tom", home_city="Leeds", occupation="  ", of_display_name="tommy_of",
                  custom_nickname="T-bone")
    res, _fake, _j, info, fw = await dm_turn(aid, fan, 6011, "hey u up")
    assert res["row_status"] == "sent", res
    w = _writer_text(fw)
    assert "Tom" in w and "Leeds" in w, w
    offered = _offered(info)
    assert offered and "real_name" not in offered and "home_city" not in offered, offered
    assert "occupation" in offered, offered
    (row,) = await live_rows(aid, fan)
    fi = reply(row)["fan_info"]
    assert fi == {"real_name": "Tom", "home_city": "Leeds", "of_display_name": "tommy_of"}, fi


async def case_extract_lands_in_fans():
    aid, fan = "fa_facts_extract", 602
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan, real_name="Sam")
    before = await get_fan(aid, fan)
    res, *_ = await dm_turn(aid, fan, 6021, "im 31 btw", info=FakeInfoJev(({"his_age": 0.95}, "none")),
                            writers={DEEPSEEK: extract_says(his_age="31")})
    assert res["row_status"] == "sent", res
    (r1,) = await live_rows(aid, fan)
    assert reply(r1)["info_error"] is None and reply(r1)["fan_info"]["his_age"] == "31", reply(r1)
    f = await get_fan(aid, fan)
    assert f.his_age == "31" and f.real_name == "Sam", (f.his_age, f.real_name)
    assert f.grok_facts_updated_at is not None and f.updated_at > before.updated_at
    stamp = f.grok_facts_updated_at
    await her_reply(aid, fan, 6022)
    res, _f, _j, _i, fw = await dm_turn(aid, fan, 6023, "what are u up to")
    assert res["row_status"] == "sent", res
    r2 = (await live_rows(aid, fan))[-1]
    assert reply(r2)["fan_info"] == {"real_name": "Sam", "his_age": "31"}, reply(r2)
    assert DEEPSEEK not in [x["host"] for x in fw.requests], fw.requests
    assert (await get_fan(aid, fan)).grok_facts_updated_at == stamp
    await her_reply(aid, fan, 6024)
    upd = (await get_fan(aid, fan)).updated_at
    res, *_ = await dm_turn(aid, fan, 6025, "promo pls", jev=({**QUIET, "promo": 0.99}, 1.0))
    assert res["row_status"] == "no_send", res
    assert (await get_fan(aid, fan)).updated_at == upd


async def case_wcfi_write_between_turns():
    aid, fan = "fa_facts_wcfi", 603
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan)
    await dm_turn(aid, fan, 6031, "hey")
    async with get_session() as s:
        await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == fan).values(home_country="UK"))
    await her_reply(aid, fan, 6032)
    _res, _f, _j, info, _fw = await dm_turn(aid, fan, 6033, "so whats up")
    r2 = (await live_rows(aid, fan))[-1]
    assert reply(r2)["fan_info"] == {"home_country": "UK"}, reply(r2)
    assert "home_country" not in _offered(info), _offered(info)


async def case_asked_not_repeated():
    aid, fan = "fa_facts_asked", 604
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan)
    res, *_ = await dm_turn(aid, fan, 6041, "hey", info=FakeInfoJev(({}, "occupation")),
                            writers={NANO: LINE + "\nASKED: occupation"})
    (r1,) = await live_rows(aid, fan)
    assert reply(r1)["asked"] == {"occupation": 1}, reply(r1)
    await her_reply(aid, fan, 6042)
    _res, _f, _j, info, _fw = await dm_turn(aid, fan, 6043, "lol idk", info=FakeInfoJev(({}, "none")))
    st = info.calls[-1]["state"]
    offered = _offered(info)
    assert st["asked"] == _info_jev.state({}, {"occupation": 1}, offered)["asked"], st["asked"]
    assert st["asked"]["occupation"] == 1, st["asked"]
    r2 = (await live_rows(aid, fan))[-1]
    assert reply(r2)["asked"] == {"occupation": 1}, reply(r2)


async def case_list_mode_asked():
    aid, fan = "fa_facts_list", 605
    cfg = {**NO_LEAD, "info_questions": "list"}
    await seed_live(aid, cfg)
    await fan_row(aid, fan)
    asked = {"job": 2, "name": 1}
    await _seed_row(aid, fan, "6050", {"asked": asked, "typo_state": {}})
    await her_reply(aid, fan, 6050, at=datetime.utcnow() - timedelta(minutes=5))
    await dm_turn(aid, fan, 6051, "hey whats new")
    r = (await live_rows(aid, fan))[-1]
    info = json.loads(r.jev_json)["info"]
    want = [k for k, _ in _info_jev.still_needed({**DEFAULTS, **cfg}, {}, asked)]
    assert info["still_needed"] == want and "job" not in want, (info, want)


async def _seed_row(aid: str, fan: int, key: str, rep: dict, *, status: str = "sent",
                    at: datetime | None = None) -> None:
    async with get_session() as s:
        s.add(AiDecision(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=key,
                         route="chat", heat=0, route_row="chat", question_version="v", status=status,
                         reply_json=json.dumps(rep), jev_json="{}",
                         created_at=at or datetime.utcnow() - timedelta(minutes=5)))


async def case_typo_state_carried():
    aid, fan = "fa_facts_typo", 606
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan, custom_fields='{"_typo_fix": {"n": 3}}')
    typo = {"since_fix": 0, "fixes": 1}
    await _seed_row(aid, fan, "6060", {"parts": [{"text": "omg"}, {"text": "*fix"}], "typo_state": typo})
    await her_reply(aid, fan, 6060, at=datetime.utcnow() - timedelta(minutes=5))
    await _msg_in(aid, fan, 6061)
    got = await full_ai_live.load(aid, fan, None)
    assert got.typo_state == typo, got.typo_state
    await dm_turn(aid, fan, 6062, "haha ok")
    r = (await live_rows(aid, fan))[-1]
    assert r.trigger_key == "6062" and isinstance(reply(r)["typo_state"], dict), reply(r)
    assert (await get_fan(aid, fan)).custom_fields == '{"_typo_fix": {"n": 3}}'


async def _msg_in(aid: str, fan: int, mid: int, body: str = "hey") -> None:
    from _full_ai_fixtures import _msg
    await _msg(aid, fan, mid, "in", body, datetime.utcnow() - timedelta(seconds=5))


async def case_newest_row_any_status():
    aid, fan = "fa_facts_status", 607
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan)
    await _seed_row(aid, fan, "6070", {"asked": {"occupation": 1}, "typo_state": {"a": 1}},
                    at=datetime.utcnow() - timedelta(minutes=9))
    await _seed_row(aid, fan, "6071", {"asked": {"occupation": 2}, "typo_state": {"a": 2}}, status="no_send",
                    at=datetime.utcnow() - timedelta(minutes=8))
    await _msg_in(aid, fan, 6072)
    got = await full_ai_live.load(aid, fan, None)
    assert got.asked == {"occupation": 2} and got.typo_state == {"a": 2}, (got.asked, got.typo_state)
    await _seed_row(aid, fan, "6073", {"asked": {"occupation": 3}, "typo_state": {"a": 3}}, status="failed",
                    at=datetime.utcnow() - timedelta(minutes=1))
    got = await full_ai_live.load(aid, fan, None)
    assert got.asked == {"occupation": 3} and got.typo_state == {"a": 3}, (got.asked, got.typo_state)
    async with get_session() as s:
        s.add(AiDecision(account_id=aid, fan_id=fan, mode="shadow", trigger_kind="inbound", trigger_key="6074",
                         route="chat", heat=0, route_row="chat", question_version="v", status="planned",
                         reply_json=json.dumps({"asked": {"x": 9}}), jev_json="{}"))
    got = await full_ai_live.load(aid, fan, None)
    assert got.asked == {"occupation": 3}, got.asked
    await _seed_row(aid, fan, "6075", {}, at=datetime.utcnow())
    async with get_session() as s:
        await s.execute(update(AiDecision).where(AiDecision.trigger_key == "6075").values(reply_json=None))
    got = await full_ai_live.load(aid, fan, None)
    assert got.asked == {} and got.typo_state == {}, got.asked


async def case_blank_extract_never_overwrites():
    upd = full_ai_live.fan_updates
    loaded = {"his_age": "31", "real_name": "Tom"}
    assert upd(loaded, {"his_age": "", "real_name": "   "}) == {}
    assert upd(loaded, {"his_age": " 31 ", "real_name": "Tom"}) == {}
    assert upd(loaded, {"his_age": "32", "home_city": " Leeds "}) == {"his_age": "32", "home_city": "Leeds"}
    assert upd({}, {"generated_nickname": "x", "of_display_name": "y"}) == {}
    assert upd({}, {"hobbies": "a" * 300}) == {"hobbies": "a" * 200}
    aid, fan = "fa_facts_blank", 608
    await seed_live(aid, NO_LEAD)
    await fan_row(aid, fan, his_age="31")
    stamp = (await get_fan(aid, fan)).grok_facts_updated_at
    res, *_ = await dm_turn(aid, fan, 6081, "lol", info=FakeInfoJev(({"his_age": 0.95}, "none")),
                            writers={DEEPSEEK: extract_says(his_age="  ")})
    assert res["row_status"] == "sent", res
    f = await get_fan(aid, fan)
    assert f.his_age == "31" and f.grok_facts_updated_at == stamp, (f.his_age, f.grok_facts_updated_at, stamp)


async def case_he_likes_from_fans():
    aid, fan = "fa_facts_likes", 609
    await seed_live(aid, {"he_likes": True})
    await fan_row(aid, fan, fetishes="feet, stockings")
    await _msg_in(aid, fan, 6091)
    got = await full_ai_live.load(aid, fan, None)
    assert got.state["he_likes"] == "feet, stockings", got.state
    _res, _f, jevs, _i, _fw = await dm_turn(aid, fan, 6092, "hey")
    assert jevs.calls[0]["state"]["he_likes"] == "feet, stockings", jevs.calls[0]["state"]
    aid2, fan2 = "fa_facts_likes0", 610
    await seed_live(aid2, {"he_likes": True})
    await _msg_in(aid2, fan2, 6101)
    got = await full_ai_live.load(aid2, fan2, None)
    assert got.state["he_likes"] == full_ai_test.NO_LIKES == "nothing stored yet", got.state
    aid3, fan3 = "fa_facts_likes_off", 611
    await seed_live(aid3, {"he_likes": False})
    await _msg_in(aid3, fan3, 6111)
    assert "he_likes" not in (await full_ai_live.load(aid3, fan3, None)).state


_harness.run()
