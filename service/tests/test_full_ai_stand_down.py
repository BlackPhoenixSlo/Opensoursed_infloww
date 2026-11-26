#!/usr/bin/env python3
from __future__ import annotations

import _harness

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import autoreply  # noqa: E402
from automations import full_ai_owner_io as io  # noqa: E402
from automations.full_ai_owner import Stop, who_owns  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    Account, AccountAiConfig, AiDecision, AutomationRule, Fan, FunnelState, MassRun, Message,
)

LIST = 777
_mid = iter(range(5_000_000, 10**9))
_n = 0
_VOLATILE = {"status", "run_id", "job_id", "duration_ms"}


class FakeOF:

    def __init__(self, members: list[int] | None = None):
        self.sent: list[tuple[int, str]] = []
        self.members = members or []
        self._id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._id += 1
        self.sent.append((int(chat_id), text))
        when = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "+00:00"
        return {"id": self._id, "text": f"<p>{text}</p>", "createdAt": when}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}

    def list_users_in(self, list_id, *, limit=20, offset=0):
        ids = self.members if int(list_id) == LIST else []
        return [{"id": i} for i in ids[offset:offset + limit]]

    def fans(self) -> set[int]:
        return {c for c, _ in self.sent}


@contextlib.contextmanager
def _world(members: list[int] | None = None, *, live: bool = True):
    fake, calls = FakeOF(members), []
    real_client, real_chat, real_live = ax._make_client, llm_client.chat, io._live

    async def chat(**kw):
        calls.append(kw)
        return SimpleNamespace(content="heyy what are you up to tonight? 😏", call_id=1)

    async def is_live(account_id):
        return live
    ax._make_client = lambda account_id: fake
    llm_client.chat = chat
    io._live = is_live
    autoreply._folder_cache.clear()
    try:
        yield fake, calls
    finally:
        ax._make_client, llm_client.chat, io._live = real_client, real_chat, real_live


def _mentions(calls: list[dict], needle: str) -> int:
    return sum(needle in json.dumps(c, default=str) for c in calls)


async def _account(*, rule: bool | None = True, listed: bool = True) -> str:
    global _n
    _n += 1
    aid = f"acc-sd-{_n}"
    ar = {"enabled": True, "silence_min_minutes": 5}
    style = {k: False for k in ("autoreply", "typos_autoreply", "nonnative_autoreply", "nonnative_spacing_autoreply")}
    fa = {"checkpoint": {"fans": {"include": [LIST] if listed else [], "exclude": []}}, "rev": 1}
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(AccountAiConfig(account_id=aid, utc_offset=0, autoreply_config_json=json.dumps(ar),
                              style_config_json=json.dumps(style), full_ai_config_json=json.dumps(fa)))
        if rule is not None:
            s.add(AutomationRule(account_id=aid, name="Full AI Chat", kind="full_ai_chat", trigger_json="{}",
                                 steps_json="{}", is_enabled=rule))
    return aid


async def _waiting(aid: str, fan: int, line: str, *, spend: int = 0) -> None:
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Jack", lifetime_spend_cents=spend,
                  subscribed_at=now - timedelta(days=5), his_age="27", home_city="Ljubljana",
                  hobbies="trail running", likes_boobs=True))
        for d, body, ago in (("out", "hey 😏", 50), ("in", "haha hi", 48), ("out", "what u up to", 46),
                             ("in", line, 30)):
            s.add(Message(account_id=aid, fan_id=fan, message_id=next(_mid), direction=d, body=body,
                          created_at=now - timedelta(minutes=ago)))


def _stats(res: dict) -> dict:
    return {k: v for k, v in res.items() if k not in _VOLATILE}


async def case_wcfi_skips_claimed():
    aid = await _account()
    await _waiting(aid, 101, "claimed line aaa")
    await _waiting(aid, 102, "free line bbb")
    with _world(members=[101]) as (fake, calls):
        res = await run_once(aid, "welcome_chatter_for_info", payload={})
    assert res["status"] == "ok", res
    assert fake.fans() == {102}, fake.sent
    assert _mentions(calls, "claimed line aaa") == 0 and _mentions(calls, "free line bbb") >= 1, calls
    assert res["full_ai_claimed"] == 1 and res["replies_sent"] == 1, res
    other = await _account(rule=None)
    await _waiting(other, 101, "claimed line aaa")
    await _waiting(other, 102, "free line bbb")
    with _world(members=[101, 102]) as (fake, calls):
        res = await run_once(other, "welcome_chatter_for_info", payload={})
    assert fake.fans() == {101, 102} and "full_ai_claimed" not in res, (fake.sent, res)


async def case_wcfi_forced_still_skipped():
    aid = await _account()
    await _waiting(aid, 201, "claimed forced ccc")
    with _world(members=[201]) as (fake, calls):
        res = await run_once(aid, "welcome_chatter_for_info", payload={
            "only_fan_ids": [201], "force_ids": [201], "turn_handoff_ids": [201]})
    assert fake.sent == [] and _mentions(calls, "claimed forced ccc") == 0, (fake.sent, calls)
    assert res["full_ai_claimed"] == 1, res


async def case_autoreply_skips_claimed():
    aid = await _account()
    await _waiting(aid, 301, "claimed ar ddd")
    await _waiting(aid, 302, "free ar eee")
    with _world(members=[301]) as (fake, calls):
        res = await run_once(aid, "autoreply", payload={})
    assert fake.fans() == {302}, (fake.sent, res)
    assert [c.get("fan_id") for c in calls] == [302], calls
    assert res["full_ai_claimed"] == 1 and res["sent"] == 1, res
    lim = await _account()
    for f in (311, 312, 313):
        await _waiting(lim, f, f"ar line {f}")
    with _world(members=[311]) as (fake, calls):
        res = await run_once(lim, "autoreply", payload={"limit": 1})
    assert len(fake.sent) == 1 and fake.fans() <= {312, 313}, (fake.sent, res)
    assert res["full_ai_claimed"] == 1 and res["candidates"] == 1, res


async def _both_lanes(aid: str, members: list[int]) -> tuple[set[int], set[int], dict, dict]:
    with _world(members=members) as (fake, _calls):
        w = await run_once(aid, "welcome_chatter_for_info", payload={})
        wcfi = fake.fans()
    with _world(members=members) as (fake, _calls):
        a = await run_once(aid, "autoreply", payload={})
        ar = fake.fans()
    return wcfi, ar, w, a


async def case_no_send_turn_stays_claimed():
    aid = await _account()
    await _waiting(aid, 401, "im 17 lol")
    async with get_session() as s:
        s.add(AiDecision(account_id=aid, fan_id=401, mode="live", trigger_kind="inbound", trigger_key="1",
                         route="no_send", heat=0, route_row="says_under_18", question_version="q1",
                         status="no_send"))
    wcfi, ar, w, a = await _both_lanes(aid, [401])
    assert wcfi == set() and ar == set(), (wcfi, ar)
    assert w["full_ai_claimed"] == 1 and a["full_ai_claimed"] == 1, (w, a)


async def case_top_spend_and_walk_claimed():
    aid = await _account()
    await _waiting(aid, 501, "big spender fff", spend=200000)
    await _waiting(aid, 502, "walking ggg")
    async with get_session() as s:
        s.add(AutomationRule(account_id=aid, name="rmf", kind="reply_mass_funnel", trigger_json="{}",
                             steps_json="{}", is_enabled=True))
        run = MassRun(account_id=aid)
        s.add(run)
        await s.flush()
        s.add(FunnelState(mass_run_id=run.id, fan_id=502, status="pending"))
    with _world(members=[501, 502]):
        anchor = datetime.utcnow() - timedelta(minutes=31)
        assert who_owns(await io.load(aid, 501, anchor)) == Stop("top_spend")
        assert who_owns(await io.load(aid, 502, anchor)) == Stop("funnel_walk")
        assert await io.claimed_ids(aid, [501, 502]) == {501, 502}
    wcfi, ar, w, a = await _both_lanes(aid, [501, 502])
    assert wcfi == set() and ar == set(), (wcfi, ar)
    assert w["full_ai_claimed"] == 2 and a["full_ai_claimed"] == 2, (w, a)


async def _seed_pair(*, rule: bool | None = True) -> str:
    aid = await _account(rule=rule)
    await _waiting(aid, 601, "off line hhh")
    await _waiting(aid, 602, "off line iii")
    return aid


async def _off_run(*, rule: bool | None = True, live: bool = True, stub: bool = False) -> tuple:
    real = io.stand_down

    async def noop(account_id, fan_ids, *, lane, client=None):
        return set(), {}
    out = []
    if stub:
        io.stand_down = noop
    try:
        for kind in ("welcome_chatter_for_info", "autoreply"):
            aid = await _seed_pair(rule=rule)
            with _world(members=[601, 602], live=live) as (fake, _c):
                res = await run_once(aid, kind, payload={})
            out += [fake.fans(), res]
    finally:
        io.stand_down = real
    return tuple(out)


async def case_off_is_today():
    wcfi0, w0, ar0, a0 = await _off_run(stub=True)
    assert wcfi0 == ar0 == {601, 602}, (wcfi0, ar0)

    def same(got):
        wcfi, w, ar, a = got
        assert (wcfi, ar) == (wcfi0, ar0), (wcfi, ar)
        assert _stats(w) == _stats(w0) and _stats(a) == _stats(a0), (_stats(w), _stats(w0), _stats(a), _stats(a0))
        assert "full_ai_claimed" not in w and "full_ai_claimed" not in a

    same(await _off_run(rule=False))
    same(await _off_run(rule=None))
    os.environ["FULL_AI_CHAT_OFF"] = "1"
    try:
        same(await _off_run())
    finally:
        del os.environ["FULL_AI_CHAT_OFF"]
    same(await _off_run(live=False))


class _Count(logging.Handler):
    def __init__(self):
        super().__init__()
        self.hits: list[str] = []

    def emit(self, record):
        if "full_ai_stand_down_failed" in record.getMessage():
            self.hits.append(record.getMessage())


async def case_claimed_ids_raising():
    real = io.claimed_ids

    async def boom(account_id, fan_ids, *, client=None):
        raise RuntimeError("full ai broke")
    for kind in ("welcome_chatter_for_info", "autoreply"):
        aid = await _seed_pair()
        h = _Count()
        io.log.addHandler(h)
        io.claimed_ids = boom
        try:
            with _world(members=[601, 602]) as (fake, _c):
                res = await run_once(aid, kind, payload={})
        finally:
            io.claimed_ids = real
            io.log.removeHandler(h)
        assert fake.fans() == {601, 602}, (kind, fake.sent, res)
        assert len(h.hits) == 1 and "full_ai_claimed" not in res, (kind, h.hits, res)


async def case_bad_config_claims_nobody():
    from automations import full_ai_live
    for blob in ("{not json", "[1, 2]"):
        for kind in ("welcome_chatter_for_info", "autoreply"):
            aid = await _account()
            async with get_session() as s:
                (await s.get(AccountAiConfig, aid)).full_ai_config_json = blob
            await _waiting(aid, 701, "bad config fff")
            with _world(members=[701]) as (fake, _c):
                res = await run_once(aid, kind, payload={})
            assert fake.fans() == {701} and "full_ai_claimed" not in res, (blob, kind, fake.sent, res)
        with _world(members=[701]):
            assert await io.claimed_ids(aid, [701]) == set(), blob
            facts = await io.load(aid, 701, datetime.utcnow())
            assert facts.off is None and facts.listed is False, (blob, facts)
            assert await full_ai_live._run(aid, {"only_fan_ids": [701]}) == {"skipped": "bad_config"}, blob


async def case_stand_down_reuses_client():
    real, seen = io.claimed_ids, []

    async def spy(account_id, fan_ids, *, client=None):
        seen.append(client)
        return {1}
    io.claimed_ids = spy
    try:
        mine = object()
        assert await io.stand_down("a", [1, 2], lane="autoreply", client=mine) == ({1}, {"full_ai_claimed": 1})
        assert await io.stand_down("a", [1], lane="welcome_chatter_for_info") == ({1}, {"full_ai_claimed": 1})
    finally:
        io.claimed_ids = real
    assert seen == [mine, None], seen
    src = (_harness._REPO_ROOT / "service/automations/autoreply.py").read_text()
    assert 'lane="autoreply",\n        client=client)' in src


if __name__ == "__main__":
    _harness.run()
