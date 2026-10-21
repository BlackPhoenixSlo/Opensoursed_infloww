#!/usr/bin/env python3
"""Tracking / UTM link tests (Growth feature #4).

  case_click_records_and_redirects  GET /t/{slug} → 302 + a TrackingClick row +
                                     click_count increments per hit.
  case_unknown_slug_404             a slug that doesn't exist → 404 (no redirect).
  case_crud_and_analytics           create → list → analytics(total) → delete.

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

from sqlalchemy import func, select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import Account, TrackingClick, TrackingLink  # noqa: E402

_client = _harness.make_client()


async def _seed_link(aid, slug, target):
    async with get_session() as s:
        s.add(Account(id=aid))
        s.add(TrackingLink(account_id=aid, name="Promo", slug=slug,
                           target_url=target, click_count=0))


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


_harness.run(
    case_redirect_survives_a_failed_click_write,
    case_click_records_and_redirects,
    case_unknown_slug_404,
    case_crud_and_analytics,
    case_slug_collision_retries_not_500,
)
