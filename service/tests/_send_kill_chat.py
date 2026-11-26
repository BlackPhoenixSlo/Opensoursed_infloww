from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import _harness
from _send_kill import Driver, Wire, WireOF, db_row, seed_account


def _lease(ctx) -> bool:
    return bool(db_row("SELECT 1 FROM fan_lease WHERE account_id=? AND fan_id=? AND automation_kind=?",
                       (ctx["aid"], ctx["fan"], ctx["lease_kind"])))


@contextlib.contextmanager
def _stubs(reply: str | None = None):
    import llm_client

    async def chat(**kw):
        return SimpleNamespace(content=reply, call_id=1)
    if reply is None:
        yield
        return
    with patch.object(llm_client, "chat", chat):
        yield


async def _run(ctx, kind: str, payload: dict | None = None, reply: str | None = None):
    from automation_executor import run_once
    with _stubs(reply):
        return await run_once(ctx["aid"], kind, payload=payload or {})


async def _msgs(aid: str, fan: int, rows: list[tuple[str, str, int]]) -> None:
    from db.engine import get_session
    from db.models import Message
    now = datetime.utcnow()
    async with get_session() as s:
        for i, (d, body, ago_min) in enumerate(rows):
            s.add(Message(account_id=aid, fan_id=fan, message_id=fan * 100 + i, direction=d,
                          body=f"<p>{body}</p>", created_at=now - timedelta(minutes=ago_min)))


_AR_REPLY = "hey u, been thinking about that sunrise run"


async def _autoreply_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import Fan
    style = json.dumps(dict.fromkeys(
        ("autoreply", "typos_autoreply", "nonnative_autoreply", "nonnative_spacing_autoreply"), False))
    await seed_account(aid, autoreply_config_json=json.dumps({"enabled": True, "silence_min_minutes": 5}),
                   style_config_json=style)
    fan, now = 72001, datetime.utcnow()
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Jack", lifetime_spend_cents=0,
                  subscribed_at=now - timedelta(days=5), his_age="27", home_city="Ljubljana",
                  hobbies="trail running", likes_boobs=True))
    await _msgs(aid, fan, [("out", "hey", 50), ("in", "haha hi", 48), ("out", "what u up to", 46),
                           ("in", "you up?", 30)])
    return {"aid": aid, "fan": fan, "of": WireOF(wire, aid), "lease_kind": "autoreply"}


async def _autoreply_tick(ctx):
    await _run(ctx, "autoreply", reply=_AR_REPLY)


_FA_KIND = "full_ai_chat"
_FA_LINE = "ok:haha stop it"


@contextlib.contextmanager
def _fa_world(ctx):
    from _full_ai_live_helpers import HOSTS
    from _full_ai_live_helpers import world as fa_world
    with fa_world(ctx["of"], writers=dict.fromkeys(HOSTS, _FA_LINE)):
        yield


async def _fa_live_setup(aid: str, wire: Wire):
    from _full_ai_fixtures import _msg
    from _full_ai_live_helpers import seed_live
    rid = await seed_live(aid)
    fan, mid = 72003, 72003_01
    await _msg(aid, fan, mid, "in", "hey you, how was your day", datetime.utcnow() - timedelta(minutes=5))
    return {"aid": aid, "fan": fan, "mid": mid, "rid": rid, "of": WireOF(wire, aid)}


async def _due_jobs(ctx, kind: str) -> None:
    from automation_executor import run_once
    for _ in range(4):
        with sqlite3.connect(str(_harness.DB_PATH)) as c:
            c.execute("UPDATE scheduled_jobs SET run_at=? WHERE account_id=? AND kind=? AND status='pending'",
                      ((datetime.utcnow() - timedelta(seconds=1)).isoformat(sep=" "), ctx["aid"], kind))
        if (await run_once(ctx["aid"], kind)).get("reason") == "no_job":
            return


async def _fa_live_first(ctx):
    from automations import full_ai_live
    with _fa_world(ctx):
        await full_ai_live.enqueue(ctx["aid"], ctx["fan"], ctx["mid"], ctx["rid"])
        await _due_jobs(ctx, _FA_KIND)


async def _fa_live_tick(ctx):
    from automation_executor import run_once
    with _fa_world(ctx):
        await run_once(ctx["aid"], _FA_KIND, payload={})
        await _due_jobs(ctx, _FA_KIND)


def _fa_row(ctx, where: str):
    return db_row(f"SELECT 1 FROM ai_decisions WHERE account_id=? AND fan_id=? AND mode='live' AND {where}",
                  (ctx["aid"], ctx["fan"]))


async def _fa_ppv_setup(aid: str, wire: Wire):
    from _full_ai_fixtures import _msg
    from _full_ai_live_helpers import seed_live
    from automations import full_ai_test
    from automations.full_ai_sell import Pick
    from db.engine import get_session
    from db.models import AiDecision
    await seed_live(aid)
    fan, mid = 72004, 72004_01
    at = datetime.utcnow() - timedelta(minutes=5)
    await _msg(aid, fan, mid, "in", "show me something", at)
    pick = Pick(ref=8601, media=(8601, 8602), previews=(8603,), price_cents=1500, list_cents=1500,
                subject="shower", format="photo", lane="L1", facts={})
    row = dict(account_id=aid, fan_id=fan, mode="live", trigger_kind="inbound", trigger_key=str(mid),
               route="sell_now", heat=2, route_row="sell", question_version="v", reply_json={}, jev_json={})
    full_ai_test.send(row, ["this one is just for u"], pick)
    async with get_session() as s:
        obj = AiDecision(**dict(row, status="sending", anchor_message_id=mid, anchor_created_at=at,
                                reply_json=json.dumps(row["reply_json"]), jev_json=json.dumps(row["jev_json"])))
        s.add(obj)
        await s.flush()
        rid = int(obj.id)
    return {"aid": aid, "fan": fan, "row": rid, "ppv": row["reply_json"]["parts"][-1]["ppv"],
            "of": WireOF(wire, aid)}


async def _fa_ppv_first(ctx):
    from automations import full_ai_ppv
    await full_ai_ppv.send_priced(ctx["of"], row_id=ctx["row"], account_id=ctx["aid"], fan_id=ctx["fan"],
                                  text="this one is just for u", ppv=ctx["ppv"], send_purpose="gated",
                                  min_gap_s=0.0)


def _fa_ppv_col(ctx, col: str) -> bool:
    return bool(db_row(f"SELECT 1 FROM ai_decisions WHERE id=? AND {col} IS NOT NULL", (ctx["row"],)))


class _SubsOF(WireOF):

    def __init__(self, wire: Wire, account_id: str, fan: int):
        super().__init__(wire, account_id)
        self.fan = fan

    def notifications(self, *, limit: int = 10, offset: int = 0, type=None, **kw) -> dict:
        return {"list": [{"user": {"id": self.fan, "name": None, "username": f"u{self.fan}"}}],
                "hasMore": False}


_WELCOME = {"message": "hey welcome babe, so happy ur here"}


async def _welcome_setup(aid: str, wire: Wire):
    await seed_account(aid)
    fan = 72005
    return {"aid": aid, "fan": fan, "of": _SubsOF(wire, aid, fan), "lease_kind": "send_welcome"}


async def _welcome_tick(ctx):
    await _run(ctx, "send_welcome", payload=dict(_WELCOME), reply="hey")


_WCFI_REPLY = "heyy what are you up to tonight?"


class _NickOF(WireOF):

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}


async def _wcfi_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import Fan
    await seed_account(aid)
    fan = 72006
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Bob", lifetime_spend_cents=0))
    await _msgs(aid, fan, [("out", "hey babe", 30), ("in", "hi! how are you", 29)])
    return {"aid": aid, "fan": fan, "of": _NickOF(wire, aid), "lease_kind": "welcome_chatter_for_info"}


async def _wcfi_tick(ctx):
    await _run(ctx, "welcome_chatter_for_info", reply=_WCFI_REPLY)


_CLOSING = {"closing_ppv_text": "a little goodbye gift", "closing_ppv_media_ids": [501, 502],
            "closing_ppv_price_cents": 1500}


async def _closing_setup(aid: str, wire: Wire):
    from db.engine import get_session
    from db.models import Fan
    await seed_account(aid)
    fan = 72007
    async with get_session() as s:
        s.add(Fan(account_id=aid, fan_id=fan, of_display_name="Tom", lifetime_spend_cents=0))
    await _msgs(aid, fan, [("in", f"msg {i}", 40 - i) for i in range(10)])
    return {"aid": aid, "fan": fan, "of": _NickOF(wire, aid), "lease_kind": "welcome_chatter_for_info"}


async def _closing_tick(ctx):
    await _run(ctx, "welcome_chatter_for_info", payload=dict(_CLOSING), reply=_WCFI_REPLY)


DRIVERS = [
    Driver(
        kind="autoreply",
        setup=_autoreply_setup,
        first=_autoreply_tick,
        tick=_autoreply_tick,
        resend=None,
        pre_write=_lease,
        post_update=lambda ctx: bool(db_row(
            "SELECT 1 FROM autoreply_state WHERE account_id=? AND fan_id=? AND nudges_sent=1",
            (ctx["aid"], ctx["fan"]))),
    ),
    Driver(
        kind="full_ai_live",
        setup=_fa_live_setup,
        first=_fa_live_first,
        tick=_fa_live_tick,
        resend=None,
        pre_write=lambda ctx: _fa_row(ctx, "status='sending'"),
        post_update=lambda ctx: bool(_fa_row(ctx, "status='sent'")),
    ),
    Driver(
        kind="full_ai_ppv",
        setup=_fa_ppv_setup,
        first=_fa_ppv_first,
        tick=_fa_live_tick,
        resend=None,
        pre_write=lambda ctx: _fa_ppv_col(ctx, "offer_attempt_at"),
        post_update=lambda ctx: _fa_ppv_col(ctx, "offer_message_id"),
    ),
    Driver(
        kind="send_welcome",
        setup=_welcome_setup,
        first=_welcome_tick,
        tick=_welcome_tick,
        resend=None,
        pre_write=_lease,
        post_update=lambda ctx: bool(db_row(
            "SELECT 1 FROM welcome_sent WHERE account_id=? AND fan_id=?", (ctx["aid"], ctx["fan"]))),
    ),
    Driver(
        kind="welcome_chatter",
        setup=_wcfi_setup,
        first=_wcfi_tick,
        tick=_wcfi_tick,
        resend=None,
        pre_write=lambda ctx: db_row(
            "SELECT 1 FROM fans WHERE account_id=? AND fan_id=? AND turn_counter=1", (ctx["aid"], ctx["fan"])),
        post_update=lambda ctx: bool(db_row(
            "SELECT 1 FROM fans WHERE account_id=? AND fan_id=? AND last_message_sent_at IS NOT NULL",
            (ctx["aid"], ctx["fan"]))),
    ),
    Driver(
        kind="welcome_closing_ppv",
        setup=_closing_setup,
        first=_closing_tick,
        tick=_closing_tick,
        resend=None,
        pre_write=lambda ctx: bool(db_row(
            "SELECT 1 FROM fans WHERE account_id=? AND fan_id=? AND gather_close_sending_at IS NOT NULL",
            (ctx["aid"], ctx["fan"]))),
        post_update=lambda ctx: bool(db_row(
            "SELECT 1 FROM fans WHERE account_id=? AND fan_id=? AND gather_close_at IS NOT NULL",
            (ctx["aid"], ctx["fan"]))),
    ),
]
