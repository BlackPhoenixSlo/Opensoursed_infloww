"""automations/_model_wait.py — a sender's model call, off the run slot.

`freed_chat(budget_s=..., **chat_kw)`: `llm_client.chat(**chat_kw)` with the senders' wait
(`rhythm.MODEL_WAIT_S` a try, `rhythm.MODEL_TRIES` tries) awaited off the run slot (`run_slot.freed`,
taken back within `budget_s`; no OF call, no lock held meanwhile). Each caller passes its own
module-level `INLINE_MAX_S` as `budget_s` and keeps its own error handling (`run_slot.SlotLost`, the
LLM cap, provider errors). `llm_client.chat` and `run_slot.freed` are looked up at call time, so a
test's patch of either still bites.
"""
from __future__ import annotations

from typing import Any, Awaitable

import llm_client
import run_slot

from . import rhythm


def freed_chat(*, budget_s: float, **chat_kw: Any) -> Awaitable[Any]:
    """`llm_client.chat(**chat_kw, timeout_s=MODEL_WAIT_S, max_attempts=MODEL_TRIES)` off the run slot."""
    return run_slot.freed(llm_client.chat(
        **chat_kw, timeout_s=rhythm.MODEL_WAIT_S, max_attempts=rhythm.MODEL_TRIES), budget_s=budget_s)
