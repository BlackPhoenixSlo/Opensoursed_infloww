"""Vault Pro's feet pack picker (precision only: confident Jev photos, prefilled, keyboard): check names and
break-it-once faults, for scenarios/2026-11-11-vault-feet-picker.py. lib/faults.py merges `register(Fault)`.
"""
from __future__ import annotations

RANKED = "feet_ranked_above_like_baseline"
PREFILL = "feet_prefill_matches_flags"
NO_FREE = "feet_no_free_prefill_without_tier"
KEYS = "feet_keyboard_confirm_members"
PHONE = "feet_phone_layout_tap_save"
JEV_RANK = "feet_jev_selects_and_ranks"
JEV_FREE_GUARD = "feet_jev_free_guard"
PRESELECT = "feet_preselect_confirm"


def _need(vp, *names: str) -> None:
    for n in names:
        if not hasattr(vp, n):
            raise RuntimeError(f"slop fault: vault_pack_picker.{n} is gone; update lib/vault_feet_picker_faults.py")


def _like_only() -> None:
    """The gate falls back to "Jev saw feet" (the LIKE-era recall): every Jev score is 1, so every Jev photo with
    a feet tag "y" is a candidate, the half-sure .55 rows (and any other below the gate) queued and prefilled.
    (Name kept from the qwen-ranking era, when it zeroed the old blended score; that score is gone.)"""
    import vault_pack_picker as vp

    _need(vp, "jev_likelihood", "confident")
    vp.jev_likelihood = lambda cat, j: 1.0


def _free_prefill_unknown_tier() -> None:
    """The pre-fix prefill: an unknown Jev tier (lane5 review, an unsure body answer) guessed from Jev's covering
    answer alone, so socks land on the free preview rung (a body Jev half-saw would ride free)."""
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
    """The pre-fix Jev tier: lane5 "free" is tier 0 whatever the body answers, so a free-filed photo with
    breasts_bare / crotch_bare / penetration "unsure" (settle nn.10 can do that) is prefilled on, and filed to, the
    free preview rung."""
    import vault_pack_picker as vp

    _need(vp, "jev_tier", "free_ok", "NotFreeSafe")
    real = vp.jev_tier
    vp.jev_tier = lambda j: 0 if j.get("lane5") == "free" else real(j)


def _preselect_threshold_low() -> None:
    """The Jev gate back down at 0.3 (below the measured .6): a Jev row Jev is only half sure is feet (the seeded
    `jev_maybe`, feet_subject .55) is a candidate again, prefilled and PRESELECTED, so "File N preselected" files
    it unseen."""
    import vault_pack_picker as vp

    _need(vp, "FEET_PRESELECT_SCORE", "jev_pick")
    vp.FEET_PRESELECT_SCORE = 0.3


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-11-vault-feet-picker --break (the scenario's FAULT). Server. Below-gate Jev rows in the
        # queue (ranked: set != keepers; jev rank: out-row back), prefilled (prefill: stray) and preselected
        # (preselect: API extra). The keyboard check is no longer targeted: the top tiles still show a prefill.
        "feet-rank-like-only": Fault(_like_only, (RANKED, PREFILL, JEV_RANK, PRESELECT)),
        # --fault=feet-free-prefill-unknown-tier: the free-rung leak (server): the unknown-tier rows prefilled
        # (prefill), on tease (no-free), and preselected (preselect).
        "feet-free-prefill-unknown-tier": Fault(_free_prefill_unknown_tier, (NO_FREE, PREFILL, PRESELECT)),
        # --fault=feet-jev-free-guard-off: Jev's lane5 free trusted over unsure body answers (server): the unsafe
        # rows prefilled tease (prefill), flagged free-safe, the triage 400 gone, the UI's tease enabled (guard).
        "feet-jev-free-guard-off": Fault(_jev_free_guard_off, (JEV_FREE_GUARD, PREFILL)),
        # --fault=feet-preselect-threshold-low: the Jev gate at 0.3 (server): the half-sure Jev rows come back as
        # candidates (ranked, jev rank), preselected (preselect check: API flags, ticked tiles, the File POST) and
        # prefilled (prefill).
        "feet-preselect-threshold-low": Fault(_preselect_threshold_low, (PRESELECT, PREFILL, RANKED, JEV_RANK)),
        # --fault=feet-keys-enter-ignores-suggestion: app/components/vault/packPickerState.ts, Enter only moves on
        # (never takes the suggestion). Client; `next dev` serves the module unminified.
        "feet-keys-enter-ignores-suggestion": Fault(None, (KEYS,), browser=(
            (r"if\s*\(\s*decided\s*\|\|\s*!item\.suggested\s*\)", r"if (true)"),
        )),
    }
