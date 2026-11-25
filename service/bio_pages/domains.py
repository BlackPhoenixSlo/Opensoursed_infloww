from __future__ import annotations

import asyncio
import ipaddress
import os
from dataclasses import dataclass, field

import httpx

from bio_pages import decide

TXT_PREFIX = "_oflink"
PROOF_PREFIX = "oflink-verify="
MAX_PER_OWNER = 10
RESERVED_SUFFIXES = ("ofl.ink", "inflowwww.com")
DOH_URL = "https://cloudflare-dns.com/dns-query"
DNS_TIMEOUT_S = 4.0
PROBE_TIMEOUT_S = 5.0
_CHECKS = asyncio.Semaphore(4)

OFF_MSG = "Custom Domains are not set up on this server yet. Try again later."
CERT_MSG = "DNS is set. Getting the certificate: check again in a minute or two."


def _ip(env: str, kind) -> str | None:
    raw = (os.environ.get(env) or "").strip()
    try:
        return str(kind(raw)) if raw else None
    except ValueError:
        return None


def server_ip() -> str | None:
    return _ip("BIO_SERVER_IP", ipaddress.IPv4Address)


def server_ipv6() -> str | None:
    return _ip("BIO_SERVER_IPV6", ipaddress.IPv6Address)


def normalize(raw: str) -> str:
    return raw.strip().lower()


def host_of(url: str | None) -> str | None:
    rest = (url or "").strip().lower().split("://", 1)[-1]
    host = rest.split("/", 1)[0].split(":", 1)[0]
    return host or None


def own_host(domain: str, reserved_hosts: set[str]) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in (*RESERVED_SUFFIXES, *reserved_hosts))


def valid(domain: str) -> bool:
    return len(domain) <= 253 and bool(decide.HOSTNAME.fullmatch(domain))


def relative_name(domain: str, prefix: str = "") -> str:
    # Wrong for a multi-label public suffix (x.co.uk); no suffix list here.
    in_zone = ".".join(domain.split(".")[:-2])
    return ".".join(p for p in (prefix, in_zone) if p) or "@"


def records_for(domain: str, token: str, ip: str | None, ipv6: str | None) -> list[dict[str, str]]:
    def rec(kind: str, prefix: str, value: str) -> dict[str, str]:
        fqdn = f"{prefix}.{domain}" if prefix else domain
        return {"type": kind, "name": relative_name(domain, prefix), "fqdn": fqdn, "value": value}
    out = []
    if ip:
        out.append(rec("A", "", ip))
    if ipv6:
        out.append(rec("AAAA", "", ipv6))
    out.append(rec("TXT", TXT_PREFIX, PROOF_PREFIX + token))
    return out


@dataclass(frozen=True)
class Dns:
    a: tuple[str, ...] = ()
    aaaa: tuple[str, ...] = ()
    txt: tuple[str, ...] = ()
    caa: tuple[tuple[str, str], ...] = field(default=())


def _same_ipv6(a: str, b: str) -> bool:
    try:
        return ipaddress.IPv6Address(a) == ipaddress.IPv6Address(b)
    except ValueError:
        return False


def allows_letsencrypt(caa: tuple[tuple[str, str], ...]) -> bool:
    issuers = [v.split(";")[0].strip().lower() for t, v in caa if t == "issue"]
    return not issuers or "letsencrypt.org" in issuers


def problems(domain: str, token: str, ip: str, ipv6: str | None, dns: Dns, sole: bool = False) -> list[str]:
    out = []
    proof = PROOF_PREFIX + token
    if not dns.txt:
        out.append(f"No TXT record {TXT_PREFIX}.{domain} yet.")
    elif proof not in dns.txt:
        out.append(f"The TXT record {TXT_PREFIX}.{domain} does not hold {proof} yet.")
    elif sole and any(v.startswith(PROOF_PREFIX) and v != proof for v in dns.txt):
        out.append(f"The TXT record {TXT_PREFIX}.{domain} holds another {PROOF_PREFIX} value too. Keep only {proof}.")
    if not dns.a:
        out.append(f"No A record for {domain} yet.")
    elif ip not in dns.a:
        out.append(f"{domain} points to {', '.join(dns.a)}, not {ip}.")
    else:
        out.extend(f"Delete the A record {other}." for other in dns.a if other != ip)
    out.extend(f"Delete the AAAA record {other}." for other in dns.aaaa if not ipv6 or not _same_ipv6(other, ipv6))
    if not allows_letsencrypt(dns.caa):
        out.append(f"A CAA record for {domain} does not allow letsencrypt.org. Add one that does, or delete it.")
    return out


class DnsUnavailable(Exception):
    pass


def _txt_value(data: str) -> str:
    parts = [p for i, p in enumerate(data.split('"')) if i % 2 == 1]
    return "".join(parts) if parts else data


def _caa_entry(data: str) -> tuple[str, str] | None:
    bits = data.split(None, 2)
    if len(bits) != 3:
        return None
    return bits[1].lower(), bits[2].strip().strip('"')


async def _doh(client: httpx.AsyncClient, name: str, rtype: str, want: int) -> list[str]:
    r = await client.get(DOH_URL, params={"name": name, "type": rtype}, headers={"accept": "application/dns-json"})
    if r.status_code != 200:
        raise DnsUnavailable
    body = r.json()
    if body.get("Status") == 3:
        return []
    if body.get("Status") != 0:
        raise DnsUnavailable
    return [str(a.get("data", "")) for a in body.get("Answer") or [] if isinstance(a, dict) and a.get("type") == want]


async def _caa_set(client: httpx.AsyncClient, domain: str) -> tuple[tuple[str, str], ...]:
    labels = domain.split(".")
    for i in range(len(labels)):
        found = [e for e in map(_caa_entry, await _doh(client, ".".join(labels[i:]), "CAA", 257)) if e]
        if found:
            return tuple(found)
    return ()


async def lookup(domain: str) -> Dns:
    try:
        async with httpx.AsyncClient(timeout=DNS_TIMEOUT_S, trust_env=False) as cl:
            a, aaaa, txt, caa = await asyncio.gather(
                _doh(cl, domain, "A", 1), _doh(cl, domain, "AAAA", 28),
                _doh(cl, f"{TXT_PREFIX}.{domain}", "TXT", 16), _caa_set(cl, domain))
    except (httpx.HTTPError, ValueError):
        raise DnsUnavailable from None
    return Dns(tuple(a), tuple(aaaa), tuple(map(_txt_value, txt)), caa)


async def probe(domain: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S, trust_env=False, follow_redirects=False) as cl:
            return (await cl.get(f"https://{domain}/internal/healthz")).status_code == 200
    except httpx.HTTPError:
        return False


async def check(domain: str, token: str, status: str, ip: str, ipv6: str | None,
                sole: bool = False) -> tuple[str, list[str]]:
    if status == "live":
        return "live", []
    async with _CHECKS:
        try:
            dns = await lookup(domain)
        except DnsUnavailable:
            return status, [f"The DNS lookup for {domain} did not answer. Try again in a few minutes."]
        found = problems(domain, token, ip, ipv6, dns, sole=sole)
        if found:
            return "pending", found
        if await probe(domain):
            return "live", []
    return "pending_cert", [CERT_MSG]
