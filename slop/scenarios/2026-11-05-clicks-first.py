from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
import statistics
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from slop.actors.ui import LAUNCH_ARGS, _client_fault, _patched
from slop.lib.clicks_first_faults import C_ABORT, C_BUNDLE, C_CAP, C_ENTRY, C_PARTIAL, C_SNAPSHOT
from slop.lib.faults import FAULTS
from slop.lib.screen_bundle import DASH_SCREEN_PATH, bundle_view, late_reads
from slop.lib.wan import WanEdge
from slop.seed import agency, earnings, fans, of_sessions, threads
from slop.seed import creators as creators_seed

BUNDLE_OF = frozenset(("/api/of/v2/users/me", "/api/of/v2/subscriptions/count/all",
                       "/api/of/v2/subscriptions/subscribers/chart", "/api/of/v2/chats",
                       "/api/of/v2/users/notifications/count"))

UI = True
APP_MODE = "prod"
RELAY_ENV = {"VAPID_SUBJECT": "mailto:slop@example.test"}
OF_WIRE = True
FAULT = "relay-scheduler-bypassed"
PER_CREATOR = 2
CREATORS = 13
RTT_MS = 250
OF_MS = 500
NET = (12_000, 4_000, 2)
CLICKS = 3
LEAVE_OF_MS = 2_000
REPORTS_PATH = "/analytics/creator-reports"
LEAVE_TO = "/share-for-share/settings"
STALE_S = 32
SLOW_ROUTES = ("GET /api2/v2/users/me", "GET /api2/v2/subscriptions/count/all",
               "GET /api2/v2/subscriptions/subscribers/chart")
ZONE = "Europe/Ljubljana"
INLINE_READS = ("/auth/me", "/chatter/me", "/admin/settings/applied", "/admin/screens/")
SLOW_SHIFT_S = 31 * 60
SLOW_EXTRA_S = 3.0
# before the change this scenario measured 777 ms (one OF call + one round trip); budget = that + 30% for CPU noise
CLICK_BUDGET_MS = 1_000
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")

C_CLICK = "median tap -> OnlyFans' newest message of that Fan painted within CLICK_BUDGET_MS while the other Creators load"
C_LOADING = "each tap landed while at least creators - 1 Creators' chat lists were still loading"
C_THREAD = ("each tap opened that Fan's Thread: a saved message of that Fan (DB row) painted, then the message OnlyFans "
            "answered for that Fan")
C_PAINT = ("every visit but reports-leave painted (Dashboard: Total earnings; Creator reports extras: every card's fan count; Messages Pro: Fan rows) and no page "
           "request 5xx")

PROBE_JS = r"""(() => {
  try { performance.setResourceTimingBufferSize(5000); } catch (e) {}
  // Safari has no NetworkInformation: the app judges the link by its own round trips (declared bypass).
  try { Object.defineProperty(Navigator.prototype, 'connection', { get: () => undefined, configurable: true }); } catch (e) {}
  const S = window.__cf = { marks: {}, path: location.pathname };
  const mark = (k) => { if (!(k in S.marks)) S.marks[k] = performance.now(); };
  document.addEventListener('click', (e) => {
    if (e.target && e.target.closest && e.target.closest('[data-chat-row]')) S.marks.click = performance.now();
    if (e.target?.closest('[aria-controls="creator-reports-extras"]')) S.marks.extras = performance.now();
  }, true);
  let q = false;
  const check = () => {
    q = false;
    if (document.querySelector('[data-chat-row]')) mark('rows');
    if (/\$[\d,]+/.test(document.querySelector('[data-control="total"] [data-figure]')?.textContent || '')) mark('total');
    // legs' marks
    if (location.pathname !== S.path) mark('left');
    const fans = [...document.querySelectorAll('dt')].filter((d) => d.textContent.trim() === 'Fans')
      .map((d) => ((d.nextElementSibling || {}).textContent || '').trim());
    if (fans.length && fans.every((t) => /^[\d,]+$/.test(t)) && !S.fans) { S.fans = fans; requestAnimationFrame(() => mark('fans')); }
    // a card that showed its count and then lost it (a spinner, a dash, the card gone)
    if (S.fans && location.pathname === S.path && (fans.length < S.fans.length || !fans.every((t) => /^[\d,]+$/.test(t)))) mark('blank');
    const b = document.querySelector('[data-msg-id]');
    if ('click' in S.marks && b && !S.bubble) { S.bubble = b.getAttribute('data-msg-id'); requestAnimationFrame(() => mark('bubble')); }
    // OnlyFans' own message (lib/of_wire.py: id 8000000 + Fan id % 1e6; saved rows have other ids)
    const o = 'click' in S.marks && !S.ofmsg && [...document.querySelectorAll('[data-msg-id]')]
      .find((e) => /^8\d{6}$/.test(e.getAttribute('data-msg-id')));
    if (o) { S.ofmsg = o.getAttribute('data-msg-id'); requestAnimationFrame(() => mark('ofmsg')); }
  };
  new MutationObserver(() => { if (!q) { q = true; queueMicrotask(check); } })
    .observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
})();"""

LEGS = [importlib.import_module(f"slop.lib.{m.stem}")
        for m in sorted((Path(__file__).resolve().parents[1] / "lib").glob("clicks_first_*_leg.py"))]
PROBE_JS = PROBE_JS.replace("    // legs' marks\n", "".join(leg.PROBE_MARKS for leg in LEGS))
UNCAPPED = tuple(p for leg in LEGS for p in leg.UNCAPPED)

SHOW_CARDS_JS = """() => { const d = [...document.querySelectorAll('dt')].find((x) => x.textContent.trim() === 'Fans');
  if (d) d.scrollIntoView({ block: 'center' }); }"""

COLLECT_JS = r"""() => ({
  origin: performance.timeOrigin,
  marks: window.__cf.marks, fans: window.__cf.fans || null, bubble: window.__cf.bubble || null,
  ofmsg: window.__cf.ofmsg || null,
  msgIds: [...document.querySelectorAll('[data-msg-id]')].map((e) => e.getAttribute('data-msg-id')),
  settledFans: [...document.querySelectorAll('dt')].filter((d) => d.textContent.trim() === 'Fans')
    .map((d) => ((d.nextElementSibling || {}).textContent || '').trim()),
  rows: document.querySelectorAll('[data-chat-row]').length,
  res: performance.getEntriesByType('resource').filter((e) => e.initiatorType === 'fetch' || e.initiatorType === 'xmlhttprequest')
    .map((e) => ({ name: e.name, start: e.startTime, end: e.responseEnd, status: e.responseStatus })),
})"""


def _path(url: str) -> str:
    u = urlsplit(url)
    return u.path + (f"?{u.query}" if u.query else "")


class Net:

    def __init__(self, host: str):
        self.host, self.reqs = host, {}

    def attach(self, cdp) -> None:
        def sent(e):
            r = e["request"]
            if urlsplit(r["url"]).netloc != self.host:
                return
            h = {k.lower(): v for k, v in r.get("headers", {}).items()}
            self.reqs[e["requestId"]] = {
                "path": _path(r["url"]), "method": r["method"], "bg": h.get("x-priority") == "background",
                "account": h.get("x-account-id"), "prio": r.get("initialPriority"),
                "t0": e["wallTime"] * 1000, "mono0": e["timestamp"], "end": None, "status": None}
        def got(e):
            if (r := self.reqs.get(e["requestId"])) is not None:
                r["status"] = e["response"]["status"]
        def done(e):
            if (r := self.reqs.get(e["requestId"])) is not None:
                r["end"] = r["t0"] + (e["timestamp"] - r["mono0"]) * 1000
                r["mono1"] = e["timestamp"]
        cdp.on("Network.requestWillBeSent", sent)
        cdp.on("Network.responseReceived", got)
        cdp.on("Network.loadingFinished", done)
        cdp.on("Network.loadingFailed", done)

    def of(self, bg: bool | None = None) -> list[dict]:
        return [r for r in self.reqs.values() if r["path"].startswith("/api/of/") and (bg is None or r["bg"] == bg)]


def _end(r: dict) -> float:
    if r.get("mono1") is None:
        return float("inf")
    return r["mono1"] * 1000 - (20 if r["status"] is None else 0)


def _max_inflight(reqs: list[dict]) -> int:
    ev = sorted([(r["mono0"] * 1000, 1) for r in reqs] + [(_end(r), -1) for r in reqs],
                key=lambda x: (x[0], x[1]))
    n = best = 0
    for _, d in ev:
        n += d
        best = max(best, n)
    return best


async def _quiet(page, quiet_s: float = 3.0, cap_s: float = 90.0) -> None:
    last, still, t0 = -1, 0.0, time.time()
    while time.time() - t0 < cap_s:
        n = await page.evaluate("() => performance.getEntriesByType('resource').length")
        still = still + 0.25 if n == last else 0.0
        if still >= quiet_s:
            return
        last = n
        await asyncio.sleep(0.25)


async def _visit(ctx, pw, edge, udir, name: str, path: str, *, first: bool, act=None, early: bool = False,
                 no_bundle: bool = False, shift_s: float = 0.0, done: str | None = None,
                 hold_counts: bool = False) -> dict:
    down, up, cpu = NET
    fault = FAULTS.get(ctx.fault or "")
    bctx = await pw.chromium.launch_persistent_context(
        str(udir), args=[*LAUNCH_ARGS, *edge.chrome_args], viewport={"width": 390, "height": 844},
        device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=IPHONE_UA, timezone_id=ZONE)
    net = Net(urlsplit(edge.url).netloc)
    held_counts = []
    counts_started = asyncio.Event()
    try:
        if first:
            await bctx.add_cookies([{"name": c.name, "value": c.value, "url": edge.url,
                                     "expires": time.time() + 30 * 86400} for c in ctx.owner.c.cookies.jar])
        for js in (PROBE_JS, *((fault.browser_js,) if fault and fault.browser_js else ())):
            await bctx.add_init_script(js)
        if patches := _client_fault(ctx):
            await bctx.route("**/_next/static/**/*.js", lambda r: _patched(r, ctx, patches, origin=ctx.app))
        if no_bundle:
            await ctx.owner.post("/__slop/screens-404", json={"on": True})
        if hold_counts:
            async def hold_count(r):
                held_counts.append(r)
                if len(held_counts) >= ctx.param("creators", CREATORS):
                    counts_started.set()
            await bctx.route("**/api/of/v2/subscriptions/count/all**", hold_count)
        if shift_s:
            await bctx.add_init_script("""(() => {
              const NativeDate = Date, shift = %d;
              window.Date = new Proxy(NativeDate, {
                apply: () => new NativeDate(NativeDate.now() + shift).toString(),
                construct: (target, args) => Reflect.construct(target, args.length ? args : [target.now() + shift]),
                get: (target, key) => key === 'now' ? () => target.now() + shift : Reflect.get(target, key)
              });
            })();""" % (shift_s * 1000))
        page = bctx.pages[0] if bctx.pages else await bctx.new_page()
        cdp = await bctx.new_cdp_session(page)
        net.attach(cdp)
        await cdp.send("Network.enable")
        await cdp.send("Network.emulateNetworkConditions", {
            "offline": False, "latency": 0, "downloadThroughput": down * 1000 / 8,
            "uploadThroughput": up * 1000 / 8, "connectionType": "cellular4g"})
        await cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu})
        t_nav = time.time()
        await page.goto(edge.url + path, wait_until="commit", timeout=120_000)
        if path == REPORTS_PATH:
            await page.locator('[aria-controls="creator-reports-extras"]').click(timeout=60_000)
        done = done or ("total" if path == "/" else "fans" if path == REPORTS_PATH else "rows")
        painted, extra = True, {}
        if early:
            extra = await act(page, net)
        else:
            try:
                await page.wait_for_function(f"() => window.__cf && '{done}' in window.__cf.marks", timeout=5_000 if hold_counts else 60_000)
            except Exception:  # noqa: BLE001  never painted: recorded, C_PAINT says so
                painted = False
        if hold_counts:
            try:
                await asyncio.wait_for(counts_started.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            extra["snapshot_before_release"] = await page.evaluate(COLLECT_JS)
            await page.evaluate(SHOW_CARDS_JS)
            await page.screenshot(path=str(ctx.out / "screenshots" / f"{name}-held.png"))
            for r in held_counts:
                await r.continue_()
            await bctx.unroute("**/api/of/v2/subscriptions/count/all**", hold_count)
            if not painted:
                try:
                    await page.wait_for_function(f"() => window.__cf && '{done}' in window.__cf.marks", timeout=60_000)
                    painted = True
                except Exception:  # noqa: BLE001  recorded by C_PAINT
                    pass
        if path == REPORTS_PATH and not early:
            await page.evaluate(SHOW_CARDS_JS)
        await page.screenshot(path=str(ctx.out / "screenshots" / f"{name}-trigger.png"))
        if act and painted and not early:
            extra = await act(page, net)
        await _quiet(page)
        d = await page.evaluate(COLLECT_JS)
        if path == REPORTS_PATH and urlsplit(page.url).path == REPORTS_PATH:
            await page.evaluate(SHOW_CARDS_JS)
        await page.screenshot(path=str(ctx.out / "screenshots" / f"{name}.png"))
        await page.evaluate("() => window.dispatchEvent(new Event('pagehide'))")
        await asyncio.sleep(1.0)
        if path == REPORTS_PATH:
            d["saved_queries"] = await page.evaluate("""() => new Promise(resolve => {
              const r = indexedDB.open('chatterly-rq');
              r.onerror = () => resolve({error:'open'});
              r.onsuccess = () => {
                const db = r.result;
                if (!db.objectStoreNames.contains('snapshot')) { db.close(); resolve({error:'store'}); return; }
                const q = db.transaction('snapshot').objectStore('snapshot').get('cache');
                q.onsuccess = () => { const c = q.result ? JSON.parse(q.result) : null;
                  resolve({timestamp:c?.timestamp, keys:c?.clientState?.queries?.map(q => q.queryKey)}); db.close(); };
                q.onerror = () => { db.close(); resolve({error:'get'}); };
              };
            })""")
    finally:
        await bctx.close()
        if no_bundle:
            await ctx.owner.post("/__slop/screens-404", json={"on": False})
    reads = (await ctx.owner.get("/__slop/server-reads")).json()["reads"]
    inline = [x for x in reads if x["t0"] >= t_nav - 0.05 and x["path"].startswith(INLINE_READS)]
    if hold_counts:
        d["snapshot_held_counts"] = len(held_counts)
    d.update(painted=painted, done=done, net=list(net.reqs.values()), inline=inline, **(extra or {}))
    return d


def _bundles(d: dict) -> tuple[list[str], list[str]]:
    sb = [r["path"] for r in d["net"] if r["path"].startswith("/admin/screens/")]
    plain = [p for p in sb if "accounts=" not in p and "cursor=" not in p.replace("cursor=0", "")]
    if not plain:
        plain = [x["path"] for x in d.get("inline", ()) if x["path"].startswith("/admin/screens/") and x["status"] < 500]
    return plain, [p for p in sb if "accounts=" in p]


def _took_inline(d: dict, pre: str) -> bool:
    return (not any(r["path"].startswith(pre) for r in d["net"])
            and any(x["path"].startswith(pre) and x["status"] < 500 for x in d.get("inline", ())))


def _summary(d: dict) -> dict:
    res = [e for e in d["res"] if "/perflog/" not in e["name"]]
    of = [e for e in res if "/api/of/" in e["name"]]
    net_of = [r for r in d["net"] if r["path"].startswith("/api/of/")]
    paint = d["marks"].get("fans", d["marks"].get("rows", d["marks"].get(d["done"])))
    plain, follow = _bundles(d)
    extras = d["marks"].get("extras")
    bundle_start = min((r["t0"] for r in d["net"] if r["path"].startswith(DASH_SCREEN_PATH)), default=None)
    return {"bundles": len(plain), "follow_ups": len(follow),
            "relay_before_paint": None if paint is None else sum(1 for e in res if e["start"] < paint),
            "of_before_paint": None if paint is None else sum(1 for e in of if e["start"] < paint),"settled_ms": round(max((e["end"] for e in res), default=0)),
            "of_settled_ms": round(max((e["end"] for e in of), default=0)),
            "relay_requests": len(res), "of_requests": len(of),
            "of_background": sum(1 for r in net_of if r["bg"]), "of_user": sum(1 for r in net_of if not r["bg"]),
            "max_bg_inflight": _max_inflight([r for r in net_of if r["bg"]]),
            "painted_ms": round(paint if paint is not None else -1),
            "cards_from_extras_ms": round(paint - extras) if paint is not None and extras is not None else None,
            "bundle_from_extras_ms": (round(bundle_start - d["origin"] - extras)
                                      if bundle_start is not None and extras is not None else None)}


async def _restart(ctx) -> None:
    await asyncio.to_thread(ctx.stack.crash_relay)
    await asyncio.to_thread(ctx.stack.start_relay)


def _message_open(path: str) -> tuple[str, str] | None:
    parts = path.split("?")[0].split("/")
    return (parts[3], parts[4]) if len(parts) == 5 and parts[:3] == ["", "admin", "messages"] else None


async def run(ctx) -> None:  # noqa: C901  one flow, its checks in order
    w = ctx.world
    await agency.seed(w)
    n = ctx.param("creators", CREATORS)
    cs = creators_seed.seed(w, n)
    by_creator = fans.seed(w, cs)
    threads.seed(w, by_creator)
    of_sessions.seed(w, cs)
    earnings.seed(w, cs, ctx.stack.tmp, history_days=30, connected_days=9)
    fake = ctx.of_wire
    fake.latency_s = ctx.param("of_ms", OF_MS) / 1000
    for leg in LEGS:
        leg.setup(fake)
    for c in cs:
        fake.chats[c["id"]] = [
            {"withUser": {"id": f["id"], "_view": "s"}, "unreadMessagesCount": 0,
             "lastMessage": {"id": 7_000_000 + i, "text": "hey", "fromUser": {"id": f["id"]}, "isFree": True,
                             "price": 0, "createdAt": f"2026-11-05T{10 + i % 10}:00:00+00:00"}}
            for i, f in enumerate(by_creator[c["id"]][:30])]
    rtt = ctx.param("rtt_ms", RTT_MS)
    clicks = ctx.param("clicks", CLICKS)
    ctx.metric("world", {"creators": len(cs), "of_ms": round(fake.latency_s * 1000), "rtt_ms": rtt, "net": NET,
                         "clicks": clicks})
    checks = (C_CAP, C_SNAPSHOT, C_CLICK, C_LOADING, C_THREAD, C_ABORT, C_PAINT, C_BUNDLE, C_PARTIAL, C_ENTRY,
              *(c for leg in LEGS for c in leg.CHECKS))
    if not ctx.ui:
        for c in checks:
            ctx.skip(c, "--no-ui: no browser (the change is the app's alone)")
        return

    slow = cs[0]["id"]
    edge = await asyncio.to_thread(WanEdge, ctx.stack, rtt)
    v: dict[str, dict] = {}
    udir = ctx.stack.tmp / "chrome-phone"
    reports_udir = ctx.stack.tmp / "chrome-reports-phone"

    async def leave(page, net) -> dict:
        await page.get_by_role("button", name="Toggle sidebar").tap(timeout=60_000)
        menu = page.get_by_role("dialog", name="Menu")
        await menu.wait_for(state="visible", timeout=15_000)
        await menu.get_by_text("Share for Share", exact=True).first.tap()
        link = menu.locator(f'a[href="{LEAVE_TO}"]').first
        await link.wait_for(state="visible", timeout=15_000)
        t0 = time.time()
        while time.time() - t0 < 30 and not any("/subscriptions/" in r["path"] for r in net.of()):
            await asyncio.sleep(0.05)
        t_nav = time.time() * 1000
        await link.tap()
        await page.wait_for_url(f"**{LEAVE_TO}", timeout=30_000)
        await asyncio.sleep(8)
        return {"t_nav": t_nav}

    def tap(i: int):
        async def act(page, net) -> dict:
            rows = page.locator("[data-chat-row]")
            await rows.nth(i % max(1, await rows.count())).click()
            await page.screenshot(path=str(ctx.out / "screenshots" / f"mp-click-{i}-tapped.png"))
            try:
                await page.wait_for_function("() => 'ofmsg' in window.__cf.marks", timeout=60_000)
            except Exception:  # noqa: BLE001  no Thread: C_CLICK / C_THREAD say so
                pass
            return {}
        return act

    try:
        async with async_playwright() as pw:
            await _restart(ctx)
            v["dash-first"] = await _visit(ctx, pw, edge, udir, "dash-first", "/", first=True)
            v["dash-reload"] = await _visit(ctx, pw, edge, udir, "dash-reload", "/", first=False)
            v["reports-first"] = await _visit(ctx, pw, edge, reports_udir, "reports-first", REPORTS_PATH, first=True)
            v["reports-snapshot"] = await _visit(ctx, pw, edge, reports_udir, "reports-snapshot", REPORTS_PATH, first=False,
                                               hold_counts=True, no_bundle=True, shift_s=SLOW_SHIFT_S)
            await _restart(ctx)
            n_slow = len(fake.calls)
            fake.extra_s[slow] = SLOW_EXTRA_S
            v["reports-slow"] = await _visit(ctx, pw, edge, reports_udir, "reports-slow", REPORTS_PATH, first=False, shift_s=2 * SLOW_SHIFT_S)
            t_end = time.time() + 30
            while time.time() < t_end and len({c["route"] for c in fake.calls[n_slow:] if c["account"] == slow
                                               and c["route"] in SLOW_ROUTES and c["status"] == 200}) < 3:
                await asyncio.sleep(0.25)
            fake.extra_s.pop(slow, None)
            n_after = len(fake.calls)
            plain = _bundles(v["reports-slow"])[0]
            r = await ctx.owner.get(plain[0] if plain else DASH_SCREEN_PATH)
            after_body = bundle_view(r.json()) if r.status_code == 200 else None
            slow_after = {"status": r.status_code,
                          "counts": (after_body or {}).get("subscriberCounts", {}).get(slow),
                          "late": sorted(r for a, r in late_reads(after_body) if a == slow),
                          "duplicates": (after_body or {}).get("duplicates", []),
                          "of_calls": sum(1 for c in fake.calls[n_after:] if c["account"] == slow
                                          and c["route"].startswith("GET /api2/")),
                          "of_calls_during_visit": sum(1 for c in fake.calls[n_slow:n_after] if c["account"] == slow)}
            await _restart(ctx)
            fake.latency_s = LEAVE_OF_MS / 1000
            v["reports-leave"] = await _visit(ctx, pw, edge, ctx.stack.tmp / "chrome-leave", "reports-leave", REPORTS_PATH,
                                           first=True, act=leave, early=True, no_bundle=True)
            fake.latency_s = ctx.param("of_ms", OF_MS) / 1000
            await _restart(ctx)
            v["mp-first"] = await _visit(ctx, pw, edge, udir, "mp-first", "/messages-pro", first=False)
            for i in range(clicks):
                t_last = time.time()
                await _restart(ctx)
                await asyncio.sleep(max(0.0, STALE_S - (time.time() - t_last)))
                v[f"mp-click-{i}"] = await _visit(ctx, pw, edge, udir, f"mp-click-{i}", "/messages-pro",
                                                  first=False, act=tap(i), no_bundle=True)
            for leg in LEGS:
                await leg.visit(ctx, pw, edge, udir, v, cs=cs, n=n, fake=fake, visit_fn=_visit)
    finally:
        edge.close()
    for k, d in v.items():
        (ctx.out / f"visit-{k}.json").write_text(json.dumps(d, indent=1))

    summ = {k: _summary(d) for k, d in v.items()}
    ctx.metric("visits", summ)
    cols = ("painted_ms", "cards_from_extras_ms", "bundle_from_extras_ms", "settled_ms", "of_settled_ms", "relay_requests", "of_requests", "of_background", "of_user",
            "max_bg_inflight", "bundles", "follow_ups", "relay_before_paint", "of_before_paint")
    ctx.note(f"per visit at {rtt} ms RTT (ms from navigation start except *_from_extras_ms; counts = fetches the page sent):",
             f"{'visit':14} " + " ".join(f"{c[:15]:>15}" for c in cols),
             *(f"{k:14} " + " ".join(f"{str(s[c]):>15}" for c in cols) for k, s in summ.items()))

    bad5 = [(k, r["path"], r["status"]) for k, d in v.items() for r in d["net"] if (r["status"] or 0) >= 500]
    def of_base(d: dict) -> Counter:
        return Counter(r["path"].split("?")[0] for r in d["net"] if r["path"].startswith("/api/of/"))
    per = {k: {"of_paths": Counter({p: n for p, n in of_base(v[k]).items() if p in BUNDLE_OF}),
               "own_routes": Counter({p: n for p, n in of_base(v[k]).items() if p not in BUNDLE_OF}),
               "bundles": summ[k]["bundles"], "follow_ups": summ[k]["follow_ups"]} for k in ("dash-first", "reports-first", "mp-first")}
    cards = v["reports-first"]
    activation = cards["marks"].get("extras")
    card_bundles = [r for r in cards["net"] if r["path"].startswith(DASH_SCREEN_PATH)]
    per["reports-first"]["activation_ms"] = activation
    per["reports-first"]["bundle_from_extras_ms"] = summ["reports-first"]["bundle_from_extras_ms"]
    per["reports-first"]["bundle_after_activation"] = (activation is not None and bool(card_bundles)
        and all(r["t0"] >= cards["origin"] + activation for r in card_bundles))
    ctx.check(C_BUNDLE, per["reports-first"]["bundle_after_activation"] and all(
                  not x["of_paths"] and x["bundles"] == 1 and x["follow_ups"] <= 1 for x in per.values()),
              **{k: {**x, "of_paths": dict(x["of_paths"]), "own_routes": dict(x["own_routes"])}
                 for k, x in per.items()})
    def entry(d: dict, dash: bool) -> dict:
        first = lambda pre: min((r["t0"] for r in d["net"] if r["path"].startswith(pre)), default=None)  # noqa: E731
        me = [r["end"] for r in d["net"] if r["path"].split("?")[0] == "/auth/me" and r["end"] is not None]
        plain, _follow = _bundles(d)
        page_bundles = [r for r in d["net"] if r["path"] in plain]
        settings = "/admin/settings/applied"
        o = {"auth_me_end": round(min(me) - d["origin"]) if me else None, "auth_me_inline": _took_inline(d, "/auth/me"),
             "bundle_t0": min((r["t0"] for r in page_bundles), default=None),
             "bundle_inline": bool(plain) and not page_bundles,
             "settings_t0": first(settings), "settings_inline": _took_inline(d, settings)}
        want = ("settings",) if dash else ("bundle",)
        cards = [r for r in d["net"] if r["path"] in plain and r["path"].startswith(DASH_SCREEN_PATH)]
        set_end = [r["end"] for r in d["net"] if r["path"].split("?")[0] == settings and r["end"] is not None]
        o["card_bundle_own"] = (len(plain) == 1 and len(cards) == 1
                                and not any(x["path"].startswith(DASH_SCREEN_PATH) for x in d.get("inline", []))
                                and (o["settings_inline"] or (bool(set_end) and cards[0]["t0"] >= min(set_end))))
        o["ok"] = (not dash or o["card_bundle_own"]) and (bool(me) or o["auth_me_inline"]) and all(
            o[f"{k}_inline"] or (bool(me) and o[f"{k}_t0"] is not None and o[f"{k}_t0"] < min(me)) for k in want)
        for k in ("bundle", "settings"):
            o[f"{k}_t0"] = None if o[f"{k}_t0"] is None else round(o[f"{k}_t0"] - d["origin"])
        return o
    ent = {k: entry(v[k], k.startswith("dash")) for k in ("dash-first", "dash-reload", "mp-first")}
    ctx.check(C_ENTRY, all(e["ok"] for e in ent.values()), **ent)
    d = v["reports-slow"]
    plain, follow = _bundles(d)
    of_reads = [r["path"] for r in d["net"] if r["path"].split("?")[0] in BUNDLE_OF]
    ctx.check(C_PARTIAL, d["painted"] and "blank" not in d["marks"] and len(plain) == 1 and len(follow) <= 1
              and not of_reads and slow_after["status"] == 200 and not slow_after["late"] and not slow_after["duplicates"]
              and slow_after["counts"] is not None and slow_after["of_calls"] == 0,
              painted_ms=round(d["marks"].get("fans", -1)), blank_ms=d["marks"].get("blank"), bundles=plain,
              follow_ups=follow, of_reads=of_reads[:6], slow_creator=slow, after=slow_after)

    ctx.check(C_PAINT, all(d["painted"] for k, d in v.items() if k != "reports-leave") and not bad5,
              unpainted=[k for k, d in v.items() if not d["painted"] and k != "reports-leave"], status_5xx=bad5[:8])

    def tapped(d: dict) -> str | None:
        r = [x for x in d["net"] if _message_open(x["path"]) is not None]
        return _message_open(r[0]["path"])[0] if r else None
    inflight = {}
    for k, d in v.items():
        bg = [r for r in d["net"] if r["path"].startswith("/api/of/") and r["bg"] and r["account"] != tapped(d)
              and not r["path"].startswith(UNCAPPED)]
        inflight[k] = max((_max_inflight([r for r in bg if r["account"] == a]) for a in {r["account"] for r in bg}),
                          default=0)
    ctx.check(C_CAP, max(inflight.values(), default=0) <= PER_CREATOR and any(inflight.values()),
              max_per_creator=inflight, per_creator=PER_CREATOR)

    d = v["reports-snapshot"]
    reads = [r["end"] - d["origin"] for r in d["net"] if r["end"] is not None
             and "/subscriptions/count/all" in r["path"]]
    painted = d["marks"].get("fans")
    want = sorted(f"{int(c['id']) % 900 + 100:,}" for c in cs)
    ctx.check(C_SNAPSHOT, painted is not None and d["snapshot_held_counts"] == n
              and sorted(d["snapshot_before_release"]["settledFans"]) == want
              and (not reads or painted < min(reads))
              and sorted(d["fans"] or []) == want and sorted(d["settledFans"]) == want,
              painted_ms=painted and round(painted), first_count_read_end=reads and round(min(reads)),
              held_counts=d["snapshot_held_counts"], before_release=d["snapshot_before_release"]["settledFans"],
              shown=d["fans"], settled=d["settledFans"], want=want)

    d = v["reports-leave"]
    dash_reads = [r for r in d["net"] if "/subscriptions/count/all" in r["path"] or "/subscribers/chart" in r["path"]]
    left = d["origin"] + d["marks"]["left"] if "left" in d["marks"] else None
    after = [r["path"] for r in dash_reads if left is not None and r["t0"] > left]
    before = sum(1 for r in dash_reads if left is not None and r["t0"] <= left)
    ctx.check(C_ABORT, left is not None and 0 < before < 2 * n and not after, tap_to_switch_ms=left and round(left - d["t_nav"]),
              sent_before_switch=before, of_total=2 * n, sent_after_switch=after[:8])

    taps, loading, thread = {}, {}, {}
    for i in range(clicks):
        d = v[f"mp-click-{i}"]
        m, t_click = d["marks"], d["marks"].get("click")
        tap_ms = (m["ofmsg"] - t_click) if (t_click is not None and "ofmsg" in m) else None
        taps[i] = None if tap_ms is None else round(tap_ms)
        click_wall = None if t_click is None else d["origin"] + t_click
        lists = [r for r in d["net"] if r["path"].startswith("/api/of/v2/chats?")]
        open_ = {r["account"] for r in lists if click_wall is not None and (r["end"] is None or r["end"] > click_wall)}
        loading[i] = len(open_)
        opened = [r for r in d["net"] if _message_open(r["path"]) is not None
                  and click_wall is not None and r["t0"] >= click_wall - 50]
        acc, fan = _message_open(opened[0]["path"]) if opened else (None, None)
        head = [r for r in d["net"] if fan and r["path"].startswith(f"/api/of/v2/chats/{fan}/messages?")]
        rows = []
        if acc and d.get("msgIds"):
            with sqlite3.connect(f"file:{ctx.stack.db}?mode=ro", uri=True) as db:
                q = ",".join("?" * len(d["msgIds"]))
                rows = sorted({(str(a), str(f)) for a, f in db.execute(
                    f"SELECT account_id, fan_id FROM messages WHERE account_id = ? AND message_id IN ({q})",
                    [acc, *d["msgIds"]])})
        thread[i] = {"account": acc, "fan": fan, "saved_owners": rows, "painted": len(d.get("msgIds") or []),
                     "of_msg": d["ofmsg"], "want": fan and str(8_000_000 + int(fan) % 1_000_000),
                     "tap_to_saved_ms": None if (t_click is None or "bubble" not in m) else round(m["bubble"] - t_click),
                     "of_read": head and {k: head[-1][k] for k in ("bg", "prio", "status")},
                     "of_read_wait_ms": head and click_wall and round(head[-1]["t0"] - click_wall)}
    ok_taps = [t for t in taps.values() if t is not None]
    med = statistics.median(ok_taps) if ok_taps else None
    ctx.metric("taps_ms", {"each": taps, "median": med, "loading_at_tap": loading, "threads": thread})
    ctx.check(C_LOADING, len(loading) == clicks and all(n_ >= n - 1 for n_ in loading.values()),
              loading_at_tap=loading, need=n - 1)
    ctx.check(C_THREAD, all(t["fan"] and t["saved_owners"] == [(t["account"], t["fan"])] and t["of_msg"] == t["want"]
                            for t in thread.values()), threads=thread)
    ctx.check(C_CLICK, med is not None and len(ok_taps) == clicks and med <= CLICK_BUDGET_MS, budget=True,
              median_ms=med, taps_ms=taps, budget_ms=CLICK_BUDGET_MS)

    for leg in LEGS:
        leg.check(ctx, v, cs=cs, n=n, click_budget_ms=CLICK_BUDGET_MS, max_inflight=_max_inflight)
