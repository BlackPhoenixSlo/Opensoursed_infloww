#!/usr/bin/env python3
"""test_full_ai_owner_live — `who_owns` in the live sender (04b ticket 81, full_ai_live's four
04b slots off_switch / fans_list / who_owns / human_yield, `full_ai_owner_io._live`).

OF faked (`OwnerOF` behind `ax._make_client`), Jev + Writers faked, the other Lanes' LLM faked at
`llm_client.chat`, holds recorded (never slept). Temp DB only.

  case_two_lanes              Full AI live + Get to know fans + Auto-reply on, one DM through the hook: the
                              W7-queued Get to know fans job and Auto-reply send 0 (0 LLM calls, claimed),
                              Full AI answers once, every sent row full_ai_chat
  case_off_global             FULL_AI_CHAT_OFF before the job: skipped off_switch:off_global, 0 Router calls;
                              during bubble 1's hold: 0 bubbles, stood_down; between bubble 1 and 2: 1 sent
  case_rule_off               rule off during the hold: off_rule, no bubble; his next DM -> Get to know fans
  case_human_row              an employee row during bubble 2's hold: cut human, no send after it, the
                              human's pause outlives the 10 s cooldown; 2 OF-app reads (pre-look, bubble 1)
  case_human_of_app           an unknown creator item in the pre-look's read: skipped human_yield:human_of_app,
                              0 Router calls, 0 rows, pause ~60 s after the item, exactly 1 get_messages
  case_app_before_bubble_1    an OF-app item after the pre-look, before bubble 1: 0 sent, `no_send`,
                              stood_down human_yield:human_of_app, yield started
  case_app_before_ppv         an OF-app item after bubble 1: text bubbles go (no read before them), the
                              card does not, cut human_of_app, Offer NULL + offer_dropped, yield started
  case_app_reads_clear        no outside item: text+card 3 reads (pre, bubble 1, card), card alone 2, all
                              sent; our own sent bubbles in the read never stand down (also with their
                              `messages` rows missing); a raising read sends as today
  case_welcome_handoff        his DM, a welcome after it, the hook's job + the handoff job: one reply; the
                              sweep's pre-look (client None) makes 0 get_messages
  case_job_start_skips        off-list / top spend / hard skip / advancing walk: skipped, 0 Router, 0 rows;
                              off-list answered by Get to know fans, the other three by no Lane
  case_funnel_walk            a pending funnel_state during bubble 2's hold: cut funnel_walk
  case_under_18               says_under_18: `no_send` row; neither other Lane answers on its next run
  case_slot_partition         every `who_owns` reason lands in exactly one of the four slots
  case_live_gate              `_live` follows `live_rule` (a Shadow rule is not live)

Run: ./venv/bin/python service/tests/test_full_ai_owner_live.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select, update  # noqa: E402

import attribution  # noqa: E402
import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from _full_ai_fixtures import KIND, QUIET, _seed  # noqa: E402
from _full_ai_live_fixtures import LiveOF, clear_pause, live_rows, paused, payload, seed_live, world  # noqa: E402
from _full_ai_live_helpers import reply as _reply  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import autoreply, full_ai_live, full_ai_test, welcome_turn  # noqa: E402
from automations import full_ai_owner_io as io  # noqa: E402
from automations.full_ai_sell import Pick  # noqa: E402
from automations._skiplist import MANUAL_RESTRICT_REASON  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    AccountAiConfig, AutomationRule, Employee, Fan, FunnelState, MassRun, Message, ScheduledJob, SkipList,
)

LIST = 778
OFF = "FULL_AI_CHAT_OFF"
_mid = iter(range(8_100_000, 10**9))
OFFER_COLS = ("offer_price_cents", "offer_list_cents", "offer_media_json", "offer_item_ref")
PICK = Pick(ref=711, media=(711, 712), previews=(701,), price_cents=1500, list_cents=1500,
            subject="any", format="photo", lane="paid", facts={})
STYLE = {k: False for k in ("autoreply", "typos_autoreply", "nonnative_autoreply", "nonnative_spacing_autoreply")}


class OwnerOF(LiveOF):
    """LiveOF plus what Get to know fans, Auto-reply and the Fans list read call."""

    def __init__(self, members: list[int] | None = None, **kw):
        super().__init__(**kw)
        self.members = members or []

    def list_users_in(self, list_id, *, limit=20, offset=0):
        ids = self.members if int(list_id) == LIST else []
        return [{"id": i} for i in ids[offset:offset + limit]]

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def fans(self) -> list[int]:
        return [s["fan_id"] for s in self.sent]


@contextlib.contextmanager
def _patched(obj, name, value):
    real = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield real
    finally:
        setattr(obj, name, real)


@contextlib.contextmanager
def _env(on: bool = True):
    try:
        if on:
            os.environ[OFF] = "1"
        yield
    finally:
        os.environ.pop(OFF, None)


@contextlib.contextmanager
def _on_hold(n: int, act):
    """`act()` (async) runs at bubble n's typing hold (1-based); holds never sleep."""
    seen = []

    async def hold(*_a, **_k):
        seen.append(1)
        if len(seen) == n:
            await act()
    with _patched(full_ai_live, "hold_with_typing", hold):
        yield seen


async def _creator(aid: str, *, listed: bool = True, autoreply_on: bool = False) -> int:
    """A live Creator (Get to know fans + reply_mass_funnel rules on, from `_seed`); `listed`: the Fans
    list is include [LIST]; `autoreply_on`: Auto-reply on at 5 min silence."""
    rid = await seed_live(aid, {"fans": {"include": [LIST], "exclude": []}} if listed else {})
    async with get_session() as s:
        await s.execute(update(AccountAiConfig).where(AccountAiConfig.account_id == aid).values(
            utc_offset=0, style_config_json=json.dumps(STYLE),
            autoreply_config_json=json.dumps({"enabled": autoreply_on, "silence_min_minutes": 5})))
    return rid


async def _fan(aid: str, fan: int, *, ago_min: float = 6, spend: int = 0, line: str = "haha what about u") -> int:
    """A Fan who wrote last `ago_min` ago after a short chat (every Lane's candidate): his DM's id."""
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Jack", lifetime_spend_cents=spend,
                  subscribed_at=now - timedelta(days=5), his_age="27", home_city="Ljubljana",
                  hobbies="trail running", likes_boobs=True))
        for d, body, ago in (("out", "hey 😏", 50), ("in", "haha hi", 48), ("out", "what u up to", 46)):
            s.add(Message(account_id=aid, fan_id=fan, message_id=next(_mid), direction=d, body=body,
                          created_at=now - timedelta(minutes=ago)))
    return await _dm(aid, fan, line, ago_min)


async def _dm(aid: str, fan: int, body: str, ago_min: float) -> int:
    mid = next(_mid)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="in", body=body,
                      created_at=datetime.utcnow() - timedelta(minutes=ago_min)))
    return mid


async def _job(aid, fan, mid, rid, of, **kw):
    with world(of, **kw) as w:
        res = await full_ai_live.run(aid, payload(fan, mid, rid), run_id=0)
    return res, w


@contextlib.contextmanager
def _lanes(of: OwnerOF):
    """The other Lanes' world: `of` as every client, their LLM recorded (a canned line)."""
    calls = []

    async def chat(**kw):
        calls.append(kw)
        return SimpleNamespace(content="heyy what are you up to tonight? 😏", call_id=1)
    autoreply._folder_cache.clear()
    with _patched(ax, "_make_client", lambda account_id: of), _patched(llm_client, "chat", chat):
        yield calls


async def _lane(aid: str, kind: str, of: OwnerOF) -> tuple[list[int], list, dict]:
    """One run of `kind`: (fans it sent to, its LLM calls, its result)."""
    before = len(of.sent)
    with _lanes(of) as calls:
        res = await run_once(aid, kind, payload={})
    return of.fans()[before:], calls, res


async def _out_after(aid: str, fan: int, mid: int) -> list[Message]:
    async with get_session() as s:
        at = (await s.get(Message, (aid, fan, mid))).created_at
        return list((await s.execute(select(Message).where(
            Message.account_id == aid, Message.fan_id == fan, Message.direction == "out",
            Message.created_at > at))).scalars())


async def case_two_lanes():
    aid, fan = "fa_ol_two", 901
    await _creator(aid, autoreply_on=True)
    mid = await _fan(aid, fan)
    async with get_session() as s:            # W7 on: the hook wakes Get to know fans for his DM
        await s.execute(update(AccountAiConfig).where(AccountAiConfig.account_id == aid).values(
            webhook_config_json=json.dumps({"enabled": True})))
    of = OwnerOF(members=[fan])
    with world(of) as w:
        await wd.on_inbound_message(aid, fan, mid)
        async with get_session() as s:
            kinds = [k for (k,) in (await s.execute(select(ScheduledJob.kind).where(
                ScheduledJob.account_id == aid, ScheduledJob.status == "pending"))).all()]
            await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid,
                                                       ScheduledJob.kind == "welcome_chatter_for_info")
                            .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
        assert "welcome_chatter_for_info" in kinds and KIND in kinds, kinds
        before = len(of.sent)
        with _lanes(of) as wcalls:
            wres = await run_once(aid, "welcome_chatter_for_info")     # the W7-queued job itself
        wcfi = of.fans()[before:]
        ar, acalls, ares = await _lane(aid, "autoreply", of)
        res = await run_once(aid, KIND)
    assert (wcfi, wcalls, ar, acalls) == ([], [], [], []), (wcfi, len(wcalls), ar, len(acalls))
    assert wres.get("status") == "ok" and wres.get("full_ai_claimed") == 1, wres
    assert ares.get("full_ai_claimed") == 1, ares
    assert res["status"] == "ok", res
    (row,) = await live_rows(aid)
    n = len(_reply(row)["parts"])
    assert row.status == "sent" and of.fans() == [fan] * n, (row.status, of.fans())
    outs = await _out_after(aid, fan, mid)
    assert len(outs) == n and all(o.automation_kind == KIND for o in outs), [o.automation_kind for o in outs]
    assert len(w.jev.calls) == 1


async def case_off_global():
    # Set while the job waits: the pre-look stands down before the Router.
    aid, fan = "fa_ol_off0", 911
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)
    with _env():
        res, w = await _job(aid, fan, mid, rid, LiveOF())
    assert res == {"skipped": "off_switch:off_global"}, res
    assert (w.jev.calls, w.of.calls, w.of.reads, await live_rows(aid)) == ([], 0, 0, [])
    # Set during bubble 1's typing hold: nothing goes out, the reason is on the row.
    aid, fan = "fa_ol_off1", 912
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)

    async def off():
        os.environ[OFF] = "1"
    with _env(False), _on_hold(1, off):
        res, w = await _job(aid, fan, mid, rid, LiveOF())
    (row,) = await live_rows(aid)
    assert (row.status, w.of.calls) == ("no_send", 0), row.status
    assert _reply(row)["stood_down"] == {"check": "off_switch", "reason": "off_global", "index": 0}
    # Set between bubble 1 and 2 of a 3-bubble reply: 1 sent, the rest dropped.
    aid, fan = "fa_ol_off2", 913
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)

    def after(n, _text):
        if n == 1:
            os.environ[OFF] = "1"
    with _env(False):
        res, w = await _job(aid, fan, mid, rid, LiveOF(after=after))
    (row,) = await live_rows(aid)
    assert len(_reply(row)["parts"]) >= 3, _reply(row)["parts"]
    assert (row.status, w.of.calls) == ("sent", 1), row.status
    assert _reply(row)["cut"] == {"check": "off_switch", "reason": "off_global", "index": 1}


async def case_rule_off():
    aid, fan = "fa_ol_rule", 921
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan, ago_min=32)

    async def rule_off():
        async with get_session() as s:
            await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(is_enabled=False))
    with _on_hold(1, rule_off):
        res, w = await _job(aid, fan, mid, rid, LiveOF())
    (row,) = await live_rows(aid)
    assert (row.status, w.of.calls) == ("no_send", 0), row.status
    assert _reply(row)["stood_down"] == {"check": "off_switch", "reason": "off_rule", "index": 0}
    # His next DM: Get to know fans answers him, no cleanup step.
    await _dm(aid, fan, "u there?", 30)
    of = OwnerOF()
    sent, calls, _res = await _lane(aid, "welcome_chatter_for_info", of)
    assert sent == [fan] and calls, (sent, len(calls))


async def _employee() -> int:
    async with get_session() as s:
        e = Employee(display_name=f"chatter{next(_mid)}")
        s.add(e)
        await s.flush()
        return e.id


async def _automation_sentinel() -> None:
    """The Automation Employee (prod's migration 0011): `hard_yield` needs it to rest the Fan."""
    async with get_session() as s:
        if (await s.execute(select(Employee.id).where(Employee.display_name == "Automation"))).first() is None:
            s.add(Employee(display_name="Automation", is_active=False))


async def case_human_row():
    await _automation_sentinel()
    aid, fan = "fa_ol_human", 931
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)
    emp = await _employee()

    async def human():         # a chatter types to him from the app: the row + its yield
        await attribution.write_outbound_attribution(
            account_id=aid, fan_id=fan, message_id=next(_mid), sent_by_employee_id=emp, body="hey its me",
            price_cents=0, created_at=datetime.utcnow())
    of = LiveOF()
    with _on_hold(2, human):
        res, w = await _job(aid, fan, mid, rid, of)
    (row,) = await live_rows(aid)
    assert (row.status, of.calls) == ("sent", 1), row.status
    assert _reply(row)["cut"] == {"check": "human_yield", "reason": "human", "index": 1}
    assert of.reads == 2, of.reads                       # the OF-app read: the pre-look + bubble 1 only
    until = await paused(aid, fan)
    assert until is not None and until > datetime.utcnow() + timedelta(seconds=30), until


async def case_human_of_app():
    aid, fan = "fa_ol_app", 941
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)
    at = datetime.utcnow().replace(microsecond=0) - timedelta(seconds=20)
    of = LiveOF()
    of.chat = [{"id": 7_900_000_000_001, "createdAt": at.isoformat() + "+00:00", "text": "typed in the app",
                "fromUser": {"id": 1}}]
    res, w = await _job(aid, fan, mid, rid, of)
    assert res == {"skipped": "human_yield:human_of_app"}, res
    assert (w.jev.calls, of.calls, of.reads, await live_rows(aid)) == ([], 0, 1, []), (of.reads,)
    until = await paused(aid, fan)
    assert until is not None and abs((until - (at + timedelta(seconds=60))).total_seconds()) <= 5, (until, at)


class AppOF(LiveOF):
    """LiveOF whose chat read lists `chat` plus every DM it took (ours, newest first, as OF lists them);
    `broken`: every read raises."""

    def __init__(self, broken: bool = False, **kw):
        super().__init__(**kw)
        self.broken, self.mine = broken, []

    def send_message(self, chat_id, text, **kw) -> dict:
        res = super().send_message(chat_id, text, **kw)
        self.mine.insert(0, {"id": res["id"], "createdAt": res["createdAt"], "text": text, "fromUser": {"id": 999}})
        return res

    def get_messages(self, chat_id, **kw) -> dict:
        self.reads += 1
        if self.broken:
            raise RuntimeError("OF read failed")
        return {"list": [*self.chat, *self.mine], "hasMore": False}


def _app_item() -> dict:
    """A creator item typed in the OF app just now (an id none of our rows has)."""
    return {"id": 7_900_000_000_000 + next(_mid), "createdAt": datetime.utcnow().isoformat() + "+00:00",
            "text": "typed in the app", "fromUser": {"id": 1}}


def _three(parts: list[str]) -> list[str]:
    return [parts[0], "one sec babe", parts[-1]]


@contextlib.contextmanager
def _sent_as(shape=_three, pick: Pick | None = PICK):
    """Every live Turn's bubbles are `shape(parts)`; `pick`: `PICK` rides the last one (the card)."""
    real = full_ai_test.send

    def send(row, parts, p=None, **kw):
        return real(row, shape(parts), p or pick, **kw)
    with _patched(full_ai_live.full_ai_test, "send", send):
        yield


async def _yielded(aid: str, fan: int) -> None:
    until = await paused(aid, fan)
    assert until is not None and until > datetime.utcnow() + timedelta(seconds=30), until


async def case_app_before_bubble_1():
    # Measured 2026-11-16: an outside reply landed while the Writer ran, after the pre-look's read.
    aid, fan = "fa_ol_app0", 942
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)
    of = AppOF()

    async def human():
        of.chat.append(_app_item())
    with _on_hold(1, human):
        res, w = await _job(aid, fan, mid, rid, of)
    (row,) = await live_rows(aid)
    assert (row.status, of.calls, of.reads) == ("no_send", 0, 2), (row.status, of.calls, of.reads)
    assert _reply(row)["stood_down"] == {"check": "human_yield", "reason": "human_of_app", "index": 0}
    await _yielded(aid, fan)


async def case_app_before_ppv():
    aid, fan = "fa_ol_app1", 943
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)
    of = AppOF(after=lambda n, _t: of.chat.append(_app_item()) if n == 1 else None)
    with _sent_as():                           # text, text, card
        res, w = await _job(aid, fan, mid, rid, of)
    (row,) = await live_rows(aid)
    reply = _reply(row)
    assert len(reply["parts"]) == 3 and "ppv" in reply["parts"][2], reply["parts"]
    assert [("message_id" in p) for p in reply["parts"]] == [True, True, False], reply["parts"]
    # Bubble 2 (text) reads the DB only: the item is seen first at the card's look.
    assert (row.status, of.calls, of.reads) == ("sent", 2, 3), (row.status, of.calls, of.reads)
    assert not any("price" in s for s in of.sent), of.sent
    assert reply["cut"] == {"check": "human_yield", "reason": "human_of_app", "index": 2}, reply.get("cut")
    assert reply["offer_dropped"] == "stood_down" and all(getattr(row, c) is None for c in OFFER_COLS)
    await _yielded(aid, fan)


async def case_app_reads_clear():
    async def turn(aid, fan, of, pick):
        rid = await _creator(aid, listed=False)
        mid = await _fan(aid, fan)
        with pick:
            await _job(aid, fan, mid, rid, of)
        (row,) = await live_rows(aid)
        reply = _reply(row)
        assert row.status == "sent" and "cut" not in reply and of.calls == len(reply["parts"]), (row.status, reply)
        return row, reply
    # Text, text, card: pre-look, bubble 1, the card. Our sent bubbles are in every read after bubble 1.
    of = AppOF()
    row, reply = await turn("fa_ol_app2", 944, of, _sent_as())
    assert (len(reply["parts"]), of.reads, row.offer_price_cents) == (3, 3, 1500), (reply["parts"], of.reads)
    assert reply["parts"][-1]["message_id"] and "price" in of.sent[-1], of.sent
    # The card alone: pre-look + the card.
    of = AppOF()
    row, reply = await turn("fa_ol_app3", 945, of, _sent_as(lambda p: p[-1:]))
    assert (len(reply["parts"]), of.reads) == (1, 2), (reply["parts"], of.reads)
    # Three text bubbles: pre-look + bubble 1.
    of = AppOF()
    row, reply = await turn("fa_ol_app4", 946, of, _sent_as(pick=None))
    assert (len(reply["parts"]), of.reads) == (3, 2), (reply["parts"], of.reads)
    # Bubble 1's `messages` row missing (a best-effort write failed): the card's read lists it, still ours.
    async def no_row(**_kw):
        return None
    of = AppOF()
    with _patched(full_ai_live, "write_outbound_attribution", no_row):
        row, reply = await turn("fa_ol_app5", 947, of, _sent_as(lambda p: [p[0], p[-1]]))
    async with get_session() as s:
        assert await s.get(Message, ("fa_ol_app5", 947, reply["parts"][0]["message_id"])) is None
    assert (len(reply["parts"]), of.reads) == (2, 3) and reply["parts"][-1]["message_id"], of.reads
    # Every read raises: no Stop, all of it sends as today.
    of = AppOF(broken=True)
    row, reply = await turn("fa_ol_app6", 948, of, _sent_as())
    assert of.reads == 3 and reply["parts"][-1]["message_id"], of.reads


async def case_welcome_handoff():
    aid, fan = "fa_ol_wel", 951
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)
    async with get_session() as s:
        s.add(Message(account_id=aid, fan_id=fan, message_id=next(_mid), direction="out", body="welcome babe!",
                      created_at=datetime.utcnow() - timedelta(minutes=5), automation_kind="welcome"))
    of = LiveOF()
    with world(of) as w:
        await wd.on_inbound_message(aid, fan, mid)
        assert await welcome_turn.enqueue_turn_handoff(aid, fan) == KIND
        async with get_session() as s:
            jobs = list((await s.execute(select(ScheduledJob).where(
                ScheduledJob.account_id == aid, ScheduledJob.kind == KIND))).scalars())
            await s.execute(update(ScheduledJob).where(ScheduledJob.account_id == aid, ScheduledJob.kind == KIND)
                            .values(run_at=datetime.utcnow() - timedelta(seconds=1)))
        assert len(jobs) == 2 and {json.loads(j.payload_json)["anchor"] for j in jobs} == {mid}, jobs
        first = await run_once(aid, KIND)
        await clear_pause(aid, fan)
        second = await run_once(aid, KIND)
    (row,) = await live_rows(aid)
    assert (first["status"], second["status"], row.status) == ("ok", "ok", "sent"), (first, second)
    assert of.calls == len(_reply(row)["parts"]) and len(w.jev.calls) == 1
    # The sweep's pre-look (client None) on an open Turn with a human item on OF: 0 OF-app reads
    # (the sweep itself is ticket 68).
    fan2 = 952
    mid2 = await _fan(aid, fan2)
    async with get_session() as s:
        at = (await s.get(Message, (aid, fan2, mid2))).created_at
    of2 = LiveOF()
    of2.chat = [{"id": 7_900_000_000_002, "createdAt": datetime.utcnow().isoformat() + "+00:00", "text": "x",
                 "fromUser": {"id": 1}}]
    with world(of2):
        why = await full_ai_live._look(full_ai_live.Look(aid, fan2, (at, mid2), None, None, None, -1, 0))
    assert why is None and of2.reads == 0, (why, of2.reads)


async def case_job_start_skips():
    aid = "fa_ol_skip"
    rid = await _creator(aid, autoreply_on=True)
    off_list, rich, hard, walking = 961, 962, 963, 964
    mids = {f: await _fan(aid, f, ago_min=30 - i, spend=10**8 if f == rich else 0)
            for i, f in enumerate((off_list, rich, hard, walking))}
    async with get_session() as s:
        s.add(SkipList(account_id=aid, fan_id=hard, reason=MANUAL_RESTRICT_REASON))
        run = MassRun(account_id=aid)
        s.add(run)
        await s.flush()
        s.add(FunnelState(mass_run_id=run.id, fan_id=walking, status="pending"))
    of = OwnerOF(members=[rich, hard, walking])
    want = {off_list: "fans_list:not_listed", rich: "who_owns:top_spend", hard: "who_owns:hard_skip",
            walking: "who_owns:funnel_walk"}
    for f, why in want.items():
        res, w = await _job(aid, f, mids[f], rid, of)
        assert res == {"skipped": why} and w.jev.calls == [], (f, res)
    assert await live_rows(aid) == [] and of.calls == 0
    wcfi, _c, wres = await _lane(aid, "welcome_chatter_for_info", of)
    ar, _c, ares = await _lane(aid, "autoreply", of)
    assert wcfi == [off_list] and ar == [], (wcfi, ar)
    # rich, hard, walking: on the list with Full AI on = claimed, whatever who_owns says
    assert wres.get("full_ai_claimed") == 3 and ares.get("full_ai_claimed") == 3, (wres, ares)


async def case_funnel_walk():
    aid, fan = "fa_ol_walk", 971
    rid = await _creator(aid, listed=False)
    mid = await _fan(aid, fan)

    async def walk():
        async with get_session() as s:
            run = MassRun(account_id=aid)
            s.add(run)
            await s.flush()
            s.add(FunnelState(mass_run_id=run.id, fan_id=fan, status="pending"))
    of = LiveOF()
    with _on_hold(2, walk):
        await _job(aid, fan, mid, rid, of)
    (row,) = await live_rows(aid)
    assert (row.status, of.calls) == ("sent", 1), row.status
    assert _reply(row)["cut"] == {"check": "who_owns", "reason": "funnel_walk", "index": 1}


async def case_under_18():
    aid, fan = "fa_ol_u18", 981
    rid = await _creator(aid, autoreply_on=True)
    mid = await _fan(aid, fan, ago_min=30, line="im 17 lol")
    of = OwnerOF(members=[fan])
    res, w = await _job(aid, fan, mid, rid, of, jev=({**QUIET, "says_under_18": 0.99}, 1.0))
    (row,) = await live_rows(aid)
    assert (row.status, row.route_row, of.calls) == ("no_send", "says_under_18", 0), (row.status, row.route_row)
    wcfi, wc, wres = await _lane(aid, "welcome_chatter_for_info", of)
    ar, ac, ares = await _lane(aid, "autoreply", of)
    assert (wcfi, ar, wc, ac) == ([], [], [], []), (wcfi, ar)
    assert wres.get("full_ai_claimed") == 1 and ares.get("full_ai_claimed") == 1, (wres, ares)


def case_slot_partition():
    """Each `who_owns` reason is answered by exactly one of the four 04b slots."""
    from automations import full_ai_owner
    from automations.full_ai_owner import Stop
    slots = (full_ai_live.off_switch, full_ai_live.fans_list, full_ai_live.who_owns, full_ai_live.human_yield)
    look = full_ai_live.Look("a", 1, (datetime.utcnow(), 1), None, None, None, -1, 0, {"off_switch": None})
    for r in full_ai_owner.REASONS:
        with _patched(full_ai_owner, "who_owns", lambda _f, r=r: Stop(r)):
            hits = [c.__name__ for c in slots if c(look) == r]
        assert len(hits) == 1, (r, hits)
    with _patched(full_ai_owner, "who_owns", lambda _f: None):
        assert all(c(look) is None for c in slots)


async def case_live_gate():
    live, shadow = "fa_ol_gate_live", "fa_ol_gate_shadow"
    await seed_live(live)
    await _seed(shadow, rule=True, gate=False)
    assert await io._live(live) is True and await io._live(shadow) is False
    assert await io._live("fa_ol_gate_none") is False


_harness.run()
