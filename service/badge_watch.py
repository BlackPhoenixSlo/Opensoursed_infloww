"""Un-peeked thread reads vs counter drops (creator-badges phase 0D, ADR-0050's cost): `of_reads.get_messages` notes
each first-page thread GET sent with no cursor (it marks the chat read on OF) under any Caller kind but the Messages
Pro thread route's (a Click read is meant to mark read); the counter-frame lane calls `on_drop` on every drop and one
`badge_unpeeked_drop` line is logged when it lands <= WINDOW_S after such a read. Correlated here, logged on a hit
only, so the log does not carry every frame."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

import of_call_counter

log = logging.getLogger("of-relay.badge_watch")

WINDOW_S = 2.0
KEEP = 8
THREAD_ROUTE = of_call_counter.fold_caller("route:" + of_call_counter.path_key("GET", "/api/of/v2/chats/0/messages"))

_mono = time.monotonic
_lock = threading.Lock()
_slots: dict[str, deque] = {}   # Creator -> its newest KEEP un-peeked reads, (chat, Caller kind, monotonic s)


def note_unpeeked(account_id, chat_id) -> None:
    kind = of_call_counter.caller_kind()
    if account_id is None or kind == THREAD_ROUTE:
        return
    entry = (str(chat_id), kind, _mono())
    with _lock:
        _slots.setdefault(str(account_id), deque(maxlen=KEEP)).append(entry)


def on_drop(account_id: str) -> None:
    now = _mono()
    with _lock:
        entries = list(_slots.get(str(account_id), ()))
    for chat, kind, t in reversed(entries):
        if 0 <= now - t <= WINDOW_S:
            log.info("badge_unpeeked_drop account=%s chat=%s caller=%s gap_ms=%d", account_id, chat, kind,
                     round((now - t) * 1000))
            return
