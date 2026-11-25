from __future__ import annotations

EXACTLY_ONCE = ("describe sweep: every undescribed photo/clip got exactly one answer that described it, and its row "
                "holds that answer (blank ones end 'refused', nothing written); its Jev pass first (a photo one call, "
                "a clip one per frame) and the Jev-fed recipe (prose / vid)")
PLAN = ("describe sweep: the plan's undescribed count == the items the sweep called the model for plus the "
        "re-uploads it copied == its progress total (pass 1: == the seeded undescribed count)")
CACHE = ("describe sweep: no model call for a row already described (the seeded cache rows in pass 1, every row "
         "described by pass 1 in pass 2), their descriptions kept; pass 2 retries exactly the blank ones")
ESCALATE = ("describe sweep: a refusal or blank answer escalates to qwen3-vl-235b exactly once, an answered item "
            "never")
COST = ("describe sweep: the cost flags-all and describe-all pass 2 report == the fakes' billed sum for the "
        "sweep's own calls, DeepInfra's plus TypeSafe Jev's (pass 2: its describe calls plus any auto-flags, none for "
        "its blank retries; flags-all: its flags calls and Jev calls)")
COST_INCL_FLAGS = ("describe sweep: the cost describe-all reports includes the Jev pass (the flags) it runs on "
                   "each item (pass 1: reported == describe + Jev billed, Jev > 0)")
FLAGS = ("flags-all: every live photo/clip flagged (no qwen flags call: a Jev pass for each item pass 1 left "
         "without `_jev`, none for the rest, `_flags_model` jev; a planted re-upload copied from its set instead: "
         "none), no description, tags, describe status or non-flag ai_fields_json key rewritten (a photo's "
         "Jev lane fields aside), the flags answer's description/tags stored nowhere")
REUSE = ("duplicate reuse: the Duplicates route's sets at threshold 2 == the planted re-upload sets; pass 1 called the "
         "model for the undescribed minus the planted copies, and each copy ends described with `_copied_from` a "
         "member of its set and that member's description and flags (a set with a cached member pays one: a pre-Jev "
         "describe is never a photo's or clip's source); flags: one Jev-paid member per set over pass 1 and "
         "flags-all, the rest copy its `_jev` with a mark")
ONE_SWEEP = "describe-all pressed by several owners at once: one sweep per Creator (one 200, the rest 409)"
UI_SETTLED = ("UI: Vault Pro's 'Describe all (N)' shows the plan's count, the click starts the sweep and the button "
              "settles on the plan's count after it; the Creator's rows are described in the DB")
TARGET = ("describe-all `target`: a press at a met target is zero work (status done, target_remaining 0, no model "
          "call, no sweep), before and after; a target K above the described count walks exactly K undescribed "
          "items (progress total K, each described) and walks past the Terminal ones (no call for a refused blank)")


def _ignores_cache() -> None:
    import vault_ai_vision
    import vault_ai_vision_decide as d

    real = d.describe_selection

    def selection(account_id, mode, pv):
        return d.live_describable(account_id) if mode == "undescribed" else real(account_id, mode, pv)

    d.describe_selection = selection
    vault_ai_vision.describe_selection = selection


def _cost_last_attempt() -> None:
    import __future__
    import inspect

    import vault_ai_vision

    src = inspect.getsource(vault_ai_vision._describe_one)
    old = "cost += int(result.cost_cents or 0)"
    if src.count(old) != 1:
        raise SystemExit(f"slop: vault-describe-cost-last-attempt: {old!r} found {src.count(old)}x in _describe_one")
    ns: dict = {}
    code = compile(src.replace(old, "cost = int(result.cost_cents or 0)"), vault_ai_vision.__file__, "exec",
                   flags=__future__.annotations.compiler_flag, dont_inherit=True)
    exec(code, vault_ai_vision.__dict__, ns)
    vault_ai_vision._describe_one = ns["_describe_one"]


def _claim_after_budget() -> None:
    import vault_ai_vision as v
    from fastapi import HTTPException

    async def claim(account_id, model):
        if account_id in v._describe_running:
            raise HTTPException(status_code=409, detail={"error": "describe_already_running"})
        v._assert_vision_model(model)
        budget = await v._vision_budget(account_id, model)
        if budget["key_missing"]:
            raise v._vision_key_missing()
        if budget["capped"]:
            raise HTTPException(status_code=429, detail={"error": "daily_cap_reached", **budget})
        v._describe_running.add(account_id)
        return budget

    v._claim_describe = claim


def _drops_flags_cost() -> None:
    import vault_ai_vision_decide as d

    d.with_jev = lambda describe_res, jev_res: dict(describe_res)


def _no_reuse() -> None:
    import vault_dupes

    async def none(_account_id, _want):
        return []

    vault_dupes.reuse_groups = none


def register(Fault) -> dict:
    return {
        "vault-describe-ignores-cache": Fault(_ignores_cache, (CACHE, PLAN, REUSE)),
        "vault-describe-cost-last-attempt": Fault(_cost_last_attempt, (COST, COST_INCL_FLAGS)),
        "vault-describe-claim-after-budget": Fault(_claim_after_budget, (ONE_SWEEP,)),
        "vault-describe-drops-flags-cost": Fault(_drops_flags_cost, (COST_INCL_FLAGS,)),
        "vault-describe-no-reuse": Fault(_no_reuse, (REUSE,)),
    }
