"""service/automations/send_marker_decide.py — the send-once marker's rules, pure.

Read by both drip senders (reply_mass_funnel, send_followup) and the
unconfirmed-sends API. At-most-once: a row is marked (`sending_at`, + ctx) right
before the first OF call of an attempt; a marked row is never auto-sent; only a
settle (the landed message found) or the user's Retry clears it.

  marker_state(sending_at, unconfirmed_at, boot_ts, now)
      NONE        no marker
      UNCONFIRMED may have sent, no live call: `unconfirmed_at` set, or the mark
                  predates this process (one relay process: a pre-boot marker has
                  no call in flight), or it is older than IN_FLIGHT_MAX_S (the
                  kept fan lease)
      IN_FLIGHT   a call of this process may still be writing it

  failure_outcome(sent, returned, entered, may_have_sent, *, unreachable=False)
      SENT        a bubble landed with an id: save the step as sent
      CLEAR       the raise came before the marker, or OF refused the fan itself
                  (`unreachable`: skip_unreachable_fan), or surely did not send
      UNCONFIRMED a bubble came back id-less, or the raise may have sent

Invariant: `unconfirmed_at` set => `sending_at` set (every writer marks first).

No I/O and no service imports. `BOOT_TS` is the one impure line: imported by the
senders before any mark, so every marker this process writes is >= BOOT_TS.
"""
from __future__ import annotations

from datetime import datetime, timedelta

NONE = "NONE"
UNCONFIRMED = "UNCONFIRMED"
IN_FLIGHT = "IN_FLIGHT"

SENT = "SENT"
CLEAR = "CLEAR"

IN_FLIGHT_MAX_S = 900   # = the kept fan lease (reply_mass_funnel's 900 s fallback)
# OF stamps the message on its own clock: a landed row may read a little before
# our mark. The settle's lookup looks back this far (inferred slack).
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
    """The earliest `messages.created_at` the settle counts as this attempt's."""
    return sending_at - timedelta(seconds=LOOKUP_SLACK_S)
