import json, os, subprocess
from urllib.parse import urlsplit

HERE=os.path.dirname(os.path.abspath(__file__))
BASE=f"http://localhost:{os.environ.get('PORT','3091')}"
M="/fansly-manager"
BUILT={f"{M}/scheduled":(f"{M}/scheduled","Scheduled Posts"),f"{M}/lists":(f"{M}/lists","Lists"),f"{M}/notifications":(f"{M}/notifications","Notifications"),f"{M}/statistics/earnings":(f"{M}/earning-statistics","Earning Statistics")}
OVERLAY=".back-drop, .cdk-overlay-backdrop"
def href_of(key):
    section, _, sub = key.partition("/")
    return f"{M}/{section}" if sub=="index" else f"{M}/{key}"
def key_of(path):
    rest=path.removeprefix(f"{M}/")
    return rest if "/" in rest else f"{rest}/index"
def is_state(key): return key.rsplit("/",1)[-1].startswith("state-")
def mirror_pages(empty=False):
    return json.loads(subprocess.run(["node","--no-warnings",os.path.join(HERE,"pages.mjs")]+(["--empty-table"] if empty else []),capture_output=True,text=True,check=True).stdout)
LOCAL={"localhost","127.0.0.1"}
RELAY=("/health","/admin/","/auth/","/chatter/","/api/","/img","/events","/push/","/lanes-panel","/t/","/share/","/p/","/.well-known/")
A={"id":"fa1","nickname":"Nova A","platform":"fansly","has_session":True,"is_active":True,"proxy_down":False}
B={"id":"fb2","nickname":"Nova B","platform":"fansly","has_session":True,"is_active":True,"proxy_down":False}
ME={"fa1":{"id":"fa1","username":"nova_a","name":"Nova Alpha","avatar":"https://img.invalid/a.jpg"},"fb2":{"id":"fb2","username":"nova_b","name":"Nova Beta","avatar":"https://img.invalid/b.jpg"}}
PNG=bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201a1e1c1f10000000049454e44ae426082")

class Relay:
    def __init__(self, fail):
        self.fail=fail; self.log=[]; self.current="setup"; self.extra=None
        self.flag=True; self.pages=None; self.delay={}

    def __call__(self, route):
        req=route.request; u=urlsplit(req.url); p=u.path
        entry={"method":req.method,"url":req.url,"page":self.current}; self.log.append(entry)
        if u.scheme in ("http","https") and u.hostname not in LOCAL:
            entry["aborted"]="off localhost"; self.fail(self.current, f"request off localhost aborted: {req.method} {req.url}"); return route.abort()
        if req.method!="GET":
            try: origin=urlsplit(req.frame.url).path
            except Exception: origin=""
            if origin.startswith("/fansly-mirror/") or p.startswith("/fansly-mirror/"):
                entry["aborted"]="non-GET from the mirror"; self.fail(self.current, f"non-GET request from the mirror aborted: {req.method} {req.url}"); return route.abort()
            if p.startswith(RELAY): entry["mocked"]=True; return route.fulfill(status=200, content_type="application/json", body="{}")
            return route.continue_()
        if self.extra and self.extra(route, entry): return
        if not p.startswith(RELAY): return route.continue_()
        entry["mocked"]=True
        if p.startswith("/img"): return route.fulfill(status=200, content_type="image/png", body=PNG)
        if p=="/events": return route.fulfill(status=200, content_type="text/event-stream", body="")
        if p=="/auth/me": body={"user_id":"u1","username":"tester","is_admin":False}
        elif p=="/chatter/me": body=None
        elif p=="/admin/employees": body={"employees":[{"id":1,"display_name":"Tim","color":"#a78bfa","is_active":True,"chatter_id":None}]}
        elif p=="/admin/accounts": body={"accounts":[A,B],"active_account_id":None}
        elif p=="/admin/settings/applied": body={"permissions":{"enforced":self.pages is not None,"pages":self.pages,"scope":"all"},"flags":{"fansly_manager":self.flag}}
        elif p=="/api/of/v2/users/me":
            who=req.headers.get("x-account-id"); body=ME.get(who)
            if who in self.delay: req.frame.page.wait_for_timeout(self.delay[who])
        else: body=[]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def watch(pg, relay):
    pg.on("pageerror", lambda e: relay.fail(relay.current, f"page error: {str(e)[:200]}"))
    pg.on("response", lambda r: urlsplit(r.url).hostname in LOCAL and r.status==404 and relay.fail(relay.current, f"localhost 404: {r.url}"))

def new_context(browser, relay, theme=None):
    ctx=browser.new_context(viewport={"width":1440,"height":900}, service_workers="block")
    ctx.add_init_script("localStorage.setItem('chatterly:platform','fansly')" + (f";localStorage.setItem('chatterly:theme','{theme}')" if theme else ""))
    ctx.route("**/*", relay)
    # never connect_to_server, so the socket stays a local mock; ws.close() in this handler deadlocks the sync API (1.63)
    ctx.route_web_socket(lambda url: urlsplit(url).hostname not in LOCAL, lambda ws: relay.fail(relay.current, f"websocket off localhost held before connecting: {ws.url}"))
    return ctx

def sign_in(pg, path):
    pg.goto(f"{BASE}{path}", wait_until="load", timeout=90000); pg.wait_for_timeout(3000)
    card=pg.get_by_text("Tim", exact=True)
    if card.count(): card.first.click(); pg.wait_for_timeout(2000)

def mirror_frame(pg, key, timeout=30000):
    want=f"/fansly-mirror/pages/{key}.html"
    try: pg.wait_for_function("p => [...document.querySelectorAll('iframe')].some(f => new URL(f.src, location.href).pathname === p && f.contentDocument?.readyState === 'complete')", arg=want, timeout=timeout)
    except Exception: return None
    for _ in range(20):
        el=pg.query_selector(f"iframe[src='{want}']"); fr=el and el.content_frame()
        if fr and urlsplit(fr.url).path==want: return fr
        pg.wait_for_timeout(250)
    return None

PROBE="""([sel, i, scroll]) => {
  const a = document.querySelectorAll(sel)[i];
  if (!a || !a.checkVisibility()) return {why: "hidden"};
  if (scroll) a.scrollIntoView({block: "center", inline: "center"});
  const r = a.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return {why: "zero-size"};
  const fs = a.classList.contains("oi-state-backdrop") ? [.995, .005, .5, .25, .75, .1, .9] : [.5, .2, .8];
  const clip = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  const fe = frameElement, box = fe?.getBoundingClientRect();
  const onTop = (x, y) => !fe || parent.document.elementFromPoint(box.left + fe.clientLeft + x, box.top + fe.clientTop + y) === fe;
  for (const fy of fs) for (const fx of fs) {
    const x = clip(r.left + r.width * fx, Math.max(r.left, 1), Math.min(r.right, innerWidth) - 1), y = clip(r.top + r.height * fy, Math.max(r.top, 1), Math.min(r.bottom, innerHeight) - 1);
    if (document.elementFromPoint(x, y)?.closest("a") === a && onTop(x, y)) return {x: x - r.left, y: y - r.top};
  }
  return {why: "covered", hover: {x: clip(r.width / 2, 0, innerWidth - r.left - 1), y: clip(r.height / 2, 0, innerHeight - r.top - 1)}};
}"""

def reach(fr, sel, i):
    loc=fr.locator(sel).nth(i); p=fr.evaluate(PROBE, [sel, i, True])
    for _ in range(8):
        if p.get("why")!="zero-size": break
        fr.wait_for_timeout(250); p=fr.evaluate(PROBE, [sel, i, True])
    if p.get("why")=="covered":
        try: loc.hover(position=p["hover"], force=True, timeout=3000)
        except Exception: return loc, p
        for _ in range(6):
            fr.wait_for_timeout(250); p=fr.evaluate(PROBE, [sel, i, False])
            if "x" in p: break
    return loc, p

def links(fr, sel):
    return fr.evaluate("sel => [...document.querySelectorAll(sel)].map(a => ({path: new URL(a.href, location.href).pathname, nav: !!a.closest('[data-oi-nav]')}))", sel)

def click_first(fr, sel, indices, **kw):
    for i in indices:
        loc, p=reach(fr, sel, i)
        if "x" in p: loc.click(position={"x":p["x"],"y":p["y"]}, timeout=5000, **kw); return i
    raise RuntimeError(f"no reachable {sel} among {len(indices)} candidate(s)")
