from __future__ import annotations

from typing import Any, Awaitable

import llm_client
import run_slot

from . import rhythm


# No OF call and no lock held while the model call waits off the run slot.
def freed_chat(*, budget_s: float, **chat_kw: Any) -> Awaitable[Any]:
    return run_slot.freed(llm_client.chat(
        **chat_kw, timeout_s=rhythm.MODEL_WAIT_S, max_attempts=rhythm.MODEL_TRIES), budget_s=budget_s)
