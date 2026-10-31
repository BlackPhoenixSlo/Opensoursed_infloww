"""The vault import pick list's break-it-once fault (scenarios/2026-10-30-vault-import-reducer.py): lib/faults.py
merges `register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's served JS (actors/ui.py). The
check names live here and the scenario imports them, so a target can never name a check that does not exist.
"""
from __future__ import annotations

SENT_FILES = ("vault import: the browser sends exactly the selected, not-deleted files (a.jpg, c.mp4), each with "
              "its own meta; nothing for the deselected b.png or the deleted d.jpg")
PROTOCOL = ("vault import: the first file opens the run (POST /batch, keep_open=1), the other follows in one "
            "POST /batch/append (last=1, the run's id), both for the picked Creator")
RUN_ITEMS = "vault import: the relay's run lists exactly the sent files, all done, and saved both files' details"
OF_BYTES = "vault import: OnlyFans received exactly the sent files' bytes, and every carrier post was deleted"
DB_ROWS = "vault import: each landed file's vault_items row carries its own typed hashtags / price / notes"
SETTLED_UI = ("vault import: the card settles with the deselected b.png still listed, unchecked, its notes kept, "
              "and '2 in vault'")


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-vault-import-reducer --break (the scenario's FAULT)
        # app/components/vault/importPickReducer.ts `chosenOf`: the selection ignored, every picked file sent.
        "import-sends-unselected": Fault(None, (SENT_FILES, PROTOCOL, RUN_ITEMS, OF_BYTES, DB_ROWS, SETTLED_UI), browser=(
            (r"return s\.picked\.filter\(\(f\)\s*=>\s*s\.selected\.has\(f\)\);", "return [...s.picked];"),
        )),
    }
