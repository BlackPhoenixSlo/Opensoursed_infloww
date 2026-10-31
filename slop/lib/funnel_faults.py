"""The house funnel's break-it-once fault (docs/reducer-scan.md, Non-React #9):
lib/faults.py merges `register(Fault)` into FAULTS. It patches reply_mass_funnel's pure
`funnel_decide.decide()` inside the throwaway relay, so the bug lives in the rules and
every shell around them (reads, sends, saves) is the product's.

  house-funnel-offer-taken-ignored   scenarios/2026-10-30-house-funnel-walk

The house funnel's check names live here and its scenario imports them, so a target
can never name a check that does not exist.
"""
from __future__ import annotations

from dataclasses import replace

# ── house funnel (scenarios/2026-10-30-house-funnel-walk.py) ──────────
DISCOVER = ("house funnel: every recipient who answered the broadcast is enrolled and gets step 1 "
            "(both lines) once; a silent recipient gets nothing and no walk")
ADVANCE = ("house funnel: a fan who answered his step gets exactly the next one; one who did not is "
           "rescheduled (check_count 1, next check +4 min), nothing sent")
PPV = ("house funnel: an answer on the PPV step sends one priced PPV and ends the walk "
       "(done, handed to the chatters)")
OFFER = ("house funnel: a fan who unlocked a PPV since the funnel began is halted offer_taken and sent "
         "nothing, though he answered")
END = "house funnel: a walk left past the script's end (the funnel was shortened) is closed done, nothing sent"
COUNTS = ("house funnel: fake OF's sends = the funnel's new outbound rows = the lines the walks earned; "
          "the runs' advanced add up; no errors, nothing twice")
AGAIN = "house funnel: a second tick right away sends nothing (every walked fan waits for his next answer)"


def _house_funnel_offer_taken_ignored() -> None:
    """reply_mass_funnel's status machine never sees a purchase: a `Checked` event's
    `bought` fact reads False, so the offer-taken halt (and a `next.bought` branch)
    never fires and a buyer who answered is walked on to the next step. The fact is
    still read and nothing errors, so only the check on buyers can see it (the bug
    class: a precedence rule that lost to the reply gate)."""
    from automations import funnel_decide as fd

    real = fd.decide

    def decide(e, ev, s):
        if isinstance(ev, fd.Checked) and ev.facts.bought:
            ev = replace(ev, facts=replace(ev.facts, bought=False))
        return real(e, ev, s)

    fd.decide = decide  # reply_mass_funnel looks it up per call


def register(Fault) -> dict:
    return {
        # slop/run house-funnel-walk --break (the scenario's FAULT)
        "house-funnel-offer-taken-ignored": Fault(_house_funnel_offer_taken_ignored, (OFFER,)),
    }
