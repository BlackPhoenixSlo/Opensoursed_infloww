#!/usr/bin/env python3
"""Vault picker per-media stats — GET /admin/vault/media-stats.

  case_counts_fans_not_rows:
      sent / priced / unlocks count distinct fans (a re-send or a backfill
      duplicate is one fan), unlock_rate = unlocks / priced, last_sent_at = the
      newest row.
  case_free_only_media_has_no_rate:
      no priced send → unlock_rate None, not 0.
  case_scoped_to_the_account:
      another account's sends never leak in.
  case_mass_and_stamp_rows_do_not_inflate:
      purchase stamps on a mass message or a wall post are not 1:1 sends.

Run: ./venv/bin/python service/tests/test_vault_media_stats.py
"""
from __future__ import annotations

import _harness  # MUST be first — binds a throwaway temp DB

_harness.bootstrap()

import os  # noqa: E402

# House pattern for driving /admin route coroutines directly (test_ai_chatter).
os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, Message, VaultSend  # noqa: E402
from vault import vault_media_stats  # noqa: E402

T0 = datetime(2026, 10, 1, 12, 0, 0)


async def _sends(aid: str, rows: list[tuple[int, int, int, bool | None, int]]) -> None:
    """1:1 chat sends: (fan_id, media_id, price_cents, was_purchased, minutes
    after T0), each on its own (non-mass) message id."""
    async with get_session() as s:
        for fan, media, price, bought, mins in rows:
            s.add(VaultSend(account_id=aid, fan_id=fan, media_id=media, price_cents=price,
                            message_id=fan * 1000 + mins,
                            was_purchased=bought, sent_at=T0 + timedelta(minutes=mins)))


async def case_counts_fans_not_rows():
    aid = "acc_vstats"
    await _sends(aid, [
        (1, 100, 1500, True, 0),
        (1, 100, 1500, True, 5),     # same fan again — still one fan
        (2, 100, 1500, None, 10),
        (3, 100, 0, None, 20),       # a free send: sent, not priced
        (4, 100, 2000, False, 30),
    ])
    st = (await vault_media_stats(account_id=aid))["by_media"]["100"]
    assert st["sent"] == 4 and st["priced"] == 3 and st["unlocks"] == 1, st
    assert st["unlock_rate"] == round(1 / 3, 4), st
    assert st["last_sent_at"] == (T0 + timedelta(minutes=30)).isoformat(), st


async def case_free_only_media_has_no_rate():
    aid = "acc_vstats_free"
    await _sends(aid, [(1, 200, 0, None, 0), (2, 200, 0, None, 1)])
    st = (await vault_media_stats(account_id=aid))["by_media"]["200"]
    assert st == {"sent": 2, "priced": 0, "unlocks": 0, "unlock_rate": None,
                  "last_sent_at": (T0 + timedelta(minutes=1)).isoformat()}, st


async def case_scoped_to_the_account():
    await _sends("acc_vstats_other", [(9, 300, 500, True, 0)])
    got = (await vault_media_stats(account_id="acc_vstats_free"))["by_media"]
    assert set(got) == {"200"}, got


async def case_mass_and_stamp_rows_do_not_inflate():
    """A mass PPV writes no vault_sends row until a fan buys it; the ownership
    stamp then adds a was_purchased row on the mass message (or with no message
    for a wall-post buy). Those are not 1:1 sends, so they stay out: otherwise
    every mass-sold media reads ~100% unlocked."""
    aid, mrid = "acc_vstats_mass", 4242
    async with get_session() as s:
        s.add(Account(id=aid))
    async with get_session() as s:
        s.add(MassRun(id=mrid, account_id=aid, status="ok"))
        for fan, mid, mass in ((1, 9001, mrid), (2, 9002, mrid), (3, 9003, None)):
            s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out",
                          price_cents=1500, created_at=T0, mass_run_id=mass))
        # 1:1 send to fan 3, unbought: the only real send.
        s.add(VaultSend(account_id=aid, fan_id=3, media_id=500, message_id=9003,
                        price_cents=1500, was_purchased=None, sent_at=T0))
        # Mass buyers 1 and 2: stamp rows on the mass message.
        for fan, mid in ((1, 9001), (2, 9002)):
            s.add(VaultSend(account_id=aid, fan_id=fan, media_id=500, message_id=mid,
                            price_cents=1500, was_purchased=True,
                            sent_at=T0 + timedelta(hours=fan)))
        # Wall-post buyer 4: a stamp with no message.
        s.add(VaultSend(account_id=aid, fan_id=4, media_id=500, message_id=None,
                        price_cents=1500, was_purchased=True, sent_at=T0 + timedelta(hours=5)))
        # A mass-only media: nothing 1:1, so no entry at all.
        s.add(VaultSend(account_id=aid, fan_id=1, media_id=600, message_id=9001,
                        price_cents=1500, was_purchased=True, sent_at=T0))
    got = (await vault_media_stats(account_id=aid))["by_media"]
    assert set(got) == {"500"}, got
    assert got["500"] == {"sent": 1, "priced": 1, "unlocks": 0, "unlock_rate": 0.0,
                          "last_sent_at": T0.isoformat()}, got


_harness.run()
