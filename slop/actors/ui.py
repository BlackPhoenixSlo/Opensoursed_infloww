"""Browser actor: Chromium signed in as the owner, loopback-only (every other
host unresolvable), OnlyFans-live reads (/api/of/*) held pending so a screen
shows what the relay's own DB serves (the Fan List's local seed), screenshot on
every visit.

`owner_tabs` opens several tabs, each in its own browser context: production
serves the app over HTTP/2 (one multiplexed connection), while the slop stack is
plain HTTP/1.1, where Chromium's 6-connections-per-host cap would let 5 open SSE
streams starve every other request. `PROBE_JS` instruments a tab without touching
app code: SSE receipt time per chat message id (`rx`), the app's handler time per
SSE event, long tasks (>50 ms), heap, rendered Fan List rows, and a text watcher
for marker DMs (`watch` / `seen`)."""
from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from slop.lib.faults import FAULTS

# Light theme; hide Next's dev overlay so screenshots show only the app.
INIT_JS = """try { localStorage.setItem('chatterly:theme', 'light'); } catch (e) {}
document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style');
  s.textContent = 'nextjs-portal, [data-nextjs-toast], [data-next-badge-root] { display: none !important; }';
  document.documentElement.appendChild(s); });"""
# Relay routes outside /api/of/ that are OnlyFans-live reads too: held like /api/of/*.
OF_LIVE_PATHS = ("/admin/vault/wall-media",)
SEND_PATH = re.compile(r"/api/of/v2/chats/\d+/messages")
# precise-memory-info: without it performance.memory is bucketed and never moves.
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


def _client_fault(ctx) -> tuple:
    """The run's client fault (lib/faults.py `browser=`): compiled (regex, replacement) pairs."""
    from slop.lib.faults import FAULTS
    f = FAULTS.get(getattr(ctx, "fault", None) or "")
    return tuple((re.compile(rx), rx, rep) for rx, rep in f.browser) if f else ()


async def _patched(r, ctx, patches) -> None:
    """Serve the app's JS with the client fault's rewrites; count each rewrite's matches
    (ctx.browser_fault_hits, which lib/cli.py requires to be > 0 for every rewrite) and the
    files they hit (ctx.browser_fault_files). A file that cannot be fetched (the page moved
    on mid-load) is aborted, never served unpatched."""
    hits = ctx.browser_fault_hits
    files = ctx.browser_fault_files
    try:
        resp = await r.fetch()
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


async def _owner_page(browser, ctx, viewport, held, aborted, init_scripts=(), *, http=None, app=None,
                      send=False, through=(), scale=1, touch=False):
    """A tab signed in as `http`'s session (default the owner's) on `app` (default ctx.app).
    `send`: let the chat send (POST /api/of/v2/chats/{fan}/messages) through to the relay,
    whose OnlyFans hop lib/relay.py answers; `through`: exact /api/of/ paths let through to
    the relay too (a read whose OnlyFans hop lib/relay.py fakes), compiled patterns a GET's
    whole path must match, or (method, compiled pattern) pairs for another method (e.g. the
    chat mute's POST / DELETE); every other /api/of/ call stays held. `scale`: the device
    scale factor (2 for a zoomed crop). `touch`: a phone's context (touch input, mobile
    viewport), for `tap` and `swipe`."""
    bctx = await browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                     device_scale_factor=scale, has_touch=touch, is_mobile=touch)
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
        elif u.path.startswith("/api/of/") or u.path in OF_LIVE_PATHS:
            held.append(r)  # never answered: OF is not reachable from a slop run
        else:
            await r.continue_()

    await bctx.route("**/*", route)
    page = await bctx.new_page()
    statuses: list[tuple[int, str]] = []
    page.on("response", lambda resp: statuses.append((resp.status, resp.url)))
    page.slop = {"held_of_reads": held, "offhost_aborted": aborted, "statuses": statuses, "crashed": None}
    page.on("crash", lambda _p: page.slop.update(crashed=time.time() * 1000))
    return page


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
    """Close `pop`, a window `opener`'s page opened (same context, same routes). Its held
    /api/of/ reads are aborted first: Chromium resumes requests still paused at the Fetch domain
    when their page detaches, so a plain close would let them through to the relay, whose
    offline OnlyFans answers 500. Aborted, they die as a closed window's fetches do."""
    held = opener.slop["held_of_reads"]

    def page_of(r):
        try:
            return r.request.frame.page
        except Exception:  # noqa: BLE001 — a worker's request has no frame
            return None

    for r in [r for r in held if page_of(r) is pop]:
        held.remove(r)
        try:
            await r.abort()
        except Exception:  # noqa: BLE001 — already gone with its frame
            pass
    await pop.close()


@asynccontextmanager
async def owner_tabs(ctx, n: int, viewport=(1600, 1000), probe: bool = True):
    """`n` signed-in tabs (one browser context each), PROBE_JS installed."""
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
    """One tab signed in as a chatter (`http`'s cookie) on `app`, its chat send let through."""
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
    """Picks a Creator on a My Automations page's creator column (`CreatorRail`, Smart lists' own): clicks its row
    and waits until that row is the current pick."""
    rows = page.get_by_test_id("of-creator-column").get_by_test_id("of-creator-row")
    mine = page.get_by_text(name, exact=True)
    await rows.filter(has=mine).first.click(timeout=timeout_ms)
    await rows.and_(page.locator("[aria-current='true']")).filter(has=mine).first.wait_for(timeout=timeout_ms)


async def swipe(page, x0: float, y0: float, x1: float, y1: float, *, ms: int = 200, steps: int = 10,
                cancel: bool = False, via: tuple[tuple[float, float], ...] = (),
                legs: tuple[tuple[int, int], ...] = (), mid=None, hold_ms: int = 0) -> None:
    """One finger from (x0, y0) to (x1, y1) over `ms`, as Chromium's touch input (CDP
    Input.dispatchTouchEvent): the page sees real touch and pointer events, and the
    compositor scrolls as it would for a finger. `via` bends the path through those
    points (`steps` moves per leg); `legs` gives each leg its own (ms, steps), e.g. a
    slow drag then a quick flick back. `cancel` ends it as the OS taking the gesture does
    (touchcancel). `mid` (async) runs halfway through the moves and the finger then
    moves on, so the release keeps the finger's real speed (a sheet's release decision
    reads the last ~100ms); `hold_ms` holds the finger still at the end, which makes the
    release speed 0.

    Each event carries the finger's own time (CDP `timestamp`, which becomes the page's
    `event.timeStamp`), as a phone's digitizer stamps a touch when it happens, not when
    the page gets it: the moves are paced against the wall clock, but a slow CDP round
    trip (a busy dev server) no longer stretches the swipe the page measures. A `mid`
    or hold pauses that clock with the finger: it held still meanwhile."""
    pts = [(x0, y0), *via, (x1, y1)]
    timing = legs or tuple((ms // (len(pts) - 1), steps) for _ in pts[1:])
    total = sum(n for _, n in timing)
    done = 0
    cdp = await page.context.new_cdp_session(page)
    finger = time.time()  # the finger's clock (s since the epoch, as CDP takes it)
    sync = (finger, time.monotonic())  # a moment both clocks agree on: moves are due from it

    async def send(kind: str, touch: list) -> None:
        await cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": touch, "timestamp": finger})

    def held() -> None:  # the finger held still while something else ran: its clock catches up
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


# Every touch event the page sees, from `touch_log` on: [kind, clientX, event.timeStamp, performance.now()].
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
    """Start (or restart) logging the page's touch events; `touches` reads them."""
    await page.evaluate(TOUCH_LOG_JS)


async def touches(page) -> list:
    return await page.evaluate("() => window.__touches || []")


# In-page recorder for one sheet gesture (`sheet_probe`), on the sheet `sel` (its real element, never a
# `.exit-ghost` copy): the release (the first touchend), the frame it is first off screen (or gone), its
# unmount, a hit test at `pt` 50ms after it went off, each touchstart (was the sheet still mounted, was a
# leaving copy there) and each click (on `main`? sheet still mounted?). Installed once per page; each call
# resets it and sets the sheet and point it watches.
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
    """Record the next gesture on the sheet `sel` (`SHEET_PROBE_JS`); `sheet_read` returns it, times in ms
    from the release."""
    await page.evaluate(SHEET_PROBE_JS, [sel, pt[0], pt[1]])


async def sheet_read(page) -> dict:
    return await page.evaluate(SHEET_READ_JS)


async def shot(ctx, page, name: str, timeout_ms: float = 30_000) -> str:
    path = ctx.out / "screenshots" / f"{name}.png"
    await page.screenshot(path=str(path), timeout=timeout_ms)
    return str(path)
