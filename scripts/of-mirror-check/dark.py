"""OF's dark mode in the mirror follows our theme (app/lib/ofMirrorTheme.ts).

For each theme (`chatterly:theme` in localStorage, as useTheme persists it) opens home,
messages/chat, settings/fans and settings/display and checks the frame's <html> has
`m-mode-dark` exactly when ours is dark, with OF's body background to match, and had it
already when the parser finished (readyState "interactive") and at DOMContentLoaded, before
any load event, where only the generator's boot script can have set it (no light first paint);
then, on display, OF's "Dark mode" switch flips our theme and the frame with it.
Live first-paint proof, in dark: a CDP screencast (every frame) runs from navigation start until
the mirror frame has loaded, for each page; every frame after the <iframe> element exists must have
a mean luminance under 0.4 inside the frame's box (Pillow decodes the PNGs; without it, a canvas
in a throwaway page does). And over the whole viewport (our dark grey chrome included), for every
frame from navigation start: each frame's mean luminance must be at most the page's steady state
(a screenshot once loaded) + 0.1, and under 0.4.
Screenshots: /tmp/of-mirror-shots/{dark,light}-<page>.png. Exit 1 on a failed check.
"""
import base64, io, json, os, sys
from playwright.sync_api import sync_playwright
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
SHOTS="/tmp/of-mirror-shots"
os.makedirs(SHOTS, exist_ok=True)
user={"user_id":"u1","username":"tester","is_admin":False}
PAGES={"home":"home/index","chat":"messages/chat","fans":"settings/fans","display":"settings/display"}
PATHS={"home":"/of-manager/home","chat":"/of-manager/messages/chat","fans":"/of-manager/settings/fans","display":"/of-manager/settings/display"}
failures=[]
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: failures.append(f"{label}: got {got!r}, expected {want!r}")
def mock(route):
    u=route.request.url
    if "/auth/me" in u: body=json.dumps(user)
    elif "/admin/employees" in u: body=json.dumps({"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]})
    elif u.split("?")[0].endswith("/admin/accounts"): body='{"accounts":[{"id":"acc1","nickname":"Model One","has_session":true},{"id":"1","nickname":"Model Two","has_session":true}],"active_account_id":null}'  # creators: none shows OfNotHaveModel
    elif "/chatter/me/accounts" in u: body="[]"
    elif "/chatter/me" in u: body="null"
    else: body="[]"
    route.fulfill(status=200, content_type="application/json", body=body)
# In every frame: the <html> class when the parser finishes (readyState "interactive", before DOMContentLoaded
# and load) and at DOMContentLoaded. Window-level capture listeners, because an iframe's real page reuses the
# window of its initial about:blank, where alone Playwright runs the init script.
BOOT="""
const rec = (e) => {
  if (location.href === 'about:blank') return;
  if (e.type === 'DOMContentLoaded') window.__ofBootClass = document.documentElement.className;
  else if (document.readyState === 'interactive') window.__ofInteractiveClass = document.documentElement.className;
};
addEventListener('readystatechange', rec, true);
addEventListener('DOMContentLoaded', rec, true);
"""
# In the app page: when (epoch ms, as the screencast's timestamps) the mirror <iframe> element first exists.
IFRAME_SEEN="""
if (window.top === window) new MutationObserver((_, o) => {
  if (!document.querySelector('iframe[src*="/of-mirror/"]')) return;
  window.__ofIframeAt = performance.timeOrigin + performance.now(); o.disconnect();
}).observe(document, {childList: true, subtree: true});
"""
LIGHT=0.4
FLASH=0.1  # full viewport: allowed rise over the loaded page's luminance
try:
    from PIL import Image, ImageStat
except ImportError:
    Image=None
def luminance(data, box, scratch):
    """Mean luminance (0-1, Rec. 709 weights on sRGB) of the box (x, y, w, h, in image pixels; None: all) of a base64 PNG."""
    x,y,w,h=box or (0,0,None,None)
    if Image:
        img=Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
        if box: img=img.crop((x,y,x+w,y+h))
        r,g,b=ImageStat.Stat(img).mean
        return (0.2126*r+0.7152*g+0.0722*b)/255
    return scratch.evaluate("""async ([data, x, y, w, h]) => {
      const img = new Image(); img.src = 'data:image/png;base64,' + data; await img.decode();
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const g = c.getContext('2d'); g.drawImage(img, 0, 0);
      const d = g.getImageData(x, y, w ?? img.width, h ?? img.height).data; let s = 0;
      for (let i = 0; i < d.length; i += 4) s += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
      return s / (d.length / 4) / 255;
    }""", [data,x,y,w,h])
def first_paint(pg, ctx, key, page):
    """Screencast every frame of a navigation to PATHS[key] until the mirror frame has loaded; check the frame's box stays dark."""
    cdp=ctx.new_cdp_session(pg); frames=[]
    def on_frame(ev):
        frames.append(ev); cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
    cdp.on("Page.screencastFrame", on_frame)
    cdp.send("Page.startScreencast", {"format":"png","everyNthFrame":1})
    pg.goto(f"{BASE}{PATHS[key]}", wait_until="load", timeout=90000)
    pg.wait_for_function("p => [...document.querySelectorAll('iframe')].some(f => f.src.endsWith(p) && f.contentDocument?.readyState === 'complete')", arg=f"/of-mirror/pages/{page}.html", timeout=30000)
    pg.wait_for_timeout(300)
    cdp.send("Page.stopScreencast"); pg.wait_for_timeout(200); cdp.detach()
    pg.wait_for_timeout(1000)
    steady_shot=base64.b64encode(pg.screenshot()).decode()
    check(f"dark {key}: our theme dark during the screencast", pg.evaluate("document.documentElement.getAttribute('data-theme') !== 'light'"), True)
    seen=pg.evaluate("window.__ofIframeAt")
    bb=pg.locator(f"iframe[src$='/of-mirror/pages/{page}.html']").bounding_box()
    scratch=None if Image else ctx.new_page()
    steady=luminance(steady_shot, None, scratch)
    full=[luminance(ev["data"], None, scratch) for ev in frames]
    lums=[]
    for ev in frames:
        m=ev["metadata"]
        if seen is None or m["timestamp"]*1000 < seen: continue
        w=m["deviceWidth"]; img_w=Image.open(io.BytesIO(base64.b64decode(ev["data"]))).width if Image else scratch.evaluate("async d => { const i = new Image(); i.src = 'data:image/png;base64,' + d; await i.decode(); return i.width }", ev["data"])
        k=img_w/w
        box=(round(bb["x"]*k), round((bb["y"]+m.get("offsetTop",0))*k), max(1,round(bb["width"]*k)), max(1,round(bb["height"]*k)))
        lums.append(luminance(ev["data"], box, scratch))
    if scratch: scratch.close()
    print(json.dumps({"first paint":key, "frames":len(frames), "checked":len(lums), "max luminance":round(max(lums),3) if lums else None, "decoder":"pillow" if Image else "canvas"}))
    print(json.dumps({"full viewport":key, "frames":len(full), "max luminance":round(max(full),3) if full else None, "steady state":round(steady,3)}))
    if not full: failures.append(f"dark {key}: no screencast frame")
    else:
        bad=[l for l in full if l>steady+FLASH or l>=LIGHT]
        if bad: failures.append(f"dark {key}: a light full-viewport frame during load (max {max(full):.3f}, steady state {steady:.3f}, {len(bad)} of {len(full)} frames over min({steady+FLASH:.3f}, {LIGHT}))")
    if not lums: failures.append(f"dark {key}: no screencast frame with the iframe ({len(frames)} frames)")
    elif max(lums)>=LIGHT: failures.append(f"dark {key}: a light frame in the mirror's box during load (max luminance {max(lums):.3f}, {sum(l>=LIGHT for l in lums)} of {len(lums)} frames)")
BOOT_STATE="({cls: window.__ofBootClass, early: window.__ofInteractiveClass})"
STATE="({dark: document.documentElement.classList.contains('m-mode-dark'), bg: getComputedStyle(document.body).backgroundColor})"
with sync_playwright() as p:
    b=p.chromium.launch()
    for theme in ["dark","light"]:
        ctx=b.new_context(viewport={"width":1440,"height":900})
        ctx.add_init_script(f"localStorage.setItem('chatterly:theme','{theme}')")
        ctx.add_init_script(BOOT)
        ctx.add_init_script(IFRAME_SEEN)
        pg=ctx.new_page()
        for pat in ["**/auth/**","**/chatter/**","**/admin/**","**/accounts**","**/api/**"]: pg.route(pat, mock)
        pg.route("**/events?**", lambda r: r.fulfill(status=200, content_type="text/event-stream", body=""))  # no Relay: an empty stream, not a 500
        first=True
        for key, page in PAGES.items():
            pg.goto(f"{BASE}{PATHS[key]}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
            if first:
                card=pg.get_by_text("Tim", exact=True)
                if card.count(): card.first.click(); pg.wait_for_timeout(3000)
                first=False
            fr=[f for f in pg.frames if f.url.endswith(f"/of-mirror/pages/{page}.html")]
            if not fr: failures.append(f"{theme} {key}: NO IFRAME (url {pg.url})"); continue
            st=fr[0].evaluate(STATE)
            check(f"{theme} {key}: m-mode-dark", st["dark"], theme=="dark")
            boot=fr[0].evaluate(BOOT_STATE)
            check(f"{theme} {key}: m-mode-dark at DOMContentLoaded", "m-mode-dark" in (boot["cls"] or "").split(), theme=="dark")
            check(f"{theme} {key}: m-mode-dark at readyState interactive", "m-mode-dark" in (boot["early"] or "").split(), theme=="dark")
            check(f"{theme} {key}: body background", st["bg"], "rgb(22, 22, 24)" if theme=="dark" else "rgb(255, 255, 255)")
            pg.screenshot(path=f"{SHOTS}/{theme}-{key}.png")
        # On display (the last page): OF's Dark mode switch sets our theme, and the frame follows.
        if fr:
            check(f"{theme} display: switch shows the theme", fr[0].evaluate("document.getElementById('dark_mode_switcher').checked"), theme=="dark")
            fr[0].locator("label[for='dark_mode_switcher']").click(); pg.wait_for_timeout(1000)
            flipped="light" if theme=="dark" else "dark"
            check(f"{theme} display: our theme after the switch", pg.evaluate("document.documentElement.getAttribute('data-theme')"), flipped)
            check(f"{theme} display: frame after the switch", fr[0].evaluate(STATE)["dark"], flipped=="dark")
            check(f"{theme} display: no read-only note", fr[0].evaluate("!!document.getElementById('oi-note')"), False)
        if theme=="dark":  # the init script sets our theme to dark again on every navigation
            # Reload first: the display switch above left the page light, and the screencast starts on it.
            pg.reload(wait_until="load", timeout=90000); pg.wait_for_timeout(2000)
            for key, page in PAGES.items(): first_paint(pg, ctx, key, page)
        ctx.close()
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("dark mode ok")
