from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db.models import Fan

log = logging.getLogger("of-relay.automation.customs")

MIN_CENTS = 5_000

ASK_MIN_CENTS = 10_000

assert ASK_MIN_CENTS >= MIN_CENTS, \
    "a quotable price the watch refuses to book is a paid, unmarked custom"

# Only a DM tip: tip_post/tip_stream are generosity, not an order.
ORDER_KINDS = ("tip",)

# Shared by watch and queue so a charged-back tip never counts; pending is money in flight.
SETTLED_STATUSES = ("cleared", "pending")


def resolve_floor(min_cents) -> int:
    return MIN_CENTS if min_cents is None else max(1, int(min_cents))


BURST_MINUTES = 30


# rows must arrive occurred_at DESC.
def _walk_bursts(rows, min_cents: int | None = None) -> dict[tuple, list[tuple]]:
    floor = resolve_floor(min_cents)
    walk: dict[tuple, list[list]] = {}
    for acct, fid, cents, at, msg_id in rows:
        if fid is None or at is None:
            continue
        key = (acct, int(fid))
        cents = int(cents or 0)
        open_burst = walk[key][-1] if key in walk else None
        if open_burst is not None and (open_burst[1] - at) <= timedelta(minutes=BURST_MINUTES):
            open_burst[0] += cents
            continue
        walk.setdefault(key, []).append([cents, at, msg_id])
    out: dict[tuple, list[tuple]] = {}
    for key, bursts in walk.items():
        kept = [(int(t), a, m) for t, a, m in bursts if t >= floor]
        if kept:
            out[key] = kept
    return out


# Floor is tested on the burst total, newest burst only: customs_watch uses its anchor as the delivery cutoff.
def orders_per_fan(rows, min_cents: int | None = None) -> dict[tuple, tuple]:
    floor = resolve_floor(min_cents)
    return {key: bursts[0]
            for key, bursts in _walk_bursts(rows, min_cents=0).items()
            if bursts[0][0] >= floor}


def bursts_per_fan(rows, min_cents: int | None = None) -> dict[tuple, list[tuple]]:
    return _walk_bursts(rows, min_cents)




def is_owed(fan: "Fan | None") -> bool:
    return fan is not None and fan.customs_owed_at is not None


# Seller engines build an exclude set without loading a Fan, so is_owed alone never brakes them.
async def owed_fan_ids(account_id) -> set[int]:
    from sqlalchemy import select

    from db.engine import get_session
    from db.models import Fan

    async with get_session() as s:
        rows = (await s.execute(
            select(Fan.fan_id).where(
                Fan.account_id == str(account_id),
                Fan.customs_owed_at.is_not(None),
            )
        )).all()
    return {int(r[0]) for r in rows}


# mark/clear mutate the row and do not commit: the caller owns the session.
def mark(fan: "Fan | None", tipped_at: datetime | None = None) -> bool:
    if fan is None or is_owed(fan):
        return False
    # Stamp is the tip time: the queue ages by it.
    fan.customs_owed_at = tipped_at or datetime.utcnow()
    return True


def clear(fan: "Fan | None", cleared_at: datetime | None = None) -> bool:
    if fan is None or not is_owed(fan):
        return False
    fan.customs_owed_at = None
    # Without this stamp customs_watch re-marks the same tip next sweep.
    fan.customs_cleared_at = cleared_at or datetime.utcnow()
    return True




# The owed brake has no timeout on purpose (a timeout would resume selling to a fan who was never delivered); delivery clears it, or the operator by hand.
# Audio only: a free video once false-cleared debts incurred days earlier.
DELIVERY_TYPES = ("audio",)
