"""Notification clicks, as the owner makes them. A fan DM enters at the pump boundary
(actors/fan_dm), the toaster and the bell's history mirror pick it up, and the owner
clicks it from each place a notification shows. Every click must open the Fan as a Fan
tab in the one Messages Pro window (app/lib/notificationLink.ts): no new tab or window,
the Fan in the Fan tabs strip, in the stored Fan tabs and in the Chat header, and the
clicked window left where it was. A click inside Messages Pro adds the tab in place,
with no reload.

`browser`: headless Chromium (actors/ui), Messages Pro opened from the sidebar as the
app opens it (the `messages-pro` popup). `desktop`: the real Electron app
(desktop/main.js) on this run's app, driven over CDP; SKIP when the binary is missing.

Declared bypasses:
- message toasts and the OS ping are switched on in localStorage
  `chatterly:notif-settings:v1` (both default off), as the bell's Toast settings would;
- browser: OF's notifications feed is answered with one fixture row at the wire
  boundary (the /notifications page's row; every other /api/of read stays held, as in
  actors/ui). Headless Chromium has no notification centre, so the web Notification is
  a recorder and `document.hasFocus()` reads false while the OS step asks for it; that
  notification is clicked through its own onclick;
- desktop: a wrapper outside product code (written into the run folder) points
  userData at a temp dir (never the user's profile or single-instance lock), logs the
  cards sent to the app's macOS toast window (desktop/lib/toast-window.js) and clicks,
  in that window's DOM, the card whose body carries NATIVE_CLICK, where a user's mouse
  would (the only bypass); the rest is the product's IPC. The main window's `document.hasFocus()` reads
  false for that step, as in the browser (a CDP-driven window keeps OS focus). The owner
  cookie is set over CDP. OF reads are held and the feed answered as in the browser.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from slop.actors import fan_dm, ui
from slop.lib.faults import FAULTS

ROOT = Path(__file__).resolve().parents[2]
ELECTRON = ROOT / "desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
NATIVE_CLICK = "slop native click"
SETTLE_S = 90  # a first Deep link compiles under `next dev`

BROWSER_ENTRIES = ("main-window toast", "Messages Pro toast", "top bar bell row", "/notifications row",
                   "OS notification")
DESKTOP_ENTRIES = ("main-window toast", "Messages Pro toast", "top bar bell row", "native notification")


_STEP: list[tuple[int, str]] = []  # (ms, step) as the steps start: what a console line happened during


def _step(name: str) -> None:
    _STEP.append((round(time.time() * 1000), name))


def _step_at(t_ms: int) -> str:
    return next((n for t, n in reversed(_STEP) if t <= t_ms), "setup")


class _Console:
    """Console errors and warnings, and uncaught errors, of every app page, by step: what
    `next dev`'s Issues badge counts. One JSON line each in console-<env>.jsonl."""

    def __init__(self, ctx, env: str):
        self.path, self.env, self.seen = ctx.out / f"console-{env}.jsonl", env, set()

    def write(self, row: dict, t_ms: int | None = None) -> None:
        t_ms = t_ms if t_ms is not None else round(time.time() * 1000)
        with open(self.path, "a") as f:
            f.write(json.dumps({"env": self.env, "step": _step_at(t_ms), "t": t_ms, **row}) + "\n")

    def attach(self, page) -> None:
        if id(page) in self.seen:
            return
        self.seen.add(id(page))

        def on_console(m):
            if m.type in ("error", "warning"):
                loc = m.location or {}
                self.write({"page": page.url, "type": m.type, "text": m.text[:2000],
                            "at": f'{loc.get("url")}:{loc.get("lineNumber")}:{loc.get("columnNumber")}'})

        page.on("console", on_console)
        page.on("pageerror", lambda e: self.write({"page": page.url, "type": "pageerror", "text": str(e)[:2000],
                                                   "stack": (getattr(e, "stack", "") or "")[:2000]}))

    def watch(self, bctx) -> None:
        bctx.on("page", self.attach)
        for p in bctx.pages:
            self.attach(p)


def distinct(fans: list[dict]) -> list[dict]:
    """Fans no other Fan of the list shares a name with: a Fan tab is found by its name."""
    names = [f["name"] for f in fans]
    return [f for f in fans if names.count(f["name"]) == 1]


def check_name(env: str, entry: str) -> str:
    return f"{env} {entry} click opens the Fan as a Fan tab in the one Messages Pro window"


BROWSER_CHECKS = tuple(check_name("browser", e) for e in BROWSER_ENTRIES)
DESKTOP_CHECKS = tuple(check_name("desktop", e) for e in DESKTOP_ENTRIES)

SETTINGS = {"enabled": True, "osPing": True,
            "toast": {"message": True, "purchases": True, "tip": True, "subscribed": False, "mentioned": False,
                      "commented": False, "favorited": False},
            "bubble": {"message": False, "purchases": True, "tip": True, "subscribed": False, "mentioned": False,
                       "commented": False, "favorited": False},
            "platforms": {"onlyfans": True, "fansly": True},
            "sounds": {"message": {"on": False, "sound": "s1"}, "reminder": {"on": True, "sound": "s1"}}}
SETTINGS_JS = f"try {{ localStorage.setItem('chatterly:notif-settings:v1', {json.dumps(json.dumps(SETTINGS))}); }} catch (e) {{}}"
# Headless Chromium's stand-in for the OS: notifications are recorded, focus is lost on request.
FOCUS_JS = """window.__slopBlur = false;
(() => { const has = Document.prototype.hasFocus;
  Document.prototype.hasFocus = function () { return window.__slopBlur ? false : has.call(this); }; })();"""
OS_JS = FOCUS_JS + """
window.__slopNotifs = [];
window.Notification = class { constructor(title, o) { this.title = title; this.body = (o || {}).body; this.tag = (o || {}).tag;
  this.onclick = null; this.closed = false; window.__slopNotifs.push(this); }
  close() { this.closed = true; } static get permission() { return 'granted'; }
  static requestPermission() { return Promise.resolve('granted'); } };"""

# What the Messages Pro window shows for `fan` right now.
STATE_JS = """(fan) => {
  const strip = document.querySelector('[role=tablist][aria-label="Fan tabs strip"]');
  const tabs = strip ? [...strip.querySelectorAll('[role=tab]')] : [];
  const active = tabs.find((t) => t.getAttribute('aria-selected') === 'true');
  let stored = 0;
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (!k || !k.startsWith('chatterly:fan-tabs:v1:')) continue;
    try { stored += JSON.parse(localStorage.getItem(k)).filter((t) => String(t.fanId) === String(fan.id)).length; } catch (e) {}
  }
  const head = document.querySelector('button[title="Avatar menu"]');  // the Chat header's name and presence
  return { url: location.pathname + location.search, mark: window.__slopMark || null,
           tabs: tabs.map((t) => t.innerText.trim()), active: active ? active.innerText.trim() : null,
           stored, header: head ? head.textContent.trim().slice(0, 120) : null };
}"""


def _shown(state: dict, fan: dict) -> bool:
    """The Fan's tab in the strip and active, stored once, and its chat open. The Chat header
    names the Fan by its OF profile, which slop holds, so after a reload it reads `fan <id>`."""
    header = state.get("header") or ""
    return (any(fan["name"] in t for t in state.get("tabs", [])) and fan["name"] in (state.get("active") or "")
            and state.get("stored") == 1 and (fan["name"] in header or str(fan["id"]) in header))


async def _settle(mp, fan: dict) -> dict:
    state: dict = {}
    for _ in range(SETTLE_S * 2):
        try:
            state = await mp.evaluate(STATE_JS, fan)
            if _shown(state, fan):
                return state
        except Exception as e:  # noqa: BLE001  (mid-navigation)
            state = {"error": repr(e)}
        await asyncio.sleep(0.5)
    return state


class _Dms:
    """Fan DMs at the pump boundary. A DM that shows no toast is sent again with a new id
    (the transcoder fault drops every 10th): what is tested is the click, not delivery."""

    def __init__(self, ctx, account_id: str, base: int):
        self.ctx, self.account_id, self.ids = ctx, account_id, iter(range(base, base + 1000))

    async def send(self, fan: dict, text: str) -> int:
        return (await fan_dm.inject(self.ctx.owner, self.account_id, fan_dm.frame(next(self.ids), fan, text))).status_code

    async def toast(self, page, fan: dict, text: str):
        for attempt in range(1, 4):
            await self.send(fan, text)
            loc = page.locator("a.animate-toast-in").filter(has_text=text).first
            try:
                await loc.wait_for(timeout=20_000)
                return loc, attempt
            except Exception:  # noqa: BLE001
                continue
        return None, 3


async def _arm(mp) -> None:
    """Right before a click: Messages Pro is up to take it (`next dev` may have reloaded it
    while compiling a route the other window opened), and marked, so a reload by the click
    itself shows (the mark gone)."""
    await mp.wait_for_function("() => typeof window.__inflowwOpenNotification === 'function'", timeout=120_000)
    await mp.evaluate("() => { window.__slopMark = 1; }")


def _pages(any_page) -> list:
    return [p for c in any_page.context.browser.contexts for p in c.pages]


async def _judge(ctx, env: str, entry: str, *, mp, fan: dict, trigger, trigger_url: str, windows_before: int,
                 windows, slug: str, pages_before: list, extra: dict | None = None) -> dict:
    state = await _settle(mp, fan)
    await asyncio.sleep(1.0)  # a stray window would have opened by now
    after = await windows()
    kept = trigger.url == trigger_url
    no_reload = state.get("mark") == 1  # set by _arm: Messages Pro took the click in place
    ok = _shown(state, fan) and after == windows_before and kept and no_reload
    try:
        settled = await ui.shot(ctx, mp, f"{slug}-settled")
    except Exception as e:  # noqa: BLE001  (Messages Pro gone: the check fails, the steps after it go on)
        settled, ok, state = None, False, {**state, "screenshot_error": repr(e)[:300]}
    # A window the click opened, counted above, is closed: its /events stream would hold one
    # of the browser's six connections to the app, starving the steps after it.
    for p in _pages(trigger):
        if p not in pages_before:
            await p.close()
    res = {"env": env, "entry": entry, "fan": fan["id"], "ok": ok, "windows_before": windows_before,
           "windows_after": after, "clicked_window_url_kept": kept, "in_place_no_reload": no_reload,
           "state": state, "settled_png": settled, **(extra or {})}
    ctx.check(check_name(env, entry), ok, windows=f"{windows_before}->{after}", tabs=state.get("tabs"),
              active=state.get("active"), stored=state.get("stored"), header=state.get("header"),
              clicked_window_kept=kept, no_reload=no_reload)
    return res


def _feed(account_id: str, fan: dict, text: str):
    """OF's notifications feed: one row about `fan` for its Creator, none for the others."""
    async def handle(r):
        if "/count" in r.request.url:
            await r.fulfill(json={})
            return
        # As OF: a row is listed for its own type only (the money rail's type=tip and type=purchases
        # lists never carry a message; one would show twice there, under one key).
        typ = parse_qs(urlsplit(r.request.url).query).get("type", ["message"])[0]
        if r.request.headers.get("x-account-id") != account_id or typ != "message":
            await r.fulfill(json={"list": [], "hasMore": False})
            return
        await r.fulfill(json={"list": [{"id": 424242, "type": "message", "isRead": False,
                                        "createdAt": "2026-10-26T01:00:00+00:00", "text": text,
                                        "user": {"id": fan["id"], "name": fan["name"], "username": fan["username"]}}],
                              "hasMore": False})
    return handle


async def browser(ctx, account_id: str, fans: list[dict]) -> list[dict]:
    """Five entry points in headless Chromium; one check each (BROWSER_CHECKS). Each clicks
    about a Fan with no tab yet, so a click that does nothing cannot pass."""
    pick = distinct(fans)
    if len(pick) < 5:
        for n in BROWSER_CHECKS:
            ctx.check(n, False, reason=f"{len(pick)} Fans with a name of their own, 5 needed")
        return []
    f1, f2, f3, f4, f5 = pick[:5]
    dms = _Dms(ctx, account_id, fan_dm.INJECT_ID_BASE + 777_000)
    out: list[dict] = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=ui.LAUNCH_ARGS)
        try:
            _STEP.clear()
            page = await ui._owner_page(b, ctx, (1600, 1000), [], [], (SETTINGS_JS, OS_JS))
            bctx = page.context
            _Console(ctx, "browser").watch(bctx)
            row_text = "slop notif click: page row"
            await bctx.route("**/api/of/v2/users/notifications**", _feed(account_id, f4, row_text))

            async def windows() -> int:
                return len(bctx.pages)

            await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
            await page.get_by_role("button", name="Notifications").first.wait_for(timeout=120_000)
            async with bctx.expect_page(timeout=60_000) as popup:
                await page.locator("a[href='/messages-pro']").first.click()
            mp = await popup.value
            await mp.get_by_role("button", name="Notifications").first.wait_for(timeout=120_000)

            # A: a toast in the main window.
            await page.bring_to_front()
            _step("nc-b1-main-toast arrival")
            toast, tries = await dms.toast(page, f1, "slop notif click: main toast")
            out.append(await _click(ctx, "browser", BROWSER_ENTRIES[0], toast, tries, page, mp, f1, windows, "nc-b1-main-toast"))

            # B: another Fan's row in the top bar bell (its toast left alone).
            await page.bring_to_front()
            _step("nc-b2-bell-row arrival")
            await dms.toast(page, f5, "slop notif click: bell row")
            await page.get_by_role("button", name="Notifications").first.click()
            row = page.locator(f'a[href*="/{f5["id"]}?"]:not(.animate-toast-in)').first
            out.append(await _click(ctx, "browser", BROWSER_ENTRIES[2], row, 1, page, mp, f5, windows, "nc-b2-bell-row",
                                    wait=True))

            # C: a toast inside Messages Pro.
            await mp.bring_to_front()
            _step("nc-b3-mp-toast arrival")
            toast, tries = await dms.toast(mp, f2, "slop notif click: Messages Pro toast")
            out.append(await _click(ctx, "browser", BROWSER_ENTRIES[1], toast, tries, mp, mp, f2, windows,
                                    "nc-b3-mp-toast"))

            # E: a row on the /notifications page.
            await page.bring_to_front()
            _step("nc-b4-notifications-row arrival")
            await page.goto(f"{ctx.app}/notifications", wait_until="domcontentloaded")
            row = page.locator("a").filter(has_text=row_text).first
            out.append(await _click(ctx, "browser", BROWSER_ENTRIES[3], row, 1, page, mp, f4, windows,
                                    "nc-b4-notifications-row", wait=True))

            # O: the OS notification of a DM that lands while the main window is unfocused.
            _step("nc-b5-os-notification arrival")
            await page.goto(f"{ctx.app}/", wait_until="domcontentloaded")
            await page.get_by_role("button", name="Notifications").first.wait_for(timeout=120_000)
            await page.evaluate("() => { window.__slopBlur = true; }")
            await mp.evaluate("() => { window.__slopBlur = false; }")
            text = "slop notif click: OS notification"
            shown, tries = None, 0
            for tries in range(1, 4):
                await dms.send(f3, text)
                for _ in range(40):
                    shown = await page.evaluate("(t) => window.__slopNotifs.findIndex((n) => (n.body || '').includes(t))", text)
                    if shown >= 0:
                        break
                    await asyncio.sleep(0.5)
                if shown is not None and shown >= 0:
                    break
            entry = BROWSER_ENTRIES[4]
            if shown is None or shown < 0:
                ctx.check(check_name("browser", entry), False, reason="no OS notification was raised", tries=tries)
            else:
                await _arm(mp)
                trigger_png = await ui.shot(ctx, page, "nc-b5-os-notification-trigger")
                before, url, known = await windows(), page.url, _pages(page)
                _step("nc-b5-os-notification click")
                await page.evaluate("(i) => window.__slopNotifs[i].onclick()", shown)
                out.append(await _judge(ctx, "browser", entry, mp=mp, fan=f3, trigger=page, trigger_url=url,
                                        windows_before=before, pages_before=known, windows=windows, slug="nc-b5-os-notification",
                                        extra={"trigger_png": trigger_png, "dm_tries": tries,
                                               "notification": await page.evaluate("(i) => { const n = window.__slopNotifs[i]; return {title: n.title, body: n.body, tag: n.tag, closed: n.closed}; }", shown)}))
        finally:
            await b.close()
    return out


async def _click(ctx, env, entry, target, tries, trigger, mp, fan, windows, slug, *, wait=False):
    if target is None:
        ctx.check(check_name(env, entry), False, reason="no toast showed", tries=tries)
        return {"env": env, "entry": entry, "ok": False, "reason": "no toast", "tries": tries}
    if wait:
        try:
            await target.wait_for(timeout=60_000)
        except Exception as e:  # noqa: BLE001
            png = await ui.shot(ctx, trigger, f"{slug}-missing")
            ctx.check(check_name(env, entry), False, reason=f"nothing to click: {e!r}"[:300], screenshot=png)
            return {"env": env, "entry": entry, "ok": False, "reason": "nothing to click", "png": png}
    await _arm(mp)
    trigger_png = await ui.shot(ctx, trigger, f"{slug}-trigger")
    before, url, known = await windows(), trigger.url, _pages(trigger)
    href = await target.get_attribute("href")
    _step(f"{slug} click")
    await target.click()
    return await _judge(ctx, env, entry, mp=mp, fan=fan, trigger=trigger, trigger_url=url, windows_before=before,
                        pages_before=known, windows=windows, slug=slug,
                        extra={"trigger_png": trigger_png, "href": href, "dm_tries": tries})


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


WRAPPER = """// slop: the desktop app on a throwaway profile, its notification clicked as a user would (actors/notif_click).
const {{ app, ipcMain }} = require("electron");
const handle = ipcMain.handle.bind(ipcMain);
ipcMain.handle = (ch, fn) => handle(ch, ch !== "shell:notify" ? fn : async (e, n) => {{
  const r = await fn(e, n);
  console.log("[slop] shell:notify", JSON.stringify({{ from: e.senderFrame && e.senderFrame.url, body: n && n.body, shown: r }}));
  return r;
}});
const set = app.setPath.bind(app);
set("userData", {udata});
app.setPath = (n, p) => set(n, n === "userData" ? {udata} : p);
// macOS: the app's own toast window (desktop/lib/toast-window.js). Log each card it is sent and click,
// in that window's DOM, the one whose body carries the mark: its preload's toast:open does the rest.
const clicked = new Set();
app.on("web-contents-created", (_e, wc) => {{
  // Each page's console errors and warnings (uncaught errors included), for console-desktop.jsonl.
  wc.on("console-message", (e, level, message, line, sourceId) => {{
    const d = typeof level === "number"
      ? {{ level: ["verbose", "info", "warning", "error"][level], message, line, sourceId }}
      : {{ level: e.level, message: e.message, line: e.lineNumber, sourceId: e.sourceId }};
    if (d.level !== "warning" && d.level !== "error") return;
    console.log("[slop] console " + JSON.stringify({{ t: Date.now(), page: wc.getURL(), type: d.level,
      text: String(d.message).slice(0, 2000), at: `${{d.sourceId}}:${{d.line}}` }}));
  }});
  const send = wc.send.bind(wc);
  wc.send = (ch, ...args) => {{
    send(ch, ...args);
    if (ch !== "toast:cards") return;
    for (const c of args[0] || []) {{
      console.log("[slop] native notification", JSON.stringify({{ title: c.title, body: c.body }}));
      if (!String(c.body || "").includes({mark}) || clicked.has(c.id)) continue;
      clicked.add(c.id);
      setTimeout(() => wc.executeJavaScript(`[...document.querySelectorAll("#stack .card")]
        .find((el) => el.querySelector(".body").textContent.includes(${{JSON.stringify(c.body)}})).click()`, true)
        .catch((err) => console.log("[slop] toast click failed", err.message)), 1000);
    }}
  }};
}});
{fault}
require({main});
"""


async def desktop(ctx, account_id: str, fans: list[dict]) -> list[dict]:
    """Four entry points in the real Electron app; one check each (DESKTOP_CHECKS)."""
    if not ELECTRON.exists():
        for n in DESKTOP_CHECKS:
            ctx.skip(n, f"no Electron binary at {ELECTRON}")
        return []
    pick = distinct(fans)
    if len(pick) < 9:
        for n in DESKTOP_CHECKS:
            ctx.check(n, False, reason=f"{len(pick)} Fans with a name of their own, 9 needed")
        return []
    f1, f2, f3, f4 = pick[5:9]  # none the browser steps opened: each starts with no tab
    dms = _Dms(ctx, account_id, fan_dm.INJECT_ID_BASE + 778_000)
    out: list[dict] = []
    fault = FAULTS.get(ctx.fault or "")
    udata = tempfile.mkdtemp(prefix="slop-electron-userdata.")
    wrapper = ctx.out / "electron-wrapper.js"
    wrapper.write_text(WRAPPER.format(udata=json.dumps(udata), mark=json.dumps(NATIVE_CLICK),
                                      fault=(fault.desktop if fault and fault.desktop else ""),
                                      main=json.dumps(str(ROOT / "desktop/main.js"))))
    port = _port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELECTRON_")}
    env["OPENINFLOWW_URL"] = ctx.app
    log = open(ctx.out / "electron.log", "w")
    proc = subprocess.Popen([str(ELECTRON), str(wrapper), f"--remote-debugging-port={port}"], env=env,
                            cwd=str(ROOT / "desktop"), stdout=log, stderr=subprocess.STDOUT)
    ctx.metric("desktop_electron", {"pid": proc.pid, "userdata": udata, "cdp_port": port})
    try:
        async with async_playwright() as pw:
            b = None
            for _ in range(60):
                try:
                    b = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                    break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1)
            if b is None:
                for n in DESKTOP_CHECKS:
                    ctx.check(n, False, reason="Electron's CDP never came up")
                return out
            cdp = await b.new_browser_cdp_session()

            async def windows() -> int:
                # The app's windows: the toast window (a local file) comes and goes on its own.
                return sum(1 for t in (await cdp.send("Target.getTargets"))["targetInfos"]
                           if t["type"] == "page" and t["url"].startswith(ctx.app))

            async def page_where(pred, timeout_s=60):
                for _ in range(timeout_s * 4):
                    for p in [p for c in b.contexts for p in c.pages]:
                        if pred(p.url):
                            return p
                    await asyncio.sleep(0.25)
                return None

            _step("desktop setup")
            main = await page_where(lambda u: u.startswith(ctx.app))
            held: list = []
            routed: set = set()
            closing = False

            async def hold(r):
                path = urlsplit(r.request.url).path
                if path.startswith("/api/of/") or path in ui.OF_LIVE_PATHS:
                    held.append(r)  # as actors/ui: OF is not reachable from a slop run
                    if closing:
                        await r.abort()
                else:
                    await r.continue_()

            # As actors/ui's pages: focus on request, and the fault's page script.
            primed = "window.__slopPrimed = 1;\n" + FOCUS_JS + "\n" + (fault.browser if fault and fault.browser else "")

            async def prime(p):
                # A window opened before the init script reached it (Messages Pro) runs it now.
                if await p.evaluate("() => window.__slopPrimed === undefined"):
                    await p.evaluate(f"() => {{ {primed} }}")

            async def route(bctx):
                if id(bctx) not in routed:
                    routed.add(id(bctx))
                    await bctx.add_init_script(primed)
                    for p in bctx.pages:
                        await prime(p)
                    await bctx.route("**/*", hold)
                    await bctx.route("**/api/of/v2/users/notifications**", _feed(account_id, f3, "slop desktop: page row"))

            for c in b.contexts:
                await route(c)
            pcdp = await main.context.new_cdp_session(main)
            for ck in ctx.owner.c.cookies.jar:
                await pcdp.send("Network.setCookie", {"name": ck.name, "value": ck.value, "url": ctx.app + "/"})
            await main.evaluate(f"() => {{ {SETTINGS_JS} }}")
            await main.goto(f"{ctx.app}/", wait_until="domcontentloaded")
            await main.get_by_role("button", name="Notifications").first.wait_for(timeout=120_000)
            await main.locator("a[href='/messages-pro']").first.click()
            mp = await page_where(lambda u: "/messages-pro" in u, 60)
            await route(mp.context)
            await prime(mp)
            await mp.get_by_role("button", name="Notifications").first.wait_for(timeout=120_000)
            ctx.metric("desktop_windows_with_messages_pro", await windows())

            await main.bring_to_front()
            _step("nc-d1-main-toast arrival")
            toast, tries = await dms.toast(main, f1, "slop desktop click: main toast")
            out.append(await _click(ctx, "desktop", DESKTOP_ENTRIES[0], toast, tries, main, mp, f1, windows,
                                    "nc-d1-main-toast"))

            await mp.bring_to_front()
            _step("nc-d2-mp-toast arrival")
            toast, tries = await dms.toast(mp, f2, "slop desktop click: Messages Pro toast")
            out.append(await _click(ctx, "desktop", DESKTOP_ENTRIES[1], toast, tries, mp, mp, f2, windows,
                                    "nc-d2-mp-toast"))

            await main.bring_to_front()
            _step("nc-d3-bell-row arrival")
            await dms.toast(main, f4, "slop desktop click: bell row")
            await main.get_by_role("button", name="Notifications").first.click()
            row = main.locator(f'a[href*="/{f4["id"]}?"]:not(.animate-toast-in)').first
            out.append(await _click(ctx, "desktop", DESKTOP_ENTRIES[2], row, 1, main, mp, f4, windows,
                                    "nc-d3-bell-row", wait=True))
            await main.keyboard.press("Escape")

            # The native notification: raised by a window without focus, clicked "by the OS" (the wrapper).
            await mp.bring_to_front()
            await main.evaluate("() => { window.__slopBlur = true; }")
            entry = DESKTOP_ENTRIES[3]
            await _arm(mp)  # the wrapper clicks the card about a second after it shows
            trigger_png = await ui.shot(ctx, main, "nc-d4-native-notification-trigger")
            before, url, known = await windows(), main.url, _pages(main)

            def raised() -> int:
                log.flush()
                return sum(1 for ln in (ctx.out / "electron.log").read_text().splitlines()
                           if ln.startswith("[slop] native notification") and NATIVE_CLICK in ln)

            tries = 0
            _step("nc-d4-native-notification arrival+click")  # the wrapper clicks a second after it shows
            for tries in range(1, 4):
                await dms.send(f3, f"{NATIVE_CLICK} {tries}")
                for _ in range(30):
                    if raised():
                        break
                    await asyncio.sleep(0.5)
                if raised():
                    break
            if not raised():
                diag = await main.evaluate("""() => ({ hasFocus: document.hasFocus(), blur: window.__slopBlur,
                  shellNotify: typeof (window.fasttShell || {}).notify,
                  osPing: JSON.parse(localStorage.getItem('chatterly:notif-settings:v1') || '{}').osPing })""")
                log.flush()
                ipc = [ln for ln in (ctx.out / "electron.log").read_text().splitlines() if ln.startswith("[slop] shell:notify")]
                ctx.check(check_name("desktop", entry), False, reason="no native notification was raised", tries=tries,
                          main=diag, shell_notify_calls=ipc[-5:])
            else:
                out.append(await _judge(ctx, "desktop", entry, mp=mp, fan=f3, trigger=main, trigger_url=url,
                                        windows_before=before, pages_before=known, windows=windows, slug="nc-d4-native-notification",
                                        extra={"trigger_png": trigger_png, "dm_tries": tries,
                                               "native_raised": raised()}))
            # A held read let go on disconnect would reach the relay's OF client (a 500 and a Traceback).
            closing = True
            for r in held:
                try:
                    await r.abort()
                except Exception:  # noqa: BLE001  (its page is gone)
                    pass
            await b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        shutil.rmtree(udata, ignore_errors=True)
        con = _Console(ctx, "desktop")
        for ln in (ctx.out / "electron.log").read_text().splitlines():
            if ln.startswith("[slop] console "):
                row = json.loads(ln[len("[slop] console "):])
                con.write(row, row.pop("t"))
    return out
