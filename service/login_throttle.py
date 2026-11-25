from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

import client_addr
from token_bucket import Buckets, bucket_key, wait_s

NAME_CAPACITY = 5
NAME_REFILL_S = 60.0
# Tight bucket is per IP so a stranger's wrong guesses never lock the owner out; this loose per-username one caps a guesser rotating addresses (or forging X-Forwarded-For) at ~30 per 10 min, at the price of locking that account for everyone while he keeps at it.
USER_CAPACITY = 30
USER_REFILL_S = 20.0
IP_CAPACITY = 20
IP_REFILL_S = 30.0
REGISTER_CAPACITY = 20
REGISTER_REFILL_S = 180.0
# Past it only refilled buckets are dropped, so a drained username/IP bucket is never forgotten however many keys a guesser writes.
_MAX_KEYS = 100_000

log = logging.getLogger("of-relay.login_throttle")
_clock = time.monotonic
_buckets = Buckets(_MAX_KEYS)


def _limits(key: tuple[str, ...]) -> tuple[int, float]:
    return {"name": (NAME_CAPACITY, NAME_REFILL_S), "user": (USER_CAPACITY, USER_REFILL_S),
            "register": (REGISTER_CAPACITY, REGISTER_REFILL_S),
            "client_register": (REGISTER_CAPACITY, REGISTER_REFILL_S)}.get(key[0], (IP_CAPACITY, IP_REFILL_S))


def _level(key: tuple[str, ...], now: float) -> float:
    return _buckets.level(key, *_limits(key), now)


@dataclass
class Attempt:
    keys: tuple[tuple[str, ...], ...]
    _settled: bool = False

    def refund(self) -> None:
        if self._settled:
            return
        self._settled = True
        # No await between the buckets, so concurrent requests cannot share one token; one token per submit for owners and employees alike, so neither a 401 nor a 429 tells which usernames are owners.
        now = _clock()
        for key in self.keys:
            cap, refill = _limits(key)
            _buckets.put(key, min(float(cap), _level(key, now) + 1), now, cap, refill)

    def succeeded(self) -> None:
        # Refill the username's bucket only once sign-in is complete, never on a right password alone: else repeating the password buys extra 2FA guesses.
        self.refund()
        for key in self.keys:
            if key[0] == "name":
                _buckets.pop(key)


def take(request: Request, username: str) -> Attempt:
    now = _clock()
    addr = client_addr.client_address(request)
    ip = bucket_key(addr)
    keys = (("name", username, ip), ("user", username), ("ip", ip))
    levels = [_level(k, now) for k in keys]
    short = [(k, lv) for k, lv in zip(keys, levels) if lv < 1]
    if short:
        wait = max(wait_s(lv, _limits(k)[1]) for k, lv in short)
        log.warning("sign-in throttled addr=%s key=%s buckets=%s retry_after=%ss", addr, ip,
                    ",".join(k[0] for k, _ in short), wait)
        raise _too_many("Too many sign-in attempts.", wait)
    for key, level in zip(keys, levels):
        _buckets.put(key, level - 1, now, *_limits(key))
    return Attempt(keys)


def take_register(request: Request) -> None:
    addr = client_addr.client_address(request)
    key = ("register", bucket_key(addr))
    wait = _buckets.take(key, *_limits(key), _clock())
    if wait is not None:
        log.warning("sign-up throttled addr=%s key=%s retry_after=%ss", addr, key[1], wait)
        raise _too_many("Too many sign-ups from this address.", wait)


def take_client_register(request: Request) -> None:
    addr = client_addr.client_address(request)
    key = ("client_register", bucket_key(addr))
    wait = _buckets.take(key, *_limits(key), _clock())
    if wait is not None:
        log.warning("client registration throttled addr=%s key=%s retry_after=%ss", addr, key[1], wait)
        raise _too_many("Too many app registrations from this address.", wait)


def _too_many(what: str, wait: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={"code": "too_many_attempts", "message": f"{what} Try again in {_wait_words(wait)}.",
                "retry_after": wait},
        headers={"Retry-After": str(wait)},
    )


def _wait_words(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = math.ceil(seconds / 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def reset() -> None:
    _buckets.reset()
