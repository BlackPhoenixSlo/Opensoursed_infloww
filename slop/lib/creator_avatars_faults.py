from __future__ import annotations

OWN_ONLY = "creators table: no row shows another Creator's OF picture"
OWN_SHOWN = "creators table: every Creator answered as itself shows its own OF picture (all distinct)"


def register(Fault) -> dict:
    return {
        "avatar-keeps-other-creators-body": Fault(None, (OWN_ONLY,), browser=(
            (r"String\(me\.id\) === accountId", "true"),
            (r"String\(profile\.id\) === accountId", "true"),), browser_files=2),
    }
