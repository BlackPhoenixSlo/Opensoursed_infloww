from __future__ import annotations

from dataclasses import replace

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
    from automations import funnel_decide as fd

    real = fd.decide

    def decide(e, ev, s):
        if isinstance(ev, fd.Checked) and ev.facts.bought:
            ev = replace(ev, facts=replace(ev.facts, bought=False))
        return real(e, ev, s)

    fd.decide = decide


def register(Fault) -> dict:
    return {
        "house-funnel-offer-taken-ignored": Fault(_house_funnel_offer_taken_ignored, (OFFER,)),
    }
