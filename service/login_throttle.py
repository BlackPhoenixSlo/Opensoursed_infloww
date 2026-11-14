"""service/login_throttle.py — the sign-in throttle (roadmap S14, 07 M6).

Three token buckets per attempt, process-local (token_bucket.Buckets; the relay
runs one uvicorn worker): one per username from one client IP, NAME_CAPACITY tries refilling one
per NAME_REFILL_S; one per username from anywhere, USER_CAPACITY refilling one
per USER_REFILL_S; and one per client IP, IP_CAPACITY refilling one per
IP_REFILL_S (an IPv6 client counts by its /64). The tight bucket is per IP, so
a stranger's few wrong guesses never lock the owner out of their own sign-in;
the loose one caps a guesser who rotates addresses (or forges X-Forwarded-For,
see client_addr) at about 30 guesses per 10 minutes per account, at the price
that such a guesser can lock that account out for everyone while he keeps at
it. `take()` runs
before any DB read and takes a token from each at once (no await in between, so
concurrent requests cannot share one token); an empty bucket is a 429 with
Retry-After. One token per submit: the sign-in form's /auth/sign-in checks
owners and employees under that one token (account_security.password_sign_in),
so neither a 401 nor a 429 tells which usernames are owners. The route gives
the token back when the attempt was not a guess, i.e. the password was right
(`Attempt.refund`), and refills the username's bucket once the sign-in is
complete (`Attempt.succeeded`), never on a right password alone, so passing the
password again buys no extra 2FA guesses.

One username key for both principals, and the 2FA code step uses it too.

Sign-up (`take_register`, POST /auth/register, also MCP register_account's in-process call as
the caller's address): one bucket per client IP, REGISTER_CAPACITY refilling one per
REGISTER_REFILL_S, taken once the username and password are valid. It bounds new owner rows and
"username already taken" probing from one address.
"""

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
USER_CAPACITY = 30
USER_REFILL_S = 20.0  # 30 per 10 minutes
IP_CAPACITY = 20
IP_REFILL_S = 30.0
REGISTER_CAPACITY = 20  # a slop world registers up to 10 Agencies from one address; 2x headroom
REGISTER_REFILL_S = 180.0  # 20 per hour
# Soft cap on tracked keys (token_bucket): past it only refilled buckets are
# dropped, so a drained username or IP bucket is never forgotten however many
# other keys a guesser writes; the store grows instead.
_MAX_KEYS = 100_000

log = logging.getLogger("of-relay.login_throttle")
_clock = time.monotonic
_buckets = Buckets(_MAX_KEYS)


def _limits(key: tuple[str, ...]) -> tuple[int, float]:
    return {"name": (NAME_CAPACITY, NAME_REFILL_S), "user": (USER_CAPACITY, USER_REFILL_S),
            "register": (REGISTER_CAPACITY, REGISTER_REFILL_S)}.get(key[0], (IP_CAPACITY, IP_REFILL_S))


def _level(key: tuple[str, ...], now: float) -> float:
    return _buckets.level(key, *_limits(key), now)


@dataclass
class Attempt:
    keys: tuple[tuple[str, ...], ...]
    _settled: bool = False

    def refund(self) -> None:
        """Not a guess: give this attempt's tokens back."""
        if self._settled:
            return
        self._settled = True
        now = _clock()
        for key in self.keys:
            cap, refill = _limits(key)
            _buckets.put(key, min(float(cap), _level(key, now) + 1), now, cap, refill)

    def succeeded(self) -> None:
        """Signed in: refund, and the username starts over with a full bucket
        from this IP. The per-username bucket keeps its level, so the owner
        signing in hands a guesser elsewhere no fresh tries."""
        self.refund()
        for key in self.keys:
            if key[0] == "name":
                _buckets.pop(key)


def take(request: Request, username: str) -> Attempt:
    """Take one token per bucket for this sign-in attempt, or 429."""
    now = _clock()
    # The socket peer, the address our proxy wrote in X-Forwarded-For, or the
    # CDN's CF-Connecting-IP (EDGE_PROXIES); see client_addr.
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
    """One sign-up token for this client address, or 429."""
    addr = client_addr.client_address(request)
    key = ("register", bucket_key(addr))
    wait = _buckets.take(key, *_limits(key), _clock())
    if wait is not None:
        log.warning("sign-up throttled addr=%s key=%s retry_after=%ss", addr, key[1], wait)
        raise _too_many("Too many sign-ups from this address.", wait)


def _too_many(what: str, wait: int) -> HTTPException:
    """The 429 both throttles answer (the app and MCP read `code` / `retry_after`)."""
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
    """Forget every bucket (tests)."""
    _buckets.reset()
