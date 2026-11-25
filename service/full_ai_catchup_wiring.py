from __future__ import annotations

from fastapi import FastAPI

import relay_hooks


def _start() -> None:
    import relay_host
    from automations import full_ai_catchup
    relay_host.spawn_bg(full_ai_catchup.boot(), "full-ai-catchup-boot")


def _reconnected(account_id: str) -> None:
    from automations import full_ai_catchup
    full_ai_catchup.reconnected(account_id)


relay_hooks.background_loops.append(_start)
relay_hooks.socket_reconnected.append(_reconnected)


def wire(app: FastAPI) -> None:
    """Nothing to route; the starter is registered at import."""
