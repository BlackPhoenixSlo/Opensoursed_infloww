from __future__ import annotations

import _harness

_harness.bootstrap()

import asyncio  # noqa: E402
import inspect  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Message, is_paid_ratchet  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILS.append(label)


async def _upsert(message_id: int, is_paid, price_cents: int = 300):
    async with get_session() as s:
        await s.execute(
            sqlite_insert(Message)
            .values(account_id="acct", fan_id=1, message_id=message_id,
                    direction="out", price_cents=price_cents, is_paid=is_paid,
                    created_at=datetime.utcnow())
            .on_conflict_do_update(
                index_elements=["account_id", "fan_id", "message_id"],
                set_={"is_paid": is_paid_ratchet(is_paid)},
            )
        )
        await s.commit()
    async with get_session() as s:
        return (await s.execute(
            select(Message.is_paid).where(Message.message_id == message_id)
        )).scalar_one()


def upsert(message_id: int, is_paid, price_cents: int = 300):
    return asyncio.run(_upsert(message_id, is_paid, price_cents))


def main() -> int:
    check(upsert(1, False) is False, "a fresh unpaid PPV stores False")
    check(upsert(1, True) is True, "the purchase flips it to True")
    # Fansly isOpened comes from a purchases feed that ages out; a re-scrape must not erase a real sale.
    check(upsert(1, False) is True, "an aged-out feed must NOT erase the sale")
    check(upsert(1, None) is True, "nor may a NULL write erase it")
    check(upsert(1, False) is True, "still True after repeated unpaid scrapes")

    check(upsert(2, None, price_cents=0) is None, "a free message stores NULL")
    check(upsert(2, None, price_cents=0) is None, "a free message stays NULL")

    check(upsert(3, False) is False, "unpaid stays unpaid until a real purchase")

    import automations.scrape_chats as scrape_chats
    import event_transcoder
    for mod in (scrape_chats, event_transcoder):
        src = inspect.getsource(mod)
        check('"is_paid": is_paid_ratchet(' in src,
              f"{mod.__name__} writes is_paid through the ratchet")
        check('"is_paid": is_paid,' not in src,
              f"{mod.__name__} has no raw unconditional is_paid write left")

    for f in FAILS:
        print(f"  FAIL {f}")
    if FAILS:
        print(f"{len(FAILS)} check(s) failed")
        return 1
    print("all is_paid ratchet checks passed — a recorded sale cannot be erased")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
