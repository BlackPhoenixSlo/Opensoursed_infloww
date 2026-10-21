"""
service/automations/rhythm.py — the creator's clock and the inline-hold ceiling.

What is left of Human Rhythm after the AI Chatter reply engine was removed: the
one clock resolver every engine reads (`tz_offset_for` / `tz_hours_for`), the
house sleep window (`DEFAULT_SLEEP` / `in_sleep_window`), and `INLINE_MAX_S`, the
ceiling on any inline hold. Pure stdlib, imports nothing of ours, so any module
may import it without a cycle.
"""
from __future__ import annotations

import logging
from datetime import datetime, time

log = logging.getLogger("of-relay.automation.rhythm")

# The ceiling on any INLINE hold. Longer than this and the hold outlives the 900s
# fan lease and burns one of the executor's 4 GLOBAL run slots.
INLINE_MAX_S = 120

# The HOUSE NIGHT, on the creator's own clock. Operator ruling 2026-08-04: a
# four-hour pause, 02:00-06:00. NOT "always awake" — a girl who never sleeps is a
# bot, and the default has to be safe in the absence of evidence.
#
# It was ("03:00", "10:00") — seven hours, chosen as a conservative stand-in when
# the only alternative was deriving one. Two things make four the better default
# now: an OF creator who is dark from 3am to 10am misses the whole US morning, and
# a shorter night is the one that fails cheaply — an account that should sleep
# longer loses a little realism, an account that sleeps too long loses replies.
DEFAULT_SLEEP = ("02:00", "06:00")


# ── Time ─────────────────────────────────────────────────────────────────────
def tz_offset_for(timezone: str | None, utc_offset: int | None,
                  utc_now: datetime | None = None) -> int | None:
    """Resolve an account's creator-local offset IN MINUTES. THE one clock — every
    engine that tells a fan the time resolves it here.

    `utc_offset` (whole HOURS, 0 == unset) WINS. It is what the Brain's one
    place-and-time dropdown writes, so it is the answer somebody chose and can see
    on screen. The IANA `timezone` is only the fallback for an account that has a
    zone and no offset. Returns None when neither is set — and None means the
    clock stays OFF for that account (no clock line, no sleep window). We do NOT
    default to UTC: a UTC default silently puts a US creator to sleep through her
    peak earning window, and nothing in the product would explain the revenue drop.

    ⚠️ The precedence was the OTHER WAY around until 2026-08-08, and that is what
    this reversal is for. Two clocks were stored per account and the silent one won:
    Nora sat on `America/Los_Angeles` next to a stored -4, so her welcome told
    new subscribers "it's Friday night in US" at 07:38 Eastern and named yesterday's
    weekday after Eastern midnight. Nothing on any screen said which of the two was
    live. A fixed offset does NOT track DST — that is the accepted cost of having
    exactly one clock, and it is somebody's job twice a year (US: Nov 1; EU: Oct 25)."""
    if utc_offset:
        return int(utc_offset) * 60
    if timezone:
        try:
            from datetime import timezone as _tz
            from zoneinfo import ZoneInfo
            # The stored datetimes are naive UTC; stamp UTC before converting, or
            # astimezone() would read them as the SERVER's local time (the VPS is
            # UTC, a laptop is not — that divergence would only show up in tests).
            ref = (utc_now or datetime.utcnow()).replace(tzinfo=_tz.utc)
            off = ref.astimezone(ZoneInfo(timezone)).utcoffset()
            if off is not None:
                return int(off.total_seconds() // 60)
        except Exception:
            log.warning("bad timezone %r — and no utc_offset to fall back to", timezone)
    return None


def tz_hours_for(timezone: str | None, utc_offset: int | None,
                 utc_now: datetime | None = None) -> float:
    """`tz_offset_for` in HOURS, with no-clock resolving to 0.0 (UTC).

    Four callers used to spell this out themselves — `off_min / 60.0 if off_min is
    not None else (cfg.utc_offset or 0)` — and that expression is precisely where
    "which of the two clocks is this?" got decided four separate times. The senders
    want hours because `_model_hour` / `_model_weekday` take hours; they should not
    each re-derive the units AND the no-clock default.

    0.0 for a clockless account is what the welcome has always used (it reads as
    UTC). Engines that must NOT invent a clock — the chat prompt line, the sleep
    window — need to tell "no clock" from "UTC", so they call `tz_offset_for` and
    keep the None."""
    off_min = tz_offset_for(timezone, utc_offset, utc_now)
    return off_min / 60.0 if off_min is not None else 0.0


def _parse_hhmm(s: str) -> time:
    h, _, m = str(s).partition(":")
    return time(int(h) % 24, int(m or 0) % 60)


def in_sleep_window(local_dt: datetime, window: tuple[str, str]) -> bool:
    """Is she asleep at this creator-local moment? Handles the wrap past midnight
    (03:00-10:00 does not wrap; 22:00-06:00 does)."""
    start, end = _parse_hhmm(window[0]), _parse_hhmm(window[1])
    t = local_dt.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end          # wraps midnight
