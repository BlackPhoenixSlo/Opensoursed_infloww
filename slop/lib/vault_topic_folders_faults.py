"""Build AI folders' opt-in "Topic folders (Jev)": check names and break-it-once faults, for
scenarios/2026-11-12-vault-topic-folders.py. lib/faults.py merges `register(Fault)`.
"""
from __future__ import annotations

OFF_BY_DEFAULT = "topic_folders_off_by_default"
UNKNOWN_422 = "topic_folders_unknown_422"
PLAN = "topic_folders_plan_exact"
FREE_GUARD = "topic_folders_free_guard"
APPLIED = "topic_folders_apply_equals_preview"
UI_TICKED = "topic_folders_ticked_from_ui"
RETIRE = "topic_folders_untick_retires"
FEET = "topic_feet_folders"


def _free_guard_off() -> None:
    """The free split trusts `lane5` alone: an item Jev saw bare or was unsure about (settle nn.10 calls a
    coin-flip nipple free when NudeNet saw nothing) lands in a free topic folder."""
    import vault_topic_folders as vtf

    if not hasattr(vtf, "free_ok"):
        raise RuntimeError("slop fault: vault_topic_folders.free_ok is gone; update lib/vault_topic_folders_faults.py")
    vtf.free_ok = lambda jev: True


def _feet_tease_free_guard_off() -> None:
    """AI-feet tease trusts `lane5` free alone: both guards off (the pack picker's tier-0 rule, `jev_tier`, and the
    topic module's own `free_ok`), so a feet photo Jev filed free but saw a breast bare or unsure of lands in the
    free preview folder."""
    import vault_pack_picker as vp
    import vault_topic_folders as vtf

    for mod, name in ((vp, "jev_tier"), (vtf, "free_ok"), (vtf, "feet_rung")):
        if not hasattr(mod, name):
            raise RuntimeError(f"slop fault: {mod.__name__}.{name} is gone; update lib/vault_topic_folders_faults.py")
    real = vp.jev_tier
    vp.jev_tier = lambda j: 0 if j.get("lane5") == "free" else real(j)
    vtf.free_ok = lambda jev: True


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-12-vault-topic-folders --break (the scenario's FAULT): the free guard off (server).
        "vault-topics-free-guard-off": Fault(_free_guard_off, (FREE_GUARD,)),
        # --fault=ai-feet-tease-free-guard-off: AI-feet tease takes lane5 free on trust (server; also trips the
        # general free guard: free_ok is shared).
        "ai-feet-tease-free-guard-off": Fault(_feet_tease_free_guard_off, (FEET,)),
    }
