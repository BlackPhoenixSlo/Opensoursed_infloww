from __future__ import annotations

from typing import Any

from pydantic import Field

import toolbox_decide as td
import toolbox_sends as ts
from toolbox_args import Args

MAX_STEPS = 20
MAX_SUMMARY = 500
MAX_QUESTION = 500
MAX_PICK = ts.MAX_MEDIA
TOOL_KEYS = frozenset({"id", "tool", "args"})


class PlanStep(Args):
    id: str = Field(description="Step id: 1-32 of a-z 0-9 _, starting with a letter; unique in the plan.")
    tool: str | None = Field(None, description="A tool name (none on a judge step).")
    args: dict[str, Any] = Field(default_factory=dict, description="The tool's args (none on a judge step).")
    question: str | None = Field(None, max_length=MAX_QUESTION, description="Judge step: what to pick.")
    candidates: str | list[str] | None = Field(None, description="Judge step: \"$<vault_search step id>"
                                                                 ".data_only.list\", or a list of them.")
    pick_n: int | None = Field(None, ge=1, le=MAX_PICK, description="Judge step: how many to pick.")
    confirm: bool | None = Field(None, description="Judge step: the owner confirms the picks before the run "
                                                   "goes on.")


class PlanArgs(Args):
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY, description="One line: what the plan does.")
    steps: list[PlanStep] = Field(min_length=1, max_length=MAX_STEPS, description="The steps, run in order.")


JUDGE_KEYS = frozenset(PlanStep.model_fields) - (TOOL_KEYS - {"id"})


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return _inline({**defs[ref.removeprefix("#/$defs/")], **{k: v for k, v in node.items() if k != "$ref"}},
                           defs)
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(x, defs) for x in node]
    return node


def parameters() -> dict[str, Any]:
    schema = td.args_schema(PlanArgs)
    return _inline({k: v for k, v in schema.items() if k != "$defs"}, schema.get("$defs", {}))
