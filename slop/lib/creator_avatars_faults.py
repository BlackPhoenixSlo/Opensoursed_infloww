"""The Manage creators avatars flow's break-it-once fault (scenarios/2026-11-04-creator-avatars.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them.
"""
from __future__ import annotations

OWN_ONLY = "creators table: no row shows another Creator's OF picture"
OWN_SHOWN = "creators table: every Creator answered as itself shows its own OF picture (all distinct)"


def register(Fault) -> dict:
    return {
        # slop/run creator-avatars --break: the identity guard reverted (useAccountAvatar's fetchOwnProfile keeps any
        # /users/me body, and the cache/health selector accepts it), so the rows the fake OF answers as the default Creator paint its face (the AE bug).
        # Replace only the identity comparison: keep null for absent profiles,
        # otherwise a false health value would mask the fallback and hide the fault.
        # `next dev` bundles the hook into the layout's chunk and /creators' page chunk: 2 files.
        "avatar-keeps-other-creators-body": Fault(None, (OWN_ONLY,), browser=(
            (r"String\(me\.id\) === accountId", "true"),
            (r"String\(profile\.id\) === accountId", "true"),), browser_files=2),
    }
