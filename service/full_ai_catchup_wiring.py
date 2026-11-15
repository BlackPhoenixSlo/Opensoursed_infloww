"""Relay start: every Creator already in Full AI Chat's Live Mode starts its waiting-chats catch-up
(`automations.full_ai_catchup.boot`: a pass after `BOOT_DELAY_S`, then +5, +15, every 25 min (config catchup_minutes)). A background loop
starter (relay_hooks): server.py's event-pump startup calls it once, never in test mode.
"""
from __future__ import annotations

from fastapi import FastAPI

import relay_hooks


def _start() -> None:
    import relay_host
    from automations import full_ai_catchup   # lazy: the automations import widely
    relay_host.spawn_bg(full_ai_catchup.boot(), "full-ai-catchup-boot")


relay_hooks.background_loops.append(_start)


def wire(app: FastAPI) -> None:
    """Nothing to route; the starter is registered at import."""
