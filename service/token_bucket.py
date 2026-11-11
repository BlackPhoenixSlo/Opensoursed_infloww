"""service/token_bucket.py — the one token-bucket store behind the relay's
per-client throttles (login_throttle's sign-in buckets, tracking_links_api's
public verify budget).

Process-local (the relay runs one uvicorn worker). A bucket holds `capacity`
tokens and refills one per `refill_s`; a key never seen is full. A drained
bucket is NEVER forgotten: forgetting it would hand its key a fresh bucket, so
a guesser could drain a username and then flood other keys to reset it. Past
`max_keys` (a soft cap) the store drops, oldest write first, only buckets that
have refilled by now (nothing left to remember); it stops at the first one
that has not, and grows instead. Each key is dropped at most once per write,
so this is O(1) amortised with no scan, and the store holds at most the keys
written within one full-refill window. Never fails closed.
"""
from __future__ import annotations

import ipaddress
import math
from collections import OrderedDict
from collections.abc import Hashable

import client_addr


def bucket_key(addr: client_addr.Addr | str) -> str:
    """An IPv4 client by its address, an IPv6 one by its /64 (one host's usual
    share); a peer that is no address by its string."""
    if isinstance(addr, str):
        return addr
    return str(ipaddress.ip_network(f"{addr}/64", strict=False)) if addr.version == 6 else str(addr)


def wait_s(level: float, refill_s: float) -> int:
    """Whole seconds until a bucket at `level` (< 1) holds one token."""
    return math.ceil((1 - level) * refill_s)


class Buckets:
    def __init__(self, max_keys: int) -> None:
        self.max_keys = max_keys
        # key -> (tokens, at, full_at); ordered by last write, oldest first
        self._store: OrderedDict[Hashable, tuple[float, float, float]] = OrderedDict()

    def level(self, key: Hashable, capacity: int, refill_s: float, now: float) -> float:
        tokens, at, _ = self._store.get(key, (float(capacity), now, now))
        return min(float(capacity), tokens + (now - at) / refill_s)

    def put(self, key: Hashable, tokens: float, now: float, capacity: int, refill_s: float) -> None:
        self._store[key] = (tokens, now, now + (capacity - tokens) * refill_s)
        self._store.move_to_end(key)
        while len(self._store) > self.max_keys:
            head = next(iter(self._store))
            if self._store[head][2] > now:
                break   # not refilled: keep it, grow past the soft cap
            del self._store[head]

    def pop(self, key: Hashable) -> None:
        self._store.pop(key, None)

    def take(self, key: Hashable, capacity: int, refill_s: float, now: float) -> int | None:
        """One token from `key`'s bucket: None, or the seconds until one is back."""
        level = self.level(key, capacity, refill_s, now)
        if level < 1:
            return wait_s(level, refill_s)
        self.put(key, level - 1, now, capacity, refill_s)
        return None

    def reset(self) -> None:
        """Forget every bucket (tests)."""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
