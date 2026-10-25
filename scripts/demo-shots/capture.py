"""Capture the marketing-site product shots (run through run.sh, which starts the stack).

    run.sh                       every screen
    run.sh --only dashboard,login
    run.sh --keep-png            also keep the raw 2x PNGs in .scratch/demo-shots/png/

Registers a throwaway owner, seeds the demo agency (dataset.py -> seed.py), then
for every screen opens the route on a 1280x800 and a 390x844 viewport (device
scale 2), waits for the page's own data to be on screen (and fails the screen if
a loading skeleton or a forbidden empty figure is still visible), screenshots,
and writes WebP files into web/public/img/ (see web/public/img/README.md).

Nothing leaves the machine: the router fulfils assets from scripts/demo-shots/assets,
answers OnlyFans reads from fixtures.py, passes /admin, /auth and /events to the
temp relay, and aborts every other origin; Chromium resolves no name but localhost.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dataset  # noqa: E402
from fixtures import AssetRef, Fixtures  # noqa: E402
from screens import SCREENS  # noqa: E402
from seed import Api, seed  # noqa: E402

ROOT = Path(os.environ["DEMO_SHOTS_ROOT"])
TMP = Path(os.environ["DEMO_SHOTS_TMP"])
APP = os.environ["DEMO_SHOTS_APP"]
RELAY = os.environ["DEMO_SHOTS_RELAY"]
OUT = ROOT / "web/public/img"
PNG = TMP / "png"
ASSETS = HERE / "assets"
MAGICK, CWEBP = shutil.which("magick"), shutil.which("cwebp")

DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
LAUNCH_ARGS = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"]
RELAY_PREFIXES = ("/admin", "/api", "/auth", "/chatter", "/img", "/events", "/ws", "/health")
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
ASSET_HOST = urlsplit(dataset.ASSET_ORIGIN).hostname
PASSWORD = "demo-shots-throwaway"

# Light theme; hide the cursor, the caret and Next's dev indicator.
INIT_JS = """
try { localStorage.setItem('chatterly:theme', 'light');
  localStorage.setItem('chatterly:lockedText-default-changed-seen', '1');
  localStorage.setItem('vaultProOnboarding', JSON.stringify({batchUploadEntry: '1', uploadPageStep: '1'})); } catch (e) {}
(() => {
  const css = `nextjs-portal, [data-nextjs-toast], [data-next-badge-root],
    [aria-label="Help assistant"], .tsqd-open-btn-container, .tsqd-parent-container { display: none !important; }
    * { cursor: none !important; caret-color: transparent !important; }
    *, *::before, *::after { animation-duration: 0s !important; transition-duration: 0s !important; }`;
  const add = () => { const s = document.createElement('style'); s.textContent = css; document.documentElement.appendChild(s); };
  if (document.documentElement) add(); else document.addEventListener('DOMContentLoaded', add);
})();
"""


def relay_bound(p: str) -> bool:
    return any(p == x or p.startswith(x + "/") for x in RELAY_PREFIXES)


def asset_file(url: str) -> Path | None:
    u = urlsplit(url)
    if u.hostname != ASSET_HOST:
        return None
    f = (ASSETS / u.path.lstrip("/")).resolve()
    return f if f.is_file() and ASSETS in f.parents else None


class Router:
    def __init__(self, fx: Fixtures):
        self.fx = fx
        self.unmatched: list[str] = []
        self.offhost: list[str] = []

    def _file(self, route, f: Path | None):
        if f is None:
            return route.fulfill(status=404, body="")
        return route.fulfill(status=200, body=f.read_bytes(), content_type="image/jpeg",
                             headers={"cache-control": "max-age=3600"})

    def handle(self, route, request):
        u = urlsplit(request.url)
        if u.scheme in ("data", "blob"):
            return route.continue_()
        if u.hostname == ASSET_HOST:
            return self._file(route, asset_file(request.url))
        if u.hostname in FONT_HOSTS:
            return route.fulfill(status=200, body="", content_type="text/css")
        if f"{u.scheme}://{u.netloc}" not in (APP, RELAY):
            self.offhost.append(request.url)
            return route.abort()
        p = u.path
        if not relay_bound(p):
            return route.continue_()
        q = parse_qs(u.query)
        if p == "/img" or p.startswith("/img/"):
            return self._file(route, asset_file((q.get("u") or [""])[0]))
        if p in ("/auth/me", "/chatter/me"):
            # The trial badge, banner and expired nag all key off created_at; a null hides all three.
            res = route.fetch()
            body = res.json() if res.ok else None
            if isinstance(body, dict):
                body["created_at"] = None
            return route.fulfill(response=res, body=json.dumps(body))
        if p == "/events" or p.startswith("/ws"):
            return route.abort() if p.startswith("/ws") else route.continue_()
        account = request.headers.get("x-account-id")
        body = self.fx.answer(request.method, p, q, account)
        if isinstance(body, AssetRef):
            return self._file(route, asset_file(body))
        if body is not None:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        if p.startswith("/api/"):
            self.unmatched.append(f"{request.method} {p}{'?' + u.query if u.query else ''}")
            return route.fulfill(status=200, content_type="application/json", body="{}")
        return route.continue_()

    def ws(self, ws):
        u = urlsplit(ws.url)
        if f"{'https' if u.scheme == 'wss' else 'http'}://{u.netloc}" in (APP, RELAY) and not relay_bound(u.path):
            ws.connect_to_server()


def new_context(browser, router: Router, viewport: dict, state: dict | None, now):
    # Every shot is 2560 px wide: a wider viewport (screens' desktop_viewport) gets a lower device scale.
    scale = 2 if viewport["width"] <= DESKTOP["width"] else 2 * DESKTOP["width"] / viewport["width"]
    ctx = browser.new_context(viewport=viewport, device_scale_factor=scale, service_workers="block",
                              storage_state=state, timezone_id="UTC", locale="en-US", color_scheme="light")
    ctx.clock.install(time=now)  # the dataset's `now`; time then runs normally
    ctx.add_init_script(INIT_JS)
    ctx.route("**/*", router.handle)
    ctx.route_web_socket("**/*", router.ws)
    return ctx


def settle(page, screen: dict, kind: str) -> list[str]:
    """Wait for the screen's data; return the problems still visible (empty = ready)."""
    try:
        page.wait_for_load_state("networkidle", timeout=60_000)
    except Exception:  # noqa: BLE001  (an open stream can keep the network busy; the text checks decide)
        pass
    problems = []
    for text in screen.get(f"{kind}_wait", screen.get("wait", [])):
        loc = (page.get_by_placeholder(text[12:], exact=False) if text.startswith("placeholder=")
               else page.get_by_text(text, exact=False)).filter(visible=True).first
        try:
            loc.wait_for(state="visible", timeout=45_000)
        except Exception:  # noqa: BLE001
            problems.append(f"missing text {text!r}")
    for text in screen.get("frame_wait", []):  # OF Manager's mirror renders inside an iframe
        loc = page.frame_locator("iframe").first.get_by_text(text, exact=False).first
        try:
            loc.wait_for(state="visible", timeout=45_000)
        except Exception:  # noqa: BLE001
            problems.append(f"missing text in frame {text!r}")
    page.wait_for_timeout(screen.get("pause", 1200))
    vp = page.viewport_size
    skeletons = page.evaluate("""(vp) => [...document.querySelectorAll('.animate-pulse, [aria-busy="true"]')]
        .filter(e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
          return r.width > 4 && r.height > 4 && r.bottom > 0 && r.top < vp.height && s.visibility !== 'hidden'
            && s.display !== 'none' && r.right > 0 && r.left < vp.width; }).length""", vp)
    if skeletons:
        problems.append(f"{skeletons} loading skeleton(s) visible")
    for bad in screen.get("forbid", ["$0.00", "No creators", "Loading…"]):
        # Polled for up to 30 s: a read still in flight (a chart's "Loading…") clears by itself; data that is
        # really missing ("$0.00", "No creators") stays and fails the shot.
        for waited in range(0, 30_001, 500):
            n = page.evaluate("""([t, vp]) => { let n = 0; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (w.nextNode()) { const el = w.currentNode.parentElement; if (!el || !w.currentNode.data.includes(t)) continue;
                  const r = el.getBoundingClientRect(); if (r.width && r.height && r.bottom > 0 && r.top < vp.height
                    && getComputedStyle(el).visibility !== 'hidden') n++; } return n; }""", [bad, vp])
            if not n:
                if waited:
                    page.wait_for_timeout(800)  # let the chart that just got its data draw
                break
            page.wait_for_timeout(500)
        if n:
            problems.append(f"{n} visible {bad!r}")
    want = screen.get(f"{kind}_min_bubbles", screen.get("min_bubbles"))
    if want:  # Messages Pro bubbles wholly inside the thread's scroll box and the viewport
        n = page.evaluate("""(vp) => [...document.querySelectorAll('[data-msg-id]')].filter(e => {
            let p = e.parentElement;
            while (p && !/(auto|scroll)/.test(getComputedStyle(p).overflowY)) p = p.parentElement;
            const r = e.getBoundingClientRect(), b = p ? p.getBoundingClientRect() : {top: 0, bottom: vp.height};
            return r.height > 0 && r.top >= Math.max(b.top, 0) - 1 && r.bottom <= Math.min(b.bottom, vp.height) + 1;
          }).length""", vp)
        if n < want:
            problems.append(f"{n} bubbles in view, want {want}")
    problems += font_problems(page)
    money = page.evaluate(MONEY_JS, bool(screen.get("prices")))
    if money:
        problems.append(f"money off the house format: {money}")
    return problems


FONT_JS = """async () => {
    const unq = s => s.trim().replace(/^["']|["']$/g, "");
    await document.fonts.ready;
    // next/font renames the family (to the layout's const, "ui", or `__Instrument_Sans_<hash>` with
    // next/font/google) and publishes it as --font-ui; the face behind it must load and lead body's stack.
    const fam = unq(getComputedStyle(document.documentElement).getPropertyValue("--font-ui").split(",")[0] || "");
    const body = getComputedStyle(document.body).fontFamily;
    let faces = [];
    if (fam) try { faces = (await document.fonts.load(`16px "${fam}"`)).filter(f => f.status === "loaded").map(f => unq(f.family)); } catch {}
    // A visible text element that uses the family, for the platform-font check (CDP) in font_problems.
    document.querySelectorAll("[data-font-probe]").forEach(e => e.removeAttribute("data-font-probe"));
    const probe = fam && [...document.body.querySelectorAll("h1, h2, h3, p, span, button, td, label")].find(e => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && /[A-Za-z]/.test(e.textContent || "")
            && [...e.childNodes].some(n => n.nodeType === 3 && /[A-Za-z]/.test(n.textContent))
            && unq(getComputedStyle(e).fontFamily.split(",")[0]) === fam;
    });
    if (probe) probe.setAttribute("data-font-probe", "1");
    // Visible text set in another family: an inline font-family left over from an older face (Creator reports kept
    // "Inter, -apple-system" after the app moved to Instrument Sans, so it painted the system face), or /login
    // (`data-look="site"`) on the site's system stack. Monospace is on purpose (Infloww's "Suisse Int'l Mono" figures).
    const off = !fam ? [] : [...document.body.querySelectorAll("*")].filter(e => {
        const r = e.getBoundingClientRect();
        if (!(r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight)) return false;
        if (![...e.childNodes].some(n => n.nodeType === 3 && /[A-Za-z0-9]/.test(n.textContent))) return false;
        const first = unq(getComputedStyle(e).fontFamily.split(",")[0]);
        return first !== fam && !/mono/i.test(first);
    }).slice(0, 3).map(e => `${unq(getComputedStyle(e).fontFamily.split(",")[0])}: ${(e.textContent || "").trim().slice(0, 30)}`);
    return {fam, faces, body, probe: !!probe, off, ok: !!fam && faces.includes(fam) && unq(body.split(",")[0]) === fam};
}"""

# A visible money figure printed off the house formats (lib/format.ts): "$" then a space ("$ 10.00", the bundle's script
# price), four or more digits with no comma ("$11134.68", "$1338"), or $1,000+ with cents ("$28,507.24"). Aggregates
# are whole dollars with commas from $1,000 (the dashboard's "$1,005,875"); a unit price under $1,000 keeps its
# cents ("$9.99"). A fan's or OnlyFans' own text under $1,000 ("I sent you a $50.00 tip") passes.
# The house money format, as on the dashboard: whole dollars with en-US commas ("$1,005,875", "$86"),
# or "$11.1k" on the fan-list badge. Cents only on a real non-round unit price or average ("$19.99", an LTV
# "$86.42"), and only on screens flagged `prices` in screens.py; never "$N.00", "$ 10" or "$11134". Chat bubbles
# ([data-msg-id]) are what the fan or creator typed ("I sent you a $50.00 tip") and are skipped.
MONEY_JS = r"""(prices) => {
    const tok = /\$(\s*)([\d,]+)(?:\.(\d+))?([kKmM])?/g;
    const out = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode()) && out.length < 5;) {
        const el = n.parentElement;
        if (!el || !n.textContent.includes("$") || el.closest("[data-msg-id]")) continue;
        const r = el.getBoundingClientRect();
        if (!(r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight)) continue;
        for (const [t, space, int, dec, unit] of n.textContent.matchAll(tok)) {
            const bad = space || (!int.includes(",") && int.length >= 4)
                || (dec !== undefined && !unit && (dec === "00" || !prices || dec.length !== 2));
            if (bad) { out.push(t.trim()); break; }
        }
    }
    return out;
}"""


def font_problems(page) -> list[str]:
    """The app font must have rendered: next/font's family for Instrument Sans (app/app/fonts/, --font-ui)
    has a loaded FontFace and leads body's font-family, and a visible text node that uses it is painted
    by Chromium in "Instrument Sans" (CSS.getPlatformFontsForNode), not a fallback. Pages styled with
    the system stack on purpose (the dark /login, `data-look="site"`) have no such node and skip the
    paint check."""
    f = page.evaluate(FONT_JS)
    if not f["ok"]:
        return [f"font: --font-ui family {f['fam']!r}, loaded faces {f['faces']}, body font-family {f['body'][:100]!r}"]
    if f["off"]:
        return [f"font: text not in the app font: {f['off']}"]
    if not f["probe"]:
        return []
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("DOM.enable")
        cdp.send("CSS.enable")
        root = cdp.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]
        node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": "[data-font-probe]"})["nodeId"]
        painted = [x["familyName"] for x in cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]]
    finally:
        page.evaluate("document.querySelectorAll('[data-font-probe]').forEach(e => e.removeAttribute('data-font-probe'))")
        cdp.detach()
    if "Instrument Sans" not in painted:
        return [f"font: text painted in {painted}, not Instrument Sans"]
    return []


def shoot(ctx, screen: dict, kind: str, d: dataset.Dataset) -> tuple[Path | None, list[str]]:
    route = screen.get(f"{kind}_path") or screen["path"]
    route = route(d) if callable(route) else route
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    try:
        page.goto(APP + route, wait_until="domcontentloaded", timeout=180_000)
        act = screen.get(f"{kind}_act") or screen.get("act")
        problems = []
        if act:
            settle(page, {"wait": screen.get(f"{kind}_pre_wait", screen.get("pre_wait", [])), "forbid": []}, kind)
            try:
                act(page, kind)
            except Exception as e:  # noqa: BLE001  (reported; the shot is kept for debugging)
                problems.append(f"act failed: {str(e).splitlines()[0][:160]}")
        problems += settle(page, screen, kind)
        page.mouse.move(-10, -10)
        key = screen.get("key")
        if kind == "desktop" and key:  # the figure the combo's phone must not cover (CSS px of the desktop viewport)
            # A text key is its first visible match (a headline figure), a css key its last (the newest bubble).
            loc = (page.locator(key[4:]).filter(visible=True).last if key.startswith("css=")
                   else page.get_by_text(key, exact=False).filter(visible=True).first)
            box = loc.bounding_box()
            (PNG / f"{screen['slug']}-desktop.key.json").write_text(
                json.dumps(box and {**box, "vw": page.viewport_size["width"]}))
            if not box:
                problems.append(f"key {key!r} has no box")
        if os.environ.get("DEMO_SHOTS_PROBE"):  # debugging aid: print a JS expression's value per shot
            print(f"  probe {screen['slug']} {kind}: {page.evaluate(os.environ['DEMO_SHOTS_PROBE'])}")
        path = PNG / f"{screen['slug']}-{kind}.png"
        page.screenshot(path=str(path))
        return path, problems + [f"page error: {e}" for e in errors if "ResizeObserver" not in e]
    finally:
        page.close()


# ── compose and encode ────────────────────────────────────────────────────────
def magick(*args: str) -> None:
    subprocess.run([MAGICK, *args], check=True)


def webp(src: Path, dst: Path, size: str | None = None) -> None:
    tmp = src
    if size:
        tmp = src.with_name(f"{src.stem}-{size}.png")
        magick(str(src), "-filter", "Lanczos", "-resize", f"{size}!", str(tmp))
    subprocess.run([CWEBP, "-quiet", "-q", "80", "-m", "6", "-sharp_yuv", str(tmp), "-o", str(dst)], check=True)


def page_bg(png: Path) -> str:
    out = subprocess.run([MAGICK, str(png), "-format", "%[pixel:p{4,1590}]", "info:"], check=True,
                         capture_output=True, text=True).stdout.strip()
    return out or "white"


def phone_spot(desktop: Path, W: int, H: int, pw: int, ph: int, margin: int) -> tuple[int, int]:
    """Bottom-right, unless the phone would cover the shot's key figure (`<slug>-desktop.key.json`, written by
    shoot): then lower, bleeding up to 40% of the phone off the bottom edge, then bottom-left."""
    keyf = desktop.with_name(desktop.stem + ".key.json")
    box = json.loads(keyf.read_text()) if keyf.exists() else None
    x, y = W - pw - margin, H - ph - margin
    if not box:
        return x, y
    k = W / box["vw"]
    pad = 12 * k
    kx0, ky0 = box["x"] * k - pad, box["y"] * k - pad
    kx1, ky1 = (box["x"] + box["width"]) * k + pad, (box["y"] + box["height"]) * k + pad
    clear = lambda px, py: px >= kx1 or px + pw <= kx0 or py >= ky1 or py + ph <= ky0  # noqa: E731
    for yy in range(y, H - int(ph * 0.6) + 1, 8):
        if clear(x, yy):
            if yy != y:
                print(f"    combo {desktop.stem}: phone lowered {(yy - y) // 2}px to clear the key figure")
            return x, yy
    if clear(margin, y):
        print(f"    combo {desktop.stem}: phone moved bottom-left to clear the key figure")
        return margin, y
    print(f"    combo {desktop.stem}: WARNING the phone covers the key figure")
    return x, y


def compose(desktop: Path, phone: Path, dst: Path) -> None:
    """1440x900 @2x: the desktop shot fills the canvas, the phone sits over the bottom-right
    (~24% of the width) in a 5px dark ring with rounded corners and a soft shadow."""
    W, H, S = 2880, 1800, 2
    pw = int(W * 0.24)
    ph = round(pw * 844 / 390)
    ring, radius, margin = 5 * S, 28 * S, 36 * S
    bg = page_bg(desktop)
    work = PNG
    d2 = work / f"{dst.stem}-d.png"
    magick(str(desktop), "-filter", "Lanczos", "-resize", f"{W}x{H}!", str(d2))
    inner_w, inner_h = pw - 2 * ring, ph - 2 * ring
    p2 = work / f"{dst.stem}-p.png"
    magick(str(phone), "-filter", "Lanczos", "-resize", f"{inner_w}x{inner_h}!",
           "(", "-size", f"{inner_w}x{inner_h}", "xc:none", "-fill", "white", "-draw",
           f"roundrectangle 0,0 {inner_w - 1},{inner_h - 1} {radius - ring},{radius - ring}", ")",
           "-alpha", "set", "-compose", "DstIn", "-composite", str(p2))
    framed = work / f"{dst.stem}-f.png"
    magick("-size", f"{pw}x{ph}", "xc:none", "-fill", "#16171b", "-draw",
           f"roundrectangle 0,0 {pw - 1},{ph - 1} {radius},{radius}", str(p2), "-geometry", f"+{ring}+{ring}",
           "-compose", "over", "-composite",
           "(", "+clone", "-background", "black", "-shadow", f"38x{18 * S}+0+{10 * S}", ")",
           "+swap", "-background", "none", "-layers", "merge", "+repage", str(framed))
    x, y = phone_spot(desktop, W, H, pw, ph, margin)
    big = work / f"{dst.stem}-c.png"
    shadow_pad = 18 * S * 2 - 10 * S  # -shadow grows the canvas by 2*sigma on each side, offset moves it
    magick("-size", f"{W}x{H}", f"xc:{bg}", str(d2), "-composite", str(framed), "-geometry",
           f"+{x - 18 * S * 2}+{y - 18 * S * 2 + 0 * shadow_pad}", "-composite", "-flatten", str(big))
    webp(big, dst, "1440x900")
    webp(big, dst.with_name(dst.stem + "-720.webp"), "720x450")


def encode(slug: str, desktop: Path | None, phone: Path | None) -> list[Path]:
    out = []
    if desktop:
        for name, size in ((f"{slug}.webp", "1280x800"), (f"{slug}-640.webp", "640x400")):
            webp(desktop, OUT / name, size)
            out.append(OUT / name)
    if phone:
        for name, size in ((f"{slug}-phone.webp", "390x844"), (f"{slug}-phone-780.webp", "780x1688")):
            webp(phone, OUT / name, size)
            out.append(OUT / name)
    if desktop and phone:
        compose(desktop, phone, OUT / f"{slug}-combo.webp")
        out += [OUT / f"{slug}-combo.webp", OUT / f"{slug}-combo-720.webp"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--keep-png", action="store_true")
    ap.add_argument("--no-encode", action="store_true")
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s}
    PNG.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    d = dataset.build()
    fx = Fixtures(d)
    router = Router(fx)
    report: dict = {"now": dataset.iso(d.now), "screens": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=LAUNCH_ARGS)
        boot = browser.new_context()
        r = boot.request.post(f"{APP}/auth/register", data={"username": dataset.OWNER_USERNAME, "password": PASSWORD})
        if not r.ok:
            print(f"demo-shots: register -> {r.status} {r.text()[:200]}")
            return 1
        user_id = r.json()["user_id"]
        emp = seed(d, db=TMP / "relay.db", sessions=TMP / "sessions", user_id=user_id, api=Api(boot.request, APP))
        state = boot.storage_state()
        boot.close()
        print(f"demo-shots: seeded in {time.time() - t0:.0f}s ({len(d.transactions)} sales, {len(d.messages)} messages, "
              f"{len(emp)} employees)")
        # The manager (an Employee login with Shifts) for screens with session "manager": an owner has no shifts.
        mgr = browser.new_context()
        r = mgr.request.post(f"{APP}/chatter/login",
                             data={"username": d.employees[dataset.MANAGER]["username"], "password": PASSWORD})
        if not r.ok:
            print(f"demo-shots: manager sign-in -> {r.status} {r.text()[:200]}")
            return 1
        mstate = mgr.storage_state()
        mgr.close()
        states = {"owner": state, "manager": mstate, "anon": None}
        pool: dict = {}

        def context_for(screen: dict, kind: str):
            who = "anon" if screen.get("anon") else screen.get("session", "owner")
            vp = screen.get("desktop_viewport", DESKTOP) if kind == "desktop" else PHONE
            k = (who, kind, vp["width"], vp["height"])
            if k not in pool:
                pool[k] = new_context(browser, router, vp, states[who], d.now)
            return pool[k]
        failed = False
        for screen in SCREENS:
            slug = screen["slug"]
            if only and slug not in only:
                continue
            shots, notes = {}, {}
            for kind in ("desktop", "phone"):
                if kind in screen.get("skip", ()):
                    continue
                ctx = context_for(screen, kind)
                path, problems = shoot(ctx, screen, kind, d)
                shots[kind], notes[kind] = path, problems
                print(f"  {slug} {kind}: {'OK' if not problems else 'FAIL ' + '; '.join(problems)}")
            ok = all(not p for p in notes.values())
            files = []
            if ok and not args.no_encode:
                files = [str(f.relative_to(ROOT)) for f in encode(slug, shots.get("desktop"), shots.get("phone"))]
            failed |= not ok
            report["screens"][slug] = {"ok": ok, "problems": notes, "files": files}
        browser.close()
    report["unmatched"] = sorted(set(router.unmatched))
    report["offhost"] = sorted(set(router.offhost))
    (TMP / "report.json").write_text(json.dumps(report, indent=2))
    if args.keep_png:
        keep = ROOT / ".scratch/demo-shots/png"
        keep.mkdir(parents=True, exist_ok=True)
        for f in PNG.glob("*.png"):
            if f.stem.endswith(("-desktop", "-phone")):
                shutil.copy(f, keep / f.name)
    print(f"demo-shots: unmatched OF reads: {len(report['unmatched'])}; off-host requests aborted: "
          f"{len(report['offhost'])}")
    for u in report["unmatched"][:40]:
        print(f"    unmatched {u}")
    print(f"demo-shots: done in {time.time() - t0:.0f}s, {'with failures' if failed else 'all screens OK'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
