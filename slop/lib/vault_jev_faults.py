"""The vault Jev v8 pass's check names and break-it-once faults (scenarios/2026-11-11-vault-jev-flags.py):
lib/faults.py merges `register(Fault)` into FAULTS. Each patches a product module attribute the product looks up per
call (`_jev_and_flag` by bare name inside `vault_ai_vision`, `vault_describe_jev.route` via the module,
`vault_jev_rules.settle` by bare name inside `final`, `vault_describe_jev.review_lane` by bare name inside `route`),
so the patch bites on the next press. JEV_BEFORE_DESCRIBE has no fault of its own any more: a photo described before
Jev has no `_jev` and is skipped, so the order cannot break without the describe checks going red with it.
"""
from __future__ import annotations

JEV_DEFAULT_ON = ("Jev v8 default on: with no setting anywhere, every Creator's photos (bar the planted Jev-down "
                  "ones) end with `_jev` ok; no TypeSafe call and no `_jev` for clips or audio; the describe plan's "
                  "`jev` is {ready, reason} and ready; no `vault_jev_enabled` on the config route or the "
                  "account_ai_config table")
JEV_PHOTO_NO_QWEN_FLAGS = ("Jev v8 default on: no DeepInfra flags call for any photo in either sweep; every photo Jev "
                           "read carries its flags from Jev (`_flags_model` jev, `_flags_v` 3, every flag key)")
JEV_CLIP_QWEN_FLAGS = ("Jev v8 default on: clips keep the qwen flags call: every Creator's videos get DeepInfra flags "
                       "calls, and no video carries Jev flags")
JEV_PHOTO_NEVER_V2 = ("Jev v8 default on: no photo is ever described with the V2 recipe (no v2 describe call, no "
                      "`_describe` path v2 written this run); a Jev-down photo (TypeSafe 400) ends `_jev` error with "
                      "no describe call and its describe status untouched (skipped, not v2), one Jev "
                      "try per sweep")
JEV_LANES = ("Jev v8: every photo ends `_jev.status` ok with `lane5` the lane its planted answers "
             "spell ($100 inserted, $50 bare vulva / lower crop, $10 topless, free dressed, a coin flip settled), "
             "the fake saw exactly the passes those answers call for (1 / 1+2 / 1+L), `settled` only on the "
             "coin flips; every profile and pass 2 / L exercised; no unplaced, key-less or danger-header-less call")
JEV_BEFORE_DESCRIBE = ("Jev v8: in describe-all, each photo's TypeSafe calls all happen before its first "
                       "describe call")
JEV_COST = ("Jev v8: each sweep's `jev_cost_millicents` == the fake's billed input tokens at $0.042/M (rounded up per "
            "photo), its `cost_millicents` == DeepInfra billed + that; the account's `typesafe` grok_daily_cost row "
            "and its done `vault_jev_flags` grok_calls rows sum to the same")
JEV_COPY = ("Jev v8: in each planted re-upload photo set one member pays TypeSafe, every other "
            "carries that member's `_jev` with a copy mark and no TypeSafe call of its own")
JEV_DESCRIBE_PROSE = ("Jev-fed describe (D51): every photo Jev did not leave in review is described with "
                      "the prose recipe (no hedge) and stamped `_describe` path prose / px 640 / its `_jev` version; "
                      "its stored description is the fake's prose cut down to exactly the claims its planted answers "
                      "spell (nipples / pussy / inserted), marker kept; each claim both kept and dropped somewhere; "
                      "its `clothing_items` the fake's, and its `over_` garment names from them only over a region "
                      "Jev calls covered")
JEV_DESCRIBE_REVIEW = ("Jev-fed describe (D51): every photo Jev left in review (the coin flips) is "
                       "described with the v6 recipe (V2 + facts + the review hedge) and stamped `_describe` path v6 "
                       "/ px 960; its description is the fake's, unchanged")
JEV_DESCRIBE_OFF = ("Jev-fed describe (D51): clips keep today's describe: the verbatim V2 prompt, `_describe` path v2 "
                    "with no Jev version or px, the fake's description")
JEV_UI_DESCRIBED = ("Jev v8 UI: Vault Pro on Creator 0, one click on a prose-described photo's tile opens its "
                    "panel, whose Description box settles on the stored Jev-fed text; the row's `_describe.path` is "
                    "prose with Jev flags, and `/admin/vault-ai/items` serves it described with that text and path")


def _photo_qwen_flags() -> None:
    """Photos still get the qwen flags call: the flags sweep's per-photo step (`vault_ai_vision._jev_and_flag`,
    looked up per call) also runs `vault_ai_vision._flags_one` after Jev, as the pre-Jev photo path did, its spend
    reported like the real regression would (JEV_PHOTO_NO_QWEN_FLAGS)."""
    import vault_ai_vision

    real = vault_ai_vision._jev_and_flag

    async def _jev_and_flag(account_id, media_id, **kw):
        res = await real(account_id, media_id, **kw)
        if await vault_ai_vision._kind(account_id, media_id) != "photo":
            return res
        q = await vault_ai_vision._flags_one(account_id, media_id)
        return {**res, "cost_millicents": int(res.get("cost_millicents") or 0) + int(q.get("cost_millicents") or 0)}

    vault_ai_vision._jev_and_flag = _jev_and_flag


def _photo_v2_fallback() -> None:
    """A photo with no Jev reading falls back to the V2 describe instead of being skipped: `route` answers v2 where
    it said skip (JEV_PHOTO_NEVER_V2)."""
    import vault_describe_jev

    real = vault_describe_jev.route

    def route(*, kind, fields):
        path, jev = real(kind=kind, fields=fields)
        return (vault_describe_jev.V2, None) if path is None and kind == "photo" else (path, jev)

    vault_describe_jev.route = route


def _no_settle() -> None:
    """settle nn.10 blind to NudeNet: a review photo NudeNet sees nothing on settles into a paid lane instead of free
    (JEV_LANES). Still settled, so flags / describe keep reading it (skipping settle outright would leave `review`,
    which no reading maps, and turn the flags + describe checks red with it)."""
    import vault_jev_rules

    real = vault_jev_rules.settle

    def settle(d, mode=vault_jev_rules.SETTLE_MODE):
        had, nn = "nn" in d, d.pop("nn", None)
        real(d, mode)
        if had:
            d["nn"] = nn

    vault_jev_rules.settle = settle


def _describe_ignores_review() -> None:
    """The Jev-fed describe ignores the review lane: `vault_describe_jev.review_lane` (looked up by bare name inside
    `route`) always False, so a review photo gets the prose recipe (JEV_DESCRIBE_REVIEW)."""
    import vault_describe_jev

    vault_describe_jev.review_lane = lambda jev: False


def register(Fault) -> dict:
    return {
        # slop/run vault-jev-flags --break (the scenario's FAULT)
        "photo-still-calls-qwen-flags": Fault(_photo_qwen_flags, (JEV_PHOTO_NO_QWEN_FLAGS,)),
        # slop/run vault-jev-flags --break --fault=photo-describe-falls-back-to-v2
        "photo-describe-falls-back-to-v2": Fault(_photo_v2_fallback, (JEV_PHOTO_NEVER_V2,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-no-settle
        "vault-jev-no-settle": Fault(_no_settle, (JEV_LANES,)),
        # slop/run vault-jev-flags --break --fault=vault-jev-describe-ignores-review
        "vault-jev-describe-ignores-review": Fault(_describe_ignores_review, (JEV_DESCRIBE_REVIEW,)),
    }
