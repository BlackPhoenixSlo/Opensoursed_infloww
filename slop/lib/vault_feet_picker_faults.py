"""Vault Pro's feet pack picker (ranked, prefilled, keyboard): check names and break-it-once faults, for
scenarios/2026-11-11-vault-feet-picker.py. lib/faults.py merges `register(Fault)`.
"""
from __future__ import annotations

RANKED = "feet_ranked_above_like_baseline"
PREFILL = "feet_prefill_matches_flags"
NO_FREE = "feet_no_free_prefill_without_tier"
KEYS = "feet_keyboard_confirm_members"
PHONE = "feet_phone_layout_tap_save"


def _need(vp, *names: str) -> None:
    for n in names:
        if not hasattr(vp, n):
            raise RuntimeError(f"slop fault: vault_pack_picker.{n} is gone; update lib/vault_feet_picker_faults.py")


def _like_only() -> None:
    """The ranking falls back to LIKE-only: every candidate scores 0, so the queue comes back in media_id order
    (the pre-change grid, the base rate) and nothing is prefilled (below SUGGEST_MIN)."""
    import vault_pack_picker as vp

    _need(vp, "likelihood", "SUGGEST_MIN")
    vp.likelihood = lambda cat, fields, text="": 0.0


def _free_prefill_unknown_tier() -> None:
    """The pre-fix prefill: an unknown tier (no `_jev.lane5`, no flags) guessed from clothing alone, so socks on an
    unflagged row land on the free preview rung (a nude body the describe missed would ride free)."""
    import vault_pack_picker as vp

    _need(vp, "suggest", "price_tier", "SUGGEST_MIN")
    real = vp.suggest

    def leaky(cat, fields, p):
        got = real(cat, fields, p)
        if got is None and p >= vp.SUGGEST_MIN and isinstance(fields, dict) and vp.price_tier(fields) is None:
            worn = " ".join(str(x).lower() for x in fields.get("clothing_items") or [])
            return cat.rungs[0] if any(g in worn for g in cat.covered_by) else cat.rungs[1]
        return got

    vp.suggest = leaky


def register(Fault) -> dict:
    return {
        # slop/run 2026-11-11-vault-feet-picker --break (the scenario's FAULT). Server. The keyboard check is
        # targeted too: with nothing ranked or prefilled, the top tiles show no prefill for Enter to confirm.
        "feet-rank-like-only": Fault(_like_only, (RANKED, PREFILL, KEYS)),
        # --fault=feet-free-prefill-unknown-tier: the free-rung leak (server).
        "feet-free-prefill-unknown-tier": Fault(_free_prefill_unknown_tier, (NO_FREE, PREFILL)),
        # --fault=feet-keys-enter-ignores-suggestion: app/components/vault/packPickerState.ts, Enter only moves on
        # (never takes the suggestion). Client; `next dev` serves the module unminified.
        "feet-keys-enter-ignores-suggestion": Fault(None, (KEYS,), browser=(
            (r"if\s*\(\s*decided\s*\|\|\s*!item\.suggested\s*\)", r"if (true)"),
        )),
    }
