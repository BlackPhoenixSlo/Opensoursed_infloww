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
SCRIPTS_CAPPED = "scripts_capped_named"


def _dupe_collapse_off() -> None:
    import vault_scripts as vs

    if not hasattr(vs, "collapse_dupes"):
        raise RuntimeError("slop fault: vault_scripts.collapse_dupes is gone; update lib/vault_ai_folders_faults.py")
    vs.collapse_dupes = lambda rows, groups: (list(rows), [])


def _script_cap_off() -> None:
    import vault_scripts as vs

    if not hasattr(vs, "cap_ladder"):
        raise RuntimeError("slop fault: vault_scripts.cap_ladder is gone; update lib/vault_ai_folders_faults.py")
    vs.cap_ladder = lambda items: (list(items), [])


def _guess_unflagged() -> None:
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
        "ai-folders-dupe-collapse-off": Fault(_dupe_collapse_off, (NO_DUPES,)),
        "ai-folders-create-blocked-on-flags": Fault(None, (CREATE_ENABLED,), browser=(
            (r"(disabled:\s*)(!submittable\b)", r"\1flagsMissing || \2"),
        )),
        "ai-folders-guess-unflagged": Fault(_guess_unflagged, (PLAN, PAID_ONLY)),
        "ai-folders-script-cap-off": Fault(_script_cap_off, (SCRIPTS_CAPPED,)),
    }
