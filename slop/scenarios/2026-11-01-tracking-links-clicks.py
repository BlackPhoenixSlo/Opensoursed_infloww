"""Tracking links under a click storm: every public `/t/<slug>` click is stored once and redirected to its own
target, the internal links' analytics add up, and OnlyFans' own tracking links (Growth > Tracking links) show
per-link earnings that equal the attribution rule, with one claimers walk per link however many owners read.

World: `agency_inbox` (small 3 Creators x 50 fans, medium 10 x 500) plus seed/tracking_campaigns.py: per
Creator `links` internal /t/ links with 1..40 past clicks each (hand-labelled referer / user agent / country,
one at least between 00:00 and 04:00 UTC, else INFRA), one `hot` link with `hot_per_day` clicks a day over 90
days (small 200, medium 3,500, huge 5,000: each medium hot link has 315,000 raw rows), their raw label columns, including NULL old rows,
`campaigns` OF tracking links (every 4th with no
subscriber, one deactivated 20 days after it opened, the oldest with 61 claimers: two claimers pages) whose
`claimed` fans each claimed 1..3 links, and those fans' ledger (`transactions` as the payouts ingest and the WS
pump write them: tracked and reversed statuses, WS rows with no net), plus a few fans who claimed nothing.
OnlyFans' /campaigns side is lib/tracking_relay.py (`of-campaigns.json`).

Report zone: the owner's `report_tz` is America/New_York (PUT before the storm), so every stats day is a New
York day; the 14 seeded days span the 2026-11-01 DST end.

Load (`--users` anonymous clients, no cookie, redirects not followed): `clicks` GET /t/<slug>, open loop at
`rate` clicks/s (click k leaves at k / rate on client k % users; `--rate=0`: a closed loop, every client
clicking back to back, which measures the relay's saturation, not a fan's latency), links drawn from the seed
with uneven weights, each click a referer / user agent / country and the headers Cloudflare would add
(`RELAY_ENV` EDGE_PROXIES=cloudflare): X-Forwarded-For a Cloudflare server (`CF_HOPS`), CF-Connecting-IP the
client's own address (100.64.x.y), CF-IPCountry the plan's country (none for None); 1 in 20 (`SPOOF_SHARE`)
skips Cloudflare (X-Forwarded-For its own address) with a forged CF-IPCountry, which must be filed XX. Meanwhile owners (max(3, users // 10), each its own
pool of 4; owner i at home on Creator i % n): wave 1, one Creator after another, every owner opens its
earnings at once (`GET /admin/of-tracking-links/earnings`: the first open, a cold computation that walks
every claimers page, with the others waiting on the per-account lock; in the budgeted row); the owner creates
one OF tracking link per Creator (`POST /admin/of-tracking-links`, the Create dialog: it drops the account's
60 s memo); wave 2, each owner reloads its home Creator's Links list (the
OF list and earnings at once) and opens one link's Details (`/{campaign_id}/fans`); then browsing until the
storm ends (1-3 s think, 70 % on its home Creator: `/admin/tracking-links`, `/summary`, `/{id}/analytics`
over 7 / 30 / 90 days, the Links list, a Details).

Bot check before redirect (Cloudflare Turnstile, `RELAY_ENV` keys): per Creator `gated` links made through the
real Create (`POST /admin/tracking-links`, a scheme-less `ofl.ink/...` target; even ones with `bot_check` set
there, odd ones by `PATCH`), and `gated_clicks` fans (open loop at rate / 10, on max(4, users // 10)
connections, visit k from its own address 100.96.x.y: one fan, one phone) each GET a gated link's /t/ (the
Turnstile page), then POST its /verify with a token: 3 in 4 pass (`pass-k`), the rest fail. After the storm
the verify throttle: one fresh address (`PROBE_IP`) posts VERIFY_CAPACITY failing tokens to one gated link at
once, then 3 more.

Checks (lib/tracking_faults.py): GATE_CREATE, GATE_PAGE, GATE_VERIFY (siteverify as the storm left it,
before the throttle probe), GATE_COUNT (the gated links' clicks == the passed verifies; their seeded clicks are
0), GATE_THROTTLE (the probe: 403 x VERIFY_CAPACITY then 429 + Retry-After x 3, siteverify + VERIFY_CAPACITY,
no click), CLICKS (rows, click_count, list == seeded + the 302s answered), CLIENT_IP (every
stored storm click's ip is one of the clients' own addresses, none a Cloudflare or proxy address), REDIRECT,
BY_DAY (`?days=30`, per New York day: seeded + the 302s answered that day; a 302 sent before New York
midnight and answered after may count on either day), STATS_SUMMARY (per Creator today / 7 / 30 days, every
link's sparkline, the top link == the same oracle, gated links' passes included), STATS_BREAKDOWN (per ungated
link, 30 days in the zone the API names: Opened in / Came from / Country == the hand labels, each summing to
the total), STATS_INVARIANT (per link: analytics buckets == range raw rows; all raw rows == click_count), CREATED, EARNINGS (every link of each Creator
listed, the created ones at zero; the oracle derived here from the seed: each tracked sale of a claimer goes
to the claiming link with the latest createdAt at or before it whose window is still open,
`of_tracking_api._spend`'s rule, gross / net / fans counted / fans who spent; each link's /fans rows sum to
its figure; the run is INFRA unless each of the rule's branches occurs in the seed: a sale past a deactivated
link's end falling back, a sale before any claim, an untracked status inside a window, a fan with several
links), CLAIMERS (`GET
/__slop/tracking-calls`: one walk, a call at offset 0, per link with subscribers, of ceil(n / 50) pages; 0 for
zero-subscriber and created links). Budgets: p95 `/t/` <= 150 ms, earnings (the page's reads) <= 2 s, the stats
reads (`/summary`, `/:id/analytics`) <= 300 ms in 20 timed reads each after the storm and <= 1200 / 700 ms under
it (a single-relay saturation guard), plus a separate 90-day hot-link probe <= 600 ms p95;
p95 vs the last green run (routes with >= 20 calls in both).
UI (`UI = True`; UI == API only, the oracle is the API checks' job): /growth/tracking-links for the Creator
the page picks, its Redirect links tab: the summary cards == `/summary` (UI_SUMMARY, screenshots
`tracking-links-summary`, `tracking-links-trigger`); its hot link's Analytics opened: "{n} clicks · last 30
days" == the API's total == the DB's rows in that window, 30 bars and the top Opened in row == the API
(UI_STATS; `tracking-links-stats-30d`, `tracking-links-settled`); the same on a 390 x 844 phone with no
sideways scroll, loaded and expanded (UI_PHONE; `tracking-links-phone-summary`, `tracking-links-phone-stats`).

Bypasses (declared): Cloudflare's siteverify is lib/tracking_relay.py's loopback fake (the product's
TURNSTILE_VERIFY_URL env seam, set by the relay part; 30 ms a call, a guess; a token passes iff it starts
`pass-`); the Turnstile widget itself never runs (no browser opens the gate page: the slop browser aborts
off-host scripts), so the fans post the token the widget would; OnlyFans' /campaigns, /campaigns/{id}/claimers and the create are lib/tracking_relay.py
(in-process, 50 ms a call, a guess; not lib/of_wire.py: this run has no OF_WIRE), the product's `_make_client`
falls back to it as for every offline Creator; `of-me.json` answers `me()` with no username, so the share
URLs are null (OF's username is cosmetic here); the /t/ slugs are custom numeric slugs (`_slugify` keeps
digits) so the recorder folds them into one `GET /t/:id` row; the past clicks, links, campaigns' claimers and
ledger are SQL in the product's shape (the WS rows' message ids name no `messages` row); the big link's
free-trial claimers are OF ids with no `fans` row; the clients are httpx, not browsers (no referer chain, no
redirect followed: the target is off-host); CF-IPCountry is set by the clients, as the CF hop is today; the
seed's raw rows include NULL labels classified by the boot job; the click rate is the scenario's (100 / 250 clicks/s small /
medium, a guess at a bio-link burst); the Cloudflare hop is its headers alone: the clients reach the relay
straight from loopback (a trusted proxy, as the Next app is), no Traefik or Next in between. Break-it-once: tracking-click-lost-1-in-20 (CLICKS, BY_DAY, STATS_SUMMARY, STATS_BREAKDOWN, GATE_COUNT);
--fault=tracking-stats-utc-days (BY_DAY, STATS_SUMMARY);
--fault=client-addr-cdn-header-ignored (CLIENT_IP, STATS_BREAKDOWN);
--fault=of-tracking-claimers-no-memo (CLAIMERS); --fault=of-tracking-spend-first-link (EARNINGS);
--fault=tracking-bot-check-fails-open (GATE_VERIFY, GATE_COUNT, STATS_SUMMARY, GATE_THROTTLE);
--fault=tracking-classify-raises (STATS_BREAKDOWN);
--fault=tracking-verify-unthrottled (GATE_THROTTLE).
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from slop.actors import ui
from slop.lib.client import Http, Recorder
from slop.lib.tracking_faults import (BY_DAY, CLAIMERS, CLICKS, CLIENT_IP, CREATED, EARNINGS, GATE_COUNT,
                                     GATE_CREATE, GATE_PAGE, GATE_THROTTLE, GATE_VERIFY, REDIRECT,
                                     STATS_BREAKDOWN, STATS_INVARIANT, STATS_SUMMARY)
from slop.seed import tracking_campaigns

PROFILE = "agency_inbox"
UI = True
FAULT = "tracking-click-lost-1-in-20"
RELAY_ENV = {"EDGE_PROXIES": "cloudflare",   # the fans come through Cloudflare (deploy/ae/EDGE-CDN.md)
             # Bot check on: Cloudflare's always-pass test site key; siteverify is lib/tracking_relay.py's fake.
             "TURNSTILE_SITE_KEY": "1x00000000000000000000AA", "TURNSTILE_SECRET_KEY": "slop-turnstile-secret"}
GATED_SLUG_BASE = 79_000_000   # the gated links' custom numeric slugs (seed/tracking_campaigns.SLUG_BASE + 9e6)
PASS_SHARE = 0.75              # gated clicks whose token passes
VERIFY_CAPACITY = 30           # tracking_links_api.VERIFY_CAPACITY: one address's verify burst before 429
PROBE_IP = "100.127.255.254"   # GATE_THROTTLE's address: no fan's (CGNAT, outside both fan ranges)
CF_HOPS = tuple(f"162.158.88.{i}" for i in range(1, 9))   # Cloudflare servers (inside its published ranges)
T_P95_MS = 150
EARNINGS_P95_MS = 2000
STATS_P95_MS = 300   # /summary and 30-day /:id/analytics, 20 timed reads each once the storm is over
# Under the storm one relay process saturates (250 clicks/s + owner reads): server-side /summary 200-460 ms in
# the storm, 33-53 ms right after (medium, runs 20261111T062608Z-d344 / 20261111T083333Z-78ca: summary p95
# 777 / 878, analytics 286 / 483). A saturation guard, not the product budget; a rollup is the followup.
SUMMARY_STORM_P95_MS = 1200
ANALYTICS_STORM_P95_MS = 700
# Measured 315k rows: idle p95 275 ms, two readers 525 ms; allow concurrent readers.
HOT_90D_P95_MS = 600
REPORT_TZ = "America/New_York"
NY = ZoneInfo(REPORT_TZ)
SPOOF_SHARE = 1 / 20   # clicks that skip Cloudflare with a forged CF-IPCountry
FORGED_COUNTRY = "KP"
RANGES = (7, 30, 90)
# app/components/growth/redirectStats.ts OPENED_IN (the UI's row label of an API key)
OPENED_IN = {"instagram": "Instagram app", "tiktok": "TikTok app", "facebook": "Facebook app",
             "threads": "Threads app", "": "Browser", "bot": "Bots & link previews"}
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20   # under 20 calls a p95 is the slowest of a handful
THINK_S = (1.0, 3.0)   # an owner between page actions (a guess at a human's)
TRACKED = ("cleared", "pending")
SUBS = ("subscription", "rebill")
FIGURES = ("earnings_cents", "earnings_net_cents", "net_missing_count", "fans_counted", "fans_who_spent")


def _local_day(hour: str, tz) -> date:
    """The local day (of `tz`) a UTC hour bucket '%Y-%m-%d %H:00:00' starts in."""
    return datetime.strptime(hour, tracking_campaigns.HOUR).replace(tzinfo=timezone.utc).astimezone(tz).date()


def _window(n: int, tz=NY) -> list[str]:
    """The last `n` days of `tz` ending today, oldest first, as 'YYYY-MM-DD'."""
    today = datetime.now(timezone.utc).astimezone(tz).date()
    return [(today - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _digits(text: str) -> int | None:
    m = re.search(r"\d[\d,]*", text or "")
    return int(m.group().replace(",", "")) if m else None


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


@dataclass(frozen=True)
class _ClickOracle:
    clicks_want: Callable
    astride: dict
    storm_labels: dict
    plan: list
    gated_answers: list


def _verified_off(summary, analytics, mine, answers, month):
    """Plan verdicts are independent of the API; midnight straddles bound the 30-day total."""
    passes = [a for a in answers if a.get("pass") and "verify" in a]
    slugs = {l["slug"] for l in mine}
    relevant = [a for a in passes if a["slug"] in slugs]
    lo = sum(a["vsent"] in month and a["vanswered"] in month for a in relevant)
    hi = sum(a["vsent"] in month or a["vanswered"] in month for a in relevant)
    off = {}
    got = summary.get("verified_clicks")
    if got is None or not lo <= got <= hi:
        off["verified_clicks"] = {"got": got, "lo": lo, "hi": hi}
    for link in mine:
        expected = sum(a["slug"] == link["slug"] for a in passes)
        value = analytics.get(link["id"], {}).get("totals", {}).get("verified_clicks")
        if value != expected:
            off[f"verified {link['slug']}"] = {"got": value, "want": expected}
    return off


async def _check_stats(ctx, w, reader, links, gated, aids, oracle: _ClickOracle) -> None:
    clicks_want = oracle.clicks_want
    astride = oracle.astride
    storm_labels = oracle.storm_labels
    plan = oracle.plan
    # ── stats: 30-day series per New York day, summary, breakdowns, raw-row invariant ──

    async def analytics(l, days=30):
        r = await reader.get(f"/admin/tracking-links/{l['id']}/analytics?account_id={l['account_id']}&days={days}")
        return l, (r.json() if r.status_code == 200 else {"status": r.status_code})

    month = _window(30)
    by_day_bad, an30 = [], {}
    gated_ids = {g["id"] for g in gated}
    for l, a in await asyncio.gather(*(analytics(l) for l in links + gated)):
        an30[l["id"]] = a
        if l["id"] in gated_ids:
            continue
        lo, hi, _ = clicks_want(l)
        total = sum(lo[d] for d in month) + astride[l["slug"]].total() // 2
        got = Counter({d["day"]: d["clicks"] for d in a.get("series", [])})
        days_off = {d: (got[d], lo[d], hi[d]) for d in month if not lo[d] <= got[d] <= hi[d]}
        days = [d["day"] for d in a.get("series", [])]
        if days_off or days != month or got.total() != total or a.get("totals", {}).get("clicks") != total:
            by_day_bad.append({"slug": l["slug"], "total": a.get("totals", {}).get("clicks"), "series_total": got.total(),
                               "want_total": total, "tz": a.get("tz"), "first_day": days[:1], "want_first": month[0],
                               "days_off (got, lo, hi)": dict(list(days_off.items())[:6])})
    ctx.check(BY_DAY, not by_day_bad, links=len(links), bad=len(by_day_bad), sample=by_day_bad[:5],
              astride_midnight=sum(c.total() // 2 for c in astride.values()))

    week, all_links = _window(7), links + gated
    summary_bad, astride_any = [], any(c.total() for c in astride.values())
    for aid in aids:
        r = await reader.get(f"/admin/tracking-links/summary?account_id={aid}")
        got = r.json() if r.status_code == 200 else {"status": r.status_code}
        mine = [l for l in all_links if l["account_id"] == aid]
        want = {l["id"]: clicks_want(l)[:2] for l in mine}

        def span(days, lid=None):
            ids = [lid] if lid is not None else list(want)
            return (sum(want[i][0][d] for i in ids for d in days), sum(want[i][1][d] for i in ids for d in days))

        off = {}
        for key, days in (("today", month[-1:]), ("d7", week), ("d30", month)):
            v, (lo, hi) = got.get("clicks", {}).get(key), span(days)
            if v is None or not lo <= v <= hi:
                off[key] = {"got": v, "lo": lo, "hi": hi}
        spark = got.get("spark") or {}
        if set(spark) != {str(i) for i in want}:
            off["spark_ids"] = {"got": sorted(spark)[:6], "want": sorted(map(str, want))[:6]}
        for lid, (lo, hi) in want.items():
            vals = spark.get(str(lid)) or []
            if len(vals) != 7 or any(not lo[d] <= v <= hi[d] for d, v in zip(week, vals)):
                off[f"spark {lid}"] = {"got": vals, "lo": [lo[d] for d in week], "hi": [hi[d] for d in week]}
        d30 = {l["id"]: span(month, l["id"]) for l in mine}
        top, name_of = got.get("top"), {l["id"]: l["name"] for l in mine}
        if not any(hi for _, hi in d30.values()):
            top_ok = top is None
        elif top is None or top.get("id") not in d30:
            top_ok = False
        elif not astride_any:   # exact: most clicks, then name, then id
            top_ok = top["id"] == min(d30, key=lambda i: (-d30[i][0], name_of[i], i)) and top["clicks"] == d30[top["id"]][0]
        else:
            lo, hi = d30[top["id"]]
            top_ok = lo <= top["clicks"] <= hi and all(d30[i][0] <= top["clicks"] for i in d30)
        if not top_ok:
            off["top"] = {"got": top, "want_d30": {i: v for i, v in sorted(d30.items(), key=lambda x: -x[1][0])[:3]}}
        if got.get("tz") != REPORT_TZ or got.get("today") != month[-1]:
            off["zone"] = {"tz": got.get("tz"), "today": got.get("today"), "want_today": month[-1]}
        off.update(_verified_off(got, an30, [l for l in mine if l["id"] in gated_ids],
                                 oracle.gated_answers, month))
        if off:
            summary_bad.append({"creator": aid, **off})
    ctx.check(STATS_SUMMARY, not summary_bad, creators=len(aids), bad=len(summary_bad), sample=summary_bad[:3])

    breakdown_bad = []
    for l in links:
        a = an30.get(l["id"], {})
        tz = ZoneInfo(a["tz"]) if a.get("tz") else timezone.utc   # null tz: UTC days
        lo_day, hi_day = a.get("from", ""), a.get("to", "")
        want = Counter(storm_labels[l["slug"]])
        for (hour, *lab), n in l["seeded"].items():
            if lo_day <= _local_day(hour, tz).isoformat() <= hi_day:
                want[tuple(lab)] += n
        total = a.get("totals", {}).get("clicks")
        off = {}
        for field, idx in (("country", 0), ("opened_in", 1), ("came_from", 2)):
            w_rows = Counter()
            for lab, n in want.items():
                w_rows[lab[idx]] += n
            g_rows = {row["key"]: row["clicks"] for row in a.get(field, [])}
            if g_rows != {k: v for k, v in w_rows.items() if v} or sum(g_rows.values()) != total:
                off[field] = {"got": g_rows, "want": dict(w_rows), "total": total}
        if off:
            breakdown_bad.append({"slug": l["slug"], "hot": l["hot"], **off})
    ctx.check(STATS_BREAKDOWN, not breakdown_bad, links=len(links), bad=len(breakdown_bad), sample=breakdown_bad[:3],
              spoofed=sum(p[4] for p in plan))

    con = w.sql()
    try:
        invariant = con.execute(
            "SELECT l.id, l.click_count, COUNT(c.id) FROM tracking_links l "
            "LEFT JOIN tracking_clicks c ON c.tracking_link_id=l.id GROUP BY l.id").fetchall()
        off = []
        for lid, click_count, raw in invariant:
            a = an30.get(lid)
            ranged = None
            if a and a.get("from") and a.get("to"):
                zone = ZoneInfo(a["tz"]) if a.get("tz") else timezone.utc
                lo = datetime.combine(date.fromisoformat(a["from"]), dtime(), tzinfo=zone).astimezone(timezone.utc)
                hi = datetime.combine(date.fromisoformat(a["to"]) + timedelta(days=1), dtime(), tzinfo=zone).astimezone(timezone.utc)
                ranged = con.execute(
                    "SELECT COUNT(*) FROM tracking_clicks WHERE tracking_link_id=? AND clicked_at>=? AND clicked_at<?",
                    (lid, lo.strftime("%Y-%m-%d %H:%M:%S"), hi.strftime("%Y-%m-%d %H:%M:%S"))).fetchone()[0]
            bucket_sum = sum(row["clicks"] for row in a.get("series", [])) if a else None
            if click_count != raw or (a and not bucket_sum == ranged == a.get("totals", {}).get("clicks")):
                off.append({"id": lid, "click_count": click_count, "rows": raw,
                            "range_rows": ranged, "buckets": bucket_sum})
    finally:
        con.close()
    ctx.check(STATS_INVARIANT, bool(invariant) and not off, links=len(invariant), bad=len(off), sample=off[:5])

async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    aids = [c["id"] for c in creators]
    tc = tracking_campaigns.seed(
        w, creators, ctx.stack.tmp,
        links=ctx.param("links", w.size["tracking_links_links"]),
        campaigns=ctx.param("campaigns", w.size["tracking_links_campaigns"]),
        claimed=ctx.param("claimed", w.size["tracking_links_claimed"]),
        hot_per_day=ctx.param("hot_per_day", w.size["tracking_links_hot_per_day"]))
    # The seed includes pre-existing NULL-labelled rows. Restart so the product's boot job sees them.
    await asyncio.to_thread(ctx.stack.stop_relay)
    await asyncio.to_thread(ctx.stack.start_relay)
    for _ in range(300):
        con = w.sql()
        try:
            remaining = con.execute("SELECT COUNT(*) FROM tracking_clicks WHERE ref IS NULL").fetchone()[0]
        finally:
            con.close()
        if not remaining:
            break
        await asyncio.sleep(0.1)
    if remaining:
        raise RuntimeError(f"tracking old-row classifier left {remaining} NULL refs")
    n_clicks = ctx.param("clicks", w.size["tracking_links_clicks"])
    rate = ctx.param("rate", {"small": 100.0, "medium": 250.0, "huge": 400.0}[ctx.scale])   # clicks/s; 0: closed loop
    links = tc["links"]
    by_slug = {l["slug"]: l for l in links}
    links_of = {aid: [l for l in links if l["account_id"] == aid] for aid in aids}
    live = {aid: [r["id"] for r in rows if r["countSubscribers"] > 0] for aid, rows in tc["campaigns"].items()}
    rng = w.rng("scenario:tracking-links-clicks")
    weights = [rng.uniform(0.2, 3.0) for _ in links]
    plan = [(rng.choices(links, weights)[0]["slug"], rng.choice(tracking_campaigns.REFERERS),
             rng.choice(tracking_campaigns.UAS), rng.choice(tracking_campaigns.COUNTRIES), rng.random() < SPOOF_SHARE)
            for _ in range(n_clicks)]
    no_astride = [l["slug"] for l in links if not l["hot"]
                  and not any(h[:10] != _local_day(h, NY).isoformat() for h, *_ in l["seeded"])]
    if no_astride:   # no seeded click on a UTC day that is not its New York day: the zone goes untested
        raise RuntimeError(f"tracking seed: no click between UTC and New York midnight on {no_astride[:5]}")
    oracle, branches = _oracle(tc)
    if not all(branches.values()):   # a seed that cannot tell the rule's branches apart: no verdict
        raise RuntimeError(f"tracking seed misses a branch of the attribution rule: {branches}")
    ctx.metric("world", {"creators": len(aids), "links": len(links), "campaigns": sum(map(len, tc["campaigns"].values())),
                         "claims": sum(map(len, tc["claimers"].values())), "tx": len(tc["tx"]), "clicks": n_clicks,
                         "seeded_clicks": sum(l["seeded"].total() for l in links)})
    r = await ctx.owner.put("/admin/settings/preferences", json={"report_tz": REPORT_TZ})
    if r.status_code != 200:
        raise RuntimeError(f"report_tz PUT -> {r.status_code} {r.text[:200]}")

    # ── gated links: made through the real Create (+ PATCH), scheme-less targets ──
    n_gated = ctx.param("gated", 2)
    gated: list[dict] = []
    create_off: list = []
    for ci, aid in enumerate(aids):
        for k in range(n_gated):
            raw = f"ofl.ink/slop{aid}/g{k}"
            r = await ctx.owner.post("/admin/tracking-links", json={
                "account_id": aid, "name": f"gated {aid} {k}", "target_url": raw,
                "slug": str(GATED_SLUG_BASE + ci * 100 + k), "bot_check": k % 2 == 0})
            if r.status_code != 200:
                create_off.append((raw, r.status_code))
                continue
            row = r.json()
            if k % 2:
                r = await ctx.owner.request("PATCH", f"/admin/tracking-links/{row['id']}", json={"bot_check": True})
                row = r.json() if r.status_code == 200 else {**row, "bot_check": f"PATCH {r.status_code}"}
            if row["target_url"] != "https://" + raw:
                create_off.append((raw, row["target_url"]))
            gated.append({"id": row["id"], "account_id": aid, "slug": row["slug"], "target": row["target_url"],
                          "name": row["name"]})
    listed_gate = {l["id"]: l.get("bot_check") for aid in aids
                   for l in (await ctx.owner.get(f"/admin/tracking-links?account_id={aid}")).json().get("links", [])}
    not_gated = [g["slug"] for g in gated if listed_gate.get(g["id"]) is not True]
    ctx.check(GATE_CREATE, len(gated) == n_gated * len(aids) and not create_off and not not_gated,
              want=n_gated * len(aids), created=len(gated), off=create_off[:5], not_gated=not_gated[:5])
    grng = w.rng("scenario:tracking-links-clicks:gated")   # its own stream: the plain plan above is unchanged
    n_gclicks = ctx.param("gated_clicks", max(20, n_clicks // 10)) if gated else 0
    gplan = [(grng.choice(gated), grng.random() < PASS_SHARE) for _ in range(n_gclicks)]

    def home(i: int) -> str:
        return aids[i % len(aids)]

    def pick(aid: str, k: int) -> int | None:
        """The Creator's k-th (mod) OF link with subscribers: the one whose Details an owner opens."""
        return live[aid][k % len(live[aid])] if live[aid] else None

    # ── the storm: anonymous fans clicking /t/<slug> ───────────────────────
    # (slug, status, location, New York day sent, answered, (country, in-app, referer family) hand labels)
    answers: list[tuple[str, int, str | None, str, str, tuple[str, str, str]]] = []
    fans = [Http(ctx.relay, ctx.rec, limits=1) for _ in range(ctx.users)]
    gfans = [Http(ctx.relay, ctx.rec, limits=1) for _ in range(max(4, ctx.users // 10))]   # the gated links' fans
    n_owners = max(3, ctx.users // 10)
    owners = [ctx.owner.share(limits=4) for _ in range(n_owners)]   # an owner reads <= 2 at once: nothing queues
    stop = asyncio.Event()
    ctx.rec.stage = "storm"
    t0 = time.perf_counter()

    def today() -> str:
        return datetime.now(timezone.utc).astimezone(NY).strftime("%Y-%m-%d")

    ip_of = {id(h): f"100.64.{i // 250}.{i % 250 + 1}" for i, h in enumerate(fans)}   # a phone's CGNAT address each

    def fan_ip(h: Http) -> str:
        return ip_of[id(h)]

    def gfan_ip(k: int) -> str:
        """Gated visit k is its own fan, so its own address (the clients are only connections)."""
        return f"100.96.{k // 250}.{k % 250 + 1}"

    async def click(h: Http, slug: str, ref_l: tuple, ua_l: tuple, country: str | None, spoof: bool) -> None:
        (ref, ref_label), (ua, ua_label) = ref_l, ua_l
        sent = today()
        if spoof:   # straight to the box, no Cloudflare: its own address the hop, a forged country
            edge = {"x-forwarded-for": fan_ip(h), "cf-connecting-ip": fan_ip(h), "cf-ipcountry": FORGED_COUNTRY}
        else:
            edge = {"x-forwarded-for": CF_HOPS[sum(map(ord, slug)) % len(CF_HOPS)], "cf-connecting-ip": fan_ip(h),
                    **({"cf-ipcountry": country} if country else {})}
        labels = ("XX" if spoof else tracking_campaigns.label(country), ua_label, ref_label)
        try:
            r = await h.get(f"/t/{slug}", headers={"user-agent": ua, **edge, **({"referer": ref} if ref else {})})
            answers.append((slug, r.status_code, r.headers.get("location"), sent, today(), labels))
        except httpx.HTTPError:
            pass   # Http recorded it as a 599 (the stock no-5xx check); no answer, so no click expected
        h.c.cookies.clear()   # no cookie, ever

    gated_answers: list[dict] = []

    async def gated_click(h: Http, k: int, g: dict, passes: bool) -> None:
        """The gate page, then the widget's verify (the token it would post)."""
        edge = {"x-forwarded-for": CF_HOPS[k % len(CF_HOPS)], "cf-connecting-ip": gfan_ip(k),
                "user-agent": tracking_campaigns.UAS[k % len(tracking_campaigns.UAS)][0]}
        a = {"slug": g["slug"], "pass": passes}
        try:
            r = await h.get(f"/t/{g['slug']}", headers=edge)
            a.update(get=r.status_code, location=r.headers.get("location"), leaked=g["target"] in r.text
                     or g["target"].split("//", 1)[1] in r.text, store=r.headers.get("cache-control"),
                     page="challenges.cloudflare.com/turnstile" in r.text)
            vsent = today()
            v = await h.post(f"/t/{g['slug']}/verify", json={"token": f"{'pass' if passes else 'fail'}-{k}"},
                             headers=edge)
            a.update(vsent=vsent, vanswered=today(), verify=v.status_code,
                     url=(v.json().get("url") if v.status_code == 200 else ("url" in v.text and "leak") or None))
        except httpx.HTTPError:
            pass   # recorded as a 599 (the stock no-5xx check)
        gated_answers.append(a)
        h.c.cookies.clear()

    async def gated_storm() -> None:
        tasks = []
        grate = max(rate, 10.0) / 10   # a tenth of the plain clicks' pace (closed loop: 10/s)
        for k, (g, passes) in enumerate(gplan):
            delay = t0 + k / grate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(gated_click(gfans[k % len(gfans)], k, g, passes)))
        await asyncio.gather(*tasks)

    async def closed(h: Http, it) -> None:
        for p in it:
            await click(h, *p)

    async def paced() -> None:
        """Open loop: click k leaves at t0 + k / rate on client k % users, whatever the earlier ones did (a
        busy client queues it in its pool, and that wait is in its latency)."""
        tasks = []
        for k, p in enumerate(plan):
            delay = t0 + k / rate - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(click(fans[k % len(fans)], *p)))
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
            await asyncio.gather(h.get(f"/admin/tracking-links?account_id={aid}"),
                                 h.get(f"/admin/tracking-links/summary?account_id={aid}"))
            if links_of[aid]:
                await h.get(f"/admin/tracking-links/{r.choice(links_of[aid])['id']}/analytics?account_id={aid}"
                            f"&days={r.choice(RANGES)}")
            await page(h, aid, pick(aid, r.randrange(1 << 10)))

    if rate <= 0:
        it = iter(plan)
        storm = asyncio.gather(*(closed(h, it) for h in fans), gated_storm())
    else:
        storm = asyncio.gather(paced(), gated_storm())
    hot_link = next((link for link in links if link["hot"]), None)
    hot_times: list[float] = []
    hot_owner = ctx.owner.share(rec=Recorder())

    async def hot_reads() -> None:
        if not hot_link:
            return
        for _ in range(20):
            start = time.perf_counter()
            r = await hot_owner.get(f"/admin/tracking-links/{hot_link['id']}/analytics"
                                    f"?account_id={hot_link['account_id']}&days=90")
            hot_times.append((time.perf_counter() - start) * 1000 if r.status_code == 200 else float("inf"))

    hot_task = asyncio.create_task(hot_reads())
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
    await hot_task
    await hot_owner.aclose()
    storm_s = time.perf_counter() - t0
    stop.set()
    await browsers
    ctx.rec.stage = "after"
    for h in fans + gfans + owners:
        await h.aclose()
    quiet: dict[str, list[float]] = {"summary": [], "analytics": []}   # the stats reads off the storm
    if hot_link:
        quiet_owner = ctx.owner.share(rec=Recorder())
        aid = hot_link["account_id"]
        for kind, path in (("summary", f"/admin/tracking-links/summary?account_id={aid}"),
                           ("analytics", f"/admin/tracking-links/{hot_link['id']}/analytics?account_id={aid}&days=30")):
            for _ in range(20):
                start = time.perf_counter()
                r = await quiet_owner.get(path)
                quiet[kind].append((time.perf_counter() - start) * 1000 if r.status_code == 200 else float("inf"))
        await quiet_owner.aclose()

    # ── verify throttle: one fresh address, VERIFY_CAPACITY + 3 failing tokens to one gated link ──
    # Siteverify as the storm left it, before the probe adds to it (GATE_VERIFY reads this one).
    ts_calls = (await ctx.owner.get("/__slop/turnstile-calls")).json()
    probe: dict = {}
    if gated:
        g0 = gated[0]

        def link_clicks() -> int:
            con = w.sql()
            try:
                return con.execute("SELECT click_count FROM tracking_links WHERE id = ?", (g0["id"],)).fetchone()[0]
            finally:
                con.close()

        edge = {"x-forwarded-for": CF_HOPS[0], "cf-connecting-ip": PROBE_IP}
        ph = Http(ctx.relay, ctx.rec, limits=VERIFY_CAPACITY)
        clicks_before = link_clicks()
        tp = time.perf_counter()
        try:
            # The budget drained at once (each take is before the route's first await), then 3 more: the bucket
            # refills one per 2 s, so the whole probe must take well under that.
            burst = await asyncio.gather(*(ph.post(f"/t/{g0['slug']}/verify", json={"token": f"fail-probe-{i}"},
                                                   headers=edge) for i in range(VERIFY_CAPACITY)))
            over = [await ph.post(f"/t/{g0['slug']}/verify", json={"token": f"fail-probe-{VERIFY_CAPACITY + i}"},
                                  headers=edge) for i in range(3)]
        finally:
            await ph.aclose()
        probe_s = time.perf_counter() - tp
        ts_after = (await ctx.owner.get("/__slop/turnstile-calls")).json()
        codes = [r.status_code for r in burst + over]
        retry_after = [r.headers.get("retry-after") for r in over]
        throttled_tokens = [t for t in (f"fail-probe-{VERIFY_CAPACITY + i}" for i in range(3))
                            if ts_after["tokens"].get(t)]
        probe = {"codes": codes, "retry_after": retry_after, "siteverify_calls": ts_after["n"] - ts_calls["n"],
                 "throttled_reached_siteverify": throttled_tokens, "clicks": link_clicks() - clicks_before,
                 "probe_s": round(probe_s, 3)}
    ctx.check(GATE_THROTTLE, bool(probe) and probe["codes"] == [403] * VERIFY_CAPACITY + [429] * 3
              and all(ra and ra.isdigit() and int(ra) >= 1 for ra in probe["retry_after"])
              and probe["siteverify_calls"] == VERIFY_CAPACITY and not probe["throttled_reached_siteverify"]
              and probe["clicks"] == 0, capacity=VERIFY_CAPACITY, ip=PROBE_IP,
              link=gated[0]["slug"] if gated else None,
              codes=dict(Counter(probe.get("codes", []))), **{k: v for k, v in probe.items() if k != "codes"})

    # ── clicks: stored once per link, every answer a 302 to its own target ──
    con = w.sql()
    try:
        stored = dict(con.execute("SELECT tracking_link_id, COUNT(*) FROM tracking_clicks GROUP BY 1").fetchall())
        storm_ips = Counter(ip for (ip,) in con.execute(   # the seed's clicks are 203.0.113.x
            "SELECT ip FROM tracking_clicks WHERE (ip IS NULL OR ip NOT LIKE '203.0.113.%') AND ip IS NOT ?",
            (PROBE_IP,)))   # the throttle probe's clicks are GATE_THROTTLE's (0), not CLIENT_IP's
        counter = dict(con.execute("SELECT id, click_count FROM tracking_links").fetchall())
    finally:
        con.close()
    listed: dict[int, int] = {}
    for aid in aids:
        for l in (await ctx.owner.get(f"/admin/tracking-links?account_id={aid}")).json().get("links", []):
            listed[l["id"]] = l["click_count"]
    sure: dict[str, Counter] = defaultdict(Counter)     # slug -> NY day -> clicks sent and answered on it
    astride: dict[str, Counter] = defaultdict(Counter)  # slug -> NY day -> clicks sent before midnight, answered after
    storm_labels: dict[str, Counter] = defaultdict(Counter)   # slug -> (country, in-app, referer family) -> 302s
    for s, st, _, sent, answered, labels in answers:
        if st == 302:
            storm_labels[s][labels] += 1
        if st == 302 and sent == answered:
            sure[s][sent] += 1
        elif st == 302:
            astride[s].update((sent, answered))
    for a in gated_answers:   # a gated link's click is the plan's passing verify, on the day it was answered
        if a["pass"] and "verify" in a:
            if a["vsent"] == a["vanswered"]:
                sure[a["slug"]][a["vsent"]] += 1
            else:
                astride[a["slug"]].update((a["vsent"], a["vanswered"]))
    seeded_days = {l["slug"]: Counter() for l in links}
    for l in links:
        for (hour, *_), n in l["seeded"].items():
            seeded_days[l["slug"]][_local_day(hour, NY).isoformat()] += n

    def clicks_want(l) -> tuple[Counter, Counter, int]:
        """Per New York day the least and most clicks the link's stats may show, and their exact total."""
        lo = seeded_days.get(l["slug"], Counter()) + sure[l["slug"]]
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
    fan_ips = {fan_ip(h) for h in fans} | {gfan_ip(k) for k in range(n_gclicks)}
    foreign = {ip: n for ip, n in storm_ips.items() if ip not in fan_ips}
    ctx.check(CLIENT_IP, bool(storm_ips) and not foreign, stored=storm_ips.total(), fans=len(fan_ips),
              foreign=dict(list(foreign.items())[:5]))
    bad_redirect = [(s, st, loc) for s, st, loc, *_ in answers if st != 302 or loc != by_slug[s]["target"]]
    ctx.check(REDIRECT, bool(answers) and not bad_redirect, sent=n_clicks, answers=len(answers),
              bad=len(bad_redirect), sample=bad_redirect[:5])

    # ── gated links: the page hides the target, verify decides, clicks == passes ──
    bad_page = [a for a in gated_answers if not (a.get("get") == 200 and a.get("location") is None
                                                 and not a.get("leaked") and a.get("store") == "no-store"
                                                 and a.get("page"))]
    ctx.check(GATE_PAGE, bool(gated_answers) and not bad_page, gets=len(gated_answers), bad=len(bad_page),
              sample=bad_page[:5])
    by_gslug = {g["slug"]: g for g in gated}
    bad_verify = [a for a in gated_answers if "verify" in a and (
        (a["pass"] and (a["verify"] != 200 or a["url"] != by_gslug[a["slug"]]["target"]))
        or (not a["pass"] and (a["verify"] != 403 or a["url"] is not None)))]
    verifies = sum("verify" in a for a in gated_answers)
    twice = {t: n for t, n in ts_calls["tokens"].items() if n != 1}
    ctx.check(GATE_VERIFY, verifies > 0 and not bad_verify and ts_calls["n"] == verifies and not twice
              and ts_calls["bad_secret"] == 0 and ts_calls["no_remoteip"] == 0,
              verifies=verifies, passes=sum(a["pass"] for a in gated_answers), bad=len(bad_verify),
              sample=bad_verify[:5], siteverify_calls=ts_calls["n"], tokens_not_once=dict(list(twice.items())[:5]),
              bad_secret=ts_calls["bad_secret"], no_remoteip=ts_calls["no_remoteip"])
    # The plan's verdicts, never the answers: a gate that fails open must not move the expectation with it.
    passed = Counter(a["slug"] for a in gated_answers if a["pass"] and "verify" in a)
    gate_off = {}
    for g in gated:
        got = (stored.get(g["id"], 0), counter.get(g["id"]), listed.get(g["id"]))
        if got != (passed[g["slug"]],) * 3:
            gate_off[g["slug"]] = {"passed": passed[g["slug"]], "rows": got[0], "click_count": got[1], "listed": got[2]}
    ctx.check(GATE_COUNT, bool(gated) and not gate_off, links=len(gated), clicks=len(gated_answers),
              passed=passed.total(), failed=sum(not a["pass"] for a in gated_answers), off=len(gate_off),
              sample=dict(list(gate_off.items())[:5]))

    reader = ctx.owner.share(limits=20)
    await _check_stats(ctx, w, reader, links, gated, aids,
                       _ClickOracle(clicks_want, astride, storm_labels, plan, gated_answers))

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
    hot_p95 = sorted(hot_times)[math.ceil(len(hot_times) * .95) - 1] if hot_times else float("inf")
    ctx.check(f"p95 hot-link 90-day analytics <= {HOT_90D_P95_MS} ms", hot_p95 <= HOT_90D_P95_MS,
              budget=True, p95=hot_p95, n=len(hot_times))
    t_route, e_route = "GET /t/:id", "GET /admin/of-tracking-links/earnings"
    s_route, a_route = "GET /admin/tracking-links/summary", "GET /admin/tracking-links/:id/analytics"
    for kind, times in quiet.items():
        q_p95 = sorted(times)[math.ceil(len(times) * .95) - 1] if times else float("inf")
        ctx.check(f"p95 {kind} of the hot link's Creator <= {STATS_P95_MS} ms after the storm", q_p95 <= STATS_P95_MS,
                  budget=True, p95=q_p95, n=len(times))
    for route, budget in ((t_route, T_P95_MS), (e_route, EARNINGS_P95_MS), (s_route, SUMMARY_STORM_P95_MS),
                          (a_route, ANALYTICS_STORM_P95_MS)):
        name = f"p95 {route} <= {budget} ms under the storm"
        if route in routes:
            ctx.check(name, routes[route]["p95_ms"] <= budget, budget=True, p95=routes[route]["p95_ms"],
                      n=routes[route]["n"])
        else:
            ctx.skip(name, "no samples")
    ctx.metric("load", {"clicks": n_clicks, "fans": len(fans), "owners": n_owners, "rate": rate, "storm_s": round(storm_s, 2),
                        "clicks_per_s": round(n_clicks / storm_s, 1) if storm_s else None})
    vs_last = [r for r in (t_route, e_route, "POST /t/:id/verify", "GET /admin/of-tracking-links", "GET /admin/of-tracking-links/:id/fans",
                           "GET /admin/tracking-links", s_route, a_route) if r in routes]
    key = {e_route: f"{e_route} incl. first opens"}   # runs before wave 1 joined the row timed warm reads only
    ctx.metric("p95_vs_last_green", {key.get(r, r): routes[r]["p95_ms"] for r in vs_last})
    ctx.metric("p95_vs_last_green_n", {key.get(r, r): routes[r]["n"] for r in vs_last})

    # ── UI: Growth > Tracking links, a redirect link's Analytics ─────────
    if ctx.app:
        await _ui(ctx, tc, gated, w)
    else:
        for name in (UI_STATS_TOTAL, UI_GATE, UI_SUMMARY, UI_STATS, UI_PHONE):
            ctx.skip(name, "--no-ui")
    await reader.aclose()


UI_STATS_TOTAL = "UI: a redirect link's Analytics shows its stored clicks (== API == DB)"
UI_GATE = "UI: gated link badge and toggle, plus verified-click indicator, match API"
UI_SUMMARY = "UI: the Redirect links summary cards (clicks today / 7 / 30 days) == the API's /summary"
UI_STATS = "UI: a redirect link's 30-day Analytics draws a bar a day and its top Opened in row == the API"
UI_PHONE = ("UI: on a 390 x 844 phone the summary cards and a link's Analytics total == the API, no sideways "
            "scroll loaded or expanded")
CARDS = ("today", "d7", "d30")
HEADER = re.compile(r"^\s*([\d,]+) clicks · last 30 days")


async def _open(ctx, page, tc) -> str | None:
    """/growth/tracking-links, its Redirect links tab with the summary cards loaded; the Creator the page picked
    (by its first OF link's name)."""
    creator_of = {r["campaignName"]: aid for aid, rows in tc["campaigns"].items() for r in rows}
    await page.goto(f"{ctx.app}/growth/tracking-links", wait_until="domcontentloaded")
    await page.get_by_text(re.compile(r"OF link 0$")).first.wait_for(timeout=90_000)
    shown = (await page.get_by_text(re.compile(r"OF link 0$")).first.inner_text()).strip()
    await page.get_by_role("tab", name=re.compile("^Redirect links")).click()
    await page.locator('[data-stat="today"] [data-value]').filter(has_not_text="—").wait_for(timeout=30_000)
    return creator_of.get(shown)


async def _cards(page) -> dict:
    return {k: _digits(await page.locator(f'[data-stat="{k}"] [data-value]').first.inner_text()) for k in CARDS}


def _row(page, name: str):
    """A redirect link's row in the list (not the Clicks cards above it: Top link's card carries a name too)."""
    return (page.get_by_role("region", name="Custom redirect links").locator("li")
            .filter(has=page.get_by_text(name, exact=True)).first)


async def _expand(page, name: str) -> dict:
    """Opens the link's Analytics (30 days by default) and reads it once its bars are drawn."""
    row = _row(page, name)
    await row.wait_for(timeout=30_000)
    await row.get_by_role("button", name="Analytics").click()
    await page.get_by_test_id("click-bar").first.wait_for(timeout=30_000)
    m = HEADER.match(await page.locator("[data-stats-header]").first.inner_text())
    top = page.get_by_role("region", name="Opened in").locator("[data-breakdown-row]").first
    return {"total": int(m.group(1).replace(",", "")) if m else None,
            "bars": await page.get_by_test_id("click-bar").count(),
            "top_opened_in": ((await top.locator("span").nth(0).inner_text()).strip(),
                              _digits(await top.locator("span").nth(1).inner_text()))}


async def _ui(ctx, tc, gated, w) -> None:
    async with ui.owner_browser(ctx) as page:
        aid = await _open(ctx, page, tc)
        if aid is None:
            for name in (UI_SUMMARY, UI_STATS_TOTAL, UI_STATS):
                ctx.check(name, False, reason="the page's first OF link is none of the seeded ones")
            return
        await ui.shot(ctx, page, "tracking-links-summary")
        summary = (await ctx.owner.get(f"/admin/tracking-links/summary?account_id={aid}")).json()
        cards = await _cards(page)
        ctx.check(UI_SUMMARY, cards == {k: summary["clicks"][k] for k in CARDS}, creator=aid, ui=cards,
                  api=summary.get("clicks"))
        api = (await ctx.owner.get(f"/admin/tracking-links?account_id={aid}")).json().get("links", [])
        mine = [l for l in tc["links"] if l["account_id"] == aid]
        target = next((l for l in mine if l["hot"]), None) or next((l for l in mine if l["seeded"]), None)
        listed = next((l for l in api if target and l["id"] == target["id"]), None)
        if listed is None:
            for name in (UI_STATS_TOTAL, UI_STATS):
                ctx.check(name, False, creator=aid, reason="the seeded link is not listed")
            return
        await _row(page, listed["name"]).wait_for(timeout=30_000)
        await ui.shot(ctx, page, "tracking-links-trigger")
        got = await _expand(page, listed["name"])
        await ui.shot(ctx, page, "tracking-links-stats-30d")
        a = (await ctx.owner.get(f"/admin/tracking-links/{listed['id']}/analytics?account_id={aid}&days=30")).json()
        zone = ZoneInfo(a["tz"]) if a.get("tz") else timezone.utc   # null tz: UTC days
        bound = datetime.combine(date.fromisoformat(a["from"]), dtime(0), zone).astimezone(timezone.utc)
        con = w.sql()
        try:
            (db_rows,) = con.execute("SELECT COUNT(*) FROM tracking_clicks WHERE tracking_link_id = ? AND clicked_at >= ?",
                                     (listed["id"], bound.strftime("%Y-%m-%d %H:%M:%S"))).fetchone()
        finally:
            con.close()
        ctx.check(UI_STATS_TOTAL, got["total"] == a["totals"]["clicks"] == db_rows, creator=aid, link=listed["id"],
                  slug=listed["slug"], ui_total=got["total"], api_total=a["totals"]["clicks"], db_rows_in_window=db_rows)
        top = a["opened_in"][0] if a.get("opened_in") else None
        want_top = (OPENED_IN.get(top["key"], top["key"]), top["clicks"]) if top else None
        ctx.check(UI_STATS, got["bars"] == len(a["series"]) == 30 and got["top_opened_in"] == want_top, creator=aid,
                  link=listed["id"], bars=got["bars"], api_days=len(a["series"]), ui_top=got["top_opened_in"],
                  api_top=want_top)
        await page.locator("[data-link-stats]").get_by_text("7 d", exact=True).click()
        await page.wait_for_function("document.querySelectorAll('[data-testid=click-bar]').length === 7", timeout=30_000)
        await ui.shot(ctx, page, "tracking-links-settled")
        await _ui_gate(ctx, page, aid, api, gated, summary)

    async with ui.owner_browser(ctx, viewport=(390, 844), touch=True) as page:
        paid = await _open(ctx, page, tc)
        wide_loaded = await page.evaluate("document.documentElement.scrollWidth")
        cards = await _cards(page)
        await ui.shot(ctx, page, "tracking-links-phone-summary")
        same_creator = paid == aid
        got = await _expand(page, listed["name"]) if same_creator else {}
        wide_open = await page.evaluate("document.documentElement.scrollWidth")
        await page.locator("[data-link-stats]").first.scroll_into_view_if_needed()
        await ui.shot(ctx, page, "tracking-links-phone-stats")
        want_cards = {k: summary["clicks"][k] for k in CARDS}
        ctx.check(UI_PHONE, same_creator and cards == want_cards and got.get("total") == a["totals"]["clicks"]
                  and wide_loaded <= 390 and wide_open <= 390, creator=paid, desktop_creator=aid, ui_cards=cards,
                  api_cards=want_cards, ui_total=got.get("total"), api_total=a["totals"]["clicks"],
                  scroll_width_loaded=wide_loaded, scroll_width_expanded=wide_open)


async def _ui_gate(ctx, page, aid, api, gated, summary) -> None:
    g = next((g for g in gated if g["account_id"] == aid), None)
    if g is None:
        ctx.skip(UI_GATE, "no gated link on the Creator the page picked")
        return
    api_g = next((l for l in api if l["id"] == g["id"]), {})
    grow = _row(page, f"gated {aid} 0")
    badge = toggle = False
    verified = None
    try:
        await grow.get_by_text("bot check", exact=True).wait_for(timeout=30_000)
        badge = True
        toggle = await grow.get_by_role("checkbox", name=re.compile("^Bot check for")).is_checked()
        verified = _digits(await page.locator('[data-stat="verified"] [data-value]').first.inner_text())
    except Exception:  # noqa: BLE001
        pass
    await ui.shot(ctx, page, "tracking-links-gated-row")
    want_verified = summary["verified_clicks"]
    ctx.check(UI_GATE, badge and toggle and api_g.get("bot_check") is True and verified == want_verified,
              creator=aid, slug=g["slug"], badge=badge, toggle_on=toggle, verified=verified,
              want_verified=want_verified, api_bot_check=api_g.get("bot_check"))
