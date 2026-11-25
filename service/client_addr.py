from __future__ import annotations

import ipaddress
import logging
import os

from fastapi import Request
import re

Net = ipaddress.IPv4Network | ipaddress.IPv6Network
Addr = ipaddress.IPv4Address | ipaddress.IPv6Address
_COUNTRY = re.compile(r"[A-Z]{2}")


def valid_country(c: str | None) -> bool:
    return bool(c and _COUNTRY.fullmatch(c))

_LOOPBACK = "127.0.0.0/8,::1/128"
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7,fe80::/10"
# Cloudflare's published ranges (scripts/edge-cdn-wizard.sh diffs them live).
CLOUDFLARE = (
    "173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,"
    "190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,"
    "104.24.0.0/14,172.64.0.0/13,131.0.72.0/22,"
    "2400:cb00::/32,2606:4700::/32,2803:f800::/32,2405:b500::/32,2405:8100::/32,2a06:98c0::/29,2c0f:f248::/32"
)

log = logging.getLogger("of-relay.client_addr")
_warned: set[str] = set()


_EDGE_KEYWORDS = {"cloudflare": CLOUDFLARE, "cloudflare-tunnel": f"{CLOUDFLARE},{_LOOPBACK}"}


def _parse(raw: str, env: str, keywords: dict[str, str] | None = None) -> tuple[Net, ...]:
    out = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if keywords and entry.lower() in keywords:
            out.extend(_parse(keywords[entry.lower()], env))
            continue
        try:
            out.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            log.error("%s: %r is not an IP or CIDR, skipped", env, entry)
    return tuple(out)


def _parse_trusted(raw: str) -> tuple[Net, ...]:
    return _parse(raw, "TRUSTED_PROXIES") or _parse(_DEFAULT_TRUSTED, "TRUSTED_PROXIES")


def _parse_edge(raw: str) -> tuple[Net, ...]:
    return _parse(raw, "EDGE_PROXIES", _EDGE_KEYWORDS)


TRUSTED_PROXIES = _parse_trusted(os.environ.get("TRUSTED_PROXIES", ""))
EDGE_PROXIES = _parse_edge(os.environ.get("EDGE_PROXIES", ""))


def _ip(raw: str) -> Addr | None:
    if raw.startswith("[") and "]" in raw:
        raw = raw[1:raw.index("]")]
    elif raw.count(":") == 1:
        raw = raw.split(":")[0]
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return None
    return (ip.ipv4_mapped or ip) if ip.version == 6 else ip


def _in(ip: Addr | None, nets: tuple[Net, ...]) -> bool:
    return ip is not None and any(ip in net for net in nets)


def _is_trusted_proxy(peer: str) -> bool:
    return _in(_ip(peer), TRUSTED_PROXIES)


def edge(request: Request) -> tuple[Addr | str, str]:
    # Takes the LAST X-Forwarded-For entry (the proxy's own); the default trusts all private ranges, so a container on a shared docker network can spoof it.
    peer, hop, at_edge = _hop(request)
    country = "XX"
    if at_edge:
        c = request.headers.get("cf-ipcountry", "").strip().upper()
        if valid_country(c):
            country = c
        hop = _ip(request.headers.get("cf-connecting-ip", "").strip()) or hop
    return (hop if hop is not None else peer), country


def client_address(request: Request) -> Addr | str:
    return edge(request)[0]


def from_edge(request: Request) -> bool:
    return _hop(request)[2]


def _hop(request: Request) -> tuple[str, Addr | None, bool]:
    peer = request.client.host if request.client else "unknown"
    hop = _proxied_hop(request, peer)
    return peer, hop, _in(hop, EDGE_PROXIES)


def trusted_peer(request: Request) -> bool:
    return _is_trusted_proxy(request.client.host if request.client else "unknown")


def _proxied_hop(request: Request, peer: str) -> Addr | None:
    hop = _ip(peer)
    last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if last:
        if not _is_trusted_proxy(peer):
            if peer not in _warned:
                _warned.add(peer)
                log.warning("X-Forwarded-For from %s ignored: not in TRUSTED_PROXIES", peer)
        else:
            hop = _ip(last) or hop
    return hop
