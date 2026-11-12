"""Vault Pro's "Build AI folders" with a partly flagged vault: check names and break-it-once faults, for
scenarios/2026-11-10-vault-ai-folders-partial-flags.py. lib/faults.py merges `register(Fault)`.
"""
from __future__ import annotations

PLAN = "ai_folders_plan_partial_flags"
CREATE_ENABLED = "create_enabled_partial_flags"
PHONE_OFFERED = "ai_folders_phone_offered"
CREATED = "ai_folders_created_from_ui"
PAID_ONLY = "ai_folders_paid_flagged_only"
NO_DUPES = "ai_folders_no_duplicate_in_folder"
COLOURLESS = "ai_folders_colourless_set"
PREVIEW = "ai_folders_preview_counts"
PREVIEW_SHOWN = "ai_folders_preview_counts_shown"


def _dupe_collapse_off() -> None:
    """The plan groups every copy of a duplicate set again (the pre-PR-A behaviour): `collapse_dupes` keeps all
    rows and drops nothing, so a re-upload sits beside its original in the same folder."""
    import vault_scripts as vs

    if not hasattr(vs, "collapse_dupes"):
        raise RuntimeError("slop fault: vault_scripts.collapse_dupes is gone; update lib/vault_ai_folders_faults.py")
    vs.collapse_dupes = lambda rows, groups: (list(rows), [])


def _guess_unflagged() -> None:
    """The $10 lane guesses an unflagged paid still from its describe `clothing_state` (partially_off /
    pulled_down / pulled_aside) instead of leaving it out until the flags pass looked: the pre-flags fallback
    measured wrong on ~1 in 3 stills."""
    import vault_ai_brief
    import vault_scripts as vs

    for n in ("PURPOSE_LANES", "_lane_tease_10", "_PAID_TIERS"):
        if not hasattr(vs, n):
            raise RuntimeError(f"slop fault: vault_scripts.{n} is gone; update lib/vault_ai_folders_faults.py")
    real = vs._lane_tease_10

    def guessed(why, fields, kind):
        if kind == "photo" and why["tier"] in vs._PAID_TIERS and not vault_ai_brief.flags_known(fields):
            return str(fields.get("clothing_state") or "").lower() in ("partially_off", "pulled_down", "pulled_aside")
        return real(why, fields, kind)

    vs.PURPOSE_LANES = tuple((s, n, p, guessed if f is real else f) for s, n, p, f in vs.PURPOSE_LANES)


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-10-vault-ai-folders-partial-flags --break (the scenario's FAULT): every copy of a
        # duplicate set planned again (server, vault_scripts.collapse_dupes).
        "ai-folders-dupe-collapse-off": Fault(_dupe_collapse_off, (NO_DUPES,)),
        # --fault=ai-folders-create-blocked-on-flags
        # app/components/vault/VaultAiFoldersModal.tsx: Create disabled again while any still lacks flags (the
        # pre-change `!flags.ready` block). `next dev` serves the module inside eval("..."), unminified.
        "ai-folders-create-blocked-on-flags": Fault(None, (CREATE_ENABLED,), browser=(
            (r"(disabled:\s*)(!submittable\b)", r"\1flagsMissing || \2"),
        )),
        # --fault=ai-folders-guess-unflagged: unflagged paid stills guessed into the $10 lane (server).
        "ai-folders-guess-unflagged": Fault(_guess_unflagged, (PLAN, PAID_ONLY)),
    }
