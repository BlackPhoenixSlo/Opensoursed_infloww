"""Growth > Scripts' "Fill with content" flow's checks and break-it-once fault (scenarios/2026-11-21-script-fill.py):
lib/faults.py merges `register(Fault)` into FAULTS. Every check the scenario records is named here and the scenario
imports it."""
from __future__ import annotations

FILL_ONE_PRESS = ("script fill: one press of \"Fill with content\" on the open Sequence fills it (POST fill/apply 200 "
                  "status ok, no dialog), its cards show the written media and prices and the Fill notice reads "
                  "\"Added N items to M steps\" with Undo")
FILL_READ_BACK = ("script fill: the DB holds only Fillable media of that Creator (no partner / Jev-held / REVIEW-folder "
                  "decoy, no other Creator's id), every free and paid step got media, prices only on Options saved "
                  "at 0 (the saved $25 kept), updated_at bumped only on the written rows")
FILL_SEND = ("script fill: the chat's template picker sends a free and two paid filled steps; the fake OnlyFans' "
             "recorded send bodies carry each step's written media ids, its free previews and its PPV price, no decoy")
FILL_ISOLATION = ("script fill: after a Fill that wrote, the other Creator's same-named Sequence rows are byte-equal "
                  "before and after")
FILL_UNDO = ("script fill: the notice's Undo empties every written row (media and previews), zeroes only the prices "
             "Fill set (the saved $25 kept), and the cards show no media again")
DESCRIBE_OFFER = ("script fill, short vault: the press offers \"Describe content first?\"; Describe starts describe-all "
                  "with target 1000; the reopened dialog shows the sweep's progress; the sweep settles to \"Ready to "
                  "fill.\" with zero fill writes until the dialog's Fill is pressed, which then fills")
DESCRIBE_BLOCKED = ("script fill, short vault: a valid key and the describe cap row at the cap before the dialog opens "
                    "-> the plan's cap sentence, no Describe button, zero describe-all POSTs, zero fill writes")
DESCRIBE_REFUSED = ("script fill, short vault: the cap row written after the offer renders, before the press -> "
                    "describe-all answers 429, the dialog shows its blocked_reason sentence (no JSON), no describe call")


def _skip_eligibility() -> None:
    """Phase 1's Fillable item check passes everything: `script_fill_decide.fillable` answers None for every item,
    and `fillable_rows` (the one filter `plan_over_vault` and `plan` call, a module global looked up per call)
    keeps every item, each with its script `why` re-derived from its fields as the real gate does (a carried `why`
    is never read). So the partner and Jev-held decoys reach the Shoots (a REVIEW-folder member is still dropped
    earlier, by `full_ai_sell.load_rows`); the partner clip then takes step 7 (scenario docstring)."""
    import script_fill_decide as d
    import vault_scripts

    d.fillable = lambda item, *, account_id, standard_folders=True: None

    def fillable_rows(items, *, account_id, standard_folders=True):
        return [vault_scripts._with_script_why({k: v for k, v in i.items() if k != "why"}) for i in items
                if d.fillable(i, account_id=account_id, standard_folders=standard_folders) is None]
    d.fillable_rows = fillable_rows


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-21-script-fill --break --baseline=slop/evidence/<green folder>
        "script-fill-skips-eligibility": Fault(_skip_eligibility, (FILL_READ_BACK, FILL_SEND)),
    }
