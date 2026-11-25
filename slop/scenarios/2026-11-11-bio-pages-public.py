from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from typing import NamedTuple
from urllib.parse import quote, unquote, urlsplit

import httpx

from slop.actors import bio_visitor, fan_dm, manager, ui
from slop.actors.bio_visitor import BOOT, L_ASSET, L_JSON, L_PAGE, L_PING, L_REVEAL, STUB_MARK
from slop.lib.bio_faults import (BIO_COUNTS, BIO_ESCAPE_TAP, BIO_ISOLATION, BIO_LIMIT, BIO_NO_5XX, BIO_NO_LEAK,
                                 BIO_NO_OFFHOST_LOAD,
                                 BIO_PAGE, BIO_PROFILE_JSON, BIO_REVEAL, BIO_SHARED_DB_NO_LOCK, BIO_TLS_ASK)
from slop.lib.client import Http
from slop.seed import bio_pages, tracking_campaigns

PROFILE = "agency_inbox"
UI = True
FAULT = "bio-click-lost-1-in-20"
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20
SIDECARS = {"bio": ("slop/lib/bio.py", "BIO_PORT", "/internal/healthz")}
BIO_PORT = 0
LIMIT = 30
# EDGE_PROXIES stands in for Cloudflare: the bio service believes location headers only from an edge hop (client_addr.from_edge)
RELAY_ENV = {"BIO_FLUSH_SECONDS": "0.5", "BIO_ESCAPE_TAP": "1", "BIO_PRIMARY_HOSTS": "127.0.0.1,localhost,bio.slop.test",
             "BIO_REVEAL_LIMIT_PER_MINUTE": str(LIMIT), "EDGE_PROXIES": "100.64.0.0/10"}
PAGE_P95_MS, JSON_P95_MS, WRITE_P95_MS = 60, 80, 150
SHARED_REDIRECT_P95_MS, SHARED_DM_P95_MS = 150, 300
UI_NAME = ("UI: a bio page renders its Links, an 18+ tap opens the age gate, Continue goes to the oracle's "
           "destination and bio_daily counts the click")
_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS {v} like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
class EscapeCase(NamedTuple):
    name: str
    ua: str
    flag: bool
    shown: bool
    armed: bool
    shot: bool = False


ESCAPE_CASES = (
    EscapeCase("ios17-instagram", _IOS.format(v="17_0") + " Instagram 300.0.0.0 (iPhone14,2; iOS 17_0; en_US)", True, True, True, True),
    EscapeCase("ios17-instagram-flag-off", _IOS.format(v="17_0") + " Instagram 300.0.0.0 (iPhone14,2; iOS 17_0; en_US)", False,
     True, False),
    EscapeCase("ios16-instagram", _IOS.format(v="16_6") + " Instagram 300.0.0.0 (iPhone14,2; iOS 16_6; en_US)", True, True, False),
    EscapeCase("ios17-tiktok", _IOS.format(v="17_0") + " musical_ly_33.0.0", True, True, False),
    EscapeCase("android-instagram", "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Mobile Safari/537.36 Instagram 300.0.0.0 Android", True, True, False),
    EscapeCase("ios17-safari", _IOS.format(v="17_0").replace("Mobile/", "Version/17.0 Mobile/") + " Safari/604.1", True, False,
     False),
)
ESCAPE_CODE = "4242"
EXTBROWSER = "instagram://extbrowser/?url="


async def run(ctx) -> None:
    global BIO_PORT
    BIO_PORT = ctx.stack.extra_ports["BIO_PORT"]
    if ctx.stack.shards > 1:
        raise RuntimeError("bio-pages-public runs on one shard only (one bio sidecar uses shard 0)")
    w = await ctx.build(PROFILE)
    bp = bio_pages.seed(w, w.data["creators"], profiles=ctx.param("profiles", w.size["bio_pages_profiles"]),
                        links=ctx.param("links", w.size["bio_pages_links"]),
                        files_dir=ctx.stack.shard_svc[0] / "bio_files")
    tl = tracking_campaigns.seed(w, w.data["creators"], ctx.stack.tmp, links=1, campaigns=1, claimed=0)["links"]
    n_visits = ctx.param("visits", w.size["bio_pages_visits"])
    rate = ctx.param("rate", {"small": 50.0, "medium": 150.0, "huge": 300.0}[ctx.scale])
    reveal_share = ctx.param("reveal_share", 0.4)
    n_abusers = ctx.param("abusers", 3)
    profiles = bp["profiles"]
    base = f"http://127.0.0.1:{BIO_PORT}"
    rng = w.rng("scenario:bio-pages-public")
    vis = bio_visitor.Visitors(ctx.rec, base, ctx.users)
    plan = bio_visitor.plan(rng, profiles, n_visits, reveal_share)
    call = vis.call

    probe = vis.clients[0]
    roots_bad = []
    for host in ("127.0.0.1", "bio.slop.test", bio_pages.SPARE, profiles[1]["pending"] or "nobody.bio.slop.test"):
        r = await call(probe, "bio probe root", "GET", "/", headers={"Host": host})
        if r is None or r.status_code != 200 or STUB_MARK not in r.text or BOOT in r.text:
            roots_bad.append({"host": host, "status": getattr(r, "status_code", None)})
    vis.page_bad.extend(roots_bad)

    tls_rows = [("", 400), ("?domain=", 400), ("?domain=bad%20host!", 400), ("?domain=localhost", 200),
                ("?domain=bio.slop.test", 200), (f"?domain={bio_pages.SPARE}", 200),
                ("?domain=nobody.bio.slop.test", 404)]
    tls_rows += [(f"?domain={p['live']}", 200) for p in profiles if p["live"]]
    tls_rows += [(f"?domain={p['pending']}", 404) for p in profiles if p["pending"]]
    tls_bad = {}
    for q, want in tls_rows:
        r = await call(probe, "bio probe tls-ask", "GET", "/internal/tls-ask" + q, expect=(want,) if want == 404 else ())
        if r is None or r.status_code != want or r.content != b"":
            tls_bad[q] = {"want": want, "got": getattr(r, "status_code", None)}
    ctx.check(BIO_TLS_ASK, not tls_bad, rows=len(tls_rows), bad=tls_bad)

    iso_bad = []
    u0 = profiles[0]
    for path in ("/livez", "/admin/accounts", "/auth/me", "/openapi.json", "/docs", "/t/123"):
        r = await call(probe, "bio probe isolation", "GET", path)
        if r is None or r.status_code != 200 or BOOT not in r.text or "server" in r.headers:
            iso_bad.append({"port": "bio", "path": path, "status": getattr(r, "status_code", None)})
    r = await call(probe, "bio probe isolation", "POST", "/admin/login", expect=(404,), json={"username": "x", "password": "y"})
    if r is None or (r.status_code, r.content) != (404, b"404 Not Found"):
        iso_bad.append({"port": "bio", "path": "POST /admin/login", "status": getattr(r, "status_code", None)})
    relay = Http(ctx.relay, ctx.rec, limits=1, prefix="isolation ")
    for method, path in (("GET", f"/api/profiles/{u0['username']}.json"), ("POST", f"/v/{u0['username']}"),
                         ("GET", f"/.netlify/functions/reveal?id={u0['links'][0]['link_id']}"),
                         ("GET", f"/{u0['username']}"), ("GET", "/internal/tls-ask?domain=localhost")):
        r = await relay.request(method, path, expect=(404,))
        if r.status_code in (200, 204) and (not r.content or "slopdest-" in r.text or BOOT in r.text
                                            or r.content == u0["json"] or "realUrl" in r.text):
            iso_bad.append({"port": "relay", "path": f"{method} {path}", "status": r.status_code})
    await relay.aclose()
    ctx.check(BIO_ISOLATION, not iso_bad, bad=iso_bad)

    into = time.time() % 60
    if into > 45:
        await asyncio.sleep(60 - into + 0.2)
    ctx.rec.stage = "storm"
    t0 = time.perf_counter()
    stop = asyncio.Event()
    click_rate = ctx.param("shared_click_rate", {"small": 60.0, "medium": 120.0, "huge": 200.0}[ctx.scale])

    async def open_loop():
        tasks = []
        for k, v in enumerate(plan):
            delay = t0 + k / rate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(vis.visit(k, v)))
        await asyncio.gather(*tasks)

    async def closed_loop():
        it = iter(enumerate(plan))

        async def worker():
            for k, v in it:
                await vis.visit(k, v)
        await asyncio.gather(*(worker() for _ in vis.clients))

    async def relay_writes():
        fan_targets = [dict(w.data["fans"][c["id"]][0], account_id=c["id"]) for c in w.data["creators"]]
        relay_http = Http(ctx.relay, ctx.rec, limits=20, prefix="bio shared db ")
        click_results: list[tuple[int, int]] = []

        async def redirect_clicks():
            async def one(k):
                link = tl[k % len(tl)]
                try:
                    r = await relay_http.get(f"/t/{link['slug']}")
                    status = r.status_code
                except httpx.HTTPError:
                    status = 599
                click_results.append((link["id"], status))

            tasks = []
            k = 0
            while not stop.is_set():
                tasks.append(asyncio.create_task(one(k)))
                k += 1
                try:
                    await asyncio.wait_for(stop.wait(), 1 / click_rate)
                except asyncio.TimeoutError:
                    pass
            await asyncio.gather(*tasks)

        try:
            dm_task = asyncio.create_task(fan_dm.serial(relay_http, fan_targets, 1_000_000,
                                                        rate=ctx.param("shared_dm_rate", 20.0),
                                                        text="bio shared db", stop=stop))
            await redirect_clicks()
            dms = await dm_task
            relay_stats = await manager.quiesce(relay_http)
        finally:
            await relay_http.aclose()
        return click_results, dms, relay_stats

    relay_task = asyncio.create_task(relay_writes())
    try:
        await asyncio.gather(*(vis.abuser(i, profiles, LIMIT) for i in range(n_abusers)),
                             open_loop() if rate > 0 else closed_loop())
    except BaseException:
        stop.set()
        relay_task.cancel()
        await asyncio.gather(relay_task, return_exceptions=True)
        raise
    stop.set()
    redirects, dms, relay_stats = await relay_task
    storm_s = time.perf_counter() - t0
    ctx.rec.stage = "after"

    views_ok, clicks_ok = vis.views_ok, vis.clicks_ok
    want_v, want_c = len(views_ok), len(clicks_ok)
    past_v = sum(v for v, _ in bp["past"].values())
    past_c = sum(c for _, c in bp["past"].values())
    con = w.sql()
    try:
        deadline = time.monotonic() + 8
        while True:
            tv, tc = con.execute("SELECT COALESCE(SUM(views),0), COALESCE(SUM(clicks),0) FROM bio_daily").fetchone()
            if (tv, tc) == (past_v + want_v, past_c + want_c) or time.monotonic() > deadline:
                break
            await asyncio.sleep(0.2)
        rows = con.execute("SELECT profile_id, link_id, day, SUM(views), SUM(clicks) FROM bio_daily "
                           "GROUP BY 1, 2, 3").fetchall()
    finally:
        con.close()
    got = {(pid, lid, day): (v, c) for pid, lid, day, v, c in rows}
    off = bio_visitor.count_bounds(bp["past"], views_ok, clicks_ok, got)
    totals = (tv - past_v, tc - past_c)
    ctx.check(BIO_COUNTS, not off and totals == (want_v, want_c), pings_204=want_v, reveals_200=want_c,
              stored_views=totals[0], stored_clicks=totals[1], off=len(off), sample=dict(list(off.items())[:5]))

    con = w.sql()
    try:
        links_now = dict(con.execute("SELECT id, click_count FROM tracking_links").fetchall())
        clicks_now = dict(con.execute("SELECT tracking_link_id, COUNT(*) FROM tracking_clicks GROUP BY 1").fetchall())
        sent_ids = {d["message_id"] for d in dms}
        deadline = time.monotonic() + 8
        while True:
            stored_ids = {mid for (mid,) in con.execute(
                "SELECT message_id FROM messages WHERE message_id BETWEEN ? AND ?",
                (fan_dm.INJECT_ID_BASE, fan_dm.INJECT_ID_BASE + 10**9))}
            if sent_ids <= stored_ids or time.monotonic() > deadline:
                break
            await asyncio.sleep(0.2)
    finally:
        con.close()
    answered = Counter(lid for lid, status in redirects if status == 302)
    redirect_bad = [link["id"] for link in tl if
                    links_now.get(link["id"]) != link["seeded"].total() + answered[link["id"]] or
                    clicks_now.get(link["id"]) != link["seeded"].total() + answered[link["id"]]]
    lock_lines = [line[:200] for path in (ctx.out / "relay.log",)
                  for line in (path.read_text(errors="replace").splitlines() if path.exists() else [])
                  if "database is locked" in line.lower()]
    ctx.check(BIO_SHARED_DB_NO_LOCK, not redirect_bad and len(answered) > 0 and
              all(status == 302 for _, status in redirects) and len(dms) > 0 and
              all(d["status"] < 300 for d in dms) and sent_ids <= stored_ids and
              not relay_stats.get("timed_out") and not lock_lines,
              redirects=len(redirects), redirect_bad=redirect_bad[:5], dms=len(dms),
              missing_dms=len(sent_ids - stored_ids), relay_stats=relay_stats, lock_lines=lock_lines[:5])

    ctx.check(BIO_PAGE, not vis.page_bad, visits=n_visits, bad=vis.page_bad[:10])
    ctx.check(BIO_PROFILE_JSON, not vis.json_bad, bad=vis.json_bad[:5])
    ctx.check(BIO_REVEAL, bool(clicks_ok) and not vis.reveal_bad, reveals=sum(v["link"] is not None for v in plan),
              reveal_ok=want_c, bad=vis.reveal_bad[:10])
    log_hits = [ln[:200] for name in ("bio.log", "relay.log")
                for log in (ctx.out / name,)
                for ln in (log.read_text(errors="replace").splitlines() if log.exists() else [])
                if "slopdest-" in ln]
    ctx.check(BIO_NO_LEAK, not vis.leaks and not log_hits, answers=vis.leaks[:10], log_lines=log_hits[:5])
    abuse_bad = [a for a in vis.abuse if not (a["cross_403"] == 5 and
                                          a["minute_ok"] and
                                          not a["other"] and a["refused_body_ok"])]
    ctx.check(BIO_LIMIT, len(vis.abuse) == n_abusers and not abuse_bad and not vis.visitor_refused, limit=LIMIT,
              abusers=vis.abuse, visitors_refused=vis.visitor_refused[:10])
    fives = sum(n for s, n in vis.status.items() if s >= 500)
    ctx.check(BIO_NO_5XX, fives == 0, count=fives, statuses=dict(vis.status))

    routes = ctx.rec.summary("storm")
    for route, budget in (("bio shared db GET /t/:id", SHARED_REDIRECT_P95_MS),
                          ("bio shared db POST /__slop/of-ws-frame", SHARED_DM_P95_MS)):
        row = routes.get(route)
        ctx.check(f"p95 {route} <= {budget} ms under the storm", bool(row) and row["p95_ms"] <= budget,
                  budget=True, p95=row["p95_ms"] if row else None, n=row["n"] if row else 0)
    for route, budget in ((L_PAGE, PAGE_P95_MS), (L_JSON, JSON_P95_MS), (L_PING, WRITE_P95_MS),
                          (L_REVEAL, WRITE_P95_MS)):
        name = f"p95 {route} <= {budget} ms under the storm"
        if route in routes:
            ctx.check(name, routes[route]["p95_ms"] <= budget, budget=True, p95=routes[route]["p95_ms"],
                      n=routes[route]["n"])
        else:
            ctx.skip(name, "no samples")
    vs_last = [r for r in (L_PAGE, L_JSON, L_PING, L_REVEAL, L_ASSET) if r in routes]
    ctx.metric("p95_vs_last_green", {r: routes[r]["p95_ms"] for r in vs_last})
    ctx.metric("p95_vs_last_green_n", {r: routes[r]["n"] for r in vs_last})
    ctx.metric("load", {"visits": n_visits, "clients": len(vis.clients), "rate": rate, "abusers": n_abusers,
                        "storm_s": round(storm_s, 2), "visits_per_s": round(n_visits / storm_s, 1) if storm_s else None,
                        "profiles": len(profiles), "links": sum(len(p["links"]) for p in profiles)})
    await vis.aclose()

    if ctx.app:
        await _ui(ctx, w, profiles)
        await _escape_ui(ctx, profiles)
    else:
        ctx.skip(UI_NAME, "--no-ui")
        ctx.skip(BIO_NO_OFFHOST_LOAD, "--no-ui")
        ctx.skip(BIO_ESCAPE_TAP, "--no-ui")


async def _ui(ctx, w, profiles) -> None:
    p = next(p for p in profiles if any(lk["is_adult"] for lk in p["links"]))
    link = next(lk for lk in p["links"] if lk["is_adult"])
    want = bio_visitor.want_url(link, bio_visitor.tid_for(link, None), "US", "")
    day = bio_visitor.day()

    def clicks() -> int:
        con = w.sql()
        try:
            return con.execute("SELECT COALESCE(SUM(clicks),0) FROM bio_daily WHERE profile_id = ? AND link_id = ? "
                               "AND day = ?", (p["id"], link["id"], day)).fetchone()[0]
        finally:
            con.close()

    before = clicks()
    nav = rendered = gate = False
    nav_url = None
    offhost_aborted = []
    offhost_subresources = []
    async with ui.owner_browser(ctx, viewport=(390, 844), touch=True) as page:
        page.on("request", lambda r: offhost_subresources.append(r.url)
                if urlsplit(r.url).hostname not in ("127.0.0.1", "localhost") and not r.is_navigation_request()
                else None)
        await page.goto(f"http://127.0.0.1:{BIO_PORT}/{p['username']}", wait_until="domcontentloaded")
        title = page.locator("#linksContainer").get_by_text(link["title"], exact=True).first
        try:
            await title.wait_for(timeout=30_000)
            rendered = await page.locator("#displayName").inner_text() == json.loads(p["json"])["profile"]["displayName"]
        except Exception:  # noqa: BLE001
            pass
        await ui.shot(ctx, page, "bio-pages-trigger")
        if rendered:
            await title.tap()
            try:
                await page.locator("#overlay.active").wait_for(timeout=10_000)
                gate = True
            except Exception:  # noqa: BLE001
                pass
            await page.wait_for_timeout(400)
            await ui.shot(ctx, page, "bio-pages-settled")
            if gate:
                try:
                    async with page.expect_request(lambda r: r.url.startswith("https://dest.slop.test/"),
                                                   timeout=15_000) as req:
                        await page.locator("#continueBtn").tap()
                    nav_url = (await req.value).url
                    nav = nav_url == want
                except Exception:  # noqa: BLE001
                    pass
                for _ in range(50):
                    if any(urlsplit(u).hostname == urlsplit(want).hostname for u in page.slop["offhost_aborted"]):
                        break
                    await asyncio.sleep(0.1)
        offhost_aborted = list(page.slop["offhost_aborted"])
    after = before
    for _ in range(40):
        after = clicks()
        if after > before:
            break
        await asyncio.sleep(0.2)
    count_ok = after == before + 1 or (ctx.fault == FAULT and after == before)
    ctx.check(UI_NAME, rendered and gate and nav and count_ok, user=p["username"], link=link["link_id"],
              rendered=rendered, age_gate=gate, navigated=re.sub(r"slopdest-.*", "slopdest-…", nav_url or ""),
              nav_matches_oracle=nav, clicks_before=before, clicks_after=after)
    destination_host = urlsplit(want).hostname
    only_destination_host = bool(offhost_aborted) and all(urlsplit(u).hostname == destination_host for u in offhost_aborted)
    ctx.check(BIO_NO_OFFHOST_LOAD, rendered and only_destination_host and not offhost_subresources,
              aborted=[re.sub(r"slopdest-.*", "slopdest-…", u) for u in offhost_aborted],
              offhost_subresources=[re.sub(r"slopdest-.*", "slopdest-…", u) for u in offhost_subresources],
              rendered=rendered, only_seeded_destination_host=only_destination_host)


async def _escape_ui(ctx, profiles) -> None:
    p = next((p for p in profiles if p["avatar"]), None)
    if p is None:
        ctx.check(BIO_ESCAPE_TAP, False, reason="the seed gave no Escape Mode Profile an avatar")
        return
    path = f"/{p['username']}/{ESCAPE_CODE}"
    url = f"http://127.0.0.1:{BIO_PORT}{path}"
    rows = {}
    navs: list[str] = []
    reveals: list[str] = []
    flipped: list[int | str] = []

    async def flag_off(route):
        try:
            resp = await route.fetch()
            body = await resp.text()
        except Exception as e:  # noqa: BLE001
            flipped.append(f"fetch failed: {type(e).__name__}")
            await route.abort()
            return
        flipped.append(body.count('data-escape-tap="1"'))
        await route.fulfill(response=resp, body=body.replace('data-escape-tap="1"', 'data-escape-tap="0"'))

    def on_request(r):
        if r.is_navigation_request():
            navs.append(r.url)
        elif "/.netlify/functions/reveal" in r.url:
            reveals.append(r.url)

    async with ui.owner_browser(ctx, viewport=(390, 844), touch=True) as page:
        cdp = await page.context.new_cdp_session(page)
        page.on("request", on_request)

        async def _escape_case(page, case: EscapeCase) -> dict:
            await cdp.send("Emulation.setUserAgentOverride", {"userAgent": case.ua})
            if not case.flag:
                await page.route(url, flag_off)
            navs.clear()
            reveals.clear()
            row: dict = {"fails": []}
            try:
                await page.goto(url, wait_until="domcontentloaded")
                if case.shown:
                    await page.locator("#igOverlay.active").wait_for(timeout=15_000)
                else:
                    await page.locator("#displayName").get_by_text(json.loads(p["json"])["profile"]["displayName"],
                                                                   exact=True).wait_for(timeout=15_000)
                await page.wait_for_function("() => { const a = document.getElementById('avatar');"
                                             " return a.complete && a.naturalWidth > 0; }", timeout=10_000)
                await page.wait_for_timeout(1_000)
                host = await page.evaluate("location.host")
                href = await page.locator("#igCard").get_attribute("href")
                flag = await page.locator("#igCard").get_attribute("data-escape-tap")
                backdrop = await page.evaluate("""() => {
                    const overlay = document.getElementById('igOverlay');
                    const s = getComputedStyle(overlay, '::before');
                    return {image: s.backgroundImage, filter: s.filter, content: s.content,
                            display: getComputedStyle(overlay).display};
                }""")
                avatar = json.loads(p["json"])["profile"]["avatarUrl"]
                row.update(overlay=await page.locator("#igOverlay.active").count() == 1, href=href,
                           flag=flag, load_navs=list(navs[1:]), first_nav=list(navs[:1]),
                           backdrop=backdrop)
                target = f"https://{host}{path}"
                want = EXTBROWSER + quote(target, safe="-_.!~*'()") if case.armed else None
                decoded_host = (urlsplit(unquote(href[len(EXTBROWSER):])).netloc == host
                                if href and href.startswith(EXTBROWSER) else False)
                if case.shot:
                    await ui.shot(ctx, page, "bio-escape-card-phone")
                navs.clear()
                if row["overlay"]:
                    for _ in range(2):
                        await page.locator("#igCard").tap()
                        await page.wait_for_timeout(300)
                row["tap_navs"] = list(navs)
                row["reveals"] = list(reveals)
                checks = {
                    "overlay": row["overlay"] == case.shown,
                    "href": href == want,
                    "first_nav": row["first_nav"] == [url],
                    "load_navs": not row["load_navs"],
                    "reveals": not reveals,
                    "flag": flag == str(int(case.flag)),
                    "backdrop_image": avatar in backdrop["image"],
                    "backdrop_blur": "blur(" in backdrop["filter"],
                    "backdrop_content": backdrop["content"] != "none",
                    "overlay_display": not case.shown or backdrop["display"] != "none",
                    "tap_navs": row["tap_navs"] == ([want] * 2 if case.armed else []),
                    "page_host": not case.armed or decoded_host,
                    "flag_rewrite": case.flag or flipped[-1:] == [1],
                }
                row["fails"] = [name for name, passed in checks.items() if not passed]
            except Exception as e:  # noqa: BLE001
                row["error"] = f"{type(e).__name__}: {str(e)[:160]}"
                row["fails"] = ["exception"]
            finally:
                if not case.flag:
                    await page.unroute(url, flag_off)
            return row

        for case in ESCAPE_CASES:
            rows[case.name] = await _escape_case(page, case)
    bad = {name: row["fails"] for name, row in rows.items() if row["fails"]}
    ctx.check(BIO_ESCAPE_TAP, not bad, user=p["username"], path=path, bad=bad, cases=rows)
