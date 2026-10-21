"""service/login_throttle.py — the sign-in throttle (roadmap S14, 07 M6).

Three token buckets per attempt, process-local (the relay runs one uvicorn
worker): one per username from one client IP, NAME_CAPACITY tries refilling one
per NAME_REFILL_S; one per username from anywhere, USER_CAPACITY refilling one
per USER_REFILL_S; and one per client IP, IP_CAPACITY refilling one per
IP_REFILL_S (an IPv6 client counts by its /64). The tight bucket is per IP, so
a stranger's few wrong guesses never lock the owner out of their own sign-in;
the loose one caps a guesser who rotates addresses (or forges X-Forwarded-For,
see client_ip) at about 30 guesses per 10 minutes per account, at the price
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
import os
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

NAME_CAPACITY = 5
NAME_REFILL_S = 60.0
USER_CAPACITY = 30
USER_REFILL_S = 20.0  # 30 per 10 minutes
IP_CAPACITY = 20
IP_REFILL_S = 30.0
# Above this many tracked keys, full buckets (nothing to remember) are dropped.
_PRUNE_AT = 10_000
# The peers whose X-Forwarded-For is believed: IPs or CIDRs, comma-separated in
# env TRUSTED_PROXIES, which replaces the default. The default is loopback and
# the private ranges (RFC 1918, IPv6 unique-local and link-local), which hold
# every docker network, so the relay's proxies are trusted whatever their
# container names. Empty means the default: trusting no proxy would put every
# user in the proxy's one bucket.
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7,fe80::/10"


def _parse_trusted(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    out = []
    for entry in (raw.strip() or _DEFAULT_TRUSTED).split(","):
        if entry.strip():
            try:
                out.append(ipaddress.ip_network(entry.strip(), strict=False))
            except ValueError:
                raise ValueError(f"TRUSTED_PROXIES: {entry.strip()!r} is not an IP or CIDR") from None
    return tuple(out) or _parse_trusted(_DEFAULT_TRUSTED)


TRUSTED_PROXIES = _parse_trusted(os.environ.get("TRUSTED_PROXIES", ""))

log = logging.getLogger("of-relay.login_throttle")
_clock = time.monotonic
# key -> (tokens, last refill time)
_buckets: dict[tuple[str, ...], tuple[float, float]] = {}
_warned: set[str] = set()


def _limits(key: tuple[str, ...]) -> tuple[int, float]:
    return {"name": (NAME_CAPACITY, NAME_REFILL_S), "user": (USER_CAPACITY, USER_REFILL_S)}.get(
        key[0], (IP_CAPACITY, IP_REFILL_S))


def _level(key: tuple[str, ...], now: float) -> float:
    cap, refill = _limits(key)
    tokens, at = _buckets.get(key, (float(cap), now))
    return min(float(cap), tokens + (now - at) / refill)


def _ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """`raw` as an address (a :port and IPv4-mapped IPv6 unwrapped), else None."""
    if raw.startswith("[") and "]" in raw:
        raw = raw[1:raw.index("]")]
    elif raw.count(":") == 1:
        raw = raw.split(":")[0]
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return None
    return (ip.ipv4_mapped or ip) if ip.version == 6 else ip


def _bucket_key(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """An IPv4 client by its address, an IPv6 one by its /64 (one host's usual share)."""
    return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)


def _is_trusted_proxy(peer: str) -> bool:
    ip = _ip(peer)
    return ip is not None and any(ip in net for net in TRUSTED_PROXIES)


def client_ip(request: Request) -> str:
    """The sign-in's client IP (`_bucket_key`): the socket peer, or the LAST
    X-Forwarded-For entry when the peer is in TRUSTED_PROXIES and the entry
    parses as an address.

    The relay is reached through a proxy: the Next app (`/auth/*` and
    `/chatter/*` rewrites in next.config.ts, on the compose network) and,
    in prod, Traefik straight from the n8n_default network (the relay's
    Traefik labels in docker-compose.yml route /auth/ and /chatter/ to it).
    Next adds the browser's socket address only when the header is absent and
    never appends, and its rewrite passes the header on unchanged. Traefik (its
    untrusted clients' forwarded headers are dropped) sets the header to the
    client's address, and the cloudflared tunnel appends it after whatever the
    client sent. Either way the last entry is the one our proxy wrote. A peer
    outside TRUSTED_PROXIES (a public address reaching the relay directly) has
    its header ignored and is the client itself (warned once per peer).

    The remaining gap: the default trusts every private address, so any other
    container on a docker network the relay shares (n8n_default) can still
    spoof the header and escape the IP and per-IP username buckets (the
    per-username bucket still holds it). Setting TRUSTED_PROXIES to the
    proxies' own addresses closes it.
    """
    peer = request.client.host if request.client else "unknown"
    peer_ip = _ip(peer)
    peer_key = _bucket_key(peer_ip) if peer_ip is not None else peer
    last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if not last:
        return peer_key
    if not _is_trusted_proxy(peer):
        if peer not in _warned:
            _warned.add(peer)
            log.warning("sign-in X-Forwarded-For from %s ignored: not in TRUSTED_PROXIES", peer)
        return peer_key
    forwarded = _ip(last)
    return _bucket_key(forwarded) if forwarded is not None else peer_key


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
    ip = client_ip(request)
    keys = (("name", username, ip), ("user", username), ("ip", ip))
    levels = [_level(k, now) for k in keys]
    short = [(k, lv) for k, lv in zip(keys, levels) if lv < 1]
    if short:
        wait = max(math.ceil((1 - lv) * _limits(k)[1]) for k, lv in short)
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
    _warned.clear()
