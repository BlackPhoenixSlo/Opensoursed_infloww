from __future__ import annotations

from datetime import datetime, timedelta

NONE = "NONE"
UNCONFIRMED = "UNCONFIRMED"
IN_FLIGHT = "IN_FLIGHT"

SENT = "SENT"
CLEAR = "CLEAR"

IN_FLIGHT_MAX_S = 900
LOOKUP_SLACK_S = 60

BOOT_TS = datetime.utcnow()


def marker_state(sending_at: datetime | None, unconfirmed_at: datetime | None,
                 boot_ts: datetime, now: datetime) -> str:
    if sending_at is None and unconfirmed_at is None:
        return NONE
    if unconfirmed_at is not None:
        return UNCONFIRMED
    if sending_at < boot_ts or now - sending_at > timedelta(seconds=IN_FLIGHT_MAX_S):
        return UNCONFIRMED
    return IN_FLIGHT


def failure_outcome(sent: int, returned: int, entered: bool, may_have_sent: bool, *,
                    unreachable: bool = False) -> str:
    if sent > 0:
        return SENT
    if not entered or unreachable:
        return CLEAR
    if returned > 0:
        return UNCONFIRMED
    return UNCONFIRMED if may_have_sent else CLEAR


def lookup_since(sending_at: datetime) -> datetime:
    return sending_at - timedelta(seconds=LOOKUP_SLACK_S)
