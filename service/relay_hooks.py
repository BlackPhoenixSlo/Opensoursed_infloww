"""Product extension callbacks for relay events and chat mutations.

Outbound fires on every successful send path (manual, scheduled, automation);
inbound fires before SSE fan-out; thread head fires after a head-page read;
failed send fires on any HTTPException from the manual send route, which the
hook classifies; mute fires only after the platform accepts the change. Hooks
run synchronously on the event loop without I/O and must not raise.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from fastapi import HTTPException

outbound_sent: list[Callable[[str, int, int, datetime], None]] = []
inbound_message: list[Callable[[str | None, str | None, dict], None]] = []
thread_head: list[Callable[[str, int, Any], None]] = []
send_failed: list[Callable[[str, int, HTTPException], None]] = []
mute: list[Callable[[int, bool], None]] = []

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
