#!/usr/bin/env python3
"""Messages Pro W4 4.2 / 4.11 — the two reads the chat UI needs from our DB.

  case_saved_replies_flag_removed_media   — the saved-replies list marks each
                                            script's media our vault mirror has
                                            soft-deleted (`removed_at`) on THIS
                                            account, and stops once the mirror
                                            restores it, so the composer's
                                            "Use script?" guard can warn before
                                            sending dead media
  case_attribution_carries_our_unsends    — the attribution map exposes
                                            `unsent_at` / `unsent_reason` for a
                                            message WE unsent (mark_unsent), so
                                            the thread draws "Message withdrawn"

Run:  ./venv/bin/python service/tests/test_script_guard_and_withdrawn.py
"""
import _harness  # noqa: F401 — MUST be first (binds temp DB before engine import)

_harness.bootstrap()

# Feature logic, not the account gate (test_account_isolation_gate's job).
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import messages as messages_api  # noqa: E402
import server  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, Message, SavedReply, VaultItem  # noqa: E402

AID = "acct-script-guard"
OTHER = "acct-script-guard-other"
FAN = 6160


async def _seed_account() -> None:
    async with get_session() as s:
        if await s.get(Account, AID) is None:
            s.add(Account(id=AID))


async def case_saved_replies_flag_removed_media():
    await _seed_account()
    now = datetime.utcnow()
    async with get_session() as s:
        s.add(VaultItem(account_id=AID, media_id=101, kind="photo", created_at=now))
        s.add(VaultItem(account_id=AID, media_id=102, kind="video", created_at=now,
                        removed_at=now - timedelta(days=2)))
        s.add(SavedReply(account_id=AID, title="two pics", text="look",
                         media_json=json.dumps([{"id": 101, "type": "photo"},
                                                {"id": 102, "type": "video"},
                                                {"id": 103, "type": "photo"}])))
        s.add(SavedReply(account_id=AID, title="text only", text="hey"))

        # Another account's deleted 101 is not ours: OF media ids are per creator here.
        if await s.get(Account, OTHER) is None:
            s.add(Account(id=OTHER))
        s.add(VaultItem(account_id=OTHER, media_id=101, kind="photo", created_at=now,
                        removed_at=now))

    async def flagged() -> dict[str, list[int]]:
        resp = await server.admin_saved_replies_list(account_id=AID)
        return {r["title"]: r["removed_media_ids"] for r in resp["list"]}

    # 103 was never mirrored: unknown is not deleted.
    assert await flagged() == {"two pics": [102], "text only": []}

    # The mirror found 102 again (vault_mirror resets removed_at): no longer flagged.
    async with get_session() as s:
        (await s.get(VaultItem, (AID, 102))).removed_at = None
    assert await flagged() == {"two pics": [], "text only": []}


async def case_attribution_carries_our_unsends():
    await _seed_account()
    async with get_session() as s:
        for mid in (7001, 7002):
            s.add(Message(account_id=AID, fan_id=FAN, message_id=mid, direction="out",
                          body="hi", created_at=datetime.utcnow()))

    assert await messages_api.mark_unsent(AID, 7001, fan_id=FAN) == 1
    resp = await messages_api.list_message_attribution(AID, FAN, since_id=None, limit=200)
    gone, kept = resp["by_msg_id"]["7001"], resp["by_msg_id"]["7002"]
    assert gone["unsent_at"] is not None and gone["unsent_reason"] == "manual:chat", gone
    assert gone["created_at"] is not None, gone
    assert kept["unsent_at"] is None and kept["unsent_reason"] is None, kept


# Collected automatically — see _harness.run's docstring.
_harness.run()
