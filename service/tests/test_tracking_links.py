#!/usr/bin/env python3
"""Tracking / UTM link tests (Growth feature #4).

  case_click_records_and_redirects  GET /t/{slug} → 302 + a TrackingClick row +
                                     click_count increments per hit.
  case_unknown_slug_404             a slug that doesn't exist → 404 (no redirect).
  case_crud_and_analytics           create → list → analytics(total) → delete.
  case_target_normalization         no scheme → https:// prepended; other schemes /
                                     undotted hosts refused (unit + create route).
  case_gated_*/case_verify_*        "Bot check before redirect" (Turnstile): the gated
                                     GET holds no target and counts nothing; verify counts
                                     once on pass, zero on fail; keys unset → plain 302.
                                     siteverify is mocked at the HTTP transport.

Run: ./venv/bin/python service/tests/test_tracking_links.py
"""
from __future__ import annotations

import _harness  # MUST be first
_harness.bootstrap()

# These cases test feature logic, not the account gate (that is
# test_account_isolation_gate's job). They reach `/admin` routes or
# `assert_account_owned` with no session, which fails closed (401) since
# 3b30b486. This is the documented escape hatch (read per call), scoped to this
# test process.
import os  # noqa: E402

os.environ["ALLOW_ANONYMOUS_ADMIN"] = "1"

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from urllib.parse import parse_qs  # noqa: E402

import httpx  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, TrackingClick, TrackingLink  # noqa: E402

_client = _harness.make_client()


async def _seed_link(aid, slug, target, bot_check=False):
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(TrackingLink(account_id=aid, name="Promo", slug=slug,
                           target_url=target, click_count=0, bot_check=bot_check))


async def _link_state(slug):
    async with get_session() as s:
        row = (await s.execute(
            select(TrackingLink).where(TrackingLink.slug == slug)
        )).scalar_one()
        clicks = (await s.execute(
            select(func.count()).select_from(TrackingClick)
            .where(TrackingClick.tracking_link_id == row.id)
        )).scalar_one()
        return row.click_count, int(clicks)


def case_click_records_and_redirects():
    target = "https://onlyfans.com/mycreator"
    asyncio.run(_seed_link("tl_click", "promo-x", target))
    # two hits, no redirect-follow so we can inspect the 302 + Location.
    for _ in range(2):
        r = _client.get("/t/promo-x", follow_redirects=False)
        assert r.status_code == 302, r.status_code
        assert r.headers["location"] == target, r.headers.get("location")
    count, clicks = asyncio.run(_link_state("promo-x"))
    assert count == 2, f"click_count should be 2, got {count}"
    assert clicks == 2, f"expected 2 TrackingClick rows, got {clicks}"


def case_unknown_slug_404():
    r = _client.get("/t/does-not-exist", follow_redirects=False)
    assert r.status_code == 404, r.status_code


def case_crud_and_analytics():
    aid = "tl_crud"
    asyncio.run(_seed_link("tl_crud", "seed-slug", "https://example.com"))
    # create with a custom name (slug auto-generated)
    r = _client.post("/admin/tracking-links", json={
        "account_id": aid, "name": "Twitter bio",
        "target_url": "https://onlyfans.com/creator?utm_source=twitter",
    })
    assert r.status_code == 200, r.text
    link = r.json()
    lid, slug = link["id"], link["slug"]
    assert link["path"] == f"/t/{slug}"
    # invalid target rejected
    bad = _client.post("/admin/tracking-links", json={
        "account_id": aid, "name": "Bad", "target_url": "ftp://nope",
    })
    assert bad.status_code == 422, bad.text
    # click it once
    assert _client.get(f"/t/{slug}", follow_redirects=False).status_code == 302
    # analytics reflects the click
    an = _client.get(f"/admin/tracking-links/{lid}/analytics?account_id={aid}").json()
    assert an["total_clicks"] == 1, an
    assert an["subscribers"] is None and an["revenue_cents"] is None, "subs/$ are a TODO"
    # list shows it
    lst = _client.get(f"/admin/tracking-links?account_id={aid}").json()["links"]
    assert any(x["id"] == lid for x in lst), lst
    # delete
    d = _client.delete(f"/admin/tracking-links/{lid}")
    assert d.status_code == 200 and d.json()["deleted"] == lid


def case_slug_collision_retries_not_500():
    # Regression: a duplicate custom slug must NOT 500 (the retry loop used to
    # trip get_session's auto-commit after a swallowed IntegrityError). It should
    # mint a suffixed slug and return 200 (or a clean 409) — never 500.
    aid = "tl_dup"
    asyncio.run(_seed_link("tl_dup", "seedx", "https://example.com"))
    body = {"account_id": aid, "name": "Dup", "target_url": "https://example.com/x", "slug": "dup"}
    r1 = _client.post("/admin/tracking-links", json=body)
    assert r1.status_code == 200, r1.text
    assert r1.json()["slug"] == "dup", r1.json()
    r2 = _client.post("/admin/tracking-links", json=body)
    assert r2.status_code == 200, f"collision must not 500, got {r2.status_code}: {r2.text}"
    assert r2.json()["slug"] != "dup", "second create must get a suffixed slug"
    assert r2.json()["slug"].startswith("dup-"), r2.json()


def case_redirect_survives_a_failed_click_write():
    """/t/{slug} is the only URL a real FAN touches — it goes in the creator's
    bio. The click write must never be able to cost them the redirect. It used
    to: the write shared the lookup's transaction, so any failure poisoned it and
    the auto-commit (outside the try) raised PendingRollbackError -> 500."""
    target = "https://example.com/landing"
    asyncio.run(_seed_link("tl_boom", "bio-link", target))
    slug = "bio-link"

    import tracking_links_api as tl
    real_click = tl.TrackingClick

    class Exploding:
        def __init__(self, *a, **k):
            raise RuntimeError("simulated click-write failure")

    tl.TrackingClick = Exploding          # type: ignore[misc]
    try:
        r = _client.get(f"/t/{slug}", follow_redirects=False)
    finally:
        tl.TrackingClick = real_click     # type: ignore[misc]

    assert r.status_code == 302, f"fan must still be redirected, got {r.status_code}: {r.text[:200]}"
    assert r.headers["location"] == target, r.headers


# ── target normalization ──────────────────────────────────────────────

def case_target_normalization():
    from tracking_links_api import _normalize_target as n
    for raw, want in [
        ("ofl.ink/nora", "https://ofl.ink/nora"),
        ("  ofl.ink/nora  ", "https://ofl.ink/nora"),
        ("www.example.com", "https://www.example.com"),
        ("ofl.ink:8080/x", "https://ofl.ink:8080/x"),
        ("//ofl.ink/x", "https://ofl.ink/x"),
        ("https://ofl.ink/nora", "https://ofl.ink/nora"),
        ("http://example.com/a?b=c", "http://example.com/a?b=c"),
        ("HTTPS://Example.com", "HTTPS://Example.com"),
        ("javascript:alert(1)", None),
        ("JavaScript:alert(1)", None),
        ("javascript://ofl.ink/%0Aalert(1)", None),
        ("data:text/html,<b>x</b>", None),
        ("ftp://ofl.ink/x", None),
        ("mailto:a@b.com", None),
        ("nora", None),
        ("https://localhost/x", None),
        ("", None),
        ("   ", None),
        ("ofl.ink/a b", None),
        ("https://ofl.ink:99999/x", None),
        ("a" * 1990 + ".com/xxxxxxxxxx", None),
        (None, None),
    ]:
        assert n(raw) == want, f"{raw!r}: got {n(raw)!r}, want {want!r}"

    aid = "tl_norm"
    asyncio.run(_seed_link(aid, "norm-seed", "https://example.com"))
    r = _client.post("/admin/tracking-links", json={
        "account_id": aid, "name": "Nora", "target_url": "ofl.ink/nora"})
    assert r.status_code == 200, r.text
    assert r.json()["target_url"] == "https://ofl.ink/nora", r.json()
    assert r.json()["bot_check"] is False, r.json()
    r = _client.get(f"/t/{r.json()['slug']}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://ofl.ink/nora", r.headers
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://ofl.ink/x", "nora"):
        b = _client.post("/admin/tracking-links", json={"account_id": aid, "name": "Bad", "target_url": bad})
        assert b.status_code == 422, (bad, b.status_code, b.text)
        # The app shows this detail as is (it no longer checks the target itself).
        assert b.json()["detail"] == "Target must be a web address, e.g. ofl.ink/name.", b.json()


# ── Bot check before redirect (Turnstile) ─────────────────────────────

SITE, SECRET = "1x00000000000000000000AA", "test-turnstile-secret"


@contextlib.contextmanager
def _turnstile(verdict=True, *, keys=True, answer=None):
    """Keys in the env, and Cloudflare's siteverify answered at the HTTP transport:
    `verdict` True/False = its `success`; None = unreachable; `answer` = a raw
    httpx.Response instead. Yields the form posts it got. Every client starts
    with a full verify budget."""
    import tracking_links_api
    tracking_links_api._verify_buckets.reset()
    calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append({k: v[0] for k, v in parse_qs(req.content.decode()).items()} | {"_url": str(req.url)})
        if answer is not None:
            return answer
        if verdict is None:
            raise httpx.ConnectError("cloudflare down", request=req)
        return httpx.Response(200, json={"success": verdict, "error-codes": [] if verdict else ["invalid-input-response"]})

    real = httpx.AsyncClient
    saved = {k: os.environ.get(k) for k in ("TURNSTILE_SITE_KEY", "TURNSTILE_SECRET_KEY", "TURNSTILE_VERIFY_URL")}
    httpx.AsyncClient = lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)})  # type: ignore[misc]
    if keys:
        os.environ.update(TURNSTILE_SITE_KEY=SITE, TURNSTILE_SECRET_KEY=SECRET)
    else:
        os.environ.pop("TURNSTILE_SITE_KEY", None)
        os.environ.pop("TURNSTILE_SECRET_KEY", None)
    os.environ.pop("TURNSTILE_VERIFY_URL", None)
    try:
        yield calls
    finally:
        httpx.AsyncClient = real  # type: ignore[misc]
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


GATED_TARGET = "https://secret-landing.example.org/nora?utm=bio"


def case_gated_get_serves_check_page_without_target():
    asyncio.run(_seed_link("tl_gate", "gate-a", GATED_TARGET, bot_check=True))
    with _turnstile() as calls:
        r = _client.get("/t/gate-a", follow_redirects=False)
    assert r.status_code == 200, r.status_code
    body = r.text
    assert "secret-landing" not in body and "example.org" not in body, "target leaked into the gate page"
    assert 'data-sitekey="%s"' % SITE in body, body[:400]
    assert "challenges.cloudflare.com/turnstile/v0/api.js" in body
    assert r.headers["cache-control"] == "no-store", r.headers
    assert "noindex" in r.headers["x-robots-tag"] and 'name="robots" content="noindex' in body
    assert "location" not in r.headers
    assert "frame-src https://challenges.cloudflare.com" in r.headers["content-security-policy"]
    assert calls == [], "GET must not call siteverify"
    assert asyncio.run(_link_state("gate-a")) == (0, 0), "GET of a gated link must not count a click"


def case_verify_pass_counts_once():
    asyncio.run(_seed_link("tl_pass", "gate-pass", GATED_TARGET, bot_check=True))
    with _turnstile(True) as calls:
        r = _client.post("/t/gate-pass/verify", json={"token": "tok-1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"url": GATED_TARGET}, r.json()
    assert r.headers["cache-control"] == "no-store"
    assert len(calls) == 1, calls
    c = calls[0]
    assert c["_url"] == "https://challenges.cloudflare.com/turnstile/v0/siteverify", c
    assert c["secret"] == SECRET and c["response"] == "tok-1" and c.get("remoteip"), c
    assert asyncio.run(_link_state("gate-pass")) == (1, 1)


def case_verify_fail_counts_zero():
    asyncio.run(_seed_link("tl_fail", "gate-fail", GATED_TARGET, bot_check=True))
    with _turnstile(False) as calls:
        r = _client.post("/t/gate-fail/verify", json={"token": "bad"})
        assert r.status_code == 403, r.status_code
        assert "secret-landing" not in r.text
        empty = _client.post("/t/gate-fail/verify", json={"token": ""})
        assert empty.status_code == 403, empty.status_code
        huge = _client.post("/t/gate-fail/verify", json={"token": "x" * 3000})
        assert huge.status_code == 403, huge.status_code
    assert len(calls) == 1, f"empty / oversized tokens must not reach Cloudflare: {calls}"
    with _turnstile(None):
        down = _client.post("/t/gate-fail/verify", json={"token": "t"})
    assert down.status_code == 503, down.status_code
    assert "secret-landing" not in down.text
    assert asyncio.run(_link_state("gate-fail")) == (0, 0)
    assert _client.post("/t/nope-nope/verify", json={"token": "t"}).status_code == 404


def case_gate_page_retry_has_no_inline_handler():
    """The nonce CSP blocks inline handlers: Retry is wired from the nonce'd script."""
    asyncio.run(_seed_link("tl_retry", "gate-retry", GATED_TARGET, bot_check=True))
    with _turnstile():
        body = _client.get("/t/gate-retry", follow_redirects=False).text
    assert "onclick" not in body.lower(), "inline handler: blocked by the page's CSP"
    assert 'id="rb"' in body and 'addEventListener("click",retryTs)' in body, body


def case_verify_cloudflare_busy_is_503_not_403():
    asyncio.run(_seed_link("tl_busy", "gate-busy", GATED_TARGET, bot_check=True))
    for answer in (httpx.Response(500, text="oops"),
                   httpx.Response(200, json={"success": False, "error-codes": ["internal-error"]})):
        with _turnstile(answer=answer) as calls:
            r = _client.post("/t/gate-busy/verify", json={"token": "t"})
        assert r.status_code == 503, (answer.status_code, r.status_code)
        assert len(calls) == 1, calls
    assert asyncio.run(_link_state("gate-busy")) == (0, 0)


def case_verify_is_throttled_per_client_before_lookup_and_siteverify():
    import tracking_links_api as tla
    asyncio.run(_seed_link("tl_thr", "gate-thr", GATED_TARGET, bot_check=True))
    real_clock, tla._clock = tla._clock, lambda: 1000.0   # no refill mid-test, however slow the box
    try:
        with _turnstile(False) as calls:
            codes = [_client.post("/t/gate-thr/verify", json={"token": "junk"}).status_code
                     for _ in range(tla.VERIFY_CAPACITY)]
            over = _client.post("/t/gate-thr/verify", json={"token": "junk"})
            unknown = _client.post("/t/nope-thr/verify", json={"token": "junk"})
    finally:
        tla._clock = real_clock
    assert codes == [403] * tla.VERIFY_CAPACITY, codes
    assert over.status_code == 429 and int(over.headers["retry-after"]) >= 1, (over.status_code, over.headers)
    assert unknown.status_code == 429, "throttle runs before the link lookup"
    assert len(calls) == tla.VERIFY_CAPACITY, f"a throttled verify must not reach Cloudflare: {len(calls)}"
    with _turnstile(True):
        r = _client.get("/t/gate-thr", follow_redirects=False)
    assert r.status_code == 200, "the plain GET is never throttled"


def case_verify_url_seam_is_loopback_only():
    import tracking_links_api as tla
    real = tla.TURNSTILE_VERIFY_URL
    saved = os.environ.get("TURNSTILE_VERIFY_URL")
    try:
        for raw, want in [
            ("", real),
            ("http://127.0.0.1:9/__slop/fake/turnstile-siteverify", "http://127.0.0.1:9/__slop/fake/turnstile-siteverify"),
            ("http://localhost:9/x", "http://localhost:9/x"),
            ("https://evil.example.com/siteverify", real),
            ("http://user:pw@127.0.0.1:9/x", real),
            ("http://127.0.0.1.evil.example/x", real),
            ("ftp://127.0.0.1/x", real),
            ("http://127.0.0.1:99999/x", real),
        ]:
            os.environ["TURNSTILE_VERIFY_URL"] = raw
            assert tla._verify_url() == want, (raw, tla._verify_url())
    finally:
        if saved is None:
            os.environ.pop("TURNSTILE_VERIFY_URL", None)
        else:
            os.environ["TURNSTILE_VERIFY_URL"] = saved


def case_gated_keys_unset_falls_back_to_302():
    asyncio.run(_seed_link("tl_nokeys", "gate-nokeys", GATED_TARGET, bot_check=True))
    with _turnstile(keys=False) as calls:
        r = _client.get("/t/gate-nokeys", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == GATED_TARGET, r.status_code
        v = _client.post("/t/gate-nokeys/verify", json={"token": ""})
        assert v.status_code == 200 and v.json() == {"url": GATED_TARGET}, v.text
        lst = _client.get("/admin/tracking-links?account_id=tl_nokeys").json()
        assert lst["bot_check_available"] is False, lst
    assert calls == []
    assert asyncio.run(_link_state("gate-nokeys")) == (2, 2)
    with _turnstile():
        assert _client.get("/admin/tracking-links?account_id=tl_nokeys").json()["bot_check_available"] is True


def case_create_and_patch_bot_check():
    aid = "tl_patch"
    asyncio.run(_seed_link(aid, "patch-seed", "https://example.com"))
    r = _client.post("/admin/tracking-links", json={
        "account_id": aid, "name": "Gated", "target_url": "ofl.ink/g", "bot_check": True})
    assert r.status_code == 200 and r.json()["bot_check"] is True, r.text
    lid, slug = r.json()["id"], r.json()["slug"]
    with _turnstile():
        assert _client.get(f"/t/{slug}", follow_redirects=False).status_code == 200
        p = _client.patch(f"/admin/tracking-links/{lid}", json={"bot_check": False})
        assert p.status_code == 200 and p.json()["bot_check"] is False, p.text
        g = _client.get(f"/t/{slug}", follow_redirects=False)
        assert g.status_code == 302 and g.headers["location"] == "https://ofl.ink/g", g.status_code
    lst = _client.get(f"/admin/tracking-links?account_id={aid}").json()["links"]
    assert [x["bot_check"] for x in lst if x["id"] == lid] == [False], lst
    assert _client.patch("/admin/tracking-links/999999", json={"bot_check": True}).status_code == 404
    assert _client.patch(f"/admin/tracking-links/{lid}", json={}).status_code == 422


_harness.run(
    case_redirect_survives_a_failed_click_write,
    case_click_records_and_redirects,
    case_unknown_slug_404,
    case_crud_and_analytics,
    case_slug_collision_retries_not_500,
    case_target_normalization,
    case_gated_get_serves_check_page_without_target,
    case_verify_pass_counts_once,
    case_verify_fail_counts_zero,
    case_gate_page_retry_has_no_inline_handler,
    case_verify_cloudflare_busy_is_503_not_403,
    case_verify_is_throttled_per_client_before_lookup_and_siteverify,
    case_verify_url_seam_is_loopback_only,
    case_gated_keys_unset_falls_back_to_302,
    case_create_and_patch_bot_check,
)
