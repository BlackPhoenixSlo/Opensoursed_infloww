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


async def _owner_page(browser, ctx, viewport, held, aborted, init_scripts=(), *, scale=1):
    """A tab signed in as the owner on ctx.app. `scale`: the device scale factor
    (2 for a zoomed crop). A fault with a `browser` script runs it in every page."""
    bctx = await browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                     device_scale_factor=scale)
    host = urlsplit(ctx.app).hostname
    await bctx.add_cookies([{"name": c.name, "value": c.value, "domain": host, "path": "/"}
                            for c in ctx.owner.c.cookies.jar])
    fault = FAULTS.get(ctx.fault or "")
    for js in (INIT_JS, *init_scripts, *((fault.browser,) if fault and fault.browser else ())):
        await bctx.add_init_script(js)

    async def route(r):
        u = urlsplit(r.request.url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            aborted.append(r.request.url)
            await r.abort()
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
async def owner_browser(ctx, viewport=(1600, 1000), scale=1):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=LAUNCH_ARGS)
        try:
            yield await _owner_page(browser, ctx, viewport, [], [], scale=scale)
        finally:
            await browser.close()


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


async def take(page) -> dict:
    return await page.evaluate("() => window.__slop.take()")


async def watch(page, text: str, timeout_ms: int = 60_000) -> None:
    await page.evaluate("([t, ms]) => window.__slop.watch(t, ms)", [text, timeout_ms])


async def seen(page, text: str) -> float | None:
    """Epoch ms the watched text appeared (None: it never did within the timeout)."""
    return await page.evaluate("(t) => window.__slop.marks[t]", text)


async def shot(ctx, page, name: str, timeout_ms: float = 30_000) -> str:
    path = ctx.out / "screenshots" / f"{name}.png"
    await page.screenshot(path=str(path), timeout=timeout_ms)
    return str(path)
