"""The Scripts library flow's break-it-once fault (scenarios/2026-11-06-scripts-library.py): lib/faults.py merges
`register(Fault)` into FAULTS. Every check the scenario records is named here and the scenario imports it."""
from __future__ import annotations

IMPORT_COUNTS = ("scripts library: the CLI's bulk import creates every dump sequence and step, one row per script "
                 "(counts == dump, nothing failed, its own field-by-field read-back exits 0)")
REIMPORT_NOOP = "scripts library: a second import of the same dump creates nothing (every sequence already there)"
READ_BACK = ("scripts library: GET /admin/saved-replies holds every dump script once (a tagged step is one row with "
             "its tags), per sequence in step order (N, then option), name, text, notes, condition and price intact; "
             "/sequences has every sequence's meta (position, Created by, day, description)")
UI_TAGS = ("scripts page: the Tag tab's All scripts / tag / Uncategorized counts == the dump's (no script doubled "
           "by its tag)")
LIST_LOAD = ("scripts library at volume: --users owners reading the whole list at once each get every row "
             "(no 5xx, nothing dropped)")
LIST_P95 = "scripts library: GET /admin/saved-replies p95 (serial reads) within budget"
UI_SIDEBAR = ("scripts page: the Sequence tab's sidebar accounts for every sequence (rendered + Show more) in dump "
              "order, each count == its stored scripts, and its search finds the last one")
UI_STEPS = ("scripts page: a deep sequence opened from the sidebar shows its steps as numbered cards in dump order "
            "(labels N / N.M), notes shown, header Created by / Created on as the dump")
UI_SEND = ("chat: picking a sequence's step 1 from the template picker and sending it offers step 2 next, and the "
           "row's sent_count is 1 (DB via API)")


def _drop_last_step() -> None:
    """The bulk import silently loses each sequence's last step: `scripts_import_api._ordered_steps` (looked up per
    call) trimmed by one."""
    import scripts_import_api

    real = scripts_import_api._ordered_steps
    scripts_import_api._ordered_steps = lambda steps: real(steps)[:-1]


def register(Fault) -> dict:
    return {
        # slop/run scripts-library --break --baseline=<green folder>
        "scripts-bulk-drops-last-step": Fault(_drop_last_step, (IMPORT_COUNTS, READ_BACK, UI_STEPS, UI_TAGS)),
    }
