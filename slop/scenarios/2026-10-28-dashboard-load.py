"""The owner opens the Dashboard (`/`) on a phone far from the host: how long until Total
earnings shows, and what the time is spent on. A live deployment (2026-10-28) took 3-4 s on
the owner's iPhone 13 against ~1 s for a CDN-fronted competitor page.

The stack is served the way a live deployment serves it: the app as a production build
(`APP_MODE = "prod"`: `next build` + `next start`, minified split chunks) whose rewrites
proxy every relay path, behind a TLS + HTTP/2 edge (nghttpx, as Traefik) and a WAN of
`rtt_ms` round trip (lib/wan.py: a fresh connection pays connect + TLS + request = 3 RTTs,
as measured from the laptop to the host). OnlyFans is lib/of_wire.py (`OF_WIRE`), each
call `of_ms` (800 ms: prod's cold per-Creator reads took 0.9-1.3 s in the relay's own
access log, 10:51:30 and 10:52:08 UTC), one Creator `slow_ms` more (3700 ms: prod's
70001383, whose proxy answered CONNECT 403 three times, 4.7 s for subscriptions/count/all).

The world: one Agency with `creators` (4) Creators, as the owner's: all but the last with
a captured session; this week's earnings in the ledger (seed/earnings.py); report time
zone America/Los_Angeles (UTC-7 on 2026-10-28, the owner's).

A phone (390x844, touch, iPhone user agent; Chromium, so WebKit's own costs are not
measured) loads `/` under each network `nets` (Chromium's throttling: bandwidth and CPU
slowdown; the RTT is lib/wan.py's), three visits each on one browser profile, each a new
browser process (fresh connections):
  first         nothing cached (no HTTP cache, no IndexedDB query cache, no auth snapshot)
  return        everything cached (the immutable chunks, the query cache, the snapshot)
  after-deploy  the query cache and snapshot kept, the HTTP cache cleared (new chunk
                names after a deploy: the owner's 10:51:28 visit, DCL 5.4 s)
Then Messages Pro (`/messages-pro`) once per network on a profile of its own (`mp-first`:
nothing cached), until its Fan List shows rows.
The relay restarts before each network's first visit (its OF caches cold, as on the
owner's first visit). Each visit's Resource Timing (every request's start, first byte and
end), paint marks (Total earnings' figure, the page settled with no shimmer or spinner)
and long tasks go to `waterfall-<net>-<visit>.json` / `.txt`; screenshots per visit: the
first frame on screen while the JS still loads (`-frame`, all but return visits), the
Total's first paint (`-total-painted`, Dashboard) and the settled page.

Invariants: every visit painted Total earnings; the figure equals the relay's own answer
for the same window (`GET /admin/stats/revenue` + referrals, Net, as the card sums them;
the side-effect check); every page request rode HTTP/2 and none answered 5xx; Total
earnings painted before the slow Creator's OnlyFans reads ended (the figure never waits
on OF); a visit with the saved query cache (return, after-deploy) painted the saved Total
before its revenue read answered, the same figure the settled page shows (the revenue
read and the Applied settings ride the IndexedDB snapshot, keyed by principal); the
session-less Creator (no account on the host, so absent from `/admin/accounts`, as prod's
800000779) sent no OnlyFans request from its card (each `/api/of/` request's
`X-Account-Id`, from Playwright's request events) and wears its "Not connected" label,
while every live Creator's card still read OF; never blank while the JS loads (2026-10-29,
the owner: "paint the layout right away, then the numbers fill in"): on every Dashboard
load whose JS comes over the network and on Messages Pro's first visit, the route's frame
from the server's HTML (AuthGate's BootSkeleton: the earnings card's labels with a bar
per figure; the Fan List's skeleton rows) was on screen (visible, stamped at its next
frame) before the app's first relay read (/auth/me, from the hydrated app; the old gate
drew nothing until it answered), and the settled page has none of it left (Messages Pro:
Fan rows in). The page sweep (2026-10-29, the owner: "same for all pages"): every signed-in route
(`SWEEP_ROUTES`: each sidebar page, the settings tabs, the message dashboard's tabs, a Messages Pro
chat) opened on a phone, four tabs at once, its relay reads held until the held screen is measured
and shot (`screenshots/pages/NN_<route>-held.png`), then released and measured settled (`-settled`):
held, no spinner, no "Loading…" line, no empty state (`[data-empty-state]`) and no blank area (no
placeholder bars and content well short of the settled depth); settled, none of those and no
placeholder left (`page-sweep.json`). Billing's static "No invoices" is exempt (`SWEEP_STATIC_EMPTY`).
Budgets: Total earnings on a return visit per network (`BUDGET_MS`).
Break-it-once (each turns only its targets red):
  dashboard-total-waits-of-reads  the revenue answer held until the page's OF reads are
                                  done: the never-waits check (first visits; a saved
                                  Total paints before any answer)
  dashboard-total-not-saved       the snapshot written without the revenue read and the
                                  Applied settings (before 2026-10-28): the saved-Total
                                  check and the two budgets
  dashboard-offline-creator-reads-of  `/admin/accounts` reaches the page as a 503, so the
                                  cards cannot tell which Creators have a session and
                                  read OF for all (as before 2026-10-28): the
                                  session-less check
  boot-skeleton-not-drawn         the boot skeleton hidden from the first byte, as the
                                  old AuthGate's `null` drew nothing until /auth/me
                                  answered (CSS: the server render is out of the
                                  browser's reach): the two frame checks
  page-placeholders-not-drawn     every `[data-loading]` placeholder hidden (CSS), as the
                                  pages drew no layout before their first data: the
                                  page sweep

`--no-ui`: no browser; the Dashboard's relay reads are timed in their chain (applied
settings, then revenue and referrals) and the browser checks SKIP.

Bypasses, declared: lib/wan.py's RTT is a delay proxy (no loss, no TCP slow start: a big
download on a fresh connection is a little faster than on a real link); bandwidth and CPU
are Chromium's throttling (not an iPhone's radio or A15); the proxy retries are modelled
as `slow_ms` at OF's wire, not run; lib/of_wire.py's answers are its own (no new fans, $0
referrals; the chat list is the seeded Fans, one text message each); the app is built
from this checkout without a deployment's brand env (same chunks bar the brand strings); Next runs unthrottled on the laptop (prod: 0.75 CPU; its HTML took
10-18 ms there). The sweep holds the relay reads in the browser (Playwright routing; `/auth/me`,
`/chatter/me` and Next's own chunks and RSC pass) rather than slowing the relay, and runs unthrottled, with
the slow proxy off (every Creator's OF reads at `of_ms`) and Fansly Manager switched on (`PUT /admin/settings/flags`).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from slop.actors.ui import LAUNCH_ARGS
from slop.lib.faults import FAULTS
from slop.lib.wan import WanEdge
from slop.seed import agency, earnings, fans, of_sessions, threads
from slop.seed import creators as creators_seed

UI = True
# roster-counts logs each failed per-Creator OF read with its traceback; the session-less Creator's is expected
# (prod logs the same for 800000779 on every Dashboard load).
EXPECTED_TRACEBACKS = (("roster-counts: OF read failed", "has no captured session"),
                       # The sweep's Share for Share pages: the session-less Creator's OF profile, kept as stored.
                       ("s4s: OnlyFans profile of", "has no captured session"))
APP_MODE = "prod"
OF_WIRE = True
FAULT = "dashboard-total-waits-of-reads"
CREATORS = 4
RTT_MS = 190
OF_MS = 800
SLOW_MS = 3700
REPORT_TZ = "America/Los_Angeles"
# Chromium's throttling per network: down/up kbit/s, CPU slowdown. slow4g is Lighthouse's
# mobile profile (the /login measurement's 1.6 Mbit, 4x); lte is a guess at an iPhone 13
# on a decent LTE / Wi-Fi link.
NETS = {"lte": (12_000, 4_000, 2), "slow4g": (1_600, 750, 4)}
VISITS = ("first", "return", "after-deploy")
# Total earnings painted on a return visit (ms from navigation start), per network. The first green run
# (20261028T113107Z-...-08b0) painted it at 1135 / 1328 ms, the network chain auth/me | applied -> revenue. Since
# the revenue read and the Applied settings ride the saved snapshot (2026-10-28) it paints from IndexedDB at
# 723 / 858 ms (20261028T125758Z-...-974b); ~370 ms of headroom, under the chain's own time.
BUDGET_MS = {"lte": 1_100, "slow4g": 1_250}
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

C_PAINT = "every visit painted Total earnings"
C_MATCH = "the painted Total equals the relay's revenue + referrals for the same window (Net)"
C_H2 = "every page request rode HTTP/2 through the TLS edge and none answered 5xx"
C_NOWAIT = "Total earnings painted before the slow-proxy Creator's OnlyFans reads ended (it never waits on OF)"
C_SAVED = ("a visit with the saved query cache painted the saved Total before its revenue read answered, "
           "the figure the settled page shows")
C_OFFLINE = ("the session-less Creator's card sent no OnlyFans request and shows 'Not connected'; "
             "every live Creator's card read OF")


C_FRAME = ("Dashboard loads whose JS comes over the network (first, after-deploy): the page's frame (the earnings "
           "card's labels, placeholder bars for the figures) painted before the app's first relay read, and the "
           "settled page has no skeleton left")
C_FRAME_MP = ("Messages Pro, first visit: its frame (the Fan List's skeleton rows) painted before the app's first relay "
              "read, and the settled list shows Fan rows and no skeleton")
C_SWEEP = ("every signed-in page, its relay reads held: no blank area, spinner, 'Loading…' line or empty state "
           "before its first data (its layout with placeholder bars instead), and none of those left once the reads "
           "answer")


def C_BUDGET(net: str) -> str:
    return f"{net}: Total earnings painted within BUDGET_MS on a return visit"


PROBE_JS = r"""(() => {
  try { performance.setResourceTimingBufferSize(2000); } catch (e) {}
  const S = window.__dash = { marks: {}, longTasks: [], busy: -1 };
  const mark = (k) => { if (!(k in S.marks)) S.marks[k] = performance.now(); };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) S.longTasks.push([e.startTime, e.duration]); })
        .observe({ type: 'longtask', buffered: true }); } catch (e) {}
  let queued = false;
  const check = () => {
    queued = false;
    if (document.querySelector('[data-control="title"]')) mark('card');
    // The page's frame on screen: the boot skeleton (server HTML) or the real shell's main; visible, so a hidden
    // one does not count. Stamped at the next frame, as the Total is.
    const seen = (el) => !!el && (el.checkVisibility ? el.checkVisibility() : el.getClientRects().length > 0);
    const boot = document.querySelector('[data-boot-skeleton]');
    if (seen(boot) && !S.bootRoute) { S.bootRoute = boot.getAttribute('data-boot-skeleton'); requestAnimationFrame(() => mark('boot')); }
    if (!S.framed && (seen(boot) || seen(document.querySelector('main')))) { S.framed = true; requestAnimationFrame(() => mark('frame')); }
    if (S.bootRoute && !boot) mark('bootGone');
    if (document.querySelector('[data-chat-row]')) mark('rows');
    if (document.querySelector('[data-control="total"] [data-loading]')) mark('shimmer');
    const fig = document.querySelector('[data-control="total"] [data-figure]');
    if (fig && !('total' in S.marks) && !S.totalText) {
      S.totalText = fig.textContent; requestAnimationFrame(() => mark('total'));
    }
    S.busy = document.querySelectorAll('[data-loading], [role="status"], [data-boot-skeleton], [aria-busy="true"]').length;
  };
  new MutationObserver(() => { if (!queued) { queued = true; queueMicrotask(check); } })
    .observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
})();"""

COLLECT_JS = r"""() => {
  const n = performance.getEntriesByType('navigation')[0] || {};
  const r = (e) => ({ name: e.name, type: e.initiatorType, start: e.startTime, req: e.requestStart,
    ttfb: e.responseStart, end: e.responseEnd, transfer: e.transferSize, encoded: e.encodedBodySize,
    decoded: e.decodedBodySize, proto: e.nextHopProtocol, status: e.responseStatus });
  return { origin: performance.timeOrigin, nav: { ...r(n), dcl: n.domContentLoadedEventEnd, load: n.loadEventEnd,
             fetchStart: n.fetchStart, dnsStart: n.domainLookupStart, dnsEnd: n.domainLookupEnd,
             connectStart: n.connectStart, connectEnd: n.connectEnd, secure: n.secureConnectionStart },
           res: performance.getEntriesByType('resource').map(r),
           paint: Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime])),
           marks: window.__dash.marks, firstTotal: window.__dash.totalText, bootRoute: window.__dash.bootRoute || null,
           bootLeft: document.querySelectorAll('[data-boot-skeleton]').length,
           chatRows: document.querySelectorAll('[data-chat-row]').length,
           offline: Array.from(document.querySelectorAll('[data-of-offline]')).map((b) =>
             ({ label: b.textContent, card: ((b.closest('[class*="p-4"]') || {}).textContent || '') })),
           total: (document.querySelector('[data-control="total"] [data-figure]') || {}).textContent || null, busy: window.__dash.busy,
           longTasks: window.__dash.longTasks };
}"""


def _money(cents: int) -> str:
    """DashboardHeader's `money`: whole dollars, thousands separator, the minus first."""
    d = (Decimal(abs(cents)) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"{'-' if cents < 0 else ''}${int(d):,}"


def _path(url: str) -> str:
    u = urlsplit(url)
    return u.path + (f"?{u.query}" if u.query else "")


def _first(res: list[dict], prefix: str) -> dict | None:
    hits = [e for e in res if _path(e["name"]).startswith(prefix)]
    return min(hits, key=lambda e: e["start"]) if hits else None


def _summary(d: dict) -> dict:
    """The visit's waterfall in the numbers the report ranks: ms from navigation start."""
    res, nav = d["res"], d["nav"]
    js = [e for e in res if e["name"].endswith(".js")]
    css = [e for e in res if e["name"].endswith(".css") or e["name"].endswith(".woff2")]
    fetches = [e for e in res if e["type"] in ("fetch", "xmlhttprequest") and "/perflog/" not in e["name"]]
    of = [e for e in fetches if "/api/of/" in e["name"]]
    lt = d["longTasks"]
    total = d["marks"].get("total")
    out = {
        "html_ttfb": nav.get("ttfb"), "html_end": nav.get("end"), "connect_ms": (nav.get("connectEnd") or 0) - (nav.get("connectStart") or 0),
        "dcl": nav.get("dcl"), "load": nav.get("load"), "fcp": d["paint"].get("first-contentful-paint"),
        "js_files": len(js), "js_transfer_kb": round(sum(e["transfer"] or 0 for e in js) / 1024, 1),
        "js_decoded_kb": round(sum(e["decoded"] or 0 for e in js) / 1024, 1),
        "js_end": max((e["end"] for e in js), default=None), "css_font_end": max((e["end"] for e in css), default=None),
        "first_fetch_start": min((e["start"] for e in fetches), default=None),
        "relay_reads": len(fetches), "of_reads": len(of), "of_last_end": max((e["end"] for e in of), default=None),
        "last_fetch_end": max((e["end"] for e in fetches), default=None),
        "frame": d["marks"].get("frame"), "boot": d["marks"].get("boot"), "boot_route": d.get("bootRoute"),
        "boot_gone": d["marks"].get("bootGone"), "rows": d["marks"].get("rows"),
        "card": d["marks"].get("card"), "total_painted": total, "total_text": d["total"],
        "longtask_ms_before_total": round(sum(dur for s, dur in lt if total is None or s < total)),
        "longtasks_before_total": sum(1 for s, _ in lt if total is None or s < total),
    }
    for name, prefix in (("auth_me", "/auth/me"), ("chatter_me", "/chatter/me"), ("applied", "/admin/settings/applied"),
                         ("revenue", "/admin/stats/revenue"), ("referrals", "/admin/stats/referrals"),
                         ("per_model", "/admin/stats/per-model"), ("per_employee", "/admin/stats/per-employee")):
        e = _first(fetches, prefix)
        out[name] = None if e is None else {"start": round(e["start"]), "ttfb": round(e["ttfb"]), "end": round(e["end"])}
    return {k: (round(v) if isinstance(v, float) else v) for k, v in out.items()}


def _table(d: dict) -> str:
    rows = [("navigation " + _path(d["nav"]["name"]), d["nav"]["start"], d["nav"]["ttfb"], d["nav"]["end"],
             d["nav"]["transfer"], d["nav"]["proto"], d["nav"]["status"])]
    rows += [(_path(e["name"])[:110], e["start"], e["ttfb"], e["end"], e["transfer"], e["proto"], e["status"])
             for e in sorted(d["res"], key=lambda e: e["start"])]
    lines = [f"{'start':>7} {'ttfb':>7} {'end':>7} {'KB':>7} {'proto':>5} {'st':>4}  request"]
    lines += [f"{s:7.0f} {t:7.0f} {e:7.0f} {(b or 0) / 1024:7.1f} {p or '':>5} {st or '':>4}  {n}"
              for n, s, t, e, b, p, st in rows]
    lines += ["", "marks: " + json.dumps({k: round(v) for k, v in d["marks"].items()}),
              "paint: " + json.dumps({k: round(v) for k, v in d["paint"].items()})]
    return "\n".join(lines) + "\n"


async def _visit(ctx, pw, edge, net: str, visit: str, udir, slow: str, path: str = "/") -> dict:
    """One visit of `path` (the Dashboard, or Messages Pro: `mp-first`, a profile of its own). Painted: the Total
    (Dashboard) or a Fan List row (Messages Pro)."""
    down, up, cpu = NETS[net]
    fault = FAULTS.get(ctx.fault or "")
    bctx = await pw.chromium.launch_persistent_context(
        str(udir), args=[*LAUNCH_ARGS, *edge.chrome_args], viewport={"width": 390, "height": 844},
        device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=IPHONE_UA)
    try:
        if visit in ("first", "mp-first"):
            # The owner's session as "Remember me (always)" leaves it: a persistent cookie, so it survives the
            # browser closing (a session cookie would not, and the return visits would land on /login).
            await bctx.add_cookies([{"name": c.name, "value": c.value, "url": edge.url,
                                     "expires": time.time() + 30 * 86400} for c in ctx.owner.c.cookies.jar])
        # A fault aimed at the page sweep is the sweep's alone.
        for js in (PROBE_JS, *((fault.browser_js,) if fault and fault.browser_js and C_SWEEP not in fault.targets else ())):
            await bctx.add_init_script(js)
        page = bctx.pages[0] if bctx.pages else await bctx.new_page()
        # Every OnlyFans request the page sends, with the Creator it names (X-Account-Id; Resource Timing has no
        # headers). Listening only: no route, so no request is held.
        of_sent: list[dict] = []
        page.on("request", lambda r: of_sent.append({"path": _path(r.url), "account": r.headers.get("x-account-id")})
                if "/api/of/" in r.url else None)
        cdp = await bctx.new_cdp_session(page)
        await cdp.send("Network.enable")
        if visit == "after-deploy":
            await cdp.send("Network.clearBrowserCache")
        await cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 0, "downloadThroughput": down * 1000 / 8,
            "uploadThroughput": up * 1000 / 8, "connectionType": "cellular4g"})
        await cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})
        await cdp.send("Performance.enable")
        t_nav = time.time()
        await page.goto(edge.url + path, wait_until="commit", timeout=120_000)
        shot = f"{'messages-pro' if path != '/' else 'dashboard'}-{net}-{visit}"
        if visit != "return":
            # The first frame on screen while the JS is still loading (the boot skeleton); the return visit's JS is
            # cached, so its frame and its page come together.
            try:
                await page.wait_for_function("() => window.__dash && 'frame' in window.__dash.marks", timeout=60_000)
                await page.screenshot(path=str(ctx.out / "screenshots" / f"{shot}-frame.png"))
            except Exception:  # noqa: BLE001  no frame: recorded by the marks, the check says so
                pass
        painted = True
        done = "total" if path == "/" else "rows"
        try:
            await page.wait_for_function(f"() => window.__dash && '{done}' in window.__dash.marks", timeout=60_000)
        except Exception:  # noqa: BLE001  never painted: recorded, the check says so
            painted = False
        perf = {m["name"]: m["value"] for m in (await cdp.send("Performance.getMetrics"))["metrics"]}
        # The reload's first paint of the Total (on a return visit, the saved figure), after its timings are taken.
        if path == "/":
            await page.screenshot(path=str(ctx.out / "screenshots" / f"{shot}-total-painted.png"))
        # Settled: no shimmer or spinner, and no new request for 2.5 s (at most 45 s after the paint).
        last_n, still, t0 = -1, 0.0, time.time()
        while time.time() - t0 < 45:
            n, busy = await page.evaluate("() => [performance.getEntriesByType('resource').length, window.__dash.busy]")
            still = still + 0.25 if (n == last_n and busy == 0) else 0.0
            if still >= 2.5:
                break
            last_n = n
            await asyncio.sleep(0.25)
        d = await page.evaluate(COLLECT_JS)
        d["painted"], d["t_nav"], d["of_sent"] = painted, t_nav, of_sent
        d["script_ms_to_total"] = round(perf.get("ScriptDuration", 0) * 1000)
        d["task_ms_to_total"] = round(perf.get("TaskDuration", 0) * 1000)
        await page.screenshot(path=str(ctx.out / "screenshots" / f"{shot}.png"))
        # Flush the query cache to IndexedDB now (rqPersister saves on pagehide), as a phone leaving the page does.
        await page.evaluate("() => window.dispatchEvent(new Event('pagehide'))")
        await asyncio.sleep(1.0)
    finally:
        await bctx.close()
    # The slow Creator's OF calls during this visit, in ms from navigation start (one clock: this machine's).
    with ctx.of_wire.lock:
        calls = [c for c in ctx.of_wire.calls if c["account"] == slow and c["t"] * 1000 >= d["origin"]]
    d["slow_of_calls"] = [{"route": c["route"], "end": round(c["t"] * 1000 - d["origin"])} for c in calls]
    return d


async def _no_ui(ctx) -> None:
    """The Dashboard's reads in their chain, from the relay's side."""
    t0 = time.perf_counter()
    r = await ctx.owner.get("/admin/settings/applied")
    t1 = time.perf_counter()
    q = "from=2026-10-26T07%3A00%3A00.000Z&to=2026-11-02T07%3A59%3A59.999Z"
    rev, refs = await asyncio.gather(ctx.owner.get(f"/admin/stats/revenue?{q}&group_by=kind&include_net=true"),
                                     ctx.owner.get("/admin/stats/referrals?from=2026-10-26&to=2026-11-01"))
    t2 = time.perf_counter()
    ctx.metric("no_ui_chain_ms", {"applied": round((t1 - t0) * 1000), "revenue+referrals": round((t2 - t1) * 1000),
                                  "statuses": [r.status_code, rev.status_code, refs.status_code]})
    for name in (C_PAINT, C_MATCH, C_H2, C_NOWAIT, C_SAVED, C_OFFLINE, C_FRAME, C_FRAME_MP, C_SWEEP, *(C_BUDGET(n) for n in NETS)):
        ctx.skip(name, "--no-ui: no browser")


# ── The page sweep: every signed-in page before its first data ─────────────────────────────────────────────────
# Each page opened on a phone with its relay reads held (everything the app fetches but the principal probes and
# Next's own chunks) until the held moment is measured, then released and measured again settled.
SWEEP_ROUTES = """/ /analytics/creator-reports /analytics/employee-reports /analytics/fan-reports
/analytics/message-dashboard /analytics/message-dashboard?tab=all /analytics/message-dashboard?tab=posts
/analytics/message-dashboard?tab=myfeed /analytics/sales-records /creators /creators/proxy /employees /employees/shifts
/group /growth/auto-follow /growth/auto-funnel /growth/auto-mass /growth/auto-post /growth/auto-reply
/growth/auto-story /growth/free-trial-links /growth/gen-info /growth/get-to-know-fans
/growth/profile-promotion /growth/scripts /growth/sensitive-words /growth/smart-lists /growth/smart-messages
/growth/tracking-links /growth/vault-pro /help-center /messages-pro /notifications /admin/manage
/settings/about /settings/account /settings/ai-keys /settings/audit /settings/balance /settings/billing
/settings/cotag /settings/messaging /settings/preferences /settings/roles /settings/sales /settings/security-org
/settings/security-personal /settings/system /settings/time-tracking /share-for-share/discover-creators
/share-for-share/requests /share-for-share/schedule /share-for-share/settings /fansly-manager/notifications
/fansly-manager/lists /fansly-manager/scheduled /fansly-manager/earning-statistics /of-manager/home
/of-manager/messages /of-manager/notifications /of-manager/queue /of-manager/vault /of-manager/statements
/of-manager/statistics /of-manager/bank /of-manager/profile /of-manager/settings /of-manager/collections
/of-manager/streaming /of-manager/release-forms /of-manager/new-post""".split()
#: Pages whose empty state is their content, not a read's answer (no read to wait for), and why.
SWEEP_STATIC_EMPTY = {
    "/settings/billing": "Billing's 'No invoices' on both subtabs is static: Inflowwww bills nothing",
}
SWEEP_PASS = ("/auth/me", "/chatter/me", "/_next/", "/__nextjs", "/favicon", "/icon", "/manifest")
SWEEP_TABS = 4
#: Settled = no `[data-loading]` placeholder for 1.5 s on end (polled per frame).
SWEEP_QUIET = """() => { const t = performance.now();
  if (document.querySelector('[data-loading]')) { window.__sweepQuiet = 0; return false; }
  window.__sweepQuiet = window.__sweepQuiet || t; return t - window.__sweepQuiet > 1500; }"""
#: How long a released page may take to draw its data (its placeholders gone).
SWEEP_SETTLE_MS = 20_000
#: Held content must reach this share of the depth the settled page's content reaches (else: a blank area).
SWEEP_DEPTH = 0.6
#: Each page gets a browser context of its own (no IndexedDB snapshot); this drops what older builds kept in
#: localStorage too, so every page is a first load.
SWEEP_JS = r"""(() => { try { for (const k of Object.keys(localStorage)) if (/query|rq|cache/i.test(k)) localStorage.removeItem(k); }
  catch (e) {} })();"""
SWEEP_PROBE = r"""() => {
  const vis = (e) => { if (e.checkVisibility && !e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2 && r.bottom > 0 && r.top < innerHeight; };
  const main = document.querySelector('main');
  const root = main || document.body;
  const leaf = [...root.querySelectorAll('*')].filter((e) => e.childElementCount === 0);
  const r = main ? main.getBoundingClientRect() : { top: 0, left: 0, width: innerWidth };
  return {
    boot: !!document.querySelector('[data-boot-skeleton]'),
    spinners: [...root.querySelectorAll('.animate-spin')].filter((e) => vis(e) && !e.closest('button')).length,
    loading_text: leaf.filter((e) => /^\s*loading\b.{0,30}$/i.test(e.textContent || '') && vis(e) && !e.closest('button')).map((e) => e.textContent.trim()).slice(0, 3),
    empty: [...root.querySelectorAll('[data-empty-state]')].filter(vis).map((e) => e.getAttribute('data-empty-state')),
    placeholders: [...document.querySelectorAll('[data-loading]')].filter(vis).length,
    frames: [...root.querySelectorAll('iframe')].filter(vis).map((f) => {
      let d = null; try { d = f.contentDocument; } catch (e) {}
      return { ready: d ? d.readyState : 'x', text: d && d.body ? d.body.innerText.length : -1 }; }),
    main: { top: Math.max(0, r.top), left: Math.max(0, r.left), width: r.width },
  };
}"""


def _ink_depth(png, main: dict, scale: float) -> int:
    """How far down the screen (css px) the page's content reaches inside `main`: the lowest pixel row that differs
    from the main's background (its most common colour) by more than a hairline of noise."""
    from PIL import Image  # noqa: PLC0415  only the UI path needs it
    im = Image.open(png).convert("RGB")
    left, top = int(main["left"] * scale), int(main["top"] * scale)
    right = min(im.width, int((main["left"] + main["width"]) * scale))
    crop = im.crop((left, top, max(left + 1, right), im.height)).resize(
        (max(1, (right - left) // 4), max(1, (im.height - top) // 4)))
    bg = max(crop.getcolors(1 << 20) or [(0, (0, 0, 0))])[1]
    px = crop.load()
    w, h = crop.size
    for y in range(h - 1, -1, -1):
        if any(max(abs(a - b) for a, b in zip(px[x, y], bg)) > 6 for x in range(w)):
            return round((y * 4) / scale + main["top"])
    return round(main["top"])


async def _sweep(ctx, pw, edge, routes: list[str]) -> dict:
    """Open every route with its relay reads held; the held page and the settled page, measured and shot."""
    fault = FAULTS.get(ctx.fault or "")
    scale = 2
    browser = await pw.chromium.launch(args=[*LAUNCH_ARGS, *edge.chrome_args])
    shots = ctx.out / "screenshots" / "pages"
    shots.mkdir(parents=True, exist_ok=True)
    cookies = [{"name": c.name, "value": c.value, "url": edge.url, "expires": time.time() + 86400}
               for c in ctx.owner.c.cookies.jar]

    async def fresh():
        """A context of its own per page (no IndexedDB query snapshot, no HTTP cache): every page a first load."""
        bctx = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=scale,
                                         is_mobile=True, has_touch=True, user_agent=IPHONE_UA)
        await bctx.add_cookies(cookies)
        for js in (SWEEP_JS, *((fault.browser_js,) if fault and fault.browser_js and C_SWEEP in fault.targets else ())):
            await bctx.add_init_script(js)
        return bctx
    queue: asyncio.Queue = asyncio.Queue()
    for i, path in enumerate(routes):
        queue.put_nowait((i, path))
    out: dict[str, dict] = {}

    async def tab() -> None:
        gate = {"release": asyncio.Event(), "held": 0}

        async def route(r):
            u = urlsplit(r.request.url)
            if r.request.resource_type in ("fetch", "xhr", "eventsource") and u.netloc == urlsplit(edge.url).netloc \
                    and not any(u.path.startswith(p) for p in SWEEP_PASS) and "_rsc=" not in (u.query or ""):
                gate["held"] += 1
                await gate["release"].wait()
            try:
                await r.continue_()
            except Exception:  # noqa: BLE001  the page moved on
                pass
        while not queue.empty():
            i, path = queue.get_nowait()
            gate["release"].set()
            gate["release"], gate["held"] = asyncio.Event(), 0
            bctx = await fresh()
            page = await bctx.new_page()
            await page.route("**/*", route)
            name = f"{i:02d}" + path.replace("/", "_").replace("?", "_").replace("=", "-")
            d: dict = {"path": path}
            try:
                await page.goto(edge.url + path, wait_until="commit", timeout=60_000)
                # Past the boot skeleton (the principal probes are not held), then a beat for the page's own render.
                await page.wait_for_function("() => document.readyState !== 'loading' && "
                                             "!document.querySelector('[data-boot-skeleton]')", timeout=30_000)
                await asyncio.sleep(1.0)
                d["held"] = await page.evaluate(SWEEP_PROBE)
                d["held"]["reads_held"] = gate["held"]
                await page.screenshot(path=str(shots / f"{name}-held.png"))
                gate["release"].set()
                try:
                    # No placeholder for 1.5 s on end: a page whose reads chain (the Creators, then the Creator's
                    # list) may draw its placeholders only after the first answer.
                    await page.wait_for_function(SWEEP_QUIET, timeout=SWEEP_SETTLE_MS)
                except Exception:  # noqa: BLE001  a placeholder left: the check says so
                    pass
                await asyncio.sleep(1.0)
                d["settled"] = await page.evaluate(SWEEP_PROBE)
                await page.screenshot(path=str(shots / f"{name}-settled.png"))
                d["held"]["depth"] = _ink_depth(shots / f"{name}-held.png", d["held"]["main"], scale)
                d["settled"]["depth"] = _ink_depth(shots / f"{name}-settled.png", d["settled"]["main"], scale)
            except Exception as e:  # noqa: BLE001  recorded; the check names the page
                d["error"] = repr(e)[:200]
            d["shot"] = f"screenshots/pages/{name}-held.png"
            out[path] = d
            gate["release"].set()
            await bctx.close()

    try:
        await asyncio.gather(*(tab() for _ in range(SWEEP_TABS)))
    finally:
        await browser.close()
    # The pages' last OF reads still run in the relay; let them end before the stack stops (else they die mid-call).
    log, quiet, t0 = ctx.stack.logdir / "relay.log", 0.0, time.time()
    size = log.stat().st_size if log.exists() else 0
    while quiet < 6 and time.time() - t0 < 60:
        await asyncio.sleep(1)
        now = log.stat().st_size if log.exists() else 0
        quiet, size = (quiet + 1 if now == size else 0), now
    return out


def _sweep_faults(d: dict) -> list[str]:
    """What is wrong with one page of the sweep: before its first data, a spinner, a "Loading…" line, an empty
    state or a blank area (no placeholder bars, and the held content stops well above where the settled content
    reaches); a spinner or "Loading…" on a button is the button's own state, not the page's. Settled, a
    placeholder, spinner or "Loading…" line left."""
    if "error" in d:
        return [d["error"]]
    h, s, bad = d["held"], d["settled"], []
    if h["spinners"]:
        bad.append(f"held: {h['spinners']} spinner(s)")
    if h["loading_text"]:
        bad.append(f"held: {h['loading_text']}")
    if h["empty"] and h["reads_held"] and d["path"] not in SWEEP_STATIC_EMPTY:
        bad.append(f"held: empty state {h['empty']}")
    top = h["main"]["top"] + 64  # below the page header
    if not h["placeholders"] and s["depth"] > top + 80 and h["depth"] - top < SWEEP_DEPTH * (s["depth"] - top):
        bad.append(f"held: blank below {h['depth']}px (settled content to {s['depth']}px)")
    if s["placeholders"] or s["spinners"] or s["loading_text"]:
        bad.append(f"settled: {s['placeholders']} placeholder(s), {s['spinners']} spinner(s), {s['loading_text']}")
    return bad



async def run(ctx) -> None:  # noqa: C901  one flow, its checks in order
    w = ctx.world
    await agency.seed(w)
    n = ctx.param("creators", CREATORS)
    cs = creators_seed.seed(w, n)
    by_creator = fans.seed(w, cs)
    threads.seed(w, by_creator)
    of_sessions.seed(w, cs[:-1])
    # The last one has no captured session and no account directory (as a session-less Creator on a live deployment:
    # its scoped OF reads answer 404 Unknown account_id, roster-counts logs no captured session).
    shutil.rmtree(w.sessions / "accounts" / cs[-1]["id"])
    earnings.seed(w, cs, ctx.stack.tmp, history_days=ctx.param("history_days", 60), connected_days=9)
    r = await ctx.owner.put("/admin/settings/preferences", json={"tz": REPORT_TZ, "report_tz": REPORT_TZ,
                                                                 "week_start": "monday"})
    fake = ctx.of_wire
    fake.latency_s = ctx.param("of_ms", OF_MS) / 1000
    # OF's chat list for each live Creator: its seeded Fans, newest first, one text message each (Messages Pro's rows).
    for c in cs[:-1]:
        fake.chats[c["id"]] = [
            {"withUser": {"id": f["id"], "_view": "s"}, "unreadMessagesCount": 0,
             "lastMessage": {"id": 7_000_000 + i, "text": "hey", "fromUser": {"id": f["id"]}, "isFree": True,
                             "price": 0, "createdAt": f"2026-10-28T1{i % 10}:00:00+00:00"}}
            for i, f in enumerate(by_creator[c["id"]][:30])]
    slow = cs[0]["id"]
    fake.extra_s[slow] = ctx.param("slow_ms", SLOW_MS) / 1000
    rtt = ctx.param("rtt_ms", RTT_MS)
    ctx.metric("world", {"creators": [c["id"] for c in cs], "with_session": [c["id"] for c in cs[:-1]],
                         "slow_creator": slow, "of_ms": round(fake.latency_s * 1000),
                         "slow_ms": round(fake.extra_s[slow] * 1000), "rtt_ms": rtt, "preferences_put": r.status_code,
                         "nets": NETS})
    if not ctx.ui:
        await _no_ui(ctx)
        return

    edge = await asyncio.to_thread(WanEdge, ctx.stack, rtt)
    visits: dict[str, dict] = {}
    mp_visits: dict[str, dict] = {}
    sweep: dict[str, dict] = {}
    try:
        async with async_playwright() as pw:
            for net in NETS:
                await asyncio.to_thread(ctx.stack.crash_relay)
                await asyncio.to_thread(ctx.stack.start_relay)
                udir = ctx.stack.tmp / f"chrome-{net}"
                for visit in VISITS:
                    d = await _visit(ctx, pw, edge, net, visit, udir, slow)
                    key = f"{net}-{visit}"
                    visits[key] = d
                    (ctx.out / f"waterfall-{key}.json").write_text(json.dumps(d, indent=1))
                    (ctx.out / f"waterfall-{key}.txt").write_text(_table(d))
                    await asyncio.sleep(2)
                # Messages Pro opened on a phone that never loaded the app (its own profile, nothing cached).
                d = await _visit(ctx, pw, edge, net, "mp-first", ctx.stack.tmp / f"chrome-{net}-mp", slow, "/messages-pro")
                mp_visits[f"{net}-mp-first"] = d
                (ctx.out / f"waterfall-{net}-mp-first.json").write_text(json.dumps(d, indent=1))
                (ctx.out / f"waterfall-{net}-mp-first.txt").write_text(_table(d))
                await asyncio.sleep(2)
            # Every other signed-in page, before and after its first data (one Messages Pro chat among them).
            fan = by_creator[cs[0]["id"]][0]["id"]
            # Fansly Manager ships dark; the Agency switches it on (its real route) so the sweep sees its pages, not
            # their "not available" gate.
            r = await ctx.owner.put("/admin/settings/flags", json={"fansly_manager": True})
            assert r.status_code == 200, (r.status_code, r.text[:200])
            # The slow proxy is the Dashboard visits' case; the sweep's pages read the first Creator (that one) four
            # tabs at once, which would queue its OF reads for tens of seconds. Every Creator at `of_ms` here.
            ctx.of_wire.extra_s.clear()
            sweep = await _sweep(ctx, pw, edge, [*SWEEP_ROUTES, f"/messages-pro/{cs[0]['id']}/{fan}"])
    finally:
        edge.close()
    ctx.metric("edge_connections", edge.wan.connections)

    summ = {k: _summary(d) for k, d in (visits | mp_visits).items()}
    for k, d in (visits | mp_visits).items():
        summ[k].update(script_ms_to_total=d["script_ms_to_total"], task_ms_to_total=d["task_ms_to_total"],
                       slow_of_last_end=max((c["end"] for c in d["slow_of_calls"]), default=None))
    ctx.metric("visits", summ)
    cols = ("html_ttfb", "html_end", "js_end", "dcl", "fcp", "frame", "first_fetch_start", "card", "total_painted", "rows",
            "of_last_end", "last_fetch_end", "js_transfer_kb", "longtask_ms_before_total")
    ctx.note("ms from navigation start (Resource Timing; marks via rAF after the DOM change):",
             f"{'visit':22} " + " ".join(f"{c[:12]:>12}" for c in cols),
             *(f"{k:22} " + " ".join(f"{str(s.get(c)):>12}" for c in cols) for k, s in summ.items()),
             "chain per visit (start/end ms): " + "; ".join(
                 f"{k}: me {s['auth_me'] and (s['auth_me']['start'], s['auth_me']['end'])} applied "
                 f"{s['applied'] and (s['applied']['start'], s['applied']['end'])} revenue "
                 f"{s['revenue'] and (s['revenue']['start'], s['revenue']['end'])}" for k, s in summ.items()))

    ctx.check(C_PAINT, all(d["painted"] for d in visits.values()),
              unpainted=[k for k, d in visits.items() if not d["painted"]])

    # Side effect: the figure on screen is the relay's own sum for the window the page asked.
    wrong = {}
    for k, d in visits.items():
        rev = _first(d["res"], "/admin/stats/revenue")
        ref = _first(d["res"], "/admin/stats/referrals")
        if not d["painted"] or rev is None:
            wrong[k] = "no revenue read or no paint"
            continue
        body = (await ctx.owner.get(_path(rev["name"]))).json()
        cents = sum(int(row.get("net_cents") or 0) for row in body.get("rows", []))
        if ref is not None:
            refs = (await ctx.owner.get(_path(ref["name"]))).json()
            cents += sum(int(row.get("total_cents") or 0) for row in refs.get("rows", []))
        if d["total"] != _money(cents):
            wrong[k] = {"screen": d["total"], "relay": _money(cents)}
    ctx.check(C_MATCH, not wrong, wrong=wrong,
              shown={k: d["total"] for k, d in visits.items()})

    origin_reqs = [(k, e) for k, d in (visits | mp_visits).items() for e in d["res"] + [d["nav"]]
                   if urlsplit(e["name"]).hostname == "localhost"]
    not_h2 = [(k, _path(e["name"]), e["proto"]) for k, e in origin_reqs if e["proto"] not in ("h2", "")]
    bad = [(k, _path(e["name"]), e["status"]) for k, e in origin_reqs if (e["status"] or 0) >= 500]
    ctx.check(C_H2, not not_h2 and not bad, requests=len(origin_reqs), not_h2=not_h2[:8], status_5xx=bad[:8])

    judged = {k: (round(d["marks"]["total"]), max(c["end"] for c in d["slow_of_calls"]))
              for k, d in visits.items() if d["slow_of_calls"] and "total" in d["marks"]}
    late = {k: v for k, v in judged.items() if v[0] >= v[1]}
    ctx.check(C_NOWAIT, bool(judged) and not late and all(d["painted"] for d in visits.values()),
              judged={k: {"total": t, "slow_of_end": s} for k, (t, s) in judged.items()}, late=list(late))

    # A saved Total paints from the IndexedDB snapshot before the revenue read answers, and it is the figure the
    # page settles on (no sale lands during the run, so the saved figure is still the relay's).
    saved = {}
    for k, d in visits.items():
        if k.endswith("-first"):
            continue
        rev = _first(d["res"], "/admin/stats/revenue")
        saved[k] = {"total": round(d["marks"]["total"]) if "total" in d["marks"] else None,
                    "revenue_end": None if rev is None else round(rev["end"]),
                    "first_figure": d.get("firstTotal"), "settled": d["total"]}
    early = {k: v for k, v in saved.items() if v["total"] is not None and v["revenue_end"] is not None
             and v["total"] < v["revenue_end"] and v["first_figure"] == v["settled"]}
    ctx.check(C_SAVED, bool(saved) and len(early) == len(saved), visits=saved,
              late=sorted(set(saved) - set(early)))

    # Side effect: which Creators the page's OnlyFans requests named, per visit.
    off, live = cs[-1]["id"], [c["id"] for c in cs[:-1]]
    of_by_visit: dict[str, dict[str, int]] = {k: {} for k in visits}
    for k, d in visits.items():
        for r in d["of_sent"]:
            of_by_visit[k][r["account"] or "-"] = of_by_visit[k].get(r["account"] or "-", 0) + 1
    ctx.metric("of_requests_by_creator", of_by_visit)
    labelled = {k: any(o["label"] == "Not connected" and off in o["card"] for o in d["offline"])
                for k, d in visits.items()}
    ctx.check(C_OFFLINE, all(n.get(off, 0) == 0 for n in of_by_visit.values()) and all(labelled.values())
              and all(all(n.get(a, 0) > 0 for a in live) for n in of_by_visit.values()),
              offline_creator=off, of_requests=of_by_visit, labelled=labelled,
              labels={k: [o["label"] for o in d["offline"]] for k, d in visits.items()})

    # Never blank while the JS loads: the server's HTML draws the page's frame (the boot skeleton), so it is on screen
    # before the app runs at all (its first relay read is /auth/me, from the hydrated app). The return visit is not
    # judged: its JS is cached, so the page itself comes with the frame.
    def framed(k: str, route: str) -> dict:
        s = summ[k]
        return {"frame": s["frame"], "first_relay_read": s["first_fetch_start"], "boot_route": s["boot_route"],
                "skeleton_left": (visits | mp_visits)[k]["bootLeft"], "rows": (visits | mp_visits)[k]["chatRows"],
                "ok": (s["frame"] is not None and s["first_fetch_start"] is not None
                       and s["frame"] < s["first_fetch_start"] and s["boot_route"] == route
                       and (visits | mp_visits)[k]["bootLeft"] == 0)}
    dash = {k: framed(k, "dashboard") for k in visits if not k.endswith("-return")}
    ctx.check(C_FRAME, bool(dash) and all(v["ok"] for v in dash.values()) and all(d["painted"] for d in visits.values()),
              visits=dash, late=[k for k, v in dash.items() if not v["ok"]])
    mp = {k: framed(k, "messages-pro") for k in mp_visits}
    ctx.check(C_FRAME_MP, bool(mp) and all(v["ok"] and v["rows"] > 0 for v in mp.values())
              and all(d["painted"] for d in mp_visits.values()),
              visits=mp, late=[k for k, v in mp.items() if not (v["ok"] and v["rows"] > 0)])
    (ctx.out / "page-sweep.json").write_text(json.dumps(sweep, indent=1))
    wrong = {p: f for p, d in sweep.items() if (f := _sweep_faults(d))}
    ctx.note("page sweep (held = relay reads held; depth = css px the content reaches; placeholders = visible bars):",
             *(f"{p:42} held: bars {d['held']['placeholders']:>3} depth {d['held']['depth']:>4} reads {d['held']['reads_held']:>3}"
               f" | settled: depth {d['settled']['depth']:>4}  {'; '.join(wrong.get(p, [])) or 'ok'}"
               if "held" in d and "settled" in d else f"{p:42} {d.get('error')}" for p, d in sweep.items()))
    ctx.check(C_SWEEP, len(sweep) == len(SWEEP_ROUTES) + 1 and not wrong, pages=len(sweep), wrong=wrong)

    for net in NETS:
        t = visits[f"{net}-return"]["marks"].get("total")
        ctx.check(C_BUDGET(net), t is not None and t <= BUDGET_MS[net], budget=True,
                  total_ms=None if t is None else round(t), budget_ms=BUDGET_MS[net])
