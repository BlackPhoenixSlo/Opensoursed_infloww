import base64, io, json, os, sys
from urllib.parse import urlsplit
from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright
from mocks import BASE, Relay, mirror_frame, new_context, sign_in, watch
HERE=os.path.dirname(os.path.abspath(__file__)); REPO=os.path.dirname(os.path.dirname(HERE))
SHOTS=os.path.join(REPO,".scratch/fansly-mirror-check/dark")
os.makedirs(SHOTS, exist_ok=True)
FORCE_LIGHT="--force-light-paint" in sys.argv[1:]
PAGES={"/fansly-manager/home":"home/index","/fansly-manager/profile":"profile/index","/fansly-manager/messages/thread":"messages/thread","/fansly-manager/home/state-avatar-menu":"home/state-avatar-menu"}
MARKER="bright-theme"
LIGHT=0.4
FLASH=0.1
failures=[]
def fail(where, msg):
    failures.append(f"{where}: {msg}"); print("FAIL:", where, msg)
def check(label, got, want):
    print(json.dumps({"check":label,"want":want,"got":got}))
    if got!=want: fail(label, f"got {got!r}, expected {want!r}")
BOOT="<script>document.addEventListener('readystatechange', () => { if (document.readyState === 'interactive') window.__oiInteractiveClass = document.documentElement.className; });</script>"
def boot(route, entry):
    if not urlsplit(route.request.url).path.startswith("/fansly-mirror/pages/"): return False
    r=route.fetch(); html=r.text(); entry["boot"]=True
    if FORCE_LIGHT: html=html.replace('if(parent!==window)', 'if(false)', 1)
    route.fulfill(response=r, body=html.replace("<head>", "<head>"+BOOT, 1)); return True
IFRAME_SEEN="""if (window.top === window) new MutationObserver((_, o) => {
  if (!document.querySelector('iframe[src*="/fansly-mirror/"]')) return;
  window.__oiIframeAt = performance.timeOrigin + performance.now(); o.disconnect();
}).observe(document, {childList: true, subtree: true});"""
def luminance(data, box):
    img=Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
    if box: img=img.crop(box)
    r,g,b=ImageStat.Stat(img).mean
    return (0.2126*r+0.7152*g+0.0722*b)/255
def first_paint(pg, ctx, theme, path, key):
    cdp=ctx.new_cdp_session(pg); shots=[]
    def on_frame(ev): shots.append(ev); cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
    cdp.on("Page.screencastFrame", on_frame)
    cdp.send("Page.startScreencast", {"format":"png","everyNthFrame":1})
    pg.goto(f"{BASE}{path}?creator=fa1", wait_until="load", timeout=90000)
    fr=mirror_frame(pg, key); pg.wait_for_timeout(300)
    cdp.send("Page.stopScreencast"); pg.wait_for_timeout(200); cdp.detach()
    if not fr: fail(f"{theme} {key}", "no frame"); return None
    seen=pg.evaluate("window.__oiIframeAt"); bb=pg.locator(f"iframe[src='/fansly-mirror/pages/{key}.html']").bounding_box()
    lums=[]
    for ev in shots:
        m=ev["metadata"]
        if seen is None or m["timestamp"]*1000 < seen: continue
        k=Image.open(io.BytesIO(base64.b64decode(ev["data"]))).width/m["deviceWidth"]; top=bb["y"]+m.get("offsetTop",0)
        lums.append(luminance(ev["data"], (round(bb["x"]*k), round(top*k), round((bb["x"]+bb["width"])*k), round((top+bb["height"])*k))))
    pg.wait_for_timeout(1000)
    steady=luminance(base64.b64encode(pg.screenshot()).decode(), (round(bb["x"]), round(bb["y"]), round(bb["x"]+bb["width"]), round(bb["y"]+bb["height"])))
    print(json.dumps({"first paint":f"{theme} {key}","frames":len(shots),"in the frame's box":len(lums),"min":round(min(lums),3) if lums else None,"max":round(max(lums),3) if lums else None,"steady state":round(steady,3)}))
    if not lums: fail(f"{theme} {key}", f"no screencast frame with the iframe ({len(shots)} frames)")
    elif theme=="dark" and (bad:=[l for l in lums if l>=LIGHT or l>steady+FLASH]): fail(f"dark {key}", f"a light paint in the frame's box (max luminance {max(lums):.3f}, steady state {steady:.3f}, {len(bad)} of {len(lums)} frames)")
    elif theme=="light" and (bad:=[l for l in lums if l<steady-FLASH]): fail(f"light {key}", f"a dark paint in the frame's box (min luminance {min(lums):.3f}, steady state {steady:.3f}, {len(bad)} of {len(lums)} frames)")
    return fr
def marker(fr): return MARKER in fr.evaluate("document.documentElement.className").split()
with sync_playwright() as p:
    b=p.chromium.launch()
    for theme in ["dark","light"]:
        relay=Relay(fail); relay.extra=boot; ctx=new_context(b, relay, theme); ctx.add_init_script(IFRAME_SEEN)
        pg=ctx.new_page(); watch(pg, relay)
        sign_in(pg, "/fansly-manager/home?creator=fa1")
        for path, key in PAGES.items():
            relay.current=f"{theme} {key}"
            fr=first_paint(pg, ctx, theme, path, key)
            if not fr: continue
            check(f"{theme} {key}: {MARKER} on the frame", marker(fr), theme=="light")
            early=fr.evaluate("window.__oiInteractiveClass")
            check(f"{theme} {key}: {MARKER} at readyState interactive", MARKER in (early or "").split(), theme=="light")
            pg.screenshot(path=f"{SHOTS}/{theme}-{key.replace('/','__')}.png")
        ctx.close()
    relay=Relay(fail); relay.current="toggle"; relay.extra=boot; ctx=new_context(b, relay, "light"); pg=ctx.new_page(); watch(pg, relay)
    sign_in(pg, "/fansly-manager/home?creator=fa1")
    pg.goto(f"{BASE}/fansly-manager/home?creator=fa1", wait_until="load", timeout=90000)
    fr=mirror_frame(pg, "home/index")
    if not fr: fail("toggle", "no frame")
    else:
        check("toggle: light at start", [pg.evaluate("document.documentElement.dataset.theme"), marker(fr)], ["light", True])
        for want in ["dark","light"]:
            item=pg.get_by_role("button", name=f"{want.title()} mode")
            if not item.is_visible(): pg.get_by_role("button", name="Account menu").click()
            item.click(); pg.wait_for_timeout(800)
            fr=mirror_frame(pg, "home/index")
            check(f"toggle: after switching to {want}", [pg.evaluate("document.documentElement.dataset.theme"), marker(fr) if fr else None], [want, want=="light"])
            pg.screenshot(path=f"{SHOTS}/toggle-{want}.png")
    ctx.close(); b.close()
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("dark mode ok")
