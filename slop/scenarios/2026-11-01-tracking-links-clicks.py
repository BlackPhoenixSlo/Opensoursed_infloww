"""Tracking links under a click storm: every public `/t/<slug>` click is stored once and redirected to its own
target, the internal links' analytics add up, and OnlyFans' own tracking links (Growth > Tracking links) show
per-link earnings that equal the attribution rule, with one claimers walk per link however many owners read.

World: `agency_inbox` (small 3 Creators x 50 fans, medium 10 x 500) plus seed/tracking_campaigns.py: per
Creator `links` internal /t/ links with 0..40 past clicks each, `campaigns` OF tracking links (every 4th with no
subscriber, one deactivated 20 days after it opened, the oldest with 61 claimers: two claimers pages) whose
`claimed` fans each claimed 1..3 links, and those fans' ledger (`transactions` as the payouts ingest and the WS
pump write them: tracked and reversed statuses, WS rows with no net), plus a few fans who claimed nothing.
OnlyFans' /campaigns side is lib/tracking_relay.py (`of-campaigns.json`).

Load (`--users` anonymous clients, no cookie, redirects not followed): `clicks` GET /t/<slug>, open loop at
`rate` clicks/s (click k leaves at k / rate on client k % users; `--rate=0`: a closed loop, every client
clicking back to back, which measures the relay's saturation, not a fan's latency), links drawn from the seed
with uneven weights, each click a referer / user agent and the headers Cloudflare would add (`RELAY_ENV`
EDGE_PROXIES=cloudflare): X-Forwarded-For a Cloudflare server (`CF_HOPS`), CF-Connecting-IP the client's own
address (100.64.x.y). Meanwhile owners (max(3, users // 10), each its own
pool of 4; owner i at home on Creator i % n): wave 1, one Creator after another, every owner opens its
earnings at once (`GET /admin/of-tracking-links/earnings`: the first open, a cold computation that walks
every claimers page, with the others waiting on the per-account lock; in the budgeted row); the owner creates
one OF tracking link per Creator (`POST /admin/of-tracking-links`, the Create dialog: it drops the account's
60 s memo); wave 2, each owner reloads its home Creator's Links list (the
OF list and earnings at once) and opens one link's Details (`/{campaign_id}/fans`); then browsing until the
storm ends (1-3 s think, 70 % on its home Creator: `/admin/tracking-links`, `/{id}/analytics`, the Links
list, a Details).

Checks (lib/tracking_faults.py): CLICKS (rows, click_count, list == seeded + the 302s answered), CLIENT_IP (every
stored storm click's ip is one of the clients' own addresses, none a Cloudflare or proxy address), REDIRECT,
BY_DAY (per UTC day: seeded + the 302s answered that day; a 302 sent before UTC midnight and answered after
may count on either day), CREATED, EARNINGS (every link of each Creator
listed, the created ones at zero; the oracle derived here from the seed: each tracked sale of a claimer goes
to the claiming link with the latest createdAt at or before it whose window is still open,
`of_tracking_api._spend`'s rule, gross / net / fans counted / fans who spent; each link's /fans rows sum to
its figure; the run is INFRA unless each of the rule's branches occurs in the seed: a sale past a deactivated
link's end falling back, a sale before any claim, an untracked status inside a window, a fan with several
links), CLAIMERS (`GET
/__slop/tracking-calls`: one walk, a call at offset 0, per link with subscribers, of ceil(n / 50) pages; 0 for
zero-subscriber and created links). Budgets: p95 `/t/` <= 150 ms, earnings (the page's reads) <= 2 s, p95 vs
the last green run (routes with >= 20 calls in both).
UI (`UI = True`): /growth/tracking-links for the Creator the page picks, Custom redirect links opened
(screenshot `tracking-links-trigger`), a link's Analytics opened (`tracking-links-settled`): it shows the
link's stored clicks, which the API and the DB hold.

Bypasses (declared): OnlyFans' /campaigns, /campaigns/{id}/claimers and the create are lib/tracking_relay.py
(in-process, 50 ms a call, a guess; not lib/of_wire.py: this run has no OF_WIRE), the product's `_make_client`
falls back to it as for every offline Creator; `of-me.json` answers `me()` with no username, so the share
URLs are null (OF's username is cosmetic here); the /t/ slugs are custom numeric slugs (`_slugify` keeps
digits) so the recorder folds them into one `GET /t/:id` row; the past clicks, links, campaigns' claimers and
ledger are SQL in the product's shape (the WS rows' message ids name no `messages` row); the big link's
free-trial claimers are OF ids with no `fans` row; the clients are httpx, not browsers (no referer chain, no
redirect followed: the target is off-host); the click rate is the scenario's (100 / 250 clicks/s small /
medium, a guess at a bio-link burst); the Cloudflare hop is its headers alone: the clients reach the relay
straight from loopback (a trusted proxy, as the Next app is), no Traefik or Next in between. Break-it-once: tracking-click-lost-1-in-20 (CLICKS, BY_DAY);
--fault=client-addr-cdn-header-ignored (CLIENT_IP);
--fault=of-tracking-claimers-no-memo (CLAIMERS); --fault=of-tracking-spend-first-link (EARNINGS).
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import httpx

from slop.actors import ui
from slop.lib.client import Http
from slop.lib.tracking_faults import BY_DAY, CLAIMERS, CLICKS, CLIENT_IP, CREATED, EARNINGS, REDIRECT
from slop.seed import tracking_campaigns

PROFILE = "agency_inbox"
UI = True
FAULT = "tracking-click-lost-1-in-20"
RELAY_ENV = {"EDGE_PROXIES": "cloudflare"}   # the fans come through Cloudflare (deploy/ae/EDGE-CDN.md)
CF_HOPS = tuple(f"162.158.88.{i}" for i in range(1, 9))   # Cloudflare servers (inside its published ranges)
T_P95_MS = 150
EARNINGS_P95_MS = 2000
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20   # under 20 calls a p95 is the slowest of a handful
THINK_S = (1.0, 3.0)   # an owner between page actions (a guess at a human's)
TRACKED = ("cleared", "pending")
SUBS = ("subscription", "rebill")
FIGURES = ("earnings_cents", "earnings_net_cents", "net_missing_count", "fans_counted", "fans_who_spent")


def _oracle(tc: dict) -> tuple[dict[int, dict], dict[str, int]]:
    """Per OF link its FIGURES, from the seed alone; and how often each branch of the rule decided a sale."""
    claims: dict[tuple[str, int], list[tuple[datetime, datetime | None, int]]] = defaultdict(list)
    out: dict[int, dict] = {}
    per_fan: dict[int, dict[int, list[int]]] = defaultdict(dict)   # link -> fan -> [total, subs]
    for aid, rows in tc["campaigns"].items():
        for r in rows:
            start = datetime.fromisoformat(r["createdAt"][:19])
            end = datetime.strptime(r["endDate"], "%Y-%m-%d %H:%M:%S") if r.get("endDate") else None
            fans = tc["claimers"].get(r["id"], [])
            out[r["id"]] = {"earnings_cents": 0, "earnings_net_cents": 0, "net_missing_count": 0,
                            "fans_counted": len(fans)}
            for fid in fans:
                claims[(aid, fid)].append((start, end, r["id"]))
    branches = {"past_end_fell_back": 0, "before_any_claim": 0, "untracked_in_window": 0,
                "fans_with_several_links": sum(1 for v in claims.values() if len(v) > 1)}
    for aid, fid, kind, gross, net, at, status in tc["tx"]:
        mine = claims.get((aid, fid))
        if not mine:
            continue
        opened = [(s, cid, e) for s, e, cid in mine if s <= at]
        open_ = [(s, cid) for s, cid, e in opened if e is None or at < e]
        if not opened:
            branches["before_any_claim"] += status in TRACKED
            continue
        if not open_:
            continue
        if status not in TRACKED:
            branches["untracked_in_window"] += 1
            continue
        cid = max(open_)[1]
        branches["past_end_fell_back"] += max(opened)[1] != cid
        o = out[cid]
        o["earnings_cents"] += gross
        if net is None:
            o["net_missing_count"] += 1
        else:
            o["earnings_net_cents"] += net
        pf = per_fan[cid].setdefault(fid, [0, 0])
        pf[0] += gross
        pf[1] += gross if kind in SUBS else 0
    for cid, o in out.items():
        o["fans_who_spent"] = sum(1 for t, s in per_fan[cid].values() if t - s > 0)
    return out, branches


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    tc = tracking_campaigns.seed(
        w, creators, ctx.stack.tmp,
        links=ctx.param("links", w.size["tracking_links_links"]),
        campaigns=ctx.param("campaigns", w.size["tracking_links_campaigns"]),
        claimed=ctx.param("claimed", w.size["tracking_links_claimed"]))
    n_clicks = ctx.param("clicks", w.size["tracking_links_clicks"])
    rate = ctx.param("rate", {"small": 100.0, "medium": 250.0, "huge": 400.0}[ctx.scale])   # clicks/s; 0: closed loop
    links = tc["links"]
    by_slug = {l["slug"]: l for l in links}
    links_of = {aid: [l for l in links if l["account_id"] == aid] for aid in aids}
    live = {aid: [r["id"] for r in rows if r["countSubscribers"] > 0] for aid, rows in tc["campaigns"].items()}
    rng = w.rng("scenario:tracking-links-clicks")
    weights = [rng.uniform(0.2, 3.0) for _ in links]
    plan = [(rng.choices(links, weights)[0]["slug"], rng.choice(tracking_campaigns.REFERERS),
             rng.choice(tracking_campaigns.UAS)) for _ in range(n_clicks)]
    oracle, branches = _oracle(tc)
    if not all(branches.values()):   # a seed that cannot tell the rule's branches apart: no verdict
        raise RuntimeError(f"tracking seed misses a branch of the attribution rule: {branches}")
    ctx.metric("world", {"creators": len(aids), "links": len(links), "campaigns": sum(map(len, tc["campaigns"].values())),
                         "claims": sum(map(len, tc["claimers"].values())), "tx": len(tc["tx"]), "clicks": n_clicks})

    def home(i: int) -> str:
        return aids[i % len(aids)]

    def pick(aid: str, k: int) -> int | None:
        """The Creator's k-th (mod) OF link with subscribers: the one whose Details an owner opens."""
        return live[aid][k % len(live[aid])] if live[aid] else None

    # ── the storm: anonymous fans clicking /t/<slug> ───────────────────────
    answers: list[tuple[str, int, str | None, str, str]] = []   # (slug, status, location, UTC day sent, answered)
    fans = [Http(ctx.relay, ctx.rec, limits=1) for _ in range(ctx.users)]
    n_owners = max(3, ctx.users // 10)
    owners = [ctx.owner.share(limits=4) for _ in range(n_owners)]   # an owner reads <= 2 at once: nothing queues
    stop = asyncio.Event()
    ctx.rec.stage = "storm"
    t0 = time.perf_counter()

    def today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    ip_of = {id(h): f"100.64.{i // 250}.{i % 250 + 1}" for i, h in enumerate(fans)}   # a phone's CGNAT address each

    def fan_ip(h: Http) -> str:
        return ip_of[id(h)]

    async def click(h: Http, slug: str, ref: str | None, ua: str) -> None:
        sent = today()
        edge = {"x-forwarded-for": CF_HOPS[sum(map(ord, slug)) % len(CF_HOPS)], "cf-connecting-ip": fan_ip(h)}
        try:
            r = await h.get(f"/t/{slug}", headers={"user-agent": ua, **edge, **({"referer": ref} if ref else {})})
            answers.append((slug, r.status_code, r.headers.get("location"), sent, today()))
        except httpx.HTTPError:
            pass   # Http recorded it as a 599 (the stock no-5xx check); no answer, so no click expected
        h.c.cookies.clear()   # no cookie, ever

    async def closed(h: Http, it) -> None:
        for slug, ref, ua in it:
            await click(h, slug, ref, ua)

    async def paced() -> None:
        """Open loop: click k leaves at t0 + k / rate on client k % users, whatever the earlier ones did (a
        busy client queues it in its pool, and that wait is in its latency)."""
        tasks = []
        for k, (slug, ref, ua) in enumerate(plan):
            delay = t0 + k / rate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(click(fans[k % len(fans)], slug, ref, ua)))
        await asyncio.gather(*tasks)

    async def earnings(h, aid):
        return await h.get(f"/admin/of-tracking-links/earnings?account_id={aid}", timeout=60)

    async def page(h, aid, cid):
        """The Links list as the page loads it (the list and the earnings at once), then one link's Details."""
        await asyncio.gather(h.get(f"/admin/of-tracking-links?account_id={aid}", timeout=60), earnings(h, aid))
        if cid is not None:
            await h.get(f"/admin/of-tracking-links/{cid}/fans?account_id={aid}", timeout=60)

    async def browse(i: int, h) -> None:
        r = w.rng(f"scenario:tracking-links-clicks:owner:{i}")
        while True:
            try:
                await asyncio.wait_for(stop.wait(), r.uniform(*THINK_S))
                return
            except asyncio.TimeoutError:
                pass
            aid = home(i) if r.random() < 0.7 else r.choice(aids)
            await h.get(f"/admin/tracking-links?account_id={aid}")
            if links_of[aid]:
                await h.get(f"/admin/tracking-links/{r.choice(links_of[aid])['id']}/analytics?account_id={aid}")
            await page(h, aid, pick(aid, r.randrange(1 << 10)))

    if rate <= 0:
        it = iter(plan)
        storm = asyncio.gather(*(closed(h, it) for h in fans))
    else:
        storm = asyncio.ensure_future(paced())
    for aid in aids:   # wave 1: every owner opens this Creator's earnings at once, the first open among them
        await asyncio.gather(*(earnings(h, aid) for h in owners))
    created: dict[str, int] = {}
    create_bad: dict[str, int] = {}
    for aid in aids:
        r = await ctx.owner.post("/admin/of-tracking-links", json={"account_id": aid, "name": f"slop new {aid}"})
        if r.status_code == 200 and r.json().get("id"):
            created[aid] = r.json()["id"]
        else:
            create_bad[aid] = r.status_code
    ctx.check(CREATED, not create_bad, creators=len(aids), created=len(created), failed=create_bad)
    # wave 2: each owner back on its own Creator's page (the recompute after the create) and one link's Details
    await asyncio.gather(*(page(h, home(i), pick(home(i), i // len(aids))) for i, h in enumerate(owners)))
    browsers = asyncio.gather(*(browse(i, h) for i, h in enumerate(owners)))
    await storm
    storm_s = time.perf_counter() - t0
    stop.set()
    await browsers
    ctx.rec.stage = "after"
    for h in fans + owners:
        await h.aclose()

    # ── clicks: stored once per link, every answer a 302 to its own target ──
    con = w.sql()
    try:
        stored = dict(con.execute("SELECT tracking_link_id, COUNT(*) FROM tracking_clicks GROUP BY 1").fetchall())
        storm_ips = Counter(ip for (ip,) in con.execute(   # the seed's clicks are 203.0.113.x
            "SELECT ip FROM tracking_clicks WHERE ip IS NULL OR ip NOT LIKE '203.0.113.%'"))
        counter = dict(con.execute("SELECT id, click_count FROM tracking_links").fetchall())
    finally:
        con.close()
    listed: dict[int, int] = {}
    for aid in aids:
        for l in (await ctx.owner.get(f"/admin/tracking-links?account_id={aid}")).json().get("links", []):
            listed[l["id"]] = l["click_count"]
    sure: dict[str, Counter] = defaultdict(Counter)     # slug -> UTC day -> 302s sent and answered on it
    astride: dict[str, Counter] = defaultdict(Counter)  # slug -> UTC day -> 302s sent before midnight, answered after
    for s, st, _, sent, answered in answers:
        if st == 302 and sent == answered:
            sure[s][sent] += 1
        elif st == 302:
            astride[s].update((sent, answered))

    def clicks_want(l) -> tuple[Counter, Counter, int]:
        """Per UTC day the least and most clicks the link's analytics may show, and their exact total."""
        lo = Counter(l["by_day"]) + sure[l["slug"]]
        return lo, lo + astride[l["slug"]], lo.total() + astride[l["slug"]].total() // 2

    off, lost = {}, 0
    for l in links:
        want = clicks_want(l)[2]
        got = (stored.get(l["id"], 0), counter.get(l["id"]), listed.get(l["id"]))
        lost += want - got[0]
        if got != (want, want, want):
            off[l["slug"]] = {"want": want, "rows": got[0], "click_count": got[1], "listed": got[2]}
    ctx.check(CLICKS, not off, links=len(links), sent=n_clicks, redirected=sum(st == 302 for _, st, *_ in answers),
              lost=lost, off=len(off), sample=dict(list(off.items())[:5]))
    fan_ips = {fan_ip(h) for h in fans}
    foreign = {ip: n for ip, n in storm_ips.items() if ip not in fan_ips}
    ctx.check(CLIENT_IP, bool(storm_ips) and not foreign, stored=storm_ips.total(), fans=len(fan_ips),
              foreign=dict(list(foreign.items())[:5]))
    bad_redirect = [(s, st, loc) for s, st, loc, *_ in answers if st != 302 or loc != by_slug[s]["target"]]
    ctx.check(REDIRECT, bool(answers) and not bad_redirect, sent=n_clicks, answers=len(answers),
              bad=len(bad_redirect), sample=bad_redirect[:5])

    # ── analytics: by-day == seeded + the storm's 302s per UTC day ────────
    reader = ctx.owner.share(limits=20)

    async def analytics(l):
        r = await reader.get(f"/admin/tracking-links/{l['id']}/analytics?account_id={l['account_id']}")
        return l, (r.json() if r.status_code == 200 else {"status": r.status_code})

    by_day_bad = []
    for l, a in await asyncio.gather(*(analytics(l) for l in links)):
        lo, hi, total = clicks_want(l)
        got = Counter({d["day"]: d["clicks"] for d in a.get("by_day", [])})
        days_off = {d: (got[d], lo[d], hi[d]) for d in sorted(got.keys() | hi.keys()) if not lo[d] <= got[d] <= hi[d]}
        if days_off or got.total() != total or a.get("total_clicks") != total:
            by_day_bad.append({"slug": l["slug"], "total": a.get("total_clicks"), "series_total": got.total(),
                               "want_total": total, "days_off (got, lo, hi)": days_off})
    ctx.check(BY_DAY, not by_day_bad, links=len(links), bad=len(by_day_bad), sample=by_day_bad[:5],
              astride_midnight=sum(c.total() // 2 for c in astride.values()))

    # ── OF earnings per link == the oracle; /fans rows sum to it ──────────
    wrong, fans_bad, ids_off, unavailable = {}, {}, {}, []
    for aid in aids:
        body = (await reader.get(f"/admin/of-tracking-links/earnings?account_id={aid}", timeout=60)).json()
        if not body.get("available"):
            unavailable.append(aid)
            continue
        want_ids = {r["id"] for r in tc["campaigns"][aid]} | ({created[aid]} if aid in created else set())
        got_ids = {row["id"] for row in body["links"]}
        if got_ids != want_ids:
            ids_off[aid] = {"missing": sorted(want_ids - got_ids)[:5], "unexpected": sorted(got_ids - want_ids)[:5]}
        for row in body["links"]:
            want = dict.fromkeys(FIGURES, 0) if row["id"] == created.get(aid) else oracle.get(row["id"])
            got = {k: row[k] for k in FIGURES}
            if got != want:
                wrong[row["id"]] = {"got": got, "want": want}
        for cid in live[aid]:
            fb = (await reader.get(f"/admin/of-tracking-links/{cid}/fans?account_id={aid}", timeout=60)).json()
            tot = sum(f["total_cents"] for f in fb.get("fans", []))
            if tot != oracle[cid]["earnings_cents"] or len(fb.get("fans", [])) != oracle[cid]["fans_counted"]:
                fans_bad[cid] = {"fans_sum": tot, "fans": len(fb.get("fans", [])),
                                 "want": oracle[cid]["earnings_cents"], "want_fans": oracle[cid]["fans_counted"]}
    ctx.check(EARNINGS, not (wrong or fans_bad or ids_off or unavailable),
              links=len(oracle) + len(created), wrong=len(wrong), sample=dict(list(wrong.items())[:4]),
              ids_off=ids_off, fans_bad=len(fans_bad), fans_sample=dict(list(fans_bad.items())[:3]),
              unavailable=unavailable, branches=branches,
              oracle_gross=sum(o["earnings_cents"] for o in oracle.values()))

    # ── claimers single-flight: one walk per link, every page once ─────────
    calls = (await ctx.owner.get("/__slop/tracking-calls")).json()["claimers"]
    walks = {k: v.count(0) for k, v in calls.items()}
    subs = {f"{aid}:{r['id']}": r["countSubscribers"] for aid, rows in tc["campaigns"].items() for r in rows}
    want = {k: int(n > 0) for k, n in subs.items()} | {f"{aid}:{cid}": 0 for aid, cid in created.items()}
    bad = {k: {"walks": walks.get(k, 0), "want": want.get(k)} for k in want.keys() | walks.keys()
           if walks.get(k, 0) != want.get(k)}
    pages = {k: walks[k] * math.ceil(subs.get(k, 0) / tracking_campaigns.CLAIMERS_PAGE) for k in calls}
    pages_bad = {k: {"pages": len(v), "want": pages[k]} for k, v in calls.items() if len(v) != pages[k]}
    ctx.check(CLAIMERS, not bad and not pages_bad, owners=n_owners, links_with_subs=sum(map(len, live.values())),
              bad=len(bad), sample=dict(sorted(bad.items())[:6]), pages_bad=pages_bad,
              most_claimers=max(subs.values()), most_pages=max(map(len, calls.values()), default=0),
              claimer_pages=sum(map(len, calls.values())))

    # ── budgets ───────────────────────────────────────────────────────────
    routes = ctx.rec.summary("storm")
    t_route, e_route = "GET /t/:id", "GET /admin/of-tracking-links/earnings"
    for route, budget in ((t_route, T_P95_MS), (e_route, EARNINGS_P95_MS)):
        name = f"p95 {route} <= {budget} ms under the storm"
        if route in routes:
            ctx.check(name, routes[route]["p95_ms"] <= budget, budget=True, p95=routes[route]["p95_ms"],
                      n=routes[route]["n"])
        else:
            ctx.skip(name, "no samples")
    ctx.metric("load", {"clicks": n_clicks, "fans": len(fans), "owners": n_owners, "rate": rate, "storm_s": round(storm_s, 2),
                        "clicks_per_s": round(n_clicks / storm_s, 1) if storm_s else None})
    vs_last = [r for r in (t_route, e_route, "GET /admin/of-tracking-links", "GET /admin/of-tracking-links/:id/fans",
                           "GET /admin/tracking-links", "GET /admin/tracking-links/:id/analytics") if r in routes]
    key = {e_route: f"{e_route} incl. first opens"}   # runs before wave 1 joined the row timed warm reads only
    ctx.metric("p95_vs_last_green", {key.get(r, r): routes[r]["p95_ms"] for r in vs_last})
    ctx.metric("p95_vs_last_green_n", {key.get(r, r): routes[r]["n"] for r in vs_last})

    # ── UI: Growth > Tracking links, a redirect link's Analytics ─────────
    if ctx.app:
        await _ui(ctx, tc, stored)
    else:
        ctx.skip("UI: a redirect link's Analytics shows its stored clicks (== API == DB)", "--no-ui")
    await reader.aclose()


async def _ui(ctx, tc, stored) -> None:
    name = "UI: a redirect link's Analytics shows its stored clicks (== API == DB)"
    creator_of = {r["campaignName"]: aid for aid, rows in tc["campaigns"].items() for r in rows}
    async with ui.owner_browser(ctx) as page:
        seen_analytics: list[dict] = []

        async def on_response(resp):
            if re.search(r"/admin/tracking-links/\d+/analytics", resp.url) and resp.status == 200:
                try:
                    seen_analytics.append(await resp.json())
                except Exception:  # noqa: BLE001
                    pass

        page.on("response", on_response)
        await page.goto(f"{ctx.app}/growth/tracking-links", wait_until="domcontentloaded")
        await page.get_by_text(re.compile(r"OF link 0$")).first.wait_for(timeout=90_000)
        shown = (await page.get_by_text(re.compile(r"OF link 0$")).first.inner_text()).strip()
        aid = creator_of.get(shown)
        if aid is None:
            ctx.check(name, False, shown=shown, reason="the page's first OF link is none of the seeded ones")
            return
        await page.get_by_role("button", name=re.compile("Custom redirect links")).click()
        api = (await ctx.owner.get(f"/admin/tracking-links?account_id={aid}")).json().get("links", [])
        first = api[0] if api else None
        if first is None:
            ctx.check(name, False, creator=aid, reason="no redirect links listed")
            return
        row = page.locator("li").filter(has=page.get_by_text(first["name"], exact=True)).first
        await row.wait_for(timeout=30_000)
        await ui.shot(ctx, page, "tracking-links-trigger")
        await row.get_by_role("button", name="Analytics").click()
        want = stored.get(first["id"], 0)
        ok_text = True
        try:
            await page.get_by_text(re.compile(rf"^\s*{want}\s+total clicks")).first.wait_for(timeout=30_000)
        except Exception:  # noqa: BLE001
            ok_text = False
        await ui.shot(ctx, page, "tracking-links-settled")
        got_api = seen_analytics[-1]["total_clicks"] if seen_analytics else None
        ctx.check(name, ok_text and got_api == want, creator=aid, link=first["id"], slug=first["slug"],
                  db_rows=want, api_total=got_api, ui_text=ok_text)
