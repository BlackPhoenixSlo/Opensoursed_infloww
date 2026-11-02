"""The vault describe sweep's break-it-once faults (scenarios/2026-11-01-vault-describe-sweep.py): lib/faults.py
merges `register(Fault)` into FAULTS. The check names live here and the scenario imports them, so a target can
never name a check that does not exist. Each patches a product function's module attribute in the relay. No fault
targets a check the scenario lists in KNOWN_RED (ONE_SWEEP, COST_INCL_FLAGS): those SKIP, so they can never go red.

`vault-describe-cost-last-attempt` is the harness's only fault that rewrites a product function's SOURCE: it takes
`inspect.getsource(vault_ai_vision._describe_one)`, swaps the one `cost +=` line (refusing to arm unless it is there
exactly once, so a product edit fails loudly instead of silently injecting nothing) and `exec`s it in the module's
own namespace. The bug lives mid-function, so wrapping the function or patching a callee cannot reproduce it.
"""
from __future__ import annotations

EXACTLY_ONCE = ("describe sweep: every undescribed photo/clip got exactly one answer that described it, and its row "
                "holds that answer (blank ones end 'refused', nothing written)")
PLAN = ("describe sweep: the plan's undescribed count == the items the sweep called the model for == its progress "
        "total (pass 1: == the seeded undescribed count)")
CACHE = ("describe sweep: no model call for a row already described (the seeded cache rows in pass 1, every row "
         "described by pass 1 in pass 2), their descriptions kept; pass 2 retries exactly the blank ones")
ESCALATE = ("describe sweep: a refusal or blank answer escalates to qwen3-vl-235b exactly once, an answered item "
            "never")
COST = ("describe sweep: the cost each sweep reports == the fake DeepInfra's billed sum for the sweep's own calls "
        "(describe-all both passes: its describe calls; flags-all: its flags calls)")
COST_INCL_FLAGS = ("describe sweep: the cost describe-all reports includes the flags calls it makes after each "
                   "described item (pass 1: reported == describe + auto-flags billed; pass 2 describes no row, "
                   "so flags none)")
FLAGS = ("flags-all: every live photo/clip flagged (one call per photo, 4 per clip), no description, tags, describe "
         "status or non-flag ai_fields_json key rewritten, the flags answer's description/tags stored nowhere")
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


def register(Fault) -> dict:
    return {
        # slop/run vault-describe-sweep --break (the scenario's FAULT)
        "vault-describe-ignores-cache": Fault(_ignores_cache, (CACHE, PLAN)),
        # slop/run vault-describe-sweep --break --fault=vault-describe-cost-last-attempt
        "vault-describe-cost-last-attempt": Fault(_cost_last_attempt, (COST,)),
    }
