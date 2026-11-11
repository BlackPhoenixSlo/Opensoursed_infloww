"""Nudge online's per-day images break-it-once fault (scenarios/2026-11-10-nudge-day-images.py): lib/faults.py merges
`register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's served JS (actors/ui.py). The check names live
here and the scenario imports them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

DAY_UPLOAD = ("nudge day images (upload-went-through-vault-import): the drop and the Upload button each send their "
              "file in one POST /vault/upload/batch for Creator 0 (no append: one file per run), the relay's two runs "
              "list them done, and OnlyFans received both files' bytes (sha256)")
DAY_SAVED = ("nudge day images (saved-day-slot-has-vault-ids): the stored config's saturday.night holds the two landed "
             "vault ids in upload order and no lines of its own, saturday.evening the copied lines with the first "
             "one edited, and the every-day bucket is the seeded one (account_ai_config row)")
DAY_HELD = ("nudge day images (save-held-while-uploading): Save reads 'Uploading images…', disabled, from the drop "
            "until after the second upload was sent, and is never enabled under that label")
DAY_PREVIEW = ("nudge day images (preview-uses-day): POST /admin/nudge-config/preview on the stored config at 23:00 "
               "answers Saturday's own first image with the every-day night line, and Monday the every-day image")
DAY_NO_5XX = "nudge day images: no 5xx answered to the browser during the flow"


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-10-nudge-day-images --break (the scenario's FAULT)
        # app/components/settings/NudgeOnlineTab.tsx: a landed upload's `addImages` goes to the every-day bucket, not
        # the day picked when it was dropped. Saturday's night keeps no images, so the stored config and the
        # Saturday preview (which then rotates the every-day image, seeded first) both go red. Template literal, not
        # a quote: next dev's webpack serves the module inside an eval("...") string. Served in the Nudge tab's
        # chunk only: 1 file.
        "nudge-upload-lands-every-day": Fault(None, (DAY_SAVED, DAY_PREVIEW), browser=(
            (r"(bucket:\s*)(\w+)\.bucket,((?:\\n|\s)*key:\s*)\2\.slotKey", r"\1`default`,\3\2.slotKey"),
        )),
    }
