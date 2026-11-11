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
UI_EXPAND = ("scripts page: a sequence card's expand arrow shows only when its two-line clamp cuts the text (no "
             "dead arrow on a short step), and clicking it lifts the clamp and turns it \"Collapse script\"")
UI_SEND = ("chat: picking a sequence's step 1 from the template picker and sending it offers step 2 next, and the "
           "row's sent_count is 1 (DB via API)")
SHARE_ALL = ("scripts share-to-all: POST /copy all_creators resolves the owner's full Creator roster server-side and "
             "copies the source library to every other owned Creator (each gains >= the source's coverage), carrying "
             "each new sequence's header (position / created by)")
SHARE_ALL_NOOP = ("scripts share-to-all: re-sharing the same library to all creators copies nothing (per-target dedup "
                  "is a true no-op) and the coverage is unchanged")
ALL_MODELS_VIEW = ("scripts all-models view: GET /admin/saved-replies/overview lists every owned Creator and, per "
                   "sequence / tag name, each Creator's count == that Creator's own stored rows (lean, read-only)")
UI_ALL_MODELS = ("scripts page: \"All models\" (Creator column) shows the coverage matrix, a column per roster Creator, "
                 "each sequence / tag row's counts == GET /overview, with the header's write actions (Learn, Share, More: "
                 "Add script / Add sequence / Add tag / Import) gone; every Creator's saved-reply rows unchanged")


def _drop_last_step() -> None:
    """The bulk import silently loses each sequence's last step: `scripts_import_api._parse_sequence`'s steps (looked
    up per call) trimmed by one."""
    import scripts_import_api

    real = scripts_import_api._parse_sequence

    def trimmed(q):
        why, steps = real(q)
        return why, steps[:-1]
    scripts_import_api._parse_sequence = trimmed


def _share_drops_a_creator() -> None:
    """Share-to-all and the all-models view both resolve the roster through `accounts_admin_api.owned_account_ids`;
    this drops its last Creator, so share-to-all skips one Creator and the overview omits it (the class of a roster
    resolver that loses a tenant)."""
    import accounts_admin_api

    real = accounts_admin_api.owned_account_ids
    accounts_admin_api.owned_account_ids = lambda: real()[:-1]


def register(Fault) -> dict:
    return {
        # slop/run scripts-library --break --baseline=<green folder>
        "scripts-bulk-drops-last-step": Fault(_drop_last_step, (IMPORT_COUNTS, READ_BACK, UI_STEPS, UI_TAGS)),
        # slop/run scripts-library --break --fault=scripts-share-drops-a-creator --baseline=<green folder>
        "scripts-share-drops-a-creator": Fault(_share_drops_a_creator, (SHARE_ALL, ALL_MODELS_VIEW, UI_ALL_MODELS)),
        # slop/run scripts-library --break --fault=scripts-expand-arrow-always --baseline=<green folder>
        # ScriptRow's arrow loses its overflow guard (ScriptsParts.tsx `{overflows && <button`): one on every card.
        "scripts-expand-arrow-always": Fault(None, (UI_EXPAND,), browser=((r"\boverflows &&", "true &&"),)),
    }
