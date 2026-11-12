"""A deferred chat's head read starts its history backfill (phase-03).

The thread_head hook is registered once at import; it is sync and does no
I/O: it only spawns webhook_dispatch.backfill_if_deferred in the background,
so the messages route answers as fast as without it. Any priority counts: an
open reusing a warm page sends no head read of its own.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

import relay_host
import relay_hooks

log = logging.getLogger("of-relay.events")


def _on_thread_head(account_id: str, chat_id: int, messages: Any) -> None:
    coro = None
    try:
        import webhook_dispatch   # lazy: it pulls in the executor
        coro = webhook_dispatch.backfill_if_deferred(str(account_id), int(chat_id))
        relay_host.spawn_bg(coro, "deferred-history")
    except Exception:
        if coro is not None:
            coro.close()
        log.warning("deferred_history_hook_failed account=%s chat=%s",
                    account_id, chat_id, exc_info=True)


relay_hooks.thread_head.append(_on_thread_head)


def wire(app: FastAPI) -> None:
    """Nothing to route; the hook is registered at import."""
