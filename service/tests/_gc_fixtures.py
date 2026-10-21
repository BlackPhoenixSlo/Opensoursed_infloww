"""service/tests/_gc_fixtures.py — the gather-close suites' shared bench.

FakeOF (records sends, serves a fake vault), the LLM stub, and the row seeders,
extracted VERBATIM from test_gather_close.py on 2026-08-30 when the ask-route
cases pushed that file past 1,000 lines. test_gather_close.py sits on it (the
ask-route suite went when welcome_chatter_for_info stopped sending the
gather-close PPV).

NOT a test file: no `case_*`, no `_harness.run()`. Importers bootstrap
`_harness` FIRST (the temp-DB footgun), then import this.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import automation_executor as ax
import llm_client
from db.engine import get_session
from db.models import (
    Account, Fan, Message, Transaction, VaultItem,
)


_T0 = datetime(2026, 6, 4, 12, 0, 0)


# ── Fakes (no network) ────────────────────────────────────────────────

class FakeOF:
    """Records sends (with kwargs — the price is the point here) and serves a
    fake vault: `folders` maps name → {"id": int, "media": [{"id", "type"}, …]}."""

    def __init__(self, folders: dict | None = None):
        self.sent: list[tuple[int, str, dict]] = []
        self.folders = folders or {}
        self._next_id = 9_000_000_000_000

    def send_message(self, chat_id, text, **kw) -> dict:
        self._next_id += 1
        self.sent.append((int(chat_id), text, kw))
        return {"id": self._next_id, "text": f"<p>{text}</p>",
                "createdAt": "2026-06-04T12:30:00+00:00"}

    def vault_lists(self, view="main", limit=100) -> dict:
        return {"list": [{"id": f["id"], "name": name}
                         for name, f in self.folders.items()]}

    def vault_media(self, list_id, type="all", limit=100) -> dict:
        for f in self.folders.values():
            if int(f["id"]) == int(list_id):
                return {"list": list(f["media"])}
        return {"list": []}

    def set_fan_custom_name(self, user_id, name) -> dict:
        return {"success": True}

    def set_fan_note(self, user_id, note) -> dict:
        return {"success": True}

    def mark_chat_read(self, chat_id) -> dict:
        return {"success": True}

    def get_user(self, user_id) -> dict:
        return {"id": int(user_id), "subscribedOn": True}


def _use_fake(folders: dict | None = None) -> FakeOF:
    fake = FakeOF(folders)
    ax._make_client = lambda account_id: fake  # type: ignore[attr-defined]
    return fake


def _patch_llm(reply: str = "heyy what are you up to tonight? 😏") -> None:
    async def _fake_chat(**kw):
        return SimpleNamespace(content=reply, call_id=1)
    llm_client.chat = _fake_chat  # type: ignore[attr-defined]


# ── Seeding ───────────────────────────────────────────────────────────

async def _seed_account(aid: str) -> None:
    async with get_session() as s:
        if await s.get(Account, aid) is None:
            s.add(Account(id=aid))


async def _seed_fan(aid: str, fan_id: int) -> None:
    async with get_session() as s:
        if await s.get(Fan, (aid, fan_id)) is None:
            s.add(Fan(account_id=aid, fan_id=fan_id))


async def _add_msgs(aid: str, fan_id: int, msgs: list[tuple[str, str]],
                    *, base: int = 0, at: datetime | None = None) -> None:
    """`base` offsets the message ids — `_seed_graduate` already claims
    `fan_id * 1000`, and two rows with one id is a PK clash, not a fixture.
    `at` overrides the start of the run; the thread's OLDEST row is what the
    him-block window measures, so a case about age has to place it."""
    start = at or _T0
    async with get_session() as s:
        for i, (direction, body) in enumerate(msgs):
            s.add(Message(
                account_id=aid, fan_id=fan_id, message_id=fan_id * 1000 + base + i,
                direction=direction, body=body,
                created_at=start + timedelta(minutes=i),
            ))


async def _seed_tx(aid: str, fan_id: int, kind: str, *, cents: int = 2000,
                   status: str = "pending") -> None:
    async with get_session() as s:
        s.add(Transaction(account_id=aid, fan_id=fan_id, kind=kind,
                          amount_cents=cents, currency="USD",
                          occurred_at=_T0 - timedelta(hours=1),
                          status=status, source="ledger"))


async def _seed_photos(aid: str, ids: list[int], *, kind: str = "photo") -> None:
    async with get_session() as s:
        for mid in ids:
            if await s.get(VaultItem, (aid, mid)) is None:
                s.add(VaultItem(account_id=aid, media_id=mid, kind=kind,
                                tags="[]", send_count=0,
                                created_at=datetime.utcnow()))


_FOLDER = {"closers": {"id": 77, "media": [
    {"id": 501, "type": "photo"}, {"id": 502, "type": "photo"},
    {"id": 503, "type": "photo"}, {"id": 504, "type": "video"},
]}}
