from __future__ import annotations

import logging
from fastapi import FastAPI

import relay_host
import relay_hooks

log = logging.getLogger("of-relay.events")


# Sync, no I/O: only spawns the backfill so the route answers as fast as without it.
def _on_click_read(account_id: str, chat_id: int, at: int) -> None:
    coro = None
    try:
        import webhook_dispatch  # lazy: it pulls in the executor
        coro = webhook_dispatch.backfill_if_deferred(str(account_id), int(chat_id), at)
        relay_host.spawn_bg(coro, "deferred-history")
    except Exception:
        if coro is not None:
            coro.close()
        log.warning("deferred_history_hook_failed account=%s chat=%s",
                    account_id, chat_id, exc_info=True)


relay_hooks.thread_click_read.append(_on_click_read)


def wire(app: FastAPI) -> None:
    """Nothing to route; the hook is registered at import."""
