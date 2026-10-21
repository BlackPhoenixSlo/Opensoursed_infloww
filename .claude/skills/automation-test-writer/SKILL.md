---
name: automation-test-writer
description: Scaffold a house-style service/tests/test_*.py for an automation in this repo, or add a no-id/dry-run/cap/force_ids case to an existing one. Use when the user wants test coverage for a new or changed sender/automation.
---

# automation-test-writer

Writes a runnable test that matches the repo's conventions exactly. These tests
are **standalone scripts**, not pytest: `./venv/bin/python service/tests/test_X.py`,
exit 0 = pass. Study an existing sibling (`tests/test_of_ai_chat.py`,
`tests/test_deep_convo.py`, `tests/test_unreachable_skip.py`) before writing — copy
its seams, don't invent new ones.

## The five non-negotiables (each one is a footgun if skipped)
1. **`import _harness` is the FIRST import, then `_harness.bootstrap()`.** It binds
   a unique temp SQLite DB to `DATABASE_URL`+`CHATTERLY_DB_URL` *at import time*.
   Skip it and the engine silently falls back to PROD `chatterly.db` — the #1
   project footgun. Every `db.*`/`server`/`automations.*` import must come AFTER it
   (mark them `# noqa: E402`).
2. **Inject a `FakeOF`, never hit the network.** Senders build their OF client via
   `<module>._make_client(account_id)`. Override it:
   `import automations.<name> as ax; ax._make_client = lambda account_id: fake`.
   FakeOF records `.sent` and echoes `{"id": <next>, "text": "<p>…</p>", "createdAt": …}`.
3. **Patch `llm_client.chat`** to an async stub returning
   `SimpleNamespace(content="…", call_id=1)` — no real DeepSeek call. For the cap
   path, raise `LLMCapExceeded(acc, 100, 200)`.
4. **Seed via the DB**, not via OF: `_seed_account(aid)`, `_seed_fan(aid, fan_id,
   …)`, `_add_msgs(aid, fan_id, [(direction, body), …])` (chronological;
   `direction` is `"in"`/`"out"`). A fan "spoke last" → eligible; seed an inbound
   as the final message to make a sender pick the fan.
5. **`_harness.run(case_a, case_b, …)`** at the bottom — runs all, exits 1 on any
   failure. Cases are plain `def`s with `assert cond, "msg"`; async work goes in an
   inner `async def go(): …; asyncio.run(go())`.

## Scaffold
```python
#!/usr/bin/env python3
"""<one line: what this automation must/ must-not do>."""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB (PROD-fallback footgun)
_harness.bootstrap()

import asyncio  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Fan, Message  # noqa: E402
import llm_client  # noqa: E402
import automations.<NAME> as ax  # noqa: E402

_T0 = datetime(2026, 6, 1, 12, 0, 0)


class FakeOF:
    def __init__(self):
        self.sent = []
        self._next_id = 9_000_000_000_000
    def send_message(self, chat_id, text, **kw):
        self._next_id += 1; self.sent.append((int(chat_id), text))
        return {"id": self._next_id, "text": f"<p>{text}</p>", "createdAt": "2026-06-01T12:30:00+00:00"}
    def get_user(self, user_id):
        return {"id": int(user_id), "subscribedOn": True}   # override per case for lapsed/deleted

def _use_fake():
    fake = FakeOF(); ax._make_client = lambda account_id: fake; return fake

def _patch_llm(reply="heyy 😏"):
    async def _c(**kw): return SimpleNamespace(content=reply, call_id=1)
    llm_client.chat = _c

async def _seed_account(aid):
    async with get_session() as s:
        if await s.get(Account, aid) is None: s.add(Account(id=aid))

async def _seed_fan(aid, fan_id, **kw):
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id, **kw))

async def _add_msgs(aid, fan_id, msgs):
    async with get_session() as s:
        for i, (d, body) in enumerate(msgs):
            s.add(Message(account_id=aid, fan_id=fan_id, message_id=fan_id*1000+i,
                          direction=d, body=body, created_at=_T0 + timedelta(minutes=i)))


def case_happy_path_sends():
    async def go():
        fake = _use_fake(); _patch_llm()
        await _seed_account("acc1"); await _seed_fan("acc1", 111)
        await _add_msgs("acc1", 111, [("in", "hey")])
        await ax.run("acc1", force_ids=[111])        # force_ids bypasses eligibility GATES…
        assert fake.sent, "expected a send"
    asyncio.run(go())


_harness.run(case_happy_path_sends)
```

## Cases worth covering (pick what fits the automation)
- **happy path** — eligible fan → exactly one send, durable state advanced.
- **dry_run** — generates but `fake.sent == []` and no counter bumped.
- **no-id send** — `fake.send_message = lambda *a, **k: {"success": True}` (200, no
  id): fan must be paused/quarantined so it isn't re-messaged next tick; with
  `get_user` returning `subscribedOn: False` it should mark `expired` + week pause.
- **cap** — `llm_client.chat` raises `LLMCapExceeded`; run records the cap, no crash.
- **idempotent re-run** — running twice doesn't double-send.
- **skip/guard** — skip-listed or paused fan is left alone (`fake.sent == []`).

## Gotchas
- `force_ids` **bypasses eligibility gates** but does NOT whitelist senders — it
  doesn't scope WHO gets messaged beyond the gate logic; to scope a real run to one
  fan, seed only that fan (see `force_ids_does_not_scope_senders` memory).
- Confirm the sender's actual client factory name — most are `_make_client`, but
  verify with `grep -n "_make_client\|def run(" service/automations/<NAME>.py`.
- Confirm a gate you assert on is actually backed by a mutated column (e.g. a
  `turn_counter` cap is dead unless the run increments it).
- After writing, RUN it: `cd service && ../venv/bin/python tests/test_<NAME>.py`.
  Then re-run the touched sibling suites so a shared-helper change didn't regress them.
