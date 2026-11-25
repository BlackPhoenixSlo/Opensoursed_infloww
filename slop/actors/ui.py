from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from slop.lib.faults import FAULTS
from slop.lib.net import emulate
from slop.lib.screen_bundle import CHAT_SCREEN_PATH, NO_BUNDLES_COOKIE

INIT_JS = """try { localStorage.setItem('chatterly:theme', 'light'); } catch (e) {}
document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style');
  s.textContent = 'nextjs-portal, [data-nextjs-toast], [data-next-badge-root] { display: none !important; }';
  document.documentElement.appendChild(s); });"""
OF_LIVE_PATHS = ("/admin/vault/wall-media",)
SCREEN_BUNDLES = "/admin/screens/"
SEND_PATH = re.compile(r"/api/of/v2/chats/\d+/messages")
# --enable-precise-memory-info: without it performance.memory is bucketed and never moves.
LAUNCH_ARGS = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost",
               "--enable-precise-memory-info"]


PROBE_JS = r"""(() => {
  const P = window.__slop = { rx: {}, handler: [], longTasks: [], resync: 0, streams: 0, marks: {} };
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries())
      P.longTasks.push([performance.timeOrigin + e.startTime, e.duration]); })
      .observe({ type: "longtask", buffered: true });
  } catch (e) {}
  const ids = (o, out) => {
    if (Array.isArray(o)) { for (const v of o) ids(v, out); }
    else if (o && typeof o === "object") {
      const m = o.api2_chat_message;
      if (m && typeof m === "object" && m.id != null) out.push(String(m.id));
      for (const k in o) if (k !== "api2_chat_message" && o[k] && typeof o[k] === "object") ids(o[k], out);
    }
    return out;
  };
  const rx = (ev) => {
    const now = Date.now();
    let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
    for (const id of ids(d, [])) if (!(id in P.rx)) P.rx[id] = now;
  };
  const Native = window.EventSource;
  const add = Native.prototype.addEventListener;
  Native.prototype.addEventListener = function (type, fn, opts) {
    if (type === "ping" || typeof fn !== "function") return add.call(this, type, fn, opts);
    return add.call(this, type, function (ev) {
      rx(ev);
      const t0 = performance.now();
      try { return fn.apply(this, arguments); } finally { P.handler.push(performance.now() - t0); }
    }, opts);
  };
  window.EventSource = class extends Native {
    constructor(url, init) {
      super(url, init);
      P.streams++;
      add.call(this, "api2_chat_message", rx);
      add.call(this, "resync", () => { P.resync++; });
    }
  };
  // Marker watch: resolves with the epoch ms the text first shows in the DOM.
  P.watch = (text, timeoutMs) => {
    P.marks[text] = new Promise((res) => {
      const has = (n) => ((n && n.textContent) || "").includes(text);
      if (has(document.body)) return res(Date.now());
      const mo = new MutationObserver((ms) => {
        for (const m of ms) {
          if (m.type === "characterData" ? has(m.target) : [...m.addedNodes].some(has)) {
            mo.disconnect(); return res(Date.now());
          }
        }
      });
      mo.observe(document.body, { subtree: true, childList: true, characterData: true });
      setTimeout(() => { mo.disconnect(); res(null); }, timeoutMs);
    });
  };
  // Drain the per-stage samples; `rx` stays (lag is computed per injected id).
  P.take = () => {
    const out = { handler: P.handler, longTasks: P.longTasks, resync: P.resync, streams: P.streams,
                  heap: (performance.memory || {}).usedJSHeapSize || null,
                  rows: document.querySelectorAll("[data-chat-row]").length, rx: P.rx };
    P.handler = []; P.longTasks = [];
    return out;
  };
})();"""


async def screen_bundle_404(r) -> bool:
    path = urlsplit(r.request.url).path
    if not path.startswith(SCREEN_BUNDLES) or path == CHAT_SCREEN_PATH:
        return False
    await r.fulfill(status=404, content_type="application/json", body='{"detail":"Not Found"}')
    return True


async def route_held_read(r, held: list, aborted: list | None = None, on_hold=None) -> None:
    path = urlsplit(r.request.url).path
    if await screen_bundle_404(r):
        if aborted is not None:
            aborted.append(r.request.url)
        return
    if path.startswith("/api/of/") or path in OF_LIVE_PATHS:
        held.append(r)
        if on_hold:
            await on_hold(r)
    else:
        await r.continue_()


async def set_no_bundles_cookie(bctx, host: str) -> None:
    await bctx.add_cookies([{"name": NO_BUNDLES_COOKIE, "value": "1", "domain": host, "path": "/"}])


async def hold_of_reads(bctx, host: str, held: list, *, on_hold=None) -> None:
    await set_no_bundles_cookie(bctx, host)

    async def route(r):
        await route_held_read(r, held, on_hold=on_hold)

    await bctx.route("**/*", route)


async def end_held_background_reads(page, seconds: float) -> int:
    held, n, end = page.slop["held_of_reads"], 0, time.monotonic() + seconds
    while time.monotonic() < end:
        for r in [r for r in held if r.request.headers.get("x-priority") == "background"]:
            held.remove(r)
            n += 1
            try:
                await r.abort()
            except Exception:  # noqa: BLE001 — the page dropped it meanwhile
                pass
        await page.wait_for_timeout(100)
    return n


def _client_fault(ctx) -> tuple:
    from slop.lib.faults import FAULTS
    f = FAULTS.get(getattr(ctx, "fault", None) or "")
    return tuple((re.compile(rx), rx, rep) for rx, rep in f.browser) if f else ()


async def _patched(r, ctx, patches, origin: str | None = None) -> None:
    hits = ctx.browser_fault_hits
    files = ctx.browser_fault_files
    try:
        u = urlsplit(r.request.url)
        resp = await (r.fetch(url=f"{origin}{u.path}{'?' + u.query if u.query else ''}") if origin else r.fetch())
        body = await resp.text()
    except Exception:  # noqa: BLE001
        try:
            await r.abort()
        except Exception:  # noqa: BLE001 — the page is gone
            pass
        return
    path = urlsplit(r.request.url).path
    for rx, key, rep in patches:
        body, n = rx.subn(rep, body)
        hits[key] = hits.get(key, 0) + n
        if n:
            files[path] = files.get(path, 0) + n
    await r.fulfill(response=resp, body=body)


def track(ctx, bctx) -> None:
    seen = ctx.ui_pages

    def on_nav(page, frame) -> None:
        u = urlsplit(frame.url)
        if frame == page.main_frame and u.scheme in ("http", "https"):
            seen.add(u.path or "/")

    def on_page(page) -> None:
        page.on("framenavigated", lambda f: on_nav(page, f))
    bctx.on("page", on_page)
    for p in bctx.pages:
        on_page(p)


async def _owner_page(browser, ctx, viewport, held, aborted, init_scripts=(), *, http=None, app=None,
                      send=False, through=(), scale=1, touch=False):
    # --net: service workers blocked (their fetches ride unthrottled: CDP conditions are the page's); route('**/*') also turns Chromium's HTTP cache off.
    bctx = await browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                     device_scale_factor=scale, has_touch=touch, is_mobile=touch,
                                     service_workers="block" if ctx.net else "allow")
    host = urlsplit(app or ctx.app).hostname
    await bctx.add_cookies([{"name": c.name, "value": c.value, "domain": host, "path": "/"}
                            for c in (http or ctx.owner).c.cookies.jar])
    fault = FAULTS.get(ctx.fault or "")
    for js in (INIT_JS, *init_scripts, *((fault.browser_js,) if fault and fault.browser_js else ())):
        await bctx.add_init_script(js)

    patches = _client_fault(ctx)

    async def route(r):
        u = urlsplit(r.request.url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            aborted.append(r.request.url)
            await r.abort()
        elif patches and u.path.startswith("/_next/static/") and u.path.endswith(".js"):
            await _patched(r, ctx, patches)
        elif (send and r.request.method == "POST" and SEND_PATH.fullmatch(u.path)) or any(
                t == u.path if isinstance(t, str)
                else (r.request.method == t[0] and t[1].fullmatch(u.path)) if isinstance(t, tuple)
                else (r.request.method == "GET" and t.fullmatch(u.path))
                for t in through):
            await r.continue_()
        else:
            await route_held_read(r, held, aborted)

    await set_no_bundles_cookie(bctx, host)
    await bctx.route("**/*", route)
    track(ctx, bctx)
    page = await bctx.new_page()
    cdp = None
    if ctx.net:
        cdp = await bctx.new_cdp_session(page)
        await emulate(cdp, ctx.net)
    statuses: list[tuple[int, str]] = []
    page.on("response", lambda resp: statuses.append((resp.status, resp.url)))
    page.slop = {"held_of_reads": held, "offhost_aborted": aborted, "statuses": statuses,
                 "crashed": None, "cdp": cdp}
    page.on("crash", lambda _p: page.slop.update(crashed=time.time() * 1000))
    return page


ACCEPT_CONFIRMS_JS = """(() => {
  if (window.__slopAcceptConfirms) return;
  window.__slopAcceptConfirms = true;
  const accept = () => {
    for (const d of document.querySelectorAll('[role="dialog"][aria-describedby^="if-confirm-"]')) {
      if (d.dataset.slopAccepted) continue;
      const ok = [...d.querySelectorAll('button')].pop();
      if (ok) { d.dataset.slopAccepted = '1'; ok.click(); }
    }
  };
  const start = () => { new MutationObserver(accept).observe(document.documentElement, { childList: true, subtree: true }); accept(); };
  if (document.documentElement) start(); else document.addEventListener('DOMContentLoaded', start);
})();"""


async def accept_confirms(page) -> None:
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await page.add_init_script(ACCEPT_CONFIRMS_JS)
    await page.evaluate(ACCEPT_CONFIRMS_JS)


@asynccontextmanager
async def owner_browser(ctx, viewport=(1600, 1000), through=(), send=False, scale=1, touch=False):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            yield await _owner_page(browser, ctx, viewport, [], [], through=through, send=send, scale=scale,
                                    touch=touch)
        finally:
            await browser.close()


async def close_popup(opener, pop) -> None:
    held = opener.slop["held_of_reads"]

    def page_of(r):
        try:
            return r.request.frame.page
        except Exception:  # noqa: BLE001 — a worker's request has no frame
            return None

    # Chromium resumes requests paused at the Fetch domain when their page detaches; abort first or they reach the relay (offline OF answers 500).
    for r in [r for r in held if page_of(r) is pop]:
        held.remove(r)
        try:
            await r.abort()
        except Exception:  # noqa: BLE001 — already gone with its frame
            pass
    await pop.close()


@asynccontextmanager
async def owner_tabs(ctx, n: int, viewport=(1600, 1000), probe: bool = True):
    held, aborted = [], []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            yield [await _owner_page(browser, ctx, viewport, held, aborted, (PROBE_JS,) if probe else ())
                   for _ in range(n)]
        finally:
            await browser.close()


@asynccontextmanager
async def chatter_tab(ctx, http, app: str, viewport=(1600, 1000)):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            yield await _owner_page(browser, ctx, viewport, [], [], http=http, app=app, send=True)
        finally:
            await browser.close()


async def take(page) -> dict:
    return await page.evaluate("() => window.__slop.take()")


async def watch(page, text: str, timeout_ms: int = 60_000) -> None:
    await page.evaluate("([t, ms]) => window.__slop.watch(t, ms)", [text, timeout_ms])


async def seen(page, text: str) -> float | None:
    """Epoch ms the watched text appeared (None: it never did within the timeout)."""
    return await page.evaluate("(t) => window.__slop.marks[t]", text)


async def pick_creator(page, name: str, timeout_ms: int = 60_000) -> None:
    rows = page.get_by_test_id("of-creator-column").get_by_test_id("of-creator-row")
    mine = page.get_by_text(name, exact=True)
    await rows.filter(has=mine).first.click(timeout=timeout_ms)
    await rows.and_(page.locator("[aria-current='true']")).filter(has=mine).first.wait_for(timeout=timeout_ms)


async def swipe(page, x0: float, y0: float, x1: float, y1: float, *, ms: int = 200, steps: int = 10,
                cancel: bool = False, via: tuple[tuple[float, float], ...] = (),
                legs: tuple[tuple[int, int], ...] = (), mid=None, hold_ms: int = 0) -> None:
    pts = [(x0, y0), *via, (x1, y1)]
    timing = legs or tuple((ms // (len(pts) - 1), steps) for _ in pts[1:])
    total = sum(n for _, n in timing)
    done = 0
    cdp = await page.context.new_cdp_session(page)
    finger = time.time()
    sync = (finger, time.monotonic())

    async def send(kind: str, touch: list) -> None:
        await cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": touch, "timestamp": finger})

    def held() -> None:
        nonlocal finger, sync
        finger = max(finger, time.time())
        sync = (finger, time.monotonic())

    try:
        await send("touchStart", [{"x": x0, "y": y0}])
        for ((ax, ay), (bx, by)), (leg_ms, n) in zip(zip(pts, pts[1:]), timing):
            for i in range(1, n + 1):
                finger += leg_ms / n / 1000
                await asyncio.sleep(max(0.0, sync[1] + (finger - sync[0]) - time.monotonic()))
                await send("touchMove", [{"x": ax + (bx - ax) * i / n, "y": ay + (by - ay) * i / n}])
                done += 1
                if mid and done == total // 2:
                    await mid()
                    held()
        if hold_ms:
            await asyncio.sleep(hold_ms / 1000)
            finger += hold_ms / 1000
            held()
        await send("touchCancel" if cancel else "touchEnd", [])
    finally:
        await cdp.detach()


TOUCH_LOG_JS = """() => {
  window.__touches = [];
  if (window.__touchLogOn) return;
  window.__touchLogOn = true;
  for (const ty of ['touchstart', 'touchmove', 'touchend', 'touchcancel']) document.addEventListener(ty, (e) => {
    const t = e.changedTouches[0];
    window.__touches.push([ty.slice(5), t ? Math.round(t.clientX) : null, Math.round(e.timeStamp), Math.round(performance.now())]);
  }, { capture: true, passive: true });
}"""


async def touch_log(page) -> None:
    await page.evaluate(TOUCH_LOG_JS)


async def touches(page) -> list:
    return await page.evaluate("() => window.__touches || []")


SHEET_PROBE_JS = """([sel, px, py]) => {
  window.__sheetSel = sel;
  window.__sheetPt = [px, py];
  window.__sheet = { end: null, off: null, off_by: null, gone: null, hit50: null, starts: [], clicks: [] };
  if (window.__sheetOn) return;
  window.__sheetOn = true;
  // `.exit-ghost`: app/hooks/layerMarks.ts EXIT_GHOST.
  const real = () => document.querySelector(window.__sheetSel + ':not(.exit-ghost):not(.exit-ghost *)');
  const opts = { capture: true, passive: true };
  document.addEventListener('touchstart', () => window.__sheet.starts.push(
    { t: performance.now(), mounted: !!real(), ghost: !!document.querySelector('.exit-ghost') }), opts);
  document.addEventListener('touchend', () => { const g = window.__sheet; if (g.end === null) g.end = performance.now(); }, opts);
  document.addEventListener('click', (e) => window.__sheet.clicks.push({ t: performance.now(), mounted: !!real(),
    main: !!(e.target instanceof Element && e.target.closest('main')) }), true);
  // `by`: 'rect' (it slid past the edge) or 'gone' (it unmounted first, its slide cut short).
  const wentOff = (g, by) => { g.off = performance.now(); g.off_by = by; setTimeout(() => {
    const h = document.elementFromPoint(window.__sheetPt[0], window.__sheetPt[1]);
    g.hit50 = { main: !!(h && h.closest('main')), sheetMounted: !!real() }; }, 50); };
  new MutationObserver(() => { const g = window.__sheet;
    if (g.end !== null && g.gone === null && !real()) { g.gone = performance.now(); if (g.off === null) wentOff(g, 'gone'); }
  }).observe(document.body, { childList: true, subtree: true });
  const tick = () => { const g = window.__sheet; const el = real();
    if (g.end !== null && g.off === null && el) { const r = el.getBoundingClientRect();
      if (r.right <= 0 || r.left >= window.innerWidth) wentOff(g, 'rect'); }
    requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""
SHEET_READ_JS = """() => { const g = window.__sheet; const t = (v) => v === null || g.end === null ? null : Math.round(v - g.end);
  return { release_to_off_ms: t(g.off), release_to_unmount_ms: t(g.gone),
    off_to_unmount_ms: g.off === null || g.gone === null ? null : Math.round(g.gone - g.off), off_by: g.off_by,
    hit50: g.hit50,
    starts: g.starts.map((s) => ({ ms: t(s.t), mounted: s.mounted, ghost: s.ghost })),
    clicks: g.clicks.map((c) => ({ ms: t(c.t), mounted: c.mounted, main: c.main })) }; }"""


async def sheet_probe(page, sel: str, pt: tuple[float, float] = (0, 0)) -> None:
    await page.evaluate(SHEET_PROBE_JS, [sel, pt[0], pt[1]])


async def sheet_read(page) -> dict:
    return await page.evaluate(SHEET_READ_JS)


async def shot(ctx, page, name: str, timeout_ms: float = 30_000) -> str:
    path = ctx.out / "screenshots" / f"{name}.png"
    await page.screenshot(path=str(path), timeout=timeout_ms)
    return str(path)
