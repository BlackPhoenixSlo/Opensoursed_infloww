"""service/login_throttle.py — the sign-in throttle (roadmap S14, 07 M6).

Three token buckets per attempt, process-local (the relay runs one uvicorn
worker): one per username from one client IP, NAME_CAPACITY tries refilling one
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
"""

from __future__ import annotations

import ipaddress
import logging
import math
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

import client_addr

NAME_CAPACITY = 5
NAME_REFILL_S = 60.0
USER_CAPACITY = 30
USER_REFILL_S = 20.0  # 30 per 10 minutes
IP_CAPACITY = 20
IP_REFILL_S = 30.0
# Above this many tracked keys, full buckets (nothing to remember) are dropped.
_PRUNE_AT = 10_000

log = logging.getLogger("of-relay.login_throttle")
_clock = time.monotonic
# key -> (tokens, last refill time)
_buckets: dict[tuple[str, ...], tuple[float, float]] = {}


def _limits(key: tuple[str, ...]) -> tuple[int, float]:
    return {"name": (NAME_CAPACITY, NAME_REFILL_S), "user": (USER_CAPACITY, USER_REFILL_S)}.get(
        key[0], (IP_CAPACITY, IP_REFILL_S))


def _level(key: tuple[str, ...], now: float) -> float:
    cap, refill = _limits(key)
    tokens, at = _buckets.get(key, (float(cap), now))
    return min(float(cap), tokens + (now - at) / refill)


def _bucket_key(ip: client_addr.Addr | str) -> str:
    """An IPv4 client by its address, an IPv6 one by its /64 (one host's usual share); a peer that is no address
    by its string."""
    if isinstance(ip, str):
        return ip
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


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
            cap, _ = _limits(key)
            _buckets[key] = (min(float(cap), _level(key, now) + 1), now)

    def succeeded(self) -> None:
        """Signed in: refund, and the username starts over with a full bucket
        from this IP. The per-username bucket keeps its level, so the owner
        signing in hands a guesser elsewhere no fresh tries."""
        self.refund()
        for key in self.keys:
            if key[0] == "name":
                _buckets.pop(key, None)


def take(request: Request, username: str) -> Attempt:
    """Take one token per bucket for this sign-in attempt, or 429."""
    now = _clock()
    # The socket peer, the address our proxy wrote in X-Forwarded-For, or the
    # CDN's CF-Connecting-IP (EDGE_PROXIES); see client_addr.
    addr = client_addr.client_address(request)
    ip = _bucket_key(addr)
    keys = (("name", username, ip), ("user", username), ("ip", ip))
    levels = [_level(k, now) for k in keys]
    short = [(k, lv) for k, lv in zip(keys, levels) if lv < 1]
    if short:
        wait = max(math.ceil((1 - lv) * _limits(k)[1]) for k, lv in short)
        log.warning("sign-in throttled addr=%s key=%s buckets=%s retry_after=%ss", addr, ip,
                    ",".join(k[0] for k, _ in short), wait)
        raise HTTPException(
            status_code=429,
            detail={
                "code": "too_many_attempts",
                "message": f"Too many sign-in attempts. Try again in {_wait_words(wait)}.",
                "retry_after": wait,
            },
            headers={"Retry-After": str(wait)},
        )
    for key, level in zip(keys, levels):
        _buckets[key] = (level - 1, now)
    if len(_buckets) > _PRUNE_AT:
        for key in [k for k in _buckets if _level(k, now) >= _limits(k)[0]]:
            del _buckets[key]
    return Attempt(keys)


def _wait_words(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = math.ceil(seconds / 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


def reset() -> None:
    """Forget every bucket (tests)."""
    _buckets.clear()
