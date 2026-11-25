from __future__ import annotations

import ipaddress
import math
from collections import OrderedDict
from collections.abc import Hashable

import client_addr


def bucket_key(addr: client_addr.Addr | str) -> str:
    if isinstance(addr, str):
        return addr
    return str(ipaddress.ip_network(f"{addr}/64", strict=False)) if addr.version == 6 else str(addr)


def wait_s(level: float, refill_s: float) -> int:
    return math.ceil((1 - level) * refill_s)


# A drained bucket is never forgotten: dropping it would hand its key a fresh bucket, so a guesser could drain a username then flood other keys to reset it. Past max_keys only already-refilled buckets are dropped.
class Buckets:
    def __init__(self, max_keys: int) -> None:
        self.max_keys = max_keys
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
                break
            del self._store[head]

    def pop(self, key: Hashable) -> None:
        self._store.pop(key, None)

    def take(self, key: Hashable, capacity: int, refill_s: float, now: float) -> int | None:
        level = self.level(key, capacity, refill_s, now)
        if level < 1:
            return wait_s(level, refill_s)
        self.put(key, level - 1, now, capacity, refill_s)
        return None

    def reset(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
