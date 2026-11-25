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
        "customs-pane-seq-unguarded": Fault(None, (PANE_B, CLIP_B, API_B), browser=(
            (r"s\.pane !== null && s\.pane\.seq === seq \?", "s.pane !== null ?"),
        )),
        "customs-pull-reopens-stale": Fault(None, (PULL_STALE,), browser=(
            (r"ledger\.seq !== ticket\.seq", "false"),
        )),
        "customs-clear-keeps-pull-reopen": Fault(None, (CLEAR_PULL,), browser=(
            (r"clearsNow !== ticket\.clears", "false"),
        )),
    }
