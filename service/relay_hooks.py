# Hooks run synchronously on the event loop without I/O and must not raise; `wire` must be safe to run twice (test_route_order probes it).
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
# A Click read: a plain (not peeked) head read or a landed single-chat mark-as-read.
thread_click_read: list[Callable[[str, int, int], None]] = []
send_failed: list[Callable[[str, int, HTTPException], None]] = []
mute: list[Callable[[str, int, bool], None]] = []
socket_reconnected: list[Callable[[str], None]] = []
background_loops: list[Callable[[], None]] = []
blast_scrape_gates: list[Callable[["AsyncSession", str], Awaitable[bool]]] = []
fan_row_fields: list[Callable[["Fan"], dict[str, Any]]] = []
other_feature_words: list[str] = []


def import_wirings() -> list[ModuleType]:
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


def fire_thread_click_read(account_id: str, chat_id: int, at: int) -> None:
    for hook in thread_click_read:
        hook(account_id, chat_id, at)


def fire_send_failed(account_id: str, chat_id: int, exc: HTTPException) -> None:
    for hook in send_failed:
        hook(account_id, chat_id, exc)


def fire_mute(chat_id: int, muted: bool, *, account_id: str) -> None:
    for hook in mute:
        hook(account_id, chat_id, muted)


def fire_socket_reconnected(account_id: str) -> None:
    for hook in socket_reconnected:
        hook(account_id)


def start_background_loops() -> None:
    for start in background_loops:
        start()
