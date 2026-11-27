import os, sys, time
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright
from mocks import BASE, BUILT, M, OVERLAY, Relay, click_first, reach, href_of, is_state, key_of, links, mirror_frame, mirror_pages, new_context, sign_in, watch
HERE=os.path.dirname(os.path.abspath(__file__)); REPO=os.path.dirname(os.path.dirname(HERE))
SHOTS=os.path.join(REPO,".scratch/fansly-mirror-check/navigate")
os.makedirs(SHOTS, exist_ok=True)
args=sys.argv[1:]
FRAME_FLAG_OFF="--frame-flag-off" in args
STRICT="--strict" in args
failures=[]; steps=[0]
def fail(where, msg):
    failures.append(f"{where}: {msg}"); print("FAIL:", where, msg)
def lenient(where, msg): fail(where, msg) if STRICT else print(f"  {where}: {msg}")
def at(pg): u=urlsplit(pg.url); return u.path, parse_qs(u.query).get("creator", [None])[0]
PAGES=mirror_pages(); MIRROR={href_of(k) for k in PAGES}
PLAIN="a[target=_top]:not(.oi-state-link):not(.oi-state-backdrop)"
FIRST_BUILT="""async ([pages, built]) => { const out = []; for (const p of pages) { const d = new DOMParser().parseFromString(await (await fetch(p)).text(), 'text/html');
  if ([...d.querySelectorAll('a[target=_top]')].some(a => !a.closest('[data-oi-nav]') && built.includes(a.getAttribute('href').split('?')[0]))) out.push(p); } return out; }"""
def first_reachable(fr, cand): return next((i for i in cand if "x" in reach(fr, PLAIN, i)[1]), None)
HAS_OVERLAY=f"async p => {{ const d = new DOMParser().parseFromString(await (await fetch(p)).text(), 'text/html'); return !!d.querySelector('a.oi-state-backdrop') && !!d.querySelector('{OVERLAY}'); }}"
def to_page(k, ok):
    fr=mirror_frame(pg, k)
    if not fr: raise RuntimeError(f"no frame on {k}")
    fr.wait_for_function("() => [...document.querySelectorAll('a[href^=\"/fansly-manager/\"]')].every(a => a.getAttribute('href').includes('creator='))", timeout=10000)
    ls=links(fr, PLAIN)
    return fr, [i for i,l in enumerate(ls) if not l["nav"] and ok(l["path"])]
def frames(pg): return [f for f in pg.frames if "/fansly-mirror/" in f.url]
def step(pg, label, act, path, key, creator="fa1"):
    steps[0]+=1
    try: act(); path and pg.wait_for_function("p => location.pathname === p", arg=path, timeout=15000)
    except Exception as e: fail(label, str(e).splitlines()[0][:160])
    fr=mirror_frame(pg, key, timeout=15000) if key else None
    got, cr=at(pg); spa=pg.evaluate("window.__marker === 1")
    print(f"{label} -> {pg.url.replace(BASE,'')} | frame: {fr.url.replace(BASE,'') if fr else None} | spa: {spa}")
    if path and got!=path: fail(label, f"url {got}, expected {path}")
    if key and not fr: fail(label, f"no frame on {key}")
    if cr!=creator: fail(label, f"?creator={cr}, expected {creator}")
    if not spa: fail(label, "full page reload (client-side navigation lost)")
    return fr
def section(name, run):
    try: run()
    except Exception as e: fail(name, f"stopped: {str(e).splitlines()[0][:160]}")
def home():
    if at(pg)==(f"{M}/home","fa1") and mirror_frame(pg, "home/index", timeout=5000): return
    print(f"  back to {M}/home after a failed step (reload; the SPA marker is set again)")
    pg.goto(f"{BASE}{M}/home?creator=fa1", wait_until="load", timeout=90000); pg.evaluate("window.__marker = 1"); mirror_frame(pg, "home/index")
def gate(b, label, path, panel, setup):
    steps[0]+=1; relay=Relay(fail); relay.current=label; setup(relay)
    ctx=new_context(b, relay)
    if FRAME_FLAG_OFF and not relay.flag:
        ctx.add_init_script("""if (window === top) setInterval(() => { if (document.body?.innerText.includes('is not available') && !document.querySelector('iframe')) document.body.append(Object.assign(document.createElement('iframe'), { src: '/fansly-mirror/pages/home/index.html' })); }, 100);""")
    pg=ctx.new_page(); watch(pg, relay)
    sign_in(pg, f"{path}?creator=fa1"); pg.goto(f"{BASE}{path}?creator=fa1", wait_until="load", timeout=90000)
    try: pg.get_by_text(panel).first.wait_for(timeout=15000)
    except Exception: fail(label, f"no '{panel}' panel")
    pg.wait_for_timeout(1500)
    iframes=pg.locator("iframe").count(); me=[e["url"] for e in relay.log if urlsplit(e["url"]).path.endswith("/users/me")]
    print(f"{label} -> {pg.url.replace(BASE,'')} | panel: {pg.get_by_text(panel).count()} | iframes: {iframes} | /users/me requests: {len(me)}")
    pg.screenshot(path=f"{SHOTS}/{label.replace(' ','-')}.png")
    if iframes: fail(label, f"{iframes} iframe(s) mounted")
    if me: fail(label, f"/users/me requested: {me[0]}")
    ctx.close()
with sync_playwright() as p:
    b=p.chromium.launch(); relay=Relay(fail); ctx=new_context(b, relay); pg=ctx.new_page(); watch(pg, relay)
    sign_in(pg, f"{M}/home?creator=fa1")
    pg.goto(f"{BASE}{M}/home?creator=fa1", wait_until="load", timeout=90000); pg.evaluate("window.__marker = 1")
    relay.current="home"; steps[0]+=1
    fr=mirror_frame(pg, "home/index")
    if not fr: fail("home", "no frame"); sys.exit(1)
    try: fr.wait_for_function("() => [...document.querySelectorAll('[data-oi-nav]')].every(e => !e.checkVisibility())", timeout=10000)
    except Exception: pass
    rail=fr.evaluate("[...document.querySelectorAll('[data-oi-nav]')].map(e => e.checkVisibility())")
    shown=fr.evaluate("[...document.querySelectorAll('a.oi-state-link')].map(a => a.checkVisibility())")
    openers=lambda name: [i for i,l in enumerate(links(mirror_frame(pg, "home/index"), "a.oi-state-link")) if not l["nav"] and l["path"]==f"{M}/home/{name}"]
    top={name: [i for i in openers(name) if shown[i]] for name in ("state-avatar-menu","state-balance-menu")}
    print("rail visible:", rail, "| visible top bar openers outside the rail:", top)
    if not rail or any(rail): fail("home", f"rail not hidden ({rail})")
    if not all(top.values()): fail("home", f"top bar openers not shown ({top})")
    pg.screenshot(path=f"{SHOTS}/home.png")

    opener=lambda name: (lambda: click_first(mirror_frame(pg, "home/index"), "a.oi-state-link", openers(name)))
    def close(name):
        fr=mirror_frame(pg, f"home/{name}"); sel="a.oi-state-link"
        back=[i for i,l in enumerate(links(fr, sel)) if l["path"]==f"{M}/home"]
        toggle=fr.evaluate("sel => [...document.querySelectorAll(sel)].map(a => a.getAttribute('aria-label') === 'Toggle')", sel)
        try: i=click_first(fr, sel, [i for i in back if not toggle[i]])
        except RuntimeError:
            if not any(toggle[i] for i in back): raise
        else: return print(f"  {name}: clicked close control {i}; opener toggle(s) {[j for j in back if toggle[j]]} excluded")
        print(f"  {name}: no reachable close control in the State; the only way back is the opener toggle, clicked it")
        click_first(fr, sel, [i for i in back if toggle[i]])
    def menus():
        for name in ("state-avatar-menu","state-balance-menu"):
            home()
            step(pg, f"open {name.removeprefix('state-')}", opener(name), f"{M}/home/{name}", f"home/{name}")
            pg.screenshot(path=f"{SHOTS}/{name}.png")
            step(pg, "close it (Close)", lambda: close(name), f"{M}/home", "home/index")
        home()
        names=sorted((k.removeprefix("home/") for k in PAGES if k.startswith("home/") and is_state(k)), key=lambda n: (n not in ("state-avatar-menu","state-balance-menu"), n))
        hosted=[n for n in names if openers(n) and mirror_frame(pg, "home/index").evaluate(HAS_OVERLAY, f"/fansly-mirror/pages/home/{n}.html")]
        if not hosted:
            print(f"close it (backdrop): skipped, no home State opened from home has an overlay ({OVERLAY}) for its backdrop; a dropdown State needs only a way back"); return
        step(pg, f"open {hosted[0].removeprefix('state-')}", opener(hosted[0]), f"{M}/home/{hosted[0]}", f"home/{hosted[0]}")
        step(pg, "close it (backdrop)", lambda: click_first(mirror_frame(pg, f"home/{hosted[0]}"), "a.oi-state-backdrop", [0]), f"{M}/home", "home/index")
    section("menus", menus)

    def in_frame():
        relay.current="in-frame clicks"; home()
        other=lambda here: (lambda p: p in MIRROR and p!=here and not is_state(p))
        fr, cand=to_page("home/index", other(f"{M}/home"))
        ls=links(fr, PLAIN); i=first_reachable(fr, cand); x=ls[i]["path"] if i is not None else None
        print(f"first in-frame mirror link on home -> {x}")
        if not x: return fail("in-frame clicks", "no in-frame link from home to another mirror page")
        steps[0]+=1
        with ctx.expect_page(timeout=15000) as tab: click_first(fr, PLAIN, [i for i in cand if ls[i]["path"]==x], modifiers=["ControlOrMeta"])
        t=tab.value
        try: t.wait_for_url(f"**{x}?*", timeout=15000)
        except Exception: pass
        u=urlsplit(t.url)
        print(f"modified click {x} -> new tab {t.url.replace(BASE,'')} | this tab {pg.url.replace(BASE,'')}")
        if u.path!=x or parse_qs(u.query).get("creator")!=["fa1"]: fail("modified click", f"new tab on {t.url}, expected {x}?creator=fa1")
        if at(pg)!=(f"{M}/home","fa1"): fail("modified click", f"this tab moved to {pg.url}")
        t.close()
        xs=list(dict.fromkeys(ls[i]["path"] for i in cand if "x" in reach(fr, PLAIN, i)[1]))
        for x in xs:
            step(pg, f"click {x}", lambda: click_first(mirror_frame(pg, "home/index"), PLAIN, to_page("home/index", lambda p: p==x)[1]), x, key_of(x))
            fr, cand=to_page(key_of(x), other(x)); i=first_reachable(fr, cand); y=links(fr, PLAIN)[i]["path"] if i is not None else None
            if y:
                step(pg, f"click {y}", lambda: click_first(mirror_frame(pg, key_of(x)), PLAIN, to_page(key_of(x), lambda p: p==y)[1]), y, key_of(y))
                step(pg, "browser back", lambda: pg.go_back(), x, key_of(x))
                return step(pg, "browser back", lambda: pg.go_back(), f"{M}/home", "home/index")
            print(f"  {x} has no reachable in-frame link onward; trying the next page linked from home")
            step(pg, "browser back", lambda: pg.go_back(), f"{M}/home", "home/index")
        if not xs: return fail("in-frame clicks", "no reachable in-frame link from home to another mirror page")
        lenient("in-frame clicks", f"two-hop skipped: none of {xs} links onward outside the hidden rail; one hop and back checked for each")
    section("in-frame clicks", in_frame)

    def hand_off():
        relay.current="hand-off"; home(); key="home/index"
        fr, cand=to_page(key, lambda p: p in BUILT)
        if not cand:
            files=[f"/fansly-mirror/pages/{k}.html" for k in sorted(PAGES) if not is_state(k)]
            found=fr.evaluate(FIRST_BUILT, [files, list(BUILT)])
            if not found: return fail("hand-off", "no mirror page links to a Built page")
            for f in found:
                key=f.removeprefix("/fansly-mirror/pages/").removesuffix(".html")
                pg.goto(f"{BASE}{href_of(key)}?creator=fa1", wait_until="load", timeout=90000); pg.evaluate("window.__marker = 1")
                fr, cand=to_page(key, lambda p: p in BUILT)
                cand=[i for i in cand if "x" in reach(fr, PLAIN, i)[1]]
                if cand: break
            lenient("hand-off", f"home has no link to a Built page; starting from {href_of(key)}, the first mirror page with a reachable one")
        ls=links(fr, PLAIN); cand=[i for i in cand if "x" in reach(fr, PLAIN, i)[1]]
        cand.sort(key=lambda i: list(BUILT).index(ls[i]["path"]))
        src=ls[cand[0]]["path"] if cand else None
        if not src: return fail("hand-off", f"no in-frame link from {key} to a Built page")
        want, label=BUILT[src]
        step(pg, f"click {src} (Built)", lambda: click_first(mirror_frame(pg, key), PLAIN, [i for i in cand if ls[i]["path"]==src]), want, None)
        pg.wait_for_timeout(1500)
        mirrors=pg.locator("iframe[src*='/fansly-mirror/']").count(); h1=pg.get_by_role("heading", name=label, exact=True).count()
        print(f"  Built page: {h1} '{label}' heading(s), {mirrors} mirror iframe(s)")
        if mirrors or not h1: fail("hand-off", f"{h1} heading(s), {mirrors} mirror iframe(s)")
        pg.screenshot(path=f"{SHOTS}/handoff-scheduled.png")
    section("hand-off", hand_off)

    def switch():
        relay.current="switch"; steps[0]+=1
        pg.goto(f"{BASE}{M}/home?creator=fa1", wait_until="load", timeout=90000); fr=mirror_frame(pg, "home/index")
        if not fr: return fail("switch", "no home frame")
        try: fr.wait_for_function("() => /Nova Alpha|nova_a/.test(document.body?.textContent ?? '')", timeout=10000)
        except Exception: fail("switch", "A's name or handle never shown before the switch")
        relay.delay={"fb2":2000}
        pg.get_by_role("combobox", name="Creator").first.click(); pg.get_by_role("option", name="Nova B").first.click(); clicked=time.time()
        pg.wait_for_function("() => new URLSearchParams(location.search).get('creator') === 'fb2'", timeout=10000)
        seen_a=[]; beta_at=None; placeholder=False
        while time.time()-clicked < 4:
            for f in frames(pg):
                try: txt=f.evaluate("document.body?.textContent ?? ''")
                except Exception: continue
                if "Nova Alpha" in txt or "nova_a" in txt: seen_a.append(round(time.time()-clicked, 2))
                if "Your Model" in txt: placeholder=True
                if ("Nova Beta" in txt or "nova_b" in txt) and beta_at is None: beta_at=round(time.time()-clicked, 2)
            pg.wait_for_timeout(100)
        print(f"switch A -> B: url {pg.url.replace(BASE,'')} | A's handle seen at {seen_a[:5]} | placeholder while B loads: {placeholder} | B's name at {beta_at}s")
        pg.screenshot(path=f"{SHOTS}/switch-b.png")
        if seen_a: fail("switch", f"A's handle shown after the switch to B ({len(seen_a)} sample(s), first at {seen_a[0]}s)")
        if beta_at is None: fail("switch", "B's name or handle never shown")
        elif beta_at < 1.9: fail("switch", f"B's name at {beta_at}s, before its delayed /users/me (2 s) answered")
    section("switch", switch)
    relay.delay={}

    relay.current="bare landing"; steps[0]+=1
    pg.goto(f"{BASE}{M}?creator=fb2", wait_until="load", timeout=90000)
    try: pg.wait_for_function("p => location.pathname === p", arg=f"{M}/home", timeout=15000)
    except Exception: pass
    fr=mirror_frame(pg, "home/index", timeout=15000)
    print(f"{M}?creator=fb2 -> {pg.url.replace(BASE,'')} | frame: {fr.url.replace(BASE,'') if fr else None}")
    if at(pg)!=(f"{M}/home","fb2") or not fr: fail("bare landing", f"{pg.url}, expected {M}/home?creator=fb2 with the Homepage frame")
    ctx.close()

    def flag_off(r): r.flag=False
    def denied(r): r.pages=["/of-manager/profile"]
    gate(b, "flag off home", f"{M}/home", "is not available", flag_off)
    gate(b, "flag off thread", f"{M}/messages/thread", "is not available", flag_off)
    gate(b, "denied role home", f"{M}/home", "Your role does not allow this page", denied)
    gate(b, "denied role thread", f"{M}/messages/thread", "Your role does not allow this page", denied)
    b.close()
print(f"steps checked: {steps[0]}, failed: {len(failures)}")
if failures:
    print("FAIL:", *failures, sep="\n  "); sys.exit(1)
print("navigate ok")
