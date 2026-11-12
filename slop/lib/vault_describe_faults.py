"""The vault describe sweep's break-it-once faults (scenarios/2026-11-01-vault-describe-sweep.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can
never name a check that does not exist. Each patches a product function's module attribute in the relay, one the
product looks up per call (`vault_ai_vision._claim_describe` by bare global name, `vault_ai_vision_decide
.with_jev` by module attribute), so the patch bites on the next press.

`vault-describe-cost-last-attempt` is the harness's only fault that rewrites a product function's SOURCE: it takes
`inspect.getsource(vault_ai_vision._describe_one)`, swaps the one `cost +=` line (refusing to arm unless it is there
exactly once, so a product edit fails loudly instead of silently injecting nothing) and `exec`s it in the module's
own namespace. The bug lives mid-function, so wrapping the function or patching a callee cannot reproduce it.
"""
from __future__ import annotations

EXACTLY_ONCE = ("describe sweep: every undescribed photo/clip got exactly one answer that described it, and its row "
                "holds that answer (blank ones end 'refused', nothing written); a photo one Jev call first and the "
                "Jev-fed prose recipe")
PLAN = ("describe sweep: the plan's undescribed count == the items the sweep called the model for plus the "
        "re-uploads it copied == its progress total (pass 1: == the seeded undescribed count)")
CACHE = ("describe sweep: no model call for a row already described (the seeded cache rows in pass 1, every row "
         "described by pass 1 in pass 2), their descriptions kept; pass 2 retries exactly the blank ones")
ESCALATE = ("describe sweep: a refusal or blank answer escalates to qwen3-vl-235b exactly once, an answered item "
            "never")
COST = ("describe sweep: the cost flags-all and describe-all pass 2 report == the fakes' billed sum for the "
        "sweep's own calls, DeepInfra's plus TypeSafe Jev's (pass 2: its describe calls plus any auto-flags, none for "
        "its blank retries; flags-all: its flags calls and Jev calls)")
COST_INCL_FLAGS = ("describe sweep: the cost describe-all reports includes the flags calls it makes after each "
                   "described clip (pass 1: reported == describe + Jev + auto-flags billed)")
FLAGS = ("flags-all: every live photo/clip flagged (4 qwen calls per clip, none per photo: one Jev call for each photo "
         "pass 1 left without `_jev`, none for the rest, `_flags_model` jev; a planted re-upload copied from its set "
         "instead: none), no description, tags, describe status or non-flag ai_fields_json key rewritten (a photo's "
         "Jev lane fields aside), the flags answer's description/tags stored nowhere")
REUSE = ("duplicate reuse: the Duplicates route's sets at threshold 2 == the planted re-upload sets; pass 1 called the "
         "model for the undescribed minus the planted copies, and each copy ends described with `_copied_from` a "
         "member of its set and that member's description and flags (a photo set with a cached member pays one: a "
         "pre-Jev describe is never a photo's source); flags: one paid member per set (a photo set's Jev, over pass 1 "
         "and flags-all), the rest copy it (clips `_flags_copied_from` with its flags, photos its `_jev` with a mark)")
ONE_SWEEP = "describe-all pressed by several owners at once: one sweep per Creator (one 200, the rest 409)"
UI_SETTLED = ("UI: Vault Pro's 'Describe all (N)' shows the plan's count, the click starts the sweep and the button "
              "settles on the plan's count after it; the Creator's rows are described in the DB")


def _ignores_cache() -> None:
    """The 'undescribed' sweep blind to `describe_status`: every live row is picked, described ones included (the
    plan counts with the same clause, so plan and sweep still agree with each other, but no longer with the seeded
    undescribed count: PLAN)."""
    import vault_ai_vision
    import vault_ai_vision_decide as d

    real = d.describe_selection

    def selection(account_id, mode, pv):
        return d.live_describable(account_id) if mode == "undescribed" else real(account_id, mode, pv)

    d.describe_selection = selection
    vault_ai_vision.describe_selection = selection  # imported by name: the sweep and the plan read this one


def _cost_last_attempt() -> None:
    """The pre-W9 cost: `_describe_one` reports only the LAST attempt's cost, so a refused 30b call before a 235b
    answer goes unreported (its own source with `cost +=` -> `cost =`, compiled in its module)."""
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
    """The pre-fix start: check `_describe_running`, AWAIT the budget, only then claim it. Concurrent presses all
    pass the check while the first awaits, so each starts a sweep (ONE_SWEEP). Same 400 / 409 / 424 / 429 bodies;
    this copy must track vault_ai_vision._claim_describe."""
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
    """Describe-and-flag reports describe's cost alone, the Jev flags pass's dropped (COST_INCL_FLAGS; the qwen
    flags call it once dropped is gone, D52/D54)."""
    import vault_ai_vision_decide as d

    d.with_jev = lambda describe_res, jev_res: dict(describe_res)


def _no_reuse() -> None:
    """Duplicate reuse off: `reuse_groups` (looked up per sweep as `vault_dupes.reuse_groups`) finds no set, so
    every re-upload pays its own calls (REUSE)."""
    import vault_dupes

    async def none(_account_id, _want):
        return []

    vault_dupes.reuse_groups = none


def register(Fault) -> dict:
    return {
        # slop/run vault-describe-sweep --break (the scenario's FAULT)
        # REUSE too: its per-Creator call count (the undescribed minus the planted copies) gains the cached rows.
        "vault-describe-ignores-cache": Fault(_ignores_cache, (CACHE, PLAN, REUSE)),
        # slop/run vault-describe-sweep --break --fault=vault-describe-cost-last-attempt
        # Pass 1's one total is describe + flags, so the describe under-report reds COST_INCL_FLAGS too.
        "vault-describe-cost-last-attempt": Fault(_cost_last_attempt, (COST, COST_INCL_FLAGS)),
        # slop/run vault-describe-sweep --break --fault=vault-describe-claim-after-budget
        "vault-describe-claim-after-budget": Fault(_claim_after_budget, (ONE_SWEEP,)),
        # slop/run vault-describe-sweep --break --fault=vault-describe-drops-flags-cost
        "vault-describe-drops-flags-cost": Fault(_drops_flags_cost, (COST_INCL_FLAGS,)),
        # slop/run vault-describe-sweep --break --fault=vault-describe-no-reuse
        "vault-describe-no-reuse": Fault(_no_reuse, (REUSE,)),
    }
