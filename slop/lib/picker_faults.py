from __future__ import annotations

PICKER_FOLDERS_FILES = 2

RESTRICTED_MENU = "vault picker: a folder-restricted chatter's folder menu lists only their allowed folders"


def register(Fault) -> dict:
    return {
        "picker-ignores-folder-access": Fault(None, (RESTRICTED_MENU,), browser=(
            # next dev (webpack) serves each module as an eval string with literal `\n` for newlines
            (r"(function folderSelectItems\([^)]*\)\s*\{(?:\s|\\n)*)if \(restricted\)", r"\1if (false)"),
        ), browser_files=PICKER_FOLDERS_FILES, ts_files=1),
    }
