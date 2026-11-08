"""service/client_addr.py — the browser's own address behind the proxies in front of the relay.

Used by the sign-in throttle (login_throttle) and the tracking-link click rows
(tracking_links_api). Two env vars, both read at import:

TRUSTED_PROXIES  the peers whose X-Forwarded-For is believed: IPs or CIDRs,
                 comma-separated, replacing the default (loopback + the private
                 ranges, which hold every docker network: the Next app and
                 Traefik). Empty means the default: trusting no proxy would put
                 every user in the proxy's one bucket.
EDGE_PROXIES     a CDN in front of Traefik (deploy/ae/EDGE-CDN.md): `cloudflare`
                 (Cloudflare's published ranges, below) and/or IPs or CIDRs. When
                 the address our proxies saw is one of these, the CDN's
                 `CF-Connecting-IP` header is the client. Empty (the default):
                 the header is never read, nothing changes.
                 `cloudflare-tunnel`: the same plus loopback, for a cloudflared
                 tunnel on the host (deploy/ae/docker-compose.tunnel.yml).
                 cloudflared reaches Traefik from 127.0.0.1, so Traefik's
                 X-Forwarded-For is loopback. Safe: a hit on the public IP
                 reaches Traefik from a public peer, so that address is not
                 loopback and the header is ignored; only a process on the box
                 can present a loopback peer, and that one owns the box already.

Why a header of its own: Traefik believes no forwarded header from its clients,
so behind Cloudflare it sets X-Forwarded-For to the Cloudflare server's address
and every phone near one Cloudflare city would share one throttle bucket.
Cloudflare overwrites `CF-Connecting-IP` on every request, so it is trusted
only when the request really came from a Cloudflare address; a request sent
straight to the host's IP (no Cloudflare) is keyed by its own address, whatever
header it forges.
"""

from __future__ import annotations

import ipaddress
import logging
import os

from fastapi import Request

Net = ipaddress.IPv4Network | ipaddress.IPv6Network
Addr = ipaddress.IPv4Address | ipaddress.IPv6Address

_LOOPBACK = "127.0.0.0/8,::1/128"
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7,fe80::/10"
# https://www.cloudflare.com/ips-v4 + /ips-v6, fetched 2026-11-06.
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
    """`raw`'s networks. An entry that is no IP or CIDR (nor one of `keywords`) is logged and skipped, never
    raised: the relay must still start. Skipping trusts less; a TRUSTED_PROXIES left with nothing gets the default,
    as an empty one does."""
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


def _in(ip: Addr | None, nets: tuple[Net, ...]) -> bool:
    return ip is not None and any(ip in net for net in nets)


def _is_trusted_proxy(peer: str) -> bool:
    return _in(_ip(peer), TRUSTED_PROXIES)


def client_address(request: Request) -> Addr | str:
    """The client's address: the socket peer, or the LAST X-Forwarded-For entry
    when the peer is in TRUSTED_PROXIES and the entry parses; then, when that
    address is in EDGE_PROXIES, the CDN's `CF-Connecting-IP` if it parses. A
    peer that is no address at all (a test client) comes back as its string.

    The relay is reached through a proxy: the Next app (its rewrites, on the
    compose network) and, where the compose labels route relay paths
    straight to it, Traefik. Next adds the browser's socket address only when
    the header is absent and never appends, and its rewrite passes the header
    on unchanged. Traefik (its untrusted clients' forwarded headers are
    dropped) sets the header to the client's address, and the cloudflared
    tunnel appends it after whatever the client sent. Either way the last entry
    is the one our proxy wrote. A peer outside TRUSTED_PROXIES (a public
    address reaching the relay directly) has its header ignored and is the
    client itself (warned once per peer).

    The remaining gap: the default trusts every private address, so any other
    container on a docker network the relay shares can still spoof the header.
    Setting TRUSTED_PROXIES to the proxies' own addresses closes it.
    """
    peer = request.client.host if request.client else "unknown"
    hop = _ip(peer)
    last = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if last:
        if not _is_trusted_proxy(peer):
            if peer not in _warned:
                _warned.add(peer)
                log.warning("X-Forwarded-For from %s ignored: not in TRUSTED_PROXIES", peer)
        else:
            hop = _ip(last) or hop
    if _in(hop, EDGE_PROXIES):
        hop = _ip(request.headers.get("cf-connecting-ip", "").strip()) or hop
    return hop if hop is not None else peer
