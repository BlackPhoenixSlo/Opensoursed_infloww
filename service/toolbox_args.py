"""service/toolbox_args.py — the Toolbox args base, a leaf: toolbox_decide (reads) and toolbox_writes import it."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

CREATOR = "The Creator's id (an id from creators_list)."


class Args(BaseModel):
    """Base of every tool's args: unknown keys are refused, never dropped."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
