import json, os, re, subprocess, sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from mocks import BASE, BUILT, ME, OVERLAY, Relay, href_of, is_state, key_of, mirror_frame, mirror_pages, new_context, reach, sign_in, watch
HERE=os.path.dirname(os.path.abspath(__file__)); REPO=os.path.dirname(os.path.dirname(HERE))
SHOTS=os.path.join(REPO,".scratch/fansly-mirror-check/render")
os.makedirs(SHOTS, exist_ok=True)
args=sys.argv[1:]
def switch(name): return name in args and not args.remove(name)
PLANT_IMG, PLANT_IP, PLANT_NAME, EMPTY = (switch(s) for s in ["--plant-remote-img","--plant-ip","--plant-name","--empty-table"])
def opt(name, default=None):
    if name in args and args.index(name)+1 < len(args): return args[args.index(name)+1]
    if default is None: sys.exit("usage: render.py --capture <capture dir> [--plan <mirror_plan.json>] [--plant-remote-img] [--plant-ip] [--plant-name] [--empty-table]")
    return default
CAPTURE=opt("--capture"); PLAN=opt("--plan", os.path.join(REPO,"fansly/capture/mirror_plan.json"))
PLANTS="".join(p for on, p in [(PLANT_IMG,'<img src="https://example.org/oi-plant.png" alt="">'),(PLANT_IP,"<p>198.51<span hidden>x</span>.100.7</p>"),(PLANT_NAME,"<p>velvet<span hidden>x</span>moth</p>")] if on)
pages=mirror_pages(EMPTY)
failures={}; texts=[]; edges=set(); unreachable={}
def fail(where, msg):
    failures.setdefault(where, []).append(msg); print("FAIL:", where, msg)
if not pages:
    print("pages checked: 0, failed: 0"); print("FAIL: the pages table lists no routable Fansly mirror page"); sys.exit(1)
relay=Relay(fail)
def plant(route, entry):
    if not PLANTS or urlsplit(route.request.url).path!=f"/fansly-mirror/pages/{pages[0]}.html": return False
    r=route.fetch(); entry["planted"]=True
    route.fulfill(response=r, body=r.text().replace("</body>", PLANTS+"</body>", 1)); return True
relay.extra=plant
MOCK_HANDLES=[f"@{m['username']}" for m in ME.values()]
def grab(pg, fr, where):
    for label, doc in [("top", pg), ("frame", fr)]:
        if not doc: continue
        text=doc.evaluate("document.body?.innerText ?? ''")
        for h in MOCK_HANDLES: text=text.replace(h, "")
        texts.append({"where":f"{where} ({label})","text":text})
def goto(pg, path):
    pg.goto(f"{BASE}{path}{'&' if '?' in path else '?'}creator=fa1", wait_until="load", timeout=90000)
WIRE="a.oi-state-link, a.oi-state-backdrop"
checked=0
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=new_context(b, relay); pg=ctx.new_page(); watch(pg, relay)
    sign_in(pg, f"{href_of(pages[0])}?creator=fa1")
    for key in pages:
        relay.current=key; checked+=1; path=href_of(key)
        goto(pg, path); fr=mirror_frame(pg, key)
        if not fr: fail(key, f"no frame on /fansly-mirror/pages/{key}.html (url {pg.url})"); pg.screenshot(path=f"{SHOTS}/{key.replace('/','__')}.png"); continue
        if urlsplit(pg.url).path!=path: fail(key, f"url {pg.url}, expected {path}")
        try: fr.wait_for_function("() => ![...document.querySelectorAll('[data-oi-avatar]')].some(e => e.localName === 'img' ? !(e.getAttribute('src') || '').startsWith('/img?') : !e.style.backgroundImage.startsWith('url(\"/img?'))", timeout=5000)
        except Exception: fail(key, "a [data-oi-avatar] is not on /img? after 5 s")
        pg.wait_for_timeout(500)
        if not fr.evaluate("document.body?.innerText.trim().length || 0"): fail(key, "empty page content")
        grab(pg, fr, key)
        pg.screenshot(path=f"{SHOTS}/{key.replace('/','__')}.png")
        wires=fr.evaluate(f"[...document.querySelectorAll('{WIRE}')].map(a => [a.className, a.getAttribute('href')])"); overlay=fr.evaluate(f"!!document.querySelector('{OVERLAY}')")
        print(json.dumps({"page":key,"url":pg.url.replace(BASE,""),"frame":fr.url.replace(BASE,""),"wires":len(wires)}))
        moved=False
        for i,(cls,href) in enumerate(wires):
            if moved: goto(pg, path); fr=mirror_frame(pg, key); moved=False
            if not fr: fail(key, f"no frame before wire {i}"); break
            target=href.split("?")[0]; el, at=reach(fr, WIRE, i)
            if "x" not in at:
                unreachable.setdefault(key, []).append(at["why"]); print(json.dumps({"page":key,"unreachable":cls,"href":href,"why":at["why"]}))
                if cls=="oi-state-backdrop" and overlay: fail(key, f"the page has an overlay ({OVERLAY}) but its backdrop {i} -> {href} is {at['why']}")
                continue
            try: moved=True; el.click(position={"x":at["x"],"y":at["y"]}, timeout=5000)
            except Exception as e: fail(key, f"{cls} {i} -> {href}: cannot click ({str(e).splitlines()[0][:120]})"); continue
            built=BUILT.get(target)
            if built:
                try: pg.wait_for_url(lambda u: urlsplit(u).path==built[0] and "creator=fa1" in urlsplit(u).query, timeout=15000)
                except Exception: pass
            to=None if built else mirror_frame(pg, key_of(target))
            got=urlsplit(pg.url)
            print(json.dumps({"page":key,"click":cls,"href":href,"url":pg.url.replace(BASE,""),"frame":to.url.replace(BASE,"") if to else None}))
            if built:
                if got.path!=built[0] or "creator=fa1" not in (got.query or ""): fail(key, f"{cls} {i} -> {href}: expected the Built page at {built[0]}, landed on {pg.url.replace(BASE,'')}")
                else: edges.add((path, target))
            elif got.path!=target or not to: fail(key, f"{cls} {i} -> {href}: landed on {pg.url.replace(BASE,'')} with frame {to.url if to else None}")
            elif "creator=fa1" not in (got.query or ""): fail(key, f"{cls} {i} -> {href}: lost ?creator= ({pg.url})")
            else: edges.add((path, target)); grab(pg, to, f"{key} -> {key_of(target)}")
    seen={href_of(k) for k in pages if not is_state(k)}; todo=list(seen)
    while todo:
        f=todo.pop()
        for t in {t for g,t in edges if g==f}-seen: seen.add(t); todo.append(t)
    for key in filter(is_state, pages):
        here=href_of(key); parent=here.rsplit("/",1)[0]
        if here not in seen: fail(key, "no chain of reachable wires from a non-State page opens this State")
        if (here,parent) not in edges: fail(key, f"no reachable wire goes back to {parent.replace('/fansly-manager','')}")
    for src,(want,label) in BUILT.items():
        relay.current=src; checked+=1
        goto(pg, src); pg.wait_for_timeout(2500)
        mirrors=pg.locator("iframe[src*='/fansly-mirror/']").count(); h1=pg.locator("h1", has_text=re.compile(f"^{re.escape(label)}$")).count()
        print(json.dumps({"landing":src,"url":pg.url.replace(BASE,""),"mirror iframes":mirrors,"h1":h1}))
        pg.screenshot(path=f"{SHOTS}/built{src.removeprefix('/fansly-manager').replace('/','__')}.png")
        if urlsplit(pg.url).path!=want or mirrors or not h1: fail(src, f"expected the Built page {label} at {want}; got {pg.url.replace(BASE,'')}, {mirrors} mirror iframe(s), {h1} '{label}' heading(s)")
    relay.current="teardown"; ctx.close(); b.close()
kinds=json.loads(subprocess.run(["node",os.path.join(HERE,"kinds.mjs"),"--capture",CAPTURE,"--plan",PLAN],input=json.dumps(texts),capture_output=True,text=True,check=True).stdout)
for hit in kinds: fail(hit["where"].split(" ")[0], f"rendered text kinds {', '.join(hit['kinds'])} in {hit['where']}")
print(f"rendered texts scanned: {len(texts)}")
why=[w for ws in unreachable.values() for w in ws]
print(f"unreachable wires: {len(why)} on {len(unreachable)} page(s) ({', '.join(f'{w} {why.count(w)}' for w in sorted(set(why))) or 'none'})")
with open(os.path.join(SHOTS,"requests.json"),"w") as f: json.dump(relay.log, f, indent=1)
print(f"requests: {len(relay.log)} logged, {sum('aborted' in e for e in relay.log)} aborted, {sum(bool(e.get('mocked')) for e in relay.log)} mocked; log {os.path.relpath(SHOTS, REPO)}/requests.json")
print(f"pages checked: {checked}, failed: {len(failures)}")
if failures:
    print("FAIL:", *[f"{k}: {m}" for k,ms in failures.items() for m in ms], sep="\n  "); sys.exit(1)
print("render ok")
