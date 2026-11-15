#!/usr/bin/env python3
"""test_full_ai_live — Full AI Chat Mode live tracer (04a ticket 63, automations/full_ai_live.py).

OF faked at `ax._make_client` (FakeOF records each send), `of_write_paced` unspaced (its purpose
recorded), Jev (FakeJev) and the Writers' wire (FakeWriterHTTP) faked. Temp DB only.

  case_tracer_one_dm_one_reply       live rule + his DM + hook + run_once: FakeOF got the reply's
                                     bubbles in order; one live row (sent, anchor set, message ids);
                                     one full_ai_chat `messages` row per bubble; no lease; 10 s cooldown
  case_no_send_route                 FakeJev promo: no OF call, one no_send row, lease released
  case_same_job_twice                the second run sends nothing, still one row
  case_shadow_rule_untouched         a rule without `mode` on another Creator: the planned Shadow row,
                                     no OF client, no lease
  case_welcome_after_dm_keeps_turn   his DM then a `welcome` outbound: answered once, Anchor his DM
  case_longer_pause_not_shortened    a pause written during the run outlives the 10 s cooldown
  case_only_live_sends               AST: spine + full_ai_test never import full_ai_live / full_ai_ppv;
                                     among full_ai_*.py, _router_jev, _info_jev only those two have a
                                     send path (owner_io: reads + the yield pause, no send)

Run: ./venv/bin/python service/tests/test_full_ai_live.py  (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import ast  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from sqlalchemy import select, text, update  # noqa: E402

from _full_ai_fixtures import (  # noqa: E402
    KIND, QUIET, T0, FakeJev, FakeWriterHTTP, _fake_jev, _msg, _rows, _seed,
)
import automation_executor as ax  # noqa: E402
import fan_lease  # noqa: E402
import webhook_dispatch as wd  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import full_ai_live  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import AutomationRule, Fan, Message  # noqa: E402

os.environ.setdefault("NANOGPT_API_KEY", "test-nanogpt-house-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-house-key")
LINE = "ok:haha stop it. what are u doing later tonight"
HOSTS = ("nano-gpt.com", "openrouter.ai", "api.z.ai", "api.deepseek.com")
AUTOMATIONS = Path(__file__).resolve().parents[1] / "automations"


class FakeOF:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self._id = 9_600_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._id += 1
        self.sent.append((int(chat_id), text))
        return {"id": self._id, "text": text, "createdAt": datetime.utcnow().isoformat() + "+00:00"}


@contextlib.contextmanager
def _world(jev=(QUIET, 1.0)):
    """FakeOF behind the client factory, unspaced OF writes, faked Jev and Writers."""
    fake, made, purposes = FakeOF(), [], []
    real_make, real_paced = ax._make_client, ax.of_write_paced

    async def unpaced(account_id, fn, **kw):
        purposes.append(kw.get("send_purpose"))
        assert kw.get("min_gap_s") == full_ai_live.WRITE_GAP_S == 2.0, kw   # the Full AI gap, not 11 s
        return await real_paced(account_id, fn, **{**kw, "min_gap_s": 0.0, "pause_s": 0.0})

    def make(account_id):
        made.append(account_id)
        return fake
    ax._make_client, ax.of_write_paced = make, unpaced
    jevs = FakeJev(*([jev] * 4))
    try:
        with FakeWriterHTTP(dict.fromkeys(HOSTS, LINE)).on(), _fake_jev(jevs):
            yield fake, made, purposes
    finally:
        ax._make_client, ax.of_write_paced = real_make, real_paced


async def _seed_live(aid: str) -> int:
    rid = await _seed(aid, rule=True, gate=False)
    async with get_session() as s:
        await s.execute(update(AutomationRule).where(AutomationRule.id == rid).values(
            trigger_json=json.dumps({"every_seconds": 300, "mode": "live"})))
    return rid


async def _out_rows(aid: str, fan: int) -> list[Message]:
    async with get_session() as s:
        return list((await s.execute(select(Message).where(
            Message.account_id == aid, Message.fan_id == fan, Message.direction == "out",
            Message.automation_kind == KIND).order_by(Message.created_at, Message.message_id))).scalars())


async def _leases(aid: str) -> list[tuple]:
    async with get_session() as s:
        return [tuple(r) for r in (await s.execute(text(
            "SELECT * FROM fan_lease WHERE account_id = :a"), {"a": aid})).all()]


async def _paused(aid: str, fan: int) -> datetime | None:
    async with get_session() as s:
        return (await s.execute(select(Fan.automation_paused_until).where(
            Fan.account_id == aid, Fan.fan_id == fan))).scalar_one_or_none()


async def _clear_pause(aid: str, fan: int) -> None:
    async with get_session() as s:
        await s.execute(update(Fan).where(Fan.account_id == aid, Fan.fan_id == fan)
                        .values(automation_paused_until=None))


async def _dm_run(aid: str, fan: int, mid: int, body: str = "hey you, how was your day", *,
                  at: datetime | None = None, jev=(QUIET, 1.0)):
    """His DM lands (the hook queues the job), then one run_once: (result, FakeOF, made, purposes)."""
    await _msg(aid, fan, mid, "in", body, at or datetime.utcnow() - timedelta(minutes=3))   # past "0-2m"
    with _world(jev) as (fake, made, purposes):
        await wd.on_inbound_message(aid, fan, mid)
        res = await run_once(aid, KIND)
    return res, fake, made, purposes


async def case_tracer_one_dm_one_reply():
    aid, fan, mid = "fa_live_tracer", 501, 7101
    await _seed_live(aid)
    res, fake, made, purposes = await _dm_run(aid, fan, mid)
    assert res["status"] == "ok", res
    (row,) = await _rows(aid)
    reply = json.loads(row.reply_json)
    parts = reply["parts"]
    assert parts and all(set(p) == {"text", "message_id"} for p in parts), parts
    assert fake.sent == [(fan, p["text"]) for p in parts], (fake.sent, parts)
    assert (row.mode, row.trigger_kind, row.trigger_key, row.status) == ("live", "inbound", str(mid), "sent"), row
    assert row.anchor_message_id == mid and row.anchor_created_at is not None
    assert [p["message_id"] for p in parts] == [9_600_000_000_001 + i for i in range(len(parts))]
    outs = await _out_rows(aid, fan)
    assert [o.message_id for o in outs] == [p["message_id"] for p in parts], outs
    assert purposes == ["gated"] * len(parts), purposes
    assert made == [aid]
    assert not [r for r in await _leases(aid) if KIND in r], await _leases(aid)
    until = await _paused(aid, fan)
    now = datetime.utcnow()
    assert until is not None and now < until <= now + timedelta(seconds=11), until


async def case_no_send_route():
    aid, fan, mid = "fa_live_nosend", 502, 7201
    await _seed_live(aid)
    res, fake, _made, purposes = await _dm_run(aid, fan, mid, jev=({**QUIET, "promo": 0.99}, 1.0))
    assert res["status"] == "ok", res
    (row,) = await _rows(aid)
    assert (row.status, row.route, row.mode) == ("no_send", "no_send", "live"), (row.status, row.route)
    assert fake.sent == [] and purposes == [], fake.sent
    assert await _leases(aid) == [] and await _out_rows(aid, fan) == []
    assert await _paused(aid, fan) is None         # nothing sent: no cooldown


async def case_same_job_twice():
    aid, fan, mid = "fa_live_twice", 503, 7301
    await _seed_live(aid)
    await _dm_run(aid, fan, mid)
    (row,) = await _rows(aid)
    n_out = len(await _out_rows(aid, fan))
    payload = {"only_fan_ids": [fan], "anchor": mid, "_rule_id": await full_ai_live.live_rule(aid)}
    with _world() as (fake, _made, _p):
        busy = await full_ai_live.run(aid, payload, run_id=0)       # still on its 10 s cooldown
        await _clear_pause(aid, fan)
        again = await full_ai_live.run(aid, payload, run_id=0)
    assert busy == {"skipped": "busy", "tries": 1} and again == {"skipped": "no_turn"}, (busy, again)
    assert fake.sent == [] and [r.id for r in await _rows(aid)] == [row.id]
    assert len(await _out_rows(aid, fan)) == n_out and await _leases(aid) == []


async def case_shadow_rule_untouched():
    aid, fan, mid = "fa_live_shadow", 504, 7401
    await _seed(aid, rule=True, gate=False)          # trigger_json has no `mode`: Shadow
    assert await full_ai_live.live_rule(aid) is None
    res, fake, made, purposes = await _dm_run(aid, fan, mid)
    assert res["status"] == "ok", res
    (row,) = await _rows(aid)
    assert (row.mode, row.status, row.trigger_key) == ("shadow", "planned", str(mid)), row
    assert fake.sent == [] and made == [] and purposes == []
    assert await _leases(aid) == [] and await _paused(aid, fan) is None


async def case_welcome_after_dm_keeps_turn():
    aid, fan, mid = "fa_live_welcome", 505, 7501
    await _seed_live(aid)
    at = datetime.utcnow() - timedelta(minutes=2)
    await _msg(aid, fan, mid - 1, "out", "hi there", at - timedelta(minutes=5), automation_kind="autoreply")
    await _msg(aid, fan, mid, "in", "hey gorgeous", at)
    await _msg(aid, fan, mid + 1, "out", "welcome babe!", at + timedelta(minutes=1), automation_kind="welcome")
    with _world() as (fake, _made, _p):
        await wd.on_inbound_message(aid, fan, mid)
        res = await run_once(aid, KIND)
    assert res["status"] == "ok", res
    (row,) = await _rows(aid)
    assert (row.trigger_key, row.status, row.anchor_message_id) == (str(mid), "sent", mid), row
    assert fake.sent and len(fake.sent) == len(json.loads(row.reply_json)["parts"])
    # A non-welcome outbound after his DM closes the Turn: nothing to answer.
    aid2, fan2 = "fa_live_answered", 506
    await _seed_live(aid2)
    await _msg(aid2, fan2, 7601, "in", "hey", at)
    await _msg(aid2, fan2, 7602, "out", "hey you", at + timedelta(minutes=1), automation_kind="autoreply")
    assert await full_ai_live.load(aid2, fan2, None) is None


async def case_longer_pause_not_shortened():
    aid, fan, mid = "fa_live_pause", 507, 7701
    await _seed_live(aid)
    real = full_ai_live.write_outbound_attribution

    async def and_pause(**kw):        # e.g. a Human yield lands while the Turn sends
        await real(**kw)
        await fan_lease.start_fan_cooldown(aid, fan, cooldown_s=3600)
    full_ai_live.write_outbound_attribution = and_pause
    try:
        await _dm_run(aid, fan, mid)
    finally:
        full_ai_live.write_outbound_attribution = real
    (row,) = await _rows(aid)
    assert row.status == "sent", row.status
    until = await _paused(aid, fan)
    assert until is not None and until > datetime.utcnow() + timedelta(minutes=50), until


_BANNED_MODULES = {"of_client", "automation_executor", "fan_lease", "dm_rate", "of_sends", "of_write"}
_BANNED_NAMES = {"_make_client", "send_message", "acquire_fan_lease", "start_fan_cooldown"}
# 04b's owner reads (ticket 79): the OF-app read and the Human yield's pause, never a send.
_OWNER_IO = {"automation_executor", "fan_lease", "_make_client", "start_fan_cooldown"}
# 05's priced bubble (ticket 86, `send_priced`): a bubble sender the live loop calls (BUBBLE_SENDERS).
_SENDERS = ("full_ai_live.py", "full_ai_ppv.py")


def _send_paths(source: str) -> list[str]:
    """test_full_ai_test_chat.py's walker, same banned sets."""
    found = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import):
            found += [a.name for a in n.names if a.name in _BANNED_MODULES]
        elif isinstance(n, ast.ImportFrom):
            mod = ".".join(p for p in ("automations" if n.level else "", n.module or "") if p)
            names = {f"{mod}.{a.name}" if mod else a.name for a in n.names}
            found += [m for m in {mod} | names if m in _BANNED_MODULES]
            found += [a.name for a in n.names if a.name in _BANNED_NAMES]
        elif isinstance(n, ast.Name) and n.id in _BANNED_NAMES:
            found.append(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _BANNED_NAMES:
            found.append(n.attr)
    return found


def _imports_live(source: str) -> bool:
    """Imports a send module (`full_ai_live` or `full_ai_ppv`)."""
    mods = {f.removesuffix(".py") for f in _SENDERS}
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Import) and any(a.name.rsplit(".", 1)[-1] in mods for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and ((n.module or "").rsplit(".", 1)[-1] in mods
                                              or any(a.name in mods for a in n.names)):
            return True
    return False


def case_only_live_sends():
    for name in ("full_ai_turn.py", "full_ai_test.py"):
        assert not _imports_live((AUTOMATIONS / name).read_text()), name
    files = sorted(AUTOMATIONS.glob("full_ai_*.py")) + [AUTOMATIONS / "_router_jev.py", AUTOMATIONS / "_info_jev.py"]
    hits = {f.name: set(_send_paths(f.read_text())) for f in files}
    assert hits["full_ai_live.py"] >= {"_make_client", "send_message", "dm_rate", "acquire_fan_lease"}, hits
    assert hits.get("full_ai_owner_io.py", set()) <= _OWNER_IO, hits["full_ai_owner_io.py"]
    others = {f: h for f, h in hits.items() if h and f not in (*_SENDERS, "full_ai_owner_io.py")}
    assert others == {}, others
    # The scans bite.
    assert _imports_live("from automations import full_ai_live\n")
    assert _imports_live("import automations.full_ai_live as x\n")
    assert _imports_live("from automations.full_ai_ppv import send_priced\n")
    assert _send_paths("x.send_message(1, 'a')\n") == ["send_message"]


def case_write_gap_env_is_safe():
    """rwl2 F7: FULL_AI_WRITE_GAP_S never raises and never closes the write gate: bad / inf / nan / negative
    -> 2.0, above of_write's 11 s -> 11."""
    import os
    saved = os.environ.get("FULL_AI_WRITE_GAP_S")
    try:
        for raw, want in (("", 2.0), ("abc", 2.0), ("inf", 2.0), ("nan", 2.0), ("-1", 2.0), ("0", 0.0),
                          ("5", 5.0), ("30", 11.0)):
            os.environ["FULL_AI_WRITE_GAP_S"] = raw
            assert full_ai_live._write_gap() == want, (raw, full_ai_live._write_gap())
    finally:
        if saved is None:
            os.environ.pop("FULL_AI_WRITE_GAP_S", None)
        else:
            os.environ["FULL_AI_WRITE_GAP_S"] = saved


_harness.run()
