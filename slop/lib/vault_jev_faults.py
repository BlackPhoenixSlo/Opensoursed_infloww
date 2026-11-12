"""The vault Jev v8 pass's check names and break-it-once faults (scenarios/2026-11-11-vault-jev-flags.py):
lib/faults.py merges `register(Fault)` into FAULTS. Each patches a product module attribute the product looks up per
call (`vault_jev_pass.enabled` by bare global name / via the module, `vault_ai_vision._describe_and_flag` by bare
global name, `vault_jev_rules.settle` by bare name inside `final`, `vault_describe_jev.review_lane` by bare name inside
`route`), so the patch bites on the next press.
"""
from __future__ import annotations

JEV_ONLY_WHEN_ON = ("Jev v8: TypeSafe is called only for photos of the Creator the operator switched Jev on for "
                    "(none for the Creator switched on then off, the untouched ones, clips or audio); only that "
                    "Creator's photos carry `_jev`; the config route stores the toggle and the describe plan's "
                    "`jev.enabled` follows it")
JEV_LANES = ("Jev v8: every photo of the on-Creator ends `_jev.status` ok with `lane5` the lane its planted answers "
             "spell ($100 inserted, $50 bare vulva / lower crop, $10 topless, free dressed, a coin flip settled), "
             "the fake saw exactly the passes those answers call for (1 / 1+2 / 1+L), `settled` only on the "
             "coin flips; every profile and pass 2 / L exercised; no unplaced, key-less or danger-header-less call")
JEV_BEFORE_DESCRIBE = ("Jev v8: in describe-all, each on-Creator photo's TypeSafe calls all happen before its first "
                       "describe call")
JEV_COST = ("Jev v8: each sweep's `jev_cost_millicents` == the fake's billed input tokens at $0.042/M (rounded up per "
            "photo), its `cost_millicents` == DeepInfra billed + that; the account's `typesafe` grok_daily_cost row "
            "and its done `vault_jev_flags` grok_calls rows sum to the same")
JEV_COPY = ("Jev v8: in each planted re-upload photo set of the on-Creator one member pays TypeSafe, every other "
            "carries that member's `_jev` with a copy mark and no TypeSafe call of its own")
JEV_DESCRIBE_PROSE = ("Jev-fed describe (D51): every on-Creator photo Jev did not leave in review is described with "
                      "the prose recipe (no hedge) and stamped `_describe` path prose / px 640 / its `_jev` version; "
                      "its stored description is the fake's prose cut down to exactly the claims its planted answers "
                      "spell (nipples / pussy / inserted), marker kept; each claim both kept and dropped somewhere")
JEV_DESCRIBE_REVIEW = ("Jev-fed describe (D51): every on-Creator photo Jev left in review (the coin flips) is "
                       "described with the v6 recipe (V2 + facts + the review hedge) and stamped `_describe` path v6 "
                       "/ px 960; its description is the fake's, unchanged")
JEV_DESCRIBE_OFF = ("Jev-fed describe (D51): everything else (other Creators, clips) keeps today's describe: the "
                    "verbatim V2 prompt, `_describe` path v2 with no Jev version or px, the fake's description")
JEV_UI_TOGGLE = ("Jev v8 UI: Vault Pro > Extras' \"Jev v8 flags\" switch for an off Creator shows off (config route "
                 "false), one click turns it on and it settles on with no refusing line; then the config route says "
                 "`vault_jev_enabled` true, the describe plan's `jev` enabled and ready, and the account_ai_config row "
                 "true")


def _ignores_setting() -> None:
    """The opt-in ignored: `vault_jev_pass.enabled` says on for every Creator, so Jev runs on every photo
    (JEV_ONLY_WHEN_ON)."""
    import vault_jev_pass

    async def on(_account_id: str) -> bool:
        return True

    vault_jev_pass.enabled = on


def _no_settle() -> None:
    """settle nn.10 skipped: a photo Jev is unsure about stays `review` instead of settling (JEV_LANES)."""
    import vault_jev_rules

    vault_jev_rules.settle = lambda d, mode=None: None


def _after_describe() -> None:
    """Jev after describe: `_describe_and_flag` describes and flags first, Jev last (JEV_BEFORE_DESCRIBE). This copy
    must track vault_ai_vision._describe_and_flag with only the order changed."""
    import vault_ai_vision as v
    import vault_ai_vision_decide as d
    import vault_jev_pass as jp

    async def describe_then_jev(account_id, media_id, *, jev_sweep=None, **describe_kw):
        res = await v._describe_one(account_id, media_id, **describe_kw)
        if res.get("ok"):
            try:
                res = d.with_flags_cost(res, await v._flags_one(account_id, media_id))
            except Exception:  # noqa: BLE001 — as the product
                pass
        return d.with_jev(res, await jp.safe(account_id, media_id, sweep=jev_sweep))

    v._describe_and_flag = describe_then_jev


def _describe_ignores_review() -> None:
    """The Jev-fed describe ignores the review lane: `vault_describe_jev.review_lane` (looked up by bare name inside
    `route`) always False, so a review photo gets the prose recipe (JEV_DESCRIBE_REVIEW)."""
    import vault_describe_jev

    vault_describe_jev.review_lane = lambda jev: False


def register(Fault) -> dict:
    return {
        # slop/run vault-jev-flags --break (the scenario's FAULT)
        "vault-jev-ignores-setting": Fault(_ignores_setting, (JEV_ONLY_WHEN_ON,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-no-settle
        "vault-jev-no-settle": Fault(_no_settle, (JEV_LANES,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-after-describe
        "vault-jev-after-describe": Fault(_after_describe, (JEV_BEFORE_DESCRIBE,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-describe-ignores-review
        "vault-jev-describe-ignores-review": Fault(_describe_ignores_review, (JEV_DESCRIBE_REVIEW,)),
    }
