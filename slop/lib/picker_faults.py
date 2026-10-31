"""The chat vault picker's folder-menu fault (scenarios/2026-10-30-vault-import-reducer.py, its restricted-chatter
phase): lib/faults.py merges `register(Fault)` into FAULTS. Client side: `browser=` rewrites the app's served JS
(actors/ui.py) and the modules lib/app_ts.py loads in node. The check name lives here and the scenario imports it,
so a target can never name a check that does not exist.
"""
from __future__ import annotations

# Served JS files `next dev` bundles vaultPickerFolders.ts into that a run of the scenario loads (measured below).
PICKER_FOLDERS_FILES = 2

RESTRICTED_MENU = "vault picker: a folder-restricted chatter's folder menu lists only their allowed folders"


def register(Fault) -> dict:
    return {
        # slop/run 2026-10-30-vault-import-reducer --break --fault=picker-ignores-folder-access
        # app/components/chat/vaultPickerFolders.ts `folderSelectItems`: the restricted branch off, so a restricted
        # chatter's menu is OF's folder list (as an owner's) instead of their Chatter Access allowlist.
        "picker-ignores-folder-access": Fault(None, (RESTRICTED_MENU,), browser=(
            # `(?:\s|\\n)*`: next dev (webpack) serves each module as an eval string, its newlines a literal `\n`.
            (r"(function folderSelectItems\([^)]*\)\s*\{(?:\s|\\n)*)if \(restricted\)", r"\1if (false)"),
        ), browser_files=PICKER_FOLDERS_FILES, ts_files=1),
    }
