"""Creator earnings read OnlyFans' own Statistics: the Dashboard's earnings card
and Creator reports (Earnings summary and its growth, Earnings trends, Creator
performance) show, for each complete UTC day and category, the larger of what
OF's Statistics › Statements show and what the ledger holds (OF fills the days
before a Creator was connected; it never erases a sale we recorded), the ledger
alone for today; Employee sales stays the ledger's (attribution).

The world: an Agency whose Creators were connected `connected_days` ago (the
owner's case: the ledger has a trickle the month before and most sales since),
with `history_days` of OF earnings (seed/earnings.py). OF's side is answered at
its wire boundary (lib/relay.py `_OfflineOF.earnings_chart` and the Statistics
reads); the OF Statistics job runs through `POST /__slop/of-stats-tick` (its
hourly timer, bypassed) while `--users` owners read the reports.

Invariants: before the job, a window with days before the connection says they
are unknown (so growth shows "-", not +1,700%); every pass reads at most the
job's chunks per Creator, the history is complete (400 days x 5 categories and
OF's total per Creator) and then no OF read is made again; after it, the totals
by kind, each trend day and each Creator's net equal max(OF, ledger) per UTC day
and category (plus today's ledger), the prior window's growth is OF's too, a
window older than the kept history says its days are unknown, Employee sales is
unchanged; on the zero day (OF $0, the ledger one $14 PPV message per Creator,
seed/earnings.py) every Creator keeps its $14; in the report zone
America/Los_Angeles a PPV message at 23:30 local (06:30 UTC the next day, OF's
next UTC day) is counted once, on its local day. UI: the Dashboard's This month
and Creator reports' Last 30 days show those numbers, and Creator reports on
the zero day show the $14s. Budgets: report route p95s under the crowd, and vs
the last green run.
Break-it-once: of-zero-erases-db-sale (OF's day replaces the ledger's, as
shipped in f96535be0); --fault=reports-ignore-of-earnings (the ledger alone).
Screenshots: dashboard-month-{before,after}, creator-reports-30d-{before,after},
creator-reports-zero-day-after (gross), creator-performance-zero-day-after.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from slop.actors import reports, ui
from slop.seed import earnings

PROFILE = "agency_inbox"
UI = True
FAULT = "of-zero-erases-db-sale"
HISTORY_DAYS = 400       # of_stats_daily._EARNINGS_HISTORY_DAYS: the job keeps this many days
CHUNKS_PER_TICK = 4      # of_stats_daily._EARNINGS_CHUNKS_PER_TICK
CATEGORIES = 6           # subscribes, tips, messages, post, stream, and OF's total (of_stats_daily.TOTAL)
# Budgets (ms), per actor call, while the job runs and after: a Dashboard card's read, and Creator
# performance's table (its engagement reads are the heavy part).
P95_MS = {"GET /admin/stats/revenue": 750, "GET /admin/stats/per-model": 1500,
          "GET /admin/stats/per-employee": 750}
P95_VS_LAST = (1.5, 150)
KIND = {"subscribes": "subscription", "tips": "tip", "messages": "ppv_message", "post": "ppv_post"}
CATEGORY = {k: c for c, k in KIND.items()}


def _iso(d: date, end: bool = False) -> str:
    return f"{d.isoformat()}T{'23:59:59.999' if end else '00:00:00.000'}Z"


def _dollars(text: str) -> float | None:
    m = re.search(r"(-?)\$([\d,]+(?:\.\d+)?)", text or "")
    return None if not m else float(m.group(2).replace(",", "")) * (-1 if m.group(1) else 1)


async def run(ctx) -> None:
    w = await ctx.build(PROFILE)
    creators = w.data["creators"]
    ids = [c["id"] for c in creators]
    history = ctx.param("history_days", 130)
    connected_days = ctx.param("connected_days", 9)
    truth = earnings.seed(w, creators, ctx.stack.tmp, history_days=history, connected_days=connected_days)
    today = w.now.date()
    yesterday = today - timedelta(days=1)
    win = {"month": (_iso(today.replace(day=1)), _iso(today, True)),
           "range": (_iso(today - timedelta(days=29)), _iso(today, True)),
           "prior": (_iso(today - timedelta(days=59)), _iso(today - timedelta(days=30), True)),
           "old": (_iso(today - timedelta(days=HISTORY_DAYS + 120)), _iso(today - timedelta(days=HISTORY_DAYS + 90), True))}
    ctx.metric("world", {"creators": len(ids), "history_days": history, "connected": w.data["connected"],
                         "ledger_rows": w.data["ledger_rows"], "windows": win})
    r = await ctx.owner.request("PUT", "/admin/settings/preferences",
                                json={"tz": "UTC", "report_tz": "UTC", "week_start": "monday"})
    ctx.metric("report_tz_put", r.status_code)

    con = w.sql()
    ledger_today = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for aid, kind, gross, net in con.execute(
            "SELECT account_id, kind, SUM(amount_cents), SUM(net_cents) FROM transactions WHERE occurred_at >= ? "
            "AND status IN ('cleared','pending') GROUP BY account_id, kind", (f"{today.isoformat()} 00:00:00",)):
        ledger_today[aid][kind] = [gross, net]
    ledger_day = defaultdict(lambda: defaultdict(int))  # (account, UTC day) -> {category: net}
    for aid, day, kind, net in con.execute(
            "SELECT account_id, date(occurred_at), kind, SUM(net_cents) FROM transactions "
            "WHERE status IN ('cleared','pending') GROUP BY 1, 2, 3"):
        ledger_day[(aid, day)][CATEGORY[kind]] += net
    con.close()
    cases = w.data["earnings_cases"]

    def want(f_iso: str, t_iso: str) -> dict:
        """{account_id: {kind: net}} and {day: net}: each complete UTC day in the window max(OF, ledger) per
        category (OF's history days; the ledger's alone before it), the ledger's today."""
        lo, hi = date.fromisoformat(f_iso[:10]), date.fromisoformat(t_iso[:10])
        per, days = defaultdict(lambda: defaultdict(int)), defaultdict(int)
        d = lo
        while d <= min(hi, yesterday):
            for aid in ids:
                of = truth[aid]["earnings"].get(d.isoformat())
                db = ledger_day.get((aid, d.isoformat()), {})
                for cat in set(of or {}) | set(db):
                    net = db.get(cat, 0) if of is None else max(of.get(cat, [0, 0])[0], db.get(cat, 0))
                    per[aid][KIND[cat]] += net
                    days[d.isoformat()] += net
            d += timedelta(days=1)
        if hi >= today:
            for aid in ids:
                for kind, (_g, net) in ledger_today[aid].items():
                    per[aid][kind] += net
                    days[today.isoformat()] += net
        return {"per": per, "days": days}

    async def rev(group_by: str, f: str, t: str, **kw) -> dict:
        q = {"group_by": group_by, "include_net": "true", "from": f, "to": t, **kw}
        return (await ctx.owner.get(f"/admin/stats/revenue?{urlencode(q)}")).json()

    def by_kind(resp: dict) -> dict:
        out = defaultdict(int)
        for row in resp.get("rows", []):
            out[row["kind"]] += row.get("net_cents") or 0
        return {k: v for k, v in out.items() if v}

    async def employee_total(f: str, t: str) -> int:
        body = (await ctx.owner.get(f"/admin/stats/per-employee?{urlencode({'from': f, 'to': t})}")).json()
        rows = next((v for v in body.values() if isinstance(v, list)), [])
        return sum(r.get("revenue_cents") or 0 for r in rows)

    # ── Before: the ledger alone, and the OF job has not run. ─────────────────
    con = w.sql()
    stored_before = con.execute("SELECT COUNT(*) FROM of_earnings_daily").fetchone()[0]
    con.close()
    before = {k: await rev("kind", *win[k]) for k in ("month", "range", "prior")}
    ctx.metric("before", {k: {"net_by_kind": by_kind(v), "history_missing_days": v.get("history_missing_days")}
                          for k, v in before.items()})
    (ctx.out / "api-before.json").write_text(json.dumps(before, indent=2))
    ctx.check("before the history is read, a window with unknown days says so (history_missing_days > 0)",
              stored_before == 0 and (before["prior"].get("history_missing_days") or 0) > 0,
              stored_rows=stored_before, prior_missing=before["prior"].get("history_missing_days"))
    emp_before = await employee_total(*win["month"])
    ui_before = await _ui_pass(ctx, "before", win["prior"][0]) if ctx.app else None

    # ── The OF job passes while the owners read the reports. ──────────────────
    stop = asyncio.Event()
    ctx.rec.stage = "during-job"  # from the first owners' arrival to the job's last pass
    pool = ctx.owner.share(limits=max(10, ctx.users))
    readers = asyncio.create_task(reports.crowd(pool, win, ids, stop, ctx.users, seed=ctx.seed, rounds=0))
    await asyncio.sleep(reports.THINK_S[1] / 2)  # owners have arrived and are reading
    passes = []
    for _ in range(HISTORY_DAYS // (CHUNKS_PER_TICK * 30) + 2):
        t0 = time.perf_counter()
        body = (await ctx.owner.post("/__slop/of-stats-tick", timeout=600)).json()
        passes.append({"ms": round((time.perf_counter() - t0) * 1000), "of_earnings_reads": body["of_earnings_reads"]})
        if body["of_earnings_reads"] == 0:
            break
    stop.set()
    ctx.rec.stage = "after"
    loads_during = await readers
    ctx.metric("job_passes", passes)
    per_pass_max = len(ids) * (CHUNKS_PER_TICK + 1)  # + the daily snapshot's 7-day re-read
    ctx.check("each job pass reads OF at most its chunks per Creator (+ the daily re-read)",
              all(p["of_earnings_reads"] <= per_pass_max for p in passes), max_allowed=per_pass_max, passes=passes)
    con = w.sql()
    stored = dict(con.execute("SELECT account_id, COUNT(*) FROM of_earnings_daily GROUP BY account_id").fetchall())
    con.close()
    short = {a: stored.get(a, 0) for a in ids if stored.get(a, 0) != HISTORY_DAYS * CATEGORIES}
    ctx.check(f"OF history complete: {HISTORY_DAYS} days x {CATEGORIES} categories per Creator, nothing dropped",
              not short, short=short, want=HISTORY_DAYS * CATEGORIES)
    ctx.check("a complete history makes no more OF earnings reads", bool(passes) and passes[-1]["of_earnings_reads"] == 0,
              last=passes[-1] if passes else None)

    # ── After: OF's days, the ledger's today. ─────────────────────────────────
    ctx.rec.stage = "after"
    stop = asyncio.Event()
    readers = asyncio.create_task(reports.crowd(pool, win, ids, stop, ctx.users, seed=ctx.seed + 1, rounds=2))
    after = {k: await rev("kind", *win[k]) for k in ("month", "range", "prior", "old")}
    trend = await rev("day", *win["range"], by_kind="true")
    pm = (await ctx.owner.get(f"/admin/stats/per-model?{urlencode({'from': win['range'][0], 'to': win['range'][1]})}")).json()
    emp_after = await employee_total(*win["month"])
    stop.set()
    loads_after = await readers
    await pool.aclose()
    (ctx.out / "api-after.json").write_text(json.dumps({**after, "trend": trend, "per_model": pm}, indent=2))

    bad = {}
    for k in ("month", "range"):
        exp = defaultdict(int)
        for kinds in want(*win[k])["per"].values():
            for kind, v in kinds.items():
                exp[kind] += v
        exp = {kd: v for kd, v in exp.items() if v}
        if by_kind(after[k]) != exp:
            bad[k] = {"got": by_kind(after[k]), "want": exp}
    ctx.check("Dashboard and Creator reports totals by kind == max(OF, ledger) per complete day + the ledger (today)",
              not bad, wrong=bad, month=by_kind(after["month"]), range=by_kind(after["range"]))
    exp_days = want(*win["range"])["days"]
    got_days = {row["day"]: row.get("net_cents") or 0 for row in trend.get("rows", [])}
    wrong_days = {d: {"got": got_days.get(d, 0), "want": v} for d, v in exp_days.items() if got_days.get(d, 0) != v}
    wrong_days |= {d: {"got": v, "want": 0} for d, v in got_days.items() if v and d not in exp_days}
    ctx.check("Earnings trends: every day == max(OF, ledger) per category (today: the ledger's)", not wrong_days,
              wrong=len(wrong_days), sample=dict(list(wrong_days.items())[:5]), days=len(exp_days))
    exp_pm = {a: sum(v.values()) for a, v in want(*win["range"])["per"].items()}
    got_pm = {r["account_id"]: r.get("total_net_revenue_cents") or 0 for r in pm.get("per_model", [])}
    wrong_pm = {a: {"got": got_pm.get(a), "want": v} for a, v in exp_pm.items() if got_pm.get(a) != v}
    ctx.check("Creator performance: each Creator's net == max(OF, ledger) per day + today's ledger", not wrong_pm,
              wrong=wrong_pm, creators=len(exp_pm))
    exp_prior = sum(sum(v.values()) for v in want(*win["prior"])["per"].values())
    got_prior = sum(by_kind(after["prior"]).values())
    ctx.check("growth: the prior window is OF's too, with no unknown day",
              got_prior == exp_prior and (after["prior"].get("history_missing_days") or 0) == 0,
              got=got_prior, want=exp_prior, missing=after["prior"].get("history_missing_days"))
    ctx.check("a window older than OF's kept history says its days are unknown",
              (after["old"].get("history_missing_days") or 0) == len(ids) * 31,
              got=after["old"].get("history_missing_days"), want=len(ids) * 31)
    ctx.check("Employee sales stays the ledger's (unchanged by OF's history)", emp_before == emp_after,
              before=emp_before, after=emp_after)
    # The zero day: OF charts $0 for every Creator, the ledger one $14 PPV message each.
    z = cases["zero_day"]
    zero = await rev("day", _iso(date.fromisoformat(z)), _iso(date.fromisoformat(z), True), by_kind="true")
    zero_pm = (await ctx.owner.get(f"/admin/stats/per-model?{urlencode({'from': _iso(date.fromisoformat(z)), 'to': _iso(date.fromisoformat(z), True)})}")).json()
    kept = {r["account_id"]: r.get("total_revenue_cents") for r in zero_pm.get("per_model", [])}
    zrow = next((r for r in zero.get("rows", []) if r["day"] == z), {})
    ppv = next((k for k in zrow.get("by_kind", []) if k["kind"] == "ppv_message"), {})
    ctx.check("DB sale not erased by OF zero day",
              all(kept.get(a) == cases["zero_sale_cents"] for a in ids)
              and ppv.get("total_cents") == cases["zero_sale_cents"] * len(ids) and ppv.get("count") == len(ids),
              day=z, per_creator=kept, want_each=cases["zero_sale_cents"], ppv=ppv)
    (ctx.out / "api-zero-day.json").write_text(json.dumps({"revenue": zero, "per_model": zero_pm}, indent=2))

    # The midnight sale, in the report zone America/Los_Angeles: once, on its local day.
    m = cases["midnight"]
    zone = ZoneInfo(m["tz"])
    ld = date.fromisoformat(m["local_day"])

    def utc_iso(d: date, end: bool = False) -> str:
        """Local midnight of `d` in the zone (with `end`, the last millisecond before it) as a UTC instant."""
        at = datetime.combine(d, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        return (at - timedelta(milliseconds=1 if end else 0)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    r = await ctx.owner.request("PUT", "/admin/settings/preferences",
                                json={"tz": "UTC", "report_tz": m["tz"], "week_start": "monday"})
    try:
        mid = await rev("day", utc_iso(ld), utc_iso(ld + timedelta(days=2), True), account_id=m["account_id"],
                        by_kind="true")
        mid_kind = await rev("kind", utc_iso(ld), utc_iso(ld + timedelta(days=2), True), account_id=m["account_id"])
    finally:
        await ctx.owner.request("PUT", "/admin/settings/preferences",
                                json={"tz": "UTC", "report_tz": "UTC", "week_start": "monday"})
    got_mid = {row["day"]: (row["total_cents"], row["count"]) for row in mid.get("rows", []) if row["total_cents"]}
    got_kind = sum(row["total_cents"] for row in mid_kind.get("rows", []))
    ctx.check("a sale at 23:30 UTC-7 lands on its local day once (OF's next UTC day adds nothing)",
              r.status_code == 200 and got_mid == {m["local_day"]: (m["gross_cents"], 1)}
              and got_kind == m["gross_cents"],
              put=r.status_code, sale_utc=m["utc"], days=got_mid, by_kind_total=got_kind,
              want={m["local_day"]: (m["gross_cents"], 1)})

    gross_off = {}
    for k in ("month", "range"):
        g = sum(row.get("total_cents") or 0 for row in after[k].get("rows", []))
        n = sum(by_kind(after[k]).values())
        gross_off[k] = {"gross": g, "net": n, "net_over_gross": round(n / g, 4) if g else None}
    ctx.metric("after", {k: {"net_by_kind": by_kind(v), "history_missing_days": v.get("history_missing_days")}
                         for k, v in after.items()} | {"gross": gross_off})
    ctx.check("net is OF's 80% of gross (fee 20%), within a cent a day",
              all(x["net_over_gross"] is not None and abs(x["net_over_gross"] - 0.8) < 0.001 for x in gross_off.values()),
              **gross_off)

    ctx.metric("page_loads", {"during_job": loads_during, "after": loads_after})
    p95s, ns = {}, {}
    for stage in ("during-job", "after"):
        routes = ctx.rec.summary(stage)
        for route, budget in P95_MS.items():
            name = f"p95 {route} < {budget}ms ({stage})"
            if route in routes:
                ctx.check(name, routes[route]["p95_ms"] < budget, budget=True, p95=routes[route]["p95_ms"],
                          n=routes[route]["n"])
                p95s[f"{stage} {route}"], ns[f"{stage} {route}"] = routes[route]["p95_ms"], routes[route]["n"]
            else:
                ctx.skip(name, "no samples")
    ctx.metric("p95_vs_last_green", p95s)
    ctx.metric("p95_vs_last_green_n", ns)
    ctx.rec.stage = None

    if not ctx.app:
        for n in UI_CHECKS:
            ctx.skip(n, "--no-ui")
        return
    ui_after = await _ui_pass(ctx, "after", win["prior"][0], zero_day=z)
    ctx.metric("ui", {"before": ui_before, "after": ui_after})
    ctx.check(UI_CHECKS[0], ui_before["reports_growth"] == "-", growth=ui_before["reports_growth"])
    month_api = sum(by_kind(after["month"]).values()) / 100
    range_api = sum(by_kind(after["range"]).values()) / 100
    ctx.check(UI_CHECKS[1], ui_after["dashboard_total"] is not None and abs(ui_after["dashboard_total"] - month_api) < 1,
              ui=ui_after["dashboard_total"], api=month_api, before=ui_before["dashboard_total"])
    ctx.check(UI_CHECKS[2], ui_after["reports_total"] is not None and abs(ui_after["reports_total"] - range_api) < 1
              and ui_after["reports_growth"] not in ("-", ""),
              ui=ui_after["reports_total"], api=range_api, growth=ui_after["reports_growth"],
              before=ui_before["reports_total"])
    ctx.check(UI_CHECKS[3], not (ui_before["5xx"] or ui_after["5xx"]), before=ui_before["5xx"], after=ui_after["5xx"])
    zero_api = sum(row.get("total_cents") or 0 for row in zero.get("rows", [])) / 100
    ctx.check(UI_CHECKS[4], ui_after["zero_total"] is not None and abs(ui_after["zero_total"] - zero_api) < 1,
              ui=ui_after["zero_total"], api=zero_api, want=cases["zero_sale_cents"] * len(ids) / 100,
              day=z, shots=[ui_after["zero_shot"], ui_after["zero_table_shot"]])


UI_CHECKS = ("UI before: Creator reports' growth against unknown days shows '-'",
             "UI: Dashboard This month total == OF Statistics + today's ledger (the API's)",
             "UI: Creator reports Last 30 days Total earnings == OF Statistics + today's ledger, with a growth %",
             "no 5xx in the browser sessions",
             "UI: Creator reports on OF's $0 day show the API's gross (the ledger's $14 per Creator)")


async def _ui_pass(ctx, tag: str, prior_from: str, zero_day: str | None = None) -> dict:
    out = {}
    async with ui.owner_browser(ctx, viewport=(1440, 1000)) as page:
        await page.goto(f"{ctx.app}/?window=month", wait_until="domcontentloaded")
        total = page.locator("[data-control=total]").last
        await total.wait_for(timeout=120_000)
        await page.wait_for_function(
            "() => /\\$\\d/.test([...document.querySelectorAll('[data-control=total]')].pop()?.textContent || '')",
            timeout=60_000)
        await page.wait_for_timeout(1500)
        out["dashboard_shot"] = await ui.shot(ctx, page, f"dashboard-month-{tag}")
        out["dashboard_total"] = _dollars(await total.inner_text())

        await page.goto(f"{ctx.app}/analytics/creator-reports", wait_until="domcontentloaded")
        await page.get_by_role("button", name="Date range").first.wait_for(timeout=120_000)
        await page.get_by_role("button", name="Date range").first.click()
        async with page.expect_response(lambda r: "/admin/stats/revenue" in r.url and "group_by=kind" in r.url
                                        and parse_qs(urlsplit(r.url).query).get("from", [""])[0][:10]
                                        == prior_from[:10], timeout=60_000):
            await page.get_by_role("button", name="Last 30 days").click()
        await page.keyboard.press("Escape")
        tile = page.get_by_role("group", name="Total earnings")
        await page.wait_for_function(
            "() => { const g = document.querySelector('[role=group][aria-label=\"Total earnings\"]');"
            " const dd = g && g.querySelectorAll('dd'); return dd && /\\$\\d/.test(dd[0].textContent); }",
            timeout=60_000)
        await page.wait_for_timeout(2500)
        out["reports_shot"] = await ui.shot(ctx, page, f"creator-reports-30d-{tag}")
        dds = tile.locator("dd")
        out["reports_total"] = _dollars(await dds.nth(0).inner_text())
        out["reports_growth"] = (await dds.nth(1).inner_text()).strip()
        if zero_day:
            # The zero day alone (Custom: From, then To), its Total earnings and Creator performance.
            await page.get_by_role("button", name="Date range").first.click()
            await page.get_by_label("From date").fill(zero_day)
            async with page.expect_response(lambda r: "/admin/stats/revenue" in r.url and "group_by=kind" in r.url
                                            and parse_qs(urlsplit(r.url).query).get("to", [""])[0][:10] == zero_day,
                                            timeout=60_000):
                await page.get_by_label("To date").fill(zero_day)
            await page.keyboard.press("Escape")
            # Gross ("Show net earnings" off): the $14 a fan paid, as the owner reads a sale.
            async with page.expect_response(lambda r: "/admin/stats/" in r.url, timeout=60_000):
                await page.get_by_role("switch", name="Show net earnings").click()
            await page.wait_for_timeout(2500)
            out["zero_shot"] = await ui.shot(ctx, page, f"creator-reports-zero-day-{tag}")
            out["zero_total"] = _dollars(await dds.nth(0).inner_text())
            await page.get_by_role("tab", name="Creator performance").or_(
                page.get_by_role("button", name="Creator performance")).first.click()
            await page.wait_for_timeout(3000)
            out["zero_table_shot"] = await ui.shot(ctx, page, f"creator-performance-zero-day-{tag}")
        out["5xx"] = [u for s, u in page.slop["statuses"] if s >= 500 and "/api/of/" not in u][:10]
    return out
