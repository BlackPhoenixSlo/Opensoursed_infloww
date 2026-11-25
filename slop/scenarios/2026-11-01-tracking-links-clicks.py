from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import httpx

from slop.actors import ui
from slop.lib.client import Http, Recorder
from slop.lib.tracking_faults import (BY_DAY, CLAIMERS, CLICKS, CLIENT_IP, CREATED, EARNINGS, GATE_COUNT,
                                     GATE_CREATE, GATE_PAGE, GATE_THROTTLE, GATE_VERIFY, REDIRECT,
                                     STATS_BREAKDOWN, STATS_INVARIANT, STATS_SUMMARY, UI_VIEWED)
from slop.seed import tracking_campaigns

PROFILE = "agency_inbox"
UI = True
FAULT = "tracking-click-lost-1-in-20"
RELAY_ENV = {"EDGE_PROXIES": "cloudflare",
             "TURNSTILE_SITE_KEY": "1x00000000000000000000AA", "TURNSTILE_SECRET_KEY": "slop-turnstile-secret"}
GATED_SLUG_BASE = 79_000_000
PASS_SHARE = 0.75
VERIFY_CAPACITY = 30
PROBE_IP = "100.127.255.254"
CF_HOPS = tuple(f"162.158.88.{i}" for i in range(1, 9))
T_P95_MS = 150
EARNINGS_P95_MS = 2000
STATS_P95_MS = 300
SUMMARY_STORM_P95_MS = 1200
# one relay process saturates under the storm (250 clicks/s + owner reads): a saturation guard, not the product budget (measured summary p95 777 / 878, analytics 286 / 483)
ANALYTICS_STORM_P95_MS = 700
HOT_90D_P95_MS = 600
REPORT_TZ = "America/New_York"
NY = ZoneInfo(REPORT_TZ)
SPOOF_SHARE = 1 / 20
FORGED_COUNTRY = "KP"
RANGES = (7, 30, 90)
OPENED_IN = {"instagram": "Instagram app", "tiktok": "TikTok app", "facebook": "Facebook app",
             "threads": "Threads app", "": "Browser", "bot": "Bots & link previews"}
P95_VS_LAST = (1.5, 100)
P95_VS_LAST_MIN_N = 20
THINK_S = (1.0, 3.0)
TRACKED = ("cleared", "pending")
SUBS = ("subscription", "rebill")
FIGURES = ("earnings_cents", "earnings_net_cents", "net_missing_count", "fans_counted", "fans_who_spent")


def _local_day(hour: str, tz) -> date:
    return datetime.strptime(hour, tracking_campaigns.HOUR).replace(tzinfo=timezone.utc).astimezone(tz).date()


def _window(n: int, tz=NY) -> list[str]:
    today = datetime.now(timezone.utc).astimezone(tz).date()
    return [(today - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _digits(text: str) -> int | None:
    m = re.search(r"\d[\d,]*", text or "")
    return int(m.group().replace(",", "")) if m else None


def _oracle(tc: dict) -> tuple[dict[int, dict], dict[str, int]]:
    claims: dict[tuple[str, int], list[tuple[datetime, datetime | None, int]]] = defaultdict(list)
    out: dict[int, dict] = {}
    per_fan: dict[int, dict[int, list[int]]] = defaultdict(dict)
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
        elif not astride_any:
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
        tz = ZoneInfo(a["tz"]) if a.get("tz") else timezone.utc
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
    rate = ctx.param("rate", {"small": 100.0, "medium": 250.0, "huge": 400.0}[ctx.scale])
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
    if no_astride:
        raise RuntimeError(f"tracking seed: no click between UTC and New York midnight on {no_astride[:5]}")
    oracle, branches = _oracle(tc)
    if not all(branches.values()):
        raise RuntimeError(f"tracking seed misses a branch of the attribution rule: {branches}")
    ctx.metric("world", {"creators": len(aids), "links": len(links), "campaigns": sum(map(len, tc["campaigns"].values())),
                         "claims": sum(map(len, tc["claimers"].values())), "tx": len(tc["tx"]), "clicks": n_clicks,
                         "seeded_clicks": sum(l["seeded"].total() for l in links)})
    r = await ctx.owner.put("/admin/settings/preferences", json={"report_tz": REPORT_TZ})
    if r.status_code != 200:
        raise RuntimeError(f"report_tz PUT -> {r.status_code} {r.text[:200]}")

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
    grng = w.rng("scenario:tracking-links-clicks:gated")
    n_gclicks = ctx.param("gated_clicks", max(20, n_clicks // 10)) if gated else 0
    gplan = [(grng.choice(gated), grng.random() < PASS_SHARE) for _ in range(n_gclicks)]

    def home(i: int) -> str:
        return aids[i % len(aids)]

    def pick(aid: str, k: int) -> int | None:
        return live[aid][k % len(live[aid])] if live[aid] else None

    answers: list[tuple[str, int, str | None, str, str, tuple[str, str, str]]] = []
    fans = [Http(ctx.relay, ctx.rec, limits=1) for _ in range(ctx.users)]
    gfans = [Http(ctx.relay, ctx.rec, limits=1) for _ in range(max(4, ctx.users // 10))]
    n_owners = max(3, ctx.users // 10)
    owners = [ctx.owner.share(limits=4) for _ in range(n_owners)]
    stop = asyncio.Event()
    ctx.rec.stage = "storm"
    t0 = time.perf_counter()

    def today() -> str:
        return datetime.now(timezone.utc).astimezone(NY).strftime("%Y-%m-%d")

    ip_of = {id(h): f"100.64.{i // 250}.{i % 250 + 1}" for i, h in enumerate(fans)}

    def fan_ip(h: Http) -> str:
        return ip_of[id(h)]

    def gfan_ip(k: int) -> str:
        return f"100.96.{k // 250}.{k % 250 + 1}"

    async def click(h: Http, slug: str, ref_l: tuple, ua_l: tuple, country: str | None, spoof: bool) -> None:
        (ref, ref_label), (ua, ua_label) = ref_l, ua_l
        sent = today()
        if spoof:
            edge = {"x-forwarded-for": fan_ip(h), "cf-connecting-ip": fan_ip(h), "cf-ipcountry": FORGED_COUNTRY}
        else:
            edge = {"x-forwarded-for": CF_HOPS[sum(map(ord, slug)) % len(CF_HOPS)], "cf-connecting-ip": fan_ip(h),
                    **({"cf-ipcountry": country} if country else {})}
        labels = ("XX" if spoof else tracking_campaigns.label(country), ua_label, ref_label)
        try:
            r = await h.get(f"/t/{slug}", headers={"user-agent": ua, **edge, **({"referer": ref} if ref else {})})
            answers.append((slug, r.status_code, r.headers.get("location"), sent, today(), labels))
        except httpx.HTTPError:
            pass
        h.c.cookies.clear()

    gated_answers: list[dict] = []

    async def gated_click(h: Http, k: int, g: dict, passes: bool) -> None:
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
            pass
        gated_answers.append(a)
        h.c.cookies.clear()

    async def gated_storm() -> None:
        tasks = []
        grate = max(rate, 10.0) / 10
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
    for aid in aids:
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
    quiet: dict[str, list[float]] = {"summary": [], "analytics": []}
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
            # the budget drains at once, then 3 more: the bucket refills one per 2 s, so the probe must take well under that
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

    con = w.sql()
    try:
        stored = dict(con.execute("SELECT tracking_link_id, COUNT(*) FROM tracking_clicks GROUP BY 1").fetchall())
        storm_ips = Counter(ip for (ip,) in con.execute(
            "SELECT ip FROM tracking_clicks WHERE (ip IS NULL OR ip NOT LIKE '203.0.113.%') AND ip IS NOT ?",
            (PROBE_IP,)))
        counter = dict(con.execute("SELECT id, click_count FROM tracking_links").fetchall())
    finally:
        con.close()
    listed: dict[int, int] = {}
    for aid in aids:
        for l in (await ctx.owner.get(f"/admin/tracking-links?account_id={aid}")).json().get("links", []):
            listed[l["id"]] = l["click_count"]
    sure: dict[str, Counter] = defaultdict(Counter)
    astride: dict[str, Counter] = defaultdict(Counter)
    storm_labels: dict[str, Counter] = defaultdict(Counter)
    for s, st, _, sent, answered, labels in answers:
        if st == 302:
            storm_labels[s][labels] += 1
        if st == 302 and sent == answered:
            sure[s][sent] += 1
        elif st == 302:
            astride[s].update((sent, answered))
    for a in gated_answers:
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
    key = {e_route: f"{e_route} incl. first opens"}
    ctx.metric("p95_vs_last_green", {key.get(r, r): routes[r]["p95_ms"] for r in vs_last})
    ctx.metric("p95_vs_last_green_n", {key.get(r, r): routes[r]["n"] for r in vs_last})

    if ctx.app:
        await _ui(ctx, tc, gated, w)
        await _ui_viewed(ctx, tc)
    else:
        for name in (UI_STATS_TOTAL, UI_GATE, UI_SUMMARY, UI_STATS, UI_PHONE, UI_VIEWED):
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
_GROWTH_TS = Path(__file__).resolve().parents[2] / "app" / "hooks" / "useGrowth.ts"


def _viewed_refresh_ms() -> int:
    m = re.search(r"export const GROWTH_VIEWED_REFRESH_MS = ([\d_]+);", _GROWTH_TS.read_text())
    return int(m.group(1).replace("_", ""))


async def _ui_viewed(ctx, tc) -> None:
    every = _viewed_refresh_ms()
    creator_of = {r["campaignName"]: aid for aid, rows in tc["campaigns"].items() for r in rows}
    reads: list[tuple[str, int, float]] = []

    def on_response(resp) -> None:
        m = re.search(r"/admin/of-tracking-links(/earnings)?\?account_id=", resp.url)
        if m:
            reads.append(("earnings" if m.group(1) else "list", resp.status, time.time()))

    def n(kind: str) -> int:
        return sum(1 for k, st, _t in reads if k == kind and st == 200)

    async def until(pred, timeout_s: float) -> bool:
        t_end = time.monotonic() + timeout_s
        while not pred():
            if time.monotonic() > t_end:
                return False
            await asyncio.sleep(0.2)
        return True

    async with ui.owner_browser(ctx) as page:
        await page.clock.install()
        page.on("response", on_response)
        await page.goto(f"{ctx.app}/growth/tracking-links", wait_until="domcontentloaded")
        await page.get_by_text(re.compile(r"OF link 0$")).first.wait_for(timeout=90_000)
        aid = creator_of.get((await page.get_by_text(re.compile(r"OF link 0$")).first.inner_text()).strip())
        opened = await until(lambda: n("list") >= 1 and n("earnings") >= 1, 30)
        await ui.shot(ctx, page, "growth-viewed-open")
        before = {"list": n("list"), "earnings": n("earnings")}
        left, x = every - 60_000, 0
        while left > 0:
            step = min(5 * 60_000, left)
            await page.clock.fast_forward(step)
            left -= step
            x = 400 + (x + 37) % 300
            # a pointer move per step: 10 min without input is Idle mode (useIdleMode), which stops every poll until the next input
            await page.mouse.move(x, 500)
            await asyncio.sleep(0.3)
        await asyncio.sleep(3)
        early = {"list": n("list"), "earnings": n("earnings")}
        of0 = (await ctx.owner.get("/__slop/tracking-calls")).json()["campaigns"].get(aid or "", 0)
        await page.clock.fast_forward(60_000)
        refetched = await until(lambda: n("list") > before["list"] and n("earnings") > before["earnings"], 30)
        await page.get_by_text(re.compile(r"OF link 0$")).first.wait_for(timeout=30_000)
        await ui.shot(ctx, page, "growth-viewed-settled")
        after = {"list": n("list"), "earnings": n("earnings")}
        of1 = (await ctx.owner.get("/__slop/tracking-calls")).json()["campaigns"].get(aid or "", 0)
        not_200 = [(k, st) for k, st, _t in reads if st != 200]
    ctx.check(UI_VIEWED, bool(aid) and opened and early == before and refetched
              and after == {k: v + 1 for k, v in before.items()} and of1 > of0 and not not_200,
              creator=aid, refresh_ms=every, opened=opened, reads_open=before, reads_59_min=early,
              reads_60_min=after, of_campaigns_reads=[of0, of1], not_200=not_200[:5])


async def _open(ctx, page, tc) -> str | None:
    creator_of = {l["name"]: l["account_id"] for l in tc["links"]}
    await page.goto(f"{ctx.app}/growth/redirect-links", wait_until="domcontentloaded")
    first = page.get_by_role("region", name="Custom redirect links").get_by_text(re.compile(r" link 0$")).first
    await first.wait_for(timeout=90_000)
    shown = (await first.inner_text()).strip()
    await page.locator('[data-stat="today"] [data-value]').filter(has_not_text="—").wait_for(timeout=30_000)
    return creator_of.get(shown)


async def _cards(page) -> dict:
    return {k: _digits(await page.locator(f'[data-stat="{k}"] [data-value]').first.inner_text()) for k in CARDS}


def _row(page, name: str):
    return (page.get_by_role("region", name="Custom redirect links").locator("li")
            .filter(has=page.get_by_text(name, exact=True)).first)


async def _expand(page, name: str) -> dict:
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
                ctx.check(name, False, reason="the page's first redirect link is none of the seeded ones")
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
        zone = ZoneInfo(a["tz"]) if a.get("tz") else timezone.utc
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
