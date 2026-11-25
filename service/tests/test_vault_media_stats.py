#!/usr/bin/env python3
from __future__ import annotations

import _harness  # MUST be first: binds temp DB

_harness.bootstrap()

import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

from datetime import datetime, timedelta  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, MassRun, Message, VaultSend  # noqa: E402
from vault import vault_media_stats  # noqa: E402

T0 = datetime(2026, 10, 1, 12, 0, 0)


async def _sends(aid: str, rows: list[tuple[int, int, int, bool | None, int]]) -> None:
    async with get_session() as s:
        for fan, media, price, bought, mins in rows:
            s.add(VaultSend(account_id=aid, fan_id=fan, media_id=media, price_cents=price,
                            message_id=fan * 1000 + mins,
                            was_purchased=bought, sent_at=T0 + timedelta(minutes=mins)))


async def case_counts_fans_not_rows():
    aid = "acc_vstats"
    await _sends(aid, [
        (1, 100, 1500, True, 0),
        (1, 100, 1500, True, 5),
        (2, 100, 1500, None, 10),
        (3, 100, 0, None, 20),
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
    aid, mrid = "acc_vstats_mass", 4242
    async with get_session() as s:
        s.add(Account(id=aid))
    async with get_session() as s:
        s.add(MassRun(id=mrid, account_id=aid, status="ok"))
        for fan, mid, mass in ((1, 9001, mrid), (2, 9002, mrid), (3, 9003, None)):
            s.add(Message(account_id=aid, fan_id=fan, message_id=mid, direction="out",
                          price_cents=1500, created_at=T0, mass_run_id=mass))
        s.add(VaultSend(account_id=aid, fan_id=3, media_id=500, message_id=9003,
                        price_cents=1500, was_purchased=None, sent_at=T0))
        for fan, mid in ((1, 9001), (2, 9002)):
            s.add(VaultSend(account_id=aid, fan_id=fan, media_id=500, message_id=mid,
                            price_cents=1500, was_purchased=True,
                            sent_at=T0 + timedelta(hours=fan)))
        s.add(VaultSend(account_id=aid, fan_id=4, media_id=500, message_id=None,
                        price_cents=1500, was_purchased=True, sent_at=T0 + timedelta(hours=5)))
        s.add(VaultSend(account_id=aid, fan_id=1, media_id=600, message_id=9001,
                        price_cents=1500, was_purchased=True, sent_at=T0))
    got = (await vault_media_stats(account_id=aid))["by_media"]
    assert set(got) == {"500"}, got
    assert got["500"] == {"sent": 1, "priced": 1, "unlocks": 0, "unlock_rate": 0.0,
                          "last_sent_at": T0.isoformat()}, got


_harness.run()
