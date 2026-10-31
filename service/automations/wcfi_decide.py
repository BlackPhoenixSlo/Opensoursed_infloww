"""
service/automations/wcfi_decide.py — welcome_chatter_for_info's per-fan eligibility
verdict, pure.

`run()` reads everything a gate needs into a `FanSnapshot` (stop-lists, the turn,
the Fan row's flags, the payer set, the gather state) and asks `decide(snap)`
per fan through this MODULE (`wcfi_decide.decide`), so a test or slop fault can
swap it. The effects stay in `run()`: the counters (`STAT`), the turn-handoff rewrite
(`handoff_admitted`) and `_skip_and_collect` for a durable skip. No I/O, no DB import.

Precedence (first match wins) — the order the loop has always checked:

  1. listed       blacklist / skip_list                               (even forced)
  2. mid_funnel   reply_mass_funnel owns him                          (not forced)
  3. not_turn     we spoke last and no welcome handoff admits him     (even forced)
  4. paused       automation_paused_until in the future               (even forced)
  5. muted        a muted creator we follow — HARD                    (even forced)
  -- below: not forced and a Fan row exists --
  6. spam         promo-spam; REVERSIBLE, no skip_list write
  7. spent        bought content                                      → durable
  8. too_long     runaway cutoff, gather not done, no closing PPV due → durable
     ClosePpv     the same cutoff with the closing PPV set and not yet sent
  9. Ask          everyone else: a candidate this tick
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Reason = Literal["listed", "mid_funnel", "not_turn", "paused", "muted", "spam", "spent",
                 "too_long"]
DURABLE: frozenset[Reason] = frozenset({"spent", "too_long"})  # run() writes skip_list
# reason -> the run's stats_json counter it bumps
STAT: dict[Reason, str] = {
    "listed": "skipped_listed", "mid_funnel": "skipped_listed", "paused": "skipped_listed",
    "not_turn": "skipped_not_turn", "muted": "skipped_muted_creator", "spam": "skipped_spam",
    "spent": "newly_skiplisted", "too_long": "newly_skiplisted",
}
# every counter run() reports (stats_json order), all present at 0
COUNTERS = ("skipped_listed", "skipped_not_turn", "turn_handoffs", "skipped_spam",
            "skipped_muted_creator", "newly_skiplisted")


@dataclass(frozen=True)
class FanSnapshot:
    listed: bool                # blacklist (global) or this account's skip_list
    mid_funnel: bool            # pending funnel_state under one of this account's mass runs
    forced: bool                # in the payload's force_ids
    his_turn: bool              # the fan spoke last (`last_dir == "in"`)
    handoff: bool               # send_welcome's turn handoff admits him (TurnHandoff.admit)
    has_fan_row: bool           # a Fan row exists (gates 6-8 need one)
    paused: bool                # automation_paused_until > now
    muted_creator: bool         # should_skip_muted_creator(fan)
    promo_spam: bool            # in load_promo_spam_ids
    content_payer: bool         # in content_payer_fans (a tip or a PPV unlock)
    gather_done: bool           # _gather_done(fan, questions_asked)
    fan_msg_n: int              # his substantive inbound count
    max_fan_messages: int       # the runaway cutoff
    closing_due: bool           # a closing PPV is set AND he has not had it (gather_close_at)


# Every verdict carries `handoff_admitted`: True iff he passed listed / mid_funnel with
# a handoff — run() then rewrites the candidate to his words and counts turn_handoffs.
@dataclass(frozen=True)
class Skip:
    reason: Reason
    handoff_admitted: bool = False

    @property
    def durable(self) -> bool:  # True → run() writes the skip_list row (_skip_and_collect)
        return self.reason in DURABLE


@dataclass(frozen=True)
class ClosePpv:
    """The runaway cut, deferred to the send loop (under the fan lease) so his last
    message from this lane is the closing PPV; `too_long` lands there."""
    handoff_admitted: bool = False


@dataclass(frozen=True)
class Ask:
    """A candidate: the turn loop generates (and maybe graduates) under the lease."""
    handoff_admitted: bool = False


Verdict = Skip | ClosePpv | Ask


def decide(snap: FanSnapshot) -> Verdict:
    if snap.listed:
        return Skip("listed")
    if snap.mid_funnel and not snap.forced:
        return Skip("mid_funnel")
    h = snap.handoff
    if not h and not snap.his_turn:
        return Skip("not_turn")
    if snap.paused:
        return Skip("paused", h)
    if snap.muted_creator:
        return Skip("muted", h)
    if not snap.forced and snap.has_fan_row:
        if snap.promo_spam:
            return Skip("spam", h)
        if snap.content_payer:
            return Skip("spent", h)
        if not snap.gather_done and snap.fan_msg_n >= snap.max_fan_messages:
            if snap.closing_due:
                return ClosePpv(h)
            return Skip("too_long", h)
    return Ask(h)
