from __future__ import annotations

from datetime import datetime, timedelta

from db.engine import get_session
from db.models import AccountAiConfig

from . import rhythm


async def load_clock_tz(account_id: str) -> int | None:
    async with get_session() as s:
        cfg = await s.get(AccountAiConfig, account_id)
    if cfg is None:
        return None
    return rhythm.tz_offset_for(getattr(cfg, "timezone", None),
                                getattr(cfg, "utc_offset", None))


# '' when no tz, never the server's clock: a wrong claimed time burned the thread.
def clock_line(tz_offset_minutes: int | None,
               now: datetime | None = None) -> str:
    if tz_offset_minutes is None:
        return ""
    local = (now or datetime.utcnow()) + timedelta(minutes=int(tz_offset_minutes))
    h = local.hour
    tod = ("late night" if h < 5 else "morning" if h < 12 else
           "afternoon" if h < 18 else "evening" if h < 22 else "late night")
    return f"{local.strftime('%A, %B %d — %I:%M %p')} ({tod})"


def clock_block(clock: str) -> str:
    return (
        f"RIGHT NOW for you it is {clock} — never claim a different time of "
        "day.\n\n" if clock else "")
