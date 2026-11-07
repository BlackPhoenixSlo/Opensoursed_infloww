#!/usr/bin/env python3
"""The client's address behind a CDN (service/client_addr.py, deploy/ae/EDGE-CDN.md).

Behind Cloudflare, Traefik writes the Cloudflare server's address in
X-Forwarded-For, so every phone near one Cloudflare city would share it. With
EDGE_PROXIES set, a request that came from a Cloudflare address is keyed by
Cloudflare's CF-Connecting-IP; unset, nothing changes; a request that did not
come from Cloudflare cannot pick its address by forging the header.

The seam: client_address on hand-built requests, then the Relay over HTTP
(TestClient with a docker-network peer, as the Next app is) for the sign-in
throttle's buckets and log line and the tracking-link click row. EDGE_PROXIES
is swapped per case (it is read at import).

Run: ./venv/bin/python service/tests/test_client_addr.py   (exit 0 = green)
"""
import _harness  # MUST be first — binds a throwaway temp DB before any db import

_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import ipaddress  # noqa: E402
import logging  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from starlette.requests import Request  # noqa: E402

import client_addr  # noqa: E402
import login_throttle  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import Account, TrackingClick, TrackingLink  # noqa: E402

CF_V4, CF_V6 = "162.158.88.17", "2a06:98c0:3600::103"  # inside Cloudflare's published ranges
PHONE_A, PHONE_B = "203.0.113.7", "198.51.100.23"
NEXT_PEER = "172.18.0.5"                               # the Next app on the compose network


@contextlib.contextmanager
def edge(raw: str):
    real = client_addr.EDGE_PROXIES
    client_addr.EDGE_PROXIES = client_addr._parse_edge(raw)
    try:
        yield
    finally:
        client_addr.EDGE_PROXIES = real
        login_throttle.reset()


def addr(peer: str, xff: str | None = None, cf: str | None = None) -> str:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    headers += [(b"cf-connecting-ip", cf.encode())] if cf else []
    return str(client_addr.client_address(Request({"type": "http", "headers": headers, "client": (peer, 1)})))


def case_unset_the_cdn_header_is_never_read():
    with edge(""):
        assert client_addr.EDGE_PROXIES == ()
        assert addr(NEXT_PEER, CF_V4, PHONE_A) == CF_V4
        assert addr(CF_V4, None, PHONE_A) == CF_V4


def case_cloudflare_is_its_published_ranges_plus_any_extra_cidr():
    nets = client_addr._parse_edge("cloudflare, 10.9.9.0/24")
    assert ipaddress.ip_network("10.9.9.0/24") in nets and ipaddress.ip_network("173.245.48.0/20") in nets
    assert len(nets) == len(client_addr.CLOUDFLARE.split(",")) + 1, len(nets)
    assert client_addr._in(ipaddress.ip_address(CF_V6), nets)
    try:
        client_addr._parse_edge("cloudflare,cdn-host")
        raise AssertionError("parsed")
    except ValueError as e:
        assert "EDGE_PROXIES" in str(e) and "cdn-host" in str(e), e


def case_through_cloudflare_the_phone_is_the_client():
    with edge("cloudflare"):
        assert addr(NEXT_PEER, CF_V4, PHONE_A) == PHONE_A                   # Traefik -> Next -> relay
        assert addr(NEXT_PEER, f"10.0.0.1, {CF_V6}", "2001:db8::9") == "2001:db8::9"
        assert addr(CF_V4, None, PHONE_A) == PHONE_A                        # Cloudflare as the peer itself
        assert addr(NEXT_PEER, CF_V4, "not-an-ip") == CF_V4                 # a header that is no address
        assert addr(NEXT_PEER, CF_V4) == CF_V4


def case_a_request_that_skipped_cloudflare_cannot_forge_the_header():
    with edge("cloudflare"):
        # Straight to the host's IP: Traefik writes the sender's own address.
        assert addr(NEXT_PEER, PHONE_B, PHONE_A) == PHONE_B
        # A public peer outside TRUSTED_PROXIES naming a Cloudflare hop is ignored first.
        assert addr(PHONE_B, CF_V4, PHONE_A) == PHONE_B


def case_through_the_tunnel_the_phone_is_the_client():
    """cloudflared on the host hands Traefik the request from 127.0.0.1, so
    Traefik's X-Forwarded-For is loopback; `cloudflare-tunnel` believes the
    header there too. A hit on the public IP still keys by its sender."""
    nets = client_addr._parse_edge("cloudflare-tunnel")
    assert len(nets) == len(client_addr.CLOUDFLARE.split(",")) + 2, len(nets)
    with edge("cloudflare-tunnel"):
        assert addr(NEXT_PEER, "127.0.0.1", PHONE_A) == PHONE_A             # tunnel -> Traefik -> Next -> relay
        assert addr(NEXT_PEER, "::1", PHONE_A) == PHONE_A
        assert addr(NEXT_PEER, CF_V4, PHONE_A) == PHONE_A                   # orange cloud without the tunnel
        assert addr(NEXT_PEER, PHONE_B, PHONE_A) == PHONE_B                 # straight to the IP: forged header ignored
    with edge("cloudflare"):
        assert addr(NEXT_PEER, "127.0.0.1", PHONE_A) == "127.0.0.1"         # plain mode stays as it was


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _spray(c: TestClient, phone: str, n: int) -> list[int]:
    return [c.post("/auth/sign-in", json={"username": f"nobody_{phone}_{i}", "password": "bad"},
                   headers={"X-Forwarded-For": CF_V4, "CF-Connecting-IP": phone}).status_code
            for i in range(n)]


def case_two_phones_behind_one_cloudflare_server_keep_their_own_sign_in_bucket():
    c = TestClient(_harness.make_client().app, client=(NEXT_PEER, 50000))
    lines = _Lines()
    logging.getLogger("of-relay.login_throttle").addHandler(lines)
    try:
        with edge(""):  # today: both phones are the Cloudflare server
            assert _spray(c, PHONE_A, login_throttle.IP_CAPACITY) == [401] * login_throttle.IP_CAPACITY
            assert _spray(c, PHONE_B, 1) == [429]
            assert any(f"ip={CF_V4}" in ln for ln in lines.lines), lines.lines
        lines.lines.clear()
        with edge("cloudflare"):
            codes = _spray(c, PHONE_A, login_throttle.IP_CAPACITY + 1)
            assert codes == [401] * login_throttle.IP_CAPACITY + [429], codes
            assert _spray(c, PHONE_B, 1) == [401]
            # The throttle's log names the phone, not Cloudflare.
            assert any(f"sign-in throttled ip={PHONE_A} buckets=ip" in ln for ln in lines.lines), lines.lines
            assert not any(CF_V4 in ln for ln in lines.lines), lines.lines
    finally:
        logging.getLogger("of-relay.login_throttle").removeHandler(lines)


async def _seed_link(slug: str) -> None:
    async with get_session() as s:
        s.add(Account(id=f"acct_{slug}"))
        s.add(TrackingLink(account_id=f"acct_{slug}", name="Bio", slug=slug,
                           target_url="https://onlyfans.com/creator", click_count=0))


async def _click_ips(slug: str) -> list[str | None]:
    async with get_session() as s:
        link = (await s.execute(select(TrackingLink).where(TrackingLink.slug == slug))).scalar_one()
        return list((await s.execute(select(TrackingClick.ip).where(TrackingClick.tracking_link_id == link.id)
                                     .order_by(TrackingClick.id))).scalars())


def case_a_tracking_click_records_the_fans_address_not_the_proxy():
    asyncio.run(_seed_link("edge-bio"))
    c = TestClient(_harness.make_client().app, client=(NEXT_PEER, 50000))
    hop = {"X-Forwarded-For": CF_V4, "CF-Connecting-IP": PHONE_A}
    with edge(""):
        assert c.get("/t/edge-bio", headers=hop, follow_redirects=False).status_code == 302
        assert c.get("/t/edge-bio", headers={"X-Forwarded-For": PHONE_B}, follow_redirects=False).status_code == 302
    with edge("cloudflare"):
        assert c.get("/t/edge-bio", headers=hop, follow_redirects=False).status_code == 302
    # Before this, every row held the Next container's address (NEXT_PEER).
    assert asyncio.run(_click_ips("edge-bio")) == [CF_V4, PHONE_B, PHONE_A]


def case_a_relay_answer_without_its_own_cache_header_is_no_store():
    """No CDN may keep a per-user answer (deploy/ae/EDGE-CDN.md); a route's own header wins."""
    c = TestClient(_harness.make_client().app)
    for path in ("/auth/me", "/chatter/me", "/admin/accounts", "/t/no-such-link"):
        r = c.get(path, follow_redirects=False)
        assert r.headers.get("cache-control") == "no-store", (path, r.status_code, dict(r.headers))
    import img_api
    url = "https://cdn2.onlyfans.com/files/e/ee/edge/source.jpg?Signature=e"
    img_api._img_cache_write(url, "image/jpeg", b"x")
    assert img_api._serve_if_cached(url, "HIT").headers["cache-control"].startswith("private, max-age=604800")


_harness.run()
