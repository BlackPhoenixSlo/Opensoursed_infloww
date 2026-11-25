from __future__ import annotations

OFF_BY_DEFAULT = "topic_folders_off_by_default"
UNKNOWN_422 = "topic_folders_unknown_422"
PLAN = "topic_folders_plan_exact"
FREE_GUARD = "topic_folders_free_guard"
APPLIED = "topic_folders_apply_equals_preview"
UI_TICKED = "topic_folders_ticked_from_ui"
RETIRE = "topic_folders_untick_retires"


def _free_guard_off() -> None:
    import vault_topic_folders as vtf

    if not hasattr(vtf, "free_ok"):
        raise RuntimeError("slop fault: vault_topic_folders.free_ok is gone; update lib/vault_topic_folders_faults.py")
    vtf.free_ok = lambda jev: True


def register(Fault) -> dict:
    return {
        "vault-topics-free-guard-off": Fault(_free_guard_off, (FREE_GUARD,)),
    }
