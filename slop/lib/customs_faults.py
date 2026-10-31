"""The owed-customs pane's break-it-once fault (scenarios/2026-10-30-customs-pane-race.py):
lib/faults.py merges `register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's
served JS (actors/ui.py). The check names live here and the scenario imports them, so a target
can never name a check that does not exist.
"""
from __future__ import annotations

RACE = "customs pane: A was opened before B and A's held replies were all answered after B's (the race happened)"
GATE = ("customs pane: Copy handoff is disabled while B's brief and order are in flight, "
        "and enabled once both settle")
PANE_B = ("customs pane: after A's late replies land, B's open pane shows only B's thread, order and brief "
          "(B's tag present; A's tag and @username absent)")
CLIP_B = ("customs pane: Copy handoff puts B's @username, account and brief on the clipboard, "
          "with nothing of A's")
API_B = ("customs pane: GET /admin/customs/order for B returns B's lines, and B's pane shows exactly "
         "those order lines")
PULL_STALE = ("customs pane: a Pull on A that answers ok after a newer open (Hide + Read B) reopens nothing: "
              "no thread, order or (paid) brief asked for A, and B's pane stays open, B's alone")
CLEAR_PULL = ("customs pane: Sent on a row mid-Pull reopens nothing: no thread, order or (paid) brief "
              "asked for it after Sent, and no pane shows it")
CLEARED = ("customs pane: Sent clears the fan for real: POST /admin/customs/clear 200, "
           "fans.customs_owed_at NULL, gone from GET /admin/customs and from the queue")


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-customs-pane-race --break (the scenario's FAULT)
        # app/components/messages/customsPaneReducer.ts `onPane`: a reply lands on whatever pane
        # is open, whatever open it was asked for (the seq guard removed, as before 7f2604fcd).
        # A's late thread, brief and order then fill B's pane, so the pane, clipboard and API
        # checks go red; the race and the Copy gate (taken before A's replies land) stay green.
        "customs-pane-seq-unguarded": Fault(None, (PANE_B, CLIP_B, API_B), browser=(
            (r"s\.pane !== null && s\.pane\.seq === seq \?", "s.pane !== null ?"),
        )),
        # slop/run 2026-10-30-customs-pane-race --break --fault=customs-pull-reopens-stale
        # app/components/messages/customsPaneReducer.ts `mayReopen`: an ok rescrape reopens its
        # row whatever was opened or closed since (the `paneMoved` condition removed). A's
        # reopen then asks for A's thread, order and a paid brief and replaces B's pane, so only
        # the Pull check goes red; the race, gate, pane, clipboard and API checks are taken
        # before the Pull, and step 7's Pull is still stopped by its fan's clear.
        "customs-pull-reopens-stale": Fault(None, (PULL_STALE,), browser=(
            (r"ledger\.seq !== ticket\.seq", "false"),
        )),
        # slop/run 2026-10-30-customs-pane-race --break --fault=customs-clear-keeps-pull-reopen
        # app/components/messages/customsPaneReducer.ts `mayReopen`: an ok rescrape reopens its
        # row even after Sent on its fan (the `fanCleared` condition removed, as before W10).
        # A's rescrape then reopens the cleared A and asks for its thread, order and a paid
        # brief, so only the Sent-mid-Pull check goes red: the clear itself (CLEARED) still
        # lands, and step 6's Pull (A never Sent) is still stopped by the newer open.
        "customs-clear-keeps-pull-reopen": Fault(None, (CLEAR_PULL,), browser=(
            (r"clearsNow !== ticket\.clears", "false"),
        )),
    }
