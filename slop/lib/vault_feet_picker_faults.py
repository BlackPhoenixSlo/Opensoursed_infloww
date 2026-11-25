from __future__ import annotations

RANKED = "feet_ranked_above_like_baseline"
PREFILL = "feet_prefill_matches_flags"
NO_FREE = "feet_no_free_prefill_without_tier"
KEYS = "feet_keyboard_confirm_members"
PHONE = "feet_phone_layout_tap_save"
JEV_RANK = "feet_jev_selects_and_ranks"
JEV_FREE_GUARD = "feet_jev_free_guard"
PRESELECT = "feet_preselect_confirm"
POSSIBLE_FLOOR = "feet_possible_floor"


def _need(vp, *names: str) -> None:
    for n in names:
        if not hasattr(vp, n):
            raise RuntimeError(f"slop fault: vault_pack_picker.{n} is gone; update lib/vault_feet_picker_faults.py")


def _like_only() -> None:
    import vault_pack_picker as vp

    _need(vp, "jev_likelihood", "confident")
    vp.jev_likelihood = lambda cat, j: 1.0


def _free_prefill_unknown_tier() -> None:
    import vault_pack_picker as vp

    _need(vp, "jev_pick", "jev_tier", "confident", "JEV_KEY", "_jev_tags")
    real = vp.jev_pick

    def leaky(cat, j):
        got = real(cat, j)
        if got is None and vp.confident(cat, {vp.JEV_KEY: j}) is not None and vp.jev_tier(j) is None:
            detail = vp._jev_tags(j).get(cat.jev_detail) if cat.jev_detail else None
            return cat.rungs[1] if detail == "bare" else cat.rungs[0]
        return got

    vp.jev_pick = leaky


def _jev_free_guard_off() -> None:
    import vault_pack_picker as vp

    _need(vp, "jev_tier", "free_ok", "NotFreeSafe")
    real = vp.jev_tier
    vp.jev_tier = lambda j: 0 if j.get("lane5") == "free" else real(j)


def _preselect_threshold_low() -> None:
    import vault_pack_picker as vp

    _need(vp, "FEET_PRESELECT_SCORE", "jev_pick")
    vp.FEET_PRESELECT_SCORE = 0.3


def _possible_floor_off() -> None:
    import vault_pack_picker as vp

    _need(vp, "FEET_POSSIBLE_MIN", "possible")
    vp.FEET_POSSIBLE_MIN = 0.0


def register(Fault) -> dict:
    return {
        "feet-rank-like-only": Fault(_like_only, (RANKED, PREFILL, JEV_RANK, PRESELECT)),
        "feet-free-prefill-unknown-tier": Fault(_free_prefill_unknown_tier, (NO_FREE, PREFILL, PRESELECT)),
        "feet-jev-free-guard-off": Fault(_jev_free_guard_off, (JEV_FREE_GUARD, PREFILL)),
        "feet-preselect-threshold-low": Fault(_preselect_threshold_low, (PRESELECT, PREFILL, RANKED, JEV_RANK)),
        "feet-possible-floor-off": Fault(_possible_floor_off, (POSSIBLE_FLOOR, RANKED, PREFILL)),
        "feet-keys-enter-ignores-suggestion": Fault(None, (KEYS,), browser=(
            (r"if\s*\(\s*decided\s*\|\|\s*!item\.suggested\s*\)", r"if (true)"),
        )),
    }
