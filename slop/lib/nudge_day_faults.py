"""Nudge online's day picker, vault-only images and Share to models: break-it-once faults
(scenarios/2026-11-10-nudge-day-images.py). lib/faults.py merges `register(Fault)` into FAULTS. The check names live
here and the scenario imports them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

DAY_CHIP = ("nudge day images (day-chip-no-fade): right after 'Sat' is clicked (same task, no frame waited) the "
            "'Every day' chip's computed border colour equals the unselected 'Mon' chip's and differs from 'Sat''s")
VAULT_ONLY = ("nudge day images (images-vault-only): the Night card has no Upload button or image file input, its "
              "image came through the Vault picker, and no POST /api/of/v2/vault/upload/* left the browser during "
              "the flow")
DAY_SAVED = ("nudge day images (saved-day-slot-has-vault-id): Creator 0's stored config has saturday.night = the "
             "picked vault id and no lines of its own, saturday.evening the copied lines with the first one edited, "
             "and the every-day bucket the seeded one (account_ai_config row)")
SHARE_SAVED = ("nudge day images (share-keeps-own-images): Share to 2 models PUTs Creator 0's dirty form first, then "
               "one PUT /admin/nudge-config/bulk for [Creator 1, Creator 2]; each target's row has Creator 0's "
               "settings and lines (Saturday's edit too), its own images only (Creator 1's 9101, Creator 2 none), no "
               "Creator 0 vault id, and its nudge_online rule on")
DAY_PREVIEW = ("nudge day images (preview-uses-day): POST /admin/nudge-config/preview on the stored config at 23:00 "
               "answers Saturday's own image with the every-day night line, and Monday the every-day image")
DAY_NO_5XX = "nudge day images: no 5xx answered to the browser during the flow"


def _share_copies_source_images() -> None:
    """PUT /admin/nudge-config/bulk writes the source's slots as sent, its vault ids included (the pre-fix roll-out
    with images left on): `put_nudge_config_bulk` calls `_with_own_images` by module global per request."""
    import nudge_config_api as n

    n._with_own_images = lambda shared, own: {b: dict(v) for b, v in shared.items()}


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-10-nudge-day-images --break (the scenario's FAULT). Relay side: each target gets Creator
        # 0's images, so only SHARE_SAVED (the targets' rows) goes red; Creator 0's row, the preview, the chips and
        # the browser's requests stay as they were.
        "nudge-share-copies-source-images": Fault(_share_copies_source_images, (SHARE_SAVED,)),
        # slop/run 2026-11-10-nudge-day-images --break --fault=nudge-day-chip-fades
        # app/components/settings/NudgeSlotPools.tsx: the day chips get `transition-colors` back (the pre-fix
        # class), so right after the click 'Every day' still draws the selected border mid-fade. Only that class
        # string carries "px-2.5 text-[13px] focus:outline-none": 1 file.
        "nudge-day-chip-fades": Fault(None, (DAY_CHIP,), browser=(
            (r"(rounded-md border px-2\.5 text-\[13px\]) (focus:outline-none)", r"\1 transition-colors \2"),
        )),
    }
