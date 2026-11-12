#!/usr/bin/env python3
"""Raw redirect-click stats and their real public/owner routes.

STATS_CLOCK_SHIFT_DAYS shifts the shared write/read clock to check date-boundary stability.
"""
import _harness
_harness.bootstrap()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
import _agency_fixtures as fx  # noqa: E402
import admission  # noqa: E402
import click_classify as cc  # noqa: E402
import tracking_stats as ts  # noqa: E402
from db.engine import get_session  # noqa: E402
from db.models import TrackingLink  # noqa: E402

IDS = fx.seed_two_agencies()
AID, BID = IDS["creator_a"], IDS["creator_b"]
_anon = _harness.make_client()
_owner = fx.login_owner("agency_a_owner")
_other = fx.login_owner("agency_b_owner")
NOW = datetime(2026, 11, 11, 15, tzinfo=timezone.utc) + timedelta(days=int(os.environ.get("STATS_CLOCK_SHIFT_DAYS", "0")))
ts.utcnow = lambda: NOW
_n = iter(range(1, 10000))


def sql(q, **p):
    async def go():
        async with get_session() as s:
            result = await s.execute(text(q), p)
            return result.all() if result.returns_rows else None
    return asyncio.run(go())


def link(aid=AID, gated=False):
    slug = f"st-{next(_n)}"
    async def go():
        async with get_session() as s:
            row = TrackingLink(account_id=aid, name=slug, slug=slug, target_url="https://example.com/x",
                               click_count=0, bot_check=gated)
            s.add(row)
            await s.flush()
            return row.id
    return asyncio.run(go()), slug


def analytics(lid, aid=AID, days=30, client=_owner):
    return client.get(f"/admin/tracking-links/{lid}/analytics?account_id={aid}&days={days}")


def summary(aid=AID, client=_owner):
    return client.get(f"/admin/tracking-links/summary?account_id={aid}")


def seed(lid, when, ua=None, referer=None, country=None, app=None, ref=None):
    sql("INSERT INTO tracking_clicks (tracking_link_id, clicked_at, user_agent, referer, country, in_app, ref) "
        "VALUES (:lid,:at,:ua,:referer,:country,:app,:ref)", lid=lid, at=when.strftime("%Y-%m-%d %H:%M:%S"),
        ua=ua, referer=referer, country=country, app=app, ref=ref)
    sql("UPDATE tracking_links SET click_count=click_count+1 WHERE id=:lid", lid=lid)


def counts(lid):
    return sql("SELECT (SELECT COUNT(*) FROM tracking_clicks WHERE tracking_link_id=:lid), click_count "
               "FROM tracking_links WHERE id=:lid", lid=lid)[0]


@contextlib.contextmanager
def turnstile():
    real = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: real(**{**kw, "transport": httpx.MockTransport(
        lambda req: httpx.Response(200, json={"success": True}))})
    os.environ.update(TURNSTILE_SITE_KEY="1x00000000000000000000AA", TURNSTILE_SECRET_KEY="s")
    import tracking_links_api as tla
    tla._verify_http = None
    try:
        yield
    finally:
        httpx.AsyncClient = real
        tla._verify_http = None
        os.environ.pop("TURNSTILE_SITE_KEY", None)
        os.environ.pop("TURNSTILE_SECRET_KEY", None)


def case_clicks_classify_failure_and_clock():
    lid, slug = link()
    r = _anon.get(f"/t/{slug}", headers={"user-agent": "Instagram", "referer": "https://t.co/x"},
                  follow_redirects=False)
    assert r.status_code == 302 and counts(lid) == (1, 1)
    row = sql("SELECT clicked_at,country,in_app,ref FROM tracking_clicks WHERE tracking_link_id=:lid", lid=lid)[0]
    assert str(row[0]).startswith(NOW.strftime("%Y-%m-%d")) and row[1:] == ("XX", "instagram", "x"), row
    real = cc.classify
    cc.classify = lambda *args: (_ for _ in ()).throw(RuntimeError("classifier bug"))
    try:
        r = _anon.get(f"/t/{slug}", follow_redirects=False)
    finally:
        cc.classify = real
    assert r.status_code == 302 and counts(lid) == (2, 2)
    assert sql("SELECT country,in_app,ref FROM tracking_clicks WHERE tracking_link_id=:lid ORDER BY id DESC LIMIT 1",
               lid=lid)[0] == (None, None, None)
    a = analytics(lid).json()
    assert a["totals"]["clicks"] == 2 and a["came_from"] == [{"key": "", "clicks": 1}, {"key": "x", "clicks": 1}], a
    assert summary().json()["today"] == NOW.date().isoformat()


def case_gate_referer():
    lid, slug = link(gated=True)
    with turnstile():
        page = _anon.get(f"/t/{slug}", headers={"referer": "https://l.instagram.com/x"})
        assert page.status_code == 200 and 'ref:"instagram"' in page.text and page.headers["referrer-policy"] == "no-referrer"
        assert _anon.post(f"/t/{slug}/verify", json={"token": "ok", "ref": "instagram"}).status_code == 200
        assert _anon.post(f"/t/{slug}/verify", json={"token": "ok", "ref": "forged.bad"}).status_code == 200
    assert counts(lid) == (2, 2)
    assert analytics(lid).json()["came_from"] == [{"key": "", "clicks": 1}, {"key": "instagram", "clicks": 1}]


def case_verified_only_after_pass():
    lid, slug = link()
    before_verified = summary().json()["verified_clicks"]
    assert _anon.get(f"/t/{slug}", follow_redirects=False).status_code == 302
    patched = _owner.patch(f"/admin/tracking-links/{lid}", json={"bot_check": True})
    assert patched.status_code == 200, patched.text
    assert _anon.get(f"/t/{slug}", follow_redirects=False).status_code == 302  # keys unset
    assert analytics(lid).json()["totals"]["verified_clicks"] == 0, analytics(lid).json()
    assert summary().json()["verified_clicks"] == before_verified, summary().json()
    with turnstile():
        import tracking_links_api as tla
        real = tla._turnstile_passes
        async def reject(*_args):
            return False
        tla._turnstile_passes = reject
        try:
            bad = _anon.post(f"/t/{slug}/verify", json={"token": "bad"})
            assert bad.status_code == 403, bad.text
        finally:
            tla._turnstile_passes = real
        passed = _anon.post(f"/t/{slug}/verify", json={"token": "ok"})
        assert passed.status_code == 200, passed.text
    assert counts(lid) == (3, 3), counts(lid)
    assert sql("SELECT SUM(verified) FROM tracking_clicks WHERE tracking_link_id=:lid", lid=lid)[0][0] == 1
    assert analytics(lid).json()["totals"] == {"clicks": 3, "verified_clicks": 1}
    assert summary().json()["verified_clicks"] == before_verified + 1


def case_zone_and_tenancy():
    assert _owner.put("/admin/settings/preferences", json={"report_tz": "Asia/Kolkata"}).status_code == 200
    try:
        lid, _ = link()
        day = NOW.astimezone(timezone.utc).date() - timedelta(days=1)
        # 18:15Z = 23:45 IST; 18:45Z = 00:15 IST on the next day.
        at = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        seed(lid, at + timedelta(hours=18, minutes=15), app="instagram", ref="x")
        seed(lid, at + timedelta(hours=18, minutes=45), app="", ref="")
        a = analytics(lid).json()
        by = {r["day"]: r["clicks"] for r in a["series"]}
        assert by[day.isoformat()] == 1 and by[(day+timedelta(days=1)).isoformat()] == 1, by
        assert summary().json()["spark"][str(lid)][-1] == 1
        assert analytics(lid, aid=BID, client=_other).status_code == 404
        assert summary(AID, _other).status_code == 403
    finally:
        _owner.put("/admin/settings/preferences", json={})


def case_old_rows_chunks_idempotent():
    lid, _ = link()
    at = NOW - timedelta(days=1)
    for _ in range(3):
        seed(lid, at, ua="Instagram", referer="https://reddit.com/x")
    url = f"sqlite:///{_harness.DB_PATH}"
    assert asyncio.run(ts.classify_old_rows_background(url, chunk=2)) >= 3
    assert asyncio.run(ts.classify_old_rows_background(url, chunk=2)) == 0
    assert sql("SELECT COUNT(*) FROM tracking_clicks WHERE tracking_link_id=:lid AND in_app='instagram' AND ref='reddit'",
               lid=lid)[0][0] == 3
    assert analytics(lid).json()["came_from"] == [{"key": "reddit", "clicks": 3}]


def case_stats_reads_share_one_lane():
    """Owner stats reads queue on TRACKING_STATS_READ, so a burst never holds more pooled connections than its cap."""
    import server
    lid, _ = link()
    seen = {"now": 0, "max": 0}
    real = ts.get_session

    @contextlib.asynccontextmanager
    async def slow_session():
        seen["now"] += 1
        seen["max"] = max(seen["max"], seen["now"])
        try:
            await asyncio.sleep(0.05)
            async with real() as s:
                yield s
        finally:
            seen["now"] -= 1

    async def burst():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test",
                                     cookies=dict(_owner.cookies.items())) as c:
            paths = [f"/admin/tracking-links/summary?account_id={AID}"] * 4 + \
                    [f"/admin/tracking-links/{lid}/analytics?account_id={AID}&days=30"] * 4
            return await asyncio.gather(*(c.get(path) for path in paths))

    ts.get_session = slow_session
    try:
        answers = asyncio.run(burst())
    finally:
        ts.get_session = real
    assert [r.status_code for r in answers] == [200] * 8, [(r.status_code, r.text[:80]) for r in answers]
    assert seen["max"] == admission.TRACKING_STATS_READ.cap == 2, seen


_harness.run(case_clicks_classify_failure_and_clock, case_gate_referer, case_verified_only_after_pass,
             case_zone_and_tenancy, case_stats_reads_share_one_lane,
             case_old_rows_chunks_idempotent)
