from __future__ import annotations

import ipaddress
import zlib
from collections import OrderedDict
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

import events_decide as ed

DEDUPE_MAX = 4096
# Longer than the 2 h purchase re-offer; a bad timestamp re-offers forever.
DEDUPE_TTL_S = 24 * 3600
RETRY_DELAYS_S = (1.0, 4.0)
RETRY_AFTER_MAX_S = 30.0
ENDPOINT_MAX = 2048
KEY_MAX = 1024
DEFAULT_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
                 "*.push.apple.com", "*.notify.windows.com")

Outcome = Literal["ok", "prune", "retry", "fail"]


def should_push(sub: Any, notice: Any, accounts: Optional[frozenset], platform: str, seen: "Seen | None",
                now: float = 0.0) -> bool:
    if accounts is None or not ed.sees("all", accounts, notice.account_id):
        return False
    return wanted(sub, notice, platform) and (seen is None or not seen.has(notice.tag, now))


def wanted(sub: Any, notice: Any, platform: str) -> bool:
    if notice.type_key is None or notice.type_key not in sub.types:
        return False
    return bool((sub.platforms or {}).get(platform, True))


def outcome(status: Optional[int]) -> Outcome:
    if status is None or status == 429 or status >= 500:
        return "retry"
    if 200 <= status < 300:
        return "ok"
    if status in (404, 410):
        return "prune"
    return "fail"


def retry_delay(attempt: int, retry_after: Optional[str] = None) -> Optional[float]:
    if attempt >= len(RETRY_DELAYS_S):
        return None
    try:
        ra = float(retry_after) if retry_after is not None else None
    except ValueError:
        ra = None
    if ra is not None and 0 <= ra:
        return min(ra, RETRY_AFTER_MAX_S)
    return RETRY_DELAYS_S[attempt]


def parse_hosts(raw: Optional[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_HOSTS
    return tuple(h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip())


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_listed(host: str, hosts: tuple[str, ...]) -> bool:
    for h in hosts:
        if h.startswith("*."):
            if host.endswith(h[1:]) and len(host) > len(h) - 1:
                return True
        elif host == h:
            return True
    return False


def endpoint_allowed(url: Any, hosts: tuple[str, ...]) -> bool:
    if not isinstance(url, str) or len(url) > ENDPOINT_MAX:
        return False
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return False
    host = (u.hostname or "").rstrip(".")
    if not host or u.username is not None or u.password is not None or "@" in u.netloc:
        return False
    if not _host_listed(host, hosts):
        return False
    if _loopback(host):
        return u.scheme in ("http", "https")
    return u.scheme == "https" and port in (None, 443)


class Seen:
    __slots__ = ("_d",)

    def __init__(self) -> None:
        self._d: OrderedDict[str, float] = OrderedDict()

    def has(self, tag: str, now: float) -> bool:
        at = self._d.get(tag)
        return at is not None and now - at < DEDUPE_TTL_S

    def add(self, tag: str, now: float) -> None:
        self._d[tag] = now
        self._d.move_to_end(tag)
        while len(self._d) > DEDUPE_MAX:
            self._d.popitem(last=False)

    def discard(self, tag: str) -> None:
        self._d.pop(tag, None)


def shard(sub_id: str, n: int) -> int:
    return zlib.crc32(sub_id.encode()) % n
