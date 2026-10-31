#!/usr/bin/env python3
"""
welcome_compose — what a welcome SAYS, driven through the real `run_once`
dispatcher (registry, automation_runs) against a fake OFClient + a patched
llm_client.chat. No network. The burst text is `_compose_bubbles`' (greeting,
the slot's activity line, the operator's question), so every case checks the
wire text against the composer's own output.

  case_no_id_send_still_welcomes:  OF answers a send with no message id: the
      composed bubbles still go out, the fan is claimed once, and no outbound
      `messages` row is written (nothing to key it on).
  case_dry_run_composes_but_sends_nothing:  dry_run composes and counts a
      would-send, but no OF send, no claim, no row.
  case_llm_cap_never_blocks_compose:  an LLM daily-cap trip cannot stop a
      welcome (compose is deterministic).
  case_max_welcomes_caps_the_batch:  `max_welcomes` caps the batch, the rest
      wait for the next tick; a bare id greets as "cutie".

Every patch (ax._make_client, llm_client.chat) is scoped to its case and restored.

Run: ./venv/bin/python service/tests/test_welcome_compose.py   (exit 0 = pass)
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)

_harness.bootstrap()

import contextlib  # noqa: E402
import json  # noqa: E402

from sqlalchemy import select  # noqa: E402

import automation_executor as ax  # noqa: E402
import llm_client  # noqa: E402
from automation_executor import run_once  # noqa: E402
from automations import welcome_compose as wc  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, AccountAiConfig, Message, WelcomeSent  # noqa: E402
from llm_client import LLMCapExceeded  # noqa: E402


class FakeOF:
    """Serves a canned subscribe feed; records sends. `with_id=False` answers a
    send the way OF sometimes does: 200 with no message id."""

    def __init__(self, subs: list[dict], *, with_id: bool = True):
        self._subs = subs
        self.with_id = with_id
        self.sent: list[tuple[int, str, list]] = []
        self._next_id = 9_100_000_000_000
        self.followed: list[int] = []

    def notifications(self, *, limit: int = 10, offset: int = 0, type=None, **kw) -> dict:
        return {"list": [{"user": s} for s in self._subs], "hasMore": False}

    def send_message(self, chat_id, text, *, media_files=None, **kw) -> dict:
        self.sent.append((int(chat_id), text, list(media_files or [])))
        if not self.with_id:
            return {"text": text}
        self._next_id += 1
        return {"id": self._next_id, "text": text,
                "createdAt": "2026-10-30T12:00:00+00:00"}

    def get_user(self, user_id) -> dict:
        return {"subscribePrice": 0}

    def follow_user(self, user_id):
        self.followed.append(int(user_id))
        return {"ok": True}

    def vault_lists(self, **kw) -> dict:
        return {"list": []}


@contextlib.contextmanager
def _patched(mod, name: str, value):
    real = getattr(mod, name)
    setattr(mod, name, value)
    try:
        yield
    finally:
        setattr(mod, name, real)


@contextlib.contextmanager
def _world(subs: list[dict], *, llm=None, **kw):
    """The fake OF client, and `llm_client.chat` (default: must not run)."""
    fake = FakeOF(subs, **kw)

    async def _boom(**kw):
        raise AssertionError("no LLM on the welcome compose path")
    with _patched(ax, "_make_client", lambda account_id: fake), \
            _patched(llm_client, "chat", llm or _boom):
        yield fake


async def _seed(aid: str) -> dict:
    """An account with a brain (bubble 2) — returns the cfg compose reads."""
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))
        s.add(AccountAiConfig(
            account_id=aid, utc_offset=0, location="Lisbon",
            time_activities_json=json.dumps(
                {k: f"doing {k} stuff" for k in wc._SLOT_KEYS})))
    return await wc._load_ai_config(aid)


async def _expected_burst(cfg: dict, name: str, *, question: str = "") -> list[str]:
    bubbles, _, _ = await wc._compose_bubbles(
        greeting=wc._local_greeting(name), cfg=cfg,
        hour=wc._model_hour(wc._clock_hours(cfg)), skip_time_bubble=False,
        time_only=False, question=question, strip_emoji_on=False)
    return bubbles


async def _rows(aid: str):
    async with get_session() as s:
        ws = (await s.execute(select(WelcomeSent.fan_id)
                              .where(WelcomeSent.account_id == aid))).scalars().all()
        msgs = (await s.execute(select(Message)
                                .where(Message.account_id == aid))).scalars().all()
    return sorted(ws), msgs


async def case_no_id_send_still_welcomes():
    aid = "acc_wc_noid"
    cfg = await _seed(aid)
    with _world([{"id": 51, "name": "Nina", "username": "nina_x"}], with_id=False) as fake:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False, "question": "what's yours?",
                                      "follow_back": False})
    assert res["status"] == "ok", res
    assert res["welcomes_sent"] == 1 and res["errors"] == 0, res
    want = await _expected_burst(cfg, "Nina", question="what's yours?")
    assert len(want) == 3, want
    assert [t for _, t, _ in fake.sent] == want, fake.sent
    ws, msgs = await _rows(aid)
    assert ws == [51], ws
    assert msgs == [], "no id -> no outbound row to key"


async def case_dry_run_composes_but_sends_nothing():
    aid = "acc_wc_dry"
    await _seed(aid)
    with _world([{"id": 61, "name": "Omar"}, {"id": 62, "username": "pete_99"}]) as fake:
        res = await run_once(aid, "send_welcome", payload={"dry_run": True})
        assert res["status"] == "ok", res
        assert res["dry_run"] is True, res
        assert res["new_subscribers"] == 2 and res["welcomes_sent"] == 2, res
        assert fake.sent == [] and fake.followed == [], (fake.sent, fake.followed)
        ws, msgs = await _rows(aid)
        assert ws == [] and msgs == [], (ws, msgs)
        # Not claimed, so the next real tick still welcomes both.
        res2 = await run_once(aid, "send_welcome",
                              payload={"with_image": False, "follow_back": False})
    assert res2["welcomes_sent"] == 2, res2


async def case_llm_cap_never_blocks_compose():
    aid = "acc_wc_cap"
    cfg = await _seed(aid)

    async def _capped(**kw):
        raise LLMCapExceeded(aid, 100, 200)
    with _world([{"id": 71, "name": "Quinn"}], llm=_capped) as fake:
        res = await run_once(aid, "send_welcome",
                             payload={"with_image": False, "follow_back": False})
    assert res["status"] == "ok", res
    assert res["welcomes_sent"] == 1 and res["errors"] == 0, res
    want = await _expected_burst(cfg, "Quinn")
    assert [t for _, t, _ in fake.sent] == want, fake.sent
    ws, msgs = await _rows(aid)
    assert ws == [71] and len(msgs) == len(want), (ws, len(msgs))


async def case_max_welcomes_caps_the_batch():
    aid = "acc_wc_max"
    cfg = await _seed(aid)
    pay = {"with_image": False, "follow_back": False, "max_welcomes": 2}
    with _world([{"id": 71, "name": "Quinn"}, {"id": 72, "username": "rex_xo"},
                 {"id": 73, "username": "8812"}]) as fake:
        res = await run_once(aid, "send_welcome", payload=pay)
        assert res["status"] == "ok", res
        assert res["new_subscribers"] == 3 and res["batch_capped"] is True, res
        assert res["welcomes_sent"] == 2 and res["errors"] == 0, res
        want = (await _expected_burst(cfg, "Quinn")) + (await _expected_burst(cfg, "rex"))
        assert [t for _, t, _ in fake.sent] == want, fake.sent
        ws, msgs = await _rows(aid)
        assert ws == [71, 72], ws
        assert len(msgs) == len(want), len(msgs)
        # The capped-out fan is next tick's; the bare id greets as "cutie", never "#8812".
        fake.sent.clear()
        res2 = await run_once(aid, "send_welcome", payload=pay)
    assert res2["welcomes_sent"] == 1 and res2["new_subscribers"] == 1, res2
    assert fake.sent[0][1] == wc._local_greeting("cutie"), fake.sent
    assert (await _rows(aid))[0] == [71, 72, 73]


_harness.run()
