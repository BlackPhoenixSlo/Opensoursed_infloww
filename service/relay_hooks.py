"""Product extension callbacks for relay events and chat mutations.

How a private feature plugs in (shared code never names or imports one; a
public checkout without the feature simply has nothing registered):
  - `service/<name>_wiring.py`: imported by `import_wirings()` at server.py's
    wiring point; at import it appends to the lists below, then `wire(app)`
    binds its routes there (route precedence kept). `wire` only binds
    routes and must be safe to run twice (test_route_order probes it).
  - The lists below: event hooks, background loops, blast scrape gates, fan row
    fields and other feature words.
  - `automations/_funnel_walkers.register_walker`: a mass run kind's funnel walker.
  - `service/db/<name>_models.py`: more tables on `Base` (db/models.py loads them).
  - App: `app/plugins/<name>/register.ts` (data) and `ui.ts` (components), read
    through generated barrels by app/lib/chatSlots.ts and chatUiSlots.ts.

Outbound fires on every successful send path (manual, scheduled, automation);
inbound fires before SSE fan-out; thread head fires after a head-page read;
failed send fires on any HTTPException from the manual send route, which the
hook classifies; mute fires only after the platform accepts the change; socket
reconnected fires when an account's OF socket is open again after a drop (events
sent meanwhile are lost). Hooks
run synchronously on the event loop without I/O and must not raise.

Background loops are starters, not event hooks: server.py's event-pump startup
calls each once (not in test mode) to spawn its task; one that raises fails
startup, as the inline starts beside it do.

Blast scrape gates are async predicates, not event hooks: webhook_dispatch asks
them `(session, account_id)` before the after-blast one-fan scrape; any True
allows it, none registered means no scrape. They may read the DB through the
session they are given; one that raises is handled (fail closed) by the caller.

Fan row fields: each `(fan) -> dict` is merged last into every fan row fans.py
serves. Other feature words: whole words naming another feature, which veto the
help bot's mass draft when the request has no mass word (assistant_draft).
"""
from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from fastapi import HTTPException

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models import Fan

outbound_sent: list[Callable[[str, int, int, datetime], None]] = []
inbound_message: list[Callable[[str | None, str | None, dict], None]] = []
thread_head: list[Callable[[str, int, Any], None]] = []
send_failed: list[Callable[[str, int, HTTPException], None]] = []
mute: list[Callable[[int, bool], None]] = []
socket_reconnected: list[Callable[[str], None]] = []
background_loops: list[Callable[[], None]] = []
blast_scrape_gates: list[Callable[["AsyncSession", str], Awaitable[bool]]] = []
fan_row_fields: list[Callable[["Fan"], dict[str, Any]]] = []
other_feature_words: list[str] = []


def import_wirings() -> list[ModuleType]:
    """Import every `*_wiring.py` beside this module (sorted), which registers
    its hooks; returns the modules (server.py then calls each one's `wire`)."""
    return [importlib.import_module(p.stem) for p in sorted(Path(__file__).parent.glob("*_wiring.py"))]


def fire_outbound_sent(account_id: str, fan_id: int, message_id: int, created_at: datetime) -> None:
    for hook in outbound_sent:
        hook(account_id, fan_id, message_id, created_at)


def fire_inbound_message(account_id: str | None, event_type: str | None, event: dict) -> None:
    for hook in inbound_message:
        hook(account_id, event_type, event)


def fire_thread_head(account_id: str, chat_id: int, messages: Any) -> None:
    for hook in thread_head:
        hook(account_id, chat_id, messages)


def fire_send_failed(account_id: str, chat_id: int, exc: HTTPException) -> None:
    for hook in send_failed:
        hook(account_id, chat_id, exc)


def fire_mute(chat_id: int, muted: bool) -> None:
    for hook in mute:
        hook(chat_id, muted)


def fire_socket_reconnected(account_id: str) -> None:
    for hook in socket_reconnected:
        hook(account_id)


def start_background_loops() -> None:
    for start in background_loops:
        start()
